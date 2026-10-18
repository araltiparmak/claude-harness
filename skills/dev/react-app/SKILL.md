---
name: react-app
description: Scaffold a new React + Vite + TS + Tailwind prototype via `cra` (in `CRA_DIR`, default ~/dev), then build the user's directives into it at a requested effort level.
disable-model-invocation: true
---

A **prototype**: speed over polish, cheap to throw away, cheap to restart. Scaffolding is delegated to `cra.sh`, which ships in this skill's folder — it is fixed and verified, so spend the run's thinking on the idea, not on the shell.

Step 4's build and grep is the verification of what `cra.sh` wrote; open a generated file only when you are about to edit it.

## 1. Name it

If the user gave a project name in the invocation, kebab-case it and use it directly. If they didn't, derive a kebab-case name from the idea and ask the user to confirm before creating anything — don't assume.

**Done when:** you have a kebab-case name the user has either given directly or confirmed.

## 2. Set the effort level

The user may pass an effort level 1–5 in the invocation (e.g. a trailing number, or "effort 3"). If none is given, default to **1**. This level frames how you approach step 6 (build v1) and everything the user directs afterward in this project — hold it in mind for the rest of the session, not just the first feature.

- **1 — Normal.** Build directly and efficiently. Move fast, make reasonable choices, don't over-engineer.
- **2 — Elevated.** Take a bit more care than usual: double-check edge cases and polish the parts that will actually be seen, but keep the pace up.
- **3 — Deliberate.** Make design and implementation choices on purpose, not by default. Handle empty, loading and error states, and check the layout at phone and desktop widths.
- **4 — High.** Verify every claim, question your own assumptions, and hold the work to a standard you would defend under expert review.
- **5 — Maximum.** Everything in 4, plus: cut anything that does not serve the idea, refine spacing, typography and interaction until nothing looks unfinished, and ship nothing that is not excellent.

**Done when:** you know the level (given or defaulted) and have adopted its framing.

## 3. Scaffold with `cra`

```bash
~/.claude/skills/react-app/cra.sh <name>
```

This creates `$CRA_DIR/<name>` (default `~/dev`) with a free port pinned in `vite.config.ts`, the `@/` alias, a `Proof.tsx` placeholder, the scripts `typecheck`, `check`, `clean` and `ship`, and an initial commit. If `cra.sh` fails (wrong Node version, name collision, bad name), relay its error plainly and stop.

**Done when:** `cra.sh` has printed its "✓ ready" line with the project path and port.

## 4. Verify the wiring

```bash
cd <project path>
set -o pipefail; pnpm build 2>&1 | tail -30 && grep -q 'justify-content' dist/assets/*.css && echo "PROOF OK"
```

**Done when:** the build exits green *and* the grep finds the utility in the freshly built CSS. A green build with no utilities in the CSS means Tailwind is wired wrong — the app will look unstyled and every class you write afterwards will do nothing. Fix it here, before touching feature code.

## 5. Document it

```bash
cd <project path>
PORT=$(grep -oE 'port: [0-9]+' vite.config.ts | grep -oE '[0-9]+')
sed "s/<PORT>/$PORT/g" ~/.claude/skills/react-app/project-CLAUDE.md > CLAUDE.md
git add -A
git commit -m "Add project CLAUDE.md"
```

**Done when:** `git log --oneline` shows this commit on top of `cra`'s scaffold commit, and `git status --porcelain` is empty.

Feature code starts after this line, so v1 is always a diff that can be thrown away whole.

## 6. Build v1

Build the first real screen of the idea, at the effort level set in step 2. Replace `Proof.tsx` with the actual thing. Then:

```bash
set -o pipefail; pnpm check 2>&1 | tail -30 && git add -A && git commit -m "<what v1 does>"
```

**Done when:** `pnpm check` (typecheck, lint, build) is green and the commit has landed.

## 7. Hand it over

Start `pnpm dev` in the background and report the localhost URL — `http://localhost:<PORT>`, the port `cra.sh` picked — along with the project path and what you built. If the dev server refuses to start because the port is taken, pick a fresh one the same way `cra.sh` did and update `vite.config.ts` and `CLAUDE.md` together.

When the user wants it live, `pnpm ship` checks that the git tree is clean, runs `pnpm check`, then deploys to the project's target. It needs a target first, and picks the first it finds: a `deploy` script in `package.json`, then a `cloudflare.config.ts` (Cloudflare), then Vercel config (the `vercel` skill writes it). Without one, `ship` stops after the checks with exit code 3 and says so.
