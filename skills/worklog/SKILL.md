---
name: worklog
description: Writes a one-page report of how the user works with Claude Code and what the work was - tips and measures on tokens, context and session quality, the most expensive sessions, then the Jira tickets, support tickets, pull requests and code reviews with a one-line outcome, active time and cost per ticket - and with share, publishes that whole page as a private Artifact link. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

Run these from this skill's folder.

1. Run `python3 worklog.py prepare [period]`. It prints JSON: `sessions`, the sessions the rules gave no ticket (date, repo, branches, title, first prompt, cost, and `in_progress`: the Jira issues the user had in progress that day); `tickets`, the period's tickets with their sub-tasks, pull request titles, session titles, hours, cost and current note; and `assigned`, the other Jira issues assigned to the user and updated in the period.
2. Map: for each session, choose a key from `tickets` (or a sub-task) or `assigned` only when its title, prompt, repo or branch clearly matches. A single `in_progress` issue is a strong hint, not proof: take it when nothing in the session points elsewhere. Leave a session unmapped when it is personal, general or unclear; it stays in Other work. Do not invent keys. Save the choices in one call: `python3 worklog.py map SESSION KEY [SESSION KEY...]`. They go to `<DEV_DIR>/worklog/mapped.json`, and the page marks those sessions as mapped. To undo one, remove its line from that file.
3. Notes: for each ticket in `tickets` that cost $1 or more, plus each ticket you just mapped sessions to, write one sentence on what was done, from its pull request and session titles: past tense, plain words, the outcome first, at most 20 words, no cost, no guesses beyond those titles. Keep a current note that still fits. Save them in one call: `python3 worklog.py note KEY "sentence" [KEY "sentence"...]`. They go to `<DEV_DIR>/worklog/notes.json` and show at the top of the ticket's box.
4. Run `python3 worklog.py report [period]`.

- period: empty for this month, `last-month` when the arguments ask for last month (in any language), or a first day such as `2026-07-01`.
- Skip step 2 when `sessions` is empty or Jira gave no `tickets` and no `assigned`, and step 3 when `tickets` is empty.

The report writes the page, opens it and prints a few lines, the top tip among them. Pass those lines on with how many sessions you mapped and to which tickets, and how many notes you wrote; do not read the page.

Only when the arguments include `share`: read the page printed after `Page:` and publish it with the Artifact tool (icon `chart`), then give the link. Publish the whole page as the report wrote it; do not remove, shorten or redact any part. The script only writes the page; publishing is your step. Keep one link: `<DEV_DIR>/worklog/share.json` holds its artifact URL; when it has one, read that artifact and publish to its URL, otherwise publish a new one and write its URL there. It is private until the user shares it. Without `share`, only what `prepare` prints goes to the model; `worklog.py report` in a shell runs with no model and reuses the mappings and notes saved before.

When the user asks about setup, or the page misses pull requests, tickets or sessions, run `python3 worklog.py check` and pass on its lines. To set up or change the settings, ask the user to type `! python3 ~/.claude/skills/worklog/worklog.py setup`; it asks questions, so it cannot run from the Bash tool. `README.md` has the setup steps. When the user asks why a session landed where it did, read the docstrings of `collect`, `ticket` and `Jira.pick` in `worklog.py`; for what a measure or tip means, read `measures` and `TIPS` there.
