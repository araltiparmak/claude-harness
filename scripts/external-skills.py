#!/usr/bin/env python3
"""Skills from other repos, listed in the repo's external-skills.yaml.

The file is plain YAML in one shape only, so no YAML library is needed:

    https://github.com/owner/repo:    # a repo: its https URL as a key
      - skill-name                    # the skills to link from it, by SKILL.md name

Usage:
    external-skills.py            check the file, then print URL<TAB>NAME for every skill
    external-skills.py resolve    print NAME<TAB>DIR for every skill in the cloned repos, found
                                  by the `name:` in its SKILL.md, and delete the clones of
                                  repos the file no longer lists

update.sh clones and pulls the repos between the two calls. A problem in the file is printed
with its line number, and the exit code is 1.
"""
import os
import re
import shutil
import sys
from pathlib import Path

LIST = Path(__file__).resolve().parent.parent / "external-skills.yaml"
# Same folder as CACHE in update.sh.
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "claude-harness" / "repos"
REPO = re.compile(r"(https://[^\s/]+/[^\s/]+/[^\s/:]+?)(\.git)?:")
SKILL = re.compile(r"\s+- ([a-z0-9]+(?:-[a-z0-9]+)*)")


def parse_line(line, url, repos, seen):
    """Apply one line to repos; return (url now in effect, problem or None)."""
    if m := REPO.fullmatch(line):
        new = m.group(1)
        problem = f"{new} is listed twice" if new in repos else None
        repos[new] = []
        return new, problem
    m = SKILL.fullmatch(line)
    if not m:
        return url, f"neither 'https://host/owner/repo:' nor '  - skill-name': {line.strip()}"
    name = m.group(1)
    if url is None:
        return url, f"skill '{name}' comes before any repo URL"
    repos[url].append(name)
    if name in seen:
        return url, f"'{name}' is listed twice"
    seen.add(name)
    return url, None


def read_list():
    """Return {url: [skill names]}, or exit listing every problem in the file."""
    repos, seen, problems, url = {}, set(), [], None
    for n, raw in enumerate(LIST.open(encoding="utf-8"), 1):
        line = re.sub(r"(^|\s)#.*", "", raw).rstrip()
        if line:
            url, problem = parse_line(line, url, repos, seen)
            if problem:
                problems.append(f"{LIST}:{n}: {problem}")
    problems += [f"{LIST}: {u} lists no skills" for u, names in repos.items() if not names]
    if problems:
        sys.exit("\n".join(problems))
    return repos


def clone_dir(url):
    return CACHE / url.removeprefix("https://")


def skill_name(skill_md):
    """The `name:` in a SKILL.md's front matter, or None."""
    lines = skill_md.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("name: "):
            return line.removeprefix("name: ").strip()
    return None


def skills_in(root):
    """{name: folder} for every SKILL.md in a clone; the first one wins a name."""
    found = {}
    for md in sorted(root.rglob("SKILL.md")):
        if ".git" not in md.relative_to(root).parts:
            found.setdefault(skill_name(md), md.parent)
    return found


def resolve(repos):
    for url, names in repos.items():
        root = clone_dir(url)
        if not (root / ".git").is_dir():
            continue  # update.sh has already reported the failed clone
        found = skills_in(root)
        for name in names:
            if name in found:
                print(f"{name}\t{found[name]}")
            else:
                print(f"warn: {url} has no skill named {name}", file=sys.stderr)
    prune(repos)


def prune(repos):
    """Delete the clones of repos the list no longer names."""
    listed = {clone_dir(u) for u in repos}
    for git in sorted(CACHE.glob("*/*/*/.git")):
        if git.parent not in listed:
            shutil.rmtree(git.parent)
            print(f"removed clone {git.parent.relative_to(CACHE)}", file=sys.stderr)


def main(args):
    repos = read_list()
    if args == ["resolve"]:
        resolve(repos)
    elif not args:
        for url, names in repos.items():
            for name in names:
                print(f"{url}\t{name}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
