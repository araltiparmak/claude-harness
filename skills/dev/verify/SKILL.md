---
name: verify
description: Sets up a project's .claude/verify, the checks a Stop hook runs before Claude may finish when the code changed. Runs only when typed as /verify.
disable-model-invocation: true
---

# Verify

Arguments passed: $ARGUMENTS

A `Stop` hook (`stop-hook.py`, this skill's folder) runs `.claude/verify` from the repo root when Claude is about to finish and the code differs from the last state that passed. A failure sends the last 40 lines back, and Claude keeps working. A project without the file is left alone.

1. Find the project's own checks: `package.json` scripts (`check`, `typecheck`, `lint`, `test`, `validate`, `build`), a `Makefile` (`check`, `test`, `validate`), `pyproject.toml`, Terraform (`fmt -check`, `validate`), `scripts/check.sh`. Prefer one existing target that already runs them all.
2. Write `.claude/verify` as an executable bash script with `set -euo pipefail` that calls those checks, quiet where the tool allows. Keep it under two minutes: leave out deploys, anything that needs network credentials, and slow end-to-end suites.
3. Run it once. When it fails on code you did not touch, tell the user what fails instead of weakening the script.
4. Report the commands it runs and the time it took. The file belongs in the repo; commit it only when the user asks.
