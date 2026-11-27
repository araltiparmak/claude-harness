#!/usr/bin/env python3
"""Your pull requests from GitHub, through the gh CLI: the ones you opened, the ones you reviewed for others, and
the ones that hold your commits.

  python3 github.py SINCE UNTIL     prints {"opened": [...], "earlier": [...], "reviewed": [...]} as JSON (days as
                                    YYYY-MM-DD); earlier: yours, opened before SINCE and updated since
  python3 github.py commits DIR FROM TO
                                    prints the texts of the pull requests that hold your commits made in the repo
                                    at DIR between two times (ISO); cached in commits.json

Each pull request: date, repo, title, url, status (open, draft, merged, closed), author, branch, and text (its
title, branch, description and commit messages, where the report looks for ticket keys).
"""
import functools
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta

from ledger import local_day, moment
from settings import DATA

QUERY = """query($q: String!, $after: String) {
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


def search(query):
    """(your login, the pull requests a GitHub search finds). On a gh error, what was read so far."""
    nodes, after, login = [], None, ""
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"q={query}"]
        cmd += ["-f", f"after={after}"] if after else []
        try:
            data = json.loads(subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout)["data"]
        except Exception as err:  # gh missing, not logged in, network
            print(f"note: could not read pull requests with gh ({err})\n", file=sys.stderr)
            return login, nodes
        login = data["viewer"]["login"]
        nodes += [n for n in data["search"]["nodes"] if n]
        if not data["search"]["pageInfo"]["hasNextPage"]:
            return login, nodes
        after = data["search"]["pageInfo"]["endCursor"]


def status_of(node):
    """open, draft, merged or closed."""
    if node["state"] != "OPEN":
        return node["state"].lower()
    return "draft" if node["isDraft"] else "open"


def brief(node, when):
    commits = "\n".join(c["commit"]["message"] for c in (node.get("commits") or {}).get("nodes", []))
    status = status_of(node)
    return {"date": when, "repo": node["repository"]["name"], "title": node["title"], "url": node["url"],
            "status": status, "author": (node["author"] or {}).get("login", ""), "branch": node["headRefName"],
            "text": f"{node['title']}\n{node['headRefName']}\n{node['body'] or ''}\n{commits}"}


def pull_requests(since, until):
    """Opened: created in the period. Earlier: yours, created before the period and updated since; their branches
    still name a ticket. Reviewed: by others, with a review of yours submitted in the period (a pending one has no
    time yet), dated by it. One search finds both of yours, since a pull request created in the period was also
    updated in it. Days are local (local_day); GitHub searches by UTC days, so the searches start a day early."""
    since, until = date.fromisoformat(since).isoformat(), date.fromisoformat(until).isoformat()
    early = date.fromisoformat(since) - timedelta(days=1)
    login, mine = search(f"is:pr author:@me updated:>={early}")
    _, theirs = search(f"is:pr reviewed-by:@me -author:@me updated:>={early}")
    reviewed = []
    for node in theirs:
        days = [local_day(r["submittedAt"]) for r in node["reviews"]["nodes"]
                if r["submittedAt"] and (r["author"] or {}).get("login") == login]
        days = [d for d in days if since <= d <= until]
        if days:
            reviewed.append(brief(node, max(days)))
    created = [(local_day(n["createdAt"]), n) for n in mine]
    return {"opened": sorted((brief(n, d) for d, n in created if since <= d <= until), key=lambda p: p["date"]),
            "earlier": [brief(n, d) for d, n in created if d < since],
            "reviewed": sorted(reviewed, key=lambda p: p["date"])}


def output(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True, cwd=cwd).stdout.strip()


CACHE = DATA / "commits.json"  # {sha: [texts of its pull requests]}; a commit in a pull request stays there
DEFAULT_BRANCHES = {"main", "master", "develop", "HEAD"}  # every branch starts from one; successors leaves them out
REFLOG = re.compile(r"(.+)@\{(\d+)\} (.*)")  # a reflog line as --date=unix --format='%gd %gs' prints it
MOVED = re.compile(r"checkout: moving from (\S+) to (\S+)")
RENAMED = re.compile(r"Branch: renamed refs/heads/(\S+) to refs/heads/(\S+)")


@functools.lru_cache(maxsize=None)
def successors(repo_dir):
    """{branch: the branch it became} in the repo at repo_dir, read from its reflogs: a branch renamed, or a
    branch created and checked out while on it (git checkout -b, git switch -c), so work done on a branch before it
    got its ticket key still finds the pull request. A branch that became several, and the DEFAULT_BRANCHES, are
    left out. {} when git fails."""
    try:
        lines = output(["git", "log", "-g", "--all", "--date=unix", "--format=%gd %gs"], repo_dir).splitlines()
    except Exception:  # not a git repo, no reflog, git missing
        return {}
    created, moves, found = defaultdict(set), [], defaultdict(set)  # created: {branch: the times it was created}
    for line in lines:
        entry = REFLOG.fullmatch(line)
        if not entry:
            continue
        ref, when, what = entry[1], int(entry[2]), entry[3]
        moved, renamed = MOVED.fullmatch(what), RENAMED.fullmatch(what)
        if what.startswith("branch: Created from"):
            created[ref].add(when)
        elif moved and ref == "HEAD":
            moves.append((moved[1], moved[2], when))
        elif renamed:
            found[renamed[1]].add(renamed[2])
    for old, new, when in moves:
        if any(abs(when - t) <= 1 for t in created[new]):  # the checkout that created the branch
            found[old].add(new)
    return {old: next(iter(new)) for old, new in found.items() if len(new) == 1 and old not in DEFAULT_BRANCHES}


def commit_pulls(repo_dir, start, end):
    """The texts (title, branch, description) of the pull requests that hold the commits you made in the repo at
    repo_dir between start and end, read with git and one gh request for all the commits that commits.json does
    not hold yet. [] when that is not a GitHub repo or gh fails."""
    try:
        start, end = (moment(t).isoformat() for t in (start, end))
        found = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$",
                          output(["git", "remote", "get-url", "origin"], repo_dir))
        email = output(["git", "config", "user.email"], repo_dir)
        shas = output(["git", "log", "--all", f"--author={email}", f"--since={start}", f"--until={end}", "--format=%H"],
                      repo_dir).split()
    except Exception:  # no repo there any more, no origin, no email, a time that is not ISO
        return []
    if not found or not shas:
        return []
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    ask = [sha for sha in shas if sha not in cache]
    if ask:
        fields = "".join(f'c{i}: object(oid: "{sha}") {{ ... on Commit {{ associatedPullRequests(first: 5) '
                         f"{{ nodes {{ title headRefName body }} }} }} }} " for i, sha in enumerate(ask))
        query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {fields}}} }}"
        try:
            repo = json.loads(output(["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={found[1]}",
                                      "-f", f"name={found[2]}"]))["data"]["repository"]
        except Exception:  # gh missing, not logged in, network, repo gone
            return []
        for i, sha in enumerate(ask):
            pulls = ((repo or {}).get(f"c{i}") or {}).get("associatedPullRequests", {}).get("nodes", [])
            if pulls:  # a commit with no pull request yet is asked again next time
                cache[sha] = [f"{p['title']}\n{p['headRefName']}\n{p.get('body') or ''}" for p in pulls]
        CACHE.parent.mkdir(parents=True, exist_ok=True)  # github.py commits may run before the first report
        CACHE.write_text(json.dumps(cache, indent=1))
    return list(dict.fromkeys(text for sha in shas for text in cache.get(sha, [])))


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "commits":
        print(json.dumps(commit_pulls(*sys.argv[2:]), indent=1))
    elif len(sys.argv) == 3:
        print(json.dumps(pull_requests(sys.argv[1], sys.argv[2]), indent=1))
    else:
        sys.exit(__doc__)
