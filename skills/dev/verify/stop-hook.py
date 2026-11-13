#!/usr/bin/env python3
"""Stop hook: before Claude finishes, runs the project's .claude/verify when the code changed.

The code state is HEAD plus every uncommitted change, untracked files included. A state that
passed is not run again; a state that failed blocks once with the last lines of the output,
so Claude fixes it or says why it cannot pass, and is never held in a loop on the same failure.
A project without an executable .claude/verify is left alone.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

event = json.load(sys.stdin)
cwd = event.get("cwd") or "."
git = lambda *args: subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout
root = Path(git("rev-parse", "--show-toplevel").strip() or cwd)
script = root / ".claude" / "verify"
if not script.is_file():
    sys.exit(0)

state = hashlib.sha1()
for part in (git("rev-parse", "HEAD"), git("status", "--porcelain"), git("diff", "HEAD")):
    state.update(part.encode())
for name in git("ls-files", "--others", "--exclude-standard", "-z").split("\0"):
    if name and (root / name).is_file():
        state.update(name.encode() + (root / name).read_bytes())
now = state.hexdigest()

record = Path.home() / ".claude" / "state" / "verify" / hashlib.sha1(str(root).encode()).hexdigest()
record.parent.mkdir(parents=True, exist_ok=True)
if record.exists() and record.read_text().split()[0] == now:
    sys.exit(0)  # passed already, or failed and Claude was told

try:
    run = subprocess.run([str(script)], cwd=root, capture_output=True, text=True, timeout=540)
    ok, output = run.returncode == 0, run.stdout + run.stderr
except (OSError, subprocess.TimeoutExpired) as err:  # not executable, or too slow
    ok, output = False, str(err)
record.write_text(f"{now} {'ok' if ok else 'failed'}\n")
if not ok:
    tail = "\n".join(output.strip().splitlines()[-40:])
    print(json.dumps({"decision": "block", "reason": ".claude/verify failed. Fix it before finishing, "
                      f"or tell the user why it cannot pass. Last lines:\n{tail}"}))
