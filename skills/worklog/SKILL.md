---
name: worklog
description: Writes a plain one-page work report from the Claude Code sessions, pull requests and Jira - the tickets worked on, support tickets, incidents, code reviews given and pull requests opened - with what each ticket cost, for a performance review or a brag document. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

Run `python3 worklog.py report [period] [--no-cost] [--no-usage]` from this skill's folder.

- period: empty for this month, `last-month` when the arguments ask for last month (in any language), or a first day such as `2026-07-01`.
- `--no-cost` when they ask to leave costs out, such as for a page to share; `--no-usage` when they ask to leave out the Claude Code usage and context.

The script writes the page, opens it and prints a few lines. Pass those lines on; do not read the page.

Only when the arguments include `share`: after the report, read the page printed after `Page:` and publish it with the Artifact tool (icon `chart`), then give the link. It is private until the user shares it. Without `share`, nothing leaves the machine; the shell alias `worklog` runs the same script with no model.

Settings are the constants at the top of `worklog.py`: `JIRA_URL`, `JIRA_PREFIXES` (every Jira project whose keys you use), `SUPPORT_PREFIXES`, `EXCLUDE_REPOS`; the repo holds placeholders. `github.py` and `jira.py` fetch pull requests and issues; each runs on its own. A `SessionEnd` hook runs `worklog.py record`. When the user asks why a session landed where it did, read the docstrings of `collect`, `ticket` and `Jira.pick`.
