---
name: cloudflare
description: Deploys a project to Cloudflare Workers with the cf CLI (no Wrangler file). Use when the user says "deploy" or "ship" in a project that has cloudflare.config.ts, or for any other Cloudflare task (Workers, KV, D1, R2, DNS, logs).
---

# Cloudflare (cf CLI)

Use the `cf` CLI for every Cloudflare task, unless the project has a Wrangler configuration file (`wrangler.toml`, `wrangler.json` or `wrangler.jsonc`); then use `wrangler`.

## Deploy

1. If the project has a `ship` script (`pnpm run ship`), run that and stop. It checks everything in order.
2. Otherwise run these in order and stop at the first failure:
   1. `git status --porcelain` must be empty. If not, commit first (checkpoint).
   2. `cf auth whoami`. If not signed in, ask the user to type `! cf auth login` (needs their browser).
   3. `pnpm check` if the project has it, else `pnpm build`. `cf deploy` skips the type check.
   4. `pnpm run deploy` if that script exists, else `cf deploy`. Never bare `pnpm deploy`: that is a pnpm builtin and fails.
3. Report the URL and Version ID from the output.

`cloudflare.config.ts` stays the project's only Cloudflare config; leave Wrangler files out.
