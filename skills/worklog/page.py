"""The HTML page of a report, from the data worklog.collect returns.

Page(data) is the page for you: the work with time and cost, then what the sessions say about how you use
Claude (tips, measures, the most expensive sessions, tokens, context, misc). Page(data, share=True) is the page
for other readers: the work, outcomes and time, with no costs and none of the Using Claude sections.
"""
import html
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from string import Template

from agentsview import session_url, ticket_url
from ledger import BIG_CONTEXT, IDLE, MODELS, SENT, cost, repo_of
from settings import settings

JIRA_URL = settings["jira_url"]
TEMPLATE = Path(__file__).resolve().parent / "report.html"
SMALL = 2.0  # USD; tickets that cost less share one box
MODEL_SLOTS = {m["name"]: m["colour"] for m in MODELS.values() if "colour" in m}  # from models.json; others grey
STATUS = {"merged": ("✓", "Merged"), "closed": ("✕", "Closed, not merged"), "open": ("○", "Open"),
          "draft": ("○", "Draft")}  # a pull request's status: its mark, then its words
REVIEW_ORDER = ["draft", "open", "closed", "merged"]  # code reviews: still moving first, done last


# ---- plain helpers

def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def day(stamp):
    """2026-10-09 as 9 Oct 2026."""
    d = date.fromisoformat(str(stamp)[:10])
    return f"{d.day} {d:%b %Y}"


def hours(minutes):
    """Active minutes as hours, '-' for none."""
    if not minutes:
        return "-"
    return "<0.1h" if minutes < 6 else f"{minutes / 60:.1f}h"


def worked_on(days):
    """'10 Nov to 14 Nov, 2 days'; the year is in the page's period."""
    if not days:
        return "-"
    days = sorted(days)
    span = " to ".join(dict.fromkeys(day(d).rsplit(" ", 1)[0] for d in (days[0], days[-1])))
    return f"{span}, {plural(len(days), 'day')}"


def paid(usd):
    """Whether a cost is worth showing: under half a cent rounds to nothing."""
    return usd >= 0.005


def money(usd):
    """Dollars, or '-' for nothing, so a ticket without sessions does not read as no effort."""
    return f"${usd:,.2f}" if paid(usd) else "-"


def pct(share):
    return "-" if share is None else f"{share:.0%}"


def amount(n):
    """1234567 as 1.2M, 45678 as 46k."""
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    return f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


def tag(name, text, **attrs):
    """One HTML element. Text is escaped; pass a list for content that is already HTML."""
    inner = "".join(text) if isinstance(text, list) else html.escape(str(text))
    shown = "".join(' %s="%s"' % (k.strip("_"), html.escape(str(v))) for k, v in attrs.items())
    return f"<{name}{shown}>{inner}</{name}>"


def dot(slot):
    """The colour mark of an overview group; slot 1-8 is a palette colour, 0 is grey."""
    return tag("span", "", class_=f"dot c{slot}")


def status_cell(name):
    return [tag("span", " ".join(STATUS[name]), class_=f"status {name}")]


def jira_link(key):
    return f"{JIRA_URL.rstrip('/')}/browse/{key}" if JIRA_URL and key else ""


def pr_links(prs):
    """Each pull request as 'repo#123 status', one per line."""
    links = [tag("a", f"{pr['repo']}#{pr['url'].rsplit('/', 1)[-1]}", href=pr["url"], title=pr["title"])
             + " " + tag("span", STATUS[pr["status"]][0], class_=f"status {pr['status']}",
                         title=STATUS[pr["status"]][1]) for pr in prs]
    return ["<br>".join(links)] if links else "-"


def repos(tickets):
    """The repos the tickets touched, those of the most expensive ticket first, as one line."""
    found = {r: None for t in sorted(tickets, key=lambda t: -t.cost) for r in t.repos}
    return ", ".join(found) or "-"


def ticket_cell(key, summary, mapped, link=""):
    """A ticket's link, with its summary, how many of its sessions came from map and the link (HTML) in the small
    print."""
    small = summary + (f" · {plural(mapped, 'session')} mapped by /worklog" if mapped else "")
    return key, jira_link(key), [html.escape(small) + (" · " if small else "") + link] if link else small


def bar_cell(shown, value, top):
    """A table cell: what is shown, over a bar as long as value is against top."""
    bar = tag("span", "", class_="c1", style=f"width:{value / max(top, 0.01) * 100:.1f}%")
    return [html.escape(str(shown)) + tag("div", [bar], class_="bar")]


def most_used(counts):
    """{name: [uses, sessions]} as (name, [uses, sessions]) pairs, most used first, then by name."""
    return sorted(counts.items(), key=lambda item: (-item[1][0], item[0]))


# ---- charts: inline SVG in the page's colours

def svg(width, height, marks, label):
    return tag("div", [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)}">'
                       + "".join(marks) + "</svg>"], class_="chart")


def mark(kind, title, slot, **attrs):
    """One SVG shape in a palette colour, with a tooltip."""
    shown = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<{kind} class="c{slot}"{shown}><title>{html.escape(title)}</title></{kind}>'


def text(x, y, words, anchor="start"):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}">{html.escape(str(words))}</text>'


def daily_chart(daily, since, until):
    """Cost per day as columns, one segment per model, 2px apart."""
    first, last = date.fromisoformat(since), date.fromisoformat(until)
    days = [str(first + timedelta(n)) for n in range((last - first).days + 1)]
    models = sorted({m for d in daily.values() for m, usd in d.items() if paid(usd)},
                    key=lambda m: (MODEL_SLOTS.get(m, 99), m))
    top = max([sum(d.values()) for d in daily.values()] + [0.01])
    w, h, left, base = 720, 180, 44, 156
    step = (w - left) / len(days)
    marks = [f'<line class="grid" x1="{left}" x2="{w}" y1="{base - 140}" y2="{base - 140}"/>',
             f'<line class="axis" x1="{left}" x2="{w}" y1="{base}" y2="{base}"/>',
             text(left - 6, base - 136, money(top), "end"), text(left - 6, base, "$0", "end")]
    for i, d in enumerate(days):
        y = base
        for m in models:
            usd = daily.get(d, {}).get(m, 0)
            if paid(usd):
                height = max(usd / top * 140 - 2, 1)
                y -= height + 2
                marks.append(mark("rect", f"{day(d)}, {m}: {money(usd)}", MODEL_SLOTS.get(m, 0),
                                  x=f"{left + i * step + 1:.1f}", y=f"{y + 2:.1f}", width=f"{max(step - 2, 1):.1f}",
                                  height=f"{height:.1f}", rx=2))
        if i in (0, len(days) // 2, len(days) - 1):
            marks.append(text(f"{left + i * step + step / 2:.1f}", base + 18, day(d).rsplit(" ", 1)[0], "middle"))
    legend = tag("ul", [tag("li", [dot(MODEL_SLOTS.get(m, 0)) + html.escape(m)]) for m in models], class_="legend")
    return legend + svg(w, h + 4, marks, "Cost per day by model")


def peaks_chart(peaks):
    """The peak context of each session, in order, with the BIG_CONTEXT line."""
    top = max([p for _, p, _ in peaks] + [BIG_CONTEXT * 1.2])
    w, h, left, base = 720, 150, 44, 130
    step = (w - left - 12) / max(len(peaks) - 1, 1)
    y = base - BIG_CONTEXT / top * 120
    marks = [f'<line class="axis" x1="{left}" x2="{w}" y1="{base}" y2="{base}"/>',
             f'<line class="limit" x1="{left}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>',
             text(left - 6, y + 4, f"{BIG_CONTEXT // 1000}k", "end"), text(left - 6, base, "0", "end"),
             text(left - 6, base - 116, f"{top / 1000:.0f}k", "end")]
    marks += [mark("circle", f"{day(d)}: {p / 1000:.0f}k, {t}", 1, cx=f"{left + 6 + i * step:.1f}",
                   cy=f"{base - p / top * 120:.1f}", r=4) for i, (d, p, t) in enumerate(peaks)]
    return svg(w, h, marks, "Peak context per session")


# ---- the page

class Page:
    """One report page. share=True is the page for other readers: time instead of cost everywhere, and no
    Using Claude sections."""

    def __init__(self, data, share=False):
        self.data, self.share = data, share
        self.health = {} if share else data.get("health", {})  # AgentsView's score per session (agentsview.sync)
        self.groups = self.grouped()

    # -- building blocks that depend on who reads the page

    def grid(self, head, rows, classes=None):
        """An HTML table. A cell that is a (text, url, small print) tuple becomes a link (when there is a url)
        with a line under it. The Cost column is left out of a shared page."""
        if self.share and "Cost" in head:
            i = head.index("Cost")
            head, rows = head[:i] + head[i + 1:], [r[:i] + r[i + 1:] for r in rows]

        def cell(c):
            if not isinstance(c, tuple):
                return tag("td", c)
            words, url, small = c
            return tag("td", [tag("a", words, href=url) if url else html.escape(words)]
                       + ([tag("small", small)] if small else []))
        return tag("div", [tag("table", [tag("tr", [tag("th", h) for h in head])] + [
            tag("tr", [cell(c) for c in row], **({"class_": cls} if cls else {}))
            for row, cls in zip(rows, classes or [""] * len(rows))])], class_="scroll")

    def section(self, title, intro, *parts, usd=None, minutes=None, slot=None):
        """A boxed section with its total at the right of the title: cost on your page, time on a shared one."""
        total = ""
        if self.share and minutes:
            total = hours(minutes)
        elif not self.share and usd and paid(usd):
            total = money(usd)
        name = [(dot(slot) if slot is not None else "") + (title[0] if isinstance(title, list) else html.escape(title))]
        head = tag("div", [tag("h2", name)] + ([tag("span", total, class_="total")] if total else []), class_="head")
        return tag("section", [head] + ([tag("p", intro, class_="intro")] if intro else []) + list(parts),
                   class_="box")

    def model_split(self, models):
        """'Opus $4.10 (80%), Sonnet $1.02 (20%)', the most used first; only the percentages when shared."""
        total = sum(models.values())
        if not paid(total):
            return "-"
        parts = sorted(((m, usd) for m, usd in models.items() if paid(usd)), key=lambda item: -item[1])
        return ", ".join(f"{m} {'' if self.share else money(usd) + ' '}({usd / total:.0%})" for m, usd in parts)

    def health_cell(self, ids):
        """AgentsView's health of these sessions: their average score, with how many got each grade and how many
        were abandoned in the small print."""
        found = [self.health[sid] for sid in ids if sid in self.health]
        if not found:
            return "-"
        grades = defaultdict(int)
        for h in found:
            grades[h["grade"]] += 1
        small = ", ".join(f"{n} {grade}" for grade, n in sorted(grades.items()))
        gone = sum(h["outcome"] == "abandoned" for h in found)
        small += f" · {gone} abandoned" if gone else ""
        return [html.escape(str(round(sum(h["score"] for h in found) / len(found)))) + tag("small", small)]

    def sessions_link(self, key):
        """The ticket's latest session in AgentsView, beside the list of all its sessions, as HTML; none for a
        ticket without sessions, or on a shared page, whose readers cannot open it."""
        latest = {k: sid for sid, k in self.data["ticket_of"].items() if k}  # sessions run oldest first
        url = "" if self.share or key not in latest else ticket_url(key, latest[key])
        return tag("a", "Sessions in AgentsView", href=url) if url else ""

    # -- the work

    def grouped(self):
        """The overview's rows, keyed by id: tickets, support, reviews and other work, each with the cost and time
        of its parts (tickets, the reviews, a repo's other work), which add up to the total, and a colour slot. A
        group with no parts is left out."""
        d = self.data
        tickets, support, other, reviews = d["tickets"], d["support"], d["other"], d["reviews"]
        rows = [("tickets", "Tickets", len(tickets), repos(tickets), tickets),
                ("support", "Support tickets", len(support), repos(support), support),
                ("reviews", "Code reviews", "-", "-", [reviews] if d["prs"]["reviewed"] or paid(reviews.cost) else []),
                ("other", "Other work", "-", ", ".join(sorted(other, key=lambda r: -other[r].cost)),
                 list(other.values()))]
        found = {gid: {"name": name, "tickets": n, "repos": r, "cost": sum(p.cost for p in parts),
                       "minutes": sum(p.minutes for p in parts)}
                 for gid, name, n, r, parts in rows if parts}
        for i, g in enumerate(found.values(), 1):
            g["slot"] = i  # palette colours in a fixed order
        return found

    def headline(self):
        """The headline numbers as (number, label), outcomes first; one with nothing behind it is left out."""
        d = self.data
        prs, tickets, support = d["prs"], d["tickets"], d["support"]

        def s(n):
            return "" if n == 1 else "s"
        merged, reviewed = sum(pr["status"] == "merged" for pr in prs["opened"]), len(prs["reviewed"])
        touched = {t.key for t in tickets + support}  # reviews for others do not count
        tiles = [(len(touched), f"ticket{s(len(touched))} worked on", touched),
                 (merged, f"pull request{s(merged)} merged, of {len(prs['opened'])} opened", prs["opened"]),
                 (reviewed, f"pull request{s(reviewed)} reviewed", reviewed)]
        tiles = [(number, label) for number, label, behind in tiles if behind]
        if d["minutes"]:
            part = ("" if d["timed"] == d["sessions"]
                    else f", from the {d['timed']} of {d['sessions']} sessions that recorded it")
            tiles.append((hours(d["minutes"]), "of active time in Claude Code" + part))
        if not self.share:
            tiles.append((money(d["total"]), "at API list prices"))
        return tiles

    def overview(self):
        """The groups as a table, after a bar and legend that split the whole between them: cost on your page,
        time on a shared one."""
        rows, basis = list(self.groups.values()), "minutes" if self.share else "cost"
        top, total = max([g[basis] for g in rows] + [0.01]), sum(g[basis] for g in rows) or 0.01

        def share(g):
            if not g[basis]:
                return "-"
            part = g[basis] / total
            return "<1%" if part < 0.005 else f"{part:.0%}"

        def spend(g):
            bar = tag("div", [tag("span", "", class_=f"c{g['slot']}", style=f"width:{g[basis] / top * 100:.1f}%")],
                      class_="bar")
            return [html.escape(hours(g["minutes"]) if self.share else money(g["cost"])) + bar]
        shown = [g for g in rows if g[basis] and (self.share or paid(g["cost"]))]
        split = tag("div", [tag("span", "", class_=f"c{g['slot']}", style=f"flex-grow:{g[basis] / total:.4f}",
                                title=f"{g['name']}: {share(g)}") for g in shown], class_="split")
        legend = tag("ul", [tag("li", [dot(g["slot"]) + html.escape(g["name"]) + " " + tag("strong", share(g))])
                            for g in shown], class_="legend")
        head = ["Group", "Tickets", "Repos"] + (["Share", "Time"] if self.share else ["Time", "Share", "Cost"])
        body = [[[dot(g["slot"]) + html.escape(g["name"])], g["tickets"], g["repos"]]
                + ([share(g), spend(g)] if self.share else [hours(g["minutes"]), share(g), spend(g)]) for g in rows]
        intro = ("Where the time went, by kind." if self.share else
                 "Where the work went, by kind. A share is the group's part of the session cost.")
        return self.section("Overview", intro, split + legend + self.grid(head, body))

    def ticket_boxes(self, tickets, slot, name):
        """One box per ticket, the most expensive first, then one box for the tickets that cost less than SMALL."""
        typed = any(w.type for t in tickets for w in t.works)
        scored = any(sid in self.health for t in tickets for w in t.works for sid in w.ids)
        head = (["Ticket"] + (["Type"] if typed else []) + ["Worked on", "Pull requests", "Models"]
                + (["Health"] if scored else []) + ["Time", "Cost"])
        ranked = sorted(tickets, key=lambda t: -t.cost)
        small = [t for t in ranked if t.cost < SMALL]
        boxes = [self.ticket_box(t, head, typed, scored, slot) for t in ranked if t.cost >= SMALL]
        if small:
            boxes.append(self.small_box(small, head, typed, scored, slot, name))
        return boxes

    def ticket_box(self, t, head, typed, scored, slot):
        """A ticket's box: its note first in the intro, then a table with the ticket's own work and each sub-task,
        indented, with its own health, time and cost."""
        notes = self.data["notes"]
        rows = [[ticket_cell(w.key, w.summary, w.mapped)] + ([w.type or "-"] if typed else [])
                + [worked_on(w.days), pr_links(w.prs), self.model_split(w.models)]
                + ([self.health_cell(w.ids)] if scored else []) + [hours(w.minutes), money(w.cost)]
                for w in t.works]
        label = f"{t.key} {t.own.summary}".strip()
        title = [tag("a", label, href=jira_link(t.key))] if JIRA_URL else label
        titles = list(dict.fromkeys(pr["title"] for w in t.works for pr in w.prs))
        intro = notes[t.key] + " " if t.key in notes else ""
        intro += f"Repos: {', '.join(t.repos)}." if t.repos else ""
        intro += f" Pull requests: {'; '.join(titles)}." if titles else ""
        intro += " The total includes the sub-tasks." if t.subs else ""
        intro, link = intro.strip(), self.sessions_link(t.key)
        if link:
            intro = [html.escape(intro) + (" " if intro else "") + link]
        return self.section(title, intro, self.grid(head, rows, [""] + ["sub"] * len(t.subs)),
                            usd=t.cost, minutes=t.minutes, slot=slot)

    def small_box(self, small, head, typed, scored, slot, name):
        """The tickets that cost less than SMALL in one box, a row each with its sub-tasks included and its note in
        the small print."""
        notes = self.data["notes"]
        rows = []
        for t in small:
            models = defaultdict(float)
            for w in t.works:
                for model, usd in w.models.items():
                    models[model] += usd
            summary = f"{t.own.summary}. {notes[t.key]}" if t.key in notes else t.own.summary
            rows.append([ticket_cell(t.key, summary, sum(w.mapped for w in t.works), self.sessions_link(t.key))]
                        + ([t.own.type or "-"] if typed else [])
                        + [worked_on(set().union(*(w.days for w in t.works))),
                           pr_links([pr for w in t.works for pr in w.prs]), self.model_split(models)]
                        + ([self.health_cell([sid for w in t.works for sid in w.ids])] if scored else [])
                        + [hours(t.minutes), money(t.cost)])
        intro = (f"{plural(len(small), name[:-1])} with little session time." if self.share else
                 f"{plural(len(small), name[:-1])} that cost less than {money(SMALL)} each, sub-tasks included.")
        return self.section(f"Smaller {name}", intro, self.grid(head, rows), usd=sum(t.cost for t in small),
                            minutes=sum(t.minutes for t in small), slot=slot)

    def work(self):
        """The overview, then the ticket boxes, pull requests without a ticket, other work and code reviews."""
        d, g = self.data, self.groups
        prs = d["prs"]

        def boxed(gid, title, intro, *parts):
            return self.section(title, intro, *parts, usd=g[gid]["cost"], minutes=g[gid]["minutes"],
                                slot=g[gid]["slot"])
        body = [self.overview()]
        for gid in ("tickets", "support"):
            if d[gid]:
                body += self.ticket_boxes(d[gid], g[gid]["slot"], g[gid]["name"].lower())
        without_ticket = [pr for pr in prs["opened"] if not pr["ticket"]]
        if without_ticket:
            body.append(self.section("Pull requests without a ticket", "", self.grid(
                ["Opened", "Pull request", "Status"],
                [[day(pr["date"]), (pr["title"], pr["url"], pr["repo"]), status_cell(pr["status"])]
                 for pr in without_ticket])))
        if d["other"]:
            body.append(boxed("other", "Other work", "Sessions with no Jira ticket or review behind them, by repo.",
                              self.grid(["Repo", "Worked on", "Time", "Cost"],
                                        [[repo, worked_on(o.days), hours(o.minutes), money(o.cost)]
                                         for repo, o in sorted(d["other"].items(), key=lambda item: -item[1].cost)])))
        if "reviews" in g:
            intro = ("Pull requests by teammates that you reviewed." if prs["reviewed"]
                     else "GitHub listed no reviews in the period.")
            body.append(boxed("reviews", "Code reviews", intro, *self.review_groups(prs["reviewed"])))
        return body

    # -- how you use Claude (your page only)

    def using_claude(self):
        """Tips, then the measures, then the most expensive sessions: what to change, and where to look."""
        d = self.data
        m = d["measures"]
        merged = sum(pr["status"] == "merged" for pr in d["prs"]["opened"])
        worked = d["tickets"] + d["support"]
        advice = (tag("ul", [tag("li", [tag("strong", found) + " " + html.escape(todo)]) for found, todo in d["tips"]],
                      class_="tips") if d["tips"] else
                  tag("p", "Every measure is within its line. Nothing to change this period.", class_="intro"))
        rows = [["Sessions", m["sessions"]],
                ["Cost per merged pull request", money(m["cost"] / merged) if merged else "-"],
                ["Cost per ticket", money(sum(t.cost for t in worked) / len(worked)) if worked else "-"],
                ["Cache hit rate (cache reads / all input)", pct(m["cache_hit"])],
                [f"Share of cost in sessions past {BIG_CONTEXT // 1000}k context", pct(m["big"])],
                ["Share of cost in subagents", pct(m["subagents"])],
                ["Share of cost in sessions that changed nothing", pct(m["idle"])],
                ["Prompts per session", f"{m['prompts']:.1f}" if m["prompts"] is not None else "-"],
                ["Prompts per merged pull request",
                 f"{m['prompts'] * m['rated'] / merged:.0f}" if m["prompts"] is not None and merged else "-"],
                ["Sessions you interrupted", pct(m["interrupted"])],
                ["Sessions compacted", m["compacted"]]]
        top = self.grid(["Date", "Session", "Peak context", "Prompts", "Interrupts", "Failed tools", "Cost"],
                        [[day(r["day"]), (r["title"] or r["prompt"][:80] or "(no title)", session_url(r["id"]), repo_of(r)),
                          f"{r['context']['peak'] // 1000}k" if "context" in r else "-",
                          r.get("prompts", "-"), r.get("interrupts", "-"), r.get("errors", "-"), money(cost(r))]
                         for r in m["top"]])
        intro = ("From your sessions alone, for your own learning; --share leaves this out. Rows recorded before a "
                 "measure was kept do not count for it.")
        return self.section("Using Claude well", intro, tag("h3", "What to try"), advice,
                            tag("h3", "Measures"), self.grid(["Measure", "This period"], rows),
                            tag("h3", f"The {len(m['top'])} most expensive sessions"), top)

    def tokens_and_context(self):
        """Context sizes with the peak of each session, tokens per model, and cost per day."""
        d = self.data
        m, usage = d["measures"], d["usage"]
        c = m["context"]

        def k(n):
            return f"{n / 1000:.0f}k"
        models = sorted(m["tokens"].items(), key=lambda item: (MODEL_SLOTS.get(item[0], 99), item[0]))
        return self.section(
            "Tokens and context", f"Context is what each reply re-reads: {c['sessions']} sessions recorded it.",
            self.grid(["Average per reply", "Average peak per session", "Largest peak",
                       f"Sessions past {k(BIG_CONTEXT)}"], [[k(c["avg"]), k(c["peak_avg"]), k(c["peak"]), c["big"]]]),
            *([tag("h3", "Peak context per session"), peaks_chart(usage["peaks"])] if usage["peaks"] else []),
            tag("h3", "Tokens per model"),
            self.grid(["Model", "Input", "Output", "Cache read", "Cache write", "Cache hit rate"],
                      [[[dot(MODEL_SLOTS.get(name, 0)) + html.escape(name)], amount(t["in"]), amount(t["out"]),
                        amount(t["read"]), amount(t["write"]), pct(t["read"] / max(sum(t[x] for x in SENT), 1))]
                       for name, t in models]),
            tag("h3", "Cost per day by model"), daily_chart(usage["daily"], d["since"], d["until"]))

    def review_groups(self, reviewed):
        """The reviewed pull requests in one collapsible group per status: draft, open, closed, then merged, each
        by date. Merged, the long finished list, starts folded."""
        groups = []
        for status in REVIEW_ORDER:
            group = [pr for pr in reviewed if pr["status"] == status]
            if group:
                head = tag("summary", status_cell(status) + [tag("span", f" {len(group)}", class_="count")])
                table = self.grid(["Reviewed", "Pull request"],
                                  [[day(pr["date"]), (pr["title"], pr["url"], f"{pr['repo']} · {pr['author']}")]
                                   for pr in group])
                groups.append(tag("details", [head, table], **({} if status == "merged" else {"open": "open"})))
        return groups

    def misc(self):
        """The skills, MCP servers and subagents the sessions used, most used first; then what loaded into every
        session without being used, with what it cost, the total at the right of the title."""
        usage = self.data["usage"]
        parts = []
        for kind, head in {"skill": "Skill", "mcp": "MCP server", "agent": "Subagent"}.items():
            if usage.get(kind):
                rows = most_used(usage[kind])
                parts.append(self.grid([head, "Uses", "Sessions"], [[name, bar_cell(n, n, rows[0][1][0]), sessions]
                                                                     for name, (n, sessions) in rows]))
        unused = usage.get("unused") or []
        total = sum(u["usd"] or 0 for u in unused)
        if unused:
            parts += [tag("h3", "Loaded but not used"),
                      tag("p", f"{plural(len(unused), 'item')} sat in the context of every session without being "
                               f"used, about {money(total)} in this period. Each reply re-reads them, so this is "
                               "their share of what the sessions paid for cached context. Remove skills from "
                               "~/.claude/skills, plugins with /plugin and MCP servers with /mcp.",
                          class_="intro unused"),
                      self.grid(["Item", "Kind", "Tokens per session", "Cost"],
                                [[u["name"], u["kind"], "?" if u["tokens"] is None else amount(u["tokens"]),
                                  "?" if u["usd"] is None else money(u["usd"])] for u in unused])]
        intro = "Skills, MCP servers and subagents the sessions used, most used first, and what loaded unused."
        return self.section("Misc", intro, *parts, usd=total) if parts else ""

    def write(self, file):
        d = self.data
        body = [tag("header", [tag("h1", "Work summary"),
                               tag("p", f"{day(d['since'])} to {day(d['until'])}", class_="period")]),
                tag("div", [tag("div", [tag("strong", n), tag("span", label)], class_="tile")
                            for n, label in self.headline()], class_="tiles")]
        if not self.share:
            body.append(self.using_claude())
        body += self.work()
        if not self.share:
            body += [self.tokens_and_context(), self.misc()]
        body.append(tag("footer", "Sources: Jira, GitHub and the records Claude Code keeps on this computer. "
                        f"Time is active time in sessions: a gap over {IDLE} minutes counts as a break, and sessions "
                        "that ran side by side add up. "
                        + ("" if self.share else "Costs are what the sessions would cost at Claude API list prices. ")
                        + f"Generated on {day(date.today())}."))
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(Template(TEMPLATE.read_text()).substitute(
            title=f"Work summary, {day(d['since'])} to {day(d['until'])}", body="\n".join(b for b in body if b)))
        return file
