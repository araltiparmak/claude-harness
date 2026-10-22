#!/usr/bin/env bash
# Wrap rendered diagrams into one self-contained web page (also a valid Claude Artifact).
# Usage: page.sh <out.html> "<title>" <diagram.svg|.png>[=<caption>] ...
#   Each diagram is inlined as a data: URI, so the page is one file with no network needs.
#   The caption defaults to the file name with dashes turned into spaces.
set -euo pipefail

out="${1:?usage: page.sh <out.html> \"<title>\" <diagram.svg|.png>[=<caption>] ...}"
title="${2:?missing title}"
shift 2
[[ $# -gt 0 ]] || { echo "page.sh: name at least one diagram" >&2; exit 2; }

esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' <<<"$1"; }

figures=""
for arg in "$@"; do
  file="${arg%%=*}"
  caption="$(basename "${file%.*}" | tr '-' ' ')"
  [[ "$arg" == *=* ]] && caption="${arg#*=}"
  [[ -f "$file" ]] || { echo "page.sh: $file does not exist" >&2; exit 2; }
  case "$file" in
    *.svg) mime="image/svg+xml" ;;
    *.png) mime="image/png" ;;
    *) echo "page.sh: $file is not .svg or .png" >&2; exit 2 ;;
  esac
  # A data URI in an <img> keeps every SVG's styles apart: two inline Mermaid SVGs share ids and restyle each other.
  data="$(base64 <"$file" | tr -d '\n')"
  figures+="<figure><div class=\"panel\"><img src=\"data:$mime;base64,$data\" alt=\"$(esc "$caption")\"></div><figcaption>$(esc "$caption")</figcaption></figure>"
done

cat >"$out" <<EOF
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$(esc "$title")</title>
<style>
:root{--bg:#f6f6f3;--ink:#161616;--muted:#5f5e5a;--panel:#ffffff;--line:#e2e1dc}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141414;--ink:#ececea;--muted:#a3a29d;--line:#2e2e2c}}
:root[data-theme="dark"]{--bg:#141414;--ink:#ececea;--muted:#a3a29d;--line:#2e2e2c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:1200px;margin:0 auto;padding:32px 16px 48px}
h1{margin:0 0 24px;font-size:28px;line-height:1.2;letter-spacing:-0.01em}
figure{margin:0 0 32px}
/* Diagrams keep their white background in both themes; a wide one scrolls inside its panel, never the page. */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow-x:auto}
.panel img{display:block;width:100%;min-width:640px;height:auto}
figcaption{margin-top:8px;font-size:14px;color:var(--muted)}
</style>
</head>
<body>
<main>
<h1>$(esc "$title")</h1>
$figures
</main>
</body>
</html>
EOF
echo "$out"
