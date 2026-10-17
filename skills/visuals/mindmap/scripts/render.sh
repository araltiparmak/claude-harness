#!/usr/bin/env bash
# Render a Markdown outline to an interactive mind map (HTML) and a PNG.
# Usage: render.sh <file.md> [out-dir]   (out-dir defaults to ./mindmap-out)
set -euo pipefail

src="${1:?usage: render.sh <file.md> [out-dir]}"
out="${2:-mindmap-out}"
mkdir -p "$out"; out="$(cd "$out" && pwd)"
base="$(basename "${src%.*}")"
size="${MINDMAP_SIZE:-1600x1000}"

find_chrome() {
  for c in "${CHROME:-}" \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    google-chrome chromium chromium-browser microsoft-edge; do
    [ -n "$c" ] && { [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; } && { echo "$c"; return; }
  done
  echo "no Chrome/Edge found: set CHROME=/path/to/browser" >&2; exit 1
}

if command -v markmap >/dev/null 2>&1; then mm=(markmap); else mm=(npx -y markmap-cli@0.18.12); fi
"${mm[@]}" "$src" --no-open --offline --no-toolbar -o "$out/$base.html" >/dev/null
# Refit the map after every click, or an opened branch runs off the screen. markmap supports autoFit
# but drops it from front matter (deriveOptions passes only numbers and colors), so set it here.
# Animations default to 200 ms instead of 500, which felt slow with the refit; `duration` in the
# front matter still wins.
fit='(getOptions || markmap.deriveOptions)(jsonOptions)'
grep -qF "$fit" "$out/$base.html" || { echo "render.sh: markmap init changed, autoFit not set" >&2; exit 1; }
FIT="$fit" perl -pi -e 's/\Q$ENV{FIT}\E/{ duration: 200, ...$ENV{FIT}, autoFit: true }/' "$out/$base.html"

chrome="$(find_chrome)"
shared="$(cd -P "$(dirname "$0")" && pwd -P)/../../scripts"   # physical path: the skill is symlinked into ~/.claude/skills

# The screenshot comes from a copy with duration 0 and every branch open. markmap animates the first
# draw for 500 ms, and headless Chrome often saved the frame before the map appeared (a blank PNG in
# about half of the runs); and a PNG cannot be clicked open. The HTML in $out keeps its own settings,
# so the interactive map still animates and opens branches on click.
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
python3 -I - "$src" "$tmp/shot.md" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.match(r"---\n(.*?)\n---\n", text, re.S)
front = m.group(1) if m else ""
body = text[m.end():] if m else text
front = re.sub(r"^\s+(duration|initialExpandLevel):.*\n?", "", front, flags=re.M)
shot = "markmap:\n  duration: 0\n  initialExpandLevel: -1"
if re.search(r"^markmap:\s*$", front, re.M):
    front = re.sub(r"^markmap:\s*$", shot, front, count=1, flags=re.M)
else:
    front = (front + "\n" if front else "") + shot
open(sys.argv[2], "w", encoding="utf-8").write(f"---\n{front}\n---\n{body}")
PY
"${mm[@]}" "$tmp/shot.md" --no-open --offline --no-toolbar -o "$tmp/shot.html" >/dev/null

"$chrome" --headless --disable-gpu --hide-scrollbars \
  --screenshot="$out/$base.png" --window-size="${size/x/,}" \
  --run-all-compositor-stages-before-draw --virtual-time-budget=10000 \
  --blink-settings=preferredColorScheme=1 "file://$tmp/shot.html" >/dev/null 2>&1

ls -1 "$out/$base".*

# Visual check: blank output, aspect ratio, resolution.
if [ -f "$shared/check-image.py" ]; then
  python3 -I "$shared/check-image.py" --max-wide 3 "$out/$base.png"
fi
