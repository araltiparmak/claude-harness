---
name: cloudflare
description: Deploys a project to Cloudflare Workers with the cf CLI (no Wrangler file). Use when the user says "deploy" or "ship" in a project that has cloudflare.config.ts.
---

# Cloudflare (cf CLI)

1. If the project has a `ship` script (`pnpm run ship`), run that and stop. It checks everything in order.
2. Otherwise run these in order and stop at the first failure:
   1. `git status --porcelain` must be empty. If not, commit first (checkpoint).
   2. `cf auth whoami`. If not signed in, ask the user to type `! cf auth login` (needs their browser).
   3. The project's check and type-check build (`pnpm build`). `cf deploy` skips the type check.
   4. `pnpm run deploy` (= `cf deploy`). Never bare `pnpm deploy`: that is a pnpm builtin and fails.
3. Report the URL and Version ID from the output.

Do not add a Wrangler file.
