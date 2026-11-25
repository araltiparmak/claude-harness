#!/usr/bin/env python3
"""Links into AgentsView (https://agentsview.io), which keeps the same session ids as Claude Code: a session opens
in its desktop app, and a ticket opens the list of its sessions, which the report labels ticket=KEY.

  python3 agentsview.py SINCE     prints {session id: its ticket= label} for the sessions active since that day

The report labels only when the agentsview CLI is installed, and changes no label but its own ticket= one. A
ticket's link is the local server that the CLI and the desktop app share, so it opens while either one runs.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

CLI = shutil.which("agentsview")
APP = Path("/Applications/AgentsView.app").exists()  # its agentsview:// links open one session, not a list
SERVER = "http://127.0.0.1:8080"
LABEL = "ticket="


def session_url(sid):
    return f"agentsview://sessions/{sid}" if APP else ""


def ticket_url(key):
    return f"{SERVER}/sessions?label={quote(LABEL + key)}" if CLI else ""


def run(*args):
    return subprocess.run([CLI, *args], capture_output=True, text=True, timeout=120, check=True).stdout


def held(since):
    """{session id: its ticket= label, or ''} for the sessions active since that day, one page at a time."""
    found, cursor = {}, []
    while True:
        page = json.loads(run("session", "list", "--date-from", since, "--include-one-shot", "--include-automated",
                              "--limit", "500", "--json", *cursor))
        for s in page["sessions"]:
            found[s["id"]] = next((label for label in s["labels"] if label.startswith(LABEL)), "")
        if not page.get("next_cursor"):
            return found
        cursor = ["--cursor", page["next_cursor"]]


def label(tickets, since):
    """Gives each session in {session id: ticket key or ''} the label ticket=KEY, and takes it off a session whose
    ticket changed or went; only the sessions that differ are written. Says so when AgentsView fails."""
    if not CLI:
        return
    try:
        have = held(since)
        for sid, key in tickets.items():
            want, old = LABEL + key if key else "", have.get(sid, "")
            if want != old:
                run("session", "label", sid, *([want] if want else []), *(["--remove", old] if old else []))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as err:
        print(f"AgentsView labels not updated: {err}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not CLI:
        sys.exit(__doc__)
    print(json.dumps(held(sys.argv[1]), indent=1))
