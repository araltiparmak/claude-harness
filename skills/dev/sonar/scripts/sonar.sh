#!/usr/bin/env bash
# Print the open SonarQube Cloud findings of a pull request, one line each, from its last analysis.
# Usage: sonar.sh [PR number]   (default: the current branch's PR)
# Env: SONAR_PROJECT (default owner_repo from the origin remote), SONAR_TOKEN (private projects only)
set -euo pipefail

info="$(gh pr view ${1:+"$1"} --json number,headRefOid -q '"\(.number) \(.headRefOid)"')"
read -r pr head <<< "$info"
project="${SONAR_PROJECT:-$(git remote get-url origin | sed -E 's#(\.git)?/?$##; s#.*[:/]([^/]+)/([^/]+)$#\1_\2#')}"

python3 - "$project" "$pr" "$head" <<'PY'
import json, os, sys, urllib.parse, urllib.request

project, pr, head = sys.argv[1:]

def get(path, **params):
    req = urllib.request.Request(f"https://sonarcloud.io/api/{path}?{urllib.parse.urlencode(params)}")
    if os.environ.get("SONAR_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['SONAR_TOKEN']}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

analysis = next((a for a in get("project_pull_requests/list", project=project)["pullRequests"] if a["key"] == pr), None)
if not analysis:
    sys.exit(f"{project}: no analysis of PR {pr} yet")
sha = analysis["commit"]["sha"]
print(f"{project} PR {pr}: analysed {sha[:7]} at {analysis['analysisDate']}")
if sha != head:
    print(f"STALE: the PR is at {head[:7]}; these findings are for {sha[:7]}")

issues = get("issues/search", componentKeys=project, pullRequest=pr, resolved="false", s="FILE_LINE", ps=500)
hotspots = get("hotspots/search", projectKey=project, pullRequest=pr, status="TO_REVIEW", ps=500)
print(f"{issues['total']} issues, {hotspots['paging']['total']} hotspots")
for i in issues["issues"]:
    print(f"{i['component'].split(':', 1)[1]}:{i.get('line', 0)} {i['severity']} {i['type']} {i['rule']} {i['message']}")
for h in hotspots["hotspots"]:
    print(f"{h['component'].split(':', 1)[1]}:{h.get('line', 0)} HOTSPOT {h['vulnerabilityProbability']} {h['ruleKey']} {h['message']}")
PY
