---
name: worklog
description: Writes a plain one-page work report from the Claude Code sessions, pull requests and Jira - the tickets worked on, support tickets, incidents, code reviews given and pull requests opened - with what each ticket cost, for a performance review or a brag document. Runs only when typed as /worklog.
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
- `exclude_repos`: repos (folder or GitHub name) whose sessions and pull requests the report leaves out, such as personal projects on a work machine.

## Report

Run `python3 worklog.py report [period] [--no-cost]` from this skill's folder. With no period it reports the current month; pass `last-month` when the arguments ask for last month (in any language), or a first day such as `2026-07-01` to report from that day to today. Pass `--no-cost` when the arguments ask to leave costs out (for example, for a page to share); it removes every cost from the page. It writes the page, opens it in the browser and prints the counts and `Page: <path>`. Do not read the page; pass the counts on to the user.

The page shows, in order: the outcome numbers, the tickets (one section per epic, then the tickets without an epic), support tickets, incidents, pull requests without a ticket, other work (sessions that changed code with no ticket, incident or review behind them), an overview of where the cost went, and the code reviews, each linked to its pull request.

When the user asks why a session or pull request landed where it did, read `collect` and the docstrings of `keys_of`, `ticket`, `Jira.pick`, `Jira.epic`, `reviewed_pr` and `cost` in the script; they hold the rules.
