#!/usr/bin/env python3
"""Keeps a ledger of Claude Code sessions and writes a one-page work summary from it.

  worklog.py record                            SessionEnd hook: appends the session on stdin to the ledger
  worklog.py start                             SessionStart hook: in a work repo on a branch with no ticket key,
                                               tells Claude to ask which ticket the session is for
  worklog.py report [period] [--no-cost] [--no-usage]
      Records every transcript still in ~/.claude/projects, writes <DEV_DIR>/worklog/report.html and
      report.csv (the tickets), opens the page and prints the counts.
      period: empty for this month, last-month, or a first day YYYY-MM-DD.
  worklog.py unmapped [period]                 prints, as JSON, the sessions the rules gave no ticket and the
                                               period's tickets, for /worklog to choose from
  worklog.py map SESSION KEY [SESSION KEY...]  saves a ticket for a session the rules gave none

Data: <DEV_DIR>/worklog, with sessions.jsonl (the ledger), jira.json (the issue cache) and mapped.json
(the tickets chosen with map).
github.py and jira.py fetch pull requests and issues; each runs on its own too.
"""
# Settings: set your own on your machine; the repo keeps these empty.
JIRA_URL = ""  # such as "https://example.atlassian.net"; ticket keys then link to <JIRA_URL>/browse/<key>
JIRA_PREFIXES = []  # every Jira project whose keys you use, such as ["ABC"] for ABC-123
SUPPORT_PREFIXES = []  # the prefixes of support tickets
EXCLUDE_REPOS = []  # repos (folder or GitHub name) the report leaves out, such as personal ones
DEV_DIR = "~/dev"  # the folder that holds the repos; the data lives in <DEV_DIR>/worklog

import csv
import html
import json
import os
import re
import subprocess
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Template

import github
import jira

HERE = Path(__file__).resolve().parent
DEV = Path(DEV_DIR).expanduser()
DATA = DEV / "worklog"
LEDGER = DATA / "sessions.jsonl"
MAPPED = DATA / "mapped.json"
PREFIXES = "|".join(re.escape(p) for p in JIRA_PREFIXES)
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b", re.I) if PREFIXES else re.compile(r"[^\s\S]")  # never matches
KEY_SHAPE = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}-\d+\b")  # the ledger keeps these; the report filters by KEY
SUPPORT = {p.upper() for p in SUPPORT_PREFIXES}
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/code-review")
COMMAND = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
PR_URL = re.compile(r"https://github\.com/[\w.-]+/([\w.-]+)/pull/(\d+)")
PR_CMD = re.compile(r"gh pr (?:diff|review|checkout|view) +#?(\d+)\b(?:.*?(?:--repo|-R)[ =][\w.-]+/([\w.-]+))?")
ALERT = re.compile(r"https://[\w-]+\.pagerduty\.com/", re.I)
TOKENS = {"in": "input_tokens", "out": "output_tokens", "write": "cache_creation_input_tokens",
          "read": "cache_read_input_tokens"}
SENT = ("in", "write", "read")  # the input a reply is sent: its context
BIG_CONTEXT = 100_000  # tokens
# API list prices in USD per million tokens: input, output, cache read. A cache write costs 1.25x input
# for 5 minutes, 2x for 1 hour; fast mode costs 2x. An id not listed is priced as claude-opus-5-5.
PRICES = {"claude-opus-5-5": (4, 20, 0.20), "claude-opus-5": (5, 25, 0.50), "claude-opus-4": (5, 25, 0.50),
          "claude-sonnet-5-5": (2, 10, 0.10), "claude-sonnet-5": (2, 10, 0.20), "claude-sonnet-4": (3, 15, 0.30)}
MODEL_SLOTS = {"Opus": 1, "Fable": 7, "Sonnet": 2, "Haiku": 3}  # a model keeps its colour on every page; others grey
STATUS = {"merged": "✓ Merged", "closed": "✕ Closed, not merged", "open": "○ Open", "draft": "○ Draft"}
SHOW_COST = True  # report --no-cost turns it off
SHOW_USAGE = True  # report --no-usage turns it off


# ---- ledger

def records(path):
    """The parsed lines of a transcript and of its subagent transcripts."""
    for file in [path, *sorted(path.with_suffix("").glob("subagents/*.jsonl"))]:
        for line in file.open(encoding="utf-8", errors="replace"):
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


class Session:
    """Reads one transcript, with its subagent transcripts, into a ledger row."""

    def __init__(self, path):
        self.row = {"id": path.stem, "title": "", "prompt": "", "cwd": "", "start": "",
                    "review": False, "edits": False, "used": {}}
        self.usage, self.contexts, self.text, self.branches, self.commands = {}, {}, [], [], []
        self.compactions = 0
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
        row["start"] = row["start"] or d.get("timestamp") or ""
        row["cwd"] = row["cwd"] or d.get("cwd") or ""
        if d.get("gitBranch") and d["gitBranch"] not in self.branches:
            self.branches.append(d["gitBranch"])
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        if d.get("type") == "assistant":
            if msg.get("usage"):  # a reply is written once per content block, each time with the same usage
                self.usage[msg.get("id")] = {**msg["usage"], "model": msg.get("model"), "side": bool(d.get("isSidechain"))}
                if not d.get("isSidechain"):
                    self.contexts[msg.get("id")] = sum(msg["usage"].get(TOKENS[k]) or 0 for k in SENT)
            for b in blocks:
                if b.get("type") == "tool_use":
                    self.tool(b.get("name"), b.get("input") or {})
        elif d.get("type") == "user" and not d.get("isMeta"):
            said = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            self.text += said
            for name in COMMAND.findall("\n".join(said)):
                self.count("command", name)

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
        row["prompt"] = next((t.strip()[:200] for t in self.text if t.strip() and not t.lstrip().startswith("<")), "")
        row["branches"] = self.branches
        row["keys"] = list(dict.fromkeys(k.upper() for k in KEY_SHAPE.findall(
            " ".join(self.branches) + "\n" + said + "\n" + commands)))
        row["pulls"] = pulls_named(said + "\n" + commands)
        row["alert"] = bool(ALERT.search(said))
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
        return row


def pulls_named(text):
    """The pull requests a text names, as 'repo#number', or '#number' when a gh command gives no repo."""
    found = [f"{repo}#{n}" for repo, n in PR_URL.findall(text)]
    found += [f"{repo}#{n}" for n, repo in PR_CMD.findall(text)]
    return list(dict.fromkeys(found))


def append(paths):
    DATA.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as out:
        for path in paths:
            row = Session(path).result()
            if row:
                out.write(json.dumps(row) + "\n")


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
    cwd = Path(row["cwd"] or "/")
    return cwd.relative_to(DEV).parts[0] if cwd.is_relative_to(DEV) and cwd != DEV else cwd.name or "/"


# ---- Jira and GitHub

class Jira:
    """Jira issues through jira.py, cached in jira.json. Stops asking after the first failure."""

    def __init__(self):
        file = DATA / "jira.json"
        self.cache, self.down = json.loads(file.read_text()) if file.exists() else {}, not PREFIXES

    def ask(self, call, *args):
        if self.down:
            return None
        try:
            return call(*args)
        except Exception as err:  # CLI missing, not logged in, unknown key, output that is not JSON
            print(f"note: Jira is not answering ({err}); tickets are shown by key only\n", file=sys.stderr)
            self.down = True

    def issue(self, key):
        """Summary, type, whether it is a sub-task, and parent of one issue."""
        if "subtask" not in self.cache.get(key, {}):
            found = self.ask(jira.issue, key)
            if not found:
                return {}
            self.cache[key] = found
        return self.cache[key]

    def top(self, key):
        """The ticket the report shows for a key: a sub-task's parent, else the key itself."""
        issue = self.issue(key) if key else {}
        return issue["parent"] if issue.get("subtask") and issue.get("parent") else key

    def pick(self, keys):
        """One key for the keys a session or pull request names: the first main ticket, else the first
        sub-task. An epic is taken only when nothing else is named."""
        epics = [k for k in keys if self.issue(k).get("type", "").lower() == "epic"]
        rest = [k for k in keys if k not in epics]
        main = next((k for k in rest if not self.issue(k).get("subtask")), rest[0] if rest else "")
        return main or (epics[0] if epics else "")

    def resolved(self, since, until):
        return self.ask(jira.resolved, since, until) or []


pull_requests = github.pull_requests  # demo and tests swap it


# ---- sorting the sessions

def is_support(key):
    return key.split("-")[0].upper() in SUPPORT


def keys_of(row):
    """The ticket keys a session names, filtered by the prefixes configured now; its branches are scanned
    again, so a prefix added later also counts for sessions recorded before."""
    found = [k.upper() for k in row["keys"] + KEY.findall(" ".join(row["branches"]))]
    return [k for k in dict.fromkeys(found) if KEY.fullmatch(k)]


def mapped():
    """{session id: ticket key} saved with map."""
    return json.loads(MAPPED.read_text()) if MAPPED.exists() else {}


def ticket(row, by_branch, issues, chosen):
    """The key a session counts for: a support key it names, else Jira.pick of its keys, else the ticket of a
    pull request opened from one of its branches, else the key saved for it with map. A branch name alone
    settles it when it names one ticket; otherwise the repo must match too."""
    keys = keys_of(row)
    support = [k for k in keys if is_support(k)]
    if support:
        return support[0]
    if keys:
        return issues.pick(keys)
    for b in row["branches"]:
        if (repo_of(row), b) in by_branch:
            return by_branch[repo_of(row), b]
        if len(by_branch.get(b, ())) == 1:
            return next(iter(by_branch[b]))
    return chosen.get(row["id"], "")


def reviewed_pr(row, reviewed):
    """The reviewed pull request a review session names: by repo and number, or by number alone when only one
    reviewed pull request has it; None otherwise. The repo folder says nothing: reviews often run in a scratch
    checkout."""
    refs = {f"{m[1]}#{m[2]}": pr for pr in reviewed if (m := PR_URL.search(pr["url"]))}
    for ref in row.get("pulls", []):
        found = [pr for r, pr in refs.items() if r == ref or ref.startswith("#") and r.endswith(ref)]
        if len(found) == 1:
            return found[0]
    return None


class Work:
    """The days, cost, cost per model and pull requests of one ticket or sub-task."""

    def __init__(self, key, issues):
        issue = issues.issue(key)
        self.key, self.summary, self.type = key, issue.get("summary", ""), issue.get("type", "")
        self.days, self.cost, self.models, self.prs = set(), 0.0, defaultdict(float), []

    def add(self, row):
        self.days.add(row["start"][:10])
        self.cost += cost(row)
        for model, usd in models_of(row).items():
            self.models[model] += usd


class Ticket:
    """A ticket: its own work, its sub-tasks' work, and the repos of both. Its cost includes the sub-tasks."""

    def __init__(self, key, issues):
        self.key, self.issues, self.own, self.subs, self.repos = key, issues, Work(key, issues), {}, {}
        self.resolved = False

    def part(self, key):
        if key == self.key:
            return self.own
        if key not in self.subs:
            self.subs[key] = Work(key, self.issues)
        return self.subs[key]

    @property
    def cost(self):
        return self.own.cost + sum(s.cost for s in self.subs.values())

    @property
    def works(self):
        """Its own work, then its sub-tasks, the most expensive first."""
        return [self.own] + sorted(self.subs.values(), key=lambda w: -w.cost)


def load(since, until):
    """The sessions that started in the period, the last row of each, and the cost of those in exclude_repos."""
    rows = {}
    for line in LEDGER.open():
        row = json.loads(line)
        rows[row["id"]] = row  # a session is recorded more than once; the last row wins
    rows = sorted((r for r in rows.values() if since <= r["start"][:10] <= until), key=lambda r: r["start"])
    excluded = sum(cost(r) for r in rows if repo_of(r) in EXCLUDE_REPOS)
    return [r for r in rows if repo_of(r) not in EXCLUDE_REPOS], excluded


def month_before(day_):
    """The same day a month earlier, or the month's last day when it has no such day."""
    d = date.fromisoformat(day_)
    first = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
    last = d.replace(day=1) - timedelta(days=1)
    return str(first.replace(day=min(d.day, last.day)))


def measures(rows):
    """What the sessions cost and how efficiently, from the ledger alone: tokens per model, cache hit rate
    (cache reads over all input), and the shares of cost in sessions past BIG_CONTEXT, in subagents and in
    sessions that changed nothing. Rows recorded before tokens were kept count for cost only."""
    total = sum(cost(r) for r in rows) or 0.0
    tokens = defaultdict(lambda: dict.fromkeys(TOKENS, 0))
    for r in rows:
        for model, t in r.get("tokens_by_model", {}).items():
            for name in TOKENS:
                tokens[model][name] += t[name]
    sent = sum(t[k] for t in tokens.values() for k in SENT)

    def share(field, part):
        """A share of cost over the rows that recorded field; None when none did."""
        known = [r for r in rows if field in r]
        whole = sum(cost(r) for r in known)
        return sum(part(r) for r in known) / whole if whole else None
    return {"cost": total, "sessions": len(rows), "tokens": {m: t for m, t in tokens.items() if any(t.values())},
            "cache_hit": sum(t["read"] for t in tokens.values()) / sent if sent else None,
            "big": share("context", lambda r: cost(r) if r["context"]["peak"] > BIG_CONTEXT else 0),
            "subagents": share("subagent_cost", lambda r: r["subagent_cost"]),
            "idle": share("edits", lambda r: 0 if r["edits"] or r["review"] or r["alert"] else cost(r))}


def collect(since, until):
    """Everything the report shows, as plain data. Every session lands in exactly one place."""
    append(sorted((Path.home() / ".claude" / "projects").glob("*/*.jsonl")))
    rows, excluded = load(since, until)
    if not rows:
        sys.exit(f"no sessions from {day(since)} to {day(until)}")
    prs = {kind: [pr for pr in found if pr["repo"] not in EXCLUDE_REPOS]
           for kind, found in pull_requests(since, until).items()}
    issues, tickets, incidents = Jira(), {}, []
    other, unmapped = defaultdict(lambda: {"days": set(), "cost": 0.0}), []
    reviews = {"cost": 0.0, "unlinked": 0.0}

    def on(key):
        top = issues.top(key)
        if top not in tickets:
            tickets[top] = Ticket(top, issues)
        return tickets[top]

    chosen = mapped()
    by_branch = {}  # (repo, branch): ticket, and branch: {tickets of the pull requests from a branch of that name}
    for pr in prs["opened"]:
        pr["sub"] = issues.pick(list(dict.fromkeys(k.upper() for k in KEY.findall(pr["text"]))))
        pr["ticket"] = issues.top(pr["sub"])
        if pr["ticket"]:
            by_branch[pr["repo"], pr["branch"]] = pr["ticket"]
            by_branch.setdefault(pr["branch"], set()).add(pr["ticket"])
    for pr in prs["reviewed"]:
        pr["cost"] = 0.0
    for row in rows:
        named = ticket(row, by_branch, issues, chosen)
        if row["alert"]:
            incidents.append({"date": row["start"][:10], "what": row["title"] or row["prompt"] or "(no title)",
                              "ticket": issues.top(named), "repo": repo_of(row), "cost": cost(row)})
        elif named:
            t = on(named)
            t.part(named).add(row)
            t.repos[repo_of(row)] = None
        elif row["review"] and not row["edits"]:
            reviews["cost"] += cost(row)
            pr = reviewed_pr(row, prs["reviewed"])
            if pr:
                pr["cost"] += cost(row)
            else:
                reviews["unlinked"] += cost(row)
        else:
            other[repo_of(row)]["days"].add(row["start"][:10])
            other[repo_of(row)]["cost"] += cost(row)
            unmapped.append(row)
    for pr in prs["opened"]:
        if pr["ticket"]:
            t = on(pr["sub"])
            t.part(pr["sub"]).prs.append(pr)
            t.repos[pr["repo"]] = None
    for key in issues.resolved(since, until):  # a resolved sub-task does not resolve its parent
        t = on(key)
        t.part(key).resolved = True
        t.resolved |= key == t.key
    if issues.cache:
        (DATA / "jira.json").write_text(json.dumps(issues.cache, indent=1))
    return {"since": since, "until": until, "incidents": incidents, "other": other, "unmapped": unmapped, "prs": prs,
            "reviews": reviews, "sessions": len(rows), "total": sum(cost(r) for r in rows), "excluded": excluded,
            "usage": usage_of(rows),
            "measures": measures(rows), "before": measures(load(month_before(since), month_before(until))[0]),
            "tickets": [t for t in tickets.values() if not is_support(t.key)],
            "support": [t for t in tickets.values() if is_support(t.key)]}


def most_used(counts):
    """{name: [uses, sessions]} as (name, [uses, sessions]) pairs, most used first, then by name."""
    return sorted(counts.items(), key=lambda item: (-item[1][0], item[0]))


def usage_of(rows):
    """{kind: {name: [uses, sessions]}} for skills, plugins, MCP servers, hooks and subagents, plus the context
    sizes. A slash command is a skill when a skill of that name is installed or it names a plugin skill. A plugin
    is the part before ':' in a skill name, or <plugin> in an MCP server named plugin_<plugin>_<server>."""
    folder = Path.home() / ".claude" / "skills"
    installed = {p.name for p in folder.iterdir()} if folder.is_dir() else set()
    found = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    measured = [r for r in rows if "used" in r]  # rows recorded before these were kept have none
    for r in measured:
        used = r["used"]
        skills = dict(used.get("skill", {}))
        for name, n in used.get("command", {}).items():
            if name in installed or ":" in name:
                skills[name] = skills.get(name, 0) + n
        plugins = defaultdict(int)
        for name, n in skills.items():
            if ":" in name:
                plugins[name.split(":")[0]] += n
        for name, n in used.get("mcp", {}).items():
            if name.startswith("plugin_"):
                plugins[name.split("_")[1]] += n
        for kind, counts in (("skill", skills), ("plugin", plugins), ("mcp", used.get("mcp", {})),
                             ("hook", used.get("hook", {})), ("agent", used.get("agent", {}))):
            for name, n in counts.items():
                found[kind][name][0] += n
                found[kind][name][1] += 1
    peaks = [r["context"]["peak"] for r in measured]
    n = max(len(measured), 1)
    found["context"] = {"sessions": len(measured), "of": len(rows),
                        "avg": sum(r["context"]["avg"] for r in measured) // n, "peak_avg": sum(peaks) // n,
                        "peak": max(peaks, default=0), "big": sum(p > BIG_CONTEXT for p in peaks),
                        "compactions": sum(r["context"]["compactions"] for r in measured)}
    found["daily"] = defaultdict(lambda: defaultdict(float))  # day: {model family: cost}
    found["repos"] = defaultdict(float)  # repo: cost
    found["hours"] = defaultdict(int)  # (weekday, local hour): sessions
    for r in rows:
        start = datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone()
        for model, usd in models_of(r).items():
            found["daily"][r["start"][:10]][model] += usd
        found["repos"][repo_of(r)] += cost(r)
        found["hours"][start.weekday(), start.hour] += 1
    found["peaks"] = [(r["start"][:10], r["context"]["peak"], r["title"] or r["prompt"][:60]) for r in measured]
    return found


# ---- page

def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def day(stamp):
    """2026-10-09 as 9 Oct 2026."""
    d = date.fromisoformat(str(stamp)[:10])
    return f"{d.day} {d:%b %Y}"


def worked_on(days):
    """'10 Nov to 14 Nov, 2 days'; the year is in the page's period."""
    if not days:
        return "-"
    days = sorted(days)
    span = " to ".join(dict.fromkeys(day(d).rsplit(" ", 1)[0] for d in (days[0], days[-1])))
    return f"{span}, {plural(len(days), 'day')}"


def paid(usd):
    """Whether a cost is worth showing: under half a cent rounds to nothing."""
    return usd >= 0.005


def money(usd):
    """Dollars, or '-' for nothing, so a ticket without sessions does not read as no effort."""
    return f"${usd:,.2f}" if paid(usd) else "-"


def tag(name, text, **attrs):
    """One HTML element. Text is escaped; pass a list for content that is already HTML."""
    inner = "".join(text) if isinstance(text, list) else html.escape(str(text))
    shown = "".join(' %s="%s"' % (k.strip("_"), html.escape(str(v))) for k, v in attrs.items())
    return f"<{name}{shown}>{inner}</{name}>"


def grid(head, rows, classes=None):
    """An HTML table. A cell that is a (text, url, small print) tuple becomes a link (when there is a url)
    with a line under it. The Cost column is left out under --no-cost."""
    if not SHOW_COST and "Cost" in head:
        i = head.index("Cost")
        head, rows = head[:i] + head[i + 1:], [r[:i] + r[i + 1:] for r in rows]

    def cell(c):
        if not isinstance(c, tuple):
            return tag("td", c)
        text, url, small = c
        return tag("td", [tag("a", text, href=url) if url else html.escape(text)] + ([tag("small", small)] if small else []))
    return tag("div", [tag("table", [tag("tr", [tag("th", h) for h in head])] + [
        tag("tr", [cell(c) for c in row], **({"class_": cls} if cls else {}))
        for row, cls in zip(rows, classes or [""] * len(rows))])], class_="scroll")


def dot(slot):
    """The colour mark of an overview group; slot 1-8 is a palette colour, 0 is grey."""
    return tag("span", "", class_=f"dot c{slot}")


def section(title, intro, *parts, total=None, slot=None):
    """A boxed section; total is the cost shown at the right of its title, slot the colour of its group."""
    with_total = SHOW_COST and paid(total or 0)
    name = [(dot(slot) if slot is not None else "") + (title[0] if isinstance(title, list) else html.escape(title))]
    head = tag("div", [tag("h2", name)] + ([tag("span", money(total), class_="total")] if with_total else []),
               class_="head")
    return tag("section", [head] + ([tag("p", intro, class_="intro")] if intro else []) + list(parts), class_="box")


def status_cell(name):
    return [tag("span", STATUS[name], class_=f"status {name}")]


def jira_link(key):
    return f"{JIRA_URL.rstrip('/')}/browse/{key}" if JIRA_URL and key else ""


def pr_links(prs):
    """Each pull request as 'repo#123 status', one per line."""
    links = [tag("a", f"{pr['repo']}#{pr['url'].rsplit('/', 1)[-1]}", href=pr["url"], title=pr["title"])
             + " " + tag("span", STATUS[pr["status"]].split()[0], class_=f"status {pr['status']}",
                         title=STATUS[pr["status"]].split(" ", 1)[1]) for pr in prs]
    return ["<br>".join(links)] if links else "-"


def model_split(models):
    """'Opus $4.10 (80%), Sonnet $1.02 (20%)', the most used first; percentages only under --no-cost."""
    total = sum(models.values())
    if not paid(total):
        return "-"
    parts = sorted(((m, usd) for m, usd in models.items() if paid(usd)), key=lambda item: -item[1])
    return ", ".join(f"{m} {money(usd) + ' ' if SHOW_COST else ''}({usd / total:.0%})" for m, usd in parts)


def repos(tickets):
    """The repos the tickets touched, those of the most expensive ticket first, as one line."""
    found = {r: None for t in sorted(tickets, key=lambda t: -t.cost) for r in t.repos}
    return ", ".join(found) or "-"


def ticket_boxes(tickets, slot):
    """One box per ticket, the most expensive first: its total cost in the title, then a table with the
    ticket's own work and each sub-task, indented, with its own cost."""
    typed = any(w.type for t in tickets for w in t.works)
    head = ["Ticket"] + (["Type"] if typed else []) + ["Worked on", "Pull requests", "Models", "Cost"]
    boxes = []
    for t in sorted(tickets, key=lambda t: -t.cost):
        rows = [[(w.key, jira_link(w.key), w.summary)] + ([w.type or "-"] if typed else [])
                + [worked_on(w.days), pr_links(w.prs), model_split(w.models), money(w.cost)] for w in t.works]
        name = f"{t.key} {t.own.summary}".strip()
        title = [tag("a", name, href=jira_link(t.key))] if JIRA_URL else name
        titles = list(dict.fromkeys(pr["title"] for w in t.works for pr in w.prs))
        intro = f"Repos: {', '.join(t.repos)}." if t.repos else ""
        intro += f" Pull requests: {'; '.join(titles)}." if titles else ""
        intro += " The total includes the sub-tasks." if t.subs and SHOW_COST else ""
        boxes.append(section(title, intro.strip(), grid(head, rows, [""] + ["sub"] * len(t.subs)),
                             total=t.cost, slot=slot))
    return boxes


def groups(data):
    """The overview's rows, keyed by id: tickets, support, incidents, reviews and other work. Their costs add up
    to the total; each has a colour slot."""
    tickets, support, incidents, other = data["tickets"], data["support"], data["incidents"], data["other"]
    rows = [("tickets", "Tickets", len(tickets), repos(tickets), sum(t.cost for t in tickets), tickets),
            ("support", "Support tickets", len(support), repos(support), sum(t.cost for t in support), support),
            ("incidents", "Incidents and investigations", "-", ", ".join(dict.fromkeys(i["repo"] for i in incidents)),
             sum(i["cost"] for i in incidents), incidents),
            ("reviews", "Code reviews", "-", "-", data["reviews"]["cost"],
             data["prs"]["reviewed"] or paid(data["reviews"]["cost"])),
            ("other", "Other work", "-", ", ".join(sorted(other, key=lambda r: -other[r]["cost"])),
             sum(o["cost"] for o in other.values()), other)]
    found = {gid: {"name": name, "tickets": n, "repos": r, "cost": usd}
             for gid, name, n, r, usd, shown in rows if shown}
    for i, g in enumerate(found.values()):
        g["slot"] = i + 1 if i < 8 else 0  # eight palette colours in a fixed order; past them, grey
    return found


def overview(rows):
    """The groups as a table, after a bar and legend that split the whole spend between them."""
    top, total = max([g["cost"] for g in rows] + [0.01]), sum(g["cost"] for g in rows) or 0.01

    def share(g):
        part = g["cost"] / total
        return "-" if not paid(g["cost"]) else "<1%" if part < 0.005 else f"{part:.0%}"

    def spend(g):
        bar = tag("div", [tag("span", "", class_=f"c{g['slot']}", style=f"width:{g['cost'] / top * 100:.1f}%")], class_="bar")
        return [html.escape(money(g["cost"])) + bar]
    charged = [g for g in rows if paid(g["cost"])]
    split = tag("div", [tag("span", "", class_=f"c{g['slot']}", style=f"flex-grow:{g['cost'] / total:.4f}",
                            title=f"{g['name']}: {share(g)}") for g in charged], class_="split")
    legend = tag("ul", [tag("li", [dot(g["slot"]) + html.escape(g["name"]) + " " + tag("strong", share(g))])
                        for g in charged], class_="legend")
    return split + legend + grid(["Group", "Tickets", "Repos", "Share", "Cost"],
                                 [[[dot(g["slot"]) + html.escape(g["name"])], g["tickets"], g["repos"], share(g),
                                   spend(g)] for g in rows])


def headline(data, group):
    """The headline numbers as (number, label), outcomes first; a box with nothing behind it is left out."""
    prs, tickets, support = data["prs"], data["tickets"], data["support"]

    def s(n):
        return "" if n == 1 else "s"
    resolved = sum(t.resolved for t in tickets)
    support_resolved = sum(t.resolved for t in support)
    merged = sum(pr["status"] == "merged" for pr in prs["opened"])
    incidents, reviewed = len(data["incidents"]), len(prs["reviewed"])
    # The tickets you worked on: sessions, pull requests and resolved tickets; reviews for others do not count.
    touched = {t.key for t in tickets + support} | {i["ticket"] for i in data["incidents"] if i["ticket"]}
    boxes = [(len(touched), f"ticket{s(len(touched))} worked on", touched),
             (resolved, f"ticket{s(resolved)} resolved, of {len(tickets)}", tickets),
             (support_resolved, f"support ticket{s(support_resolved)} resolved, of {len(support)}", support),
             (merged, f"pull request{s(merged)} merged, of {len(prs['opened'])} opened", prs["opened"]),
             (incidents, f"incident{s(incidents)} handled", incidents),
             (reviewed, f"pull request{s(reviewed)} reviewed", reviewed)]
    boxes = [(number, label) for number, label, behind in boxes if behind]
    if SHOW_COST:
        boxes.append((money(sum(g["cost"] for g in group.values())), "spent at API list prices"))
    return boxes


def svg(width, height, marks, label):
    return tag("div", [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)}">'
                       + "".join(marks) + "</svg>"], class_="chart")


def mark(kind, title, slot, **attrs):
    """One SVG shape in a palette colour, with a tooltip."""
    shown = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<{kind} class="c{slot}"{shown}><title>{html.escape(title)}</title></{kind}>'


def text(x, y, words, anchor="start"):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}">{html.escape(str(words))}</text>'


def daily_chart(daily, since, until):
    """Cost per day as columns, one segment per model, 2px apart."""
    first, last = date.fromisoformat(since), date.fromisoformat(until)
    days = [str(first + timedelta(n)) for n in range((last - first).days + 1)]
    models = sorted({m for d in daily.values() for m, usd in d.items() if paid(usd)},
                    key=lambda m: (MODEL_SLOTS.get(m, 99), m))
    top = max([sum(d.values()) for d in daily.values()] + [0.01])
    w, h, left, base = 720, 180, 44, 156
    step = (w - left) / len(days)
    marks = [f'<line class="grid" x1="{left}" x2="{w}" y1="{base - 140}" y2="{base - 140}"/>',
             f'<line class="axis" x1="{left}" x2="{w}" y1="{base}" y2="{base}"/>',
             text(left - 6, base - 136, money(top), "end"), text(left - 6, base, "$0", "end")]
    for i, d in enumerate(days):
        y = base
        for m in models:
            usd = daily.get(d, {}).get(m, 0)
            if paid(usd):
                height = max(usd / top * 140 - 2, 1)
                y -= height + 2
                marks.append(mark("rect", f"{day(d)}, {m}: {money(usd)}", MODEL_SLOTS.get(m, 0), x=f"{left + i * step + 1:.1f}",
                                  y=f"{y + 2:.1f}", width=f"{max(step - 2, 1):.1f}", height=f"{height:.1f}", rx=2))
        if i in (0, len(days) // 2, len(days) - 1):
            marks.append(text(f"{left + i * step + step / 2:.1f}", base + 18, day(d).rsplit(" ", 1)[0], "middle"))
    legend = tag("ul", [tag("li", [dot(MODEL_SLOTS.get(m, 0)) + html.escape(m)]) for m in models], class_="legend")
    return legend + svg(w, h + 4, marks, "Cost per day by model")


def peaks_chart(peaks):
    """The peak context of each session, in order, with the 100k line."""
    top = max([p for _, p, _ in peaks] + [BIG_CONTEXT * 1.2])
    w, h, left, base = 720, 150, 44, 130
    step = (w - left - 12) / max(len(peaks) - 1, 1)
    y = base - BIG_CONTEXT / top * 120
    marks = [f'<line class="axis" x1="{left}" x2="{w}" y1="{base}" y2="{base}"/>',
             f'<line class="limit" x1="{left}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>',
             text(left - 6, y + 4, f"{BIG_CONTEXT // 1000}k", "end"), text(left - 6, base, "0", "end"),
             text(left - 6, base - 116, f"{top / 1000:.0f}k", "end")]
    marks += [mark("circle", f"{day(d)}: {p / 1000:.0f}k, {t}", 1, cx=f"{left + 6 + i * step:.1f}",
                   cy=f"{base - p / top * 120:.1f}", r=4) for i, (d, p, t) in enumerate(peaks)]
    return svg(w, h, marks, "Peak context per session")


def hours_chart(hours):
    """Sessions by weekday and local hour: darker is more."""
    top = max(list(hours.values()) + [1])
    w, cell, left = 720, (720 - 40) / 24, 40
    marks = [text(left - 6, 14 + row * 18 + 9, name, "end") for row, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]
    for row in range(7):
        for hour in range(24):
            n = hours.get((row, hour), 0)
            attrs = {"x": f"{left + hour * cell + 1:.1f}", "y": 4 + row * 18, "width": f"{cell - 2:.1f}", "height": 16, "rx": 2}
            if n:
                marks.append(mark("rect", f"{plural(n, 'session')}", 1, fill_opacity=f"{0.2 + 0.8 * n / top:.2f}", **attrs))
            else:
                marks.append('<rect class="empty"' + "".join(f' {k}="{v}"' for k, v in attrs.items()) + "/>")
    marks += [text(f"{left + hour * cell + cell / 2:.1f}", 146, f"{hour:02d}", "middle") for hour in (0, 6, 12, 18, 23)]
    return svg(w, 150, marks, "Sessions by weekday and hour")


def bar_cell(shown, value, top):
    """A table cell: what is shown, over a bar as long as value is against top."""
    bar = tag("span", "", class_="c1", style=f"width:{value / max(top, 0.01) * 100:.1f}%")
    return [html.escape(str(shown)) + tag("div", [bar], class_="bar")]


def usage_sections(data):
    """The Context box and the Claude Code usage box: what the sessions used, most used first."""
    usage = data["usage"]
    c = usage["context"]
    intro = f"From the {c['sessions']} of {c['of']} sessions recorded with these details."

    def k(n):
        return f"{n / 1000:.0f}k"
    context = section("Context", intro, grid(
        ["Average per reply", "Average peak per session", "Largest peak", f"Sessions past {k(BIG_CONTEXT)}",
         "Compactions"], [[k(c["avg"]), k(c["peak_avg"]), k(c["peak"]), c["big"], c["compactions"]]]),
        *([tag("h3", "Peak context per session"), peaks_chart(usage["peaks"])] if usage["peaks"] else []))
    heads = {"skill": "Skill", "plugin": "Plugin", "mcp": "MCP server", "hook": "Hook (event:matcher)",
             "agent": "Subagent"}
    tables = []
    for kind, head in heads.items():
        if usage.get(kind):
            rows = most_used(usage[kind])
            top = rows[0][1][0]
            tables.append(grid([head, "Uses", "Sessions"], [[name, bar_cell(n, n, top), sessions]
                                                            for name, (n, sessions) in rows]))
    charts = []
    if SHOW_COST:
        repos = sorted(usage["repos"].items(), key=lambda item: -item[1])
        charts += [tag("h3", "Cost per day by model"), daily_chart(usage["daily"], data["since"], data["until"]),
                   tag("h3", "Cost by repo"),
                   grid(["Repo", "Cost"], [[repo, bar_cell(money(usd), usd, repos[0][1])] for repo, usd in repos])]
    charts += [tag("h3", "When you work: sessions by weekday and hour"), hours_chart(usage["hours"])]
    return context, section("Claude Code usage", intro, *charts, *tables)


def amount(n):
    """1234567 as 1.2M, 45678 as 46k."""
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


def efficiency_section(data):
    """How efficiently the sessions ran, against the same days a month earlier, then tokens per model."""
    now, before = data["measures"], data["before"]
    merged = sum(pr["status"] == "merged" for pr in data["prs"]["opened"])
    done = [t for t in data["tickets"] + data["support"] if t.resolved]

    def pct(v):
        return "-" if v is None else f"{v:.0%}"

    def points(a, b):
        return "-" if a is None or b is None else f"{round((a - b) * 100):+d} pts".replace("+0 ", "0 ")
    rows = [["Sessions", now["sessions"], before["sessions"] or "-",
             f"{now['sessions'] - before['sessions']:+d}" if before["sessions"] else "-"],
            ["Cache hit rate (cache reads / all input)", pct(now["cache_hit"]), pct(before["cache_hit"]),
             points(now["cache_hit"], before["cache_hit"])]]
    if SHOW_COST:
        change = f"{now['cost'] / before['cost'] - 1:+.0%}" if before["cost"] else "-"
        rows = [["Cost", money(now["cost"]), money(before["cost"]), change]] + rows + [
            ["Cost per merged pull request", money(now["cost"] / merged) if merged else "-", "-", "-"],
            ["Cost per resolved ticket", money(sum(t.cost for t in done) / len(done)) if done else "-", "-", "-"]]
    rows += [[label, pct(now[k]), pct(before[k]), points(now[k], before[k])]
             for label, k in (("Share of cost in sessions past 100k context", "big"),
                              ("Share of cost in subagents", "subagents"),
                              ("Share of cost in sessions that changed nothing", "idle"))]
    models = sorted(now["tokens"].items(), key=lambda item: (MODEL_SLOTS.get(item[0], 99), item[0]))
    tokens = grid(["Model", "Input", "Output", "Cache read", "Cache write", "Cache hit rate"],
                  [[[dot(MODEL_SLOTS.get(m, 0)) + html.escape(m)], amount(t["in"]), amount(t["out"]), amount(t["read"]),
                    amount(t["write"]), pct(t["read"] / max(sum(t[k] for k in SENT), 1))] for m, t in models])
    return section("Efficiency", f"This period against the same days a month earlier "
                                 f"({day(month_before(data['since']))} to {day(month_before(data['until']))}). "
                                 "Rows recorded before tokens were kept count for cost only.",
                   grid(["Measure", "This period", "Month before", "Change"], rows),
                   tag("h3", "Tokens per model"), tokens)


def page(data, group, name="report.html"):
    prs = data["prs"]

    def boxed(gid, title, intro, *parts):
        return section(title, intro, *parts, total=group[gid]["cost"], slot=group[gid]["slot"])
    context, usage = usage_sections(data) if SHOW_USAGE else ("", "")
    body = [tag("header", [tag("h1", "Work summary"),
                           tag("p", f"{day(data['since'])} to {day(data['until'])}", class_="period")]),
            tag("div", [tag("div", [tag("strong", number), tag("span", label)], class_="tile")
                        for number, label in headline(data, group)], class_="tiles"),
            context, efficiency_section(data) if SHOW_USAGE else "",
            section("Overview", "Where the work went, by kind. A share is the group's part of the session cost, "
                                "the closest measure of effort the records hold.", overview(list(group.values())))]
    for gid in ("tickets", "support"):
        if data[gid]:
            body += ticket_boxes(data[gid], group[gid]["slot"])
    if data["incidents"]:
        body.append(boxed("incidents", "Incidents and investigations", "Sessions that followed a PagerDuty alert.",
                          grid(["Date", "Session", "Ticket", "Repo", "Cost"],
                               [[day(i["date"]), i["what"], (i["ticket"], jira_link(i["ticket"]), "") if i["ticket"]
                                 else "-", i["repo"], money(i["cost"])] for i in data["incidents"]])))
    without_ticket = [pr for pr in prs["opened"] if not pr["ticket"]]
    if without_ticket:
        body.append(section("Pull requests without a ticket", "", grid(
            ["Opened", "Pull request", "Status"],
            [[day(pr["date"]), (pr["title"], pr["url"], pr["repo"]), status_cell(pr["status"])]
             for pr in without_ticket])))
    if data["other"]:
        body.append(boxed("other", "Other work", "Sessions with no Jira ticket, incident or review behind them, by repo.",
                          grid(["Repo", "Worked on", "Cost"],
                               [[repo, worked_on(o["days"]), money(o["cost"])]
                                for repo, o in sorted(data["other"].items(), key=lambda item: -item[1]["cost"])])))
    if "reviews" in group:
        unlinked = data["reviews"]["unlinked"]
        intro = ("Pull requests by teammates that you reviewed." if prs["reviewed"]
                 else "GitHub listed no reviews in the period.")
        if SHOW_COST and paid(unlinked):
            intro += f" Review sessions that named none of them: {money(unlinked)}."
        body.append(boxed("reviews", "Code reviews", intro, *([grid(
            ["Reviewed", "Pull request", "Status", "Cost"],
            [[day(pr["date"]), (pr["title"], pr["url"], f"{pr['repo']} · {pr['author']}"), status_cell(pr["status"]),
              money(pr["cost"])] for pr in prs["reviewed"]])] if prs["reviewed"] else [])))
    body += [usage, tag("footer", "Sources: Jira, GitHub and the records Claude Code keeps on this computer. "
                        + ("Costs are what the sessions would cost at Claude API list prices. " if SHOW_COST else "")
                        + f"Generated on {day(date.today())}.")]
    file = DATA / name
    file.write_text(Template((HERE / "report.html").read_text()).substitute(
        title=f"Work summary, {day(data['since'])} to {day(data['until'])}", body="\n".join(b for b in body if b)))
    return file


def period(arg):
    """(first day, last day) as YYYY-MM-DD: this month by default, the month before for 'last-month', or from
    a given day to today."""
    today = date.today()
    if arg == "last-month":
        last = today.replace(day=1) - timedelta(days=1)
        return str(last.replace(day=1)), str(last)
    return (arg or str(today.replace(day=1))), str(today)


def write_csv(data, file):
    """One row per ticket and sub-task, for a spreadsheet; no cost column when costs are left out."""
    with file.open("w", newline="") as out:
        rows = csv.writer(out)
        rows.writerow(["ticket", "parent", "type", "summary", "first day", "last day", "days", "pull requests"]
                      + (["cost USD"] if SHOW_COST else []))
        for t in sorted(data["tickets"] + data["support"], key=lambda t: -t.cost):
            for w in t.works:
                days = sorted(w.days)
                rows.writerow([w.key, "" if w is t.own else t.key, w.type, w.summary, days[0] if days else "",
                               days[-1] if days else "", len(days), " ".join(pr["url"] for pr in w.prs)]
                              + ([f"{w.cost:.2f}"] if SHOW_COST else []))
    return file


def report(args):
    global SHOW_COST, SHOW_USAGE
    SHOW_COST, SHOW_USAGE = "--no-cost" not in args, "--no-usage" not in args
    data = collect(*period(next((a for a in args if not a.startswith("--")), "")))
    group = groups(data)
    shown = sum(g["cost"] for g in group.values())
    if abs(shown - data["total"]) > 0.01:  # a session left off the page is a bug
        sys.exit(f"the page shows ${shown:.2f} but the sessions cost ${data['total']:.2f}")
    file = page(data, group)
    table = write_csv(data, file.with_suffix(".csv"))
    print(f"{day(data['since'])} to {day(data['until'])}: "
          + ", ".join(f"{number} {label}" for number, label in headline(data, group)))
    print(f"All {data['sessions']} sessions are on the page, ${data['total']:.2f}"
          + (f"; exclude_repos left out ${data['excluded']:.2f}" if data["excluded"] else ""))
    m = data["measures"]
    if m["cache_hit"] is not None:
        print(f"Cache hit rate {m['cache_hit']:.0%}; past 100k context {m['big'] or 0:.0%} of cost")
    top = most_used(data["usage"].get("skill", {}))[:3]
    if top:
        print("Top skills: " + ", ".join(f"{name} {n}" for name, (n, _) in top))
    print(f"Page: {file}")
    print(f"CSV: {table}")
    webbrowser.open(file.as_uri())


def start(hook):
    """The SessionStart reminder, or None: only with JIRA_PREFIXES set, in a git repo under DEV_DIR that is not in
    EXCLUDE_REPOS, on a branch that names no ticket key. The answer lands in the user's text, where record finds it."""
    cwd = Path(hook.get("cwd") or ".")
    if not PREFIXES or not cwd.is_relative_to(DEV) or cwd == DEV or repo_of({"cwd": str(cwd)}) in EXCLUDE_REPOS:
        return None
    git = subprocess.run(["git", "-C", str(cwd), "branch", "--show-current"], capture_output=True, text=True)
    if git.returncode or KEY.search(git.stdout):
        return None
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": (
        f"Worklog: the branch '{git.stdout.strip() or 'detached'}' names no Jira ticket ({', '.join(JIRA_PREFIXES)}). "
        "If the user's first request is work for a ticket and names no key, ask once which ticket it is for. "
        "Do not ask for personal, general or setup questions.")}}


def unmapped(args):
    """The sessions in Other work and the period's tickets, as JSON: what /worklog needs to choose a ticket."""
    data = collect(*period(args[0] if args else ""))
    print(json.dumps({
        "sessions": [{"id": r["id"], "date": r["start"][:10], "repo": repo_of(r), "branches": r["branches"],
                      "title": r["title"], "prompt": r["prompt"], "cost": round(cost(r), 2)}
                     for r in data["unmapped"]],
        "tickets": [{"key": w.key, "summary": w.summary, "type": w.type, "repos": list(t.repos)}
                    for t in data["tickets"] + data["support"] for w in t.works]}, indent=1, ensure_ascii=False))


def map_sessions(args):
    """Saves a ticket for each SESSION KEY pair; a key outside JIRA_PREFIXES is refused."""
    if not args or len(args) % 2:
        sys.exit("usage: worklog.py map SESSION KEY [SESSION KEY...]")
    chosen = mapped()
    for session, key in zip(args[::2], args[1::2]):
        if not KEY.fullmatch(key.upper()):
            sys.exit(f"{key} does not match JIRA_PREFIXES")
        chosen[session] = key.upper()
    DATA.mkdir(parents=True, exist_ok=True)
    MAPPED.write_text(json.dumps(chosen, indent=1))
    print(f"{len(args) // 2} mapped; {len(chosen)} in {MAPPED}")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "record":
        path = json.load(sys.stdin).get("transcript_path")
        # Claude Code gives a SessionEnd hook very little time, so the parsing runs detached.
        if path and Path(path).exists() and os.fork() == 0:
            os.setsid()
            append([Path(path)])
    elif command == "start":
        reminder = start(json.load(sys.stdin))
        if reminder:
            print(json.dumps(reminder))
    elif command == "report":
        report(sys.argv[2:])
        if (HERE / "demo.py").exists():  # a local add-on, kept out of the repo
            import demo
            demo.main(sys.argv[2:])
    elif command == "unmapped":
        unmapped(sys.argv[2:])
    elif command == "map":
        map_sessions(sys.argv[2:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
