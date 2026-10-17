# Mermaid

Read when the diagram is `.mmd`: flow, sequence, ER, state, gantt.

- Keep step labels short; long self-message labels collide with the step badge.
- Sequence: `Note over A,B` text longer than the gap between the lifelines overflows or drifts toward one side; keep it under about 35 characters. Use `autonumber` when the order is the point.
- Flow: label every arrow with what flows; draw the failure path (dashed `-.->`). Prefer `TD`; in `LR` keep to about 4 ranks and break labels with `<br/>`.
- Flow: a `direction` inside a `subgraph` is ignored as soon as one of its nodes links to a node outside. To keep an inner `LR` row, link subgraph to subgraph (`req -- publish --> async`, with the subgraph ids).
- Architecture: `architecture-beta` ships only five generic icons (cloud, database, disk, internet, server), all in one blue, so Lambda and SQS look alike, and edges cross labels. AWS icons need `registerIconPacks()` in page JavaScript, which GitHub does not run for you. Use D2 for AWS architecture; use a `flowchart` with `subgraph` groups when it must render natively.
- Colours: `classDef` and `linkStyle N` accept `var(--x)`, so one SVG can follow a site's themes.
- Gantt: add `todayMarker off` unless the date matters; the marker cuts through the title.
