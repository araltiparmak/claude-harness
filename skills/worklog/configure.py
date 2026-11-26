"""worklog.py setup and worklog.py check: the settings, the SessionEnd hook, and the sources the report reads.

setup asks a few questions, writes ~/.config/worklog.json, offers to add the hook to Claude Code's settings, then
runs check. check prints one line per part of the setup. worklog.py passes setup its own path for the hook: Python
resolves the link this module is imported through, so the path of this file would lose ~/.claude/skills/worklog.
"""
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jira
import ledger
from settings import DEV, FILE, settings

JIRA_PREFIXES = settings["jira_prefixes"]
PREFIXES = JIRA_PREFIXES + settings["support_prefixes"]  # every prefix worklog finds ticket keys by
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"  # where check looks for the hook
LABELS = {True: "ok  ", None: "warn", False: "FAIL"}
TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"
KEEP_DAYS = 90  # cleanupPeriodDays setup asks for


# ---- check

def runs(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_claude(line):
    """The SessionEnd hook and how long Claude Code keeps transcripts."""
    try:
        claude = json.loads(CLAUDE_SETTINGS.read_text()) if CLAUDE_SETTINGS.exists() else {}
    except ValueError:
        claude = {}
        line(False, str(CLAUDE_SETTINGS), "not valid JSON")
    line(has_hook(claude) or None, "SessionEnd hook", "missing; run worklog.py setup")
    keep = claude.get("cleanupPeriodDays", 30)
    line(keep >= 60 or None, f"transcripts kept {keep} days", 'set "cleanupPeriodDays": 90 so report catches '
                                                              "sessions the hook missed")


def check_sources(line):
    """git, gh and Jira, which the report asks for pull requests and issues."""
    line(runs(["git", "config", "user.email"]) or None, "git user.email",
         "not set; commits cannot find their pull requests")
    line(bool(shutil.which("gh")) and runs(["gh", "auth", "status"]) or None, "gh",
         "not installed or not logged in (gh auth login); no pull requests or reviews")
    if PREFIXES:
        try:
            jira.search("updated >= -1d")
            line(True, "Jira search")
        except Exception as err:  # not set up, not reachable, login refused
            line(None, "Jira search", f"failed ({err}); set jira_url, jira_email and JIRA_API_TOKEN; tickets show "
                                      "by key only")


def check():
    """One line per part of the setup: ok, warn (the report runs but misses something) or FAIL; exits 1 on a FAIL."""
    found = []

    def line(ok, what, fix=""):
        found.append(ok)
        print(f"{LABELS[ok]}  {what}" + (f": {fix}" if fix and ok is not True else ""))
    line(FILE.exists() or None, f"settings {FILE}", "not found; run worklog.py setup")
    line(bool(PREFIXES) or None, f"jira_prefixes {', '.join(JIRA_PREFIXES)}".strip(),
         "empty, so no session finds a ticket; run worklog.py setup")
    line(DEV.is_dir() or None, f"dev_dir {DEV}", "not a folder; sessions are named by their own folder")
    check_claude(line)
    if ledger.LEDGER.exists():
        with ledger.LEDGER.open() as rows:
            line(True, f"ledger {ledger.LEDGER}, {sum(1 for _ in rows)} sessions")
    else:
        line(None, f"ledger {ledger.LEDGER}", "none yet; the first report builds it from the transcripts")
    check_sources(line)
    if False in found:
        sys.exit(1)


# ---- setup

def hook_command(script):
    """The SessionEnd command that runs script (worklog.py, by the path it was started from), with $HOME for the
    home folder. The path keeps any link it was run through (such as ~/.claude/skills/worklog), so the hook
    survives a moved clone."""
    home = str(Path.home())
    path = "$HOME" + script[len(home):] if script.startswith(home + os.sep) else script
    return f'python3 "{path}" record' if " " in path else f"python3 {path} record"  # "" keep $HOME working


def has_hook(claude):
    """Whether Claude Code settings run worklog.py record when a session ends."""
    return bool(re.search(r'worklog\.py\W*\s+record', json.dumps(claude.get("hooks", {}).get("SessionEnd", []))))


def with_hook(claude, command):
    """Claude Code settings with the SessionEnd hook (command) and cleanupPeriodDays of KEEP_DAYS or more added,
    and the names of what changed; settings that already have them come back unchanged."""
    claude, changed = json.loads(json.dumps(claude)), []
    if not has_hook(claude):
        hook = {"hooks": [{"type": "command", "command": command}]}
        claude.setdefault("hooks", {}).setdefault("SessionEnd", []).append(hook)
        changed.append("SessionEnd hook")
    if claude.get("cleanupPeriodDays", 30) < KEEP_DAYS:
        claude["cleanupPeriodDays"] = KEEP_DAYS
        changed.append(f"cleanupPeriodDays {KEEP_DAYS}")
    return claude, changed


def answer(ask, question, default=""):
    """What the user typed, or the default for an empty line."""
    typed = ask(f"{question}" + (f" [{default}]" if default else "") + ": ").strip()
    return typed or default


def yes(ask, question):
    return answer(ask, f"{question} (Y/n)", "").lower() not in ("n", "no")


def setup_jira(ask, secret, mine):
    """Asks for the Jira site and login, tests them and finds the prefixes of your issues. Returns the Jira keys
    for the settings file, and the prefixes found (empty when Jira is skipped or refuses)."""
    url = answer(ask, "Jira Cloud site, such as https://yourcompany.atlassian.net (empty to skip Jira)",
                 mine.get("jira_url", ""))
    if not url:
        return {}, []
    url = url if url.startswith("http") else "https://" + url
    found = {"jira_url": url.rstrip("/"),
             "jira_email": answer(ask, "The email you log in to Jira with", mine.get("jira_email", ""))}
    if not os.environ.get("JIRA_API_TOKEN"):
        print(f"No JIRA_API_TOKEN in this shell. Make a token at {TOKEN_URL}", flush=True)
        token = secret("Paste it to test the login now (it is not saved; empty to skip): ").strip()
        if not token:
            return found, []
        os.environ["JIRA_API_TOKEN"] = token
        print("Add this line to your shell profile (~/.zshrc or ~/.bashrc) so Claude Code sees it:\n"
              "  export JIRA_API_TOKEN='<the token>'")
    settings.update(found)  # jira.call reads the login from here
    try:
        print(f"Logged in to Jira as {jira.myself() or found['jira_email']}")
        return found, jira.prefixes()
    except Exception as err:  # wrong site, refused login, no network
        print(f"Jira did not answer ({err}); the settings are saved anyway, run setup again to retry")
        return found, []


def setup(script, ask=input, secret=getpass.getpass):
    """Writes ~/.config/worklog.json from a few questions, adds the SessionEnd hook that runs script to Claude
    Code's settings when the user agrees, then runs script's check. Keeps every setting it does not ask about."""
    try:
        mine = json.loads(FILE.read_text()) if FILE.exists() else {}
    except ValueError:
        sys.exit(f"{FILE} is not valid JSON; fix or delete it, then run setup again")
    found, detected = setup_jira(ask, secret, mine)
    known = mine.get("jira_prefixes") or detected
    if detected:
        print(f"Projects of your Jira issues from the last 90 days: {', '.join(detected)}")
    typed = answer(ask, "Ticket prefixes, comma-separated, such as ABC for ABC-123", ", ".join(known))
    found["jira_prefixes"] = [p.strip().upper() for p in typed.split(",") if p.strip()]
    found["dev_dir"] = answer(ask, "The folder that holds your repos", mine.get("dev_dir", settings["dev_dir"]))
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({**mine, **found}, indent=1, ensure_ascii=False) + "\n")
    print(f"Saved {FILE}")
    setup_hook(ask, hook_command(script))
    print(flush=True)
    # A new process, so check reads the settings just written; it inherits the token typed above.
    subprocess.run([sys.executable, script, "check"])


def setup_hook(ask, command):
    """Adds the SessionEnd hook (command) and cleanupPeriodDays to Claude Code's settings when they are missing and
    the user agrees."""
    try:
        claude = json.loads(CLAUDE_SETTINGS.read_text()) if CLAUDE_SETTINGS.exists() else {}
    except ValueError:
        print(f"{CLAUDE_SETTINGS} is not valid JSON; README.md shows the hook to add by hand")
        return
    updated, changed = with_hook(claude, command)
    if not changed:
        print(f"{CLAUDE_SETTINGS} already has the hook")
    elif yes(ask, f"Add {' and '.join(changed)} to {CLAUDE_SETTINGS}?"):
        CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        CLAUDE_SETTINGS.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n")
        print(f"Saved {CLAUDE_SETTINGS}; it applies to sessions started from now on")
    else:
        print("Skipped; README.md shows the lines to add by hand")
