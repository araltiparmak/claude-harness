#!/usr/bin/env bash
# Render an infographic template to PNG and PDF, and run the visual checks on it.
# Usage: render.sh <file.html> [out-dir]   (out-dir defaults to ./infographics-out)
# Exits 1 when a check fails (overflow, overlap, small text, low contrast, placeholder, blank image).
set -euo pipefail

src="${1:?usage: render.sh <file.html> [out-dir]}"
out="${2:-infographics-out}"
mkdir -p "$out"; out="$(cd "$out" && pwd)"
base="$(basename "${src%.*}")"
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
chrome="$(find_chrome)"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
python3 -I "$here/build.py" "$src" "$tmp/$base.html"
cp "$tmp/$base.html" "$out/$base.html"   # the expanded file opens on its own, with the styles inlined

# 1. Checks run inside the page; read their JSON from the dumped DOM.
dom="$("$chrome" --headless --disable-gpu --virtual-time-budget=5000 --dump-dom "file://$tmp/$base.html" 2>/dev/null)"
status=0
printf '%s' "$dom" | python3 -I -c '
import html, json, re, sys
m = re.search(r"<pre id=\"check-result\" hidden=\"\">(.*?)</pre>", sys.stdin.read(), re.S)
if not m:
    print("FAIL checks did not run (the page has no .canvas, or a script error)"); sys.exit(1)
r = json.loads(html.unescape(m.group(1)))
for e in r["errors"]: print("FAIL", e)
for w in r["warnings"]: print("WARN", w)
if not r["errors"]: print("ok   page checks passed" + (" with warnings" if r["warnings"] else ""))
sys.exit(1 if r["errors"] else 0)
' || status=1

# 2. Output files. No --force-device-scale-factor: it makes headless Chrome save a blank image.
"$chrome" --headless --disable-gpu --hide-scrollbars --window-size=1280,720 \
  --run-all-compositor-stages-before-draw --virtual-time-budget=5000 \
  --screenshot="$out/$base.png" "file://$tmp/$base.html" >/dev/null 2>&1
"$chrome" --headless --disable-gpu --no-pdf-header-footer --virtual-time-budget=5000 \
  --print-to-pdf="$out/$base.pdf" "file://$tmp/$base.html" >/dev/null 2>&1

# 3. The PNG itself: blank, aspect ratio.
python3 -I "$shared/check-image.py" --max-wide 2 "$out/$base.png" || status=1

ls -1 "$out/$base".*
exit "$status"
