"""Tests for worklog.py on made-up sessions, pull requests and Jira issues: python3 -m unittest test_worklog"""
import json
import re
import tempfile
import unittest
from pathlib import Path

import worklog as w

ISSUES = {"ABC-1": {"summary": "Export", "type": "Story", "subtask": False, "parent": ""},
          "ABC-2": {"summary": "CSV", "type": "Sub-task", "subtask": True, "parent": "ABC-1"},
          "ABC-9": {"summary": "Billing", "type": "Epic", "subtask": False, "parent": ""}}


def session(n, keys=(), cost=1.0, edits=True, review=False, branches=("main",), pulls=(), repo="api"):
    return {"id": f"s{n}", "start": f"2026-11-{n:02d}T09:00:00Z", "cwd": str(w.DEV / repo), "title": "", "prompt": "",
            "keys": list(keys), "branches": list(branches), "edits": edits, "review": review, "alert": False,
            "pulls": list(pulls), "cost": cost, "models": {"Opus": cost}, "subagent_cost": 0.0,
            "context": {"peak": 50_000, "avg": 30_000, "compactions": 0},
            "tokens_by_model": {"Opus": {"in": 10, "out": 10, "read": 80, "write": 10}}}


def pr(n, text, branch, author="me", status="merged"):
    return {"date": "2026-11-05", "repo": "api", "title": f"PR {n}", "url": f"https://github.com/acme/api/pull/{n}",
            "status": status, "author": author, "branch": branch, "text": text}


class Report(unittest.TestCase):
    def collect(self, rows, opened=(), reviewed=(), resolved=(), mapped=()):
        tmp = Path(tempfile.mkdtemp())
        w.DATA, w.LEDGER, w.MAPPED = tmp, tmp / "sessions.jsonl", tmp / "mapped.json"
        w.LEDGER.write_text("\n".join(json.dumps(r) for r in rows))
        w.KEY, w.PREFIXES, w.SUPPORT = re.compile(r"\b(?:ABC)-\d+\b", re.I), "ABC", set()
        w.append = lambda paths: None
        w.pull_requests = lambda since, until: {"opened": list(opened), "reviewed": list(reviewed)}
        w.jira.issue = lambda key: ISSUES[key]
        w.jira.resolved = lambda since, until: list(resolved)
        if mapped:
            w.map_sessions(list(mapped))
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

    def test_review_session_costs_go_to_the_pull_request_it_names(self):
        data = self.collect([session(1, edits=False, review=True, pulls=["#7"], repo="scratch")],
                            reviewed=[pr(7, "", "b", author="teammate")])
        self.assertEqual((data["prs"]["reviewed"][0]["cost"], data["reviews"]["unlinked"]), (1.0, 0.0))

    def test_a_mapped_session_counts_for_its_ticket_and_rules_still_win(self):
        rows = [session(1, repo="tools"), session(2, ["ABC-9"]), session(3, repo="tools")]
        data = self.collect(rows, mapped=["s1", "abc-1", "s2", "ABC-2"])
        self.assertEqual(sorted(t.key for t in data["tickets"]), ["ABC-1", "ABC-9"])
        self.assertEqual([r["id"] for r in data["unmapped"]], ["s3"])

    def test_no_session_is_dropped(self):
        rows = [session(1, ["ABC-1"]), session(2, edits=False), session(3, repo="tools")]
        data = self.collect(rows)
        self.assertAlmostEqual(sum(g["cost"] for g in w.groups(data).values()), data["total"])
        self.assertEqual(data["measures"]["cache_hit"], 0.8)

    def test_start_asks_for_a_ticket_only_on_a_branch_without_a_key(self):
        dev, w.DEV = w.DEV, Path(tempfile.mkdtemp())
        repo = w.DEV / "api"
        try:
            w.KEY, w.PREFIXES, w.JIRA_PREFIXES = re.compile(r"\b(?:ABC)-\d+\b", re.I), "ABC", ["ABC"]
            w.subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            self.assertIn("ask once", w.start({"cwd": str(repo)})["hookSpecificOutput"]["additionalContext"])
            w.subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "abc-12-export"], check=True)
            self.assertIsNone(w.start({"cwd": str(repo)}))
            w.PREFIXES = ""
            self.assertIsNone(w.start({"cwd": str(repo)}))
        finally:
            w.subprocess.run(["rm", "-rf", str(w.DEV)])
            w.DEV = dev

    def test_month_before_keeps_the_day_or_takes_the_last(self):
        self.assertEqual((w.month_before("2026-11-23"), w.month_before("2026-03-31")), ("2026-10-23", "2026-02-28"))


if __name__ == "__main__":
    unittest.main()
