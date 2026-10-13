# Prototype

This is a prototype. Speed over polish.

React + Vite + TypeScript + Tailwind v4, on pnpm and Node 24 LTS. Import from `src/` through the `@/` alias.

Tailwind v4 needs no config file and no PostCSS step — the `@tailwindcss/vite` plugin plus `@import "tailwindcss";` in `src/index.css` is the whole setup.

## Port

This project's dev server runs on **<PORT>** — `http://localhost:<PORT>`. It is pinned in `vite.config.ts` under `server` with `strictPort: true`, so each prototype keeps its own port and `pnpm dev` never silently lands somewhere else. Change it only if something else has permanently claimed the number, and change it in both places at once.

## Verification

Prove a change with `pnpm build` and the running dev server (`pnpm dev`), and report what you saw. That is the standard of evidence here — when a test suite is wanted, say so and vitest goes in then.

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

Deep links then need a rewrite in `vercel.json` — the `vercel` skill writes it. Without that rewrite the app deploys and navigates fine, then 404s on refresh or on any shared deep link.

## Deploy

Run the `vercel` skill (`/vercel`). It writes `vercel.json` and `.vercelignore`, pins Node and pnpm so Vercel's build matches the local one, links the project, ships a preview before production, and leaves a `pnpm run deploy:prod` script behind. Once that script exists, use it.

A deploy is a checkpoint — clean tree first.
