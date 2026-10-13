# CLAUDE.md

This repo holds my Claude Code setup and my general-purpose skills, one per `skills/<name>/` folder. A skill tied to my own projects, accounts or data goes in the private `~/dev/private-skills` repo instead; this repo is public. Matt Pocock's skills are not copied here: `scripts/update.sh` pulls his repo and links them. Other external skills and plugins are recorded as install commands in `HARNESS.md`.

## Skill layout

```
skills/<name>/
  SKILL.md       required
  <anything>     reference docs, scripts, profiles the skill names by path
```

`SKILL.md` frontmatter needs `name` (matches the folder, kebab-case) and `description`. Write the description as the trigger: what the skill does, then the phrases or situations that should fire it, one phrase per distinct case. Add `disable-model-invocation: true` for a skill that should run only when typed by name. Add `allowed-tools` only with specific patterns (`Bash(git log *)`, not `Bash(*)`). Leave `model` unset so the skill runs on the session's model.

## When a skill is added, renamed or removed

1. Update the table in `README.md` so it lists exactly the folders in `skills/`.
2. Run `scripts/update.sh` so `~/.claude/skills/` matches.

Installing or removing a skill or plugin from elsewhere means editing `HARNESS.md` instead.
