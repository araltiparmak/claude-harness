# Token efficiency

Everything that loads at session start costs tokens on every turn: tool schemas, skill descriptions, `CLAUDE.md`, plugin hooks. This file records how I keep that small. Measure first with `/context`; it shows what each part costs.

## Rule of thumb

Load a thing only where it is used. Scope order, from cheapest to most expensive:

1. Not installed.
2. Installed for one project (`--scope project` or `local`).
3. Installed for the user (every session pays).

## Plugins

- Install plugins with project scope, never user scope, unless every project uses them. `claude plugin install <name> --scope project` from the project folder.
- Current state: `cloudflare` is scoped to `learning-lab`, `expo` to `diction-app` and `diction-v2`. Keep it that way.
- `frontend-design` is the only user-scope plugin. It is one skill description, so the cost is small. Move it to project scope if I stop doing UI work in most repos.
- Audit with `claude plugin list`. Remove what I did not use in the last month.

## MCP servers

An MCP server adds all of its tool names to every session. A server with 20 tools costs more than a CLI that I call only when needed.

- Prefer a CLI over an MCP server when one exists: `gh` instead of the GitHub MCP, `cf` instead of a Cloudflare MCP, `supabase` and `aws` CLIs the same way. The CLI costs nothing until I call it.
- Keep user-scope MCP servers at zero. On 2026-10-14 I removed `github` (use `gh`), `obsidian` and `canva` from user scope, and `playwright` from the `~/dev` scope. Add one back only in the repo that needs it, from that repo's folder:
  - `claude mcp add --scope project playwright -- npx @playwright/mcp@latest`
  - `claude mcp add --scope project --transport http canva https://mcp.canva.com/mcp`
  - `claude mcp add --scope project --transport http github https://api.githubcopilot.com/mcp/`
- Playwright MCP returns large page snapshots. Keep it in the few repos that test a UI, not in `~/dev` as a whole.
- Blender MCP is scoped to `~` only. Leave it.
- Disable a server for one session without removing it: `/mcp`, then toggle.

## claude.ai connectors

Connectors such as Gmail, Google Calendar, Google Drive, Supabase, Context7, Wispr Flow and Claude Docs come from the claude.ai account, not from my config files. They load in every session. Turn off the ones I do not use daily at claude.ai under Settings → Connectors, or per session with `/mcp`.

Same for the design, engineering and productivity plugin connectors (Asana, Atlassian, Figma, Intercom, Linear, Notion, Slack, Datadog, PagerDuty, ClickUp, Monday). I use none of them in `~/dev`. These plugins are synced from the claude.ai account (`claude plugin list` shows them under "Synced from claude.ai"), so I cannot remove them from config. Disable their connectors with `/mcp`.

## Skills

Each skill puts its `description` into every session. About 40 skills are linked in `~/.claude/skills`.

- Write descriptions short. Long trigger lists cost tokens on every turn.
- Add `disable-model-invocation: true` to skills I only start by hand. Their description then stays out of context.
- Remove skills I never call. Check which ones fired before deleting.
- Skills from elsewhere (Matt Pocock's repo, skills.sh) come in bulk. Link only the ones I use.

## Instructions

- Keep `~/.claude/CLAUDE.md` and project `CLAUDE.md` files short. Every line is read on every turn.
- Put long reference material in a doc and point to it by path. The agent reads it only when needed.
- Do not repeat in `CLAUDE.md` what the code or the README already says.

## Settings

- `effortLevel`: set to `medium` here (applied 2026-10-14). Raise it per task and raise it for hard tasks. High effort spends more thinking tokens on every turn.
- `model`: Opus by default (set 2026-10-14). Switch to Sonnet with `/model` for routine work.
- Keep `autoCompactEnabled` on.
- Reads of `node_modules`, `dist`, `.next` and `coverage` are denied. Grep and Glob already skip anything in `.gitignore`, so most of the time this changes nothing. The rule still helps in three cases: a repo without `.gitignore`, a path that an error message or stack trace points to, and a minified bundle that would fill the context in one read. It does not stop Bash (`cat`, `grep -r`), so keep commands narrow. Lock files are not denied: I need them when I debug dependencies.
- If I need to read library source in `node_modules` on purpose, I ask for that one path and allow it for that session.
- The status line runs the globally installed `ccstatusline` binary (`npm i -g ccstatusline`), not `npx -y ...@latest`, so it makes no network lookup on each refresh.

## Habits

- `/clear` between unrelated tasks. A long thread is re-sent on every turn.
- `/compact` with a focus note at natural breakpoints, before the context is full.
- Ask for a plan or a file list first, then read only those files. Do not say "look at the whole repo".
- Use a subagent for broad searches and noisy output (logs, test runs). Only its summary returns to the main thread.
- Pipe command output through `head`, `tail` or `grep` instead of printing all of it.
- Give exact file paths and line ranges when I know them.
- One task per session. Switch model with `/model` instead of starting a bigger session.

## Checklist for a new tool

Before I add a plugin, MCP server or skill:

1. Is there a CLI that does it?
2. Which single project needs it? Install it there.
3. What does `/context` show before and after?

## Measuring: /insights and friends

Measure before and after a change, or the numbers are guesses.

- `/insights` writes a report of my recent sessions: where time and tokens went, what repeated, where I hit friction. Run it monthly and act on the top two findings.
- `/context` shows what fills the context right now: tools, skills, memory files, messages.
- `/cost` and the status line (`Ctx`, `Session %`, `Weekly %`) show spend while I work.
- Check token use with `codeburn` and `agentsview` (neither is installed yet). Both read the local session logs in `~/.claude/projects/`. Install both through Homebrew:
  ```bash
  brew install codeburn
  brew install --cask agentsview
  ```
  - `codeburn` ([codeburn.app](https://codeburn.app/)): a CLI that shows where the tokens go, by task, tool, model and project. Use it to find what costs the most.
  - `agentsview` ([agentsview.io](https://www.agentsview.io/)): a local app that indexes past sessions. It gives token and cost totals per day, project and model, and full-text search over sessions. Use it for the monthly audit. It replaces `ccusage`, so I do not install that.

## Quality skills

Cheap checks that catch expensive mistakes. `simplify` is built into Claude Code; the others are linked in `~/.claude/skills`.

- `tdd`: write the failing test first for features and bug fixes.
- `diagnosing-bugs`: a fixed loop for hard bugs, so I do not guess in circles.
- `code-review`: run after a large change, before I commit.
- `simplify`: trims the diff after the work is done.
- `grilling`: stress-test a plan before I spend a long session on it.

## Settings added for speed and quality

- `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`: every subagent runs on Sonnet. I did not pick Haiku because this variable covers all subagents, including the ones that `code-review` and general-purpose tasks start, and those need good judgment. For cheap sweeps only, give a custom search agent `model: haiku` in its own definition.
- Allowed without asking: `npx tsc`, `prettier`, `eslint`, `vitest`, so checks do not wait for a prompt.

## Ideas not applied yet

- Trim the iTerm `cc-status` hooks to `Notification`, `Stop` and `PermissionRequest`. It saves two process starts per tool call, but the tab may stay on "waiting" after I approve a prompt. Test it first.
- A `Stop` hook that runs typecheck and lint. Add it per project, only where the check takes a few seconds.
- A `PreToolUse` hook that trims long test and build output. Risk: it can cut the line that shows the failure.
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` to compact earlier than the default.

## Periodic audit

Run this about once a month and write the result back here:

1. `/insights`, then `/context` in a fresh session: note the cost of MCP tools, skills and memory files.
2. `claude mcp list` and `claude plugin list`: remove what I did not use.
3. `ls ~/.claude/skills`: unlink skills I did not call, and mark hand-started ones `disable-model-invocation: true`.
4. Check that no user-scope plugin or MCP server crept back.
