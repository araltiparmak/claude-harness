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

Deep links then need an SPA fallback on the host (the `vercel` skill writes it into `vercel.json`). Without it the app navigates fine, then 404s on refresh or on any shared deep link.

## Deploy

Set up a target once with the `vercel` or `cloudflare` skill; after that `pnpm ship` deploys to production.
