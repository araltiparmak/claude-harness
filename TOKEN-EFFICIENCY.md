# Token efficiency

Everything that loads at session start costs tokens on every turn: tool schemas, skill descriptions, `CLAUDE.md`, plugin hooks. Keep that small, and measure with `/context` before and after a change.

## Rule of thumb

Load a thing only where it is used. Scope order, from cheapest to most expensive:

1. Not installed.
2. Installed for one project (`--scope project` or `local`).
3. Installed for the user (every session pays).

## Plugins

- Install with project scope unless every project uses the plugin: `claude plugin install <name> --scope project` from the project folder.
- Audit with `claude plugin list`, and remove what went unused for a month.

## MCP servers

An MCP server adds all of its tool names to every session; a CLI costs nothing until it is called.

- Prefer a CLI when one exists: `gh` instead of the GitHub MCP, `cf` instead of a Cloudflare MCP, the `supabase` and `aws` CLIs the same way.
- Keep user-scope MCP servers at zero. Add a server only in the repo that needs it, from that repo's folder: `claude mcp add --scope project <name> ...`.
- Playwright MCP returns large page snapshots: keep it in the repos that test a UI.
- Turn a server off for one session with `/mcp`.

## claude.ai connectors

Connectors and plugins synced from the claude.ai account load in every session and cannot be removed from config. Turn off the ones not used daily at claude.ai under Settings → Connectors, or per session with `/mcp`.

## Skills

Each skill puts its `description` into every session.

- Keep descriptions short; long trigger lists cost tokens on every turn.
- Add `disable-model-invocation: true` to skills started only by hand; their description then stays out of context.
- Link only the skills you use from bulk sources such as skills.sh, and remove skills that never fire.

## Instructions

- Keep `~/.claude/CLAUDE.md` and project `CLAUDE.md` files short. Every line is read on every turn.
- Put long reference material in a doc and point to it by path.
- Leave out of `CLAUDE.md` what the code or the README already says.

## Settings

- `effortLevel: medium` and Opus by default; raise effort for a hard task, switch to Sonnet with `/model` for routine work.
- `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`: subagents need good judgment (code review starts some), so not Haiku. Give a custom search agent `model: haiku` in its own definition for cheap sweeps.
- Keep `autoCompactEnabled` on.
- Reads of `node_modules`, `dist`, `.next` and `coverage` are denied. Grep and Glob already skip ignored files; the rule covers repos without `.gitignore`, paths from stack traces, and minified bundles. It does not stop Bash, so keep commands narrow. To read library source on purpose, allow that one path for the session.
- The status line runs the globally installed `ccstatusline` (`npm i -g ccstatusline`), not `npx -y ...@latest`, so a refresh makes no network lookup.

## Habits

- `/clear` between unrelated tasks; a long thread is re-sent on every turn.
- `/compact` with a focus note at natural breakpoints, before the context is full.
- Ask for a plan or a file list first, then read only those files.
- Use a subagent for broad searches and noisy output; only its summary returns.
- Give exact file paths and line ranges when you know them.

## Measuring

- `/context`: what fills the context right now.
- `/insights`: a report of recent sessions, where time and tokens went and what repeated.
- `/cost` and the status line: spend while working.
- `codeburn` (`brew install codeburn`) and `agentsview` (`brew install --cask agentsview`) read the local session logs in `~/.claude/projects/` and show tokens and cost by task, tool, model and project.

## Before adding a plugin, MCP server or skill

1. Is there a CLI that does it?
2. Which single project needs it? Install it there.
3. What does `/context` show before and after?
