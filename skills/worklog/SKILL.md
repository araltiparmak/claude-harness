---
name: worklog
description: Writes a plain one-page work report from the Claude Code sessions, pull requests and Jira - the tickets worked on, support tickets, code reviews given and pull requests opened - with a one-line outcome, the active time and the cost of each ticket, for a performance review or a brag document. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

Run these from this skill's folder.

1. Run `python3 worklog.py prepare [period]`. It prints JSON: `sessions`, the sessions the rules gave no ticket (date, repo, branches, title, first prompt, cost); `tickets`, the period's tickets with their sub-tasks, pull request titles, session titles, hours, cost and current note; and `assigned`, the other Jira issues assigned to the user and updated in the period.
2. Map: for each session, choose a key from `tickets` (or a sub-task) or `assigned` only when its title, prompt, repo or branch clearly matches. Leave a session unmapped when it is personal, general or unclear; it stays in Other work. Do not invent keys. Save the choices in one call: `python3 worklog.py map SESSION KEY [SESSION KEY...]`. They go to `<DEV_DIR>/worklog/mapped.json`, and the page marks those sessions as mapped. To undo one, remove its line from that file.
3. Notes: for each ticket in `tickets` that cost $1 or more, plus each ticket you just mapped sessions to, write one sentence on what was done, from its pull request and session titles: past tense, plain words, the outcome first, at most 20 words, no cost, no guesses beyond those titles. Keep a current note that still fits. Save them in one call: `python3 worklog.py note KEY "sentence" [KEY "sentence"...]`. They go to `<DEV_DIR>/worklog/notes.json` and show at the top of the ticket's box.
4. Run `python3 worklog.py report [period] [--no-cost] [--no-usage]`.

- period: empty for this month, `last-month` when the arguments ask for last month (in any language), or a first day such as `2026-07-01`.
- `--no-cost` when they ask to leave costs out, such as for a page to share; `--no-usage` when they ask to leave out the Claude Code usage and context.

The report writes the page, opens it and prints a few lines. Pass those lines on with how many sessions you mapped and to which tickets, and how many notes you wrote; do not read the page.

Only when the arguments include `share`: after the report, read the page printed after `Page:` and publish it with the Artifact tool (icon `chart`), then give the link. Keep one link: `<DEV_DIR>/worklog/share.json` holds its artifact URL; when it has one, read that artifact and publish to its URL, otherwise publish a new one and write its URL there. It is private until the user shares it. Without `share`, only what `prepare` prints goes to the model; the shell alias `worklog` runs the report alone, with no model, using the mappings and notes saved before.

Settings live in `~/.config/worklog.json`, outside the repo; `config.py` lists the keys (`jira_url`, `jira_prefixes`, `support_prefixes`, `exclude_repos`, `dev_dir`, and the two Jira commands). With no file, every setting is empty and no ticket is found. `github.py` and `jira.py` fetch pull requests and issues; each runs on its own. A `SessionEnd` hook runs `worklog.py record`. When the user asks why a session landed where it did, read the docstrings of `collect`, `ticket` and `Jira.pick`.
