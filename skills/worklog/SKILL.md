---
name: worklog
description: Writes a plain one-page work report from the Claude Code sessions, pull requests and Jira - the tickets worked on, support tickets, incidents, code reviews given and pull requests opened - for a performance review or a brag document. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

A `SessionEnd` hook runs `worklog.py record` (this skill's folder), which adds one row per session to `<dev_dir>/worklog/sessions.jsonl`. Settings are in `config.json` next to the script; copy `config.example.json` when it is missing. All keys are optional:

- `dev_dir`: the folder that holds the repos. The data folder is `<dev_dir>/worklog`.
- `jira_prefixes`: Jira project prefixes, such as `ABC` for `ABC-123`. Empty on a machine without Jira; sessions are then grouped by repo.
- `support_prefixes`: the prefixes whose tickets are support investigations.
- `jira_url`: the Jira site, such as `https://example.atlassian.net`. When set, ticket keys link to their issue.
- `jira_cmd`: the command that prints one issue as Jira REST JSON; `{key}` is the issue key.
- `jira_search_cmd`: the command that prints the issues a JQL query finds as JSON; `{jql}` is the query.

## Report

Run `python3 worklog.py report [since]` from this skill's folder; `since` is a day such as `2026-07-01`. It writes the page, opens it in the browser and prints the counts and `Page: <path>`. Do not read the page; pass the counts on to the user.

The page lists, in this order: Jira tickets (with epic, the days worked on and whether resolved), support tickets, incidents, the pull requests reviewed for teammates, the pull requests opened (with their ticket and status), and the sessions without a ticket, by repo.

## Rules the script applies

A session counts for one ticket: its first support-prefix key, else its first key. A ticket's epic is its Jira parent, read once and cached in `jira.json`. Tickets resolved in the period appear even without a session. A pull request's ticket is the Jira key in its title. A session with a PagerDuty link is an incident; a session with neither a key nor an incident is listed under its repo, except a review without edits, which the GitHub review list already covers.
