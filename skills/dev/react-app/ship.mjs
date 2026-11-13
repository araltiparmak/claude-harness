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
// cli: the host's command. local: how to run it when it is not installed globally. whoami: the sign-in check.
const targets = [
  { name: 'package.json deploy script', found: scripts.deploy, cli: ['pnpm'], deploy: ['run', 'deploy'] },
  { name: 'Cloudflare Workers', found: existsSync('cloudflare.config.ts'), cli: ['cf'], local: ['pnpm', 'exec', 'cf'],
    deploy: ['deploy'], whoami: ['auth', 'whoami'], signIn: 'not signed in to Cloudflare, or the cf CLI is missing. Run: cf auth login' },
  { name: 'Vercel', found: ['vercel.json', 'vercel.ts', '.vercel'].some(existsSync), cli: ['vercel'], local: ['npx', 'vercel'],
    deploy: ['deploy', '--prod', '--yes'], whoami: ['whoami'], signIn: 'not signed in to Vercel. Run: vercel login' },
]
const target = targets.find((t) => t.found)
if (!target) {
  console.log('\n✓ checks passed, but there is no deploy target, so nothing was deployed.')
  console.log('  Add a "deploy" script, a cloudflare.config.ts, or a vercel.json.')
  process.exit(3)
}

let [cmd, ...pre] = target.cli
if (target.local && read(cmd, ['--version']).status !== 0) [cmd, ...pre] = target.local
if (target.whoami && read(cmd, [...pre, ...target.whoami]).status !== 0) fail(target.signIn)

step(`deploying to ${target.name}`)
if (run(cmd, [...pre, ...target.deploy]).status !== 0) fail(`deploy to ${target.name} failed`)
console.log(`\n✓ shipped to ${target.name}`)
