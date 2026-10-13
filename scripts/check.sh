#!/usr/bin/env bash
set -euo pipefail

# Checks the repo is consistent. Runs in CI on every push and pull request, and
# locally with scripts/check.sh. Prints every problem, then exits 1 if any.

cd "$(dirname "$0")/.."
fail=0
problem() { echo "FAIL: $*"; fail=1; }

# Every skill: SKILL.md with front matter, name matching the folder, a description.
skills=()
for dir in skills/*/; do
  name="$(basename "$dir")"
  skills+=("$name")
  file="$dir/SKILL.md"
  if [ ! -f "$file" ]; then problem "$name: no SKILL.md"; continue; fi
  [ "$(head -1 "$file")" = "---" ] || problem "$name: SKILL.md does not start with front matter"
  front="$(awk 'NR==1{next} /^---$/{exit} {print}' "$file")"
  grep -qx "name: $name" <<<"$front" || problem "$name: front matter name is not '$name'"
  grep -qE '^description: .+' <<<"$front" || problem "$name: front matter has no description"
done

# README's skill table lists exactly the folders in skills/.
listed="$(grep -oE '^\| \[[a-z0-9-]+\]\(skills/[a-z0-9-]+/SKILL.md\)' README.md | sed -E 's/.*skills\/([a-z0-9-]+)\/.*/\1/' | sort)"
actual="$(printf '%s\n' "${skills[@]}" | sort)"
if [ "$listed" != "$actual" ]; then
  problem "README skill table does not match skills/:"
  diff <(echo "$listed") <(echo "$actual") | sed 's/^/  /' || true
fi

# Settings are valid JSON, and the public file carries no machine-specific paths.
python3 -m json.tool claude/settings.json >/dev/null || problem "claude/settings.json is not valid JSON"
if grep -q '/Users/' claude/settings.json; then problem "claude/settings.json contains a /Users/ path; use \$HOME"; fi

# Scripts parse, and pass shellcheck where it is installed (it is in CI).
for script in scripts/*.sh; do bash -n "$script" || problem "$script: syntax error"; done
python3 -m py_compile scripts/build-settings.py || problem "scripts/build-settings.py: syntax error"
if command -v shellcheck >/dev/null; then
  shellcheck scripts/*.sh || problem "shellcheck found issues"
else
  echo "note: shellcheck not installed, skipped"
fi

if [ "$fail" = 0 ]; then echo "all checks passed"; fi
exit "$fail"
