#!/usr/bin/env python3
"""Jira issues, through the two commands in config.py (the jira CLI by default).

  python3 jira.py issue KEY...           prints {key: {summary, type, subtask, parent}} as JSON
  python3 jira.py resolved SINCE UNTIL   prints the keys assigned to you and resolved in the period
  python3 jira.py updated SINCE UNTIL    prints {key: {summary, type}} of the issues assigned to you and updated
                                         in the period

All raise on a command that fails or prints something that is not JSON.
"""
import json
import subprocess
import sys
from datetime import date, timedelta

from config import settings

ISSUE_CMD, SEARCH_CMD = settings["jira_issue_cmd"], settings["jira_search_cmd"]


def run(template, **values):
    cmd = [part.format(**values) for part in template.split()]
    return json.loads(subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout)


def issue(key):
    fields = run(ISSUE_CMD, key=key)["fields"]
    return {"summary": fields.get("summary", ""), "type": fields["issuetype"]["name"],
            "subtask": bool(fields["issuetype"].get("subtask")), "parent": (fields.get("parent") or {}).get("key", "")}


def search(field, since, until):
    """The issues assigned to you whose field (resolved, updated) falls in the period."""
    after = date.fromisoformat(until) + timedelta(days=1)
    found = run(SEARCH_CMD, jql=f'assignee = currentUser() AND {field} >= "{since}" AND {field} < "{after}"')
    return found if isinstance(found, list) else found.get("issues", [])


def resolved(since, until):
    return [i["key"] for i in search("resolved", since, until)]


def updated(since, until):
    return {i["key"]: {"summary": i["fields"].get("summary", ""), "type": i["fields"]["issuetype"]["name"]}
            for i in search("updated", since, until)}


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "issue":
        print(json.dumps({key: issue(key) for key in sys.argv[2:]}, indent=1))
    elif len(sys.argv) == 4 and sys.argv[1] == "resolved":
        print(json.dumps(resolved(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == "updated":
        print(json.dumps(updated(sys.argv[2], sys.argv[3]), indent=1))
    else:
        sys.exit(__doc__)
