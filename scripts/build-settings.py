#!/usr/bin/env python3
"""Build ~/.claude/settings.json from the public base and an optional private overlay.

    build-settings.py BASE OVERLAY TARGET STATE

The merge is recursive: objects merge key by key, lists are concatenated
without duplicates, and for any other value the overlay wins. A missing
OVERLAY is treated as empty.

STATE keeps a copy of the last settings this script wrote. If TARGET no longer
matches it, something else changed TARGET (Claude Code's /config, a plugin
install, a hand edit). The script then prints the difference and stops, so the
change can be moved into the repo instead of being overwritten. Set
HARNESS_FORCE=1 to overwrite anyway; the old file is backed up first.

Exit codes: 0 written or already current, 3 drift found.
"""

import difflib
import json
import os
import shutil
import sys
import time


def merge(base, overlay):
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            out[key] = merge(base[key], value) if key in base else value
        return out
    if isinstance(base, list) and isinstance(overlay, list):
        return base + [item for item in overlay if item not in base]
    return overlay


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main():
    base_path, overlay_path, target, state = sys.argv[1:5]
    wanted = load(base_path)
    if os.path.exists(overlay_path):
        wanted = merge(wanted, load(overlay_path))

    current = load(target) if os.path.exists(target) else None
    if current == wanted:
        print("settings.json is current")
        _write(state, wanted)
        return 0

    last = load(state) if os.path.exists(state) else None
    drifted = current is not None and current != last
    if drifted and os.environ.get("HARNESS_FORCE") != "1":
        print(f"warn: {target} was changed outside the harness. Not overwriting it.", file=sys.stderr)
        print("Move the change into claude/settings.json (or the private overlay), or re-run with HARNESS_FORCE=1.", file=sys.stderr)
        print("Lines starting with - are in the repo, lines starting with + are only in the live file:", file=sys.stderr)
        diff = difflib.unified_diff(dump(wanted).splitlines(), dump(current).splitlines(), "repo", "live", lineterm="", n=1)
        for line in diff:
            print("  " + line, file=sys.stderr)
        return 3

    if current is not None:
        backup = f"{target}.harness-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(target, backup)
        print(f"backed up the old settings.json to {backup}")
    _write(target, wanted)
    _write(state, wanted)
    print("wrote settings.json")
    return 0


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump(data))


if __name__ == "__main__":
    sys.exit(main())
