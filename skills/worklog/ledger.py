"""The ledger: one row per Claude Code session, read from its transcript and its subagents' transcripts, kept in
<DEV_DIR>/worklog/sessions.jsonl so a session still counts after Claude Code deletes its transcript.

A row: id, title, first prompt, cwd, branches, start and end, the ticket-shaped keys it names, whether it edited
files or reviewed a pull request, cost and tokens per model, subagent cost, context sizes, active minutes, the
prompts, interrupts and failed tool calls, and what it used (skills, slash commands, MCP servers, hooks, subagents).

A session's cost and tokens are Claude Code's own figures when ~/.claude.json still holds them, since they count
API calls the transcript leaves out; otherwise its replies priced at the list prices in models.json.
"""
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from settings import DATA, DEV

PRICING = json.loads((Path(__file__).resolve().parent / "models.json").read_text())
MODELS = PRICING["models"]
CLAUDE_STATE = Path.home() / ".claude.json"  # Claude Code's figures for the last session in each folder
STATE_TOKENS = {"in": "inputTokens", "out": "outputTokens", "write": "cacheCreationInputTokens",
                "read": "cacheReadInputTokens"}
WAIT = 30  # seconds; Claude Code writes ~/.claude.json about a second after the SessionEnd hook starts
BACKGROUND = "Background"  # Claude Code's own calls, on a model none of the session's replies used
LEDGER = DATA / "sessions.jsonl"
PROJECTS = Path.home() / ".claude" / "projects"
KEY_SHAPE = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}-\d+\b")  # the ledger keeps these; the report filters them
REVIEW_SKILLS = ("code-review", "pr-review")  # a skill or slash command of these names reviews a pull request
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/(?:[\w.-]+:)?(?:%s)</command-name>"
                    % "|".join(REVIEW_SKILLS))
COMMAND = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
INTERRUPT = "[Request interrupted by user"
SYNTHETIC = "<synthetic>"  # the model of the replies Claude Code writes itself: API errors, usage limits
TOKENS = {"in": "input_tokens", "out": "output_tokens", "write": "cache_creation_input_tokens",
          "read": "cache_read_input_tokens"}
SENT = ("in", "write", "read")  # the input a reply is sent: its context
BIG_CONTEXT = 100_000  # tokens; a session past this re-reads a large context on every reply
IDLE = 15  # minutes; a longer gap between two messages of a session is a break, not work


def is_review_skill(name):
    """Whether a skill or slash command reviews a pull request: one of REVIEW_SKILLS, with or without the prefix
    of the plugin it comes from."""
    return str(name).split(":")[-1] in REVIEW_SKILLS


def records(path):
    """The parsed lines of a transcript and of its subagent transcripts."""
    for file in [path, *sorted(path.with_suffix("").glob("subagents/*.jsonl"))]:
        with file.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass


def listed(model):
    """The models.json entry of a model id: the longest listed id it starts with, so a dated id still matches."""
    return next((MODELS[m] for m in sorted(MODELS, key=len, reverse=True) if (model or "").startswith(m)), None)


def name(model):
    """A model's name on the page: from models.json, else its family (claude-haiku-5-5 -> Haiku), else the id."""
    found = listed(model)
    if found:
        return found["name"]
    family = re.match(r"claude-([a-z]+)", model or "")
    return family[1].capitalize() if family else (model or "Unknown")


def price(usage):
    """What one reply cost in USD at the list prices in models.json, fast mode at the model's fast prices. An
    unlisted model is priced as default_model."""
    model = listed(usage.get("model")) or MODELS[PRICING["default_model"]]
    rates = model.get("fast", model["prices"]) if usage.get("speed") == "fast" else model["prices"]
    hour = (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
    tokens = {"input": usage.get("input_tokens") or 0, "output": usage.get("output_tokens") or 0,
              "cache_read": usage.get("cache_read_input_tokens") or 0,
              "cache_write_5m": (usage.get("cache_creation_input_tokens") or 0) - hour, "cache_write_1h": hour}
    return sum(n * rates[kind] for kind, n in tokens.items()) / 1e6


def measured():
    """{session id: {model id: {cost, tokens}}} for the sessions ~/.claude.json still holds: the last one in each
    folder. Claude Code counts every API call there, including the ones its transcripts leave out."""
    try:
        folders = json.loads(CLAUDE_STATE.read_text()).get("projects", {})
    except (OSError, ValueError):
        return {}
    return {folder["lastSessionId"]: {model: {"cost": use.get("costUSD") or 0,
                                              "tokens": {kind: use.get(field) or 0
                                                         for kind, field in STATE_TOKENS.items()}}
                                      for model, use in folder["lastModelUsage"].items()}
            for folder in folders.values() if folder.get("lastSessionId") and folder.get("lastModelUsage")}


def total(figures):
    return sum(f["cost"] for f in (figures or {}).values())


def settle(row, figures):
    """Gives a freshly read row Claude Code's figures: cost and tokens per model, with the subagent cost scaled by
    the same ratio. Only when they are at least the priced cost; lower ones are from a resumed run that counted
    only part of the session. A model none of the session's replies used shows as BACKGROUND."""
    if not figures or total(figures) < row["cost"]:
        return row
    replied = set(row["models"])
    models, tokens = defaultdict(float), {}
    for model, f in figures.items():
        shown = name(model) if name(model) in replied else BACKGROUND
        models[shown] += f["cost"]
        t = tokens.setdefault(shown, dict.fromkeys(TOKENS, 0))
        for kind in TOKENS:
            t[kind] += f["tokens"][kind]
    if row["cost"]:
        row["subagent_cost"] = round(row["subagent_cost"] * total(figures) / row["cost"], 4)
    row.update(models={m: round(usd, 4) for m, usd in models.items()}, cost=round(total(figures), 4),
               tokens_by_model=tokens, measured=figures)
    return row


def moment(stamp):
    """An ISO time as transcripts and GitHub write it (UTC, ending in Z) as a datetime."""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def local_day(stamp):
    """The day an ISO time falls on by this computer's clock, so a session just after midnight counts for that day
    and not for the day before in UTC."""
    return moment(stamp).astimezone().date().isoformat()


def active_minutes(stamps):
    """Minutes of work in a session: the gaps between its messages, leaving out each gap longer than IDLE."""
    times = sorted(moment(s) for s in stamps)
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
        """One transcript line: the session's facts, then a reply or a prompt. The summary Claude Code writes when
        it compacts the context is neither."""
        self.note(d)
        msg = d.get("message")
        if not isinstance(msg, dict):
            return
        self.place(d)
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        if d.get("type") == "assistant":
            self.reply(msg, blocks, bool(d.get("isSidechain")))
        elif d.get("type") == "user" and not (d.get("isMeta") or d.get("isCompactSummary")):
            self.said(blocks, bool(d.get("isSidechain")))

    def note(self, d):
        """The lines that are not messages: the title, hooks that ran, compactions."""
        if d.get("type") == "ai-title":
            self.row["title"] = d.get("aiTitle", "")
        hook = d.get("attachment")
        if isinstance(hook, dict) and str(hook.get("type", "")).startswith("hook_") and hook.get("hookName"):
            self.count("hook", hook["hookName"])
        self.compactions += d.get("subtype") == "compact_boundary"

    def place(self, d):
        """When and where a message ran: its time, folder and branch."""
        row = self.row
        row["start"] = row["start"] or d.get("timestamp") or ""
        if d.get("timestamp") and not d.get("isSidechain"):
            self.times.append(d["timestamp"])
        row["cwd"] = row["cwd"] or d.get("cwd") or ""
        if d.get("gitBranch") and d["gitBranch"] not in self.branches:
            self.branches.append(d["gitBranch"])

    def reply(self, msg, blocks, side):
        """A reply: its usage, once per reply although it is written once per content block, and its tool calls.
        A SYNTHETIC reply ran no model, so it has no usage to count."""
        if msg.get("usage") and msg.get("model") != SYNTHETIC:
            self.usage[msg.get("id")] = {**msg["usage"], "model": msg.get("model"), "side": side}
            if not side:
                self.contexts[msg.get("id")] = sum(msg["usage"].get(TOKENS[k]) or 0 for k in SENT)
        for b in blocks:
            if b.get("type") == "tool_use":
                self.tool(b.get("name"), b.get("input") or {})

    def said(self, blocks, side):
        """A user message: its text, slash commands, failed tool results, and whether it was a prompt or a stop."""
        said = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        self.text += said
        for command in COMMAND.findall("\n".join(said)):
            self.count("command", command)
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
        row["review"] |= (name == "Skill" and is_review_skill(args.get("skill", ""))
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
            m = name(u.get("model"))
            models[m] += price(u)
            t = tokens.setdefault(m, dict.fromkeys(TOKENS, 0))
            for kind, field in TOKENS.items():
                t[kind] += u.get(field) or 0
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
    """The SessionEnd hook's step: appends one session, with Claude Code's figures once ~/.claude.json names it
    (checked every second, up to WAIT). Appending is safe when sessions end at the same time; refresh folds the
    extra rows away later."""
    row = Session(path).result()
    if not row:
        return
    figures = None
    for _ in range(WAIT):
        figures = measured().get(row["id"])
        if figures:
            break
        time.sleep(1)
    settle(row, figures)
    DATA.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as out:
        out.write(json.dumps(row) + "\n")


def refresh():
    """Every session: the ledger's rows, updated from each transcript still on disk, with the larger of the
    figures the row kept and the ones ~/.claude.json holds now. Rewrites the ledger with one row per session (the
    newest), so it grows with sessions, not with reports."""
    rows = {}
    if LEDGER.exists():
        with LEDGER.open() as lines:
            for line in lines:
                if line.strip():
                    row = json.loads(line)
                    rows[row["id"]] = row
    found = measured()
    for path in sorted(PROJECTS.glob("*/*.jsonl")):
        row = Session(path).result()
        if row:
            kept = rows.get(row["id"], {}).get("measured")
            rows[row["id"]] = settle(row, max(kept, found.get(row["id"]), key=total))
    DATA.mkdir(parents=True, exist_ok=True)
    fresh = LEDGER.with_suffix(".tmp")
    fresh.write_text("".join(json.dumps(r) + "\n" for r in rows.values()))
    os.replace(fresh, LEDGER)
    return list(rows.values())


def cost(row):
    """A row recorded before costs were kept is priced as default_model with 1-hour cache writes."""
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
