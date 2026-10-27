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
    [[ -n "$c" ]] && { [[ -x "$c" ]] || command -v "$c" >/dev/null 2>&1; } && { echo "$c"; return; }
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

# The screenshot comes from a copy with no animation, no refit and every branch open. markmap animates the first
# draw, and headless Chrome often saved the frame before the map appeared (a blank PNG in about half of
# the runs); and a PNG cannot be clicked open. The HTML in $out keeps its own settings.
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
sed 's/autoFit: true }/autoFit: false, duration: 0, initialExpandLevel: -1 }/' "$out/$base.html" > "$tmp/shot.html"

"$chrome" --headless --disable-gpu --hide-scrollbars \
  --screenshot="$out/$base.png" --window-size="${size/x/,}" \
  --run-all-compositor-stages-before-draw --virtual-time-budget=10000 \
  --blink-settings=preferredColorScheme=1 "file://$tmp/shot.html" >/dev/null 2>&1

ls -1 "$out/$base".*
