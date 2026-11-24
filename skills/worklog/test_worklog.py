"""Tests for the worklog scripts on made-up sessions, transcripts, pull requests and Jira issues.
Run: python3 -m unittest test_worklog"""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import github
import ledger
import page
import worklog as w

ISSUES = {"ABC-1": {"summary": "Export", "type": "Story", "subtask": False, "parent": ""},
          "ABC-2": {"summary": "CSV", "type": "Sub-task", "subtask": True, "parent": "ABC-1"},
          "ABC-9": {"summary": "Billing", "type": "Epic", "subtask": False, "parent": ""},
          "ABC-3": {"summary": "Typo", "type": "Bug", "subtask": False, "parent": ""},
          "ABC-4": {"summary": "Label", "type": "Bug", "subtask": False, "parent": ""}}


def session(n, keys=(), cost=1.0, edits=True, review=False, branches=("main",), repo="api", **more):
    return {"id": f"s{n}", "start": f"2026-11-{n:02d}T09:00:00Z", "cwd": str(w.DEV / repo), "title": f"Session {n}",
            "prompt": "", "keys": list(keys), "branches": list(branches), "edits": edits, "review": review,
            "cost": cost, "models": {"Opus": cost}, "subagent_cost": 0.0,
            "context": {"peak": 50_000, "avg": 30_000, "compactions": 0},
            "tokens_by_model": {"Opus": {"in": 10, "out": 10, "read": 80, "write": 10}},
            "prompts": 3, "interrupts": 0, "errors": 0, "active": 30, **more}


def pr(n, text, branch, author="me", status="merged"):
    return {"date": "2026-11-05", "repo": "api", "title": f"PR {n}", "url": f"https://github.com/acme/api/pull/{n}",
            "status": status, "author": author, "branch": branch, "text": text}


def quiet(call, *args):
    """What a call prints, as a string."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        call(*args)
    return out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        """Every data file in a fresh folder; no real transcripts, GitHub or Jira."""
        tmp = Path(tempfile.mkdtemp())
        self.tmp = tmp
        ledger.DATA, ledger.LEDGER, ledger.PROJECTS = tmp, tmp / "sessions.jsonl", tmp / "projects"
        ledger.CLAUDE_STATE = tmp / "claude.json"
        w.DATA, w.MAPPED, w.NOTES = tmp, tmp / "mapped.json", tmp / "notes.json"
        w.KEY, w.PREFIXES, w.SUPPORT = re.compile(r"\b(?:ABC)-\d+\b", re.I), "ABC", set()
        w.jira.issue = lambda key: ISSUES[key]
        w.jira.updated = lambda since, until: {k: {"summary": v["summary"], "type": v["type"]} for k, v in ISSUES.items()}
        w.jira.in_progress = lambda day: {"ABC-3": {"summary": "Typo", "type": "Bug"}} if day == "2026-11-02" else {}

    def collect(self, rows, opened=(), reviewed=(), resolved=(), mapped=(), earlier=(), commits=()):
        ledger.LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))
        w.pull_requests = lambda since, until: {"opened": list(opened), "earlier": list(earlier),
                                                "reviewed": list(reviewed)}
        w.commit_pulls = lambda repo_dir, start, end: list(commits)
        w.jira.resolved = lambda since, until: list(resolved)
        if mapped:
            quiet(w.save, w.MAPPED, {s: w.checked(k) for s, k in w.pairs(list(mapped), "map")})
        return w.collect("2026-11-01", "2026-11-30")


class Sorting(Base):
    def test_sub_task_counts_for_its_parent_with_its_own_cost(self):
        data = self.collect([session(1, ["ABC-1"], 2.0), session(2, ["abc-2"], 3.0)], resolved=["ABC-2"])
        (t,) = data["tickets"]
        self.assertEqual((t.key, t.cost, t.own.cost), ("ABC-1", 5.0, 2.0))
        self.assertEqual((t.subs["ABC-2"].cost, t.subs["ABC-2"].resolved, t.resolved), (3.0, True, False))

    def test_ticket_wins_over_an_epic_named_with_it(self):
        (t,) = self.collect([session(1, ["ABC-9", "ABC-1"])])["tickets"]
        self.assertEqual(t.key, "ABC-1")

    def test_session_takes_the_ticket_of_the_pull_request_from_its_branch(self):
        data = self.collect([session(1, branches=["feature-x"])], opened=[pr(4, "fixes ABC-1", "feature-x")])
        self.assertEqual([t.key for t in data["tickets"]], ["ABC-1"])

    def test_a_branch_of_an_earlier_pull_request_still_names_its_ticket(self):
        data = self.collect([session(1, branches=["feature-y"])], earlier=[pr(3, "ABC-4 label", "feature-y")])
        (t,) = data["tickets"]
        self.assertEqual((t.key, t.own.prs), ("ABC-4", []))

    def test_session_takes_the_ticket_of_the_pull_request_holding_its_commits(self):
        row = {**session(1, repo="tools"), "cwd": tempfile.mkdtemp(), "end": "2026-11-01T10:00:00Z"}
        data = self.collect([row], commits=["Fix label\nfix-label\nCloses ABC-3"])
        self.assertEqual([t.key for t in data["tickets"]], ["ABC-3"])

    def test_review_sessions_add_up_to_one_total(self):
        rows = [session(1, edits=False, review=True, cost=1.5), session(2, edits=False, review=True, cost=0.5)]
        data = self.collect(rows, reviewed=[pr(7, "", "b", author="teammate")])
        self.assertEqual((data["reviews"]["cost"], page.Page(data).groups["reviews"]["cost"]), (2.0, 2.0))

    def test_a_mapped_session_counts_for_its_ticket_and_rules_still_win(self):
        rows = [session(1, repo="tools"), session(2, ["ABC-9"]), session(3, repo="tools")]
        data = self.collect(rows, mapped=["s1", "abc-1", "s2", "ABC-2"])
        self.assertEqual(sorted(t.key for t in data["tickets"]), ["ABC-1", "ABC-9"])
        self.assertEqual([r["id"] for r in data["unmapped"]], ["s3"])
        self.assertEqual({t.key: t.own.mapped for t in data["tickets"]}, {"ABC-1": 1, "ABC-9": 0})
        boxes = page.Page(data).ticket_boxes(data["tickets"], 1, "tickets")
        self.assertIn("1 session mapped by /worklog", "".join(boxes))

    def test_no_session_is_dropped(self):
        rows = [session(1, ["ABC-1"]), session(2, edits=False), session(3, repo="tools")]
        data = self.collect(rows)
        self.assertAlmostEqual(sum(g["cost"] for g in page.Page(data).groups.values()), data["total"])
        self.assertEqual(data["measures"]["cache_hit"], 0.8)

    def test_map_refuses_a_key_outside_the_prefixes(self):
        with self.assertRaises(SystemExit):
            w.checked("XYZ-1")

    def test_check_runs_on_a_fresh_machine(self):
        w.FILE, w.PREFIXES, w.JIRA_PREFIXES = self.tmp / "none.json", "", []
        out = quiet(w.check)
        self.assertIn("warn  settings", out)
        self.assertIn("warn  jira_prefixes", out)
        self.assertIn("warn  ledger", out)

    def test_period_takes_empty_last_month_or_a_day(self):
        self.assertEqual(w.period("2026-11-01")[0], "2026-11-01")
        with self.assertRaises(SystemExit):
            w.period("november")


class Prepare(Base):
    def test_prepare_offers_assigned_and_in_progress_issues_and_notes_show(self):
        data = self.collect([session(1, ["ABC-1"], 2.0), session(2, repo="tools")])
        found = json.loads(quiet(w.prepare, ["2026-11-01"]))
        self.assertEqual(sorted(found["assigned"]), ["ABC-2", "ABC-3", "ABC-4", "ABC-9"])
        self.assertEqual([s["id"] for s in found["sessions"]], ["s2"])
        self.assertEqual(list(found["sessions"][0]["in_progress"]), ["ABC-3"])
        data["notes"] = {"ABC-1": "Shipped the export."}
        self.assertIn("Shipped the export.", page.Page(data).ticket_boxes(data["tickets"], 1, "tickets")[0])


class Pages(Base):
    def test_tickets_under_a_dollar_share_one_box_with_their_sum(self):
        data = self.collect([session(1, ["ABC-1"], 2.0), session(2, ["ABC-3"], 0.4), session(3, ["ABC-4"], 0.3)])
        boxes = page.Page(data).ticket_boxes(data["tickets"], 1, "tickets")
        self.assertEqual(len(boxes), 2)
        self.assertIn("Smaller tickets", boxes[1])
        self.assertTrue(all(usd in boxes[1] for usd in ("$0.70", "$0.40", "$0.30")))

    def test_shared_page_shows_time_and_no_cost_or_usage(self):
        data = self.collect([session(1, ["ABC-1"], 2.0), session(2, edits=False, repo="tools")])
        mine = page.Page(data).write(self.tmp / "report.html").read_text()
        shared = page.Page(data, share=True).write(self.tmp / "share.html").read_text()
        self.assertIn("Using Claude well", mine)
        self.assertIn("$2.00", mine)
        self.assertNotIn("Using Claude well", shared)
        self.assertNotIn("$", re.sub(r"<style>.*?</style>", "", shared, flags=re.S))
        self.assertIn("1.0h", shared)
        self.assertNotIn("sessions that recorded it", shared)
        del data["unmapped"][0]["active"]  # a session recorded before time was kept
        data.update(minutes=30, timed=1)
        self.assertIn("from the 1 of 2 sessions that recorded it", page.Page(data).write(self.tmp / "r.html").read_text())

    def test_hours(self):
        self.assertEqual((page.hours(0), page.hours(3), page.hours(90)), ("-", "<0.1h", "1.5h"))


class Measures(Base):
    def test_tips_show_only_past_their_lines_and_with_enough_sessions(self):
        heavy = {"context": {"peak": 150_000, "avg": 90_000, "compactions": 1}, "interrupts": 1, "edits": False}
        rows = [session(n, **heavy) for n in range(1, 7)]
        found = " ".join(f for f, _ in w.tips(w.measures(rows)))
        for words in ("past 100k", "only asked questions", "changed no files", "stopped Claude", "compacted"):
            self.assertIn(words, found)
        self.assertEqual(w.tips(w.measures(rows[:4])), [])
        healthy = {"tokens_by_model": {"Opus": {"in": 1, "out": 10, "read": 95, "write": 4}}}
        self.assertEqual(w.tips(w.measures([session(n, **healthy) for n in range(1, 7)])), [])

    def test_most_expensive_sessions_come_first(self):
        m = w.measures([session(1, cost=1.0), session(2, cost=5.0), session(3, cost=2.0)])
        self.assertEqual([r["id"] for r in m["top"]], ["s2", "s3", "s1"])


class Ledger(Base):
    def transcript(self, lines, name="t1"):
        folder = ledger.PROJECTS / "proj"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.jsonl"
        path.write_text("".join(json.dumps(d) + "\n" for d in lines))
        return path

    def test_a_transcript_gives_prompts_interrupts_errors_and_active_time(self):
        def user(t, content, **more):
            return {"type": "user", "timestamp": t, "cwd": "/x", "message": {"role": "user", "content": content}, **more}

        def reply(t, n):
            return {"type": "assistant", "timestamp": t, "message": {"id": f"m{n}", "model": "claude-opus-5-5",
                    "content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 10, "output_tokens": 5}}}
        path = self.transcript([
            user("2026-11-01T09:00:00Z", "Fix ABC-1 please"), reply("2026-11-01T09:01:00Z", 1),
            user("2026-11-01T09:02:00Z", [{"type": "tool_result", "is_error": True, "content": "denied"}]),
            user("2026-11-01T09:03:00Z", [{"type": "text", "text": "[Request interrupted by user]"}]),
            user("2026-11-01T10:00:00Z", "<command-name>/clear</command-name>"),
            user("2026-11-01T10:01:00Z", "try again"), reply("2026-11-01T10:02:00Z", 2)])
        row = ledger.Session(path).result()
        self.assertEqual((row["prompts"], row["interrupts"], row["errors"]), (2, 1, 1))
        self.assertEqual((row["active"], row["prompt"], row["keys"]), (5.0, "Fix ABC-1 please", ["ABC-1"]))

    def test_refresh_keeps_one_row_per_session(self):
        rows = [session(1, cost=1.0), session(1, cost=2.0), session(2)]
        ledger.LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))
        found = ledger.refresh()
        self.assertEqual(sorted((r["id"], r["cost"]) for r in found), [("s1", 2.0), ("s2", 1.0)])
        self.assertEqual(len(ledger.LEDGER.read_text().splitlines()), 2)

    def test_prices_come_from_config_and_an_unlisted_model_is_priced_as_the_default(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 1_000_000, "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}
        self.assertAlmostEqual(ledger.price({**usage, "model": "claude-sonnet-5-5-20261101"}), 2 * 3 + 10 + 0.10)
        self.assertAlmostEqual(ledger.price({**usage, "model": "claude-new-9"}),
                               ledger.price({**usage, "model": "claude-opus-5-5"}))
        self.assertEqual((ledger.name("claude-sonnet-5-5"), ledger.name("claude-haiku-5-5")), ("Sonnet", "Haiku"))

    def test_claude_codes_cost_wins_unless_it_counted_less(self):
        reply = {"type": "assistant", "timestamp": "2026-11-01T09:00:00Z", "cwd": "/x",
                 "message": {"id": "m1", "model": "claude-opus-5-5", "content": [],
                             "usage": {"input_tokens": 100_000, "output_tokens": 0}}}  # $0.40 at list prices
        self.transcript([reply], "s1")
        self.transcript([reply], "s2")
        state = {"projects": {"/a": {"lastSessionId": "s1", "lastModelUsage": {
            "claude-opus-5-5": {"costUSD": 0.42}, "claude-haiku-5-5": {"costUSD": 0.01}}},
            "/b": {"lastSessionId": "s2", "lastModelUsage": {"claude-opus-5-5": {"costUSD": 0.1}}}}}
        ledger.CLAUDE_STATE.write_text(json.dumps(state))
        found = {r["id"]: r for r in ledger.refresh()}
        self.assertEqual((found["s1"]["cost"], found["s1"]["models"]), (0.43, {"Opus": 0.42, "Haiku": 0.01}))
        self.assertEqual((found["s2"]["cost"], found["s2"].get("measured")), (0.4, None))
        ledger.CLAUDE_STATE.write_text("{}")  # the next session in that folder replaced it; the ledger keeps it
        self.assertEqual({r["id"]: r["cost"] for r in ledger.refresh()}, {"s1": 0.43, "s2": 0.4})

    def test_github_splits_your_pull_requests_into_opened_and_earlier(self):
        def node(n, created):
            return {"title": f"PR {n}", "url": f"https://github.com/acme/api/pull/{n}", "state": "MERGED",
                    "isDraft": False, "createdAt": created, "headRefName": f"b{n}", "body": "", "author": {"login": "me"},
                    "repository": {"name": "api"}, "reviews": {"nodes": []}, "commits": {"nodes": []}}
        search = github.search
        github.search = lambda q: ("me", [node(1, "2026-10-20T09:00:00Z"), node(2, "2026-11-03T09:00:00Z"),
                                          node(3, "2026-12-01T09:00:00Z")] if "author:@me" in q else [])
        try:
            found = github.pull_requests("2026-11-01", "2026-11-30")
        finally:
            github.search = search
        self.assertEqual(([p["title"] for p in found["opened"]], [p["title"] for p in found["earlier"]]),
                         (["PR 2"], ["PR 1"]))


if __name__ == "__main__":
    unittest.main()
