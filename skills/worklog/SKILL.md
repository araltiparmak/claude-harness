---
name: worklog
description: Writes a plain one-page work report from the Claude Code sessions, pull requests and Jira - the tickets worked on, support tickets, incidents, code reviews given and pull requests opened - with what each ticket cost, for a performance review or a brag document. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

Run these from this skill's folder.

1. Run `python3 worklog.py unmapped [period]`. It prints the sessions the rules gave no ticket (date, repo, branches, title, first prompt, cost) and the period's tickets (key, summary, type, repos).
2. For each session, choose a ticket from that list only when its title, prompt, repo or branch clearly matches the ticket's summary or repos. Leave a session unmapped when it is personal, general or unclear; it stays in Other work. Do not invent keys.
3. Save your choices in one call: `python3 worklog.py map SESSION KEY [SESSION KEY...]`. They go to `<DEV_DIR>/worklog/mapped.json` and are used by every later report, the alias too. To undo a choice, remove its line from that file.
4. Run `python3 worklog.py report [period] [--no-cost] [--no-usage]`.

- period: empty for this month, `last-month` when the arguments ask for last month (in any language), or a first day such as `2026-07-01`.
- `--no-cost` when they ask to leave costs out, such as for a page to share; `--no-usage` when they ask to leave out the Claude Code usage and context.

The report writes the page and a CSV of the tickets, opens the page and prints a few lines. Pass those lines on with how many sessions you mapped and to which tickets; do not read the page.

Only when the arguments include `share`: after the report, read the page printed after `Page:` and publish it with the Artifact tool (icon `chart`), then give the link. Keep one link: `<DEV_DIR>/worklog/share.json` holds its artifact URL; when it has one, read that artifact and publish to its URL, otherwise publish a new one and write its URL there. It is private until the user shares it. Without `share`, only the session titles and first prompts from step 1 go to the model; the shell alias `worklog` runs the report alone, with no model and no new mapping.

Settings live in `~/.config/worklog.json`, outside the repo; `config.py` lists the keys (`jira_url`, `jira_prefixes`, `support_prefixes`, `exclude_repos`, `dev_dir`, and the two Jira commands). With no file, every setting is empty and no ticket is found. `github.py` and `jira.py` fetch pull requests and issues; each runs on its own. A `SessionEnd` hook runs `worklog.py record`. A `SessionStart` hook runs `worklog.py start`: in a work repo on a branch with no ticket key, it tells Claude to ask once which ticket the session is for, so the key lands in the user's text. With `JIRA_PREFIXES` empty, it does nothing. When the user asks why a session landed where it did, read the docstrings of `collect`, `ticket` and `Jira.pick`.
