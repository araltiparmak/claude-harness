#!/usr/bin/env bash
set -euo pipefail

# Checks the repo is consistent. Runs in CI on every push and pull request, and
# locally with scripts/check.sh. Prints every problem, then exits 1 if any.

cd "$(dirname "$0")/.."
fail=0
problem() { echo "FAIL: $*"; fail=1; }

# Every skill: SKILL.md with front matter, name matching the folder, a description.
# A folder with SKILL.md is a skill, at any depth; a folder without one is a group holding skills.
skills=(); skill_dirs=()
while IFS= read -r file; do
  dir="$(dirname "$file")"
  inside=0
  for parent in ${skill_dirs[@]+"${skill_dirs[@]}"}; do case "$dir/" in "$parent"/*) inside=1 ;; esac; done
  [ "$inside" = 0 ] || continue   # a SKILL.md nested in a skill (an example) is not a skill
  name="$(basename "$dir")"
  skills+=("$name"); skill_dirs+=("$dir")
  [ "$(head -1 "$file")" = "---" ] || problem "$name: SKILL.md does not start with front matter"
  awk 'NR>1 && /^---$/ {found=1; exit} END {exit !found}' "$file" || problem "$name: front matter has no closing ---"
  front="$(awk 'NR==1{next} /^---$/{exit} {print}' "$file")"
  grep -qx "name: $name" <<<"$front" || problem "$name: front matter name is not '$name'"
  grep -qE '^description: .+' <<<"$front" || problem "$name: front matter has no description"
done < <(find skills -name SKILL.md | sort)
dupes="$(printf '%s\n' "${skills[@]}" | sort | uniq -d)"
[ -z "$dupes" ] || problem "skill names must be unique across groups: $dupes"
# Every folder directly under skills/ is a skill or a group with a skill somewhere inside.
for dir in skills/*/; do
  dir="${dir%/}"
  if [ -z "$(find "$dir" -name SKILL.md | head -1)" ]; then
    problem "$dir: not a skill (no SKILL.md) and not a group (no skill inside)"
  fi
done

# README's skill table lists exactly the skills, and every link in it resolves.
listed="$(grep -oE '^\| \[[a-z0-9-]+\]\(skills/' README.md | sed -E 's/^\| \[([a-z0-9-]+)\].*/\1/' | sort)"
actual="$(printf '%s\n' "${skills[@]}" | sort)"
if [ "$listed" != "$actual" ]; then
  problem "README skill table does not match the skills:"
  diff <(echo "$listed") <(echo "$actual") | sed 's/^/  /' || true
fi
while IFS= read -r path; do
  [ -f "$path" ] || problem "README links to a missing file: $path"
done < <(grep -oE 'skills/[a-z0-9/-]+/SKILL\.md' README.md | sort -u)

# external-skills.yaml has the one shape scripts/external-skills.py reads, and lists no
# skill that this repo already has.
if [ -f external-skills.yaml ]; then
  if ext="$(python3 -I scripts/external-skills.py)"; then
    while IFS=$'\t' read -r _ name; do
      if printf '%s\n' "${skills[@]}" | grep -qx "$name"; then problem "external-skills.yaml: '$name' is also a skill in this repo"; fi
    done <<< "$ext"
  else
    problem "external-skills.yaml has the problems above"
  fi
fi

# Settings are valid JSON, and the public file carries no machine-specific paths.
python3 -m json.tool claude/settings.json >/dev/null || problem "claude/settings.json is not valid JSON"
if grep -q '/Users/' claude/settings.json; then problem "claude/settings.json contains a /Users/ path; use \$HOME"; fi

# Every shell script parses, and passes the linter where it is installed (it is in CI).
# Keep this comment free of the linter's own name at the start: it reads such lines as directives.
scripts_sh=()
while IFS= read -r f; do scripts_sh+=("$f"); done < <(find scripts skills -name '*.sh' | sort)
for script in ${scripts_sh[@]+"${scripts_sh[@]}"}; do bash -n "$script" || problem "$script: syntax error"; done
for py in scripts/*.py; do python3 -m py_compile "$py" || problem "$py: syntax error"; done
if command -v shellcheck >/dev/null; then
  shellcheck "${scripts_sh[@]}" || problem "shellcheck found issues"
else
  echo "note: shellcheck not installed, skipped"
fi

# Skills, docs and scripts are English only: fail on any letter outside ASCII (accented or
# language-specific letters). Typographic punctuation and symbols are fine.
# Python, not grep -P: BSD grep on macOS has no -P, and a silent failure would pass everything.
python3 -I - <<'PY' || problem "non-English text above (skills, docs and scripts are English only)"
import sys
import unicodedata
from pathlib import Path

roots = ["skills", "README.md", "CLAUDE.md", "TOKEN-EFFICIENCY.md", "external-skills.yaml", "claude", "scripts", ".github"]
skip_dirs = {"icons", "node_modules", ".git", "__pycache__"}
hits = []
for root in roots:
    p = Path(root)
    for f in ([p] if p.is_file() else sorted(p.rglob("*"))):
        if not f.is_file() or skip_dirs & set(f.parts):
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        for n, line in enumerate(lines, 1):
            if any(ord(c) > 127 and unicodedata.category(c).startswith("L") for c in line):
                hits.append(f"  {f}:{n}: {line.strip()[:100]}")
for h in hits[:10]:
    print(h)
sys.exit(1 if hits else 0)
PY

if [ "$fail" = 0 ]; then echo "all checks passed"; fi
exit "$fail"
