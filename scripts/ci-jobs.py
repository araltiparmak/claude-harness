#!/usr/bin/env python3
"""The CircleCI jobs of your open pull requests: their status, and approval of dev and test deploys.

Usage:
  ci-jobs.py                  list every job of each PR's latest pipeline; in a terminal, then
                              ask which approval to give
  ci-jobs.py approve 1 3      approve the jobs numbered 1 and 3 in the list ('all' for every one)
  ci-jobs.py serve [port]     dashboard at http://localhost:8765 (ci-jobs.html), refreshed every 30 s

Config: ci-jobs.json next to this script (git ignores it), or the file that CI_JOBS_CONFIG
names. Copy ci-jobs.example.json to ci-jobs.json and fill it in. It holds the approval job names and, optionally, the Jira
site and key prefixes that link ticket keys in PR titles and branch names.

Env: CIRCLECI_TOKEN, a CircleCI personal API token. Needs gh, signed in.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG = Path(os.environ.get("CI_JOBS_CONFIG", Path(__file__).with_name("ci-jobs.json")))
EXAMPLE = Path(__file__).with_name("ci-jobs.example.json")


def load_config():
    """The approval jobs that may be approved from here, and the Jira link settings."""
    if not CONFIG.is_file():
        sys.exit(f"no config at {CONFIG}; copy {EXAMPLE} there and fill it in")
    try:
        cfg = json.loads(CONFIG.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{CONFIG} is not valid JSON: {e}")
    jobs = cfg.get("approval_jobs")
    if not isinstance(jobs, list) or not all(isinstance(j, str) for j in jobs):
        sys.exit(f"{CONFIG}: approval_jobs must be a list of job names")
    jira = cfg.get("jira") or {}
    return jobs, {"url": str(jira.get("url", "")).rstrip("/"),
                  "prefixes": [str(p) for p in jira.get("prefixes", []) if str(p).strip()]}


JOBS, JIRA = [], {"url": "", "prefixes": []}

API = "https://circleci.com/api/v2"
PRS_QUERY = """{ search(query: "is:pr is:open author:@me archived:false", type: ISSUE, first: 100) {
  nodes { ... on PullRequest { number title url headRefName repository { nameWithOwner } } } } }"""


def circleci(path, method="GET"):
    req = urllib.request.Request(f"{API}/{path}", method=method)
    req.add_header("Circle-Token", os.environ["CIRCLECI_TOKEN"])
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def approvable(job):
    return job["type"] == "approval" and job["status"] == "on_hold" and job["name"] in JOBS


def pr_jobs(pr):
    """The PR with the workflows and jobs of its branch's latest pipeline (None when there is none)."""
    repo = pr["repository"]["nameWithOwner"]
    out = {"repo": repo, "number": pr["number"], "title": pr["title"], "url": pr["url"],
           "branch": pr["headRefName"], "workflows": [], "error": None}
    try:
        branch = urllib.parse.quote(pr["headRefName"], safe="")
        pipelines = circleci(f"project/gh/{repo}/pipeline?branch={branch}")["items"]
        if not pipelines:
            return out
        pipeline = pipelines[0]
        for wf in circleci(f"pipeline/{pipeline['id']}/workflow")["items"]:
            jobs = circleci(f"workflow/{wf['id']}/job")["items"]
            out["workflows"].append({
                "id": wf["id"], "name": wf["name"], "status": wf["status"],
                "url": f"https://app.circleci.com/pipelines/gh/{repo}/{pipeline['number']}/workflows/{wf['id']}",
                "jobs": [{"id": j["id"], "name": j["name"], "type": j["type"], "status": j["status"],
                          "approvable": approvable(j)} for j in jobs],
            })
    except urllib.error.HTTPError as e:
        out["error"] = "not a CircleCI project (gh/ slug)" if e.code == 404 else f"CircleCI HTTP {e.code}"
    return out


def snapshot():
    """Every open PR of yours with its jobs, in a fixed order, so job numbers stay stable."""
    data = subprocess.run(["gh", "api", "graphql", "-f", f"query={PRS_QUERY}"],
                          check=True, capture_output=True, text=True).stdout
    prs = sorted(json.loads(data)["data"]["search"]["nodes"],
                 key=lambda p: (p["repository"]["nameWithOwner"], p["number"]))
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(pr_jobs, prs))


def approvals(prs):
    return [(pr, wf, job) for pr in prs for wf in pr["workflows"] for job in wf["jobs"] if job["approvable"]]


def approve(workflow_id, job_id):
    """Approve one job, after checking it is still an approval in JOBS on hold in that workflow."""
    jobs = circleci(f"workflow/{workflow_id}/job")["items"]
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job or not approvable(job):
        raise ValueError("not an approval job on hold that JOBS allows")
    circleci(f"workflow/{workflow_id}/approve/{job_id}", method="POST")
    return job["name"]


def show(prs):
    n = 0
    for pr in prs:
        print(f"{pr['repo']}#{pr['number']}  {pr['title'][:70]}")
        if pr["error"] or not pr["workflows"]:
            print(f"      {pr['error'] or 'no pipeline for this branch'}")
        for wf in pr["workflows"]:
            print(f"      {wf['name']}  [{wf['status']}]")
            for job in wf["jobs"]:
                mark = ""
                if job["approvable"]:
                    n += 1
                    mark = f"{n:>2}"
                print(f"   {mark:>2}   {job['name']:<32} {job['status']}")
        print()


def pick(words, items):
    if words == ["all"]:
        return items
    numbers = [int(w) for w in " ".join(words).replace(",", " ").split()]
    bad = [n for n in numbers if not 1 <= n <= len(items)]
    if bad:
        sys.exit(f"no approval numbered {bad[0]}; the list has {len(items)}")
    return [items[n - 1] for n in numbers]


def give(chosen):
    for pr, wf, job in chosen:
        approve(wf["id"], job["id"])
        print(f"approved {pr['repo']}#{pr['number']} {job['name']}")


class Dashboard(BaseHTTPRequestHandler):
    page = Path(__file__).with_name("ci-jobs.html")

    def local(self):
        # Only this machine's browser tab: refuse other hosts (DNS rebinding) and other sites' pages.
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return host.split(":")[0] in ("localhost", "127.0.0.1") and (origin is None or origin == f"http://{host}")

    def reply(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.local():
            return self.reply(403, {"error": "forbidden"})
        if self.path == "/":
            return self.reply(200, self.page.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/prs":
            try:
                return self.reply(200, {"prs": snapshot(), "jobs": JOBS, "jira": JIRA})
            except Exception as e:  # noqa: BLE001 - shown on the page
                return self.reply(502, {"error": str(e)})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.local() or self.headers.get("Content-Type") != "application/json":
            return self.reply(403, {"error": "forbidden"})
        if self.path != "/api/approve":
            return self.reply(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            self.reply(200, {"approved": approve(body["workflow"], body["job"])})
        except (KeyError, ValueError, urllib.error.HTTPError) as e:
            self.reply(400, {"error": str(e)})

    def log_message(self, *args):
        pass


def main():
    global JOBS, JIRA
    JOBS, JIRA = load_config()
    if "CIRCLECI_TOKEN" not in os.environ:
        sys.exit("CIRCLECI_TOKEN is not set; create one at https://app.circleci.com/settings/user/tokens")
    args = sys.argv[1:]
    if args[:1] == ["serve"]:
        port = int(args[1]) if len(args) > 1 else 8765
        url = f"http://localhost:{port}"
        server = ThreadingHTTPServer(("127.0.0.1", port), Dashboard)
        print(f"dashboard at {url} (Ctrl-C to stop)")
        subprocess.run(["open", "-a", "Google Chrome", url], check=False)
        server.serve_forever()
        return
    prs = snapshot()
    if not prs:
        print("no open pull requests")
        return
    show(prs)
    items = approvals(prs)
    if args[:1] == ["approve"]:
        give(pick(args[1:], items))
    elif items and sys.stdin.isatty():
        answer = input("approve (numbers, 'all', or Enter to skip): ").split()
        if answer:
            give(pick(answer, items))


if __name__ == "__main__":
    main()
