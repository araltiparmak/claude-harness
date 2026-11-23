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

Run `python3 worklog.py report [since] [--no-cost]` from this skill's folder; `since` is a day such as `2026-07-01`. Pass `--no-cost` when the arguments ask to leave costs out (for example, for a page to share); it removes every cost from the page. It writes the page, opens it in the browser and prints the counts and `Page: <path>`. Do not read the page; pass the counts on to the user.

The page opens with the outcomes (tickets resolved, pull requests merged, incidents, reviews; a number that is zero is left out) and the total cost. It then lists, in this order: an overview, opened by a bar and legend with each group's share of the session cost (shown also under `--no-cost`, as percentages only), with the tickets, repos, share and cost of each epic, support, incidents, reviews and other work, whose costs add up to the total; the Jira tickets, one section per epic, linked to Jira, with how many of its tickets are resolved and its repos (each ticket with the days worked on, its pull requests, cost and status), support tickets, incidents, the pull requests reviewed for teammates, the pull requests opened without a ticket, and the sessions without a ticket, by repo.

## Rules the script applies

A session counts for one ticket: its first support-prefix key, else its first key. A ticket's epic is its Jira parent, read once and cached in `jira.json`. Tickets resolved in the period appear even without a session. A pull request's ticket is the first Jira key in its title, branch or description. A session without a key counts for the ticket of a pull request opened from its branch. A session's cost is its replies, subagents included, priced per model at API list prices (`PRICES` in the script); a row recorded before costs were kept is priced as Opus 5.5. A session with a PagerDuty link is an incident; a review without edits counts for code reviews; any other session with neither a key nor an incident is listed under its repo when it edited files, and left out when it only asked questions.
