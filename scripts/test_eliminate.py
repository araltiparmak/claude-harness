"""Tests for eliminate.py, on a made-up ~/.claude in a temporary folder."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import eliminate as e
import inventory


def skill(folder, description, typed=False):
    folder.mkdir(parents=True)
    extra = "disable-model-invocation: true\n" if typed else ""
    (folder / "SKILL.md").write_text(f"---\nname: {folder.name}\ndescription: {description}\n{extra}---\nBody\n")
    return folder


class Eliminate(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        tmp = Path(folder.name).resolve()  # macOS: /var is a link to /private/var
        claude, mine, private, cache = tmp / ".claude", tmp / "harness", tmp / "private", tmp / "cache"
        self.patch(inventory, SKILLS=claude / "skills", PROJECTS=claude / "projects", SETTINGS=claude / "settings.json",
                   STATE=tmp / ".claude.json", PLUGINS=claude / "plugins")
        self.patch(e, SKILLS=claude / "skills", PROJECTS=claude / "projects", MINE=mine, PRIVATE=private,
                   PROFILE=tmp / ".zshrc", ROOTS=((mine, "own"), (private, "private")))
        links = claude / "skills"
        links.mkdir(parents=True)
        for source in (skill(mine / "skills" / "deck", "x" * 400), skill(private / "skills" / "coach", "x" * 40),
                       skill(cache / "repo" / "pr", "x" * 30), skill(mine / "skills" / "worklog", "x" * 400, typed=True)):
            (links / source.name).symlink_to(source)
        skill(links / "notes", "x" * 20)  # a real folder
        skill(links / "synced" / "org" / "pdf", "x" * 100)
        plugins = claude / "plugins"
        skill(tmp / "fd" / "skills" / "frontend-design", "x" * 200)
        skill(tmp / "cf" / "skills" / "workers", "x" * 200)
        skill(plugins / "synced" / "org" / "productivity~g2" / "skills" / "standup", "x" * 80)
        skill(plugins / "synced" / "org" / "design" / "skills" / "mock", "x" * 80)
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {
            "frontend-design@official": [{"scope": "user", "installPath": str(tmp / "fd")}],
            "cloudflare@cloudflare": [{"scope": "project", "projectPath": "/dev/lab", "installPath": str(tmp / "cf")}],
            "expo@official": [{"scope": "user", "installPath": str(tmp / "cf")}]}}))  # not enabled
        (claude / "settings.json").write_text(json.dumps({"enabledPlugins": {
            "frontend-design@official": True, "expo@official": False, "design@synced": False}}))
        (tmp / ".claude.json").write_text(json.dumps({"mcpServers": {"context": {}},
                                                      "projects": {"/dev/site": {"mcpServers": {"playwright": {}}}}}))
        day = time.strftime("%Y-%m-%d")
        lines = [{"timestamp": f"{day}T09:00:00Z", "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "pr"}},
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "anthropic-skills:pdf"}},
                     {"type": "tool_use", "name": "mcp__context__query", "input": {}}]}},
                 {"timestamp": f"{day}T10:00:00Z", "message": {
                     "content": "<command-name>/frontend-design:frontend-design</command-name>"}},
                 {"timestamp": f"{day}T11:00:00Z", "message": {"content": "<command-name>/pr</command-name>"}}]
        session = claude / "projects" / "-dev-site" / "s1.jsonl"
        session.parent.mkdir(parents=True)
        lines += [{"type": "attachment", "attachment": {"type": "deferred_tools_delta", "addedNames": [
                      "WebSearch", "mcp__claude_ai_Context7__query-docs", "mcp__easel__chart"]}},
                  {"type": "attachment", "attachment": {"type": "mcp_instructions_delta",
                      "addedNames": ["claude.ai Context7"], "addedBlocks": ["x" * 100]}}]
        session.write_text("\n".join(json.dumps(entry) for entry in lines) + "\nnot json\n")
        old = claude / "projects" / "-dev-site" / "old.jsonl"  # older than the period: not read
        old.write_text(json.dumps({"timestamp": "2020-01-01T00:00:00Z", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "deck"}}]}}))
        stamp = time.time() - 200 * 86400
        os.utime(old, (stamp, stamp))
        self.day, self.tmp, self.mine = day, tmp, mine

    def patch(self, module, **values):
        """Sets attributes of a module until the test ends."""
        patcher = mock.patch.multiple(module, **values)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_item_with_its_kind_cost_and_uses_unused_first(self):
        found = {r.name: [r.kind, r.tokens, r.uses, r.last] for r in e.rows(90) if not r.fixed}
        self.assertEqual(found, {
            "deck": ["own", 101, 0, ""], "coach": ["private", 12, 0, ""], "notes": ["local", 7, 0, ""],
            "cloudflare": ["plugin, project /dev/lab", 52, 0, ""], "productivity": ["plugin, account", 22, 0, ""],
            "playwright": ["mcp, local, /dev/site", None, 0, ""],
            "pr": ["external", 8, 2, self.day], "pdf": ["account", 26, 1, self.day],
            "frontend-design": ["plugin", 54, 1, self.day], "context": ["mcp, user", None, 1, self.day],
            "claude.ai Context7": ["mcp, claude.ai", 34, 0, ""], "easel": ["mcp, other", 5, 0, ""]})
        self.assertEqual([r.name for r in e.rows(90)][:3], ["cloudflare", "productivity", "frontend-design"])

    def test_a_plugins_skills_are_listed_under_skills_and_go_only_with_the_plugin(self):
        found = e.rows(90)
        mine = [r for r in found if r.fixed]
        self.assertEqual({(r.name, r.kind) for r in mine}, {("frontend-design", "via plugin frontend-design"),
                                                          ("workers", "via plugin cloudflare"),
                                                          ("standup", "via plugin productivity")})
        self.assertEqual([r.section for r in found], sorted((r.section for r in found), key=e.SECTIONS.index))
        listed = e.table(found, 90)
        for section in e.SECTIONS:
            self.assertIn(f"== {section}:", listed)
        self.assertRegex(listed, r"\n  -  workers +via plugin cloudflare")
        with self.assertRaisesRegex(SystemExit, "workers: comes via plugin cloudflare; remove that plugin instead"):
            e.remove(found, ["deck", "workers"])  # nothing changes, deck included
        self.assertFalse((self.tmp / ".zshrc").exists())

    def test_remove_by_name_takes_the_plugin_not_its_skill_of_the_same_name(self):
        done = []
        self.patch(e, apply=done.extend)
        e.remove(e.rows(90), ["frontend-design", "playwright"])
        self.assertEqual([(r.name, r.kind) for r in done], [("frontend-design", "plugin"),
                                                            ("playwright", "mcp, local, /dev/site")])

    def test_each_row_says_whether_it_loads_everywhere_or_in_one_project(self):
        found = {r.name + (" via" if r.fixed else ""): (e.kind_label(r), e.scope(r)) for r in e.rows(90)}
        self.assertEqual(found["deck"], ("own", "global"))
        self.assertEqual(found["cloudflare"], ("plugin", "project /dev/lab"))
        self.assertEqual(found["workers via"], ("via plugin cloudflare", "project /dev/lab"))  # its plugin's
        self.assertEqual(found["playwright"], ("mcp, local", "project /dev/site"))
        self.assertEqual(found["context"], ("mcp, user", "global"))

    def test_a_folded_description_counts_whole(self):
        file = self.tmp / "SKILL.md"
        file.write_text("---\nname: abc\ndescription: >\n  " + "x" * 20 + "\n  " + "y" * 20 + "\n---\n")
        self.assertEqual(inventory.tokens(file), -(-(3 + 41) // 4))

    def test_the_table_totals_what_removing_the_unused_saves(self):
        self.assertIn("8 of 12 unused in the last 90 days; removing them saves about 233 tokens",
                      e.table(e.rows(90), 90))

    def test_skip_skills_extends_the_profile_line_or_adds_one(self):
        self.assertEqual(e.skip_skills(["deck"]), "deck")
        self.assertIn('export SKIP_SKILLS="deck"', (self.tmp / ".zshrc").read_text())
        self.assertEqual(e.skip_skills(["pr", "deck"]), "deck pr")
        self.assertEqual((self.tmp / ".zshrc").read_text().count("SKIP_SKILLS="), 1)

    def test_a_plugin_is_turned_off_in_the_repo_settings(self):
        settings = self.mine / "claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"model": "opus", "enabledPlugins": {"fd@official": True}}, indent=2) + "\n")
        self.assertEqual(e.disable_plugins(["fd@official", "design@synced"]), settings)
        self.assertEqual(json.loads(settings.read_text())["enabledPlugins"],
                         {"fd@official": False, "design@synced": False})

    def test_each_kind_has_its_way_out(self):
        steps = {r.name: e.plan(r) for r in e.rows(90) if not r.fixed}
        self.assertEqual(e.plan(next(r for r in e.rows(90) if r.name == "workers"))[0],
                         "remove the plugin cloudflare")
        self.assertEqual(steps["deck"][0], "add to SKIP_SKILLS in ~/.zshrc")
        self.assertEqual(steps["cloudflare"][0], "claude plugin disable cloudflare@cloudflare --scope project (in /dev/lab)")
        self.assertEqual(steps["playwright"][0], "claude mcp remove playwright -s local (in /dev/site)")
        self.assertTrue(steps["claude.ai Context7"][0].startswith("by hand: disconnect it on claude.ai"))
        self.assertIsNone(steps["claude.ai Context7"][2])
        e.plan(next(r for r in e.rows(90) if r.name == "notes"))[2]()  # a real folder is moved aside
        self.assertTrue((self.tmp / ".claude" / "skills.off" / "notes" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
