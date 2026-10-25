---
name: deck
description: Builds presentation decks as PNG slides, a presentable HTML page or PDF from a JSON spec: team successes, quarterly results, KPIs, cost savings, before/after, roadmap and next steps, written for a company-wide audience, in a data style or a bold style (one message per slide on a bright solid colour). Use when the user wants a presentation, slides or a deck (all-hands, company update, leadership review, team showcase), a bold, simple or colourful deck, or a single slide or visual that shows results and numbers.
---

# Decks

You write the content as a JSON spec; `scripts/slides.mjs` owns layout, charts, color, numbers formatting and export. Never hand-build slide HTML.

## Rules

1. Every number comes from the user or their data, never a guess. A missing number is `TBD` in text fields; a `kpis` tile or `compare` row whose number is missing is left out. Both go on the TBD list.
2. Every slide title is the result in one sentence, with a number: "Checkout is 3× faster", not "Checkout".
3. Put numbers in as numbers and let the script do the math and the formatting: `"now": 2.1, "before": 8.2, "target": 3, "format": { "suffix": "s" }, "better": "lower"` (kpis), `"before": 2.3, "after": 0.9` (compare). The script writes the change and its colour; percent values change in points, and `"change": "diff"` fits scores like 4.3 to 4.7.
4. Plain words for a company-wide reader: "yearly revenue", not ARR.
5. Leave out an optional field you have nothing for (a `detail`, `org`, `meta`, `note`); `TBD` is only for a number or fact the slide needs. When the user names no source, use their team as `source` and put it on the TBD list for them to confirm.
6. Start from `examples/deck-q3-review.json`: copy the slides you need and change the values.
7. Fix every `SPEC` and `LAYOUT` line the script prints, then build again. Shorten text; never shrink fonts.

## Output type

PNG is the default. Pass another `--format` only when the user's words ask for it.

| The user says | Flag | They get |
|---|---|---|
| nothing, "PNG", "images", "Slack", "paste in a doc" | (none) | `slide-01.png`, ... (2560×1440) |
| "HTML", "web page", "present", "in the browser", "share a link", "Artifact" | `--format html` | the PNGs and `deck.html`: one file; arrow keys move, F is fullscreen. Publish `deck.html` as built when an Artifact is asked for |
| "PDF" | `--format pdf` | the PNGs and `deck.pdf` |

The script writes the PNGs in every build, because step 6 checks them.

## Steps

1. **Collect the numbers.** List every gap as `TBD`.
2. **Outline as titles.** One action title per slide: `title`, `summary`, evidence slides, `next`. A bold deck is `statement` slides only. When the user gave data but no story, show the outline and wait for agreement.
3. **Write the spec** to `decks/<name>.json` in the project, or the scratchpad for a throwaway.
4. **Build:** `node scripts/slides.mjs <deck.json> [out-dir] [--format html|pdf]`.
5. **Fix findings** (rule 7) until the script prints `lint: clean`.
6. **Read `contact.png`**, every slide on one sheet, on the first clean build. Read a single `slide-NN.png` only to look closer at one slide, and after a later fix only the slides that changed. Never read `deck.html`: the PNGs are the same slides. Done means: each slide's body proves its title, someone outside the team could read every slide, and the same number has the same value on every slide.
7. **Report** the output paths and the `TBD` list.

Read [`references/deck-guide.md`](references/deck-guide.md) when choosing slide types, writing for the audience, or using a field the examples do not show. It holds every field of the seven slide types.

## Examples

All numbers are sample data.

`examples/deck-q3-review.json` is a 6-slide review in the data style that uses every slide type once: `title`, `summary`, `kpis`, `trend`, `compare`, `next`.

`examples/deck-bold.json` is the same story as a 5-slide bold deck: `statement` slides with and without a number.

## Setup

Needs Node and Chrome or Edge. For the Inter typeface run `brew install --cask font-inter` once; without it the script falls back to the system font and says so.
