#!/usr/bin/env python3
"""Your pull requests from GitHub, through the gh CLI: the ones you opened, the ones you reviewed for others, and
the ones that hold your commits.

  python3 github.py SINCE UNTIL     prints {"opened": [...], "earlier": [...], "reviewed": [...]} as JSON (days as
                                    YYYY-MM-DD); earlier: yours, opened before SINCE and updated since
  python3 github.py commits DIR FROM TO
                                    prints the texts of the pull requests that hold your commits made in the repo
                                    at DIR between two times (ISO)

Each pull request: date, repo, title, url, status (open, draft, merged, closed), author, branch, and text (its
title, branch, description and commit messages, where the report looks for ticket keys).
"""
import json
import re
import subprocess
import sys

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
        cmd = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"q={query}"] + (["-f", f"after={after}"] if after else [])
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


def brief(node, when):
    commits = "\n".join(c["commit"]["message"] for c in (node.get("commits") or {}).get("nodes", []))
    status = ("draft" if node["isDraft"] else "open") if node["state"] == "OPEN" else node["state"].lower()
    return {"date": when, "repo": node["repository"]["name"], "title": node["title"], "url": node["url"],
            "status": status, "author": (node["author"] or {}).get("login", ""), "branch": node["headRefName"],
            "text": f"{node['title']}\n{node['headRefName']}\n{node['body'] or ''}\n{commits}"}


def pull_requests(since, until):
    """Opened: created in the period. Earlier: yours, created before the period and updated since; their branches
    still name a ticket. Reviewed: by others, with a review of yours in the period, dated by it. One search finds
    both of yours, since a pull request created in the period was also updated in it."""
    login, mine = search(f"is:pr author:@me updated:>={since}")
    _, theirs = search(f"is:pr reviewed-by:@me -author:@me updated:>={since}")
    reviewed = []
    for node in theirs:
        days = [r["submittedAt"][:10] for r in node["reviews"]["nodes"]
                if (r["author"] or {}).get("login") == login and since <= r["submittedAt"][:10] <= until]
        if days:
            reviewed.append(brief(node, max(days)))
    return {"opened": sorted((brief(n, n["createdAt"][:10]) for n in mine if since <= n["createdAt"][:10] <= until),
                             key=lambda p: p["date"]),
            "earlier": [brief(n, n["createdAt"][:10]) for n in mine if n["createdAt"][:10] < since],
            "reviewed": sorted(reviewed, key=lambda p: p["date"])}


def output(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout.strip()


def commit_pulls(repo_dir, start, end):
    """The texts (title, branch, description) of the pull requests that hold the commits you made in the repo at
    repo_dir between start and end, read with git and gh. [] when that is not a GitHub repo or gh fails."""
    git = ["git", "-C", repo_dir]
    try:
        found = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", output(git + ["remote", "get-url", "origin"]))
        shas = output(git + ["log", "--all", f"--author={output(git + ['config', 'user.email'])}",
                             f"--since={start}", f"--until={end}", "--format=%H"]).split()
    except Exception:  # no repo there any more, no origin, no email
        return []
    texts = []
    for sha in shas[:10] if found else []:
        try:
            pulls = json.loads(output(["gh", "api", f"repos/{found[1]}/commits/{sha}/pulls"]))
        except Exception:  # gh missing, not logged in, commit never pushed
            continue
        texts += [f"{p['title']}\n{p['head']['ref']}\n{p.get('body') or ''}" for p in pulls]
    return list(dict.fromkeys(texts))


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "commits":
        print(json.dumps(commit_pulls(*sys.argv[2:]), indent=1))
    elif len(sys.argv) == 3:
        print(json.dumps(pull_requests(sys.argv[1], sys.argv[2]), indent=1))
    else:
        sys.exit(__doc__)
