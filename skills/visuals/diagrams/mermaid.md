# Mermaid

Read when the diagram is `.mmd`: flow, sequence, ER, state, gantt.

- Keep step labels short; long self-message labels collide with the step badge.
- Sequence: `look: handDrawn` has no effect; the hand-drawn look is D2's (`SKETCH=1`, see `d2.md`).
- Sequence: `Note over A,B` text longer than the gap between the lifelines overflows or drifts toward one side; keep it under about 35 characters. Use `autonumber` when the order is the point.
- Flow: always left to right, `flowchart LR`. Label every arrow with what flows; draw the failure path (dashed `-.->`). Break long labels with `<br/>`.
- Flow longer than about 5 steps: one row gets wider than 3:1, so wrap it like lines of text. Split it into stages, one `subgraph` per stage with `direction LR`, and stack the stages with `flowchart TB` on the parent (`examples/long-flow.mmd`).
- Flow: a `direction` inside a `subgraph` is ignored as soon as one of its nodes links to a node outside. To keep an inner `LR` row, link subgraph to subgraph (`req -- publish --> async`, with the subgraph ids), and keep each failure path inside its stage.
- Colour: every flow box gets a fill by its kind (step, failure, result, external), through `classDef` and `class` (`examples/long-flow.mmd`), so the picture reads at a glance. Give each class a light fill, a darker stroke of the same hue, and a dark `color` for the text: GitHub draws Mermaid in its own light or dark theme, and in dark mode a light box with no `color` gets light text. Fill a `subgraph` with a see-through 8-digit hex (`style <id> fill:#94a3b81f,stroke:#94a3b8`) and no `color`: the theme's own edges and title then read on it in both modes, where an opaque light fill hides the light edges of dark mode. `rgba()` does not work in `style` or `classDef`, whose commas split the properties. In a sequence diagram, colour a group of participants with `box rgba(...)` or a phase with `rect rgba(...)` at about 0.15 alpha; an opaque light colour hides the theme's light text in dark mode.
- Architecture: `architecture-beta` ships only five generic icons (cloud, database, disk, internet, server), all in one blue, so Lambda and SQS look alike, and edges cross labels. AWS icons need `registerIconPacks()` in page JavaScript, which GitHub does not run for you. Use D2 for AWS architecture; use a `flowchart` with `subgraph` groups when it must render natively.
- Gantt: add `todayMarker off` unless the date matters; the marker cuts through the title.
