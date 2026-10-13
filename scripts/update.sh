#!/usr/bin/env bash
set -euo pipefail

# Pulls my-harness, private-skills and mattpocock/skills, then symlinks their
# skills into ~/.claude/skills. Because every entry is a symlink, the pull is
# what updates them. Run it again whenever you want the latest skills, or after
# adding, removing or renaming one of your own.
#
# - Missing repos are cloned to ~/dev. private-skills is private: on a machine
#   without access its clone fails, and the rest still links.
# - Matt's skills: the promoted buckets (engineering/, productivity/), the same
#   set his plugin ships. Set MATT_BUCKETS to change it, e.g.
#   MATT_BUCKETS="engineering productivity in-progress".
# - My skills (my-harness, private-skills) win a name clash with his.
# - Real folders in ~/.claude/skills are never touched, only reported.
# - Links into these repos whose skill no longer exists are removed.

MINE="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE="${PRIVATE_DIR:-$HOME/dev/private-skills}"
MATT="${MATT_DIR:-$HOME/dev/mattpocock-skills}"
MATT_BUCKETS="${MATT_BUCKETS:-engineering productivity}"
DEST="$HOME/.claude/skills"

sync_repo() {
  local dir="$1" url="$2"
  if [ -d "$dir/.git" ]; then
    echo "== pull $dir"
    git -C "$dir" pull --ff-only --quiet || echo "warn: could not fast-forward $dir; linking what is there" >&2
  else
    echo "== clone $url into $dir"
    git clone --quiet "$url" "$dir" || echo "warn: could not clone $url; skipping it" >&2
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

sync_repo "$MATT" https://github.com/mattpocock/skills.git
sync_repo "$PRIVATE" https://github.com/araltiparmak/private-skills.git
sync_repo "$MINE" https://github.com/araltiparmak/my-harness.git

mkdir -p "$DEST"

echo "== link"
mine_names=" "
for repo in "$MINE" "$PRIVATE"; do
  [ -d "$repo/skills" ] || continue
  for src in "$repo"/skills/*/; do
    src="${src%/}"
    [ -f "$src/SKILL.md" ] || continue
    name="$(basename "$src")"
    case "$mine_names" in
      *" $name "*) echo "skip $repo/$name: another of my repos already has $name" >&2; continue ;;
    esac
    mine_names+="$name "
    link "$src"
    echo "mine  $name ($(basename "$repo"))"
  done
done

for bucket in $MATT_BUCKETS; do
  for src in "$MATT/skills/$bucket"/*/; do
    src="${src%/}"
    [ -f "$src/SKILL.md" ] || continue
    name="$(basename "$src")"
    case "$mine_names" in
      *" $name "*) echo "skip matt/$name: you have your own $name" >&2; continue ;;
    esac
    link "$src"
    echo "matt  $name"
  done
done

# Remove links into these repos that are dangling, or that point at a Matt
# bucket no longer selected.
for entry in "$DEST"/*; do
  [ -L "$entry" ] || continue
  dest="$(readlink "$entry")"
  case "$dest" in
    "$MINE"/skills/*|"$PRIVATE"/skills/*|"$MATT"/skills/*) ;;
    *) continue ;;
  esac
  keep=1
  [ -e "$entry" ] || keep=0
  case "$dest" in
    "$MATT"/skills/*)
      bucket="${dest#"$MATT"/skills/}"; bucket="${bucket%%/*}"
      case " $MATT_BUCKETS " in *" $bucket "*) ;; *) keep=0 ;; esac
      ;;
  esac
  if [ "$keep" = 0 ]; then
    rm "$entry"
    echo "removed $(basename "$entry")"
  fi
done
