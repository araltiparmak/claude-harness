#!/usr/bin/env python3
"""Sanity-check rendered PNGs: size, aspect ratio and blank output.

Usage: check-image.py [--max-wide 3] [--max-tall 2] FILE.png ...
Exits 1 when a file fails (blank, aspect ratio). Low resolution only warns.

Blank detection compares the PNG byte size with its pixel count. A blank 3200x2000
render is about 0.0036 bytes per pixel; a sparse real slide is above 0.017.
"""
import os
import struct
import sys


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    return struct.unpack(">II", head[16:24])


def main(argv):
    max_wide, max_tall, files = 3.0, 2.0, []
    it = iter(argv)
    for a in it:
        if a == "--max-wide":
            max_wide = float(next(it))
        elif a == "--max-tall":
            max_tall = float(next(it))
        else:
            files.append(a)
    if not files:
        print(__doc__)
        return 2
    failed = False
    for path in files:
        try:
            w, h = png_size(path)
        except (OSError, ValueError) as e:
            print(f"FAIL {path}: {e}")
            failed = True
            continue
        problems, warnings = [], []
        density = os.path.getsize(path) / (w * h)
        if density < 0.008:
            problems.append(f"looks blank ({density:.4f} bytes per pixel, real content is above 0.017)")
        if w / h > max_wide:
            problems.append(f"too wide: {w}x{h} is {w / h:.1f}:1, limit {max_wide:g}:1")
        if h / w > max_tall:
            problems.append(f"too tall: {w}x{h} is 1:{h / w:.1f}, limit 1:{max_tall:g}")
        if w < 1000:
            warnings.append(f"low resolution: {w}px wide, fine for a small diagram, blurry when zoomed")
        for wmsg in warnings:
            print(f"WARN {path}: {wmsg}")
        if problems:
            failed = True
            for p in problems:
                print(f"FAIL {path}: {p}")
        elif not warnings:
            print(f"ok   {path} ({w}x{h}, {w / h:.2f}:1)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
