"""The settings: config.json next to this file over these defaults. Copy config.example.json to start."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = {"dev_dir": "~/dev", "jira_url": "", "jira_prefixes": [], "support_prefixes": [], "exclude_repos": [],
          "jira_cmd": "jira issue view {key} --raw",
          "jira_search_cmd": "jira issue list -q {jql} --raw"}
if (HERE / "config.json").exists():
    CONFIG.update(json.loads((HERE / "config.json").read_text()))
