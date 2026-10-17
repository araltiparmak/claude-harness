# Harness

Skills and plugins that live outside this repo but are part of my Claude Code setup. Run these on a fresh machine, after `scripts/update.sh`, to rebuild it. Leave Matt Pocock's `mattpocock-skills` plugin uninstalled: it would load the skills below twice.

## Plugins

```bash
claude plugin install frontend-design@claude-plugins-official
```

Project-scope plugins go in from that project's folder: `claude plugin install expo@claude-plugins-official --scope project` in `diction-app` and `diction-v2`.

## Skills (skills.sh)

Plugins from `claude-plugins-official` update themselves. skills.sh skills do not: `scripts/update.sh` runs `npx skills update` for them. Install with `-g` so the skill is recorded in `~/.agents/.skill-lock.json`; an untracked skill is never updated.

```bash
npx skills add mattpocock/skills -g -a claude-code -s ask-matt -s code-review -s codebase-design -s diagnosing-bugs -s domain-modeling -s grill-me -s grill-with-docs -s grilling -s handoff -s implement -s implement-spec -s improve-codebase-architecture -s pr -s prototype -s research -s retro -s setup-matt-pocock-skills -s tdd -s teach -s to-questionnaire -s to-spec -s to-tickets -s triage -s wait-what -s wayfinder -s wizard -s writing-for-agents -y
npx skills add AminBlg/SimpleEnglish -g -a claude-code -s '*' -y
npx skills add yetone/kill-ai-slop -g -a claude-code -s '*' -y
```

## Adding an entry

Install it, confirm it works, then add the exact command to the matching section.
