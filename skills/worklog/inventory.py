"""What loads into every Claude Code session: the skills, plugins and MCP servers, and the tokens each one adds.

Tokens are what an item adds to every session: a skill's name and description (about 4 characters per token), a
plugin's skills, agents and commands, an MCP server's tool names and instructions as the newest transcript recorded
them. A skill with disable-model-invocation: true adds nothing and is left out. A server the newest transcript did
not load (a local one of another project) has no cost (None).

Kinds: a skill is "own", "private" or "external" (by the roots items() is given), "local" or "account"; a plugin
is "plugin", "plugin, project" or "plugin, account"; an MCP server is "mcp, user", "mcp, local", "mcp, claude.ai"
or "mcp, other"; a skill a plugin brings is VIA + its plugin's name. A project plugin, a local server and a
project plugin's skills name their folder in Item.project.

worklog.py reads it for the Misc box; claude-harness's scripts/eliminate.py reads it to remove items.
"""
import json
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple, Optional

HOME = Path.home()
CLAUDE = HOME / ".claude"
SKILLS = CLAUDE / "skills"
PROJECTS = CLAUDE / "projects"
SETTINGS = CLAUDE / "settings.json"
STATE = HOME / ".claude.json"  # MCP servers of the user and local scopes
PLUGINS = CLAUDE / "plugins"
VIA = "via plugin "  # the kind of a skill a plugin brings, before the plugin's name


class Item(NamedTuple):
    """One thing that adds to the context."""
    name: str
    kind: str
    tokens: Optional[int]  # what it adds to every session; None when not measured
    ref: str  # what removing it names: the skill, the plugin id, or the server; "" for a plugin's skill
    project: str  # the folder whose sessions load it; "" for every session
    names: set  # the usage names a use of it counts under (counts_for)


class Plugin(NamedTuple):
    """One enabled plugin."""
    name: str
    kind: str  # plugin, plugin, project, or plugin, account (synced from claude.ai)
    root: Path
    id: str
    project: str  # the folder a project plugin is installed for; "" for every session


def front(file):
    """The front matter of a Markdown file as {key: text}; a block value (> or |) joins its indented lines."""
    lines = file.read_text(errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    found, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"([\w-]+):\s*(.*)", line)
        if match and not line[0].isspace():
            key, value = match[1], match[2].strip()
            found[key] = "" if value in (">", "|", ">-", "|-") else value.strip("'\"")
        elif key and line.strip():
            found[key] = (found[key] + " " + line.strip()).strip()
    return found


def tokens(file):
    """What one skill, agent or command adds to every session; 0 when only typing its name starts it."""
    meta = front(file)
    if meta.get("disable-model-invocation", "").lower() == "true":
        return 0
    text = meta.get("name", file.parent.name) + meta.get("description", "") + meta.get("when_to_use", "")
    return -(-len(text) // 4)


def kind_of(link, roots):
    """local for a real folder in ~/.claude/skills; for a link, the kind of the first of roots ((folder, kind), ...)
    that holds its target, else external."""
    if not link.is_symlink():
        return "local"
    real = link.resolve()
    for root, kind in roots:
        if root == real or root in real.parents:
            return kind
    return "external"


def skills(roots=()):
    """{name: (kind, tokens)} of the skills in ~/.claude/skills, the synced account skills included."""
    found = {}
    for entry in sorted(SKILLS.iterdir()) if SKILLS.is_dir() else []:
        if (entry / "SKILL.md").is_file():
            found[entry.name] = (kind_of(entry, roots), tokens(entry / "SKILL.md"))
    for file in sorted(SKILLS.glob("synced/*/*/SKILL.md")):
        found.setdefault(file.parent.name, ("account", tokens(file)))
    return found


def plugin_tokens(root):
    return sum(tokens(f) for pattern in ("skills/*/SKILL.md", "agents/*.md", "commands/*.md")
               for f in root.glob(pattern))


def plugins():
    """The enabled plugins: the installed ones that enabledPlugins turns on (a project one counts as enabled in its
    project), then the ones synced from claude.ai, unless enabledPlugins turns them off."""
    enabled = load(SETTINGS).get("enabledPlugins", {})
    found = {}
    for plugin_id, installs in load(PLUGINS / "installed_plugins.json").get("plugins", {}).items():
        for install in installs:
            project = install.get("projectPath") or ""
            if project or enabled.get(plugin_id):
                name = plugin_id.split("@")[0]
                found[name] = Plugin(name, "plugin, project" if project else "plugin", Path(install["installPath"]),
                                     plugin_id, project)
    for root in sorted(p for p in PLUGINS.glob("synced/*/*") if p.is_dir()):
        name = root.name.split("~")[0]
        if enabled.get(f"{name}@synced", True) and name not in found:
            found[name] = Plugin(name, "plugin, account", root, f"{name}@synced", "")
    return list(found.values())


def plugin_skills():
    """An Item per skill the enabled plugins bring that adds to every session, in its plugin's project. Its tokens
    already count under its plugin, and it leaves only with the plugin, so items() leaves it out."""
    return [Item(file.parent.name, VIA + p.name, tokens(file), "", p.project, {f"{p.name}:{file.parent.name}"})
            for p in plugins() for file in sorted(p.root.glob("skills/*/SKILL.md")) if tokens(file)]


def servers():
    """{name: (scope, tokens or None, project path or "")} of the MCP servers: the user and local ones in
    ~/.claude.json, and every server the newest session loaded (claude.ai connectors and servers of plugins and
    mods), with what it added."""
    state = load(STATE)
    found = {name: ("user", "") for name in state.get("mcpServers", {})}
    for project, config in state.get("projects", {}).items():
        for name in config.get("mcpServers", {}):
            found.setdefault(name, ("local", project))
    costs = loaded()
    for name in costs:
        found.setdefault(name, ("claude.ai" if name.startswith("claude_ai_") else "other", ""))
    return {name: (scope, costs.get(name), project) for name, (scope, project) in found.items()}


def loaded():
    """{server: tokens} of the newest session that loaded MCP servers: its deferred tool names (mcp__<server>__<tool>)
    and its instructions block. A server shows by name in tools and by title in instructions ("claude.ai Context7"
    for claude_ai_Context7)."""
    sessions = sorted(PROJECTS.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True) \
        if PROJECTS.is_dir() else []
    for file in sessions:
        chars = Counter()
        for added in attachments(file):
            chars.update(server_chars(added))
        if chars:
            return {name: -(-n // 4) for name, n in chars.items()}
    return {}


def attachments(file):
    """The deferred-tool and MCP-instruction attachments of one transcript."""
    for line in file.read_text(errors="replace").splitlines():
        if '"deferred_tools_delta"' in line or '"mcp_instructions_delta"' in line:
            try:
                yield json.loads(line).get("attachment") or {}
            except ValueError:
                continue


def server_chars(added):
    """{server: characters} one attachment adds to the context."""
    chars = Counter()
    if added.get("type") == "deferred_tools_delta":
        for name in added.get("addedNames", []):
            if name.startswith("mcp__"):
                chars[name.split("__")[1]] += len(name) + 1
    elif added.get("type") == "mcp_instructions_delta":
        for title, block in zip(added.get("addedNames", []), added.get("addedBlocks", [])):
            chars[re.sub(r"\W", "_", title)] += len(block)
    return chars


def short(path):
    """A path with ~ for the home folder."""
    return "~" + path[len(str(HOME)):] if path.startswith(str(HOME)) else path


def load(file):
    try:
        return json.loads(file.read_text())
    except (OSError, ValueError):
        return {}


def items(roots=()):
    """An Item per skill, plugin and MCP server that adds to the context, in that order. Usage names: a skill by its
    name (an account skill also as plugin:name), a plugin's items as plugin:item and its servers as
    mcp:plugin_<plugin>_..., a server as mcp:<server>. A usage name ending in : or _ is a prefix."""
    found = [Item(name, kind, cost, name, "", {name} | ({":" + name} if kind == "account" else set()))
             for name, (kind, cost) in skills(roots).items() if cost]
    found += [Item(p.name, p.kind, plugin_tokens(p.root), p.id, p.project, {p.name + ":", f"mcp:plugin_{p.name}_"})
              for p in plugins()]
    for name, (scope, cost, project) in servers().items():
        title = "claude.ai " + name[len("claude_ai_"):].replace("_", " ") if scope == "claude.ai" else name
        found.append(Item(title, f"mcp, {scope}", cost, name, project, {"mcp:" + name}))
    return found


def counts_for(names, uses):
    """The uses (a Counter of usage names) that count for one item's usage names."""
    def hit(used):
        return any(used == n or (n.endswith((":", "_")) and used.startswith(n)) or
                   (n.startswith(":") and used.endswith(n)) for n in names)
    return [u for u in uses if hit(u)]
