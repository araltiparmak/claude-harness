---
name: eliminate
description: Lists every plugin, MCP server and skill that loads into each Claude Code session with its token cost and recent use, asks which to remove section by section, and takes the chosen ones out of Claude's context. Runs only when typed as /eliminate.
disable-model-invocation: true
---

# Eliminate

Eliminate the non-essential from Claude's context: everything that loads into every session but earns no use. Quality stays: an item the user still reaches for is kept, or made type-only.

Arguments passed: $ARGUMENTS (a number of days to look back; 90 when empty)

The harness repo is the folder two levels above this skill: `cd -P ~/.claude/skills/eliminate/../.. && pwd`. Below, `<harness>` is that folder.

## 1. Measure

```bash
python3 ~/.claude/skills/eliminate/eliminate.py --list $ARGUMENTS
```

Show the three sections (Plugins, MCP servers, Skills) as printed, then add these short notes under them:

- the total it prints is the saving per session;
- the scope column says where a row loads: `global` in every session, `project <path>` only in sessions started in that folder;
- an `account` skill or `mcp, claude.ai` server comes from claude.ai, so it is switched off there;
- a skill marked `via plugin <name>` has no number: it comes with that plugin and leaves only when the plugin is removed.

Done when the user has the sections and the notes.

## 2. Ask

Let the user tick each unused row on its own, section by section: Plugins, then MCP servers, then Skills. Leave out a section with no unused rows.

Use AskUserQuestion with `multiSelect: true`. Every unused row is one option: label `<#> <name>` and description `<kind>, <scope>, <tokens> tokens` (for a plugin, add how many skills go with it). A question holds at most 4 options, so split a section into questions of 4 rows in table order. Header them `Plugins`, `MCP 1/2`, `Skills 1/8` and so on, and start each question with `Remove which of these?`. A call holds at most 4 questions, so ask the sections over as many calls as it takes; a call never mixes sections. A row left unticked is kept.

The free text (Other) of a question takes extra row numbers from that section, used rows included, and `type-only <#>` for a rarely used skill of the user's own (`own` or `private`): it stays available as `/name` and leaves the context. A `via plugin` skill is never an option; when the user asks for one, name its plugin row instead.

Read back the final list (name, kind, action) grouped by section, and go on once it matches what the user chose.

## 3. Remove

Pass the chosen rows by name, as `--list` printed them, in one call:

```bash
python3 ~/.claude/skills/eliminate/eliminate.py --remove <name> [<name>...]
```

It removes each with the action for its kind, runs `update.sh` when skills or plugins changed, and prints each step with its undo:

| Kind | What it does | Undo |
|---|---|---|
| `own`, `private`, `external` | Adds the name to `SKIP_SKILLS` in `~/.zshrc`; `update.sh` unlinks it | Take the name out, run `update.sh` |
| `local` | Moves `~/.claude/skills/<name>` to `~/.claude/skills.off/<name>` | Move it back |
| `plugin`, `plugin, account`, global | `"<id>": false` under `enabledPlugins` in the harness settings, then `update.sh`; its skills go with it | Set it to `true`, run `update.sh` |
| `plugin`, project `<path>` | `claude plugin disable <id> --scope project` in that project; its skills go with it | `claude plugin enable` |
| `mcp, user` | `claude mcp remove <name> -s user` | `claude mcp add` |
| `mcp, local`, project `<path>` | `claude mcp remove <name> -s local` in that project | `claude mcp add` |

It prints, and does not do, the steps only claude.ai or `/mcp` can take: `account` skills (off on claude.ai one by one, or all at once with `"syncClaudeAiSkills": false` in `<harness>/claude/settings.json` and `update.sh`), `mcp, claude.ai` connectors and `mcp, other` servers. Pass those steps on.

For a type-only row, add `disable-model-invocation: true` to the front matter of the skill's source `SKILL.md` (the real path of `~/.claude/skills/<name>`), then run that repo's check script when it has one (`scripts/check/check.sh` in the harness). Undo: delete the line.

Settings go through the harness repo: `update.sh` writes `~/.claude/settings.json`, so an edit there directly would be reported as drift.

Done when `--remove` has finished and a second `--list` no longer shows the removed rows (account, claude.ai and project rows excepted, which change on claude.ai or in their project).

## 4. Report

One line per removed item with its undo, the steps left for the user, the tokens saved per session, the repo files changed and left uncommitted, and that the change applies to sessions started from now on.
