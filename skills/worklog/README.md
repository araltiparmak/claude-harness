# worklog

A monthly look at how you work with Claude Code, and what the work was. It reads the session records Claude Code
keeps on your computer, your pull requests (`gh`) and your Jira issues (`jira` CLI), and writes one HTML page.

It is for learning about your own habits: where tokens go, which sessions went smoothly, and what you delivered.
It is not a way to compare people. Costs are estimates at API list prices, and time is an estimate from message
times, so both vary with how a person works, not only with how much they do.

## What you get

`/worklog` writes `report.html`, your page:

- **Using Claude well**: tips that appear when a measure crosses a rule-of-thumb line, the measures themselves,
  and your 10 most expensive sessions with their peak context, prompts, interrupts and failed tool calls.
- **The work**: sessions sorted into Jira tickets (with sub-tasks), pull requests without a ticket, other work and
  code reviews, each with active time and cost; a one-line outcome per ticket.
- **Tokens and context**: context sizes, the peak of each session, tokens per model and cost per day.
- **Tools used**: skills, MCP servers and subagents.

`/worklog share` writes `share.html` for other readers (a manager, a review document): the work, outcomes and
time, with no costs and none of the Using Claude sections. It can also publish it as a private Artifact link.

## Setup

Needs macOS or Linux, Python 3.9 or newer, and git. `gh` and the `jira` CLI are optional; without them the page
has no pull requests or ticket names.

1. Put this folder at `~/.claude/skills/worklog` (copy it, or link it from a clone).
2. Add the hook that records each session when it ends, and keep transcripts long enough for the report to catch
   sessions the hook missed. In `~/.claude/settings.json`:

   ```json
   {
     "cleanupPeriodDays": 90,
     "hooks": {
       "SessionEnd": [{"hooks": [{"type": "command", "command": "python3 $HOME/.claude/skills/worklog/worklog.py record"}]}]
     }
   }
   ```

3. Write your settings to `~/.config/worklog.json`. Every key is optional; `config.py` describes each one:

   ```json
   {"jira_url": "https://yourcompany.atlassian.net", "jira_prefixes": ["ABC"], "support_prefixes": ["SUP"],
    "exclude_repos": ["my-side-project"], "dev_dir": "~/code"}
   ```

   `dev_dir` is the folder that holds your repos; the data goes to `<dev_dir>/worklog`.
4. Log in: `gh auth login`, and `jira init` for the [jira CLI](https://github.com/ankitpokhrel/jira-cli) (or set
   `jira_issue_cmd` and `jira_search_cmd` to another command that prints Jira JSON).
5. Check: `python3 ~/.claude/skills/worklog/worklog.py check` prints one line per part of the setup.

## Use

| In Claude Code | In a shell (no model) | What it does |
|---|---|---|
| `/worklog` | `worklog.py report` | This month, your page |
| `/worklog last-month` | `worklog.py report last-month` | Last month |
| `/worklog 2026-09-01` | `worklog.py report 2026-09-01` | From that day to today |
| `/worklog share` | `worklog.py report --share` | The page for other readers |

`/worklog` also asks Claude to sort the sessions the rules could not place, and to write the one-line outcome per
ticket. It sends Claude only the titles and first prompts of those sessions and the titles of your pull requests.
The shell command reuses what Claude saved before and runs no model.

## How a session finds its ticket

The first rule that matches wins:

1. A ticket key in the branch name, in what you typed, or in the shell commands Claude ran.
2. A pull request from the session's branch whose title, description or commits name a key (also pull requests
   opened before the period).
3. A pull request that holds the commits you made in that repo while the session ran (`git log`, then `gh`).
4. A review session (`gh pr review`, `/code-review`) counts for code reviews.
5. A ticket Claude chose with `/worklog` (saved in `mapped.json`); the page marks these.
6. Everything else is Other work.

A sub-task counts for its parent ticket. Naming the key in the branch, or in your first prompt, is the surest way.

## The measures

| Measure | How it is counted | Tip when |
|---|---|---|
| Cache hit rate | Cache reads over all input tokens | under 85% |
| Cost past 100k context | Cost of sessions whose largest reply context passed 100k tokens | over 50% |
| Cost in subagents | Cost of the replies made by subagents | over 30% |
| Cost in sessions that changed nothing | Sessions with no file edit and no review | over 25% |
| Opus in sessions that changed nothing | The Opus part of those | over 10% |
| Sessions you interrupted | Sessions with at least one "Request interrupted by user" | over 20% |
| Failed tool calls per session | Tool results marked as errors | over 3 |
| Sessions compacted | Sessions where the context was compacted | 3 or more |

Tips need at least 5 sessions. The lines are in `LINES` at the top of `worklog.py`.

Active time adds up the gaps between a session's messages and leaves out every gap over 15 minutes. Sessions that
run side by side add up, so the total can be more than the hours on the clock.

## Data

Everything stays in `<dev_dir>/worklog` on your computer: `sessions.jsonl` (one row per session, including the
first 200 characters of your first prompt), `jira.json` (issue names), `mapped.json` and `notes.json` (what Claude
saved), and the pages. Nothing is sent anywhere unless you run `/worklog share` and publish the link.

## Files

`worklog.py` (commands, sorting, measures and tips), `ledger.py` (reads transcripts), `page.py` and
`report.html` (the page), `github.py` and `jira.py` (fetching; each runs on its own), `config.py` (settings),
`test_worklog.py` (`python3 -m unittest test_worklog`).
