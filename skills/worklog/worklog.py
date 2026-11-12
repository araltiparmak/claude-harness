#!/usr/bin/env python3
"""Keeps a ledger of Claude Code sessions and writes a one-page work summary from it.

  worklog.py record           SessionEnd hook: reads the hook JSON on stdin, appends that session
  worklog.py report [since]   writes <dev_dir>/worklog/report.html, opens it and prints a short summary.
                              since is the first day, YYYY-MM-DD. First records every transcript still
                              in ~/.claude/projects, so a session whose hook did not run is not lost.

Settings come from config.json next to this file (see config.example.json); all are optional.
The data lives in <dev_dir>/worklog: sessions.jsonl (the ledger), jira.json (issue cache),
notes/<group>.md (the role and impact for an epic or project).
"""
import html
import json
import os
import re
import subprocess
import sys
import webbrowser
from collections import Counter, defaultdict
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
KEY = re.compile(rf"\b(?:{PREFIXES})-\d+\b") if PREFIXES else re.compile(r"[^\s\S]")  # never matches
REVIEW = re.compile(r"gh pr (diff|review|checkout)|<command-name>/code-review")
TOKENS = {"in": "input_tokens", "out": "output_tokens",
          "cache_write": "cache_creation_input_tokens", "cache_read": "cache_read_input_tokens"}
PR_QUERY = """query($q: String!, $after: String) {
  viewer { login }
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      title url state isDraft createdAt mergedAt repository { name }
      reviews(first: 50) { nodes { author { login } submittedAt } }
    } }
  }
}"""
KINDS = {"task": "planned work", "review": "code review", "alert": "incidents", "support": "support", "other": "other"}
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
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        if d.get("type") == "assistant":
            # A reply is written once per content block, each time with the same usage.
            if msg.get("usage"):
                usage[msg.get("id")] = msg["usage"]
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
            print(f"note: Jira is not answering ({err}); tickets are grouped by key\n", file=sys.stderr)
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

    def resolved(self, since):
        """The tickets assigned to you and resolved since the day, counted by type."""
        found = self.run("jira_search_cmd", jql=f'assignee = currentUser() AND resolved >= "{since}"') or []
        issues = found if isinstance(found, list) else found.get("issues", [])
        support = lambda i: i["key"].split("-")[0] in CONFIG["support_prefixes"]
        return Counter("support" if support(i) else i["fields"]["issuetype"]["name"].lower() for i in issues).most_common()


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def day(stamp):
    """2026-10-09 as 9 Oct 2026."""
    d = date.fromisoformat(str(stamp)[:10])
    return f"{d.day} {d:%b %Y}"


def span(hours):
    """The median of some hours, in words: 40 min, 5 hours, 3 days."""
    if not hours:
        return "-"
    h = median(hours)
    if h < 1:
        return f"{max(1, round(h * 60))} min"
    return plural(round(h), "hour") if h < 48 else plural(round(h / 24), "day")


def took(pr):
    """Hours from opening a pull request to its merge. The time zone is dropped: GitHub gives UTC."""
    moment = lambda stamp: datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    return (moment(pr["mergedAt"]) - moment(pr["createdAt"])).total_seconds() / 3600


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


def pull_requests(since):
    """The pull requests you opened, and the ones you reviewed for others, since the day."""
    login, mine = search_prs(f"is:pr author:@me created:>={since}")
    _, theirs = search_prs(f"is:pr reviewed-by:@me -author:@me updated:>={since}")
    reviewed = [pr for pr in theirs if any((r["author"] or {}).get("login") == login and r["submittedAt"][:10] >= since
                                           for r in pr["reviews"]["nodes"])]
    return {"opened": [{"date": pr["createdAt"][:10], "repo": pr["repository"]["name"], "title": pr["title"],
                        "url": pr["url"], "status": status(pr), "merge": span([took(pr)] if pr["mergedAt"] else [])}
                       for pr in sorted(mine, key=lambda p: p["createdAt"])],
            "merge": span([took(pr) for pr in mine if pr["mergedAt"]]),
            "reviewed": len(reviewed), "review_repos": len({pr["repository"]["name"] for pr in reviewed})}


# ---- report

def ticket(row):
    support = [k for k in row["keys"] if k.split("-")[0] in CONFIG["support_prefixes"]]
    return (support or row["keys"] or [""])[0]


def kind(row):
    if row["alert"]:
        return "alert"
    if row["keys"] and ticket(row).split("-")[0] in CONFIG["support_prefixes"]:
        return "support"
    if row["review"] and not row["edits"]:
        return "review"
    return "task" if row["keys"] else "other"


def repo_of(row):
    cwd = Path(row["cwd"] or "/")
    return cwd.relative_to(DEV).parts[0] if cwd.is_relative_to(DEV) and cwd != DEV else cwd.name or "/"


def note_of(group):
    file = DATA / "notes" / f"{group.split()[0]}.md"
    return file.read_text().strip() if file.exists() else ""


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
    jira, groups, tickets, opened = Jira(), defaultdict(list), defaultdict(set), defaultdict(list)
    for row in rows:
        key = ticket(row)
        group = jira.group(key, repo_of(row))
        groups[group].append(row)
        if key:
            tickets[group].add(f"{key} {jira.issue(key).get('summary', '')}".strip())
    prs = pull_requests(since)
    for pr in prs["opened"]:
        key = KEY.search(pr["title"])
        opened[jira.group(key and key.group(), pr["repo"])].append(pr)
    data = {"since": since, "last": max(r["start"][:10] for r in rows), "sessions": len(rows),
            "days": len({r["start"][:10] for r in rows}), "kinds": Counter(kind(r) for r in rows).most_common(),
            "names": sorted(set(groups) | set(opened), key=lambda g: -len(groups[g])),
            "groups": groups, "tickets": tickets, "opened": opened, "prs": prs, "resolved": jira.resolved(since)}
    if jira.cache:
        (DATA / "jira.json").write_text(json.dumps(jira.cache, indent=1))
    return data


# ---- page

def tag(name, text, **attrs):
    """One HTML element. Text is escaped; pass a list for content that is already HTML."""
    inner = "".join(text) if isinstance(text, list) else html.escape(str(text))
    shown = "".join(' %s="%s"' % (k.strip("_"), html.escape(str(v))) for k, v in attrs.items())
    return f"<{name}{shown}>{inner}</{name}>"


def grid(head, rows):
    """An HTML table. A cell that is a (text, url, small print) tuple becomes a link with a line under it."""
    link = lambda c: tag("td", [tag("a", c[0], href=c[1]), tag("small", c[2])])
    return tag("div", [tag("table", [tag("tr", [tag("th", h) for h in head])] + [
        tag("tr", [link(c) if isinstance(c, tuple) else tag("td", c) for c in row]) for row in rows])], class_="scroll")


def section(title, intro, *parts):
    return tag("section", [tag("h2", title)] + ([tag("p", intro, class_="intro")] if intro else []) + list(parts))


def days_of(rows):
    return sorted({r["start"][:10] for r in rows})


def summary(data):
    """The opening: the period, one sentence a manager can repeat, and the headline numbers."""
    prs = data["prs"]
    merged = sum(pr["status"] == "merged" for pr in prs["opened"])
    resolved = sum(n for _, n in data["resolved"])
    tiles = [("Pull requests merged", merged, f"of {len(prs['opened'])} opened"),
             ("Pull requests reviewed", prs["reviewed"], f"for teammates, in {plural(prs['review_repos'], 'repo')}")]
    if data["resolved"]:
        tiles.append(("Jira tickets resolved", resolved, ", ".join(f"{n} {t}" for t, n in data["resolved"])))
    tiles += [("Epics and projects", len(data["names"]), "listed below"),
              ("Active days", data["days"], plural(data["sessions"], "session"))]
    done = [f"{plural(merged, 'pull request')} merged", f"{plural(prs['reviewed'], 'pull request')} reviewed for teammates"]
    done += [f"{plural(resolved, 'Jira ticket')} resolved"] if data["resolved"] else []
    lede = f"{', '.join(done[:-1])} and {done[-1]}, across {len(data['names'])} epics and projects."
    mix = [tag("p", "Sessions by kind of work: " + " · ".join(f"{KINDS[k]} {n}" for k, n in data["kinds"]),
               class_="intro")] if len(data["kinds"]) > 1 else []
    return tag("header", [tag("h1", "Work summary"), tag("p", f"{day(data['since'])} to {day(data['last'])}", class_="period"),
                          tag("p", lede, class_="lede")] + mix + [
        tag("div", [tag("div", [tag("span", label), tag("b", value), tag("small", caption)])
                    for label, value, caption in tiles], class_="tiles")])


def timeline(data):
    """Each epic or project as a row across the period, with a mark on every day it had work."""
    start, end = date.fromisoformat(data["since"]), date.fromisoformat(data["last"])
    length = (end - start).days + 1
    at = lambda d: (date.fromisoformat(str(d)) - start).days / length * 100
    month, labels = start, []
    while month <= end:
        if month == start or month.day == 1 and at(month) > 12:
            labels.append(tag("span", f"{month.day} {month:%b}", style=f"left:{at(month)}%"))
        month = (month.replace(day=1) + timedelta(days=32)).replace(day=1)
    rows = [tag("div", [tag("span", ""), tag("span", labels, class_="axis"), tag("span", "")], class_="row")]
    for name in [n for n in data["names"] if data["groups"][n]][:12]:
        days = days_of(data["groups"][name])
        marks = [tag("i", "", style=f"left:{at(d)}%;width:{100 / length}%") for d in days]
        reach = tag("em", "", style=f"left:{at(days[0])}%;width:{at(days[-1]) - at(days[0]) + 100 / length}%")
        rows.append(tag("div", [tag("span", name, class_="name"), tag("span", [reach] + marks, class_="track"),
                                tag("span", plural(len(days), "day"), class_="value")],
                        class_="row", title=f"{name}: {day(days[0])} to {day(days[-1])}"))
    return tag("div", rows, class_="timeline")


def cards(data):
    """One card per epic or project that has a note, tickets or pull requests: the outcome first."""
    found = []
    for name in data["names"]:
        note, tickets, prs = note_of(name), sorted(data["tickets"][name]), data["opened"][name]
        if not (note or tickets or prs):
            continue
        days = days_of(data["groups"][name])
        merged = sum(pr["status"] == "merged" for pr in prs)
        facts = ([" to ".join(dict.fromkeys([day(days[0]), day(days[-1])])), plural(len(days), "active day")] if days else []) \
            + ([f"{plural(merged, 'pull request')} merged"] if merged else [])
        items = [tag("li", t) for t in tickets] + [
            tag("li", [tag("a", pr["title"], href=pr["url"]), html.escape(f" · {STATUS[pr['status']]}")]) for pr in prs]
        found.append(tag("article", [tag("h3", name), tag("p", " · ".join(facts), class_="facts")]
                         + ([tag("p", note, class_="outcome")] if note else []) + [tag("ul", items)]))
    return "".join(found)


def usage(name, rows):
    amount = lambda n: f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k"
    return [name, len(rows), len(days_of(rows)), amount(sum(r["tokens"]["out"] for r in rows)),
            amount(sum(sum(r["tokens"].values()) for r in rows))]


def page(data):
    prs = data["prs"]
    body = [summary(data), section("What the work was, and when",
                                   "Each row is an epic or a project; each mark is a day with work on it.", timeline(data))]
    outcomes = cards(data)
    if outcomes:
        body.append(section("Outcomes", "", outcomes))
    if prs["opened"]:
        body.append(section("Pull requests", f"Median time from opening to merge: {prs['merge']}.",
                            grid(["Opened", "Pull request", "Status", "Merged after"],
                                 [[day(pr["date"]), (pr["title"], pr["url"], pr["repo"]), STATUS[pr["status"]], pr["merge"]]
                                  for pr in prs["opened"]])))
    body += [tag("details", [tag("summary", "Appendix: AI token use per epic or project"),
                             grid(["Epic or project", "Sessions", "Days", "Output tokens", "All tokens"],
                                  [usage(n, data["groups"][n]) for n in data["names"] if data["groups"][n]])]),
             tag("footer", "A session is one conversation with Claude Code, the AI coding assistant; sessions show where "
                           "the effort went, not hours. Sources: GitHub, Jira and the records Claude Code keeps on this "
                           f"computer. Generated on {day(date.today())}.")]
    template = Template((Path(__file__).resolve().parent / "report.html").read_text())
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
        prs, file = data["prs"], page(data)
        merged = sum(pr["status"] == "merged" for pr in prs["opened"])
        print(f"{day(data['since'])} to {day(data['last'])}: {plural(data['sessions'], 'session')} on "
              f"{plural(data['days'], 'active day')}, {merged} of {len(prs['opened'])} pull requests merged, "
              f"{prs['reviewed']} reviewed for teammates")
        for name in data["names"]:
            titles = [pr["title"] for pr in data["opened"][name] if pr["status"] == "merged"]
            if titles and not note_of(name):
                print(f"No note: {name}: {'; '.join(titles)}")
        print(f"Page: {file}")
        webbrowser.open(file.as_uri())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
