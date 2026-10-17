#!/usr/bin/env python3
"""Expand an infographic template into one self-contained HTML file.

Markers in the source:
  <!--base-->        templates/tokens.css + templates/base.css, as one <style>
  <!--checks-->      the in-page checks (scripts/check.js), as one <script>
  <!--icon:NAME-->   the Lucide icon NAME as inline SVG with class="ico"

Usage: build.py SOURCE.html OUT.html
"""
import json
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parent  # the infographics skill folder
RULES = {"minFont": 13, "minContrast": 4.5, "minContrastLarge": 3}  # limits check.js enforces


def main(src, out):
    html = Path(src).read_text()
    css = (root / "templates" / "tokens.css").read_text() + "\n" + (root / "templates" / "base.css").read_text()
    js = (here / "check.js").read_text().replace("/*RULES*/null", json.dumps(RULES))

    def icon(m):
        f = root / "icons" / "lucide" / f"{m.group(1)}.svg"
        if not f.exists():
            sys.exit(f"build: no icon '{m.group(1)}' in icons/lucide")
        return f.read_text().strip().replace("<svg ", '<svg class="ico" aria-hidden="true" ', 1)

    html = re.sub(r"<!--icon:([a-z0-9-]+)-->", icon, html)
    for marker, body in (("<!--base-->", f"<style>\n{css}\n</style>"), ("<!--checks-->", f"<script>\n{js}\n</script>")):
        if marker in html:
            html = html.replace(marker, body)
    if "<!--base-->" not in Path(src).read_text():
        sys.exit("build: the template has no <!--base--> marker, so it has no styles")
    Path(out).write_text(html)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
