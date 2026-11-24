"""The ledger: one row per Claude Code session, read from its transcript and its subagents' transcripts, kept in
<DEV_DIR>/worklog/sessions.jsonl so a session still counts after Claude Code deletes its transcript.

A row: id, title, first prompt, cwd, branches, start and end, the ticket-shaped keys it names, whether it edited
files or reviewed a pull request, cost and tokens per model, subagent cost, context sizes, active minutes, the
prompts, interrupts and failed tool calls, and what it used (skills, slash commands, MCP servers, hooks, subagents).
"""
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from config import DATA, DEV

LEDGER = DATA / "sessions.jsonl"
PROJECTS = Path.home() / ".claude" / "projects"
KEY_SHAPE = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}-\d+\b")  # the ledger keeps these; the report filters them
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/code-review")
COMMAND = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
INTERRUPT = "[Request interrupted by user"
TOKENS = {"in": "input_tokens", "out": "output_tokens", "write": "cache_creation_input_tokens",
          "read": "cache_read_input_tokens"}
SENT = ("in", "write", "read")  # the input a reply is sent: its context
BIG_CONTEXT = 100_000  # tokens; a session past this re-reads a large context on every reply
IDLE = 15  # minutes; a longer gap between two messages of a session is a break, not work
# API list prices in USD per million tokens: input, output, cache read. A cache write costs 1.25x input
# for 5 minutes, 2x for 1 hour; fast mode costs 2x. An id not listed is priced as claude-opus-5-5.
PRICES = {"claude-opus-5-5": (4, 20, 0.20), "claude-opus-5": (5, 25, 0.50), "claude-opus-4": (5, 25, 0.50),
          "claude-sonnet-5-5": (2, 10, 0.10), "claude-sonnet-5": (2, 10, 0.20), "claude-sonnet-4": (3, 15, 0.30)}


def records(path):
    """The parsed lines of a transcript and of its subagent transcripts."""
    for file in [path, *sorted(path.with_suffix("").glob("subagents/*.jsonl"))]:
        with file.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass


def price(usage):
    """What one reply cost in USD at API list prices."""
    model = usage.get("model") or ""
    rates = next((PRICES[m] for m in sorted(PRICES, key=len, reverse=True) if model.startswith(m)),
                 PRICES["claude-opus-5-5"])
    hour = (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
    minutes = (usage.get("cache_creation_input_tokens") or 0) - hour
    tokens = [(usage.get("input_tokens") or 0) + 1.25 * minutes + 2 * hour,
              usage.get("output_tokens") or 0, usage.get("cache_read_input_tokens") or 0]
    return sum(n * rate for n, rate in zip(tokens, rates)) / 1e6 * (2 if usage.get("speed") == "fast" else 1)


def family(model):
    """claude-opus-5-5 -> Opus; an id that is not a Claude model is kept as it is."""
    found = re.match(r"claude-([a-z]+)", model or "")
    return found[1].capitalize() if found else (model or "Unknown")


def active_minutes(stamps):
    """Minutes of work in a session: the gaps between its messages, leaving out each gap longer than IDLE."""
    times = sorted(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps)
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
    return round(sum(g for g in gaps if g <= IDLE), 1)


class Session:
    """Reads one transcript, with its subagent transcripts, into a ledger row."""

    def __init__(self, path):
        self.row = {"id": path.stem, "title": "", "prompt": "", "cwd": "", "start": "",
                    "review": False, "edits": False, "used": {}}
        self.usage, self.contexts, self.text, self.branches, self.commands = {}, {}, [], [], []
        self.compactions, self.times = 0, []
        self.prompts = self.interrupts = self.errors = 0
        for d in records(path):
            self.read(d)

    def count(self, kind, name):
        used = self.row["used"].setdefault(kind, {})
        used[name] = used.get(name, 0) + 1

    def read(self, d):
        row = self.row
        if d.get("type") == "ai-title":
            row["title"] = d.get("aiTitle", "")
        hook = d.get("attachment")
        if isinstance(hook, dict) and str(hook.get("type", "")).startswith("hook_") and hook.get("hookName"):
            self.count("hook", hook["hookName"])
        self.compactions += d.get("subtype") == "compact_boundary"
        msg = d.get("message")
        if not isinstance(msg, dict):
            return
        side = bool(d.get("isSidechain"))
        row["start"] = row["start"] or d.get("timestamp") or ""
        if d.get("timestamp") and not side:
            self.times.append(d["timestamp"])
        row["cwd"] = row["cwd"] or d.get("cwd") or ""
        if d.get("gitBranch") and d["gitBranch"] not in self.branches:
            self.branches.append(d["gitBranch"])
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        if d.get("type") == "assistant":
            if msg.get("usage"):  # a reply is written once per content block, each time with the same usage
                self.usage[msg.get("id")] = {**msg["usage"], "model": msg.get("model"), "side": side}
                if not side:
                    self.contexts[msg.get("id")] = sum(msg["usage"].get(TOKENS[k]) or 0 for k in SENT)
            for b in blocks:
                if b.get("type") == "tool_use":
                    self.tool(b.get("name"), b.get("input") or {})
        elif d.get("type") == "user" and not d.get("isMeta"):
            said = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            self.text += said
            for name in COMMAND.findall("\n".join(said)):
                self.count("command", name)
            self.errors += sum(b.get("type") == "tool_result" and bool(b.get("is_error")) for b in blocks)
            if any(INTERRUPT in t for t in said):
                self.interrupts += 1
            elif not side and any(t.strip() and not t.lstrip().startswith("<") for t in said):
                self.prompts += 1

    def tool(self, name, args):
        row = self.row
        if name == "Skill":
            self.count("skill", args.get("skill") or "?")
        elif name in ("Agent", "Task"):
            self.count("agent", args.get("subagent_type") or "general-purpose")
        elif name.startswith("mcp__"):
            self.count("mcp", name.split("__")[1])
        elif name == "Bash":
            self.commands.append(args.get("command", ""))
        row["edits"] |= name in ("Edit", "Write", "NotebookEdit")
        row["review"] |= (name == "Skill" and args.get("skill") == "code-review"
                          or name == "Bash" and bool(REVIEW.search(args.get("command", ""))))

    def result(self):
        """The ledger row, or None when no model ran."""
        if not self.usage:
            return None
        row, said = self.row, "\n".join(self.text)
        commands = "\n".join(self.commands)
        row["prompt"] = next((t.strip()[:200] for t in self.text
                              if t.strip() and not t.lstrip().startswith(("<", INTERRUPT))), "")
        row["branches"] = self.branches
        row["keys"] = list(dict.fromkeys(k.upper() for k in KEY_SHAPE.findall(
            " ".join(self.branches) + "\n" + said + "\n" + commands)))
        row["review"] |= bool(REVIEW.search(said))
        models, tokens = defaultdict(float), {}
        for u in self.usage.values():
            m = family(u.get("model"))
            models[m] += price(u)
            t = tokens.setdefault(m, dict.fromkeys(TOKENS, 0))
            for name, field in TOKENS.items():
                t[name] += u.get(field) or 0
        row["models"] = {m: round(usd, 4) for m, usd in models.items()}
        row["cost"] = round(sum(models.values()), 4)
        row["tokens_by_model"] = tokens
        row["subagent_cost"] = round(sum(price(u) for u in self.usage.values() if u["side"]), 4)
        sizes = list(self.contexts.values()) or [0]
        row["context"] = {"peak": max(sizes), "avg": sum(sizes) // len(sizes), "compactions": self.compactions}
        row["active"] = active_minutes(self.times)
        row["end"] = max(self.times, default=row["start"])
        row.update(prompts=self.prompts, interrupts=self.interrupts, errors=self.errors)
        return row


def record(path):
    """The SessionEnd hook's step: appends one session. Appending is safe when sessions end at the same time;
    refresh folds the extra rows away later."""
    row = Session(path).result()
    if row:
        DATA.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as out:
            out.write(json.dumps(row) + "\n")


def refresh():
    """Every session: the ledger's rows, updated from each transcript still on disk. Rewrites the ledger with one
    row per session (the newest), so it grows with sessions, not with reports."""
    rows = {}
    if LEDGER.exists():
        with LEDGER.open() as lines:
            for line in lines:
                if line.strip():
                    row = json.loads(line)
                    rows[row["id"]] = row
    for path in sorted(PROJECTS.glob("*/*.jsonl")):
        row = Session(path).result()
        if row:
            rows[row["id"]] = row
    DATA.mkdir(parents=True, exist_ok=True)
    fresh = LEDGER.with_suffix(".tmp")
    fresh.write_text("".join(json.dumps(r) + "\n" for r in rows.values()))
    os.replace(fresh, LEDGER)
    return list(rows.values())


def cost(row):
    """A row recorded before costs were kept is priced as claude-opus-5-5 with 1-hour cache writes."""
    if "cost" in row:
        return row["cost"]
    t = row["tokens"]
    return price({"input_tokens": t["in"], "output_tokens": t["out"], "cache_read_input_tokens": t["cache_read"],
                  "cache_creation_input_tokens": t["cache_write"],
                  "cache_creation": {"ephemeral_1h_input_tokens": t["cache_write"]}})


def models_of(row):
    """{model family: cost}; a row recorded before these were kept is all Unknown."""
    return row.get("models") or {"Unknown": cost(row)}


def repo_of(row):
    """The repo folder a session ran in: the first folder under DEV_DIR, else the last part of its path."""
    cwd = Path(row["cwd"] or "/")
    return cwd.relative_to(DEV).parts[0] if cwd.is_relative_to(DEV) and cwd != DEV else cwd.name or "/"
