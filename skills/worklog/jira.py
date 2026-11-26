#!/usr/bin/env python3
"""Jira issues, from the Jira Cloud REST API at jira_url, as jira_email with the API token in $JIRA_API_TOKEN.

  python3 jira.py issue KEY...           prints {key: {summary, type, subtask, parent}} as JSON
  python3 jira.py updated SINCE UNTIL    prints {key: {summary, type}} of the issues assigned to you and updated
                                         in the period
  python3 jira.py in-progress DAY        prints {key: {summary, type}} of the issues assigned to you that were in
                                         the in-progress status (jira_in_progress) on that day

All raise when Jira cannot be reached or refuses: urllib.error.HTTPError with code 404 for a key Jira does not
know, KeyError when jira_url, jira_email or the token is not set.
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, timedelta

from settings import settings

IN_PROGRESS = settings["jira_in_progress"]
FIELDS = "summary,issuetype,parent"


def call(path, body=None):
    """GET path, or POST body as JSON to it, and return the JSON Jira answers."""
    token = os.environ.get("JIRA_API_TOKEN", "")
    for name, value in (("jira_url", settings["jira_url"]), ("jira_email", settings["jira_email"]),
                        ("JIRA_API_TOKEN", token)):
        if not value:
            raise KeyError(f"{name} is not set")
    login = f'{settings["jira_email"]}:{token}'
    request = urllib.request.Request(
        settings["jira_url"].rstrip("/") + path, data=body and json.dumps(body).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(login.encode()).decode(),
                 "Accept": "application/json", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as answer:
        return json.load(answer)


def issue(key):
    fields = call(f"/rest/api/3/issue/{urllib.parse.quote(key)}?fields={FIELDS}")["fields"]
    return {"summary": fields.get("summary", ""), "type": fields["issuetype"]["name"],
            "subtask": bool(fields["issuetype"].get("subtask")), "parent": (fields.get("parent") or {}).get("key", "")}


def search(condition):
    """The issues assigned to you that meet a JQL condition."""
    body, issues = {"jql": f"assignee = currentUser() AND {condition}", "fields": FIELDS.split(","),
                    "maxResults": 100}, []
    while True:
        page = call("/rest/api/3/search/jql", body)
        issues += page.get("issues", [])
        if page.get("isLast", True) or not page.get("nextPageToken"):
            return issues
        body["nextPageToken"] = page["nextPageToken"]


def between(field, since, until):
    return f'{field} >= "{since}" AND {field} < "{date.fromisoformat(until) + timedelta(days=1)}"'


def brief(issues):
    return {i["key"]: {"summary": i["fields"].get("summary", ""), "type": i["fields"]["issuetype"]["name"]}
            for i in issues}


def updated(since, until):
    return brief(search(between("updated", since, until)))


def in_progress(day):
    return brief(search(f'status WAS "{IN_PROGRESS}" ON "{day}"'))


def myself():
    """The name Jira knows you by; raises like call when the login is refused."""
    return call("/rest/api/3/myself").get("displayName", "")


def prefixes(days=90):
    """The project prefixes of the issues assigned to you and updated in the last days, most issues first."""
    counts = Counter(i["key"].split("-")[0] for i in search(f"updated >= -{days}d"))
    return [prefix for prefix, _ in counts.most_common()]


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "issue":
        print(json.dumps({key: issue(key) for key in sys.argv[2:]}, indent=1))
    elif len(sys.argv) == 4 and sys.argv[1] == "updated":
        print(json.dumps(updated(sys.argv[2], sys.argv[3]), indent=1))
    elif len(sys.argv) == 3 and sys.argv[1] == "in-progress":
        print(json.dumps(in_progress(sys.argv[2]), indent=1))
    else:
        sys.exit(__doc__)
