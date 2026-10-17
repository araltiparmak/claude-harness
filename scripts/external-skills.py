#!/usr/bin/env python3
"""Read external-skills.yaml and print one line per skill: URL<TAB>NAME.

The file is plain YAML in one shape only, so no YAML library is needed:

    https://github.com/owner/repo:    # a repo: its https URL as a key
      - skill-name                    # the skills to link from it, by SKILL.md name

On any other line, a skill before its repo, a repo with no skills, or a name or repo
listed twice, it prints every problem with its line number and exits 1.

Usage: external-skills.py FILE
"""
import re
import sys

REPO = re.compile(r"(https://[^\s/]+/[^\s/]+/[^\s/:]+?)(\.git)?:")
SKILL = re.compile(r"\s+- ([a-z0-9]+(?:-[a-z0-9]+)*)")


def main(path):
    problems, pairs, names, repos = [], [], set(), {}
    url = None
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = re.sub(r"(^|\s)#.*", "", raw).rstrip()
        if not line:
            continue
        if m := REPO.fullmatch(line):
            url = m.group(1)
            if url in repos:
                problems.append(f"{path}:{n}: {url} is listed twice")
            repos[url] = 0
        elif m := SKILL.fullmatch(line):
            name = m.group(1)
            if url is None:
                problems.append(f"{path}:{n}: skill '{name}' comes before any repo URL")
                continue
            if name in names:
                problems.append(f"{path}:{n}: '{name}' is listed twice")
            names.add(name)
            repos[url] += 1
            pairs.append((url, name))
        else:
            problems.append(f"{path}:{n}: neither 'https://host/owner/repo:' nor '  - skill-name': {raw.rstrip()}")
    problems += [f"{path}: {u} lists no skills" for u, count in repos.items() if count == 0]
    if problems:
        sys.exit("\n".join(problems))
    for url, name in pairs:
        print(f"{url}\t{name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
