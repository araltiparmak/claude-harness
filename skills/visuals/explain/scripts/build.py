#!/usr/bin/env python3
"""Inline rendered diagrams into an explain page.

Each <!--svg:NAME--> marker in the page becomes a data: URI of SVG-DIR/NAME.svg. A data URI
in an <img> keeps every SVG's styles apart: two inline Mermaid SVGs share one id and restyle
each other.

Usage: build.py PAGE.html SVG-DIR OUT.html
"""
import base64
import re
import sys
from pathlib import Path


def main(page, svg_dir, out):
    def inline(m):
        f = Path(svg_dir) / f"{m.group(1)}.svg"
        if not f.exists():
            sys.exit(f"build: page names '{m.group(1)}' but {f} does not exist")
        return "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()

    html = re.sub(r"<!--svg:([a-z0-9-]+)-->", inline, Path(page).read_text())
    Path(out).write_text(html)
    print(out)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
