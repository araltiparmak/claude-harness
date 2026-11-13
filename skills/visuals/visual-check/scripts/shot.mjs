#!/usr/bin/env node
// Screenshots pages at phone and desktop width, in light and dark mode, and lists layout problems.
// Usage: node shot.mjs <url|file> [more urls...] [--out dir]
// Writes <out>/<page>-<width>-<scheme>.png (full page, up to 6000px high) and prints one line per problem:
// a page wider than the screen, an element sticking out of it, a console error or an uncaught exception.
// Exit code 3 means problems were found; 2 means bad arguments or no browser.
// Uses the local Chrome over the DevTools protocol: no Playwright, nothing to install.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const VIEWS = [['phone', 390, 844, true], ['desktop', 1440, 900, false]];
const SCHEMES = ['light', 'dark'];
const MAX_HEIGHT = 6000;

const args = process.argv.slice(2);
const outAt = args.indexOf('--out');
const out = path.resolve(outAt >= 0 ? args[outAt + 1] : 'visual-check');
const pages = args.filter((_, i) => outAt < 0 || (i !== outAt && i !== outAt + 1))
  .map(a => /^[a-z]+:\/\//.test(a) ? a : pathToFileURL(path.resolve(a)).href);
if (!pages.length) { console.error('usage: shot.mjs <url|file> [more...] [--out dir]'); process.exit(2); }

const candidates = [process.env.CHROME, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/usr/bin/google-chrome', '/usr/bin/chromium'];
const bin = candidates.find(c => c && fs.existsSync(c));
if (!bin) { console.error('no Chrome found: set CHROME=/path/to/browser'); process.exit(2); }

// Runs in the page: elements whose right edge passes the screen, unless a scrolling or clipping parent holds them.
// The screen width is passed in: on a phone, innerWidth grows with content that is too wide.
const layout = (w, h) => `(() => {
  const w = ${w}, held = el => { for (let p = el.parentElement; p; p = p.parentElement)
    if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(p).overflowX)) return true; return false; };
  const name = el => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
    ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  // The box itself is too wide, or its content runs past the box (a long line in a <pre>).
  const end = el => { const r = el.getBoundingClientRect(); return Math.max(r.right,
    getComputedStyle(el).overflowX === 'visible' ? r.left + el.scrollWidth : 0); };
  const wide = [...document.body.querySelectorAll('*')].filter(el => end(el) > w + 1 && !held(el));
  const top = wide.filter(el => !wide.some(o => o !== el && el.contains(o))).slice(0, 5)
    .map(el => name(el) + ' "' + (el.textContent || '').trim().slice(0, 40) + '" ends at ' + Math.round(end(el)) + 'px');
  // The body's own height: a zoomed-out phone page stretches the document far below the content.
  const height = Math.ceil(Math.max(${h}, document.body.scrollHeight, document.body.getBoundingClientRect().bottom));
  return JSON.stringify({ height, width: document.documentElement.scrollWidth, wide: top });
})()`;

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'visual-check-'));
const chrome = spawn(bin, ['--headless', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
const portFile = path.join(profile, 'DevToolsActivePort');
for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await new Promise(r => setTimeout(r, 100));
const [port, wsPath] = fs.readFileSync(portFile, 'utf8').trim().split('\n');
const ws = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

let nextId = 0;
const waiting = new Map(), listeners = [];
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.id && waiting.has(msg.id)) {
    const { resolve, reject } = waiting.get(msg.id);
    waiting.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  } else listeners.forEach(fn => fn(msg));
};
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = ++nextId;
  waiting.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params, sessionId }));
});
const once = (method, sessionId) => new Promise(resolve => {
  const fn = msg => { if (msg.method === method && msg.sessionId === sessionId) { listeners.splice(listeners.indexOf(fn), 1); resolve(); } };
  listeners.push(fn);
});

fs.mkdirSync(out, { recursive: true });
let problems = 0;
const report = (where, text) => { problems++; console.log(`  PROBLEM  ${where}: ${text}`); };

for (const url of pages) {
  // A file is named after itself, a served page after its path: report, lessons-sqs, home.
  const where = new URL(url), file = where.protocol === 'file:';
  const base = ((file ? path.basename(where.pathname) : where.pathname).replace(/\.html?$/, '')
    .replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '') || 'home').slice(0, 60);
  for (const [view, width, height, mobile] of VIEWS) {
    for (const scheme of SCHEMES) {
      const where = `${base} ${view} ${scheme}`;
      const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
      const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
      const errors = [];
      const collect = msg => {
        if (msg.sessionId !== sessionId) return;
        if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
        if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') errors.push(msg.params.args.map(a => a.value ?? a.description).join(' '));
        if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') errors.push(`${msg.params.entry.text} ${msg.params.entry.url || ''}`.trim());
      };
      listeners.push(collect);
      await Promise.all(['Page.enable', 'Runtime.enable', 'Log.enable'].map(m => send(m, {}, sessionId)));
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile }, sessionId);
      await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] }, sessionId);
      const loaded = once('Page.loadEventFired', sessionId);
      await send('Page.navigate', { url }, sessionId);
      await Promise.race([loaded, new Promise(r => setTimeout(r, 15000))]);
      await new Promise(r => setTimeout(r, 800)); // fonts, late scripts and transitions
      const { result } = await send('Runtime.evaluate', { expression: layout(width, height), returnByValue: true }, sessionId);
      const page = JSON.parse(result.value);
      if (page.width > width + 1) report(where, `page is ${page.width}px wide on a ${width}px screen`);
      page.wide.forEach(text => report(where, `sticks out: ${text}`));
      [...new Set(errors)].slice(0, 5).forEach(text => report(where, `console: ${text.split('\n')[0].slice(0, 160)}`));
      const tall = Math.min(page.height, MAX_HEIGHT);
      const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
        clip: { x: 0, y: 0, width, height: tall, scale: 1 } }, sessionId);
      const file = path.join(out, `${base}-${width}-${scheme}.png`);
      fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
      console.log(`${file}${page.height > MAX_HEIGHT ? `  (first ${MAX_HEIGHT}px of ${page.height}px)` : ''}`);
      listeners.splice(listeners.indexOf(collect), 1);
      await send('Target.closeTarget', { targetId });
    }
  }
}

ws.close();
chrome.kill();
try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still be writing; it is a temp folder */ }
console.log(problems ? `${problems} problem(s) found` : 'no problems found');
process.exit(problems ? 3 : 0);
