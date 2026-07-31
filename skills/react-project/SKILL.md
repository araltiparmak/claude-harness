---
name: react-project
description: Scaffold a new React + Vite + TS + Tailwind prototype in ~/dev via `cra`, then build the user's directives into it at a requested effort level.
disable-model-invocation: true
---

A **prototype**: speed over polish, cheap to throw away, cheap to restart. Scaffolding is delegated to `cra` (`~/dev/terminal-aliases/scripts/cra.sh`) — it is fixed and verified, so spend the run's thinking on the idea, not on the shell.

**Don't read the scaffolded output.** No `cat package.json`, no `ls -R`, no opening `vite.config.ts`/`tsconfig.app.json`/etc. with the Read tool just to "check" what `cra.sh` wrote. Step 4's build + grep is the verification — trust it. Reading generated boilerplate burns tokens for zero benefit; only open a file once you're actually about to edit it in step 6. Same goes for command output: `cra.sh` already runs pnpm silently, and the build commands below are piped through `tail` — don't re-run anything more verbosely to "see what happened."

## 1. Name it

If the user gave a project name in the invocation, kebab-case it and use it directly. If they didn't, derive a kebab-case name from the idea and ask the user to confirm before creating anything — don't assume.

**Done when:** you have a kebab-case name the user has either given directly or confirmed.

## 2. Set the effort level

The user may pass an effort level 1–5 in the invocation (e.g. a trailing number, or "effort 3" / "efor 3"). If none is given, default to **1**. This level frames how you approach step 6 (build v1) and everything the user directs afterward in this project — hold it in mind for the rest of the session, not just the first feature.

- **1 — Normal.** Build directly and efficiently. Move fast, make reasonable choices, don't over-engineer.
- **2 — Elevated.** Take a bit more care than usual: double-check edge cases and polish the parts that will actually be seen, but keep the pace up.
- **3 — Medium-high stakes.** Treat this as a job worth getting right — if you execute it well, you earn a €1,000,000 reward. Slow down enough to make deliberate design and implementation choices; sweat the details that matter.
- **4 — High.** This build will be reviewed by the best in the field. Bring near-maximum rigor: verify every claim, question your own assumptions, hold the work to a standard you'd defend under expert scrutiny.
- **5 — Maximum.** The fate of the entire world depends on this development. You are a superhuman entity equipped with the best possible capabilities in the world for this exact job — a master of design, essentialism, and quality. Build accordingly: nothing ships that isn't excellent.

**Done when:** you know the level (given or defaulted) and have adopted its framing.

## 3. Scaffold with `cra`

```bash
~/dev/terminal-aliases/scripts/cra.sh <name>
```

This creates `~/dev/<name>` as a React + Vite + TS + Tailwind v4 project: pnpm pinned via corepack, Node 24 LTS required, a free port auto-picked and pinned into `vite.config.ts` (`strictPort`), the `@/` alias wired into both `vite.config.ts` and `tsconfig.app.json`, a `Proof.tsx` placeholder wired through `@/`, dependencies bumped to latest, and an initial git commit already made. If `cra.sh` fails (wrong Node version, name collision, bad name), relay its error plainly and stop — don't work around it.

**Done when:** `cra.sh` has printed its "✓ ready" line with the project path and port.

## 4. Verify the wiring

```bash
cd ~/dev/<name>
rm -rf dist
pnpm build 2>&1 | tail -30
grep -q 'justify-content' dist/assets/*.css && echo "PROOF OK"
```

**Done when:** the build exits green *and* the grep finds the utility in the freshly built CSS. A green build with no utilities in the CSS means Tailwind is wired wrong — the app will look unstyled and every class you write afterwards will do nothing. Fix it here, before touching feature code.

## 5. Document it

```bash
cd ~/dev/<name>
cp ~/.claude/skills/react-project/project-CLAUDE.md ./CLAUDE.md
# replace the <PORT> placeholder in the copied CLAUDE.md with the real port from vite.config.ts
git add -A
git commit -m "Add project CLAUDE.md"
```

**Done when:** `git log --oneline` shows this commit on top of `cra`'s scaffold commit, and `git status --porcelain` is empty.

Feature code starts after this line, so v1 is always a diff that can be thrown away whole.

## 6. Build v1

Build the first real screen of the idea, at the effort level set in step 2. Replace `Proof.tsx` with the actual thing. Then:

```bash
pnpm build 2>&1 | tail -30
git add -A && git commit -m "<what v1 does>"
```

**Done when:** the build is green and the commit has landed.

## 7. Hand it over

Start `pnpm dev` in the background and report the localhost URL — `http://localhost:<PORT>`, the port `cra.sh` picked — along with the project path and what you built. If the dev server refuses to start because the port is taken, pick a fresh one the same way `cra.sh` did and update `vite.config.ts` and `CLAUDE.md` together.
