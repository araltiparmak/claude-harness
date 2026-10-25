# Deck guide

The detail behind the rules in `SKILL.md`: the reader, the story, every slide type and field. The script owns layout, charts, colour and export, so the work here is content.

## The reader

Decks go to the whole company: leadership, other teams, people far from the work. Each slide gets about 10 seconds, and most readers read only the title. So every slide carries its whole message in the title, and the body is evidence for it.

- **Plain words.** Someone from Sales or Finance must understand every slide without asking: "major outages", not Sev-1. Name the customer effect before the system that caused it.
- **Restraint.** One message per slide, short lines, no filler bullets, no exclamation marks, no emoji.

## Story

1. **Answer first.** Slide 2 is the `summary`: the result, three supporting numbers, and the decision you need. Everything after it is backup, in the order the summary raised it.
2. **Outcomes before activity.** Lead with what changed for customers, revenue, cost or risk. Engineering metrics appear as the cause of a business result, never as the headline on their own.
3. **Close on what happens next.** The last slide is `next`: priorities and, when there is one, the decision, its cost and its owner.
4. **6 to 10 slides** for a review, 3 to 5 for a team update: `title`, `summary`, evidence slides, `next`.

## Titles and numbers

- **Write numerals** in titles: "4 of 6", "3 changes cut monthly spend by $148K".
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
| One message, or one number, that should land hard: an opener, a section break, a headline result | `statement` |

## Bold style

A bold deck is built from `statement` slides only: one short sentence on a bright solid colour, and a big number when the slide has one. It suits an all-hands or a team showcase, where the room should remember three results rather than read a chart.

- **A number only when the user gave it.** A statement without a number is complete; it never carries `TBD`.
- **The number speaks, the title explains.** With a number, the title says what it changed for the business and need not repeat it ("Faster checkout turned into revenue" under $2.1M). The `label` says what the number counts.
- **Short.** About 60 characters for a title alone, 50 beside a number; `subtitle` is one line.
- **Colour.** Slides take blue, orange, green, violet, yellow and pink in turn, never the same colour twice in a row. Set `color` only when the colour carries meaning, such as `green` for a result that saved money.

The data style and the bold style mix: a `statement` slide works as an opener or a section break before `kpis` or `trend`.

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
| `statement` | `title`, `subtitle`, `number`, `format`, `label` (needs `number`), `color` (`blue`, `orange`, `green`, `violet`, `yellow`, `pink`) |

- `format` is `{prefix, suffix, decimals}`, for example `{"prefix": "$", "suffix": "K"}`.
- `better` is `"higher"` (default) or `"lower"`; it decides whether a change shows green or red.
- `change` is `"percent"`, `"points"` or `"diff"`. A value with suffix `%` defaults to points, so 38% to 61% shows +23 pt.

Colour is fixed: cards rotate through the palette, green means good, red means bad, and violet marks the decision. `statement` slides use their own bright colours (Bold style).

## Script output

- **SPEC** (exit code 2): the spec is invalid; nothing was built.
- **LAYOUT** (exit code 3): text clipped or outside the slide, or a title on 3+ lines.
- **layout**: a slide body that is mostly empty; add content or pick another type.

In the HTML presenter, `#3` in the URL opens slide 3.
