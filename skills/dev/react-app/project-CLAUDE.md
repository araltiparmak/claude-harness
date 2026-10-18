# Prototype

This is a prototype. Speed over polish.

React + Vite + TypeScript + Tailwind v4, on pnpm and Node 24 LTS. Import from `src/` through the `@/` alias.

Tailwind v4 needs no config file and no PostCSS step — the `@tailwindcss/vite` plugin plus `@import "tailwindcss";` in `src/index.css` is the whole setup.

## Port

This project's dev server runs on **<PORT>** — `http://localhost:<PORT>`. It is pinned in `vite.config.ts` under `server` with `strictPort: true`, so each prototype keeps its own port and `pnpm dev` never silently lands somewhere else. Change it only if something else has permanently claimed the number, and change it in both places at once.

## Verification

Prove a change with `pnpm check` (typecheck, lint, build) and the running dev server (`pnpm dev`), and report what you saw. That is the standard of evidence here — when a test suite is wanted, say so and vitest goes in then.

## Scripts

| Command | What it does |
|---|---|
| `pnpm dev` | Dev server on this project's pinned port |
| `pnpm check` | `typecheck`, `lint` and `build` in order; run it before every commit |
| `pnpm typecheck` | `tsc -b` only, the fast check |
| `pnpm clean` | Removes `dist` and the Vite cache |
| `pnpm ship` | Clean git tree, then `pnpm check`, then deploy to the project's target |

How `pnpm ship` picks its deploy target is documented at the top of `scripts/ship.mjs`; edit that file when the project needs another step.

## Checkpoint

Before any change that touches several files, adds or removes a dependency, or deploys:

```bash
git status --porcelain
```

Empty means go. Anything listed gets committed first — so there is always a clean state to roll back to.

## Adding routes

```bash
pnpm add react-router
```

Deep links need an SPA fallback on the host. `vercel.json` already rewrites every path to `index.html`; on another host, add the same rule, or the app 404s on refresh and on shared deep links.

## Deploy

`pnpm ship` deploys to production. It uses the first target it finds: a `deploy` script in `package.json`, then `cloudflare.config.ts` (Cloudflare), then `vercel.json` (Vercel, set up when the project was created). The first Vercel deploy links the project; sign in once with `vercel login`.

- Vercel builds the source on its own machine. `engines.node` and `packageManager` in `package.json` pin its Node and pnpm, so keep them matching your machine.
- `VITE_` variables are inlined into the public bundle: never put a secret in one. `.env.local` does not reach Vercel; add each variable with `vercel env add NAME production`.
- After a deploy, check a deep route: `curl -sI <url>/any/route` returns 200 when the rewrite works.
