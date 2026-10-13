# Harness

Skills and plugins that live outside this repo but are part of my Claude Code setup. Run these on a fresh machine, after `scripts/update.sh`, to rebuild it. Matt Pocock's skills come from `update.sh`, so leave his `mattpocock-skills` plugin uninstalled: having both loads every skill twice.

## Plugins

```bash
claude plugin install superpowers@claude-plugins-official
claude plugin install frontend-design@claude-plugins-official
claude plugin install expo@claude-plugins-official
claude plugin install vercel@claude-plugins-official
claude plugin install serena@claude-plugins-official
claude plugin install ralph-loop@claude-plugins-official
claude plugin install clangd-lsp@claude-plugins-official
```

## Skills (skills.sh)

```bash
npx skills add AminBlg/SimpleEnglish
npx skills add yetone/kill-ai-slop
npx skills add vercel-labs/skills --skill=find-skills
```

## Adding an entry

Install it, confirm it works, then add the exact command to the matching section.
