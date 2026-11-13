# Removed

Things taken out of this repo that may come back. Each one is still in git at commit `cb72212`; the command under it brings the files back. After a restore, do the steps listed with it, then run `scripts/check.sh` and `scripts/update.sh`.

## visual-check skill

Took screenshots of web pages at phone and desktop width, in light and dark mode, with the local Chrome over the DevTools protocol, and listed content wider than the screen and console errors. Removed because it did not earn its place.

```bash
git checkout cb72212 -- skills/visuals/visual-check
```

- Add its row to the Visuals table in `README.md`.
- Optional: the rule in `claude/CLAUDE.md` that made it run after every UI change (see `git show cb72212 -- claude/CLAUDE.md`).

## verify skill and its Stop hook

`stop-hook.py` ran a project's `.claude/verify` script when Claude was about to finish and the code had changed, and sent a failure back so Claude kept working. `/verify` wrote that script for a project. This repo's own `.claude/verify` ran `scripts/check.sh`. Removed because the global rule "run the typecheck and tests after a change" already covers it.

```bash
git checkout cb72212 -- skills/dev/verify .claude/verify
```

- Add its row to the Dev table in `README.md`.
- Add the hook to the `Stop` list in `claude/settings.json`: `python3 $HOME/.claude/skills/verify/stop-hook.py`.

## diagrams: page.sh

Wrapped rendered diagrams (SVG or PNG) into one self-contained HTML page with light and dark theme, each diagram inlined as a data URI. Removed because PNG and SVG are the normal delivery, and the `explain` skill already builds pages with diagrams.

```bash
git checkout cb72212 -- skills/visuals/diagrams/scripts/page.sh
```

- Add the "Web page or Artifact" bullet back under Delivery in `skills/visuals/diagrams/SKILL.md` (see `git show cb72212:skills/visuals/diagrams/SKILL.md`).
