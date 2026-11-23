#!/usr/bin/env python3
"""Jira issues, through the two commands below (the jira CLI by default).

  python3 jira.py issue KEY...           prints {key: {summary, type, subtask, parent}} as JSON
  python3 jira.py resolved SINCE UNTIL   prints the keys assigned to you and resolved in the period

Both raise on a command that fails or prints something that is not JSON.
"""
# The commands that print Jira JSON: one issue ({key}), and the issues a JQL query finds ({jql}).
ISSUE_CMD = "jira issue view {key} --raw"
SEARCH_CMD = "jira issue list -q {jql} --raw"

import json
import subprocess
import sys
from datetime import date, timedelta


def run(template, **values):
    cmd = [part.format(**values) for part in template.split()]
    return json.loads(subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout)


def issue(key):
    fields = run(ISSUE_CMD, key=key)["fields"]
    return {"summary": fields.get("summary", ""), "type": fields["issuetype"]["name"],
            "subtask": bool(fields["issuetype"].get("subtask")), "parent": (fields.get("parent") or {}).get("key", "")}


def resolved(since, until):
    after = date.fromisoformat(until) + timedelta(days=1)
    found = run(SEARCH_CMD, jql=f'assignee = currentUser() AND resolved >= "{since}" AND resolved < "{after}"')
    return [i["key"] for i in (found if isinstance(found, list) else found.get("issues", []))]


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "issue":
        print(json.dumps({key: issue(key) for key in sys.argv[2:]}, indent=1))
    elif len(sys.argv) == 4 and sys.argv[1] == "resolved":
        print(json.dumps(resolved(sys.argv[2], sys.argv[3])))
    else:
        sys.exit(__doc__)
