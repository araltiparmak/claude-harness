---
name: worklog
description: Writes a one-page work summary from the Claude Code sessions, pull requests, reviews and Jira tickets, by epic or project, for a performance review or a brag document. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

A `SessionEnd` hook runs `worklog.py record` (this skill's folder), which adds one row per session to `<dev_dir>/worklog/sessions.jsonl`. Settings are in `config.json` next to the script; copy `config.example.json` when it is missing. All keys are optional:

- `dev_dir`: the folder that holds the repos. The data folder is `<dev_dir>/worklog`.
- `jira_prefixes`: Jira project prefixes, such as `ABC` for `ABC-123`. Empty on a machine without Jira; sessions are then grouped by repo.
- `support_prefixes`: the prefixes whose tickets are support investigations.
- `jira_cmd`: the command that prints one issue as Jira REST JSON; `{key}` is the issue key.
- `jira_search_cmd`: the command that prints the issues a JQL query finds as JSON; `{jql}` is the query.

## Report

1. Run `python3 worklog.py report [since]` from this skill's folder; `since` is a day such as `2026-07-01`. It writes the page, opens it in the browser and prints a short summary that ends with `Page: <path>`. Do not read the page.
2. Each `No note:` line is an epic or project with merged pull requests and no note. Draft two or three outcome lines from the PR titles, and ask the user for their role and the impact in numbers. Never invent a number.
3. Write what the user confirms to `<dev_dir>/worklog/notes/<group>.md`, where `<group>` is the first word of the line's name (the epic key or the repo name), then run the report again.

## Rules the script applies

A ticket is grouped under its parent epic, read from Jira once and cached in `jira.json`; a session without a key is grouped by repo. A PR joins a group by the Jira key in its title, or by repo. One kind per session: a PagerDuty link is an incident, a support-prefix key is support, a review without edits is code review, any other key is planned work.
