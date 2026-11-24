"""Tests for worklog.py on made-up sessions, pull requests and Jira issues: python3 -m unittest test_worklog"""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import worklog as w

ISSUES = {"ABC-1": {"summary": "Export", "type": "Story", "subtask": False, "parent": ""},
          "ABC-2": {"summary": "CSV", "type": "Sub-task", "subtask": True, "parent": "ABC-1"},
          "ABC-9": {"summary": "Billing", "type": "Epic", "subtask": False, "parent": ""},
          "ABC-3": {"summary": "Typo", "type": "Bug", "subtask": False, "parent": ""},
          "ABC-4": {"summary": "Label", "type": "Bug", "subtask": False, "parent": ""}}


def session(n, keys=(), cost=1.0, edits=True, review=False, branches=("main",), repo="api"):
    return {"id": f"s{n}", "start": f"2026-11-{n:02d}T09:00:00Z", "cwd": str(w.DEV / repo), "title": "", "prompt": "",
            "keys": list(keys), "branches": list(branches), "edits": edits, "review": review,
            "cost": cost, "models": {"Opus": cost}, "subagent_cost": 0.0,
            "context": {"peak": 50_000, "avg": 30_000, "compactions": 0},
            "tokens_by_model": {"Opus": {"in": 10, "out": 10, "read": 80, "write": 10}}}


def pr(n, text, branch, author="me", status="merged"):
    return {"date": "2026-11-05", "repo": "api", "title": f"PR {n}", "url": f"https://github.com/acme/api/pull/{n}",
            "status": status, "author": author, "branch": branch, "text": text}


class Report(unittest.TestCase):
    def collect(self, rows, opened=(), reviewed=(), resolved=(), mapped=()):
        tmp = Path(tempfile.mkdtemp())
        w.DATA, w.LEDGER, w.MAPPED, w.NOTES = tmp, tmp / "sessions.jsonl", tmp / "mapped.json", tmp / "notes.json"
        w.LEDGER.write_text("\n".join(json.dumps(r) for r in rows))
        w.KEY, w.PREFIXES, w.SUPPORT = re.compile(r"\b(?:ABC)-\d+\b", re.I), "ABC", set()
        w.append = lambda paths: None
        w.pull_requests = lambda since, until: {"opened": list(opened), "reviewed": list(reviewed)}
        w.jira.issue = lambda key: ISSUES[key]
        w.jira.resolved = lambda since, until: list(resolved)
        w.jira.updated = lambda since, until: {k: {"summary": v["summary"], "type": v["type"]} for k, v in ISSUES.items()}
        with contextlib.redirect_stdout(io.StringIO()):
            w.save(w.MAPPED, {s: w.checked(k) for s, k in w.pairs(list(mapped), "map")} if mapped else {})
        return w.collect("2026-11-01", "2026-11-30")

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

    def test_review_sessions_add_up_to_one_total(self):
        rows = [session(1, edits=False, review=True, cost=1.5), session(2, edits=False, review=True, cost=0.5)]
        data = self.collect(rows, reviewed=[pr(7, "", "b", author="teammate")])
        self.assertEqual((data["reviews"]["cost"], w.groups(data)["reviews"]["cost"]), (2.0, 2.0))

    def test_a_mapped_session_counts_for_its_ticket_and_rules_still_win(self):
        rows = [session(1, repo="tools"), session(2, ["ABC-9"]), session(3, repo="tools")]
        data = self.collect(rows, mapped=["s1", "abc-1", "s2", "ABC-2"])
        self.assertEqual(sorted(t.key for t in data["tickets"]), ["ABC-1", "ABC-9"])
        self.assertEqual([r["id"] for r in data["unmapped"]], ["s3"])
        mapped = {t.key: t.own.mapped for t in data["tickets"]}
        self.assertEqual(mapped, {"ABC-1": 1, "ABC-9": 0})
        self.assertIn("1 session mapped by /worklog", "".join(w.ticket_boxes(data["tickets"], 1, "tickets", {})))

    def test_prepare_offers_assigned_issues_not_on_the_page_and_notes_show(self):
        data = self.collect([session(1, ["ABC-1"], 2.0), session(2, repo="tools")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            w.prepare(["2026-11-01"])
        found = json.loads(out.getvalue())
        self.assertEqual(sorted(found["assigned"]), ["ABC-2", "ABC-3", "ABC-4", "ABC-9"])
        self.assertEqual([s["id"] for s in found["sessions"]], ["s2"])
        boxes = w.ticket_boxes(data["tickets"], 1, "tickets", {"ABC-1": "Shipped the export."})
        self.assertIn("Shipped the export.", boxes[0])

    def test_active_time_leaves_out_breaks(self):
        stamps = ["2026-11-01T09:00:00Z", "2026-11-01T09:10:00Z", "2026-11-01T10:00:00Z", "2026-11-01T10:05:00Z"]
        self.assertEqual(w.active_minutes(stamps), 15.0)
        self.assertEqual((w.hours(0), w.hours(3), w.hours(90)), ("-", "<0.1h", "1.5h"))

    def test_no_session_is_dropped(self):
        rows = [session(1, ["ABC-1"]), session(2, edits=False), session(3, repo="tools")]
        data = self.collect(rows)
        self.assertAlmostEqual(sum(g["cost"] for g in w.groups(data).values()), data["total"])
        self.assertEqual(data["measures"]["cache_hit"], 0.8)

    def test_tickets_under_a_dollar_share_one_box_with_their_sum(self):
        data = self.collect([session(1, ["ABC-1"], 2.0), session(2, ["ABC-3"], 0.4), session(3, ["ABC-4"], 0.3)])
        boxes = w.ticket_boxes(data["tickets"], 1, "tickets", {})
        self.assertEqual(len(boxes), 2)
        self.assertIn("Smaller tickets", boxes[1])
        self.assertTrue(all(usd in boxes[1] for usd in ("$0.70", "$0.40", "$0.30")))


if __name__ == "__main__":
    unittest.main()
