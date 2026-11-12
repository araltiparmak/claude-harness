#!/usr/bin/env python3
"""Keeps a ledger of Claude Code sessions and reports them by work type and by epic.

  worklog.py record            SessionEnd hook: reads the hook JSON on stdin, appends that session
  worklog.py report [since]    prints the full Markdown report; since is the first day, YYYY-MM-DD.
                            First records every transcript still in ~/.claude/projects, so a
                            session whose hook did not run is not lost.
  worklog.py html [since]      writes the same report as a page, <dev_dir>/worklog/report.html, and opens it
  worklog.py prs [days]        prints only the pull request part, for the last 30 days or the given number

Settings come from config.json next to this file (see config.example.json); all are optional.
The data lives in <dev_dir>/worklog: sessions.jsonl (the ledger), jira.json (issue cache),
labels.json (session id -> type, for sessions no rule matched), notes/<group>.md (role, impact).
"""
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
from statistics import median
from string import Template

CONFIG = {"dev_dir": "~/dev", "jira_prefixes": [], "support_prefixes": [],
          "jira_cmd": "jira issue view {key} --raw",
          "jira_search_cmd": "jira issue list -q {jql} --raw"}
config_file = Path(__file__).resolve().parent / "config.json"
if config_file.exists():
    CONFIG.update(json.loads(config_file.read_text()))

DEV = Path(CONFIG["dev_dir"]).expanduser()
DATA = DEV / "worklog"
LEDGER = DATA / "sessions.jsonl"
PREFIXES = "|".join(re.escape(p) for p in CONFIG["jira_prefixes"])
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b") if PREFIXES else re.compile(r"(?!)")
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/code-review")
TOKENS = {"in": "input_tokens", "out": "output_tokens",
          "cache_write": "cache_creation_input_tokens", "cache_read": "cache_read_input_tokens"}
PR_QUERY = """query($q: String!, $after: String) {
  viewer { login }
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      title url state isDraft createdAt mergedAt closedAt additions deletions changedFiles
      repository { name }
      reviews(first: 50) { nodes { author { login __typename } state submittedAt comments { totalCount } } }
    } }
  }
}"""


# ---- ledger

def read_session(path):
    """One ledger row for a transcript and its subagent transcripts, or None when no model ran."""
    usage, text, branches = {}, [], []
    row = {"id": path.stem, "title": "", "prompt": "", "cwd": "", "start": "", "end": "",
           "review": False, "edits": False}
    for file in [path, *sorted(path.with_suffix("").glob("subagents/*.jsonl"))]:
        for line in file.open(encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "ai-title":
                row["title"] = d.get("aiTitle", "")
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            stamp = d.get("timestamp") or ""
            row["start"] = row["start"] or stamp
            row["end"] = max(row["end"], stamp)
            row["cwd"] = row["cwd"] or d.get("cwd") or ""
            if d.get("gitBranch") and d["gitBranch"] not in branches:
                branches.append(d["gitBranch"])
            content = msg.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            if d.get("type") == "assistant":
                # A reply is written once per content block, each time with the same usage.
                if msg.get("usage"):
                    usage[msg.get("id")] = msg["usage"]
                for b in blocks:
                    if b.get("type") != "tool_use":
                        continue
                    name, args = b.get("name"), b.get("input") or {}
                    row["edits"] |= name in ("Edit", "Write", "NotebookEdit")
                    row["review"] |= name == "Skill" and args.get("skill") == "code-review"
                    row["review"] |= name == "Bash" and bool(REVIEW.search(args.get("command", "")))
            elif d.get("type") == "user" and not d.get("isMeta"):
                for b in blocks:
                    if b.get("type") == "text":
                        text.append(b.get("text", ""))
    if not usage:
        return None
    said = "\n".join(text)
    row["prompt"] = next((t.strip()[:200] for t in text if t.strip() and not t.lstrip().startswith("<")), "")
    row["branches"] = branches
    row["keys"] = list(dict.fromkeys(KEY.findall(" ".join(branches) + "\n" + said)))
    row["alert"] = "pagerduty.com" in said.lower()
    row["review"] |= bool(REVIEW.search(said))
    row["tokens"] = {k: sum(u.get(field) or 0 for u in usage.values()) for k, field in TOKENS.items()}
    return row


def append(paths):
    DATA.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as out:
        for path in paths:
            row = read_session(path)
            if row:
                out.write(json.dumps(row) + "\n")


def load(name):
    file = DATA / name
    return json.loads(file.read_text()) if file.exists() else {}


# ---- Jira

class Jira:
    """Jira through the two commands in the config. Stops asking after the first failure."""

    def __init__(self):
        self.cache, self.down = load("jira.json"), not PREFIXES

    def run(self, template, **values):
        if self.down:
            return None
        try:
            cmd = [part.format(**values) for part in CONFIG[template].split()]
            return json.loads(subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout)
        except Exception as err:  # CLI missing, not logged in, unknown key, output that is not JSON
            print(f"note: Jira is not answering ({err}); tickets are grouped by key, Jira sections are left out\n",
                  file=sys.stderr)
            self.down = True

    def search(self, jql):
        found = self.run("jira_search_cmd", jql=jql) or []
        return found if isinstance(found, list) else found.get("issues", [])

    def issue(self, key):
        """Summary, type and parent of one issue, cached in jira.json."""
        if key not in self.cache:
            fields = (self.run("jira_cmd", key=key) or {}).get("fields")
            if not fields:
                return {}
            parent = fields.get("parent") or {}
            self.cache[key] = {"summary": fields.get("summary", ""), "type": fields["issuetype"]["name"],
                               "parent": parent.get("key", ""),
                               "parent_summary": (parent.get("fields") or {}).get("summary", "")}
        return self.cache[key]

    def group(self, key, repo):
        """The epic a ticket belongs to, the ticket itself when Jira is silent, else the repo."""
        if not key:
            return repo
        issue = self.issue(key)
        if issue.get("parent"):
            return f"{issue['parent']} {issue['parent_summary']}".strip()
        if issue and issue["type"] != "Epic":
            return "Tasks without an epic"
        return f"{key} {issue.get('summary', '')}".strip()

    def delivery(self, since):
        """(type, tickets resolved, median days from created to resolved) for the tickets assigned to you."""
        types = defaultdict(list)
        for issue in self.search(f'assignee = currentUser() AND resolved >= "{since}"'):
            fields = issue["fields"]
            support = issue["key"].split("-")[0] in CONFIG["support_prefixes"]
            days = hours(fields["created"], fields["resolutiondate"]) / 24
            types["Support" if support else fields["issuetype"]["name"]].append(days)
        return [(name, len(days), f"{median(days):.1f}") for name, days in sorted(types.items(), key=lambda t: -len(t[1]))]

    def shares(self, epics):
        """Per epic key: 'yours of all' tickets."""
        if not epics:
            return {}
        inside = f"parent in ({', '.join(sorted(epics))})"
        count = lambda issues: defaultdict(int, {e: sum(i["fields"]["parent"]["key"] == e for i in issues) for e in epics})
        everyone, mine = count(self.search(inside)), count(self.search(inside + " AND assignee = currentUser()"))
        return {e: f"{mine[e]} of {everyone[e]}" for e in epics if everyone[e]}


# ---- pull requests

def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def day(stamp):
    """2026-10-09 as 9 Oct 2026."""
    d = date.fromisoformat(stamp[:10])
    return f"{d.day} {d:%b %Y}"


def hours(start, end):
    # The time zone is dropped: GitHub gives UTC, and Jira gives both ends in the same zone.
    moment = lambda stamp: datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    return (moment(end) - moment(start)).total_seconds() / 3600


def span(values):
    """The median of some hours, in words: 40 min, 5 hours, 3 days."""
    if not values:
        return "-"
    h = median(values)
    if h < 1:
        return f"{max(1, round(h * 60))} min"
    return plural(round(h), "hour") if h < 48 else plural(round(h / 24), "day")


def search_prs(query):
    """(your login, the pull requests a GitHub search finds), with their reviews."""
    prs, after, login = [], None, ""
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={PR_QUERY}", "-f", f"q={query}"]
        try:
            data = json.loads(subprocess.run(cmd + (["-f", f"after={after}"] if after else []),
                                             capture_output=True, timeout=60, check=True).stdout)["data"]
        except Exception as err:
            print(f"note: could not read pull requests with gh ({err})\n", file=sys.stderr)
            return login, prs
        login = data["viewer"]["login"]
        prs += [pr for pr in data["search"]["nodes"] if pr]
        after = data["search"]["pageInfo"]["endCursor"]
        if not data["search"]["pageInfo"]["hasNextPage"]:
            return login, prs


def status(pr):
    if pr["state"] == "OPEN":
        return "draft" if pr["isDraft"] else "open"
    return "merged" if pr["state"] == "MERGED" else "closed without merge"


def reviews_by(pr, login, others):
    """The reviews by people other than you, or only yours. Bots are left out."""
    return [r for r in pr["reviews"]["nodes"]
            if r["author"] and r["author"]["__typename"] == "User" and (r["author"]["login"] != login) == others]


def pull_requests(since):
    """The PRs you opened and the reviews you gave since the given day, as plain data."""
    login, mine = search_prs(f"is:pr author:@me created:>={since}")
    opened, first, merge, counts = [], [], [], defaultdict(int)
    for pr in sorted(mine, key=lambda p: p["createdAt"]):
        theirs = reviews_by(pr, login, others=True)
        wait = [hours(pr["createdAt"], min(r["submittedAt"] for r in theirs))] if theirs else []
        took = [hours(pr["createdAt"], pr["mergedAt"])] if pr["mergedAt"] else []
        first, merge = first + wait, merge + took
        counts[status(pr)] += 1
        opened.append({"date": pr["createdAt"][:10], "repo": pr["repository"]["name"], "title": pr["title"],
                       "url": pr["url"], "status": status(pr), "first": span(wait), "merge": span(took),
                       "asked": sum(r["state"] == "CHANGES_REQUESTED" for r in theirs),
                       "size": f"+{pr['additions']} -{pr['deletions']}, {pr['changedFiles']} files"})
    _, reviewed = search_prs(f"is:pr reviewed-by:@me -author:@me updated:>={since}")
    given = [(pr, [r for r in reviews_by(pr, login, others=False) if r["submittedAt"][:10] >= since]) for pr in reviewed]
    given = [(pr, rs) for pr, rs in given if rs]
    every = [r for _, rs in given for r in rs]
    return {
        "since": since, "opened": opened, "counts": dict(sorted(counts.items())),
        "first": span(first), "merge": span(merge),
        "reviewed": len(given), "repos": len({pr["repository"]["name"] for pr, _ in given}),
        "reviews": len(every), "comments": sum(r["comments"]["totalCount"] for r in every),
        "approvals": sum(r["state"] == "APPROVED" for r in every),
        "changes": sum(r["state"] == "CHANGES_REQUESTED" for r in every),
        # Measured from the day the PR was opened: GitHub search does not say when you were asked.
        "turnaround": span([hours(pr["createdAt"], min(r["submittedAt"] for r in rs)) for pr, rs in given]),
    }


PR_HEAD = ["Opened", "Repo", "Pull request", "Status", "Changes requested", "First review", "Merged after", "Size"]


def pr_lines(prs):
    """The summary lines under the PR table and under the reviews heading."""
    counts = ", ".join(f"{n} {name}" for name, n in prs["counts"].items())
    medians = [f"to {what} {took}" for what, took in (("first review", prs["first"]), ("merge", prs["merge"])) if took != "-"]
    return ([f"Opened {len(prs['opened'])}{': ' + counts if counts else ''}"]
            + ([f"Median time {', '.join(medians)}"] if medians else []),
            [f"{plural(prs['reviewed'], 'pull request')} reviewed in {plural(prs['repos'], 'repo')}, "
             f"{plural(prs['reviews'], 'review')}, {plural(prs['comments'], 'inline comment')}",
             f"{plural(prs['approvals'], 'approval')}, {plural(prs['changes'], 'request')} for changes",
             f"Median time from PR opened to your first review {prs['turnaround']}"])


def print_prs(prs):
    print(f"## Pull requests you opened since {prs['since']}\n\n| {' | '.join(PR_HEAD)} |\n|{'---|' * len(PR_HEAD)}")
    for pr in prs["opened"]:
        print(f"| {pr['date']} | {pr['repo']} | [{pr['title']}]({pr['url']}) | {pr['status']} | {pr['asked']} "
              f"| {pr['first']} | {pr['merge']} | {pr['size']} |")
    opened, given = pr_lines(prs)
    print("\n" + "\n".join(f"- {line}" for line in opened))
    print(f"\n## Reviews you gave since {prs['since']}\n\n" + "\n".join(f"- {line}" for line in given) + "\n")


# ---- report

def ticket(row):
    support = [k for k in row["keys"] if k.split("-")[0] in CONFIG["support_prefixes"]]
    return (support or row["keys"] or [""])[0]


def kind(row, labels):
    if row["alert"]:
        return "alert"
    if ticket(row).split("-")[0] in CONFIG["support_prefixes"]:
        return "support"
    if row["review"] and not row["edits"]:
        return "review"
    return "task" if row["keys"] else labels.get(row["id"], "other")


def repo_of(row):
    cwd = Path(row["cwd"] or "/")
    return cwd.relative_to(DEV).parts[0] if cwd.is_relative_to(DEV) and cwd != DEV else cwd.name or "/"


def amount(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k"


STATS_HEAD = ["Sessions", "Days", "First", "Last", "Output tokens", "All tokens"]


def stats(groups):
    """Per group, most sessions first: (name, the STATS_HEAD values)."""
    found = []
    for name, rows in sorted(groups.items(), key=lambda g: -len(g[1])):
        days = sorted({r["start"][:10] for r in rows})
        out = sum(r["tokens"]["out"] for r in rows)
        total = sum(sum(r["tokens"].values()) for r in rows)
        found.append((name, [len(rows), len(days), days[0], days[-1], amount(out), amount(total)]))
    return found


def collect(since):
    """Everything the report shows, as plain data. Records the transcripts still on disk first."""
    append(sorted((Path.home() / ".claude" / "projects").glob("*/*.jsonl")))
    rows = {}
    for line in LEDGER.open():
        row = json.loads(line)
        rows[row["id"]] = row  # a session is recorded more than once; the last row wins
    rows = [r for r in rows.values() if r["start"][:10] >= since]
    if not rows:
        sys.exit(f"no sessions in {LEDGER}")
    since = since or min(r["start"][:10] for r in rows)
    jira, labels = Jira(), load("labels.json")
    kinds, groups, tickets, opened = defaultdict(list), defaultdict(list), defaultdict(set), defaultdict(list)
    months = defaultdict(lambda: defaultdict(int))
    for row in rows:
        kinds[kind(row, labels)].append(row)
        months[row["start"][:7]][kind(row, labels)] += 1
        group = jira.group(ticket(row), repo_of(row))
        groups[group].append(row)
        if ticket(row):
            tickets[group].add(f"{ticket(row)} {jira.issue(ticket(row)).get('summary', '')}".strip())
    prs = pull_requests(since)
    for pr in prs["opened"]:
        key = KEY.search(pr["title"])
        opened[jira.group(key and key.group(), pr["repo"])].append(pr)
    shares = jira.shares({g.split()[0] for g in set(groups) | set(opened) if KEY.fullmatch(g.split()[0])})
    details = []
    for group in sorted(set(groups) | set(opened), key=lambda g: -len(groups[g])):
        note = DATA / "notes" / f"{group.split()[0]}.md"
        detail = {"group": group, "note": note.read_text().strip() if note.exists() else "",
                  "share": shares.get(group.split()[0], ""), "tickets": sorted(tickets[group]), "prs": opened[group],
                  "days": sorted({r["start"][:10] for r in groups[group]}), "sessions": len(groups[group])}
        if detail["note"] or detail["share"] or detail["tickets"] or detail["prs"]:
            details.append(detail)
    data = {
        "since": since, "last": max(r["start"][:10] for r in rows),
        "days": len({r["start"][:10] for r in rows}), "sessions": len(rows),
        "kinds": stats(kinds), "months": {m: dict(months[m]) for m in sorted(months)},
        "groups": stats(groups), "delivery": jira.delivery(since), "prs": prs, "details": details,
        "timeline": [(name, sorted({r["start"][:10] for r in groups[name]}), values[0]) for name, values in stats(groups)],
        "untyped": [f"{r['id']} {r['start'][:10]} {repo_of(r)}: {r['title'] or r['prompt']}"
                    for r in kinds.get("other", []) if PREFIXES],
    }
    if jira.cache:
        (DATA / "jira.json").write_text(json.dumps(jira.cache, indent=1))
    return data


def print_report(data):
    def table(title, head, found):
        print(f"## {title}\n\n| {' | '.join([head] + STATS_HEAD)} |\n|{'---|' * (len(STATS_HEAD) + 1)}")
        for name, values in found:
            print(f"| {name} | {' | '.join(map(str, values))} |")
        print()

    names = [name for name, _ in data["kinds"]]
    print(f"# Work with Claude Code since {data['since']}\n")
    table("By type", "Type", data["kinds"])
    print(f"## Sessions per month\n\n| Month | {' | '.join(names)} |\n|---|{'---|' * len(names)}")
    for month, counts in data["months"].items():
        print(f"| {month} | {' | '.join(str(counts.get(k, 0)) for k in names)} |")
    print()
    table("By epic or project", "Group", data["groups"])
    if data["delivery"]:
        print("## Jira tickets resolved\n\n| Type | Resolved | Median days from created to resolved |\n|---|---|---|")
        for row in data["delivery"]:
            print(f"| {' | '.join(map(str, row))} |")
        print()
    print_prs(data["prs"])
    print("## Epics and projects in detail\n")
    for d in data["details"]:
        lines = ([f"Your share: {d['share']} tickets"] if d["share"] else []) + d["tickets"] + [
            f"PR {pr['date']} {pr['status']}: {pr['title']} {pr['url']}" for pr in d["prs"]]
        print(f"### {d['group']}\n\n" + (d["note"] + "\n\n" if d["note"] else "") + "\n".join(f"- {line}" for line in lines) + "\n")
    if data["untyped"]:
        print("## Sessions without a type\n\n" + "\n".join(f"- {line}" for line in data["untyped"]))


# ---- page

# Per type: its place in the palette (a type keeps its colour in every report), its name and
# its meaning in words a reader outside the team understands.
TYPES = {"task": (1, "Planned work", "Jira tasks and epics"),
         "review": (2, "Code review", "Reviews of pull requests from teammates"),
         "alert": (3, "Incidents", "PagerDuty alerts"),
         "support": (4, "Support", "Investigations for support tickets"),
         "other": (5, "Other", "Work without a ticket")}
STATUS = {"merged": "✓ Merged", "closed without merge": "✕ Closed, not merged",
          "open": "○ Open", "draft": "○ Draft"}
READING = [
    ("Session", "One working conversation with Claude Code, the AI coding assistant. Sessions show where the "
                "effort went. They do not measure hours."),
    ("Active day", "A day with at least one session."),
    ("First review after", "The time from opening a pull request to the first review by a person."),
    ("Merged after", "The time from opening a pull request to its merge."),
    ("Sources", "Pull requests and reviews come from GitHub, tickets and epics from Jira, sessions from the "
                "records Claude Code keeps on this computer."),
]


def tag(name, text, **attrs):
    """One HTML element. Text is escaped; pass a list for content that is already HTML."""
    inner = "".join(text) if isinstance(text, list) else html.escape(str(text))
    shown = "".join(' %s="%s"' % (k.strip("_").replace("_", "-"), html.escape(str(v))) for k, v in attrs.items())
    return f"<{name}{shown}>{inner}</{name}>"


def grid(head, rows, look="scroll"):
    """An HTML table. A cell that is a (text, url, small print) tuple becomes a link with a line under it."""
    link = lambda c: tag("td", [tag("a", c[0], href=c[1]), tag("small", c[2])])
    return tag("div", [tag("table", [tag("tr", [tag("th", h) for h in head])] + [
        tag("tr", [link(c) if isinstance(c, tuple) else tag("td", c) for c in row]) for row in rows])], class_=look)


def section(title, intro, *parts):
    return tag("section", [tag("h2", title)] + ([tag("p", intro, class_="intro")] if intro else []) + list(parts))


def summary(data):
    """The opening: the period, one sentence a manager can repeat, and the headline numbers."""
    prs, tickets = data["prs"], sum(n for _, n, _ in data["delivery"])
    merged = [pr for pr in prs["opened"] if pr["status"] == "merged"]
    done = [f"{plural(len(merged), 'pull request')} merged in {plural(len({pr['repo'] for pr in merged}), 'repo')}",
            f"{plural(prs['reviewed'], 'pull request')} reviewed for teammates"]
    tiles = [("Pull requests merged", len(merged), f"of {len(prs['opened'])} opened"),
             ("Reviews for teammates", prs["reviewed"], f"{plural(prs['reviews'], 'review')}, {plural(prs['comments'], 'comment')}")]
    if data["delivery"]:
        done.append(f"{plural(tickets, 'Jira ticket')} resolved")
        tiles.append(("Tickets resolved", tickets, "assigned to me in Jira"))
    tiles += [("Epics and projects", len(data["groups"]), "each one is listed below"),
              ("Active days", data["days"], f"{plural(data['sessions'], 'session')} with Claude Code")]
    lede = (f"In this period: {', '.join(done[:-1])} and {done[-1]}. "
            f"The work covered {plural(len(data['groups']), 'epic or project').replace('epic or projects', 'epics and projects')} "
            f"on {plural(data['days'], 'active day')}.")
    return tag("header", [
        tag("h1", "Work summary"), tag("p", f"{day(data['since'])} to {day(data['last'])}", class_="period"),
        tag("p", lede, class_="lede"),
        tag("div", [tag("div", [tag("span", label), tag("b", value), tag("small", caption)])
                    for label, value, caption in tiles], class_="tiles")])


def timeline(data):
    """Each epic or project as a row across the period, with a mark on every day it had work."""
    start, end = date.fromisoformat(data["since"]), date.fromisoformat(data["last"])
    length = (end - start).days + 1
    at = lambda d: (d - start).days / length * 100
    firsts, month = [], start.replace(day=1)
    while month <= end:
        if month >= start:
            firsts.append(month)
        month = (month + timedelta(days=32)).replace(day=1)
    ticks = [tag("u", "", style=f"left:{at(m)}%") for m in firsts]
    labels = [tag("span", f"{m.day} {m:%b}", style=f"left:{at(m)}%") for m in firsts]
    if not firsts or at(firsts[0]) > 12:
        labels.insert(0, tag("span", f"{start.day} {start:%b}", style="left:0"))
    rows = [tag("div", [tag("span", ""), tag("span", labels, class_="axis"), tag("span", "")], class_="row")]
    for name, days, sessions in data["timeline"][:12]:
        marks = [tag("i", "", style=f"left:{at(date.fromisoformat(d))}%;width:{100 / length}%") for d in days]
        reach = tag("em", "", style=f"left:{at(date.fromisoformat(days[0]))}%;"
                                    f"width:{at(date.fromisoformat(days[-1])) - at(date.fromisoformat(days[0])) + 100 / length}%")
        tip = f"{name}\n{day(days[0])} to {day(days[-1])}\n{plural(len(days), 'active day')}\n{plural(sessions, 'session')}"
        rows.append(tag("div", [tag("span", name, class_="name"), tag("span", ticks + [reach] + marks, class_="track"),
                                tag("span", plural(len(days), "day"), class_="value")],
                        class_="row", tabindex=0, data_tip=tip))
    more = len(data["timeline"]) - 12
    note = [tag("p", f"{plural(more, 'smaller item')} not drawn; all are in the appendix.", class_="quiet")] if more > 0 else []
    return tag("div", rows, class_="timeline") + "".join(note)


def cards(data):
    """One card per epic or project that has a note, tickets or pull requests: the outcome first."""
    found = []
    for d in data["details"]:
        merged = sum(pr["status"] == "merged" for pr in d["prs"])
        reach = " to ".join(dict.fromkeys([day(d["days"][0]), day(d["days"][-1])])) if d["days"] else ""
        facts = ([f"Active {reach}", plural(len(d["days"]), "day")] if reach else []) \
            + ([f"{d['share']} tickets were mine"] if d["share"] else []) \
            + ([f"{plural(merged, 'pull request')} merged"] if merged else [])
        parts = [tag("h3", d["group"]), tag("p", " · ".join(facts), class_="facts")]
        if d["note"]:
            parts.append(tag("p", d["note"], class_="outcome"))
        if d["tickets"]:
            parts += [tag("h4", "Tickets"), tag("ul", [tag("li", t) for t in d["tickets"]])]
        if d["prs"]:
            parts += [tag("h4", "Pull requests"), tag("ul", [
                tag("li", [tag("a", pr["title"], href=pr["url"]),
                           html.escape(f" · {STATUS[pr['status']]} · {day(pr['date'])}")]) for pr in d["prs"]])]
        found.append(tag("article", parts))
    return "".join(found)


def split(kinds, total):
    """One bar for all sessions, cut by type of work, with a table that names each part."""
    kinds = sorted(kinds, key=lambda k: TYPES.get(k[0], TYPES["other"])[0])  # neighbours in the bar are neighbours in the palette
    parts, rows = [], []
    for name, values in kinds:
        slot, title, meaning = TYPES.get(name, TYPES["other"])
        share = round(values[0] / total * 100)
        parts.append(tag("i", f"{share}%" if share >= 8 else "", class_=f"s{slot}", style=f"flex-grow:{values[0]}",
                         tabindex=0, data_tip=f"{title}\n{share}% of sessions\n{plural(values[0], 'session')}"))
        rows.append(tag("tr", [tag("td", [tag("i", "", class_=f"s{slot}"), html.escape(title)]), tag("td", meaning),
                               tag("td", f"{share}%"), tag("td", plural(values[0], "session")),
                               tag("td", plural(values[1], "day"))]))
    return tag("div", parts, class_="split") + tag("div", [tag("table", rows)], class_="scroll key")


def month_chart(months, names):
    """Sessions per month as stacked columns, one segment per type, with a legend and a table view."""
    names = sorted(names, key=lambda k: TYPES.get(k, TYPES["other"])[0])
    slot, title = lambda k: TYPES.get(k, TYPES["other"])[0], lambda k: TYPES.get(k, TYPES["other"])[1]
    top = max(sum(counts.values()) for counts in months.values())
    step = next(s for s in (m * 10 ** e for e in range(9) for m in (1, 2, 5)) if top / s <= 4)
    ceiling = step * -(-top // step)
    lines = [tag("div", [tag("span", tick)], class_="line", style=f"bottom:{tick / ceiling * 100}%")
             for tick in range(0, ceiling + 1, step)]
    columns = []
    for month, counts in months.items():
        parts = [tag("i", "", class_=f"s{slot(k)}", style=f"height:{counts[k] / ceiling * 100}%") for k in names if counts.get(k)]
        label = f"{date.fromisoformat(month + '-01'):%b %Y}"
        tip = f"{label}\n" + "\n".join(f"{counts[k]}  {title(k)}" for k in names if counts.get(k))
        columns.append(tag("div", parts + [tag("b", sum(counts.values())), tag("span", label)],
                           class_="column", tabindex=0, data_tip=tip))
    legend = [tag("span", [tag("i", "", class_=f"s{slot(k)}"), html.escape(title(k))]) for k in names] if len(names) > 1 else []
    table = grid(["Month"] + [title(k) for k in names], [[m] + [c.get(k, 0) for k in names] for m, c in months.items()])
    return (tag("div", legend, class_="legend") + tag("div", lines + [tag("div", columns, class_="columns")], class_="plot")
            + tag("details", [tag("summary", "Show as table"), table]))


def page(data):
    prs, names = data["prs"], [name for name, _ in data["kinds"]]
    opened, given = pr_lines(prs)
    body = [summary(data),
            section("What the work was, and when",
                    "Each row is an epic or a project. Each mark is a day with work on it.", timeline(data))]
    if data["details"]:
        body.append(section("Outcomes", "", cards(data)))
    effort = [split(data["kinds"], data["sessions"])] if len(names) > 1 else []
    if len(data["months"]) > 1:
        effort += [tag("h3", "Sessions per month"), month_chart(data["months"], names)]
    if effort:
        body.append(section("Where the effort went", "Measured in sessions. The last section explains the terms.", *effort))
    body.append(section(
        "Pull requests", ". ".join(opened) + ".",
        grid(["Opened", "Pull request", "Status", "First review after", "Merged after", "Changes requested", "Size"],
             [[day(pr["date"]), (pr["title"], pr["url"], pr["repo"]), STATUS[pr["status"]], pr["first"], pr["merge"],
               pr["asked"], pr["size"]] for pr in prs["opened"]], "scroll dated")))
    body.append(section("Reviews for teammates", "", tag("ul", [tag("li", line.replace("your", "my")) for line in given])))
    if data["delivery"]:
        body.append(section("Jira tickets resolved", "Tickets assigned to me that reached a resolution in this period.",
                            grid(["Type", "Resolved", "Median days from created to resolved"], data["delivery"])))
    body.append(section("How to read this report", "",
                        tag("dl", [tag("dt", term) + tag("dd", meaning) for term, meaning in READING])))
    body.append(tag("details", [
        tag("summary", "Appendix: all epics and projects, with AI token use"),
        grid(["Type"] + STATS_HEAD, [[TYPES.get(n, TYPES["other"])[1]] + v for n, v in data["kinds"]]),
        grid(["Epic or project"] + STATS_HEAD, [[n] + v for n, v in data["groups"]])], class_="appendix"))
    body.append(tag("footer", f"Generated on {day(str(date.today()))} by worklog."))
    template = Template((Path(__file__).resolve().parent / "report.html").read_text())
    file = DATA / "report.html"
    file.write_text(template.substitute(title=f"Work summary, {day(data['since'])} to {day(data['last'])}", body="\n".join(body)))
    return file


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    argument = sys.argv[2] if len(sys.argv) > 2 else ""
    if command == "record":
        path = json.load(sys.stdin).get("transcript_path")
        # Claude Code gives a SessionEnd hook very little time, so the parsing runs detached.
        if path and Path(path).exists() and os.fork() == 0:
            os.setsid()
            append([Path(path)])
    elif command == "report":
        data = collect(argument)
        print_report(data)
        print(f"\nPage: {page(data)}")
    elif command == "html":
        file = page(collect(argument))
        print(file)
        webbrowser.open(file.as_uri())
    elif command == "prs":
        print_prs(pull_requests(str(date.today() - timedelta(days=int(argument or 30)))))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
