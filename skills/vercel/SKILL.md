---
name: vercel
description: Deploys a Vite/React project to Vercel, or repairs its deploy path. Use when the user says "deploy", "vercel'e at", "yayına al", or "ship it"; when a deployed SPA 404s on refresh; when an env var works locally but not in production; or when a build that is green locally fails on Vercel. Also the follow-up to a `react-project` scaffold.
---

Takes a working Vite + React project (typically one built by the `react-project` skill) and gives it a deployment path: config files, a pinned build environment, a linked Vercel project, a preview, then production.

**The mental model that explains every step below:** you are not uploading `dist/`. You upload *source*, and Vercel runs the build on its own machine. That is why the Node version has to be pinned (step 2), why `dist` belongs in `.vercelignore` (step 4), and why an env var in `.env.local` is invisible in production (step 5). A local build being green proves nothing about Vercel's build until those three match.

**Don't read files to "check" the project.** Step 1 tells you the handful of things worth looking at. Step 8 is the verification — trust it over inspection.

If `vercel` is not on `PATH`, do not install it globally; prefix every command below with `npx` (`npx vercel …`). If `vercel whoami` says you are not logged in, that login is interactive — ask the user to run `! vercel login` themselves and wait.

## 1. Check the ground

```bash
cd <project>
git status --porcelain
ls -d vercel.json vercel.ts .vercelignore .vercel 2>/dev/null
node -p "JSON.stringify(require('./package.json').scripts,null,1)"
```

Decide from the output, in this order:

- **The repo already documents its own deploy command** (a `deploy:*` script, a `scripts/deploy*.sh`, a line in `CLAUDE.md`) — run that, report the result, and stop. This skill builds a deploy path where there is none; it does not replace one that exists.
- **A dirty tree** — commit first. A deploy is a checkpoint: there must be a clean commit to roll back to and to match against what went live.
- **`vercel.ts` exists** — put the configuration there instead of `vercel.json`. Vercel permits exactly one config file; shipping both is a build error. `vercel.ts` is only worth it when config must be *computed* at build time (env-dependent routes, generated headers); for everything else `vercel.json` is the default.
- **`vercel.json` / `.vercelignore` already exist** — read them and merge, don't overwrite. Someone put those rules there for a reason.

**Done when:** the tree is clean and you know which of the four cases you are in.

## 2. Pin the build environment

The classic first-deploy failure is a green local build and a red Vercel build, because Vercel chose a different Node major or a different pnpm than the machine the lockfile was written on. Pin both in `package.json`:

```json
{
  "engines": { "node": "24.x" },
  "packageManager": "pnpm@10.34.5"
}
```

- `engines.node` **overrides** the Node version set in the Vercel dashboard, which is what you want — the repo is the source of truth, and nobody has to remember a dashboard setting.
- `packageManager` needs an exact version, not a range. Read the real one with `pnpm -v` and write that string.
- **Stay on pnpm 10.** Vercel supports pnpm 6–10 natively; 11 runs only behind an experimental Corepack flag.
- Commit `pnpm-lock.yaml`. pnpm defaults to `--frozen-lockfile` under CI, so a lockfile that drifted from `package.json` fails the build instead of quietly resolving fresh.

**Done when:** both fields are present with real values, and `pnpm build` is still green locally.

## 3. Write `vercel.json`

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "vite",
  "outputDirectory": "dist",
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    },
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" },
        { "key": "X-Frame-Options", "value": "DENY" }
      ]
    }
  ]
}
```

What each line is doing, so you can drop the ones that don't apply:

- **`$schema`** — gives the editor autocomplete and catches typo'd keys, which otherwise fail silently at deploy time.
- **`framework` / `outputDirectory`** — auto-detection usually gets these right; stating them makes CLI deploys deterministic instead of dependent on what the dashboard inferred.
- **`rewrites`** — the one line an SPA cannot ship without. Client-side routing works fine while navigating, then every page refresh and every shared deep link 404s, because those paths don't exist as files. The destination is `/index.html`, not `/` — `/` is only correct when `cleanUrls: true`. Vercel checks the filesystem *before* rewrites, so real files under `/assets/` still serve normally.
- **Asset caching** — Vite content-hashes everything it emits into `dist/assets/`, so the filename changes whenever the content does and a one-year `immutable` is safe. Never put a long `max-age` on `index.html`; leave it at Vercel's default so a new deploy is visible immediately instead of after a cache expiry.
- **Security headers** — cheap and always applicable. Drop `X-Frame-Options` if the app is meant to be embedded in an iframe.

One tradeoff to state out loud rather than discover later: the catch-all rewrite makes unknown paths return `index.html` with HTTP **200**, not 404. That is correct for an app and wrong for a crawler. If real 404 statuses matter, narrow `source` to the route prefixes the app actually owns.

**Done when:** the file is written and `pnpm build` still passes (it is untouched by this, but a syntax-broken JSON is worth catching now).

## 4. Write `.vercelignore`

```
# Vercel already skips .git, node_modules, .vercel, .env.local, .DS_Store and
# friends. Repeat anything that matters anyway: with --archive=tgz the uploader
# does not apply .gitignore directory patterns reliably, and .vercelignore is
# the only exclusion list it always honours.

# Local build output — Vercel runs its own build, this is pure upload weight
dist
dist-ssr

# Editor and tooling dirs
.idea
.vscode
.DS_Store

*.log
*.local
```

Add every local-only heavy directory on top of that: design sources, scans, datasets, generated media, anything large the build does not read.

**`.vercelignore` is not a secret filter.** Everything not excluded is uploaded to a build container. Secrets go in environment variables, never in a file that merely happens to be ignored.

**Done when:** the file exists and `dist` is in it.

## 5. Get the environment variables right

Vite exposes only variables prefixed `VITE_` to client code, and it **inlines their values into the bundle at build time**. Two consequences that bite people:

1. **A `VITE_` variable is public.** Its value ships inside the JavaScript and can be read back out of the deployed site with one `curl`. Never put an API key, token, or database URL in one. A real secret belongs behind a serverless function under `api/`, not in the client bundle.
2. **`.env.local` never reaches Vercel** — it is on the default-ignore list. A variable that works locally and is `undefined` in production was simply never added on Vercel's side. That is the whole bug, every time.

```bash
vercel env add VITE_API_URL production    # also: preview, development — value read from stdin
vercel env pull .env.local                # pull remote vars down for local dev
```

For a one-off build-time value that should not be stored on the project:

```bash
vercel deploy --prod -b VITE_LANG=de
```

`-b` is also how one repo deploys to several Vercel projects with different build-time configuration — pair it with `--project <name>` per target.

**Done when:** every `VITE_` variable the code reads exists on Vercel for the environments being deployed, or there are none.

## 6. Link the project

```bash
vercel link
```

First time only. It writes `.vercel/project.json` (org id + project id) and adds `.vercel` to `.gitignore` — leave it out of the repo; it is machine state, not source. Non-interactive variants: `vercel link --yes` accepts the detected defaults, `--project <name>` targets an existing project instead of creating one.

Skip `vercel dev`. For a static SPA it is slower than and identical to `pnpm dev`; it only starts to matter once there are Vercel Functions under `api/`.

**Done when:** `.vercel/project.json` exists and `.vercel` is gitignored.

## 7. Preview first, then production

```bash
vercel deploy
```

That is a preview deployment. Open the URL it prints and confirm the app actually loads and routes. Only then:

```bash
vercel deploy --prod
```

Never make the first deploy a `--prod` one: the preview is the cheap chance to catch a broken build or a missing env var without anything user-facing going wrong. If a shared preview link asks the recipient to log in, that is Vercel Authentication on the project (plan-dependent), not a broken deploy.

Two flags worth knowing before they are needed:

- `--archive=tgz` uploads one tarball instead of N files. Use it once a repo carries thousands of static assets (audio, images) — per-file upload hits rate limits and the 15,000-file ceiling.
- `--force` redeploys ignoring Vercel's build cache. Reach for it only when a build behaves stale in a way the source doesn't explain.

**Done when:** production has been deployed and you have its URL.

## 8. Prove the deploy

A green deploy is not evidence the config landed. The two things most likely to be silently wrong are the SPA rewrite and the headers, so check both:

```bash
URL="https://<the-production-url>"

curl -sI "$URL/" | head -1                                # 200
curl -sI "$URL/a/deep/route" | head -1                    # 200 → rewrite works
ASSET=$(curl -s "$URL/" | grep -o '/assets/[^"]*\.js' | head -1)
curl -sI "$URL$ASSET" | grep -i cache-control             # immutable → headers work
```

**Done when:** the deep route returns 200 and the asset's `Cache-Control` contains `immutable`.

Reading failures:

- **Deep route 404s** → `rewrites` did not apply. Wrong filename, invalid JSON, or a `vercel.ts` present alongside `vercel.json`.
- **No `immutable`** → `headers` did not apply, same causes.
- **Build failed** → open the "Inspect" URL the CLI printed, or `vercel inspect --logs <deployment-url>`. In practice it is one of three things: a Node major mismatch (step 2), a lockfile out of sync with `package.json` (step 2), or a `VITE_` variable that only ever existed in `.env.local` (step 5).

## 9. Make the next deploy one command

```json
"scripts": { "deploy:prod": "vercel deploy --prod" }
```

Name it **`deploy:prod`**, not `deploy` — `pnpm deploy` is a built-in pnpm command and will run that instead of the script.

Then record it where the next session will look, and commit:

```bash
# add a Deploy section to CLAUDE.md: the command, the live URL, the project name
git add -A && git commit -m "Add Vercel config and deploy"
```

**Done when:** `git status --porcelain` is empty and `CLAUDE.md` names the deploy command and the live URL.

A custom domain, if wanted, goes in the dashboard (Project → Domains) or `vercel domains add <domain>`. DNS propagation is the slow part, not the deploy.
