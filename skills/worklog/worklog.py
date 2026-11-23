#!/usr/bin/env python3
"""Keeps a ledger of Claude Code sessions and writes a one-page work summary from it.

  worklog.py record                            SessionEnd hook: appends the session on stdin to the ledger
  worklog.py report [period] [--no-cost] [--no-usage]
      Records every transcript still in ~/.claude/projects, writes <dev_dir>/worklog/report.html, opens it
      and prints the counts. period: empty for this month, last-month, or a first day YYYY-MM-DD.

Settings: config.json (see config.py). Data: <dev_dir>/worklog, with sessions.jsonl (the ledger) and
jira.json (the issue cache). github.py and jira.py fetch pull requests and issues; each runs on its own too.
"""
import html
import json
import os
import re
import sys
import webbrowser
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from string import Template

import github
import jira
from config import CONFIG, HERE

DEV = Path(CONFIG["dev_dir"]).expanduser()
DATA = DEV / "worklog"
LEDGER = DATA / "sessions.jsonl"
PREFIXES = "|".join(re.escape(p) for p in CONFIG["jira_prefixes"])
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b", re.I) if PREFIXES else re.compile(r"[^\s\S]")  # never matches
KEY_SHAPE = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}-\d+\b")  # the ledger keeps these; the report filters by KEY
SUPPORT = {p.upper() for p in CONFIG["support_prefixes"]}
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/code-review")
COMMAND = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
PR_URL = re.compile(r"https://github\.com/[\w.-]+/([\w.-]+)/pull/(\d+)")
PR_CMD = re.compile(r"gh pr (?:diff|review|checkout|view) +#?(\d+)\b(?:.*?(?:--repo|-R)[ =][\w.-]+/([\w.-]+))?")
ALERT = re.compile(r"https://[\w-]+\.pagerduty\.com/", re.I)
CONTEXT_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
BIG_CONTEXT = 100_000  # tokens
# API list prices in USD per million tokens: input, output, cache read. A cache write costs 1.25x input
# for 5 minutes, 2x for 1 hour; fast mode costs 2x. An id not listed is priced as claude-opus-5-5.
PRICES = {"claude-opus-5-5": (4, 20, 0.20), "claude-opus-5": (5, 25, 0.50), "claude-opus-4": (5, 25, 0.50),
          "claude-sonnet-5-5": (2, 10, 0.10), "claude-sonnet-5": (2, 10, 0.20), "claude-sonnet-4": (3, 15, 0.30)}
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
                self.usage[msg.get("id")] = {**msg["usage"], "model": msg.get("model")}
                if not d.get("isSidechain"):
                    self.contexts[msg.get("id")] = sum(msg["usage"].get(f) or 0 for f in CONTEXT_FIELDS)
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
        models = defaultdict(float)
        for u in self.usage.values():
            models[family(u.get("model"))] += price(u)
        row["models"] = {m: round(usd, 4) for m, usd in models.items()}
        row["cost"] = round(sum(models.values()), 4)
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


def ticket(row, by_branch, issues):
    """The key a session counts for: a support key it names, else Jira.pick of its keys, else the ticket of a
    pull request opened from one of its branches. A branch name alone settles it when it names one ticket;
    otherwise the repo must match too."""
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
    return ""


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


def load(since, until):
    """The sessions that started in the period, the last row of each, and the cost of those in exclude_repos."""
    rows = {}
    for line in LEDGER.open():
        row = json.loads(line)
        rows[row["id"]] = row  # a session is recorded more than once; the last row wins
    rows = sorted((r for r in rows.values() if since <= r["start"][:10] <= until), key=lambda r: r["start"])
    excluded = sum(cost(r) for r in rows if repo_of(r) in CONFIG["exclude_repos"])
    return [r for r in rows if repo_of(r) not in CONFIG["exclude_repos"]], excluded


def collect(since, until):
    """Everything the report shows, as plain data. Every session lands in exactly one place."""
    append(sorted((Path.home() / ".claude" / "projects").glob("*/*.jsonl")))
    rows, excluded = load(since, until)
    if not rows:
        sys.exit(f"no sessions from {day(since)} to {day(until)}")
    prs = {kind: [pr for pr in found if pr["repo"] not in CONFIG["exclude_repos"]]
           for kind, found in pull_requests(since, until).items()}
    issues, tickets, incidents = Jira(), {}, []
    other = defaultdict(lambda: {"days": set(), "cost": 0.0})
    reviews = {"cost": 0.0, "unlinked": 0.0}

    def on(key):
        top = issues.top(key)
        if top not in tickets:
            tickets[top] = Ticket(top, issues)
        return tickets[top]

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
        named = ticket(row, by_branch, issues)
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
    return {"since": since, "last": until, "incidents": incidents, "other": other, "prs": prs,
            "reviews": reviews, "sessions": len(rows), "total": sum(cost(r) for r in rows), "excluded": excluded,
            "usage": usage_of(rows),
            "tickets": [t for t in tickets.values() if not is_support(t.key)],
            "support": [t for t in tickets.values() if is_support(t.key)]}


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
    return f"{CONFIG['jira_url'].rstrip('/')}/browse/{key}" if CONFIG["jira_url"] and key else ""


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
    typed = any(w.type for t in tickets for w in [t.own, *t.subs.values()])
    head = ["Ticket"] + (["Type"] if typed else []) + ["Worked on", "Pull requests", "Models", "Cost"]
    boxes = []
    for t in sorted(tickets, key=lambda t: -t.cost):
        works = [t.own] + sorted(t.subs.values(), key=lambda w: -w.cost)
        rows = [[(w.key, jira_link(w.key), w.summary)] + ([w.type or "-"] if typed else [])
                + [worked_on(w.days), pr_links(w.prs), model_split(w.models), money(w.cost)] for w in works]
        name = f"{t.key} {t.own.summary}".strip()
        title = [tag("a", name, href=jira_link(t.key))] if CONFIG["jira_url"] else name
        intro = f"Repos: {', '.join(t.repos)}." if t.repos else ""
        intro += " The total includes the sub-tasks." if t.subs else ""
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


def usage_sections(usage):
    """The Context box and the Claude Code usage box: what the sessions used, most used first."""
    c = usage["context"]
    intro = f"From the {c['sessions']} of {c['of']} sessions recorded with these details."

    def k(n):
        return f"{n / 1000:.0f}k"
    context = section("Context", intro, grid(
        ["Average per reply", "Average peak per session", "Largest peak", f"Sessions past {k(BIG_CONTEXT)}",
         "Compactions"], [[k(c["avg"]), k(c["peak_avg"]), k(c["peak"]), c["big"], c["compactions"]]]))
    heads = {"skill": "Skill", "plugin": "Plugin", "mcp": "MCP server", "hook": "Hook (event:matcher)",
             "agent": "Subagent"}
    tables = [grid([head, "Uses", "Sessions"], [[name, n, sessions] for name, (n, sessions) in
                                                sorted(usage[kind].items(), key=lambda item: (-item[1][0], item[0]))])
              for kind, head in heads.items() if usage.get(kind)]
    return context, section("Claude Code usage", intro, *tables) if tables else ""


def page(data, group, name="report.html"):
    prs = data["prs"]

    def boxed(gid, title, intro, *parts):
        return section(title, intro, *parts, total=group[gid]["cost"], slot=group[gid]["slot"])
    context, usage = usage_sections(data["usage"]) if SHOW_USAGE else ("", "")
    body = [tag("header", [tag("h1", "Work summary"),
                           tag("p", f"{day(data['since'])} to {day(data['last'])}", class_="period")]),
            tag("div", [tag("div", [tag("strong", number), tag("span", label)], class_="tile")
                        for number, label in headline(data, group)], class_="tiles"),
            context,
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
        title=f"Work summary, {day(data['since'])} to {day(data['last'])}", body="\n".join(b for b in body if b)))
    return file


def period(arg):
    """(first day, last day) as YYYY-MM-DD: this month by default, the month before for 'last-month', or from
    a given day to today."""
    today = date.today()
    if arg == "last-month":
        last = today.replace(day=1) - timedelta(days=1)
        return str(last.replace(day=1)), str(last)
    return (arg or str(today.replace(day=1))), str(today)


def report(args):
    global SHOW_COST, SHOW_USAGE
    SHOW_COST, SHOW_USAGE = "--no-cost" not in args, "--no-usage" not in args
    data = collect(*period(next((a for a in args if not a.startswith("--")), "")))
    group = groups(data)
    shown = sum(g["cost"] for g in group.values())
    if abs(shown - data["total"]) > 0.01:  # a session left off the page is a bug
        sys.exit(f"the page shows ${shown:.2f} but the sessions cost ${data['total']:.2f}")
    file = page(data, group)
    print(f"{day(data['since'])} to {day(data['last'])}: "
          + ", ".join(f"{number} {label}" for number, label in headline(data, group)))
    print(f"All {data['sessions']} sessions are on the page, ${data['total']:.2f}"
          + (f"; exclude_repos left out ${data['excluded']:.2f}" if data["excluded"] else ""))
    top = sorted(data["usage"].get("skill", {}).items(), key=lambda item: (-item[1][0], item[0]))[:3]
    if top:
        print("Top skills: " + ", ".join(f"{name} {n}" for name, (n, _) in top))
    if not (HERE / "config.json").exists():
        print(f"No config.json: copy {HERE / 'config.example.json'} to config.json and set jira_url and jira_prefixes.")
    print(f"Page: {file}")
    webbrowser.open(file.as_uri())


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "record":
        path = json.load(sys.stdin).get("transcript_path")
        # Claude Code gives a SessionEnd hook very little time, so the parsing runs detached.
        if path and Path(path).exists() and os.fork() == 0:
            os.setsid()
            append([Path(path)])
    elif command == "report":
        report(sys.argv[2:])
        if (HERE / "demo.py").exists():  # a local add-on, kept out of the repo
            import demo
            demo.main(sys.argv[2:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
