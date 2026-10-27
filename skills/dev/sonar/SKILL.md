---
name: sonar
description: Reads the SonarQube Cloud findings (issues and security hotspots) of a pull request, one line each, and fixes them. Use when the user asks about Sonar or SonarCloud findings, a failing quality gate, or code smells or hotspots on a PR.
---

# Sonar

The findings come from SonarQube Cloud's web API: the last analysis of the PR, nothing scanned locally.

1. From the repo, run `scripts/sonar.sh` (this skill's folder) for the current branch's PR, or `scripts/sonar.sh <number>` for another. It prints the analysed commit, the counts, then one line per finding: `path:line SEVERITY TYPE rule message`.
2. A `STALE` line means the PR has commits the analysis has not seen. Say so, and treat the findings as those of the analysed commit. Read the findings once and work from that list; the analysis of a new push takes a minute, and the PR's SonarCloud check shows when it is in. Wait for it only when the user asks, with `gh pr checks --watch` in the background.
3. Fix all findings in one pass, then run the project's typecheck and tests. For a finding you leave as it is, give the reason, so the user can mark it in SonarCloud.

Env: `SONAR_PROJECT` overrides the project key (default `owner_repo` from the `origin` remote); `SONAR_TOKEN` is needed only for a private project.
