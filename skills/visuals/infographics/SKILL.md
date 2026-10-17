---
name: infographics
description: Builds single-canvas infographics (process steps, stat strip, timeline, funnel) as PNG, PDF and standalone HTML from HTML templates, and checks the render for overflow, overlap, small text, low contrast and leftover sample data. Use when the user asks for an infographic, a process or timeline graphic, a results strip, a funnel, or a visual for a company presentation or one-pager. Technical diagrams belong to the diagrams skill, full decks to the deck skill.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Bash(*/infographics/scripts/render.sh *)
  - Bash(cp *)
  - Bash(ls *)
  - Bash(mkdir *)
---

# Infographics

A template is an HTML file on a 1280x720 canvas. Copy it, replace the content, render with `scripts/render.sh`, read the checks and the PNG, fix, repeat. The HTML source is the deliverable next to the images: it stays editable and diffable.

Colours, type and spacing are CSS variables in `templates/tokens.css`, with `.h-blue`, `.h-green` and so on as colour helpers. Icons are the Lucide files in `icons/lucide/`. Add a colour or an icon when a visual needs one.

## Pick the template

| The message is | Template | Fits |
|---|---|---|
| How something works, in order | `templates/process.html` | 3 to 5 steps |
| Two to four headline results | `templates/stats.html` | 3 cards (4 at most) |
| What happened and what is next, by date | `templates/timeline.html` | 4 to 6 milestones |
| Where we lose people, stage by stage | `templates/funnel.html` | 3 to 6 stages |

Series over time, bars, waterfall, KPI scorecards: `deck` has those. Boxes and arrows between systems: `diagrams`. A tree of topics: `markmap`. No template fits: say so, and build a new one from `templates/base.css` (see the end).

## Steps

1. Copy the template to `infographics-out/<name>.html` in the project, or to the scratchpad for a throwaway.
2. Replace everything: title, lede, labels, numbers and the source line. The templates hold sample data and the render fails while any is left (the footer reads "Sample data").
3. Run `scripts/render.sh infographics-out/<name>.html`. It prints `ok`, `WARN` and `FAIL` lines and exits 1 on a `FAIL`.
4. Fix every `FAIL`. Read every `WARN`. Re-render.
5. Open the PNG and run the review below. The checks cannot see meaning.
6. Report the PDF, PNG and HTML paths.

## Writing the content

- The title is the claim, as a sentence a reader can repeat: "Q3 cut cost and latency while traffic grew", not "Q3 results". The lede names the scope or the period.
- Every number is checked: a percentage, a total or a difference you show must follow from the numbers beside it. Recompute before you render.
- A visual encoding must be honest. Funnel bar width is value divided by the first stage, never smoothed. Do not shorten an axis or round up to look better.
- Text is short: a label is one to four words, a detail line is one sentence. Under 120 words on the canvas.
- Icons: write `<!--icon:name-->` and the build inlines it. Names are the files in `icons/lucide/` (licence in `icons/lucide/LICENSE`). No match: no icon.
- Results visuals carry a source line with the period.

## What the render checks

Content inside the 1280x720 canvas, no clipped or overlapping text, text at least 13px, contrast 4.5:1 (3:1 at 24px and up), no leftover placeholders (`TODO`, `lorem`, `TBD`, `XXX`, `{{ }}`, "sample data"), a non-blank PNG. It warns when Inter is missing or the canvas holds more than 120 words.

## Review the PNG yourself

The checks pass a visual that is clean and wrong. Open the PNG and answer:

1. Say the message in one sentence. Does the picture show it within five seconds?
2. Is there one clear first thing to read, then a second?
3. Are the numbers and arithmetic right, and the source and period present?
4. Does it still work in greyscale?
5. Is anything decorative that carries no meaning? Remove it.

For a web-style result run the `kill-ai-slop` skill as the last pass.

## Outputs

- `.pdf`: vector, one 1280x720 page. This is the sharp output for slides and print.
- `.png`: 1280x720, a review copy.
- `.html`: standalone, with tokens and icons inlined. It opens in any browser.

## Building a new template

Start from an existing one. Keep the `<!--base-->` marker in `<head>`, the `<!--checks-->` marker before `</body>`, and one `<div class="canvas">` with `header`, `main` and `footer`. Use the `var(--...)` variables and the `.h-<hue>` classes for colour and spacing where they fit. Add the layout CSS in a `<style>` block after the marker, and put a "Sample data" footer in it so the render fails until real content is in.

## Environment

Needs Python 3, and Chrome, Edge or Chromium (set `CHROME=/path` to override). Inter comes from `brew install --cask font-inter`. No network and no npm install.
