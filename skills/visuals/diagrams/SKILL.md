---
name: diagrams
description: Draws technical diagrams as SVG and PNG with Mermaid and D2 (architecture, sequence, ER, state, flow, gantt), optionally in a hand-drawn whiteboard style, for PR descriptions, docs and knowledge sharing. Use when the user asks for a diagram, flowchart, architecture or sequence diagram, a data model picture, a whiteboard or Excalidraw-style sketch, or a diagram image to paste into a PR or doc. Slides and results visuals belong to the deck skill.
---

# Diagrams

Write a source file, render it with `scripts/render.sh`, look at the PNG, fix, repeat. The source file is the deliverable alongside the image: it stays editable and diffable.

## Pick the tool

| Job | Source | Tool | Read |
|---|---|---|---|
| Flow, sequence, ER, state, gantt | `.mmd` | Mermaid | `mermaid.md` |
| Architecture with nested groups (accounts, VPCs, services) | `.d2` | D2 | `d2.md` |
| AWS architecture with official service icons | `.d2` | D2 with `icon:` | `d2.md` |
| Whiteboard look (hand-drawn, like Excalidraw), for drafts and discussions | `.d2` | D2, rendered with `SKETCH=1` | `d2.md` |
| Services passing messages in a chain | `.d2` and `.mmd` | D2 route + Mermaid sequence | `d2.md` (Message chains), `mermaid.md` |
| Hover, click, filters, animation | `.html` | D3 or Mermaid from cdnjs | Interactive output below |

Read only the file for the tool you picked. A pure topic hierarchy (mind map, study map) belongs to the `mindmap` skill. **Sequence diagrams are always Mermaid. Architecture diagrams are always D2**, with icons when it is AWS. Default to Mermaid for a plain flow; reach for D2 when boxes must nest. **Flows run left to right**: Mermaid `flowchart LR`, D2 `direction: right`. A slide, KPI tile or results visual is a `deck` job, even when it is one slide.

## Steps

1. Check the tool exists (`command -v mmdc d2`). Chrome is needed for `.mmd` and `.html`. Missing tools: ask before `brew install d2`; Mermaid runs through `npx` with no install.
2. Write the source to `diagrams-out/<name>.<ext>` in the project, or the scratchpad when the user wants a throwaway.
3. Run `scripts/render.sh <source> [out-dir]`. It ends with the PNG's size and aspect; a `WIDE` line means fix the source and render again before reading anything.
4. Read the PNG, once per render. Done means: something is drawn (not a blank or half-loaded page), every label legible, nothing clipped or overlapping, the picture shows the mechanism the user asked for, aspect near 16:9 or square and never wider than 3:1 (4:1 for a gantt or timeline). Fix the diagram and render again until that holds.
5. Report the paths of the PNG and the source.

## Delivery

PNG is the default; the SVG beside it is for PRs and docs that zoom.

- Web page or Artifact: `scripts/page.sh <out.html> "<title>" <name.svg>[=<caption>] ...` wraps the rendered diagrams into one self-contained page that also meets the Artifact rules (light and dark theme, phone width). Hand over or publish that file as built. The PNGs you already read are its check: every diagram sits in the page as base64, so reading the page costs far more and shows nothing new.
- Pull requests: GitHub renders fenced `mermaid` blocks natively, but not D2. So:
  - D2 diagram (every AWS-icon architecture): attach the rendered SVG, which zooms without blur, plus a 2x PNG. `gh pr create|edit|comment --attach file.svg` uploads it (gh 2.99 or newer; it rewrites a `![alt](./file.svg)` reference in the body to the uploaded asset). Commit the `.d2` source, not only the image.
  - Sequence, flow, state, ER: a fenced `mermaid` block in the description. The source stays reviewable in the PR. GitHub draws it with its own theme, so the colours come from `classDef` in the source (`mermaid.md`, Colour).
  - Architecture that must render natively (no image): a Mermaid `flowchart` with `subgraph` groups. It has no service icons.

## Interactive output

Ship one self-contained `.html` with libraries from `cdnjs.cloudflare.com` at pinned versions. Open it in the browser to check it. The same page publishes as a Claude Artifact, which loads scripts from cdnjs; when the Artifact tool is available, `artifact-diagramming` holds the SVG mechanics.

## Environment

`render.sh` finds Chrome, Edge or Chromium itself; set `CHROME=/path` to override. On a locked-down machine with no installs, HTML plus Chrome is the path that always works: write Mermaid inside an HTML page that loads it from cdnjs, then render the `.html` to PNG.

## Examples

`examples/` holds a working source for each tool and diagram kind; start from the closest one.
