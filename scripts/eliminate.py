#!/usr/bin/env python3
"""Eliminate the non-essential: what loads into every Claude Code session, how often you used it, and a checklist
to take items out of Claude's context.

  scripts/eliminate.py [DAYS]   a checklist of every skill, plugin and MCP server, unused ones first and the most
                                expensive first, from the transcripts of the last DAYS days (default 90); pick
                                items, confirm, and it removes them
  scripts/eliminate.py --list [DAYS]
                                prints the same rows as a table and changes nothing

Tokens and kinds come from skills/worklog/inventory.py, which worklog's Misc box reads too.

Kinds, and how each is removed (REMOVE):
  own, private, external   named in SKIP_SKILLS in ~/.zshrc, then update.sh unlinks it; the source stays
  local                    a real folder in ~/.claude/skills, moved to ~/.claude/skills.off
  account                  a claude.ai skill: switched off on claude.ai, one by one (printed, not done)
  plugin, plugin, account  false under enabledPlugins in claude/settings.json, then update.sh
  plugin, project <path>   claude plugin disable --scope project, run in that project
  mcp, user                claude mcp remove -s user
  mcp, local, <path>       claude mcp remove -s local, run in that project
  mcp, claude.ai           a connector: claude.ai or /mcp (printed, not done)
  mcp, other               added by a plugin or mod: /mcp (printed, not done)
"""
import curses
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "worklog"))
import inventory  # noqa: E402  (worklog's inventory.py: skills, plugins and MCP servers, and their tokens)
from inventory import HOME, PROJECTS, SKILLS, load, short  # noqa: E402

MINE = HERE.parent  # this repo
PRIVATE = Path(os.environ.get("PRIVATE_DIR", HOME / "dev" / "private-skills")).expanduser().resolve()
ROOTS = ((MINE, "own"), (PRIVATE, "private"))

COMMAND = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
HINT = re.compile(r'"Skill"|"Agent"|"Task"|mcp__|<command-name>')  # lines worth parsing


def usage(days):
    """(uses, last day) per name, from the transcripts of the last days: skills by Skill call or slash command,
    agents by subagent type, MCP servers by their tools. A plugin's items count under plugin:item."""
    since = time.time() - days * 86400
    uses, last = Counter(), {}
    for file in PROJECTS.rglob("*.jsonl") if PROJECTS.is_dir() else []:
        if file.stat().st_mtime < since:
            continue
        for line in file.read_text(errors="replace").splitlines():
            if not HINT.search(line):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            day = entry.get("timestamp", "")[:10]
            content = (entry.get("message") or {}).get("content")
            names = []
            for block in content if isinstance(content, list) else [{"type": "text", "text": content or ""}]:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool, args = block.get("name", ""), block.get("input") or {}
                    if tool == "Skill":
                        names.append(args.get("skill", ""))
                    elif tool in ("Agent", "Task"):
                        names.append(args.get("subagent_type", ""))
                    elif tool.startswith("mcp__"):
                        names.append("mcp:" + tool.split("__")[1])
                elif block.get("type") == "text":
                    names += COMMAND.findall(block.get("text", ""))
            for name in filter(None, names):
                uses[name] += 1
                last[name] = max(last.get(name, ""), day)
    return uses, last


def rows(days):
    """[name, kind, tokens or None, uses, last day, ref, project path] per item, unused first, then by tokens. ref
    is what removing it names: the skill, the plugin id, or the server."""
    uses, last = usage(days)
    found = []
    for name, kind, cost, ref, project, names in inventory.items(ROOTS):
        hits = inventory.counts_for(names, uses)
        found.append([name, kind, cost, sum(uses[h] for h in hits), max((last[h] for h in hits), default=""),
                      ref, project])
    return sorted(found, key=lambda r: (r[3] > 0, -(r[2] or 0), r[0]))


def line(row, width=200):
    name, kind, cost, n, day = row[:5]
    text = f"{name:<30.30} {kind:<36.36} {'?' if cost is None else cost:>6} {n:>5}  {day or '-'}"
    return text[:width]


def summary(found, days):
    unused = [r for r in found if not r[3]]
    return (f"{len(unused)} of {len(found)} unused in the last {days} days; removing them saves about "
            f"{sum(r[2] or 0 for r in unused)} tokens per session (? is not measured; /context shows it).")


def table(found, days):
    head = f"{'#':>3}  {'name':<30} {'kind':<36} {'tokens':>6} {'uses':>5}  last used"
    return "\n".join([head] + [f"{i:>3}  {line(r)}" for i, r in enumerate(found, 1)] + ["", summary(found, days)])


def pick(found, days):
    """The rows chosen in a full-screen checklist; [] when the user quits."""
    def run(screen):
        curses.curs_set(0)
        chosen, at, top = set(), 0, 0
        while True:
            height, width = screen.getmaxyx()
            rows_shown = max(1, height - 4)
            top = min(max(top, at - rows_shown + 1), at)
            saved = sum(found[i][2] or 0 for i in chosen)
            screen.erase()
            screen.addnstr(0, 0, f"eliminate: {summary(found, days)}", width - 1, curses.A_BOLD)
            screen.addnstr(1, 0, f"      {'name':<30} {'kind':<36} {'tokens':>6} {'uses':>5}  last used  "
                                 f"(selected {len(chosen)}, saves {saved})", width - 1, curses.A_UNDERLINE)
            for y, i in enumerate(range(top, min(len(found), top + rows_shown)), 2):
                mark = "[x]" if i in chosen else "[ ]"
                style = (curses.A_REVERSE if i == at else 0) | (curses.A_DIM if found[i][3] else 0)
                screen.addnstr(y, 0, f"{'>' if i == at else ' '} {mark} {line(found[i])}", width - 1, style)
            screen.addnstr(height - 1, 0, "up/down move  space select  a all unused  n none  enter apply  q quit",
                           width - 1, curses.A_DIM)
            key = screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                at = max(0, at - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                at = min(len(found) - 1, at + 1)
            elif key == curses.KEY_PPAGE:
                at = max(0, at - rows_shown)
            elif key == curses.KEY_NPAGE:
                at = min(len(found) - 1, at + rows_shown)
            elif key == ord(" "):
                chosen ^= {at}
                at = min(len(found) - 1, at + 1)
            elif key == ord("a"):
                chosen |= {i for i, r in enumerate(found) if not r[3]}
            elif key == ord("n"):
                chosen.clear()
            elif key in (curses.KEY_ENTER, 10, 13):
                return [found[i] for i in sorted(chosen)]
            elif key in (ord("q"), 27):
                return []
    return curses.wrapper(run)


PROFILE = HOME / ".zshrc"
SKIP = re.compile(r'^export SKIP_SKILLS="([^"]*)"', re.M)
MANUAL = {
    "account": "switch it off on claude.ai (Settings, Capabilities); all of them at once: "
               '"syncClaudeAiSkills": false in claude/settings.json',
    "mcp, claude.ai": "disconnect it on claude.ai (Settings, Connectors), which also removes it from claude.ai "
                      "chats; or /mcp in one folder; or every connector with "
                      '"disableClaudeAiConnectors": true in claude/settings.json',
    "mcp, other": "it comes from a plugin or mod: disable that, or /mcp in one folder",
}


def plan(row):
    """(what removing a row does, the undo, a function that does it or None when it is manual)."""
    name, kind, ref, project = row[0], row[1], row[5], row[6]
    if kind in ("own", "private", "external"):
        return "add to SKIP_SKILLS in ~/.zshrc", "take it out of SKIP_SKILLS, run update.sh", None
    if kind == "local":
        return f"move to {SKILLS.parent / 'skills.off' / name}", "move it back", lambda: shelve(name)
    if kind in ("plugin", "plugin, account"):
        return f'"{ref}": false in claude/settings.json', "set it to true, run update.sh", None
    if kind.startswith("plugin, project"):
        return (f"claude plugin disable {ref} --scope project (in {short(project)})", "claude plugin enable",
                lambda: claude(["plugin", "disable", ref, "--scope", "project"], project))
    if kind == "mcp, user":
        return f"claude mcp remove {ref} -s user", "claude mcp add it again", \
            lambda: claude(["mcp", "remove", ref, "-s", "user"], str(HOME))
    if kind.startswith("mcp, local"):
        return (f"claude mcp remove {ref} -s local (in {short(project)})", "claude mcp add it again",
                lambda: claude(["mcp", "remove", ref, "-s", "local"], project))
    return "by hand: " + MANUAL[kind], "", None


def shelve(name):
    (SKILLS.parent / "skills.off").mkdir(exist_ok=True)
    (SKILLS / name).rename(SKILLS.parent / "skills.off" / name)


def claude(args, cwd):
    subprocess.run(["claude", *args], cwd=cwd, check=True)


def skip_skills(names):
    """Adds names to the export SKIP_SKILLS line of ~/.zshrc (adding the line when missing); the new list."""
    text = PROFILE.read_text() if PROFILE.exists() else ""
    found = SKIP.search(text)
    words = (found[1] if found else os.environ.get("SKIP_SKILLS", "")).split()
    words += [n for n in names if n not in words]
    new = f'export SKIP_SKILLS="{" ".join(words)}"'
    if found:
        text = text[:found.start()] + new + text[found.end():]
    else:
        text += f"\n# Skills update.sh leaves out of ~/.claude/skills (scripts/eliminate.py adds to it)\n{new}\n"
    PROFILE.write_text(text)
    return " ".join(words)


def settings_file():
    """The settings file that holds enabledPlugins: the private overlay when it sets them, else this repo's."""
    private = PRIVATE / "claude" / "settings.json"
    return private if "enabledPlugins" in load(private) else MINE / "claude" / "settings.json"


def disable_plugins(ids):
    file = settings_file()
    data = json.loads(file.read_text())
    data.setdefault("enabledPlugins", {}).update({i: False for i in ids})
    file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return file


def apply(chosen):
    """Removes the chosen rows; prints each step, the undo, and what is left to do by hand."""
    skills_out = [r[0] for r in chosen if r[1] in ("own", "private", "external")]
    plugins_out = [r[5] for r in chosen if r[1] in ("plugin", "plugin, account")]
    by_hand = []
    for row in chosen:
        does, undo, step = plan(row)
        if step:
            try:
                step()
                print(f"done   {row[0]}: {does} (undo: {undo})")
            except (OSError, subprocess.CalledProcessError) as err:
                print(f"FAILED {row[0]}: {does} ({err})")
        elif does.startswith("by hand"):
            by_hand.append(f"  {row[0]}: {does[len('by hand: '):]}")
    env = dict(os.environ)
    if skills_out:
        env["SKIP_SKILLS"] = skip_skills(skills_out)
        print(f"done   {', '.join(skills_out)}: added to SKIP_SKILLS in {short(str(PROFILE))} "
              "(undo: take them out, run update.sh)")
    if plugins_out:
        file = disable_plugins(plugins_out)
        print(f"done   {', '.join(plugins_out)}: false under enabledPlugins in {short(str(file))} "
              "(undo: set them to true, run update.sh)")
    if skills_out or plugins_out:
        print("\n== update.sh")
        subprocess.run([str(MINE / "scripts" / "update.sh")], env=env, check=False)
    if by_hand:
        print("\nLeft for you, which no command can do one by one:\n" + "\n".join(by_hand))
    print("\nNew sessions start without what was removed; open shells see SKIP_SKILLS after: source ~/.zshrc")


def main(args):
    listing = args[:1] == ["--list"]
    args = args[1:] if listing else args
    if len(args) > 1 or (args and not args[0].isdigit()):
        sys.exit(__doc__)
    days = int(args[0]) if args else 90
    found = rows(days)
    if listing or not sys.stdout.isatty():
        print(table(found, days))
        return
    chosen = pick(found, days)
    if not chosen:
        print("Nothing chosen; nothing changed.")
        return
    print("Remove from Claude's context:")
    for row in chosen:
        print(f"  {row[0]:<30} {plan(row)[0]}")
    if input(f"\nRemove these {len(chosen)}? [y/N] ").strip().lower() == "y":
        apply(chosen)
    else:
        print("Nothing changed.")


if __name__ == "__main__":
    main(sys.argv[1:])
