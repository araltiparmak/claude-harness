# Deck guide

Read this before writing a deck spec for `scripts/slides.mjs`. The script owns layout, charts, colour and export, so the work here is content.

## The reader

Decks go to the whole company: leadership, other teams, people far from the work. Each slide gets about 10 seconds, and most readers read only the title. So every slide carries its whole message in the title, and the body is evidence for it.

- **Plain words.** Someone from Sales or Finance must understand every slide without asking: "yearly revenue", not ARR; "major outages", not Sev-1. Name the customer effect before the system that caused it.
- **Restraint.** One message per slide, short lines, no filler bullets, no exclamation marks, no emoji.

## Story

1. **Answer first.** Slide 2 is the `summary`: the result, three supporting numbers, and the decision you need. Everything after it is backup, in the order the summary raised it.
2. **Outcomes before activity.** Lead with what changed for customers, revenue, cost or risk. Engineering metrics appear as the cause of a business result, never as the headline on their own.
3. **Close on what happens next.** The last slide is `next`: priorities and, when there is one, the decision, its cost and its owner.
4. **6 to 10 slides** for a review, 3 to 5 for a team update: `title`, `summary`, evidence slides, `next`.

## Titles and numbers

- **Action title, not topic**, with one number: "Three changes cut monthly spend by $148K", never "Infrastructure costs". Write numerals ("4 of 6").
- **Under ~90 characters.** The layout check fails a title that wraps to three lines.
- **The subtitle names the measure and period** ("Orders per month, thousands").
- **Every number has a comparison**: a baseline, a target or a peer. Translate to money or time where you honestly can, and label estimates.
- **Round for the room**: $2.1M, not $2,084,316. A rate that moves from 99.81% to 99.97% rose 0.16 pt, not 0.16%.
- **Same number, same value on every slide**, and name the source and period in `source`.

## Slide types

| The message is | Type |
|---|---|
| The whole story in 30 seconds | `summary` |
| Two to four metrics, each with its change and target | `kpis` |
| Something grew or fell over time, with a cause | `trend` with `markers` |
| Before vs after across metrics | `compare` |
| What happens next and what we need | `next` |

## Spec format

A deck is one JSON file. The script rejects unknown fields, missing required fields and numbers written as text, and names the fix.

```json
{
  "title": "Q3 2026 Platform Review",
  "footer": "Org · Team · Confidential",
  "source": "Finance dashboard and Datadog, Q3 2026",
  "slides": [ ... ]
}
```

Every slide except `title` takes `title`, optional `subtitle` and optional `source` (overrides the deck's). Text fields accept `**bold**`.

| Type | Fields |
|---|---|
| `title` | `org`, `title`, `subtitle`, `meta` |
| `summary` | `points[] {value, label, detail}` (up to 4), `ask {label, text, meta}` |
| `kpis` | `items[] {label, now, before, target, format, better, change, vs, spark[]}` (2 to 4), `sparkLabel`, `takeaway` |
| `trend` | `labels[]`, `series[] {name, values[], display}` (the first is the focus, the second grey context), `format`, `zero`, `markers[] {at, label}`, `target {value, label}` |
| `compare` | `beforeLabel`, `afterLabel`, `rows[] {label, note, before, after, format, better, change}` (up to 5) |
| `next` | `priorities[] {title, detail, when}`, `asks[] {text, owner}`, `asksLabel` |

- `format` is `{prefix, suffix, decimals}`, for example `{"prefix": "$", "suffix": "K"}`.
- `better` is `"higher"` (default) or `"lower"`; it decides whether a change shows green or red.
- `change` is `"percent"`, `"points"` or `"diff"`. A value with suffix `%` defaults to points, so 38% to 61% shows +23 pt.

Colour is fixed: cards rotate through the palette, green means good, red means bad, and violet marks the decision.

## Script output

- **SPEC** (exit code 2): the spec is invalid; nothing was built.
- **LAYOUT** (exit code 3): text clipped or outside the slide, or a title on 3+ lines.
- **layout**: a slide body that is mostly empty; add content or pick another type.

In the HTML presenter, `#3` in the URL opens slide 3.
