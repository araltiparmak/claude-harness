# CLAUDE.md

This repo holds my Claude Code setup: my general-purpose skills (`skills/<name>/`), my settings and global instructions (`claude/`), and `scripts/update.sh`, which installs all of it into `~/.claude`. The repo is public. Anything tied to my own projects, accounts or data goes in the private `~/dev/private-skills` repo instead: skills in its `skills/`, settings in its `claude/settings.json` overlay. Matt Pocock's skills are not copied here: `update.sh` pulls his repo and links them. Other external skills and plugins are recorded as install commands in `HARNESS.md`.

## Skill layout

```
skills/<name>/
  SKILL.md       required
  <anything>     reference docs, scripts, profiles the skill names by path
```

`SKILL.md` frontmatter needs `name` (matches the folder, kebab-case) and `description`. Write the description as the trigger: what the skill does, then the phrases or situations that should fire it, one phrase per distinct case. Add `disable-model-invocation: true` for a skill that should run only when typed by name. Add `allowed-tools` only with specific patterns (`Bash(git log *)`, not `Bash(*)`). Leave `model` unset so the skill runs on the session's model.

## Settings

Change settings in `claude/settings.json` (or the private overlay), then run `scripts/update.sh`. Never edit `~/.claude/settings.json` directly: it is generated, and `update.sh` stops with a diff when the live file has drifted from what it last wrote. When that happens, move the change into the repo, then re-run. Write paths as `$HOME/...`, never `/Users/...`.

## Before finishing a change

1. Keep the skill table in `README.md` listing exactly the folders in `skills/`.
2. Run `scripts/check.sh`; CI runs the same script.
3. Run `scripts/update.sh` so `~/.claude` matches.

Installing or removing a skill or plugin from elsewhere means editing `HARNESS.md` instead.
