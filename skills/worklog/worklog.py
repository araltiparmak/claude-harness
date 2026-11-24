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

Settings: ~/.config/worklog.json, described in config.py. Data: <DEV_DIR>/worklog, with sessions.jsonl (the
ledger), jira.json (the issue cache), mapped.json (the tickets chosen with map) and notes.json (the outcomes).
ledger.py reads transcripts, page.py writes the HTML, github.py and jira.py fetch pull requests and issues.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import github
import jira
import ledger
import page
from config import DATA, DEV, FILE, settings
from ledger import BIG_CONTEXT, SENT, TOKENS, cost, models_of, repo_of

JIRA_PREFIXES, SUPPORT_PREFIXES, EXCLUDE_REPOS = (
    settings[k] for k in ("jira_prefixes", "support_prefixes", "exclude_repos"))
MAPPED = DATA / "mapped.json"
NOTES = DATA / "notes.json"
PREFIXES = "|".join(re.escape(p) for p in JIRA_PREFIXES)
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b", re.I) if PREFIXES else re.compile(r"[^\s\S]")  # never matches
SUPPORT = {p.upper() for p in SUPPORT_PREFIXES}
TOP = 10  # the most expensive sessions listed
MIN_SESSIONS = 5  # fewer sessions than this give no tips
# A tip shows when its measure crosses its line. The lines are rules of thumb, not targets.
LINES = {"big": 0.5, "cache_hit": 0.85, "idle": 0.25, "opus_questions": 0.10, "interrupted": 0.2,
         "compacted": 3, "subagents": 0.3, "errors": 3}

pull_requests, commit_pulls = github.pull_requests, github.commit_pulls  # demo and tests swap them


# ---- Jira

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
    """The days, cost, cost per model, active minutes, session titles and pull requests of one ticket or sub-task,
    and how many of its sessions came from map."""

    def __init__(self, key, issues):
        issue = issues.issue(key)
        self.key, self.summary, self.type = key, issue.get("summary", ""), issue.get("type", "")
        self.days, self.cost, self.models, self.prs = set(), 0.0, defaultdict(float), []
        self.minutes, self.titles, self.mapped, self.resolved = 0.0, [], 0, False

    def add(self, row, mapped=False):
        self.days.add(row["start"][:10])
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
        self.key, self.issues, self.own, self.subs, self.repos = key, issues, Work(key, issues), {}, {}
        self.resolved = False

    def part(self, key):
        if key == self.key:
            return self.own
        if key not in self.subs:
            self.subs[key] = Work(key, self.issues)
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
    """The sessions that started in the period, oldest first, and the cost of those in exclude_repos."""
    rows = sorted((r for r in rows if since <= r["start"][:10] <= until), key=lambda r: r["start"])
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
    issues, tickets, reviews = Jira(), {}, {"cost": 0.0, "minutes": 0.0}
    other, unmapped = defaultdict(lambda: {"days": set(), "cost": 0.0, "minutes": 0.0}), []

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
            reviews["cost"] += cost(row)
            reviews["minutes"] += row.get("active", 0)
        else:
            other[repo_of(row)]["days"].add(row["start"][:10])
            other[repo_of(row)]["cost"] += cost(row)
            other[repo_of(row)]["minutes"] += row.get("active", 0)
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

def measures(rows):
    """How the sessions used tokens and how smoothly they went, from the ledger alone. A share is of cost over
    the sessions that recorded the field; None when none did, or when too few did for a tip."""
    total = sum(cost(r) for r in rows) or 0.0
    tokens = defaultdict(lambda: dict.fromkeys(TOKENS, 0))
    for r in rows:
        for model, t in r.get("tokens_by_model", {}).items():
            for name in TOKENS:
                tokens[model][name] += t[name]
    sent = sum(t[k] for t in tokens.values() for k in SENT)

    def share(field, part):
        known = [r for r in rows if field in r]
        whole = sum(cost(r) for r in known)
        return sum(part(r) for r in known) / whole if whole else None

    def question(r):
        return not (r["edits"] or r["review"])
    rated = [r for r in rows if "prompts" in r]  # rows recorded before these were kept have none
    contexts = [r for r in rows if "context" in r]
    peaks = [r["context"]["peak"] for r in contexts]
    return {
        "cost": total, "sessions": len(rows), "tokens": {m: t for m, t in tokens.items() if any(t.values())},
        "cache_hit": sum(t["read"] for t in tokens.values()) / sent if sent else None,
        "big": share("context", lambda r: cost(r) if r["context"]["peak"] > BIG_CONTEXT else 0),
        "subagents": share("subagent_cost", lambda r: r["subagent_cost"]),
        "idle": share("edits", lambda r: cost(r) if question(r) else 0),
        "opus_questions": share("edits", lambda r: models_of(r).get("Opus", 0) if question(r) else 0),
        "rated": len(rated),
        "prompts": sum(r["prompts"] for r in rated) / len(rated) if rated else None,
        "interrupted": sum(r["interrupts"] > 0 for r in rated) / len(rated) if rated else None,
        "errors": sum(r["errors"] for r in rated) / len(rated) if rated else None,
        "context": {"sessions": len(contexts), "avg": sum(r["context"]["avg"] for r in contexts) // max(len(contexts), 1),
                    "peak_avg": sum(peaks) // max(len(peaks), 1), "peak": max(peaks, default=0),
                    "big": sum(p > BIG_CONTEXT for p in peaks)},
        "compacted": sum(r["context"]["compactions"] > 0 for r in contexts),
        "top": sorted(rows, key=lambda r: -cost(r))[:TOP]}


def tips(m):
    """What to try, from the measures that crossed their LINES: (measure, advice) pairs, the costliest habit
    first. None with fewer than MIN_SESSIONS sessions."""
    if m["sessions"] < MIN_SESSIONS:
        return []
    found = []

    def over(name):
        return m[name] is not None and m[name] > LINES[name]
    if over("big"):
        found.append((f"{m['big']:.0%} of the cost came from sessions whose context grew past "
                      f"{BIG_CONTEXT // 1000}k tokens.",
                      "Every reply re-reads the whole context, so a long session gets dearer with each turn. Start a "
                      "fresh session for each task (/clear), and point Claude at files and line ranges instead of "
                      "whole folders."))
    if m["cache_hit"] is not None and m["cache_hit"] < LINES["cache_hit"]:
        found.append((f"Only {m['cache_hit']:.0%} of the input came from the prompt cache.",
                      "The cache expires after a pause (5 minutes by default), and the next reply pays full price for "
                      "the whole context. Finish a task in one sitting, or start fresh after a long break instead of "
                      "resuming."))
    if over("opus_questions"):
        found.append((f"Sessions that only asked questions spent {m['opus_questions']:.0%} of the cost on Opus.",
                      "Sonnet answers most questions well for less; switch with /model."))
    if over("idle"):
        found.append((f"{m['idle']:.0%} of the cost went to sessions that changed no files and reviewed nothing.",
                      "Questions are fine. For exploration, a narrower first prompt (the file, the symptom, what you "
                      "expect) usually gets there in fewer turns."))
    if over("subagents"):
        found.append((f"Subagents used {m['subagents']:.0%} of the cost.",
                      "Each one starts with an empty context and reads everything again; keep them for wide searches "
                      "and independent work, not small steps."))
    if m["rated"] >= MIN_SESSIONS and over("interrupted"):
        found.append((f"You stopped Claude in {m['interrupted']:.0%} of sessions.",
                      "That often means it set off in the wrong direction. Plan mode (shift+tab) or a first prompt that "
                      "states the goal and the limits helps it start right."))
    if m["compacted"] >= LINES["compacted"]:
        found.append((f"{m['compacted']} sessions ran out of context and were compacted.",
                      "Compaction loses detail. Split long tasks into sessions, with a short hand-over note."))
    if m["rated"] >= MIN_SESSIONS and over("errors"):
        found.append((f"Tool calls failed {m['errors']:.1f} times per session.",
                      "Repeated failures often mean a missing permission, a wrong working folder or a missing tool; "
                      "the most expensive sessions show where."))
    return found


def usage_of(rows):
    """What the sessions used, as {kind: {name: [uses, sessions]}} for skills, MCP servers and subagents (a slash
    command counts as a skill when a skill of that name is installed or it names a plugin skill), cost per day
    per model, and the peak context of each session."""
    folder = Path.home() / ".claude" / "skills"
    installed = {p.name for p in folder.iterdir()} if folder.is_dir() else set()
    found = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        used = r.get("used", {})
        skills = dict(used.get("skill", {}))
        for name, n in used.get("command", {}).items():
            if name in installed or ":" in name:
                skills[name] = skills.get(name, 0) + n
        for kind, counts in (("skill", skills), ("mcp", used.get("mcp", {})), ("agent", used.get("agent", {}))):
            for name, n in counts.items():
                found[kind][name][0] += n
                found[kind][name][1] += 1
    found["daily"] = defaultdict(lambda: defaultdict(float))  # day: {model family: cost}
    for r in rows:
        for model, usd in models_of(r).items():
            found["daily"][r["start"][:10]][model] += usd
    found["peaks"] = [(r["start"][:10], r["context"]["peak"], r["title"] or r["prompt"][:60])
                      for r in rows if "context" in r]
    return found


# ---- commands

def period(arg):
    """(first day, last day) as YYYY-MM-DD: this month by default, the month before for 'last-month', or from
    a given day to today."""
    today = date.today()
    if arg == "last-month":
        last = today.replace(day=1) - timedelta(days=1)
        return str(last.replace(day=1)), str(last)
    if arg and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
        sys.exit(f"period must be empty, last-month or YYYY-MM-DD, not {arg}")
    return (arg or str(today.replace(day=1))), str(today)


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
    assigned = data["jira"].ask(jira.updated, since, until) or {}
    busy = {d: data["jira"].ask(jira.in_progress, d) or {} for d in sorted({r["start"][:10] for r in data["unmapped"]})}
    print(json.dumps({
        "sessions": [{"id": r["id"], "date": r["start"][:10], "repo": repo_of(r), "branches": r["branches"],
                      "title": r["title"], "prompt": r["prompt"], "cost": round(cost(r), 2),
                      "in_progress": busy[r["start"][:10]]}
                     for r in data["unmapped"]],
        "tickets": [{"key": t.key, "summary": t.own.summary, "type": t.own.type, "repos": list(t.repos),
                     "cost": round(t.cost, 2), "hours": round(t.minutes / 60, 1), "note": data["notes"].get(t.key, ""),
                     "subtasks": [{"key": w.key, "summary": w.summary} for w in t.subs.values()],
                     "pull_requests": [pr["title"] for w in t.works for pr in w.prs],
                     "sessions": list(dict.fromkeys(title for w in t.works for title in w.titles if title))}
                    for t in tickets],
        "assigned": {key: issue for key, issue in assigned.items() if key not in shown}},
        indent=1, ensure_ascii=False))


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


def check():
    """One line per part of the setup: ok, warn (the report runs but misses something) or FAIL; exits 1 on a FAIL."""
    found = []

    def line(ok, what, fix=""):
        found.append(ok)
        print(f"{'ok  ' if ok is True else 'warn' if ok is None else 'FAIL'}  {what}" + (f": {fix}" if fix and ok is not True else ""))

    def runs(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    line(FILE.exists() or None, f"settings {FILE}", "not found; config.py lists the keys")
    line(bool(PREFIXES) or None, f"jira_prefixes {', '.join(JIRA_PREFIXES)}".strip(), "empty, so no session finds a ticket")
    line(DEV.is_dir() or None, f"dev_dir {DEV}", "not a folder; sessions are named by their own folder")
    live = Path.home() / ".claude" / "settings.json"
    try:
        claude = json.loads(live.read_text()) if live.exists() else {}
    except ValueError:
        claude = {}
        line(False, str(live), "not valid JSON")
    hooked = "worklog.py record" in json.dumps(claude.get("hooks", {}).get("SessionEnd", []))
    line(hooked or None, "SessionEnd hook", "missing; README.md shows the lines to add")
    keep = claude.get("cleanupPeriodDays", 30)
    line(keep >= 60 or None, f"transcripts kept {keep} days", 'set "cleanupPeriodDays": 90 so report catches '
                                                              "sessions the hook missed")
    if ledger.LEDGER.exists():
        with ledger.LEDGER.open() as rows:
            line(True, f"ledger {ledger.LEDGER}, {sum(1 for _ in rows)} sessions")
    else:
        line(None, f"ledger {ledger.LEDGER}", "none yet; the first report builds it from the transcripts")
    line(runs(["git", "config", "user.email"]) or None, "git user.email", "not set; commits cannot find their pull requests")
    line(bool(shutil.which("gh")) and runs(["gh", "auth", "status"]) or None, "gh",
         "not installed or not logged in (gh auth login); no pull requests or reviews")
    if PREFIXES:
        try:
            jira.search("updated >= -1d")
            line(True, "Jira search")
        except Exception as err:  # CLI missing, not logged in, output that is not JSON
            line(None, "Jira search", f"failed ({err}); tickets show by key only")
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
        if (Path(__file__).resolve().parent / "demo.py").exists():  # a local add-on, kept out of the repo
            import demo
            demo.main(args)
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
