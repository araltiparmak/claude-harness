#!/usr/bin/env bash
set -euo pipefail

# Pulls this repo (and an optional second skills repo), then installs the
# Claude Code setup from them: skills, settings and global instructions. Run it
# again whenever you want the latest, or after changing anything in the repos.
#
# - Skills are symlinked into ~/.claude/skills, so the pull is what updates them.
#   Every folder that holds a SKILL.md is a skill, at any depth (skills/<group>/<name>/);
#   it is linked by its folder name, so names must be unique.
# - An optional second repo (for example one with private skills) is read from
#   PRIVATE_DIR (default ~/dev/private-skills). Set PRIVATE_URL to clone it when the
#   folder is missing. With neither, only this repo is installed.
# - ~/.claude/settings.json is built from claude/settings.json plus an optional overlay
#   in <second repo>/claude/settings.json (scripts/build-settings.py).
#   If the live file was changed outside the harness, it is left alone and the
#   difference is printed.
# - ~/.claude/CLAUDE.md is a symlink to claude/CLAUDE.md.
# - Also runs `npx skills update` for the skills.sh skills in HARNESS.md
#   (Matt Pocock's skills come from there, not from a clone).
# - A second repo that cannot be cloned is skipped, and the rest still links.
# - Real folders in ~/.claude/skills are never touched, only reported.
# - Links into these repos whose skill no longer exists are removed.

MINE="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE="${PRIVATE_DIR:-$HOME/dev/private-skills}"
PRIVATE_URL="${PRIVATE_URL:-}"
DEST="$HOME/.claude/skills"

sync_repo() {
  local dir="$1" url="$2"
  if [ -d "$dir/.git" ]; then
    echo "== pull $dir"
    git -C "$dir" pull --ff-only --quiet || echo "warn: could not fast-forward $dir; linking what is there" >&2
  elif [ -n "$url" ]; then
    echo "== clone $url into $dir"
    git clone --quiet "$url" "$dir" || echo "warn: could not clone $url; skipping it" >&2
  else
    echo "== skip $dir: not a git checkout and no URL to clone"
  fi
}

link() {
  local src="$1" name target
  name="$(basename "$src")"
  target="$DEST/$name"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "skip $name: $target is a real folder, not a link" >&2
    return
  fi
  ln -sfn "$src" "$target"
}

sync_repo "$PRIVATE" "$PRIVATE_URL"
sync_repo "$MINE" ""

# Skills installed with skills.sh (see HARNESS.md) do not update themselves.
if command -v npx >/dev/null; then
  echo "== update skills.sh skills"
  npx -y skills@latest update -g -y || echo "warn: skills.sh update failed" >&2
fi

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
    link "$src"
    echo "linked  $name ($(basename "$repo"))"
  done < <(find "$repo/skills" -name SKILL.md | sort)
done

# Remove links into these repos that are dangling.
for entry in "$DEST"/*; do
  [ -L "$entry" ] || continue
  dest="$(readlink "$entry")"
  case "$dest" in
    "$MINE"/skills/*|"$PRIVATE"/skills/*) ;;
    *) continue ;;
  esac
  keep=1
  [ -e "$entry" ] || keep=0
  if [ "$keep" = 0 ]; then
    rm "$entry"
    echo "removed $(basename "$entry")"
  fi
done
