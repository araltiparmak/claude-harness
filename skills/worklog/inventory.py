"""What loads into every Claude Code session: the skills, plugins and MCP servers, and the tokens each one adds.

Tokens are what an item adds to every session: a skill's name and description (about 4 characters per token), a
plugin's skills, agents and commands, an MCP server's tool names and instructions as the newest transcript recorded
them. A skill with disable-model-invocation: true adds nothing and is left out. A server the newest transcript did
not load (a local one of another project) has no cost (None).

worklog.py reads it for the Misc box; claude-harness's scripts/eliminate.py reads it to remove items.
"""
import json
import re
from collections import Counter
from pathlib import Path

HOME = Path.home()
CLAUDE = HOME / ".claude"
SKILLS = CLAUDE / "skills"
PROJECTS = CLAUDE / "projects"
SETTINGS = CLAUDE / "settings.json"
STATE = HOME / ".claude.json"  # MCP servers of the user and local scopes
PLUGINS = CLAUDE / "plugins"


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
    """{name: (kind, tokens, id, project path or "")} of the enabled plugins: installed ones (project ones count as
    enabled in their project) and the ones synced from claude.ai, unless enabledPlugins turns them off."""
    enabled = load(SETTINGS).get("enabledPlugins", {})
    found = installed_plugins(enabled)
    for root in sorted(p for p in PLUGINS.glob("synced/*/*") if p.is_dir()):
        name = root.name.split("~")[0]
        if enabled.get(f"{name}@synced", True) and name not in found:
            found[name] = ("plugin, account", plugin_tokens(root), f"{name}@synced", "")
    return found


def installed_plugins(enabled):
    """plugins() for the plugins in installed_plugins.json."""
    found = {}
    for plugin_id, installs in load(PLUGINS / "installed_plugins.json").get("plugins", {}).items():
        for install in installs:
            project = install.get("projectPath")
            if project or enabled.get(plugin_id):
                where = f"plugin, project {short(project)}" if project else "plugin"
                found[plugin_id.split("@")[0]] = (where, plugin_tokens(Path(install["installPath"])), plugin_id,
                                                  project or "")
    return found


def servers():
    """{name: (scope, tokens or None, project path or "")} of the MCP servers: the user and local ones in
    ~/.claude.json, and every server the newest session loaded (claude.ai connectors and servers of plugins and mods), with what it added."""
    state = load(STATE)
    found = {name: ("user", "") for name in state.get("mcpServers", {})}
    for project, config in state.get("projects", {}).items():
        for name in config.get("mcpServers", {}):
            found.setdefault(name, (f"local, {short(project)}", project))
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
    """[name, kind, tokens or None, ref, project path, usage names] per item that adds to the context. ref is what
    removing it names (the skill, the plugin id, the server); usage names are the names a use of it is counted
    under: a skill by its name (an account skill also as plugin:name), a plugin's items as plugin:item and its
    servers as mcp:plugin_<plugin>_..., a server as mcp:<server>. A usage name ending in : or _ is a prefix."""
    found = []
    for name, (kind, cost) in skills(roots).items():
        if cost:
            found.append([name, kind, cost, name, "", {name} | ({":" + name} if kind == "account" else set())])
    for name, (kind, cost, plugin_id, project) in plugins().items():
        found.append([name, kind, cost, plugin_id, project, {name + ":", f"mcp:plugin_{name}_"}])
    for name, (scope, cost, project) in servers().items():
        title = "claude.ai " + name[len("claude_ai_"):].replace("_", " ") if scope == "claude.ai" else name
        found.append([title, f"mcp, {scope}", cost, name, project, {"mcp:" + name}])
    return found


def counts_for(names, uses):
    """The uses (a Counter of usage names) that count for one item's usage names."""
    def hit(used):
        return any(used == n or (n.endswith((":", "_")) and used.startswith(n)) or
                   (n.startswith(":") and used.endswith(n)) for n in names)
    return [u for u in uses if hit(u)]
