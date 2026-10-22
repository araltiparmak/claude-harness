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

rm -f "$dir"/out/*.svg "$dir"/out/*.png   # a removed source must not leave its old diagram behind
for src in "$dir"/*.d2 "$dir"/*.mmd; do
  [[ -e "$src" ]] || continue
  SKETCH="${SKETCH-1}" "$render" "$src" "$dir/out"
done
# Each <!--svg:NAME--> in the page becomes a data: URI of out/NAME.svg. A data URI in an <img> keeps
# every SVG's styles apart: two inline Mermaid SVGs share one id and restyle each other.
OUT="$dir/out" perl -MMIME::Base64 -0pe '
  s{<!--svg:([a-z0-9-]+)-->}{
    my $f = "$ENV{OUT}/$1.svg";
    open(my $h, "<:raw", $f) or die "build: page names \x27$1\x27 but $f does not exist\n";
    local $/; "data:image/svg+xml;base64," . encode_base64(<$h>, "")
  }ge' "$dir/page.html" > "$dir/index.html.tmp" || { rm -f "$dir/index.html.tmp"; exit 1; }
mv "$dir/index.html.tmp" "$dir/index.html"
echo "$dir/index.html"
