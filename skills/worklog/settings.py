"""The settings: the defaults in settings.json beside this file, each overridden by the same key in
~/.config/worklog.json. README.md describes each key."""
import json
from pathlib import Path

FILE = Path.home() / ".config" / "worklog.json"  # your settings
settings = {**json.loads((Path(__file__).resolve().parent / "settings.json").read_text()),
            **(json.loads(FILE.read_text()) if FILE.exists() else {})}
DEV = Path(settings["dev_dir"]).expanduser()  # the folder that holds the repos
DATA = DEV / "worklog"  # the ledger, the Jira cache, the saved mappings and notes, the pages
