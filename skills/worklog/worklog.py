#!/usr/bin/env python3
"""Keeps a ledger of Claude Code sessions and writes a one-page work summary from it.

  worklog.py record           SessionEnd hook: reads the hook JSON on stdin, appends that session
  worklog.py report [since]   writes <dev_dir>/worklog/report.html, opens it and prints the counts.
                              since is the first day, YYYY-MM-DD. First records every transcript still
                              in ~/.claude/projects, so a session whose hook did not run is not lost.

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
from datetime import date
from pathlib import Path
from string import Template

CONFIG = {"dev_dir": "~/dev", "jira_prefixes": [], "support_prefixes": [], "jira_url": "",
          "jira_cmd": "jira issue view {key} --raw",
          "jira_search_cmd": "jira issue list -q {jql} --raw"}
HERE = Path(__file__).resolve().parent
if (HERE / "config.json").exists():
    CONFIG.update(json.loads((HERE / "config.json").read_text()))

DEV = Path(CONFIG["dev_dir"]).expanduser()
DATA = DEV / "worklog"
LEDGER = DATA / "sessions.jsonl"
PREFIXES = "|".join(re.escape(p) for p in CONFIG["jira_prefixes"])
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b") if PREFIXES else re.compile(r"[^\s\S]")  # never matches
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
    } }
  }
}"""
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


def note_tools(row, blocks):
    """Whether a reply edited files or ran a review."""
    for b in blocks:
        if b.get("type") != "tool_use":
            continue
        name, args = b.get("name"), b.get("input") or {}
        row["edits"] |= name in ("Edit", "Write", "NotebookEdit")
        row["review"] |= name == "Skill" and args.get("skill") == "code-review"
        row["review"] |= name == "Bash" and bool(REVIEW.search(args.get("command", "")))


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
    usage, text, branches = {}, [], []
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
            note_tools(row, blocks)
        elif d.get("type") == "user" and not d.get("isMeta"):
            text += [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return finish(row, usage, text, branches) if usage else None


def finish(row, usage, text, branches):
    """Fills in the fields that need the whole session."""
    said = "\n".join(text)
    row["prompt"] = next((t.strip()[:200] for t in text if t.strip() and not t.lstrip().startswith("<")), "")
    row["branches"] = branches
    row["keys"] = list(dict.fromkeys(KEY.findall(" ".join(branches) + "\n" + said)))
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

    def epic(self, key):
        """The epic a ticket belongs to, as 'KEY summary', or '' when Jira does not say."""
        issue = self.issue(key)
        return f"{issue['parent']} {issue['parent_summary']}".strip() if issue.get("parent") else ""

    def resolved(self, since):
        """The keys of the tickets assigned to you and resolved since the day."""
        found = self.run("jira_search_cmd", jql=f'assignee = currentUser() AND resolved >= "{since}"') or []
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
    found = KEY.search(f"{pr['title']}\n{pr['headRefName']}\n{pr['body'] or ''}")
    return {"date": when, "repo": pr["repository"]["name"], "title": pr["title"], "url": pr["url"],
            "status": status(pr), "author": (pr["author"] or {}).get("login", ""),
            "branch": pr["headRefName"], "ticket": found.group() if found else ""}


def pull_requests(since):
    """The pull requests you opened, and the ones you reviewed for others, since the day."""
    login, mine = search_prs(f"is:pr author:@me created:>={since}")
    _, theirs = search_prs(f"is:pr reviewed-by:@me -author:@me updated:>={since}")
    reviewed = []
    for pr in theirs:
        days = [r["submittedAt"][:10] for r in pr["reviews"]["nodes"]
                if (r["author"] or {}).get("login") == login and r["submittedAt"][:10] >= since]
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
    return key.split("-")[0] in CONFIG["support_prefixes"]


def ticket(row, by_branch):
    """The session's ticket: a key it names, else the ticket of a pull request opened from its branch."""
    support = [k for k in row["keys"] if is_support(k)]
    return (support or row["keys"] or [by_branch[b] for b in row["branches"] if b in by_branch] or [""])[0]


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
    prs = pull_requests(since)
    by_branch = {pr["branch"]: pr["ticket"] for pr in prs["opened"] if pr["ticket"]}
    jira, worked, spent, incidents = Jira(), defaultdict(set), defaultdict(float), []
    other = defaultdict(lambda: {"days": [], "cost": 0.0})
    for row in sorted(rows, key=lambda r: r["start"]):
        key = ticket(row, by_branch)
        if row["alert"]:
            incidents.append({"date": row["start"][:10], "what": row["title"] or row["prompt"] or "(no title)",
                              "ticket": key, "repo": repo_of(row), "cost": cost(row)})
        elif key:
            worked[key].add(row["start"][:10])
            spent[key] += cost(row)
        elif row["edits"] or not row["review"]:  # a review without edits is in the GitHub review list
            other[repo_of(row)]["days"].append(row["start"][:10])
            other[repo_of(row)]["cost"] += cost(row)
    resolved = jira.resolved(since)
    linked = defaultdict(list)
    for pr in prs["opened"]:
        if pr["ticket"]:
            linked[pr["ticket"]].append(pr)
    tickets = []
    for key in dict.fromkeys(list(worked) + list(linked) + resolved):
        tickets.append({"key": key, "summary": jira.issue(key).get("summary", ""), "epic": jira.epic(key),
                        "days": sorted(worked[key]), "resolved": key in resolved, "prs": linked[key],
                        "cost": spent[key]})
    if jira.cache:
        (DATA / "jira.json").write_text(json.dumps(jira.cache, indent=1))
    return {"since": since, "last": max(r["start"][:10] for r in rows), "sessions": len(rows),
            "cost": sum(cost(r) for r in rows),
            "days": len({r["start"][:10] for r in rows}), "incidents": incidents, "other": other, "prs": prs,
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
    with a line under it."""
    def cell(c):
        if not isinstance(c, tuple):
            return tag("td", c)
        text, url, small = c
        return tag("td", [tag("a", text, href=url) if url else html.escape(text)] + ([tag("small", small)] if small else []))
    return tag("div", [tag("table", [tag("tr", [tag("th", h) for h in head])] + [
        tag("tr", [cell(c) for c in row]) for row in rows])], class_="scroll")


def section(title, intro, *parts):
    return tag("section", [tag("h2", title)] + ([tag("p", intro, class_="intro")] if intro else []) + list(parts))


def jira_link(key):
    return f"{CONFIG['jira_url'].rstrip('/')}/browse/{key}" if CONFIG["jira_url"] and key else ""


def ticket_cell(key):
    return (key, jira_link(key), "") if key else "-"


def worked_on(days):
    if not days:
        return "-"
    span = " to ".join(dict.fromkeys([day(days[0]), day(days[-1])]))
    return f"{span} ({plural(len(days), 'day')})"


def money(usd):
    return f"${usd:,.2f}"


def pr_links(prs):
    """Each pull request as 'repo#123 status', one per line."""
    links = [tag("a", f"{pr['repo']}#{pr['url'].rsplit('/', 1)[-1]}", href=pr["url"], title=pr["title"])
             + " " + html.escape(STATUS[pr["status"]].split()[0]) for pr in prs]
    return ["<br>".join(links)] if links else "-"


def ticket_grid(tickets):
    return grid(["Ticket", "Worked on", "Pull requests", "Cost", "Resolved"],
                [[(t["key"], jira_link(t["key"]), t["summary"]), worked_on(t["days"]),
                  pr_links(t["prs"]), money(t["cost"]), "✓" if t["resolved"] else ""]
                 for t in sorted(tickets, key=lambda t: -t["cost"])])


def by_epic(tickets):
    """{epic: its tickets}, the most expensive epic first; tickets without an epic come last."""
    epics = defaultdict(list)
    for t in tickets:
        epics[t["epic"]].append(t)
    return dict(sorted(epics.items(), key=lambda item: (not item[0], -sum(t["cost"] for t in item[1]))))


def overview(data):
    """One row per big group: each epic, support, incidents and other work."""
    def row(name, url, tickets, usd):
        return [(name, url, ""), tickets, money(usd)]
    rows = [row(epic or "No epic", jira_link(epic.split()[0]) if epic else "", len(ts), sum(t["cost"] for t in ts))
            for epic, ts in by_epic(data["tickets"]).items()]
    if data["support"]:
        rows.append(row("Support tickets", "", len(data["support"]), sum(t["cost"] for t in data["support"])))
    if data["incidents"]:
        rows.append(row("Incidents and investigations", "", "-", sum(i["cost"] for i in data["incidents"])))
    if data["other"]:
        rows.append(row("Other work", "", "-", sum(o["cost"] for o in data["other"].values())))
    return grid(["Group", "Tickets", "Cost"], rows)


def counts(data):
    """The headline numbers, as short phrases."""
    prs = data["prs"]
    merged = sum(pr["status"] == "merged" for pr in prs["opened"])
    return [f"{money(data['cost'])} spent", plural(len(data["tickets"]), "ticket"), plural(len(data["support"]), "support ticket"),
            plural(len(data["incidents"]), "incident"),
            f"{plural(len(prs['opened']), 'pull request')} opened ({merged} merged)",
            f"{plural(len(prs['reviewed']), 'pull request')} reviewed"]


def page(data):
    prs = data["prs"]
    body = [tag("header", [tag("h1", "Work summary"),
                           tag("p", f"{day(data['since'])} to {day(data['last'])}", class_="period"),
                           tag("p", " · ".join(counts(data)), class_="counts")])]
    body.append(section("Overview", "Where the work went, by epic and kind. Cost is what the sessions "
                                    "would cost at API list prices.", overview(data)))
    for epic, tickets in by_epic(data["tickets"]).items():
        body.append(section(epic or "Tickets without an epic", "", ticket_grid(tickets)))
    if data["support"]:
        body.append(section("Support tickets", "", ticket_grid(data["support"])))
    if data["incidents"]:
        body.append(section("Incidents and investigations", "Sessions that followed a PagerDuty alert.",
                            grid(["Date", "Session", "Ticket", "Repo", "Cost"],
                                 [[day(i["date"]), i["what"], ticket_cell(i["ticket"]), i["repo"], money(i["cost"])]
                                  for i in data["incidents"]])))
    if prs["reviewed"]:
        body.append(section("Code reviews", "Pull requests by teammates that you reviewed.",
                            grid(["Reviewed", "Pull request", "Status"],
                                 [[day(pr["date"]), (pr["title"], pr["url"], f"{pr['repo']} · {pr['author']}"),
                                   STATUS[pr["status"]]] for pr in prs["reviewed"]])))
    if prs["opened"]:
        body.append(section("Pull requests", "",
                            grid(["Opened", "Pull request", "Ticket", "Status"],
                                 [[day(pr["date"]), (pr["title"], pr["url"], pr["repo"]), ticket_cell(pr["ticket"]),
                                   STATUS[pr["status"]]] for pr in prs["opened"]])))
    if data["other"]:
        body.append(section("Other work", "Sessions without a Jira ticket, by repo.",
                            grid(["Repo", "Worked on", "Cost"],
                                 [[repo, worked_on(sorted(set(o["days"]))), money(o["cost"])]
                                  for repo, o in sorted(data["other"].items(), key=lambda item: -item[1]["cost"])])))
    body.append(tag("footer", "Sources: Jira, GitHub and the records Claude Code keeps on this computer. "
                              f"Generated on {day(date.today())}."))
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
        data = collect(sys.argv[2] if len(sys.argv) > 2 else "")
        file = page(data)
        print(f"{day(data['since'])} to {day(data['last'])}: {', '.join(counts(data))}")
        print(f"Page: {file}")
        webbrowser.open(file.as_uri())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
