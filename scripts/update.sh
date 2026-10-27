#!/usr/bin/env bash
set -euo pipefail

# Pulls this repo and the optional second skills repo (PRIVATE_DIR, cloned from
# PRIVATE_URL when missing), then installs the Claude Code setup into ~/.claude.
# The README describes each part. Rules the code below relies on:
# - Real folders in ~/.claude/skills are never touched, only reported.
# - A skill of your own wins over an external skill with the same name.
# - Links whose skill is gone, and external skills no longer listed, are removed.
# - SKIP_SKILLS names skills or groups this machine does not use ("dev mindmap"); they are
#   not linked, and their old links are removed.

MINE="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE="${PRIVATE_DIR:-$HOME/dev/private-skills}"
PRIVATE_URL="${PRIVATE_URL:-}"
DEST="$HOME/.claude/skills"
EXTERNAL="$MINE/external-skills.yaml"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/claude-harness/repos"   # same folder as CACHE in external-skills.py

sync_repo() {
  local dir="$1" url="$2"
  if [[ -d "$dir/.git" ]]; then
    echo "== pull $dir"
    git -C "$dir" pull --ff-only --quiet </dev/null || echo "warn: could not fast-forward $dir; linking what is there" >&2
  elif [[ -n "$url" ]]; then
    echo "== clone $url into $dir"
    git clone --quiet "$url" "$dir" </dev/null || echo "warn: could not clone $url; skipping it" >&2
  else
    echo "== skip $dir: not a git checkout and no URL to clone"
  fi
}

# link <skill-dir> [name]: link the skill into ~/.claude/skills, by folder name unless a name is given.
link() {
  local src="$1" name="${2:-}" target
  [[ -n "$name" ]] || name="$(basename "$src")"
  target="$DEST/$name"
  if [[ -e "$target" && ! -L "$target" ]]; then
    echo "skip $name: $target is a real folder, not a link" >&2
    return 1
  fi
  ln -sfn "$src" "$target"
}

# skipped <group/name>: true, and says so, when SKIP_SKILLS names the skill or one of its groups.
skipped() {
  local word
  for word in ${SKIP_SKILLS:-}; do
    [[ "/$1/" == *"/$word/"* ]] && { echo "skipped $1 (SKIP_SKILLS)"; return 0; }
  done
  return 1
}

sync_repo "$PRIVATE" "$PRIVATE_URL"
sync_repo "$MINE" ""

echo "== settings"
python3 "$MINE/scripts/build-settings.py" \
  "$MINE/claude/settings.json" "$PRIVATE/claude/settings.json" \
  "$HOME/.claude/settings.json" "$HOME/.claude/.harness/settings.last.json" \
  || echo "warn: settings.json not updated (see above)" >&2

if [[ -L "$HOME/.claude/CLAUDE.md" || ! -e "$HOME/.claude/CLAUDE.md" ]] \
  || cmp -s "$HOME/.claude/CLAUDE.md" "$MINE/claude/CLAUDE.md"; then
  ln -sfn "$MINE/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
  echo "linked CLAUDE.md"
else
  echo "skip CLAUDE.md: ~/.claude/CLAUDE.md differs from claude/CLAUDE.md; merge them, then delete the live file" >&2
fi

mkdir -p "$DEST"

echo "== link skills"
mine_names=" "
for repo in "$MINE" "$PRIVATE"; do
  [[ -d "$repo/skills" ]] || continue
  # A folder with SKILL.md is a skill, at any depth; a folder without one is a group.
  while IFS= read -r file; do
    src="$(dirname "$file")"
    name="$(basename "$src")"
    skipped "${src#"$repo"/skills/}" && continue
    case "$mine_names" in
      *" $name "*) echo "skip $src: another skills repo already has $name" >&2; continue ;;
      *) ;;
    esac
    mine_names+="$name "
    link "$src" && echo "linked  $name ($(basename "$repo"))"
  done < <(find "$repo/skills" -name SKILL.md | sort)
done

# Skills from other repos: external-skills.py checks the list, this script clones or pulls
# each repo, then `external-skills.py resolve` finds every listed skill by its SKILL.md name.
ext_names=" "
ext_ok=0
if [[ -f "$EXTERNAL" ]]; then
  echo "== link external skills"
  if pairs="$(python3 -I "$MINE/scripts/external-skills.py")"; then
    ext_ok=1
    while IFS= read -r url; do
      mkdir -p "$(dirname "$CACHE/${url#https://}")"
      sync_repo "$CACHE/${url#https://}" "$url"
    done < <(cut -f1 <<< "$pairs" | sort -u)
    while IFS=$'\t' read -r name src; do
      skipped "$name" && continue
      case "$mine_names" in
        *" $name "*) echo "skip $name: a skill of your own has that name" >&2; continue ;;
        *) ;;
      esac
      ext_names+="$name "
      link "$src" "$name" && echo "linked  $name (external)"
    done < <(python3 -I "$MINE/scripts/external-skills.py" resolve)
  else
    echo "warn: external-skills.yaml has problems; external links left as they were" >&2
  fi
fi

# Remove links into these repos that are dangling or skipped, and external links no longer listed.
# With a broken external-skills.yaml, external links stay until the file is fixed.
for entry in "$DEST"/*; do
  [[ -L "$entry" ]] || continue
  case "$(readlink "$entry")" in
    "$MINE"/skills/*|"$PRIVATE"/skills/*)
      [[ -e "$entry" && "$mine_names" == *" $(basename "$entry") "* ]] && continue ;;
    "$CACHE"/*)
      [[ "$ext_ok" = 1 ]] || continue
      [[ -e "$entry" && "$ext_names" == *" $(basename "$entry") "* ]] && continue ;;
    *) continue ;;
  esac
  rm "$entry"
  echo "removed $(basename "$entry")"
done
