---
name: diagrams
description: Draws technical diagrams as SVG and PNG with Mermaid, D2 and Graphviz (architecture, sequence, ER, state, flow, gantt) for PR descriptions, docs and knowledge sharing. Use when the user asks for a diagram, flowchart, architecture or sequence diagram, a data model picture, or a diagram image to paste into a PR or doc. Slides and results visuals belong to the deck skill.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Bash(*/diagrams/scripts/render.sh *)
  - Bash(command -v *)
  - Bash(ls *)
  - Bash(mkdir *)
---

# Diagrams

Write a source file, render it with `scripts/render.sh`, look at the PNG, fix, repeat. The source file is the deliverable alongside the image: it stays editable and diffable.

## Pick the tool

| Job | Source | Tool |
|---|---|---|
| Flow, sequence, ER, state, gantt | `.mmd` | Mermaid |
| Architecture with nested groups (accounts, VPCs, services) | `.d2` | D2 (TALA layout, set per run with `D2_LAYOUT=elk\|dagre`) |
| Cycles, dependency graphs, anything dense | `.dot` | Graphviz |
| Hover, click, filters, animation | `.html` | D3 or Mermaid from cdnjs, delivered as the HTML itself |

Default to Mermaid for a plain flow. Reach for D2 when boxes must nest. A slide, KPI tile or results visual is a `deck` job, even when it is one slide.

## Steps

1. Check the tool exists (`command -v mmdc d2 dot`). Chrome is needed for `.mmd` and `.html`. Missing tools: ask before `brew install d2 graphviz`; Mermaid runs through `npx` with no install.
2. Write the source to `diagrams-out/<name>.<ext>` in the project, or the scratchpad when the user wants a throwaway.
3. Run `scripts/render.sh <source> [out-dir]`.
4. Read the PNG. Done means: every label legible, nothing clipped or overlapping, the picture shows the mechanism the user asked for. Fix and re-render until that holds.
5. Report the paths of the PNG and the source.

## Quality checks

- D2: nested `direction` works only under TALA. ELK stacks everything and goes very tall or wide. Aim for an aspect ratio near 16:9 or square, never wider than 3:1.
- D2: define `classes` (one fill per component type) instead of per-node styles.
- Mermaid: keep step labels short; long self-message labels collide with the step badge.
- Mermaid gantt: add `todayMarker off` unless the date matters; the marker cuts through the title.
- Pull requests: attach the SVG (zooms without blur) and a 2x PNG; GitHub also renders fenced `mermaid` blocks natively.

## Interactive output

Ship one self-contained `.html` with libraries from `cdnjs.cloudflare.com` at pinned versions. Open it in the browser to check it. When the Artifact tool is available, `artifact-diagramming` holds the SVG mechanics.

## Environment

`render.sh` finds Chrome, Edge or Chromium itself; set `CHROME=/path` to override. On a locked-down machine with no installs, HTML plus Chrome is the path that always works: write Mermaid inside an HTML page that loads it from cdnjs, then render the `.html` to PNG.

## Examples

`examples/`: `order-system.d2` (architecture with classes), `pr-sequence.mmd` (sequence with a PR callout), `order-states.mmd`, `orders-er.mmd`, `roadmap.mmd`, `flow.mmd`, `g.dot`.
