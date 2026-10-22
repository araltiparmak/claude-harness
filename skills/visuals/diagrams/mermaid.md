# Mermaid

Read when the diagram is `.mmd`: flow, sequence, ER, state, gantt.

- Keep step labels short; long self-message labels collide with the step badge.
- Sequence: `look: handDrawn` has no effect; the hand-drawn look is D2's (`SKETCH=1`, see `d2.md`).
- Sequence: `Note over A,B` text longer than the gap between the lifelines overflows or drifts toward one side; keep it under about 35 characters. Use `autonumber` when the order is the point.
- Flow: always left to right, `flowchart LR`. Label every arrow with what flows; draw the failure path (dashed `-.->`). Break long labels with `<br/>`.
- Flow longer than about 5 steps: one row gets wider than 3:1, so wrap it like lines of text. Split it into stages, one `subgraph` per stage with `direction LR`, and stack the stages with `flowchart TB` on the parent (`examples/long-flow.mmd`).
- Flow: a `direction` inside a `subgraph` is ignored as soon as one of its nodes links to a node outside. To keep an inner `LR` row, link subgraph to subgraph (`req -- publish --> async`, with the subgraph ids), and keep each failure path inside its stage.
- Architecture: `architecture-beta` ships only five generic icons (cloud, database, disk, internet, server), all in one blue, so Lambda and SQS look alike, and edges cross labels. AWS icons need `registerIconPacks()` in page JavaScript, which GitHub does not run for you. Use D2 for AWS architecture; use a `flowchart` with `subgraph` groups when it must render natively.
- Gantt: add `todayMarker off` unless the date matters; the marker cuts through the title.
