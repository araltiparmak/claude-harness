---
name: deck
description: Builds presentation decks as PDF, PNG slides or a presentable HTML file from a JSON spec: team successes, quarterly results, KPIs, cost savings, before/after, roadmap and next steps, written for a company-wide audience. Use when the user wants a presentation, slides or a deck (all-hands, company update, leadership review, team showcase), or a single slide or visual that shows results and numbers.
---

# Decks

You write the content as a JSON spec; `scripts/slides.mjs` owns layout, charts, color, numbers formatting and export. Never hand-build slide HTML.

## Rules

1. Every number comes from the user or their data, never a guess. A missing number is `TBD` in text fields; a `kpis` tile or `compare` row whose number is missing is left out. Both go on the TBD list.
2. Every slide title is the result in one sentence, with a number: "Checkout is 3× faster", not "Checkout".
3. Put numbers in as numbers and let the script do the math and the formatting: `"now": 2.1, "before": 8.2, "target": 3, "format": { "suffix": "s" }, "better": "lower"` (kpis), `"before": 2.3, "after": 0.9` (compare). The script writes the change and its colour; percent values change in points, and `"change": "diff"` fits scores like 4.3 to 4.7.
4. Plain words for a company-wide reader: "yearly revenue", not ARR.
5. Leave out an optional field you have nothing for (a `detail`, `org`, `meta`, `note`). Never fill it with placeholder text. `TBD` is only for a number or fact the slide needs, and it goes on the TBD list. When the user names no source, use their team as `source` and list it for them to confirm.
6. Start from `examples/deck-q3-review.json`: copy the slides you need and change the values.
7. Fix every `SPEC` and `LAYOUT` line the script prints, then build again. Shorten text; never shrink fonts.

## Output type

Pick the format from the user's words and pass `--format`. When they name none, build all three.

| The user says | Flag | They get |
|---|---|---|
| "PDF", "send it", "email", "attach" | `--format pdf` | `deck.pdf` |
| "PNG", "images", "Slack", "Confluence", "paste in a doc" | `--format png` | `slide-01.png`, ... (2560×1440) |
| "HTML", "present", "in the browser", "share a link" | `--format html` | `deck.html`: one file; arrow keys move, F is fullscreen |
| nothing | (none) | all of the above |

Several at once: `--format pdf,html`.

## Steps

1. **Collect the numbers.** List every gap as `TBD`.
2. **Outline as titles.** One action title per slide: `title`, `summary`, evidence slides, `next`. When the user gave data but no story, show the outline and wait for agreement.
3. **Write the spec** to `decks/<name>.json` in the project, or the scratchpad for a throwaway.
4. **Build:** `node scripts/slides.mjs <deck.json> [out-dir] --format <formats>`.
5. **Fix findings** (rule 7) until the script prints `lint: clean`.
6. **Read every PNG.** When the user did not ask for PNGs, add `png` to the build for this check anyway; the PNGs are for you, so report only the formats the user asked for. Done means: each slide's body proves its title, someone outside the team could read every slide, and the same number has the same value on every slide.
7. **Report** the output paths and the `TBD` list.

Read [`references/deck-guide.md`](references/deck-guide.md) when choosing slide types, writing for the audience, or using a field the examples do not show. It holds every field of the six slide types.

## Examples

All numbers are sample data.

`examples/deck-q3-review.json` is a 6-slide review that uses every slide type once: `title`, `summary`, `kpis`, `trend`, `compare`, `next`.

## Setup

Needs Node and Chrome or Edge. For the Inter typeface run `brew install --cask font-inter` once; without it the script falls back to the system font and says so.
