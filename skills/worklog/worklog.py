#!/usr/bin/env python3
"""Keeps a ledger of Claude Code sessions and writes a one-page work summary from it.

  worklog.py record           SessionEnd hook: reads the hook JSON on stdin, appends that session
  worklog.py report [period] [--no-cost]
                              writes <dev_dir>/worklog/report.html, opens it and prints the counts.
                              period is empty for this month, last-month, or a first day YYYY-MM-DD
                              (up to today); --no-cost leaves every cost out.
                              First records every transcript still in ~/.claude/projects, so a
                              session whose hook did not run is not lost.

Settings come from config.json next to this file (see config.example.json); all are optional.
The data lives in <dev_dir>/worklog: sessions.jsonl (the ledger) and jira.json (issue cache).
"""
import html
import json
import os
import re
import subprocess
import sys
import webbrowser
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from string import Template

CONFIG = {"dev_dir": "~/dev", "jira_prefixes": [], "support_prefixes": [], "jira_url": "", "exclude_repos": [],
          "jira_cmd": "jira issue view {key} --raw",
          "jira_search_cmd": "jira issue list -q {jql} --raw"}
HERE = Path(__file__).resolve().parent
if (HERE / "config.json").exists():
    CONFIG.update(json.loads((HERE / "config.json").read_text()))

DEV = Path(CONFIG["dev_dir"]).expanduser()
DATA = DEV / "worklog"
LEDGER = DATA / "sessions.jsonl"
PREFIXES = "|".join(re.escape(p) for p in CONFIG["jira_prefixes"])
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b", re.I) if PREFIXES else re.compile(r"[^\s\S]")  # never matches
# The ledger keeps every key-shaped word; the report keeps the ones with a configured prefix.
KEY_SHAPE = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}-\d+\b")
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/code-review")
ALERT = re.compile(r"https://[\w-]+\.pagerduty\.com/", re.I)
TOKENS = {"in": "input_tokens", "out": "output_tokens",
          "cache_write": "cache_creation_input_tokens", "cache_read": "cache_read_input_tokens"}
# API list prices in USD per million tokens: input, output, cache read. A cache write costs 1.25x input
# for 5 minutes, 2x for 1 hour; fast mode costs 2x. An id not listed is priced as claude-opus-5-5.
PRICES = {"claude-opus-5-5": (4, 20, 0.20), "claude-opus-5": (5, 25, 0.50), "claude-opus-4": (5, 25, 0.50),
          "claude-sonnet-5-5": (2, 10, 0.10), "claude-sonnet-5": (2, 10, 0.20), "claude-sonnet-4": (3, 15, 0.30)}
PR_QUERY = """query($q: String!, $after: String) {
  viewer { login }
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      title url state isDraft createdAt headRefName body author { login } repository { name }
      reviews(first: 50) { nodes { author { login } submittedAt } }
      commits(first: 100) { nodes { commit { message } } }
    } }
  }
}"""
SHOW_COST = True  # report --no-cost turns it off
STATUS = {"merged": "✓ Merged", "closed": "✕ Closed, not merged", "open": "○ Open", "draft": "○ Draft"}


# ---- ledger

def records(path):
    """The parsed lines of a transcript and of its subagent transcripts."""
    for file in [path, *sorted(path.with_suffix("").glob("subagents/*.jsonl"))]:
        for line in file.open(encoding="utf-8", errors="replace"):
            try:
                yield json.loads(line)
            except ValueError:
                pass


def note_place(row, d, branches):
    """When and where the session ran."""
    stamp = d.get("timestamp") or ""
    row["start"] = row["start"] or stamp
    row["end"] = max(row["end"], stamp)
    row["cwd"] = row["cwd"] or d.get("cwd") or ""
    if d.get("gitBranch") and d["gitBranch"] not in branches:
        branches.append(d["gitBranch"])


def note_tools(row, blocks, commands):
    """Whether a reply edited files or ran a review, and the shell commands it ran."""
    for b in blocks:
        if b.get("type") != "tool_use":
            continue
        name, args = b.get("name"), b.get("input") or {}
        row["edits"] |= name in ("Edit", "Write", "NotebookEdit")
        row["review"] |= name == "Skill" and args.get("skill") == "code-review"
        row["review"] |= name == "Bash" and bool(REVIEW.search(args.get("command", "")))
        if name == "Bash":
            commands.append(args.get("command", ""))


def price(usage):
    """What one reply cost in USD at API list prices."""
    model = usage.get("model") or ""
    rates = next((PRICES[m] for m in sorted(PRICES, key=len, reverse=True) if model.startswith(m)),
                 PRICES["claude-opus-5-5"])
    hour = (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
    minutes = (usage.get("cache_creation_input_tokens") or 0) - hour
    paid = [(usage.get("input_tokens") or 0) + 1.25 * minutes + 2 * hour,
            usage.get("output_tokens") or 0, usage.get("cache_read_input_tokens") or 0]
    return sum(n * rate for n, rate in zip(paid, rates)) / 1e6 * (2 if usage.get("speed") == "fast" else 1)


def blocks_of(msg):
    content = msg.get("content")
    return content if isinstance(content, list) else [{"type": "text", "text": content or ""}]


def read_session(path):
    """One ledger row for a transcript and its subagent transcripts, or None when no model ran."""
    usage, text, branches, commands = {}, [], [], []
    row = {"id": path.stem, "title": "", "prompt": "", "cwd": "", "start": "", "end": "",
           "review": False, "edits": False}
    for d in records(path):
        if d.get("type") == "ai-title":
            row["title"] = d.get("aiTitle", "")
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        note_place(row, d, branches)
        blocks = blocks_of(msg)
        if d.get("type") == "assistant":
            # A reply is written once per content block, each time with the same usage.
            if msg.get("usage"):
                usage[msg.get("id")] = {**msg["usage"], "model": msg.get("model")}
            note_tools(row, blocks, commands)
        elif d.get("type") == "user" and not d.get("isMeta"):
            text += [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return finish(row, usage, text, branches, commands) if usage else None


def finish(row, usage, text, branches, commands):
    """Fills in the fields that need the whole session."""
    said = "\n".join(text)
    row["prompt"] = next((t.strip()[:200] for t in text if t.strip() and not t.lstrip().startswith("<")), "")
    row["branches"] = branches
    words = KEY_SHAPE.findall(" ".join(branches) + "\n" + said + "\n" + "\n".join(commands))
    row["keys"] = list(dict.fromkeys(k.upper() for k in words))
    row["alert"] = bool(ALERT.search(said))
    row["review"] |= bool(REVIEW.search(said))
    row["tokens"] = {k: sum(u.get(field) or 0 for u in usage.values()) for k, field in TOKENS.items()}
    row["cost"] = round(sum(price(u) for u in usage.values()), 4)
    return row


def append(paths):
    DATA.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as out:
        for path in paths:
            row = read_session(path)
            if row:
                out.write(json.dumps(row) + "\n")


# ---- Jira and GitHub

class Jira:
    """Jira through the two commands in the config. Stops asking after the first failure."""

    def __init__(self):
        file = DATA / "jira.json"
        self.cache, self.down = json.loads(file.read_text()) if file.exists() else {}, not PREFIXES

    def run(self, template, **values):
        if self.down:
            return None
        try:
            cmd = [part.format(**values) for part in CONFIG[template].split()]
            return json.loads(subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout)
        except Exception as err:  # CLI missing, not logged in, unknown key, output that is not JSON
            print(f"note: Jira is not answering ({err}); tickets are shown by key only\n", file=sys.stderr)
            self.down = True

    def issue(self, key):
        """Summary, type and parent of one issue, cached in jira.json. An entry cached before sub-tasks were
        noted is read again."""
        if "subtask" not in self.cache.get(key, {}):
            fields = (self.run("jira_cmd", key=key) or {}).get("fields")
            if not fields:
                return {}
            parent = fields.get("parent") or {}
            self.cache[key] = {"summary": fields.get("summary", ""), "type": fields["issuetype"]["name"],
                               "subtask": bool(fields["issuetype"].get("subtask")),
                               "parent": parent.get("key", ""),
                               "parent_summary": (parent.get("fields") or {}).get("summary", "")}
        return self.cache[key]

    def top(self, key):
        """The ticket the report shows for a key: a sub-task's parent, else the key itself."""
        issue = self.issue(key) if key else {}
        return issue["parent"] if issue.get("subtask") and issue.get("parent") else key

    def is_epic(self, key):
        return self.issue(key).get("type", "").lower() == "epic"

    def pick(self, keys):
        """(ticket, epic) for the keys a session or pull request names. An epic is never the ticket while
        another key is named: the ticket is the first main ticket, else the first sub-task's parent, and the
        epic is the first epic key named. An epic named alone is the ticket too."""
        epics = [k for k in keys if self.is_epic(k)]
        rest = [k for k in keys if k not in epics]
        main = next((k for k in rest if not self.issue(k).get("subtask")), self.top(rest[0]) if rest else "")
        epic = epics[0] if epics else ""
        return main or epic, epic

    def epic(self, key, named=""):
        """The epic a ticket belongs to, as 'KEY summary': its Jira parent, else the epic key named with it,
        else the ticket itself when it is an epic; '' when there is none, since an epic is optional."""
        issue = self.issue(key)
        if issue.get("parent"):
            return f"{issue['parent']} {issue['parent_summary']}".strip()
        epic = named or (key if self.is_epic(key) else "")
        return f"{epic} {self.issue(epic).get('summary', '')}".strip() if epic else ""

    def resolved(self, since, until):
        """The keys of the tickets assigned to you and resolved from the first day to the last."""
        after = date.fromisoformat(until) + timedelta(days=1)
        jql = f'assignee = currentUser() AND resolved >= "{since}" AND resolved < "{after}"'
        found = self.run("jira_search_cmd", jql=jql) or []
        issues = found if isinstance(found, list) else found.get("issues", [])
        return [i["key"] for i in issues]


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
    return pr["state"].lower()


def brief(pr, when):
    messages = "\n".join(c["commit"]["message"] for c in (pr.get("commits") or {}).get("nodes", []))
    keys = [k.upper() for k in KEY.findall(f"{pr['title']}\n{pr['headRefName']}\n{pr['body'] or ''}\n{messages}")]
    return {"date": when, "repo": pr["repository"]["name"], "title": pr["title"], "url": pr["url"],
            "status": status(pr), "author": (pr["author"] or {}).get("login", ""),
            "branch": pr["headRefName"], "keys": list(dict.fromkeys(keys)), "ticket": keys[0] if keys else ""}


def pull_requests(since, until):
    """The pull requests you opened, and the ones you reviewed for others, from the first day to the last."""
    login, mine = search_prs(f"is:pr author:@me created:{since}..{until}")
    _, theirs = search_prs(f"is:pr reviewed-by:@me -author:@me updated:>={since}")
    reviewed = []
    for pr in theirs:
        days = [r["submittedAt"][:10] for r in pr["reviews"]["nodes"]
                if (r["author"] or {}).get("login") == login and since <= r["submittedAt"][:10] <= until]
        if days:
            reviewed.append(brief(pr, max(days)))
    return {"opened": sorted((brief(pr, pr["createdAt"][:10]) for pr in mine), key=lambda p: p["date"]),
            "reviewed": sorted(reviewed, key=lambda p: p["date"])}


# ---- report

def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def day(stamp):
    """2026-10-09 as 9 Oct 2026."""
    d = date.fromisoformat(str(stamp)[:10])
    return f"{d.day} {d:%b %Y}"


def is_support(key):
    return key.split("-")[0].upper() in [p.upper() for p in CONFIG["support_prefixes"]]


def keys_of(row):
    """The ticket keys a session names, read with the prefixes configured now: its branches are scanned again,
    so a prefix added later also counts for sessions recorded before."""
    found = [k.upper() for k in row["keys"] + KEY.findall(" ".join(row["branches"]))]
    return [k for k in dict.fromkeys(found) if KEY.fullmatch(k)]


def ticket(row, by_branch, jira):
    """(ticket, epic named) for a session: a support key it names, else jira.pick of the keys it names, else the
    ticket of a pull request opened from one of its branches.
    A branch name settles it when it names a single ticket; otherwise the repo must match as well."""
    keys = keys_of(row)
    support = [k for k in keys if is_support(k)]
    from_pr = []
    for b in row["branches"]:
        if (repo_of(row), b) in by_branch:
            from_pr.append(by_branch[repo_of(row), b])
        elif len(by_branch.get(b, ())) == 1:
            from_pr.extend(by_branch[b])
    if support:
        return support[0], ""
    return jira.pick(keys) if keys else ((from_pr or [""])[0], "")


def cost(row):
    """A row recorded before costs were kept is priced as claude-opus-5-5 with 1-hour cache writes."""
    if "cost" in row:
        return row["cost"]
    t = row["tokens"]
    return price({"input_tokens": t["in"], "output_tokens": t["out"], "cache_read_input_tokens": t["cache_read"],
                  "cache_creation_input_tokens": t["cache_write"],
                  "cache_creation": {"ephemeral_1h_input_tokens": t["cache_write"]}})


def repo_of(row):
    cwd = Path(row["cwd"] or "/")
    return cwd.relative_to(DEV).parts[0] if cwd.is_relative_to(DEV) and cwd != DEV else cwd.name or "/"


def period(arg):
    """(first day, last day) as YYYY-MM-DD: this month by default, the month before for 'last-month',
    or from a given day to today."""
    today = date.today()
    if arg == "last-month":
        last = today.replace(day=1) - timedelta(days=1)
        return str(last.replace(day=1)), str(last)
    return (arg or str(today.replace(day=1))), str(today)


def collect(since, until):
    """Everything the report shows, as plain data. Records the transcripts still on disk first."""
    append(sorted((Path.home() / ".claude" / "projects").glob("*/*.jsonl")))
    rows = {}
    for line in LEDGER.open():
        row = json.loads(line)
        rows[row["id"]] = row  # a session is recorded more than once; the last row wins
    rows = [r for r in rows.values()
            if since <= r["start"][:10] <= until and repo_of(r) not in CONFIG["exclude_repos"]]
    if not rows:
        sys.exit(f"no sessions from {day(since)} to {day(until)}")
    prs = {kind: [pr for pr in found if pr["repo"] not in CONFIG["exclude_repos"]]
           for kind, found in pull_requests(since, until).items()}
    jira, worked, spent, incidents = Jira(), defaultdict(set), defaultdict(float), []
    named = {}  # ticket: the epic key named with it, for a ticket whose Jira parent is not set
    for pr in prs["opened"]:
        pr["ticket"], epic = jira.pick(pr["keys"])
        if epic and pr["ticket"] != epic:
            named.setdefault(pr["ticket"], epic)
    by_branch = {}  # (repo, branch): ticket, and branch: {tickets of the pull requests from a branch of that name}
    for pr in prs["opened"]:
        if pr["ticket"]:
            by_branch[pr["repo"], pr["branch"]] = pr["ticket"]
            by_branch.setdefault(pr["branch"], set()).add(pr["ticket"])
    touched = defaultdict(dict)  # ticket: {repo: None}, in the order the repos were first worked in
    other = defaultdict(lambda: {"days": [], "cost": 0.0})
    reviews = {"cost": 0.0, "repos": {}}
    for row in sorted(rows, key=lambda r: r["start"]):
        key, epic = ticket(row, by_branch, jira)
        key = jira.top(key)
        if epic and key != epic:
            named.setdefault(key, epic)
        if row["alert"]:
            incidents.append({"date": row["start"][:10], "what": row["title"] or row["prompt"] or "(no title)",
                              "ticket": key, "repo": repo_of(row), "cost": cost(row)})
        elif key:
            worked[key].add(row["start"][:10])
            spent[key] += cost(row)
            touched[key][repo_of(row)] = None
        elif row["review"] and not row["edits"]:
            reviews["cost"] += cost(row)
            reviews["repos"][repo_of(row)] = None
        elif row["edits"]:  # a session that only asked questions is left out
            other[repo_of(row)]["days"].append(row["start"][:10])
            other[repo_of(row)]["cost"] += cost(row)
    found = jira.resolved(since, until)
    resolved = [k for k in found if jira.top(k) == k]  # a resolved sub-task does not resolve its parent
    linked = defaultdict(list)
    for pr in prs["opened"]:
        if pr["ticket"]:
            linked[pr["ticket"]].append(pr)
            touched[pr["ticket"]][pr["repo"]] = None
    tickets = []
    for key in dict.fromkeys(list(worked) + list(linked) + [jira.top(k) for k in found]):
        tickets.append({"key": key, "summary": jira.issue(key).get("summary", ""), "epic": jira.epic(key, named.get(key, "")),
                        "days": sorted(worked[key]), "resolved": key in resolved, "prs": linked[key],
                        "cost": spent[key], "repos": list(touched[key])})
    if jira.cache:
        (DATA / "jira.json").write_text(json.dumps(jira.cache, indent=1))
    return {"since": since, "last": until, "incidents": incidents, "other": other,
            "prs": prs, "reviews": reviews,
            "tickets": [t for t in tickets if not is_support(t["key"])],
            "support": [t for t in tickets if is_support(t["key"])]}


# ---- page

def tag(name, text, **attrs):
    """One HTML element. Text is escaped; pass a list for content that is already HTML."""
    inner = "".join(text) if isinstance(text, list) else html.escape(str(text))
    shown = "".join(' %s="%s"' % (k.strip("_"), html.escape(str(v))) for k, v in attrs.items())
    return f"<{name}{shown}>{inner}</{name}>"


def grid(head, rows):
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
        tag("tr", [cell(c) for c in row]) for row in rows])], class_="scroll")


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


def ticket_cell(key):
    return (key, jira_link(key), "") if key else "-"


def worked_on(days):
    """'10 Nov to 14 Nov, 2 days'; the year is in the page's period."""
    if not days:
        return "-"
    span = " to ".join(dict.fromkeys(day(d).rsplit(" ", 1)[0] for d in (days[0], days[-1])))
    return f"{span}, {plural(len(days), 'day')}"


def paid(usd):
    """Whether a cost is worth showing: under half a cent rounds to nothing."""
    return usd >= 0.005


def money(usd):
    """Dollars, or '-' for nothing, so a ticket without sessions does not read as no effort."""
    return f"${usd:,.2f}" if paid(usd) else "-"


def pr_links(prs):
    """Each pull request as 'repo#123 status', one per line."""
    links = [tag("a", f"{pr['repo']}#{pr['url'].rsplit('/', 1)[-1]}", href=pr["url"], title=pr["title"])
             + " " + tag("span", STATUS[pr["status"]].split()[0], class_=f"status {pr['status']}",
                         title=STATUS[pr["status"]].split(" ", 1)[1]) for pr in prs]
    return ["<br>".join(links)] if links else "-"


def ticket_grid(tickets):
    return grid(["Ticket", "Worked on", "Pull requests", "Cost", "Status"],
                [[(t["key"], jira_link(t["key"]), t["summary"]), worked_on(t["days"]),
                  pr_links(t["prs"]), money(t["cost"]),
                  [tag("span", "Resolved", class_="state done") if t["resolved"] else tag("span", "Open", class_="state")]]
                 for t in sorted(tickets, key=lambda t: -t["cost"])])


def by_epic(tickets):
    """{epic: its tickets}, the most expensive epic first; tickets without an epic come last."""
    epics = defaultdict(list)
    for t in tickets:
        epics[t["epic"]].append(t)
    return dict(sorted(epics.items(), key=lambda item: (not item[0], -sum(t["cost"] for t in item[1]))))


def repos(tickets):
    """The repos the tickets touched, those of the most expensive ticket first, as one line."""
    found = {r: None for t in sorted(tickets, key=lambda t: -t["cost"]) for r in t["repos"]}
    return ", ".join(found) or "-"


def repos_line(tickets):
    listed = repos(tickets)
    return f"Repos: {listed}." if listed != "-" else ""


NO_EPIC = "Tickets without an epic"


def epic_key(epic):
    """'ABC-1 Billing accuracy' -> 'ABC-1'."""
    return epic.split()[0] if epic else ""


def groups(data):
    """The big groups of the work, the overview's rows, keyed by id: each epic (its id is the epic), then support,
    incidents, reviews and other work. Their costs add up to the total; each has a colour slot."""
    found = {epic: {"name": epic or NO_EPIC, "url": jira_link(epic_key(epic)), "tickets": len(ts), "repos": repos(ts),
                    "cost": sum(t["cost"] for t in ts)} for epic, ts in by_epic(data["tickets"]).items()}
    if data["support"]:
        found["support"] = {"name": "Support tickets", "url": "", "tickets": len(data["support"]),
                            "repos": repos(data["support"]), "cost": sum(t["cost"] for t in data["support"])}
    if data["incidents"]:
        found["incidents"] = {"name": "Incidents and investigations", "url": "", "tickets": "-",
                              "repos": ", ".join(dict.fromkeys(i["repo"] for i in data["incidents"])),
                              "cost": sum(i["cost"] for i in data["incidents"])}
    if data["prs"]["reviewed"] or paid(data["reviews"]["cost"]):
        found["reviews"] = {"name": "Code reviews", "url": "", "tickets": "-",
                            "repos": ", ".join(data["reviews"]["repos"]) or "-", "cost": data["reviews"]["cost"]}
    if data["other"]:
        found["other"] = {"name": "Other work", "url": "", "tickets": "-",
                          "repos": ", ".join(sorted(data["other"], key=lambda r: -data["other"][r]["cost"])),
                          "cost": sum(o["cost"] for o in data["other"].values())}
    for i, g in enumerate(found.values()):
        g["slot"] = i + 1 if i < 8 else 0  # eight palette colours in a fixed order; past them, grey
    return found


def overview(rows):
    """The groups as a table, after a bar and legend that split the whole spend between them."""
    top, total = max([g["cost"] for g in rows] + [0.01]), sum(g["cost"] for g in rows) or 0.01

    def name(g):
        return [dot(g["slot"]) + (tag("a", g["name"], href=g["url"]) if g["url"] else html.escape(g["name"]))]

    def spend(g):
        bar = tag("div", [tag("span", "", class_=f"c{g['slot']}", style=f"width:{g['cost'] / top * 100:.1f}%")], class_="bar")
        return [html.escape(money(g["cost"])) + bar]

    def share(g):
        part = g["cost"] / total
        return "-" if not paid(g["cost"]) else "<1%" if part < 0.005 else f"{part:.0%}"
    charged = [g for g in rows if paid(g["cost"])]
    split = tag("div", [tag("span", "", class_=f"c{g['slot']}", style=f"flex-grow:{g['cost'] / total:.4f}",
                            title=f"{g['name']}: {share(g)}") for g in charged], class_="split")
    legend = tag("ul", [tag("li", [dot(g["slot"]) + html.escape(g["name"]) + " " + tag("strong", share(g))])
                        for g in charged], class_="legend")
    return split + legend + grid(["Group", "Tickets", "Repos", "Share", "Cost"],
                                 [[name(g), g["tickets"], g["repos"], share(g), spend(g)] for g in rows])


def headline(data, group):
    """The headline numbers as (number, label), outcomes first; a box with nothing behind it is left out."""
    prs, tickets, support = data["prs"], data["tickets"], data["support"]

    def s(n):
        return "" if n == 1 else "s"
    resolved = sum(t["resolved"] for t in tickets)
    support_resolved = sum(t["resolved"] for t in support)
    merged = sum(pr["status"] == "merged" for pr in prs["opened"])
    incidents, reviewed = len(data["incidents"]), len(prs["reviewed"])
    boxes = [(resolved, f"ticket{s(resolved)} resolved, of {len(tickets)}", tickets),
             (support_resolved, f"support ticket{s(support_resolved)} resolved, of {len(support)}", support),
             (merged, f"pull request{s(merged)} merged, of {len(prs['opened'])} opened", prs["opened"]),
             (incidents, f"incident{s(incidents)} handled", incidents),
             (reviewed, f"pull request{s(reviewed)} reviewed", reviewed)]
    boxes = [(number, label) for number, label, behind in boxes if behind]
    if SHOW_COST:
        boxes.append((money(sum(g["cost"] for g in group.values())), "spent at API list prices"))
    return boxes


def page(data, group):
    prs = data["prs"]
    body = [tag("header", [tag("h1", "Work summary"),
                           tag("p", f"{day(data['since'])} to {day(data['last'])}", class_="period")]),
            tag("div", [tag("div", [tag("strong", number), tag("span", label)], class_="tile")
                        for number, label in headline(data, group)], class_="tiles")]
    body.append(section("Overview", "Where the work went, by epic and kind. A share is the group's part of "
                                    "the session cost, the closest measure of effort the records hold.",
                        overview(list(group.values()))))

    def boxed(gid, title, intro, *parts):
        return section(title, intro, *parts, total=group[gid]["cost"], slot=group[gid]["slot"])
    for epic, tickets in by_epic(data["tickets"]).items():
        title = [tag("a", epic, href=jira_link(epic_key(epic)))] if epic and CONFIG["jira_url"] else epic or NO_EPIC
        done = sum(t["resolved"] for t in tickets)
        intro = " ".join(filter(None, [f"{done} of {plural(len(tickets), 'ticket')} resolved.", repos_line(tickets)]))
        body.append(boxed(epic, title, intro, ticket_grid(tickets)))
    if data["support"]:
        body.append(boxed("support", "Support tickets", repos_line(data["support"]), ticket_grid(data["support"])))
    if data["incidents"]:
        body.append(boxed("incidents", "Incidents and investigations", "Sessions that followed a PagerDuty alert.",
                          grid(["Date", "Session", "Ticket", "Repo", "Cost"],
                               [[day(i["date"]), i["what"], ticket_cell(i["ticket"]), i["repo"], money(i["cost"])]
                                for i in data["incidents"]])))
    if "reviews" in group:
        body.append(boxed("reviews", "Code reviews", "Pull requests by teammates that you reviewed."
                          if prs["reviewed"] else "Sessions spent reviewing; GitHub listed no reviews in the period.",
                          *([grid(["Reviewed", "Pull request", "Status"],
                                  [[day(pr["date"]), (pr["title"], pr["url"], f"{pr['repo']} · {pr['author']}"),
                                    status_cell(pr["status"])] for pr in prs["reviewed"]])] if prs["reviewed"] else [])))
    prs_without_ticket = [pr for pr in prs["opened"] if not pr["ticket"]]  # the others are under their ticket
    if prs_without_ticket:
        body.append(section("Pull requests without a ticket", "",
                            grid(["Opened", "Pull request", "Status"],
                                 [[day(pr["date"]), (pr["title"], pr["url"], pr["repo"]), status_cell(pr["status"])]
                                  for pr in prs_without_ticket])))
    if data["other"]:
        body.append(boxed("other", "Other work", "Sessions without a Jira ticket that changed code, by repo.",
                          grid(["Repo", "Worked on", "Cost"],
                               [[repo, worked_on(sorted(set(o["days"]))), money(o["cost"])]
                                for repo, o in sorted(data["other"].items(), key=lambda item: -item[1]["cost"])])))
    body.append(tag("footer", "Sources: Jira, GitHub and the records Claude Code keeps on this computer. "
                              + ("Costs are what the sessions would cost at Claude API list prices. " if SHOW_COST else "")
                              + f"Generated on {day(date.today())}."))
    template = Template((HERE / "report.html").read_text())
    file = DATA / "report.html"
    file.write_text(template.substitute(title=f"Work summary, {day(data['since'])} to {day(data['last'])}", body="\n".join(body)))
    return file


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "record":
        path = json.load(sys.stdin).get("transcript_path")
        # Claude Code gives a SessionEnd hook very little time, so the parsing runs detached.
        if path and Path(path).exists() and os.fork() == 0:
            os.setsid()
            append([Path(path)])
    elif command == "report":
        global SHOW_COST
        SHOW_COST = "--no-cost" not in sys.argv
        data = collect(*period(next((a for a in sys.argv[2:] if not a.startswith("--")), "")))
        group = groups(data)
        file = page(data, group)
        numbers = ", ".join(f"{number} {label}" for number, label in headline(data, group))
        print(f"{day(data['since'])} to {day(data['last'])}: {numbers}")
        print(f"Page: {file}")
        webbrowser.open(file.as_uri())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
