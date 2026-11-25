#!/usr/bin/env python3
"""Jira issues, through the two commands set in jira_issue_cmd and jira_search_cmd (the jira CLI by default).

  python3 jira.py issue KEY...           prints {key: {summary, type, subtask, parent}} as JSON
  python3 jira.py resolved SINCE UNTIL   prints the keys assigned to you and resolved in the period
  python3 jira.py updated SINCE UNTIL    prints {key: {summary, type}} of the issues assigned to you and updated
                                         in the period
  python3 jira.py in-progress DAY        prints {key: {summary, type}} of the issues assigned to you that were in
                                         the in-progress status (jira_in_progress) on that day

All raise on a command that fails or prints something that is not JSON.
"""
import json
import subprocess
import sys
from datetime import date, timedelta

from settings import settings

ISSUE_CMD, SEARCH_CMD, IN_PROGRESS = settings["jira_issue_cmd"], settings["jira_search_cmd"], settings["jira_in_progress"]


def run(template, **values):
    cmd = [part.format(**values) for part in template.split()]
    return json.loads(subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout)


def issue(key):
    fields = run(ISSUE_CMD, key=key)["fields"]
    return {"summary": fields.get("summary", ""), "type": fields["issuetype"]["name"],
            "subtask": bool(fields["issuetype"].get("subtask")), "parent": (fields.get("parent") or {}).get("key", "")}


def search(condition):
    """The issues assigned to you that meet a JQL condition."""
    found = run(SEARCH_CMD, jql=f"assignee = currentUser() AND {condition}")
    return found if isinstance(found, list) else found.get("issues", [])


def between(field, since, until):
    return f'{field} >= "{since}" AND {field} < "{date.fromisoformat(until) + timedelta(days=1)}"'


def brief(issues):
    return {i["key"]: {"summary": i["fields"].get("summary", ""), "type": i["fields"]["issuetype"]["name"]}
            for i in issues}


def resolved(since, until):
    return [i["key"] for i in search(between("resolved", since, until))]


def updated(since, until):
    return brief(search(between("updated", since, until)))


def in_progress(day):
    return brief(search(f'status WAS "{IN_PROGRESS}" ON "{day}"'))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "issue":
        print(json.dumps({key: issue(key) for key in sys.argv[2:]}, indent=1))
    elif len(sys.argv) == 4 and sys.argv[1] == "resolved":
        print(json.dumps(resolved(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == "updated":
        print(json.dumps(updated(sys.argv[2], sys.argv[3]), indent=1))
    elif len(sys.argv) == 3 and sys.argv[1] == "in-progress":
        print(json.dumps(in_progress(sys.argv[2]), indent=1))
    else:
        sys.exit(__doc__)
