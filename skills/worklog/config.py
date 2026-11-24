"""The worklog settings, read from ~/.config/worklog.json, outside the repo. Every key is optional:

  {
    "jira_url": "https://example.atlassian.net",
    "jira_prefixes": ["ABC"],
    "support_prefixes": ["SUP"],
    "exclude_repos": ["my-side-project"],
    "dev_dir": "~/dev",
    "jira_issue_cmd": "jira issue view {key} --raw",
    "jira_search_cmd": "jira issue list -q {jql} --raw",
    "jira_in_progress": "In Progress"
  }

jira_url: ticket keys link to <jira_url>/browse/<key>. jira_prefixes: every Jira project whose keys you use, such
as ABC for ABC-123. support_prefixes: the prefixes of support tickets. exclude_repos: repos (folder or GitHub name)
the report leaves out. dev_dir: the folder that holds the repos; the data lives in <dev_dir>/worklog.
jira_issue_cmd and jira_search_cmd: the commands that print Jira JSON for one issue ({key}) and for a JQL query ({jql}).
jira_in_progress: the name of the status your Jira uses for work in progress.
"""
import json
from pathlib import Path

FILE = Path.home() / ".config" / "worklog.json"
DEFAULTS = {"jira_url": "", "jira_prefixes": [], "support_prefixes": [], "exclude_repos": [], "dev_dir": "~/dev",
            "jira_issue_cmd": "jira issue view {key} --raw", "jira_search_cmd": "jira issue list -q {jql} --raw",
            "jira_in_progress": "In Progress"}
settings = {**DEFAULTS, **(json.loads(FILE.read_text()) if FILE.exists() else {})}
DEV = Path(settings["dev_dir"]).expanduser()  # the folder that holds the repos
DATA = DEV / "worklog"  # the ledger, the Jira cache, the saved mappings and notes, the pages
