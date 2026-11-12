---
name: worklog
description: Reports the work done with Claude Code by type (task, review, alert, support) and by epic or project, with sessions, days, tokens, pull requests, reviews given and Jira tickets, for a performance review or a brag document. Runs only when typed as /worklog.
disable-model-invocation: true
---

# Worklog

Arguments passed: $ARGUMENTS

A `SessionEnd` hook runs `worklog.py record` (this skill's folder), which adds one row per session to `<dev_dir>/worklog/sessions.jsonl`. The report is built from that ledger by rules, without a model. Settings are in `config.json` next to the script; copy `config.example.json` when it is missing. All keys are optional:

- `dev_dir`: the folder that holds the repos. The data folder is `<dev_dir>/worklog`.
- `jira_prefixes`: Jira project prefixes, such as `ABC` for `ABC-123`. Empty on a machine without Jira; sessions are then grouped by repo.
- `support_prefixes`: the prefixes whose tickets are support investigations.
- `jira_cmd`: the command that prints one issue as Jira REST JSON; `{key}` is the issue key.
- `jira_search_cmd`: the command that prints the issues a JQL query finds as JSON; `{jql}` is the query.

## Report

1. Run `python3 worklog.py report` from this skill's folder. A date argument (`2026-07-01`) limits it to sessions and PRs from that day on. The script first records every transcript still on disk, so sessions from before the hook existed, or whose hook did not run, are included.
2. When the output ends with `Sessions without a type`, choose `task`, `review`, `alert` or `support` for each from its title, or `other` when none fits. Merge them into `<dev_dir>/worklog/labels.json` as `{"<session id>": "<type>"}`, then run the report again.
3. Show the report, then open the page with `open <path>`, where `<path>` is the report's last line (`Page: ...`). The page is the same report with charts, written by the script from `report.html` in this skill's folder; do not read or edit the generated file.
4. For each group with merged PRs and no note, draft two or three outcome lines from the PR titles and ask the user for their role and the impact in numbers. Never invent a number.

## Page only

When the user asks only to see or refresh the page, run `python3 worklog.py html [since]`. It writes `<dev_dir>/worklog/report.html` and opens it in the browser; say where the file is and nothing more.

## Pull requests only

When the user asks only about pull requests ("my PRs of the last 30 days"), run `python3 worklog.py prs [days]` and show its output. It lists each PR the user opened (status, requests for changes, time to first review and to merge, size) and sums up the reviews the user gave. "Rejected" means closed without merge.

## Notes

When the user gives the role, outcome or impact of an epic or project, write it to `<dev_dir>/worklog/notes/<group>.md`, where `<group>` is the first word of the group's heading in the report (the epic key or the repo name). The report prints that file under the heading.

## Rules the script applies

One type per session, first match: a PagerDuty link is an `alert`; a key with a support prefix is `support`; a session that ran `/code-review` or `gh pr diff|review|checkout` and edited no file is a `review`; any other Jira key is a `task`. A ticket is grouped under its parent epic, read from Jira once and cached in `jira.json`. The PRs the user opened come from one GitHub search through `gh api graphql` and join a group by the Jira key in their title, or by repo name. With Jira prefixes set, the report also counts the tickets resolved per type, with the median days from created to resolved, and the user's share of each epic's tickets.
