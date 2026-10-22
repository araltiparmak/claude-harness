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

Connectors and plugins synced from the claude.ai account load in every session.

- A synced plugin turns off with `claude plugin disable <name>@synced --scope user`. That writes `"<name>@synced": false` into the live settings, so copy it into `enabledPlugins` in `claude/settings.json` before the next `update.sh`.
- A connector (Gmail, Drive, Notion, ...) turns off only at claude.ai under Settings → Connectors, or per session with `/mcp`.

## Skills

Each skill puts its `description` into every session.

- Keep one trigger phrase per distinct case and cut the synonyms. A description too short to fire costs more than its tokens.
- Add `disable-model-invocation: true` only to skills you always type by name: their description stays out of context, and Claude never starts them on its own.
- List only the skills you use in `external-skills.yaml`, and delete the line of a skill that never fires.

## Instructions

- Keep `~/.claude/CLAUDE.md` and project `CLAUDE.md` files short. Every line is read on every turn.
- Put long reference material in a doc and point to it by path.
- Leave out of `CLAUDE.md` what the code or the README already says.

## Settings

- Opus at medium effort by default (`modelSettings`, which `/effort` writes). Raise it with `/effort high` for hard debugging or design; switch to Sonnet with `/model` for quick questions.
- Subagents run on the session's model: code review and other judgment work hands off to them. Give a custom search agent `model: haiku` in its own definition for cheap sweeps.
- Keep `autoCompactEnabled` on.
- Reads of `node_modules`, `dist`, `.next` and `coverage` are denied. Grep and Glob already skip ignored files; the rule covers repos without `.gitignore`, paths from stack traces, and minified bundles. It also blocks Bash commands that read those paths (`grep`, `cat`), so a check that must read build output belongs inside a script. To read library source on purpose, allow that one path for the session.
- The status line runs the globally installed `ccstatusline` (`npm i -g ccstatusline`), not `npx -y ...@latest`, so a refresh makes no network lookup.

## Habits

- `/clear` between unrelated tasks; a long thread is re-sent on every turn.
- `/compact` with a focus note at natural breakpoints, before the context is full.
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
