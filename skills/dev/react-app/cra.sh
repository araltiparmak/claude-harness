#!/usr/bin/env bash
# cra — React + Vite + TS + Tailwind v4 scaffolder (pnpm). Step 3 of the
# react-app skill; alias it in your shell to run it from anywhere.
set -euo pipefail

NODE_MAJOR=24
PNPM_MAJOR=10
PROJECTS_DIR="${CRA_DIR:-$HOME/dev}"   # where new projects go; set CRA_DIR to change it
case "$PROJECTS_DIR" in /*) ;; *) PROJECTS_DIR="$PWD/$PROJECTS_DIR" ;; esac   # absolute, so the cleanup trap still works after cd

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\033[36m▸\033[0m %s\n' "$*"; }

NAME="${1:-}"
TARGET="${2:-vercel}"   # where pnpm ship deploys: vercel or cloudflare
case "$NAME" in
  ''|-h|--help) echo "usage: cra <kebab-case-name> [vercel|cloudflare]   (creates $PROJECTS_DIR/<name>; the react-app skill has the details)"; exit 0 ;;
  *) ;;
esac

[[ "$NAME" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || die "name must be kebab-case: '$NAME'"
case "$TARGET" in vercel|cloudflare) ;; *) die "target must be vercel or cloudflare: '$TARGET'" ;; esac

DEST="$PROJECTS_DIR/$NAME"
[[ -e "$DEST" ]] && die "$DEST already exists"

NODE_V="$(node -v 2>/dev/null || true)"
[[ "$NODE_V" == v${NODE_MAJOR}.* ]] || die "Node ${NODE_MAJOR}.x required, found ${NODE_V:-none}"

step "pinning pnpm@${PNPM_MAJOR} via corepack"
corepack enable
corepack prepare "pnpm@${PNPM_MAJOR}" --activate

step "picking a free port"
PORT=""
for _ in $(seq 1 200); do
  P=$((RANDOM % 6000 + 4000))
  lsof -i :"$P" >/dev/null 2>&1 || { PORT=$P; break; }
done
[[ -n "$PORT" ]] || die "no free port found in 4000-9999"
echo "  port $PORT"

step "scaffolding $DEST"
mkdir -p "$DEST"
trap 'rm -rf "$DEST"' EXIT
cd "$DEST"
LOG="$(mktemp "${TMPDIR:-/tmp}/cra.XXXXXX")"
pnpm create vite@latest . --template react-ts </dev/null >"$LOG" 2>&1 \
  || die "pnpm create vite failed — see $LOG"
pnpm install --silent || die "pnpm install failed"
pnpm add -d tailwindcss@latest @tailwindcss/vite@latest --silent \
  || die "installing tailwind failed"

step "wiring tailwind, @/ alias and port $PORT"
cat > vite.config.ts <<EOF
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: { port: $PORT, strictPort: true },
})
EOF

echo '@import "tailwindcss";' > src/index.css

# paths only — baseUrl is deprecated in TypeScript 6 and fails the build.
# perl, not sed -i: the in-place flag differs between BSD and GNU sed.
grep -q '"paths"' tsconfig.app.json \
  || perl -pi -e 's|"compilerOptions": \{|"compilerOptions": {\n    "paths": { "\@/*": ["./src/*"] },|' tsconfig.app.json
grep -q '"paths"' tsconfig.app.json || die "failed to add paths to tsconfig.app.json"

rm -f src/App.css
mkdir -p src/components
cat > src/components/Proof.tsx <<'EOF'
export function Proof() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <p className="rounded-lg bg-slate-800 px-6 py-4 text-xl font-semibold text-emerald-400">
        Tailwind + @/ alias OK
      </p>
    </div>
  )
}
EOF
cat > src/App.tsx <<'EOF'
import { Proof } from '@/components/Proof'

export default function App() {
  return <Proof />
}
EOF

step "bumping dependencies to latest"
pnpm up --latest --silent || die "pnpm up --latest failed"

step "adding project scripts (typecheck, check, clean, ship)"
mkdir -p scripts
PNPM_VERSION="$(pnpm -v)" NODE_MAJOR="$NODE_MAJOR" node - <<'NODE'
const fs = require('node:fs')
const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'))
pkg.scripts = {
  ...pkg.scripts,
  typecheck: 'tsc -b',
  check: 'pnpm typecheck && pnpm lint && pnpm build',
  clean: "node -e \"for (const p of ['dist', 'node_modules/.vite']) require('node:fs').rmSync(p, { recursive: true, force: true })\"",
  ship: 'node scripts/ship.mjs',
}
// Pin the Node major and the exact pnpm, so a build on the host matches this machine.
pkg.engines = { node: `${process.env.NODE_MAJOR}.x` }
pkg.packageManager = `pnpm@${process.env.PNPM_VERSION}`
fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2) + '\n')
NODE
cat > scripts/ship.mjs <<'EOF'
// ship: clean git tree, then `pnpm check`, then deploy. Stops at the first failure.
// Deploy target, first match wins:
//   1. a "deploy" script in package.json   -> pnpm run deploy
//   2. cloudflare.config.ts                -> cf deploy
//   3. vercel.json, vercel.ts or .vercel   -> vercel deploy --prod --yes (the first run links the project)
// Exit codes: 0 shipped, 1 a step failed, 3 checks passed but there is no deploy target.
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'

const run = (cmd, args) => spawnSync(cmd, args, { stdio: 'inherit' })
const read = (cmd, args) => spawnSync(cmd, args, { encoding: 'utf8' })
const step = (msg) => console.log(`\n▸ ${msg}`)
const fail = (msg) => { console.error(`\n✗ ${msg}`); process.exit(1) }

step('git tree is clean')
const dirty = read('git', ['status', '--porcelain']).stdout.trim()
if (dirty) fail(`uncommitted changes. Commit first, so there is a clean state to roll back to:\n${dirty}`)

step('pnpm check (typecheck, lint, build)')
if (run('pnpm', ['run', 'check']).status !== 0) fail('check failed, nothing was deployed')

const scripts = JSON.parse(readFileSync('package.json', 'utf8')).scripts ?? {}
let name, command, args
if (scripts.deploy) [name, command, args] = ['package.json deploy script', 'pnpm', ['run', 'deploy']]
else if (existsSync('cloudflare.config.ts')) [name, command, args] = ['Cloudflare Workers', 'cf', ['deploy']]
else if (['vercel.json', 'vercel.ts', '.vercel'].some(existsSync)) [name, command, args] = ['Vercel', 'vercel', ['deploy', '--prod', '--yes']]

if (!command) {
  console.log('\n✓ checks passed, but there is no deploy target, so nothing was deployed.')
  console.log('  Add a "deploy" script, a cloudflare.config.ts, or a vercel.json.')
  process.exit(3)
}

if (command === 'cf') {
  if (read('cf', ['--version']).status !== 0) [command, args] = ['pnpm', ['exec', 'cf', ...args]]
  const who = command === 'pnpm' ? read('pnpm', ['exec', 'cf', 'auth', 'whoami']) : read('cf', ['auth', 'whoami'])
  if (who.error || who.status !== 0) fail('not signed in to Cloudflare, or the cf CLI is missing. Run: cf auth login')
}
if (command === 'vercel') {
  if (read('vercel', ['--version']).status !== 0) [command, args] = ['npx', ['vercel', ...args]]
  const who = command === 'npx' ? read('npx', ['vercel', 'whoami']) : read('vercel', ['whoami'])
  if (who.status !== 0) fail('not signed in to Vercel. Run: vercel login')
}

step(`deploying to ${name}`)
if (run(command, args).status !== 0) fail(`deploy to ${name} failed`)
console.log(`\n✓ shipped to ${name}`)
EOF

if [[ "$TARGET" == vercel ]]; then
step "writing Vercel config"
cat > vercel.json <<'EOF'
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "vite",
  "outputDirectory": "dist",
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }],
  "headers": [
    { "source": "/assets/(.*)", "headers": [{ "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }] },
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
EOF
# Vercel uploads source and builds it there: keep local build output and tooling out of the upload.
printf '%s\n' dist .idea .vscode .DS_Store '*.log' '*.local' > .vercelignore
grep -qx '.vercel' .gitignore 2>/dev/null || echo '.vercel' >> .gitignore
else
step "writing Cloudflare config"
# The 2.x beta of the Vite plugin is the one that reads cloudflare.config.ts (1.x needs a Wrangler file).
pnpm add -D cf@latest @cloudflare/vite-plugin@beta --silent || die "installing cf and the Cloudflare Vite plugin failed"
perl -0pi -e "s|import tailwindcss from '\@tailwindcss/vite'\n|import tailwindcss from '\@tailwindcss/vite'\nimport { cloudflare } from '\@cloudflare/vite-plugin'\n|; s|plugins: \[react\(\), tailwindcss\(\)\]|plugins: [react(), tailwindcss(), cloudflare()]|" vite.config.ts
grep -q 'cloudflare()' vite.config.ts || die "failed to add the Cloudflare plugin to vite.config.ts"
# The project name becomes the Worker name; the build is served as static assets.
cat > cloudflare.config.ts <<EOF
import { defineConfig } from "cf/config";

export default defineConfig({
  worker: {
    name: "$NAME",
    compatibilityDate: "$(date +%F)",
    observability: { enabled: true },
    assets: { notFoundHandling: "single-page-application" },
  },
});
EOF
printf '%s\n' .cloudflare .wrangler >> .gitignore
fi

step "verifying Tailwind in the build"
pnpm build >"$LOG" 2>&1 || die "pnpm build failed — see $LOG"
# A green build with no utilities in the CSS means Tailwind is not wired: every class would do nothing.
# The Cloudflare plugin builds into .cloudflare/output instead of dist.
css_files="$(find dist .cloudflare -name '*.css' 2>/dev/null || true)"
if [[ -z "$css_files" ]] || ! printf '%s\n' "$css_files" | xargs grep -q 'justify-content'; then
  die "the built CSS has no Tailwind utilities; check @tailwindcss/vite in vite.config.ts"
fi

step "committing"
git init -b main -q
git add -A
git commit -q -m "Scaffold React + Vite + TS + Tailwind project"
[[ -z "$(git status --porcelain)" ]] || die "working tree not clean after commit"
trap - EXIT

printf '\n\033[32m✓ ready\033[0m  %s\n' "$DEST"
printf '  dev server : \033[4mhttp://localhost:%s\033[0m  (pnpm dev)\n' "$PORT"
printf '  next       : replace src/components/Proof.tsx with the real thing\n'
