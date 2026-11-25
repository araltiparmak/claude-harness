# worklog

A monthly look at how you work with Claude Code, and what the work was. It reads the session records Claude Code
keeps on your computer, your pull requests (`gh`) and your Jira issues (`jira` CLI), and writes one HTML page.

It is for learning about your own habits: where tokens go, which sessions went smoothly, and what you delivered.
It is not a way to compare people. Costs are estimates at API list prices (see [Cost](#cost)), and time is an
estimate from message times, so both vary with how a person works, not only with how much they do.

## What you get

`/worklog` writes `report.html`, your page:

- **Using Claude well**: tips that appear when a measure crosses a rule-of-thumb line, the measures themselves,
  and your 10 most expensive sessions with their peak context, prompts, interrupts and failed tool calls.
- **The work**: sessions sorted into Jira tickets (with sub-tasks), pull requests without a ticket, other work and
  code reviews, each with active time and cost; a one-line outcome per ticket.
- **Tokens and context**: context sizes, the peak of each session, tokens per model and cost per day.
- **Tools used**: skills, MCP servers and subagents, and the installed skills no session used.

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

3. Write your settings to `~/.config/worklog.json`. Every key is optional; a key you leave out keeps its default
   from `settings.json`:

   ```json
   {"jira_url": "https://yourcompany.atlassian.net", "jira_prefixes": ["ABC"], "support_prefixes": ["SUP"],
    "exclude_repos": ["my-side-project"], "dev_dir": "~/code"}
   ```

   | Key | What it is |
   |---|---|
   | `jira_url` | Ticket keys link to `<jira_url>/browse/<key>` |
   | `jira_prefixes` | Every Jira project whose keys you use, such as `ABC` for `ABC-123` |
   | `support_prefixes` | The prefixes of support tickets |
   | `exclude_repos` | Repos (folder or GitHub name) the report leaves out |
   | `dev_dir` | The folder that holds your repos; the data goes to `<dev_dir>/worklog` |
   | `jira_issue_cmd`, `jira_search_cmd` | The commands that print Jira JSON for one issue (`{key}`) and for a JQL query (`{jql}`) |
   | `jira_in_progress` | The name of the status your Jira uses for work in progress |
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
| Other models in sessions that changed nothing | The part of those not on `question_model` (Sonnet) | over 10% |
| Sessions you interrupted | Sessions with at least one "Request interrupted by user" | over 20% |
| Failed tool calls per session | Tool results marked as errors | over 3 |
| Sessions compacted | Sessions where the context was compacted | 3 or more |

Tips need at least 5 sessions. The lines and the advice are in `TIPS` in `worklog.py`.

Active time adds up the gaps between a session's messages and leaves out every gap over 15 minutes. Sessions that
run side by side add up, so the total can be more than the hours on the clock.

## Cost

A session's cost and tokens are Claude Code's own figures when `~/.claude.json` still holds them. Claude Code
keeps there the figures of the last session in each folder, written about a second after the session ends, and
they count API calls the transcripts leave out: 3 to 9% more cost in the Opus and Fable sessions compared. The
SessionEnd hook waits up to 30 seconds for them, and every report takes the ones still there. The subagent cost
is scaled by the same ratio. A model that Claude Code's figures name but none of the session's replies used is
Claude Code's own work and shows as Background.

A session without those figures is priced from its transcript's tokens at the list prices in `models.json`:

| Key | What it is |
|---|---|
| `models` | Per model id: the name on the page, its colour (`1` to `3`; a model without one is grey), `prices` in USD per million tokens (input, output, cache read, 5-minute and 1-hour cache write), and `fast` prices for a model that has fast mode. An id that starts with a listed one, such as a dated id, takes its entry |
| `default_model` | How an unlisted model is priced |
| `question_model` | The cheaper model the tips suggest for sessions that only ask questions |

The list holds Opus 5.5 and Sonnet 5.5, plus Fable 5.2, which some sessions ran on; priced as Opus, a Fable
session would show about half its cost. When a new model comes out, add its id and prices to `models`.

## Data

Everything stays in `<dev_dir>/worklog` on your computer: `sessions.jsonl` (one row per session, including the
first 200 characters of your first prompt), `jira.json` (issue names), `mapped.json` and `notes.json` (what Claude
saved), and the pages. Nothing is sent anywhere unless you run `/worklog share` and publish the link.

## Files

`worklog.py` (commands, sorting, measures and tips), `ledger.py` (reads and prices sessions), `page.py` and
`report.html` (the page), `github.py` and `jira.py` (fetching; each runs on its own), `settings.py` and
`settings.json` (settings), `models.json` (models and prices), `test_worklog.py`
(`python3 -m unittest test_worklog`).
