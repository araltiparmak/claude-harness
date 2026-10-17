---
name: markmap
description: Turns a Markdown outline into an interactive mind map (self-contained HTML) and a PNG with markmap. Use when the user asks for a mind map, markmap, a topic tree, a study or learning map, or a visual summary of notes or a Markdown document. Flows, sequences and architecture belong to the diagrams skill.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Bash(*/markmap/scripts/render.sh *)
  - Bash(command -v *)
  - Bash(ls *)
  - Bash(mkdir *)
---

# Markmap

A mind map is a tree. Write the tree as a Markdown outline, render it with `scripts/render.sh`, look at the PNG, fix, repeat. The `.md` source is the deliverable alongside the image: it stays editable and diffable.

## When to use it

Use markmap when the content is a hierarchy: topics and subtopics, a curriculum, a summary of a long document. Do not use it when the content has arrows, order or cycles. That is a `diagrams` job (Mermaid, D2, Graphviz).

## Steps

1. Check Node and Chrome exist (`command -v node`). `markmap-cli` runs through `npx` with no install. Chrome or Edge is needed for the PNG only.
2. Write the outline to `markmap-out/<name>.md` in the project, or the scratchpad when the user wants a throwaway.
3. Run `scripts/render.sh <source.md> [out-dir]`. It writes `<name>.html` (interactive, works offline) and `<name>.png`.
4. Read the PNG. Done means: every label legible, the branches balanced, nothing clipped. Fix and re-render until that holds. `render.sh` also checks the PNG and prints `ok`, `WARN` or `FAIL` (blank image, aspect ratio).
5. Report the paths of the HTML, the PNG and the source.

## Writing the outline

- One `#` root. `##` gives the main branches, then nested `-` lists. Aim for 3 to 7 branches and at most 4 levels.
- Keep each node to a few words. Put the detail in the list below it, not in a long sentence.
- Inline Markdown works in a node: `**bold**`, `` `code` ``, `[links](url)`, and `$math$`.
- Front matter sets the look. Always set `initialExpandLevel: -1`, or deep nodes stay collapsed in the PNG:

```
---
title: Name
markmap:
  colorFreezeLevel: 2
  initialExpandLevel: -1
---
```

- `colorFreezeLevel: 2` gives each main branch one colour for its whole subtree.

## Environment

- `render.sh` finds Chrome, Edge or Chromium itself. Set `CHROME=/path` to override. Set `MARKMAP_SIZE=2400x1500` for a big map (default `1600x1000`).
- The PNG is taken from a copy with `duration: 0`: markmap animates the first draw for 500 ms, and headless Chrome often saved the frame before the map appeared (blank PNG). The HTML keeps its own settings and still animates. Do not set `duration` in the outline expecting it to reach the PNG, and do not add `--force-device-scale-factor` to the screenshot: with it Chrome saves a blank image. The PNG is therefore 1x. For a sharper image, raise `MARKMAP_SIZE`.
- The PNG is forced to the light theme. The HTML follows the viewer's system theme.
- To hand over only the interactive map, send the `.html`. It has no external files.

## Examples

`examples/learning-plan.md`: a three-branch plan with front matter.
