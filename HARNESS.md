# Harness

Skills and plugins that live outside this repo but are part of my Claude Code setup. Run these on a fresh machine, after `scripts/update.sh`, to rebuild it. Matt Pocock's skills come from `update.sh`, so leave his `mattpocock-skills` plugin uninstalled: having both loads every skill twice.

## Plugins

```bash
claude plugin install frontend-design@claude-plugins-official
claude plugin install expo@claude-plugins-official
```

## Skills (skills.sh)

Plugins from `claude-plugins-official` update themselves. skills.sh skills do not: `scripts/update.sh` runs `npx skills update` for them. Install with `-g` so the skill is recorded in `~/.agents/.skill-lock.json`; an untracked skill is never updated.

```bash
npx skills add AminBlg/SimpleEnglish -g -a claude-code -s '*' -y
npx skills add yetone/kill-ai-slop -g -a claude-code -s '*' -y
```

## Adding an entry

Install it, confirm it works, then add the exact command to the matching section.
