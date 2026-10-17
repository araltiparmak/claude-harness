#!/usr/bin/env bash
# Render a diagram source to PNG (and SVG where the tool supports it).
# Usage: render.sh <file.mmd|.d2|.html> [out-dir]   (out-dir defaults to ./diagrams-out)
set -euo pipefail

src="${1:?usage: render.sh <file.mmd|.d2|.html> [out-dir]}"
out="${2:-diagrams-out}"
mkdir -p "$out"; out="$(cd "$out" && pwd)"
base="$(basename "${src%.*}")"
ext="${src##*.}"
here="$(cd -P "$(dirname "$0")" && pwd -P)"   # physical path: the skill is symlinked into ~/.claude/skills
shared="$here/../../scripts"                    # check-image.py, shared by the visuals skills

find_chrome() {
  for c in "${CHROME:-}" \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    google-chrome chromium chromium-browser microsoft-edge; do
    [ -n "$c" ] && { [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; } && { echo "$c"; return; }
  done
  echo "no Chrome/Edge found: set CHROME=/path/to/browser" >&2; exit 1
}

case "$ext" in
  mmd)
    chrome="$(find_chrome)"
    cfg="$(mktemp -t pp).json"
    printf '{"executablePath":"%s","args":["--no-sandbox"]}' "$chrome" > "$cfg"
    if command -v mmdc >/dev/null 2>&1; then mm=(mmdc); else mm=(npx -y @mermaid-js/mermaid-cli); fi
    PUPPETEER_SKIP_DOWNLOAD=1 "${mm[@]}" -p "$cfg" -i "$src" -o "$out/$base.png" -s 2 -b white
    PUPPETEER_SKIP_DOWNLOAD=1 "${mm[@]}" -p "$cfg" -i "$src" -o "$out/$base.svg" -b white
    ;;
  d2)
    layout="${D2_LAYOUT:-tala}"
    d2src="$src"
    # ICONS/ in the source stands for the local icon folder: fetch once, then work offline.
    if grep -q 'ICONS/' "$src"; then
      "$here/fetch-icons.sh" >&2
      d2src="$(mktemp -d)/$base.d2"
      sed "s|ICONS/|$here/../icons/|g" "$src" > "$d2src"
    fi
    sketch=(); [ -n "${SKETCH:-}" ] && sketch=(--sketch)   # SKETCH=1: hand-drawn look
    d2 --layout="$layout" ${sketch[@]+"${sketch[@]}"} --pad 48 "$d2src" "$out/$base.svg"
    d2 --layout="$layout" ${sketch[@]+"${sketch[@]}"} --pad 48 --scale 2 "$d2src" "$out/$base.png"
    ;;
  html)
    chrome="$(find_chrome)"
    size="$(sed -n 's/.*name="render-size" content="\([0-9]*x[0-9]*\)".*/\1/p' "$src" | head -1)"
    size="${size:-1200x800}"
    abs="$(cd "$(dirname "$src")" && pwd)/$(basename "$src")"
    "$chrome" --headless --disable-gpu --hide-scrollbars \
      --screenshot="$out/$base.png" --window-size="${size/x/,}" \
      --force-device-scale-factor=2 "file://$abs" >/dev/null 2>&1
    ;;
  *) echo "unsupported extension: .$ext" >&2; exit 2 ;;
esac

for f in "$out/$base".png "$out/$base".svg; do [ -f "$f" ] && echo "$f"; done

# Visual check: blank output, aspect ratio, resolution. MAX_WIDE=4 relaxes the width limit (gantt, timelines).
if [ -f "$shared/check-image.py" ]; then
  python3 -I "$shared/check-image.py" --max-wide "${MAX_WIDE:-3}" "$out/$base.png"
fi
