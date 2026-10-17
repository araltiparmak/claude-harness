# Deck guide

Read this before writing a deck spec for `scripts/slides.mjs`. It covers the story, the words, and the spec format. The script owns layout, charts, and export, so the work here is content.

## The reader

Decks go to the whole company: leadership, other teams, people far from the work. Write for a busy reader who gives each slide about 10 seconds and reads only the title unless something stops them. Every slide therefore carries its whole message in the title, and the body is evidence for that title. When a slide's title is true, specific, and contains a number, the deck works even if nobody reads the body.

**Plain words.** Someone from Sales or Finance must understand every slide without asking. Say "yearly revenue", not ARR; "major outages", not Sev-1; "full-time roles", not FTE. Name the customer effect before the system that caused it. The lint flags common acronyms; allow one with `"allowTerms": ["ARR"]` only when this audience uses it daily.

**Premium means restraint.** The generator supplies the look (generous space, one type family, a strong, saturated palette, aligned grids). Keep it premium with the content: one message per slide, short lines, no filler bullets, no exclamation marks, no emoji.

## Story

1. **Answer first.** Slide 2 is the summary: the result, three supporting numbers, and the decision you need. Everything after it is backup, in the order the summary raised it.
2. **Outcomes before activity.** Lead with what changed for customers, revenue, cost, or risk. Engineering metrics (lead time, deploys, latency) appear as the cause of a business result, never as the headline on their own.
3. **Close on what happens next.** The last content slide names next steps and, when there is one, the decision, its cost and its owner. For a company update the `asks` can be what other teams can do ("try the new pipeline", "send us your slowest page").
4. **6 to 10 slides** for a review; 3 to 5 for a team update. One message per slide. Merge two slides that argue the same point; move detail to an appendix deck.

Default deck shape: `title`, `summary`, 3 to 6 evidence slides, `next`.

## Titles

- **Action title, not topic.** "Three changes cut monthly spend by $148K", never "Infrastructure costs".
- **One number in the title.** The lint warns when a data slide's title has no digit. Write numerals ("4 of 6"), not words ("four of six").
- **Under ~90 characters, at most two lines.** The layout check fails a title that wraps to three lines.
- **The subtitle names the measure and period** ("Orders per month, thousands"). It is the chart's axis label in plain words.

## Numbers

- **Every number has a comparison**: a baseline (Q2, last year), a target, or a peer. "9 min" alone means nothing; "9 min, down 79% vs Q2, target 15" is a result.
- **Translate to money or time where you honestly can.** Show the method in a footnote: "11% uplift × checkout revenue, annualised". Label estimates ("est.", a range like ±$0.4M).
- **Round for the room.** $2.1M, not $2,084,316. Keep precision only where the decimal is the point (99.97%).
- **Percent vs points.** A rate that moves from 99.81% to 99.97% rose 0.16 pt, not 0.16%.
- **Same number, same value everywhere.** If the summary says −38%, the KPI slide says −38%.
- **Never invent numbers.** When the user has no figure, leave a visible placeholder (`"value": "TBD"`) and list what is missing. Sample decks say "Sample data" in the footer.
- **Name the source and period** in `source` (deck-wide or per slide). The lint warns without it.

## Team successes

- Credit the team by name on `wins` slides and in the `team` field, not a person-by-person list.
- Each win is one metric plus one plain sentence of what shipped. "+11%: One-tap pay with saved cards", not a feature description.
- Pick wins the business can measure. A refactor with no outcome belongs in an engineering review, not here.

## Choosing a slide type

| The message is | Type |
|---|---|
| The whole story in 30 seconds | `summary` |
| One number changed everything | `hero` (optional trend chart) |
| Several metrics against targets | `kpis` (2 to 4 tiles) or `scorecard` (up to 7 rows with status) |
| Something grew or fell over time, with a cause | `trend` with `markers` |
| Before vs after across metrics | `compare` |
| How we got from X to Y | `waterfall` |
| One group stands out from the rest | `bars` with `highlight` |
| How a tech change reaches the P&L | `impact` (3 steps) |
| Team results | `wins` (up to 6) |
| What happens next and what we need | `next` |

## Spec format

A deck is one JSON file. The script rejects unknown fields, missing required fields and numbers written as text, and names the fix. Top level:

```json
{
  "title": "Q3 2026 Platform Review",
  "footer": "Org · Team · Confidential",
  "source": "Finance dashboard and Datadog, Q3 2026",
  "output": "pdf,png,html",
  "theme": { "startHue": "green" },
  "slides": [ ... ]
}
```

Every non-title slide takes `title`, optional `subtitle`, optional `source` (overrides the deck's). Text fields accept `**bold**`. Per type:

| Type | Fields |
|---|---|
| `title` | `org`, `title`, `subtitle`, `meta` |
| `summary` | `points[] {value, label, detail}`, `ask {label, text, meta}` |
| `hero` | `value`, `label`, `before`, `after`, `beforeLabel`, `afterLabel`, `notes[]`, `trend {title, labels[], values[], format, zero, markers[], target}` |
| `kpis` | `items[] {label, now, before, format, better, change, vs, target, spark[]}`, `sparkLabel`, `takeaway`. With numeric `now` and `before` the script writes the value and the change; `value` and `delta` (text) override it |
| `trend` | `labels[]`, `series[] {name, values[]}` (first is the focus, second is grey context), `format`, `zero`, `markers[] {at, label}`, `target {value, label}`, `side[] {value, label}` |
| `bars` | `items[] {label, value, highlight, display}`, `format`, `side[]` |
| `compare` | `beforeLabel`, `afterLabel`, `rows[] {label, note, before, after, format, better: "higher"\|"lower", change: "percent"\|"points"\|"diff"}` (rates default to points, so 38% to 61% shows +23 pt) |
| `waterfall` | `start {label, value}`, `steps[] {label, value}`, `end {label}`, `format`, `better`, `axisFrom`, `side[]` (set `axisFrom` when the steps are small next to the totals; the chart prints "Axis starts at ...") |
| `scorecard` | `periods [prev, now]`, `rows[] {metric, note, before, now, target, format, better, status, statusLabel, spark[]}`. With numeric `now` and `target`, status is computed: target met is on track, missed but improving is at risk, otherwise off track |
| `impact` | `steps[3] {label, value, detail}`, `footnote` |
| `wins` | `items[] {metric, win, team}` |
| `next` | `priorities[] {title, detail, when}`, `asks[] {text, owner}`, `asksLabel` |

`format` is `{prefix, suffix, decimals}`, for example `{"prefix": "$", "suffix": "K"}`. `delta` is display text ("−79%"); `good: false` turns it red. `display` overrides a bar's value label.

## Color

The default `preset` is `bold`: six saturated hues (blue, green, orange, violet, amber, red), each with four steps.

| Step | Used for |
|---|---|
| `bg` | card and tile wash: KPI tiles, summary rows, wins, impact steps, side callouts, pills |
| `tint` | solid decoration (title slide shapes) |
| `mark` | chart lines, bars, sparklines, status icons; strong enough to read on white |
| `ink` | text on that hue's wash: big numbers, labels |

How color is assigned, so it stays meaningful:

- **Cards rotate hues** in palette order (tile 1 blue, tile 2 green, ...). The rotation is decoration, so never write "the green tile" in speaker notes.
- **Charts keep one color per meaning.** The focus series uses the first hue's `mark` on its `bg` wash; comparison data is grey. Never color bars by row just to add color.
- **Semantic hues are fixed by name:** green means good or on track, red means bad or off track, amber means at risk, violet is the start total and the ask panel. A custom palette keeps those names for those roles.
- **Deltas stay green or red text**, with an arrow, on any wash.

`theme` options:

- `"startHue": "green"` rotates the palette so the deck leads with that hue (charts, first tile, title rule).
- `"palette": [{ "name", "bg", "tint", "mark", "ink" }, ...]` replaces the hues with a brand set. Check each `ink` reads on its `bg` and each `mark` reads on white.
- `"preset": "classic"` switches to the restrained single-accent look (neutral panels, one `accent` color) for audiences that want it plain.
- `font` swaps the typeface; `accent` sets the chart color in `classic`.

## Build and check

```bash
node scripts/slides.mjs deck.json [out-dir]
```

It writes the formats from `--format` or the spec's `output` (default: all): `deck.pdf`, `slide-NN.png` (2x, 2560x1440) and `deck.html`, a presenter (arrow keys, F for fullscreen, `#3` in the URL opens slide 3). It prints these findings:

- **SPEC** (exit code 2): the spec is invalid; nothing was built.
- **content**: the rules above that a script can check: a title without a number, a title number that nothing on the slide shows or computes, length, source, item limits, jargon.
- **layout**: a slide body that is mostly empty.
- **LAYOUT**: text clipped or outside the slide, or a title on 3+ lines. Exit code 3. Shorten the text; never shrink fonts in the spec.

Then read every PNG. Lint clean is necessary, not sufficient: look for a slide whose body does not prove its title, empty space, and numbers that disagree between slides.
