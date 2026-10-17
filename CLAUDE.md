# CLAUDE.md

This repo holds a Claude Code setup: general-purpose skills (`skills/<group>/<name>/`), settings and global instructions (`claude/`), and `scripts/update.sh`, which installs all of it into `~/.claude`. The repo is public. Anything tied to private projects, accounts or data goes in an optional second skills repo instead (`PRIVATE_DIR`, see the README): skills in its `skills/`, settings in its `claude/settings.json` overlay. Third-party skills are not copied here: `update.sh` links the ones listed in `external-skills.txt`.

## Language

Everything in this repo is English: skills (every file inside them), docs, scripts, comments and commit messages. `scripts/check.sh` fails on any letter outside ASCII.

## Skill layout

```
skills/<group>/<name>/
  SKILL.md       required
  <anything>     reference docs, scripts, profiles the skill names by path
```

Related skills share a group folder: `visuals/` (deck, diagrams, explain, infographics, mindmap) and `dev/` (cloudflare, mobile-app-stack, react-project, vercel). A folder with a `SKILL.md` is a skill, at any depth; a folder without one is a group. Skill names stay unique across groups, because `update.sh` links each skill into `~/.claude/skills/<name>` by name. A skill that needs a file from outside its folder resolves its own path with `cd -P` and `pwd -P`, since that path is a symlink (`visuals/scripts/check-image.py` is shared this way). A skill with no relatives, like `todo`, sits directly in `skills/`.

`SKILL.md` frontmatter needs `name` (matches the folder, kebab-case) and `description`. Write the description as the trigger: what the skill does, then the phrases or situations that should fire it, one phrase per distinct case. Add `disable-model-invocation: true` for a skill that should run only when typed by name. Leave `allowed-tools` out: the setup runs in auto mode, where it would only skip the classifier. Leave `model` unset so the skill runs on the session's model.

## Settings

Change settings in `claude/settings.json` (or the private overlay), then run `scripts/update.sh`. Never edit `~/.claude/settings.json` directly: it is generated, and `update.sh` stops with a diff when the live file has drifted from what it last wrote. When that happens, move the change into the repo, then re-run. Write paths as `$HOME/...`, never `/Users/...`.

## Before finishing a change

1. Keep the skill table in `README.md` listing exactly the skills in `skills/`.
2. Run `scripts/check.sh`; CI runs the same script.
3. Run `scripts/update.sh` so `~/.claude` matches.

To take a skill from another repo, or drop one, edit `external-skills.txt`; plugins are listed in the README.
