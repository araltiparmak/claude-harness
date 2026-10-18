#!/usr/bin/env bash
set -euo pipefail

# Pulls this repo and the optional second skills repo (PRIVATE_DIR, cloned from
# PRIVATE_URL when missing), then installs the Claude Code setup into ~/.claude.
# The README describes each part. Rules the code below relies on:
# - Real folders in ~/.claude/skills are never touched, only reported.
# - A skill of your own wins over an external skill with the same name.
# - Links whose skill is gone, and external skills no longer listed, are removed.

MINE="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE="${PRIVATE_DIR:-$HOME/dev/private-skills}"
PRIVATE_URL="${PRIVATE_URL:-}"
DEST="$HOME/.claude/skills"
EXTERNAL="$MINE/external-skills.yaml"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/claude-harness/repos"

sync_repo() {
  local dir="$1" url="$2"
  if [ -d "$dir/.git" ]; then
    echo "== pull $dir"
    git -C "$dir" pull --ff-only --quiet </dev/null || echo "warn: could not fast-forward $dir; linking what is there" >&2
  elif [ -n "$url" ]; then
    echo "== clone $url into $dir"
    git clone --quiet "$url" "$dir" </dev/null || echo "warn: could not clone $url; skipping it" >&2
  else
    echo "== skip $dir: not a git checkout and no URL to clone"
  fi
}

# link <skill-dir> [name]: link the skill into ~/.claude/skills, by folder name unless a name is given.
link() {
  local src="$1" name="${2:-$(basename "$1")}" target
  target="$DEST/$name"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "skip $name: $target is a real folder, not a link" >&2
    return 1
  fi
  ln -sfn "$src" "$target"
}

# skill_dir <repo-dir> <name>: the folder whose SKILL.md front matter says `name: <name>`.
skill_dir() {
  local file
  while IFS= read -r file; do
    if awk -v n="$2" 'NR==1 && $0!="---" {exit} NR>1 && $0=="---" {exit} $0=="name: " n {found=1; exit} END {exit !found}' "$file"; then
      dirname "$file"
      return
    fi
  done < <(find "$1" -name SKILL.md -not -path '*/.git/*' | sort)
}

sync_repo "$PRIVATE" "$PRIVATE_URL"
sync_repo "$MINE" ""

echo "== settings"
python3 "$MINE/scripts/build-settings.py" \
  "$MINE/claude/settings.json" "$PRIVATE/claude/settings.json" \
  "$HOME/.claude/settings.json" "$HOME/.claude/.harness/settings.last.json" \
  || echo "warn: settings.json not updated (see above)" >&2

if [ -L "$HOME/.claude/CLAUDE.md" ] || [ ! -e "$HOME/.claude/CLAUDE.md" ] \
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
  [ -d "$repo/skills" ] || continue
  # A folder with SKILL.md is a skill, at any depth; a folder without one is a group.
  # Sorted, so a skill comes before anything nested inside it, and nested SKILL.md files
  # (examples, fixtures) are not linked as skills of their own.
  linked_dirs=()
  while IFS= read -r file; do
    src="$(dirname "$file")"
    inside=0
    for parent in ${linked_dirs[@]+"${linked_dirs[@]}"}; do
      case "$src/" in "$parent"/*) inside=1 ;; esac
    done
    [ "$inside" = 0 ] || continue
    name="$(basename "$src")"
    case "$mine_names" in
      *" $name "*) echo "skip $src: another skills repo already has $name" >&2; continue ;;
    esac
    mine_names+="$name "
    linked_dirs+=("$src")
    link "$src" && echo "linked  $name ($(basename "$repo"))"
  done < <(find "$repo/skills" -name SKILL.md | sort)
done

# external-skills.yaml, read by scripts/external-skills.py as URL<TAB>NAME lines.
ext_names=" "
if [ -f "$EXTERNAL" ]; then
  echo "== link external skills"
  pairs="$(python3 -I "$MINE/scripts/external-skills.py")" || { echo "warn: external skills not linked (see above)" >&2; pairs=""; }
  synced=" "
  while IFS=$'\t' read -r url name; do
    [ -n "$url" ] || continue
    dir="$CACHE/${url#https://}"
    case "$synced" in
      *" $url "*) ;;
      *) mkdir -p "$(dirname "$dir")"; sync_repo "$dir" "$url"; synced+="$url " ;;
    esac
    [ -d "$dir/.git" ] || continue
    case "$mine_names" in
      *" $name "*) echo "skip $name: a skill of your own has that name" >&2; continue ;;
    esac
    src="$(skill_dir "$dir" "$name")"
    if [ -z "$src" ]; then
      echo "warn: $url has no skill named $name" >&2
      continue
    fi
    ext_names+="$name "
    link "$src" "$name" && echo "linked  $name (${url#https://})"
  done <<< "$pairs"
fi

# Remove links into these repos that are dangling, and external links no longer listed.
for entry in "$DEST"/*; do
  [ -L "$entry" ] || continue
  case "$(readlink "$entry")" in
    "$MINE"/skills/*|"$PRIVATE"/skills/*) [ -e "$entry" ] && continue ;;
    "$CACHE"/*) [ -e "$entry" ] && case "$ext_names" in *" $(basename "$entry") "*) continue ;; esac ;;
    *) continue ;;
  esac
  rm "$entry"
  echo "removed $(basename "$entry")"
done
