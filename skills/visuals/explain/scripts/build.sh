#!/usr/bin/env bash
# Render a topic folder's diagrams and build its page.
# Usage: build.sh <topic-dir>
#   <topic-dir> holds page.html and the .d2 / .mmd sources it names with <!--svg:NAME-->.
#   Writes the diagrams to <topic-dir>/out/ and the finished page to <topic-dir>/index.html.
#   D2 renders in the whiteboard style; set SKETCH= (empty) for the plain style.
set -euo pipefail

dir="$(cd "${1:?usage: build.sh <topic-dir>}" && pwd)"
here="$(cd -P "$(dirname "$0")" && pwd -P)"     # physical path: the skill is symlinked into ~/.claude/skills
render="$here/../../diagrams/scripts/render.sh"  # shared with the diagrams skill

for src in "$dir"/*.d2 "$dir"/*.mmd; do
  [ -e "$src" ] || continue
  SKETCH="${SKETCH-1}" "$render" "$src" "$dir/out"
done
python3 -I "$here/build.py" "$dir/page.html" "$dir/out" "$dir/index.html"
