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

find_chrome() {
  for c in "${CHROME:-}" \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    google-chrome chromium chromium-browser microsoft-edge; do
    [[ -n "$c" ]] && { [[ -x "$c" ]] || command -v "$c" >/dev/null 2>&1; } && { echo "$c"; return; }
  done
  echo "no Chrome/Edge found: set CHROME=/path/to/browser" >&2; exit 1
}

case "$ext" in
  mmd)
    chrome="$(find_chrome)"
    cfg="$(mktemp -d)/puppeteer.json"   # mktemp -d: the same on macOS and Linux
    printf '{"executablePath":"%s","args":["--no-sandbox"]}' "$chrome" > "$cfg"
    if command -v mmdc >/dev/null 2>&1; then mm=(mmdc); else mm=(npx -y @mermaid-js/mermaid-cli); fi
    PUPPETEER_SKIP_DOWNLOAD=1 "${mm[@]}" -p "$cfg" -i "$src" -o "$out/$base.png" -s 2 -b white
    PUPPETEER_SKIP_DOWNLOAD=1 "${mm[@]}" -p "$cfg" -i "$src" -o "$out/$base.svg" -b white
    ;;
  d2)
    # D2_LAYOUT wins, then the source's own `layout-engine:` (d2-config), then TALA.
    layout="${D2_LAYOUT:-$(sed -n 's/.*layout-engine: *\([a-z]*\).*/\1/p' "$src" | head -1)}"
    layout="${layout:-tala}"
    lflags=(--layout="$layout")
    # ELK's default gap between columns leaves a left-to-right route about 15% wider than it needs.
    [[ "$layout" == elk ]] && lflags+=(--elk-nodeNodeBetweenLayers=40 --elk-edgeNodeBetweenLayers=20)
    d2src="$src"
    # ICONS/ in the source stands for the local icon folder: fetch once, then work offline.
    if grep -q 'ICONS/' "$src"; then
      "$here/fetch-icons.sh" >&2
      d2src="$(mktemp -d)/$base.d2"
      sed "s|ICONS/|$here/../icons/|g" "$src" > "$d2src"
    fi
    sketch=(); [[ -n "${SKETCH:-}" ]] && sketch=(--sketch)   # SKETCH=1: hand-drawn look
    d2 "${lflags[@]}" ${sketch[@]+"${sketch[@]}"} --pad 48 "$d2src" "$out/$base.svg"
    d2 "${lflags[@]}" ${sketch[@]+"${sketch[@]}"} --pad 48 --scale 2 "$d2src" "$out/$base.png"
    ;;
  html)
    chrome="$(find_chrome)"
    size="$(sed -n 's/.*name="render-size" content="\([0-9]*x[0-9]*\)".*/\1/p' "$src" | head -1)"
    size="${size:-1200x800}"
    abs="$(cd "$(dirname "$src")" && pwd)/$(basename "$src")"
    "$chrome" --headless --disable-gpu --hide-scrollbars \
      --screenshot="$out/$base.png" --window-size="${size/x/,}" \
      --run-all-compositor-stages-before-draw --virtual-time-budget=10000 \
      --force-device-scale-factor=2 "file://$abs" >/dev/null 2>&1
    ;;
  *) echo "unsupported extension: .$ext" >&2; exit 2 ;;
esac

for f in "$out/$base".png "$out/$base".svg; do [[ -f "$f" ]] && echo "$f"; done

# Size and aspect, so a picture that breaks the aspect rule is fixed before anyone reads it.
read -r w h < <(file "$out/$base.png" | sed -n 's/.* \([0-9]*\) x \([0-9]*\),.*/\1 \2/p')
if [[ -n "${w:-}" ]]; then
  ratio="$(awk -v w="$w" -v h="$h" 'BEGIN { printf "%.1f", w / h }')"
  echo "size $w x $h ($ratio:1)"
  awk -v r="$ratio" 'BEGIN { exit !(r > 3) }' && echo "WIDE wider than 3:1; only a gantt or timeline may reach 4:1"
fi
exit 0
