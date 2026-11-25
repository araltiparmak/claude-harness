#!/usr/bin/env python3
"""Measures how you work with Claude Code and what the work was: sessions sorted into Jira tickets, pull requests
and reviews, with time, cost and tips. Everything stays on this computer.

  worklog.py report [period] [--share]
      Updates the ledger from the transcripts still on disk, writes <DEV_DIR>/worklog/report.html, opens it and
      prints the headline. --share writes share.html instead: the work, outcomes and time for other readers,
      without costs or the Using Claude sections.
      period: empty for this month, last-month, or a first day YYYY-MM-DD.
  worklog.py prepare [period]                  prints, as JSON, what /worklog needs: the sessions the rules gave
                                               no ticket, the period's tickets with their pull request and session
                                               titles, and the other Jira issues assigned to you and updated
  worklog.py map SESSION KEY [SESSION KEY...]  saves a ticket for a session the rules gave none
  worklog.py note KEY TEXT [KEY TEXT...]       saves a one-line outcome for a ticket, shown under its name
  worklog.py check                             checks the setup: settings, hook, ledger, git, gh and Jira
  worklog.py record                            the SessionEnd hook: adds the session on stdin to the ledger

Settings: ~/.config/worklog.json over the defaults in settings.json; models and prices: models.json; README.md
describes both. Data: <DEV_DIR>/worklog, with sessions.jsonl (the
ledger), jira.json (the issue cache), commits.json (the pull requests of your commits), mapped.json (the tickets chosen with map) and notes.json (the outcomes).
ledger.py reads transcripts, page.py writes the HTML, github.py and jira.py fetch pull requests and issues,
inventory.py finds what loads into every session.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import webbrowser
from collections import Counter, defaultdict
from datetime import date, timedelta
from operator import ge, gt, lt
from pathlib import Path

import github
import inventory
import jira
import ledger
import page
from ledger import BIG_CONTEXT, QUESTION_MODEL, SENT, TOKENS, cost, models_of, repo_of
from settings import DATA, DEV, FILE, settings

JIRA_PREFIXES, SUPPORT_PREFIXES, EXCLUDE_REPOS = (
    settings[k] for k in ("jira_prefixes", "support_prefixes", "exclude_repos"))
MAPPED = DATA / "mapped.json"
NOTES = DATA / "notes.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"  # where check looks for the hook
PREFIXES = "|".join(re.escape(p) for p in JIRA_PREFIXES)
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b", re.I) if PREFIXES else re.compile(r"[^\s\S]")  # never matches
SUPPORT = {p.upper() for p in SUPPORT_PREFIXES}
TOP = 10  # the most expensive sessions listed
MIN_SESSIONS = 5  # fewer sessions than this give no tips

pull_requests, commit_pulls = github.pull_requests, github.commit_pulls  # tests swap them


# ---- Jira

class Jira:
    """Jira issues through jira.py, cached in jira.json. Stops asking after the first failure, except for a key
    Jira does not know (see fetch)."""

    def __init__(self):
        file = DATA / "jira.json"
        self.cache, self.down = json.loads(file.read_text()) if file.exists() else {}, not PREFIXES
        self.unknown = set()  # keys Jira refused in this run

    def ask(self, call, *args):
        if self.down:
            return None
        try:
            return call(*args)
        except Exception as err:  # not set up, not reachable, login refused
            print(f"note: Jira is not answering ({err}); tickets are shown by key only\n", file=sys.stderr)
            self.down = True

    def issue(self, key):
        """Summary, type, whether it is a sub-task, and parent of one issue; {} when Jira cannot say."""
        if "subtask" not in self.cache.get(key, {}) and key not in self.unknown:
            found = self.ask(self.fetch, key)
            if found:
                self.cache[key] = found
        return self.cache.get(key, {})

    def fetch(self, key):
        """One issue. When the command fails for it but Jira still answers a search, Jira does not know the key (a
        typo, an example in a prompt, a deleted issue): it is skipped, and Jira stays on for the other keys."""
        try:
            return jira.issue(key)
        except urllib.error.HTTPError as err:
            err.close()  # the answer's body, unread
            if err.code != 404:
                raise
            jira.search("updated >= -1d")  # raises when Jira itself is not answering
            self.unknown.add(key)
            return None

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

    def save(self):
        if self.cache:
            (DATA / "jira.json").write_text(json.dumps(self.cache, indent=1))


# ---- sorting the sessions

def is_support(key):
    return key.split("-")[0].upper() in SUPPORT


def keys_of(row):
    """The ticket keys a session names, filtered by the prefixes configured now; its branches are scanned
    again, so a prefix added later also counts for sessions recorded before."""
    found = [k.upper() for k in row["keys"] + KEY.findall(" ".join(row["branches"]))]
    return [k for k in dict.fromkeys(found) if KEY.fullmatch(k)]


def saved(file):
    """The JSON saved by map or note, {} when there is none."""
    return json.loads(file.read_text()) if file.exists() else {}


def ticket(row, by_branch, issues):
    """The key the rules give a session: a support key it names, else Jira.pick of its keys, else the ticket of a
    pull request from one of its branches, else Jira.pick of the keys in the pull requests that hold the commits
    you made in its repo while it ran. A branch name alone settles it when it names one ticket; otherwise the repo
    must match too. collect falls back to the key saved with map."""
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
    if PREFIXES and row.get("end") and Path(row["cwd"] or "/nowhere").is_dir():
        found = [k.upper() for text in commit_pulls(row["cwd"], row["start"], row["end"]) for k in KEY.findall(text)]
        if found:
            return issues.pick(list(dict.fromkeys(found)))
    return ""


class Work:
    """The days, cost, cost per model, active minutes, session titles and pull requests of some sessions: one
    ticket or sub-task (its key and Jira issue), the code reviews, or the other work in one repo. mapped counts the
    sessions that came from map."""

    def __init__(self, key="", issue=None):
        issue = issue or {}
        self.key, self.summary, self.type = key, issue.get("summary", ""), issue.get("type", "")
        self.days, self.cost, self.models, self.prs = set(), 0.0, defaultdict(float), []
        self.minutes, self.titles, self.mapped, self.resolved = 0.0, [], 0, False

    def add(self, row, mapped=False):
        self.days.add(row["day"])
        self.cost += cost(row)
        self.minutes += row.get("active", 0)
        self.titles.append(row["title"] or row["prompt"])
        self.mapped += mapped
        for model, usd in models_of(row).items():
            self.models[model] += usd


class Ticket:
    """A ticket: its own work, its sub-tasks' work, and the repos of both. Its cost and time include the
    sub-tasks."""

    def __init__(self, key, issues):
        self.key, self.issues, self.own, self.subs, self.repos = key, issues, Work(key, issues.issue(key)), {}, {}
        self.resolved = False

    def part(self, key):
        if key == self.key:
            return self.own
        if key not in self.subs:
            self.subs[key] = Work(key, self.issues.issue(key))
        return self.subs[key]

    @property
    def works(self):
        """Its own work, then its sub-tasks, the most expensive first."""
        return [self.own] + sorted(self.subs.values(), key=lambda w: -w.cost)

    @property
    def cost(self):
        return sum(w.cost for w in self.works)

    @property
    def minutes(self):
        return sum(w.minutes for w in self.works)


def in_period(rows, since, until):
    """The sessions that started in the period, oldest first, each given its local day, and the cost of those in
    exclude_repos."""
    for r in rows:
        r["day"] = ledger.local_day(r["start"])
    rows = sorted((r for r in rows if since <= r["day"] <= until), key=lambda r: r["start"])
    excluded = sum(cost(r) for r in rows if repo_of(r) in EXCLUDE_REPOS)
    return [r for r in rows if repo_of(r) not in EXCLUDE_REPOS], excluded


def collect(since, until):
    """Everything the report shows, as plain data. Every session lands in exactly one place: a ticket, code
    reviews, or other work."""
    rows, excluded = in_period(ledger.refresh(), since, until)
    if not rows:
        sys.exit(f"no sessions from {since} to {until}")
    prs = {kind: [pr for pr in found if pr["repo"] not in EXCLUDE_REPOS]
           for kind, found in pull_requests(since, until).items()}
    issues, tickets, reviews, other, unmapped = Jira(), {}, Work(), defaultdict(Work), []  # other: {repo: Work}

    def on(key):
        top = issues.top(key)
        if top not in tickets:
            tickets[top] = Ticket(top, issues)
        return tickets[top]

    chosen = saved(MAPPED)
    by_branch = {}  # (repo, branch): ticket, and branch: {tickets of the pull requests from a branch of that name}
    for pr in prs["opened"] + prs.get("earlier", []):
        pr["sub"] = issues.pick(list(dict.fromkeys(k.upper() for k in KEY.findall(pr["text"]))))
        pr["ticket"] = issues.top(pr["sub"])
        if pr["ticket"]:
            by_branch[pr["repo"], pr["branch"]] = pr["ticket"]
            by_branch.setdefault(pr["branch"], set()).add(pr["ticket"])
    for row in rows:
        rule = ticket(row, by_branch, issues)
        named = rule or chosen.get(row["id"], "")
        if named:
            t = on(named)
            t.part(named).add(row, mapped=not rule)
            t.repos[repo_of(row)] = None
        elif row["review"] and not row["edits"]:
            reviews.add(row)
        else:
            other[repo_of(row)].add(row)
            unmapped.append(row)
    for pr in prs["opened"]:  # the earlier ones only lent their branches
        if pr["ticket"]:
            t = on(pr["sub"])
            t.part(pr["sub"]).prs.append(pr)
            t.repos[pr["repo"]] = None
    for key in issues.resolved(since, until):  # a resolved sub-task does not resolve its parent
        t = on(key)
        t.part(key).resolved = True
        t.resolved |= key == t.key
    issues.save()
    measured = measures(rows)
    return {"since": since, "until": until, "other": other, "unmapped": unmapped, "prs": prs,
            "reviews": reviews, "sessions": len(rows), "total": sum(cost(r) for r in rows), "excluded": excluded,
            "minutes": sum(r.get("active", 0) for r in rows), "timed": sum("active" in r for r in rows),
            "notes": saved(NOTES), "jira": issues,
            "usage": usage_of(rows), "measures": measured, "tips": tips(measured),
            "tickets": [t for t in tickets.values() if not is_support(t.key)],
            "support": [t for t in tickets.values() if is_support(t.key)]}


# ---- measuring how you use Claude

def token_totals(rows):
    """{model: {in, out, read, write}} over the rows."""
    tokens = defaultdict(lambda: dict.fromkeys(TOKENS, 0))
    for r in rows:
        for model, t in r.get("tokens_by_model", {}).items():
            for kind in TOKENS:
                tokens[model][kind] += t[kind]
    return {m: t for m, t in tokens.items() if any(t.values())}


def context_stats(rows):
    """The context sizes of the sessions that recorded them."""
    contexts = [r for r in rows if "context" in r]
    peaks = [r["context"]["peak"] for r in contexts]
    return {"sessions": len(contexts), "avg": sum(r["context"]["avg"] for r in contexts) // max(len(contexts), 1),
            "peak_avg": sum(peaks) // max(len(peaks), 1), "peak": max(peaks, default=0),
            "big": sum(p > BIG_CONTEXT for p in peaks)}


def question(r):
    """A session that changed no files and reviewed nothing."""
    return not (r["edits"] or r["review"])


def measures(rows):
    """How the sessions used tokens and how smoothly they went, from the ledger alone. A share is of cost over
    the sessions that recorded the field, and an average is over the rated sessions; None when none did."""
    tokens = token_totals(rows)
    sent = sum(t[k] for t in tokens.values() for k in SENT)

    def share(field, part):
        known = [r for r in rows if field in r]
        whole = sum(cost(r) for r in known)
        return sum(part(r) for r in known) / whole if whole else None

    def per_session(field):
        return sum(field(r) for r in rated) / len(rated) if rated else None
    rated = [r for r in rows if "prompts" in r]  # rows recorded before these were kept have none
    return {
        "cost": sum(cost(r) for r in rows) or 0.0, "sessions": len(rows), "tokens": tokens,
        "cache_hit": sum(t["read"] for t in tokens.values()) / sent if sent else None,
        "big": share("context", lambda r: cost(r) if r["context"]["peak"] > BIG_CONTEXT else 0),
        "subagents": share("subagent_cost", lambda r: r["subagent_cost"]),
        "idle": share("edits", lambda r: cost(r) if question(r) else 0),
        "off_model_questions": share("edits", lambda r: sum(usd for m, usd in models_of(r).items()
                                                           if m != QUESTION_MODEL) if question(r) else 0),
        "rated": len(rated),
        "prompts": per_session(lambda r: r["prompts"]),
        "interrupted": per_session(lambda r: r["interrupts"] > 0),
        "errors": per_session(lambda r: r["errors"]),
        "context": context_stats(rows),
        "compacted": sum(r["context"]["compactions"] > 0 for r in rows if "context" in r),
        "top": sorted(rows, key=lambda r: -cost(r))[:TOP]}


# A tip shows when its measure crosses its line: (measure, test, line, what was found, what to try), the costliest
# habit first. The lines are rules of thumb, not targets.
TIPS = [
    ("big", gt, 0.5, f"{{:.0%}} of the cost came from sessions whose context grew past {BIG_CONTEXT // 1000}k tokens.",
     "Every reply re-reads the whole context, so a long session gets dearer with each turn. Start a fresh session "
     "for each task (/clear), and point Claude at files and line ranges instead of whole folders."),
    ("cache_hit", lt, 0.85, "Only {:.0%} of the input came from the prompt cache.",
     "The cache expires after a pause (5 minutes by default), and the next reply pays full price for the whole "
     "context. Finish a task in one sitting, or start fresh after a long break instead of resuming."),
    ("off_model_questions", gt, 0.10,
     f"Sessions that only asked questions spent {{:.0%}} of the cost on models other than {QUESTION_MODEL}.",
     f"{QUESTION_MODEL} answers most questions well for less; switch with /model."),
    ("idle", gt, 0.25, "{:.0%} of the cost went to sessions that changed no files and reviewed nothing.",
     "Questions are fine. For exploration, a narrower first prompt (the file, the symptom, what you expect) usually "
     "gets there in fewer turns."),
    ("subagents", gt, 0.3, "Subagents used {:.0%} of the cost.",
     "Each one starts with an empty context and reads everything again; keep them for wide searches and independent "
     "work, not small steps."),
    ("interrupted", gt, 0.2, "You stopped Claude in {:.0%} of sessions.",
     "That often means it set off in the wrong direction. Plan mode (shift+tab) or a first prompt that states the "
     "goal and the limits helps it start right."),
    ("compacted", ge, 3, "{} sessions ran out of context and were compacted.",
     "Compaction loses detail. Split long tasks into sessions, with a short hand-over note."),
    ("errors", gt, 3, "Tool calls failed {:.1f} times per session.",
     "Repeated failures often mean a missing permission, a wrong working folder or a missing tool; the most "
     "expensive sessions show where."),
]
PER_SESSION = ("interrupted", "errors")  # averages over the sessions that recorded prompts (rated)


def tips(m):
    """What to try: (what was found, what to try) for each measure in TIPS past its line. None with fewer than
    MIN_SESSIONS sessions; a PER_SESSION measure also needs MIN_SESSIONS rated sessions."""
    if m["sessions"] < MIN_SESSIONS:
        return []
    found = []
    for name, crossed, line, finding, advice in TIPS:
        value = None if name in PER_SESSION and m["rated"] < MIN_SESSIONS else m[name]
        if value is not None and crossed(value, line):
            found.append((finding.format(value), advice))
    return found


def skills_of(row, installed):
    """A session's skill uses: Skill calls, and slash commands named after an installed or a plugin skill."""
    used = row.get("used", {})
    skills = dict(used.get("skill", {}))
    for skill, n in used.get("command", {}).items():
        if skill in installed or ":" in skill:
            skills[skill] = skills.get(skill, 0) + n
    return skills


RATES = {m["name"]: m["prices"] for m in ledger.MODELS.values()}  # model family: prices per million tokens
KINDS = {"account": "claude.ai skill", "plugin, account": "claude.ai plugin", "mcp, claude.ai": "claude.ai connector"}


def kind_name(kind):
    """An inventory kind as the page names it: skill, plugin, MCP server, or its claude.ai variant."""
    if kind in KINDS:
        return KINDS[kind]
    if kind.startswith("plugin, project "):
        return "plugin, in " + kind[len("plugin, project "):]
    if kind.startswith("mcp, local, "):
        return "MCP server, in " + kind[len("mcp, local, "):]
    if kind == "plugin":
        return "plugin"
    return "MCP server" if kind.startswith("mcp") else "skill"


def loaded_cost(row, tokens):
    """About what tokens loaded into every reply cost in one session: their share of its average context, times
    what the session paid to read and write its cached context. Background calls carry no such context."""
    avg = (row.get("context") or {}).get("avg")
    if not avg or not tokens:
        return 0.0
    default = ledger.MODELS[ledger.PRICING["default_model"]]["prices"]
    paid = sum(t.get("read", 0) * RATES.get(m, default)["cache_read"] + t.get("write", 0) *
               RATES.get(m, default)["cache_write_1h"] for m, t in row.get("tokens_by_model", {}).items()
               if m != "Background")
    return min(tokens / avg, 1.0) * paid / 1e6


def unused_of(rows, names):
    """The skills, plugins and MCP servers that load into sessions and that no session of the period used, as
    {name, kind, tokens, usd}, the most expensive first. usd covers the sessions the item loaded into: all of
    them, or those in its project for a project plugin or local server; None when the tokens are not known."""
    found = []
    for name, kind, tokens, _, project, keys in inventory.items():
        if inventory.counts_for(keys, names):
            continue
        sessions = [r for r in rows if not project or (r["cwd"] or "").startswith(project)]
        usd = None if tokens is None else sum(loaded_cost(r, tokens) for r in sessions)
        found.append({"name": name, "kind": kind_name(kind), "tokens": tokens, "usd": usd})
    return sorted(found, key=lambda u: (u["usd"] is None, -(u["usd"] or 0), -(u["tokens"] or 0), u["name"]))


def usage_of(rows):
    """What the sessions used, as {kind: {name: [uses, sessions]}} for skills, MCP servers and subagents, cost per
    day per model, the peak context of each session, and what loaded into the sessions unused (unused_of)."""
    installed = {p.name for p in inventory.SKILLS.iterdir() if (p / "SKILL.md").is_file()} \
        if inventory.SKILLS.is_dir() else set()
    found = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    found["daily"] = defaultdict(lambda: defaultdict(float))  # day: {model: cost}
    names = Counter()  # every use under the names inventory counts it by
    for r in rows:
        used = r.get("used", {})
        for kind, counts in (("skill", skills_of(r, installed)), ("mcp", used.get("mcp", {})),
                             ("agent", used.get("agent", {}))):
            for item, n in counts.items():
                found[kind][item][0] += n
                found[kind][item][1] += 1
                names["mcp:" + item if kind == "mcp" else item] += n
        for model, usd in models_of(r).items():
            found["daily"][r["day"]][model] += usd
    found["peaks"] = [(r["day"], r["context"]["peak"], r["title"] or r["prompt"][:60])
                      for r in rows if "context" in r]
    found["unused"] = unused_of(rows, names)
    return found


# ---- commands

def period(arg):
    """(first day, last day) as YYYY-MM-DD: this month by default, the month before for 'last-month', or from
    a given day to today."""
    today = date.today()
    if arg == "last-month":
        last = today.replace(day=1) - timedelta(days=1)
        return str(last.replace(day=1)), str(last)
    try:
        first = date.fromisoformat(arg) if arg else today.replace(day=1)
    except ValueError:  # not a day, such as november or 2026-02-30
        sys.exit(f"period must be empty, last-month or YYYY-MM-DD, not {arg}")
    return str(first), str(today)


def report(args):
    share = "--share" in args
    data = collect(*period(next((a for a in args if not a.startswith("--")), "")))
    view = page.Page(data, share)
    shown = sum(g["cost"] for g in view.groups.values())
    if abs(shown - data["total"]) > 0.01:  # a session left off the page is a bug
        sys.exit(f"the page shows ${shown:.2f} but the sessions cost ${data['total']:.2f}")
    file = view.write(DATA / ("share.html" if share else "report.html"))
    print(f"{data['since']} to {data['until']}: " + ", ".join(f"{n} {label}" for n, label in view.headline()))
    print(f"All {data['sessions']} sessions are on the page"
          + (f"; exclude_repos left out ${data['excluded']:.2f}" if data["excluded"] and not share else ""))
    if data["tips"] and not share:
        print(f"Top tip: {data['tips'][0][0]} {data['tips'][0][1]}")
    print(f"Page: {file}")
    webbrowser.open(file.as_uri())


def prepare(args):
    """What /worklog needs, as JSON: the sessions in Other work to map, each with the Jira issues you had in
    progress on its day, the period's tickets with their pull request and session titles to write notes from, and
    the other Jira issues assigned to you and updated in the period, which a session may also be mapped to."""
    since, until = period(args[0] if args else "")
    data = collect(since, until)
    tickets = data["tickets"] + data["support"]
    shown = {w.key for t in tickets for w in t.works}
    assigned = mappable(data["jira"].ask(jira.updated, since, until))
    busy = {d: mappable(data["jira"].ask(jira.in_progress, d)) for d in sorted({r["day"] for r in data["unmapped"]})}
    print(json.dumps({
        "sessions": [{"id": r["id"], "date": r["day"], "repo": repo_of(r), "branches": r["branches"],
                      "title": r["title"], "prompt": r["prompt"], "cost": round(cost(r), 2),
                      "in_progress": busy[r["day"]]}
                     for r in data["unmapped"]],
        "tickets": [{"key": t.key, "summary": t.own.summary, "type": t.own.type, "repos": list(t.repos),
                     "cost": round(t.cost, 2), "hours": round(t.minutes / 60, 1), "note": data["notes"].get(t.key, ""),
                     "subtasks": [{"key": w.key, "summary": w.summary} for w in t.subs.values()],
                     "pull_requests": [pr["title"] for w in t.works for pr in w.prs],
                     "sessions": list(dict.fromkeys(title for w in t.works for title in w.titles if title))}
                    for t in tickets],
        "assigned": {key: issue for key, issue in assigned.items() if key not in shown}},
        indent=1, ensure_ascii=False))


def mappable(issues):
    """The issues whose keys map accepts (under jira_prefixes); a Jira search can return other projects' too."""
    return {key: issue for key, issue in (issues or {}).items() if KEY.fullmatch(key)}


def save(file, found):
    """Merges {name: value} into file and says how many it holds."""
    merged = {**saved(file), **found}
    DATA.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(merged, indent=1, ensure_ascii=False))
    print(f"{len(found)} saved; {len(merged)} in {file}")


def checked(key):
    """A ticket key in upper case; one outside jira_prefixes stops the script."""
    if not KEY.fullmatch(key.upper()):
        sys.exit(f"{key} does not match jira_prefixes in {FILE}")
    return key.upper()


def pairs(args, usage):
    if not args or len(args) % 2:
        sys.exit(f"usage: worklog.py {usage}")
    return list(zip(args[::2], args[1::2]))


LABELS = {True: "ok  ", None: "warn", False: "FAIL"}


def runs(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_claude(line):
    """The SessionEnd hook and how long Claude Code keeps transcripts."""
    try:
        claude = json.loads(CLAUDE_SETTINGS.read_text()) if CLAUDE_SETTINGS.exists() else {}
    except ValueError:
        claude = {}
        line(False, str(CLAUDE_SETTINGS), "not valid JSON")
    hooked = "worklog.py record" in json.dumps(claude.get("hooks", {}).get("SessionEnd", []))
    line(hooked or None, "SessionEnd hook", "missing; README.md shows the lines to add")
    keep = claude.get("cleanupPeriodDays", 30)
    line(keep >= 60 or None, f"transcripts kept {keep} days", 'set "cleanupPeriodDays": 90 so report catches '
                                                              "sessions the hook missed")


def check_sources(line):
    """git, gh and Jira, which the report asks for pull requests and issues."""
    line(runs(["git", "config", "user.email"]) or None, "git user.email", "not set; commits cannot find their pull requests")
    line(bool(shutil.which("gh")) and runs(["gh", "auth", "status"]) or None, "gh",
         "not installed or not logged in (gh auth login); no pull requests or reviews")
    if PREFIXES:
        try:
            jira.search("updated >= -1d")
            line(True, "Jira search")
        except Exception as err:  # not set up, not reachable, login refused
            line(None, "Jira search", f"failed ({err}); set jira_url, jira_email and JIRA_API_TOKEN; tickets show "
                                      "by key only")


def check():
    """One line per part of the setup: ok, warn (the report runs but misses something) or FAIL; exits 1 on a FAIL."""
    found = []

    def line(ok, what, fix=""):
        found.append(ok)
        print(f"{LABELS[ok]}  {what}" + (f": {fix}" if fix and ok is not True else ""))
    line(FILE.exists() or None, f"settings {FILE}", "not found; README.md lists the keys")
    line(bool(PREFIXES) or None, f"jira_prefixes {', '.join(JIRA_PREFIXES)}".strip(), "empty, so no session finds a ticket")
    line(DEV.is_dir() or None, f"dev_dir {DEV}", "not a folder; sessions are named by their own folder")
    check_claude(line)
    if ledger.LEDGER.exists():
        with ledger.LEDGER.open() as rows:
            line(True, f"ledger {ledger.LEDGER}, {sum(1 for _ in rows)} sessions")
    else:
        line(None, f"ledger {ledger.LEDGER}", "none yet; the first report builds it from the transcripts")
    check_sources(line)
    if False in found:
        sys.exit(1)


def main():
    command, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if command == "record":
        path = json.load(sys.stdin).get("transcript_path")
        # Claude Code gives a SessionEnd hook very little time, so the parsing runs detached (macOS, Linux).
        if path and Path(path).exists() and os.fork() == 0:
            os.setsid()
            ledger.record(Path(path))
    elif command == "report":
        report(args)
    elif command == "prepare":
        prepare(args)
    elif command == "map":
        save(MAPPED, {s: checked(k) for s, k in pairs(args, "map SESSION KEY [SESSION KEY...]")})
    elif command == "note":
        save(NOTES, {checked(k): text for k, text in pairs(args, "note KEY TEXT [KEY TEXT...]")})
    elif command == "check":
        check()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
