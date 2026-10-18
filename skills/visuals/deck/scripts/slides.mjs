#!/usr/bin/env node
// Builds a presentation deck from a JSON spec.
// Usage: node slides.mjs <deck.json> [out-dir] [--format pdf,png,html]
// Writes deck.pdf, slide-NN.png (2x) and deck.html (a presenter: arrow keys, F for fullscreen), then prints the layout check.
// Exit code 2 means the spec is invalid; 3 means a slide failed the layout check (text clipped or overflowing).
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const W = 1280, H = 720, PAD_X = 64, PAD_TOP = 52, FOOT = 48;
const CONTENT_W = W - 2 * PAD_X;

const DEFAULT_THEME = {
  ink: '#0b0b0b', ink2: '#52514e', muted: '#898781',
  grid: '#e8e7e1', axis: '#c3c2b7', context: '#dedcd5', contextLine: '#b5b2a9', surface: '#ffffff',
  good: '#006300', bad: '#b42318',
  // Inter comes from `brew install --cask font-inter`; without it the system font is used and the lint says so.
  font: '"Inter", system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif',
  display: '"Inter Display", "Inter", system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif',
};
// Each hue has four steps: bg (card wash), tint (title slide shapes), mark (chart mark, readable on white), ink (text on bg).
const PALETTE = [
  { name: 'blue', bg: '#dbe5ff', tint: '#2453d6', mark: '#2453d6', ink: '#0d2a7a' },
  { name: 'green', bg: '#d2f0e2', tint: '#0e8a5f', mark: '#0e8a5f', ink: '#06523a' },
  { name: 'orange', bg: '#ffe0cc', tint: '#e0560b', mark: '#d4520a', ink: '#7f2f00' },
  { name: 'violet', bg: '#e5ddfd', tint: '#5b34d4', mark: '#5b34d4', ink: '#33188c' },
  { name: 'amber', bg: '#fbe9b0', tint: '#e0a100', mark: '#b07a00', ink: '#5c3f00' },
  { name: 'red', bg: '#fcd9e1', tint: '#d0244c', mark: '#d0244c', ink: '#850f2c' },
];
// Fixed palette: green, red and amber keep their meaning; violet marks a decision.
let th = { ...DEFAULT_THEME, palette: PALETTE, accent: PALETTE[0].mark, accentInk: PALETTE[0].ink, accentWash: PALETTE[0].bg };
const hue = i => th.palette[((i % th.palette.length) + th.palette.length) % th.palette.length];
// Semantic hues (good, bad, warning, emphasis) by name, falling back to the first hue.
const hueExcept = (i, name) => { const list = th.palette.filter(h => h.name !== name); return list.length ? list[i % list.length] : hue(i); };
const role = name => th.palette.find(h => h.name === name) || th.palette[0];
const hv = h => `--bg:${h.bg};--tint:${h.tint};--mark:${h.mark};--ink:${h.ink}`;

// ---------- text and number helpers ----------

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
const decimalsOf = n => (String(+n.toFixed(10)).split('.')[1] || '').length;

function fmt(v, f = {}, signed = false) {
  const d = f.decimals ?? (Number.isInteger(v) ? 0 : 1);
  const n = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sign = v < 0 ? '−' : signed && v > 0 ? '+' : '';
  return sign + (f.prefix || '') + n + (f.suffix || '');
}

// Change between two numbers as display text. Rates (suffix %) default to points,
// because a percent change of a percent reads like the value itself.
function change(before, after, f = {}, mode, better = 'higher') {
  const d = after - before, pct = before ? d / before * 100 : 0;
  mode = mode || (f.suffix === '%' ? 'points' : 'percent');
  const abs = mode === 'points' ? `${fmt(Math.abs(d), { decimals: f.decimals ?? (Number.isInteger(d) ? 0 : 1) })} pt`
    : mode === 'diff' ? fmt(Math.abs(d), { ...f, suffix: f.suffix === '%' ? ' pt' : f.suffix })
    : `${Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%`;
  return { d, abs, signed: (d < 0 ? '−' : '+') + abs, good: (d >= 0) === (better === 'higher'), pct };
}

function ticks(min, max, count = 4) {
  if (min === max) max = min + 1;
  const raw = (max - min) / count, p = 10 ** Math.floor(Math.log10(raw)), m = raw / p;
  const step = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  const out = [];
  for (let v = Math.floor(min / step) * step; v <= Math.ceil(max / step) * step + step / 1e6; v += step) out.push(+v.toFixed(10));
  return out;
}

// Rough rendered width of system sans text, used only to size chart margins and header height.
const textW = (s, size, weight = 400) => String(s).length * size * (weight >= 600 ? 0.56 : 0.52);
const lines = (s, size, width, weight) => Math.max(1, Math.ceil(textW(s, size, weight) / width));

function headerHeight(slide) {
  let h = lines(slide.title, 36, 1080, 650) * 42.5;
  if (slide.subtitle) h += 12 + lines(slide.subtitle, 19, 980) * 27.5;
  return h;
}
// Height left for <main> once header, paddings and footer are taken.
// The first render pass measures the real height and stores it in slide._mh.
const mainHeight = slide => slide._mh ?? H - PAD_TOP - FOOT - 36 - 28 - headerHeight(slide);

// ---------- SVG marks ----------

function spark(values, w, h, c = hue(0)) {
  if (!values?.length) return '';
  const min = Math.min(...values), max = Math.max(...values), pad = 6;
  const x = i => pad + i * (w - 2 * pad) / Math.max(1, values.length - 1);
  const y = v => pad + (h - 2 * pad) * (1 - (max === min ? 0.5 : (v - min) / (max - min)));
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const lx = x(values.length - 1), ly = y(values.at(-1));
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
<polyline points="${pts}" fill="none" stroke="${c.mark}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
<circle cx="${lx}" cy="${ly}" r="5" fill="${c.ink}" stroke="${th.surface}" stroke-width="2"/></svg>`;
}

const deltaHtml = (delta, good, vs) => {
  if (!delta) return '';
  const down = /^[-−]/.test(delta);
  return `<div class="delta ${good === false ? 'bad' : 'good'}"><span class="arrow">${down ? '▼' : '▲'}</span>${esc(delta.replace(/^[-−+]/, ''))}${vs ? ` <span class="vs">${esc(vs)}</span>` : ''}</div>`;
};

// ---------- charts ----------

function lineChart({ labels, series, format = {}, markers = [], target, zero, w, h }) {
  const all = series.flatMap(s => s.values).concat(target ? [target.value] : []);
  let min = Math.min(...all);
  const max = Math.max(...all);
  if (zero ?? (min >= 0 && min < max * 0.5)) min = Math.min(0, min);
  const tk = ticks(min, max, 4), lo = tk[0], hi = tk.at(-1);
  const tf = { ...format, decimals: decimalsOf(tk[1] - tk[0]) };
  const L = Math.max(...tk.map(t => textW(t === 0 ? '0' : fmt(t, tf), 13))) + 20, R = 110, T = markers.length ? 44 : 16, B = 36;
  const iw = w - L - R, ih = h - T - B;
  const x = i => L + i * iw / Math.max(1, labels.length - 1);
  const y = v => T + ih - (v - lo) / (hi - lo) * ih;
  let g = '';
  for (const t of tk) {
    g += `<line x1="${L}" x2="${L + iw}" y1="${y(t)}" y2="${y(t)}" stroke="${t === lo ? th.axis : th.grid}"/>`;
    g += `<text x="${L - 12}" y="${y(t) + 4.5}" text-anchor="end" class="tick">${t === 0 ? '0' : esc(fmt(t, tf))}</text>`;
  }
  const every = Math.ceil(labels.length / 12);
  labels.forEach((l, i) => {
    if (i % every === 0 || i === labels.length - 1) g += `<text x="${x(i)}" y="${T + ih + 26}" text-anchor="middle" class="tick">${esc(l)}</text>`;
  });
  for (const m of markers) {
    const i = labels.indexOf(m.at);
    if (i < 0) continue;
    g += `<line x1="${x(i)}" x2="${x(i)}" y1="8" y2="${T + ih}" stroke="${th.ink2}" stroke-width="1"/>`;
    g += `<text x="${x(i) + 8}" y="22" class="note">${esc(m.label)}</text>`;
  }
  if (target) {
    const ty = y(target.value);
    g += `<line x1="${L}" x2="${L + iw}" y1="${ty}" y2="${ty}" stroke="${th.muted}" stroke-width="1.5"/>`;
    g += `<text x="${L + 8}" y="${ty - 8}" class="note">${esc(target.label || 'Target ' + fmt(target.value, format))}</text>`;
  }
  const focus = series[0], fy = y(focus.values.at(-1));
  const pts = focus.values.map((v, i) => [x(i), y(v)]);
  // The focus wash goes first so comparison lines stay visible on top of it.
  if (lo === 0 || min === 0) {
    const base = y(lo);
    g += `<path d="M${pts[0][0]},${base}L${pts.map(p => p.join(',')).join('L')}L${pts.at(-1)[0]},${base}Z" fill="${th.accentWash}"/>`;
  }
  for (const s of series.slice(1)) {
    const pts = s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ');
    g += `<polyline points="${pts}" fill="none" stroke="${th.contextLine}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;
    let ly = y(s.values.at(-1));
    if (Math.abs(ly - fy) < 26) ly = ly > fy ? fy + 26 : fy - 26;
    g += `<text x="${x(s.values.length - 1) + 12}" y="${ly + 5}" class="note">${esc(s.name)}</text>`;
  }
  g += `<polyline points="${pts.map(p => p.join(',')).join(' ')}" fill="none" stroke="${th.accent}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;
  const [ex, ey] = pts.at(-1);
  g += `<circle cx="${ex}" cy="${ey}" r="6" fill="${th.accent}" stroke="${th.surface}" stroke-width="2.5"/>`;
  g += `<text x="${ex + 14}" y="${ey + 6.5}" class="endv">${esc(focus.display ?? fmt(focus.values.at(-1), format))}</text>`;
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(focus.name || 'trend')}">${g}</svg>`;
}

// ---------- slide types ----------

const legend = series => series.length < 2 ? '' : `<div class="legend">${series.map((s, i) =>
  `<span><i style="background:${i === 0 ? th.accent : th.contextLine}"></i>${esc(s.name)}</span>`).join('')}</div>`;

const SLIDES = {
  title: s => `
    <div class="title-wrap">
      ${s.org ? `<div class="t-org">${esc(s.org)}</div>` : ''}
      <div class="t-main"><div class="rule"></div><h1 class="t-h">${md(s.title)}</h1>
      ${s.subtitle ? `<p class="t-sub">${md(s.subtitle)}</p>` : ''}</div>
      <div class="t-meta">${esc(s.meta || '')}</div>
      <div class="t-art" aria-hidden="true">${[0, 1, 2, 3, 4, 5].map(i =>
        `<i class="${i % 3 === 1 ? 'round' : ''}" style="background:${hue(i).tint}"></i>`).join('')}</div>
    </div>`,

  summary: s => `<main class="sum">
    <div class="sum-points">${s.points.map((p, i) => `
      <div class="sp" style="${hv(s.ask ? hueExcept(i, 'violet') : hue(i))}"><div class="sp-v">${esc(p.value)}</div>
      <div class="sp-t"><div class="sp-l">${md(p.label)}</div>${p.detail ? `<div class="sp-d">${md(p.detail)}</div>` : ''}</div></div>`).join('')}
    </div>
    ${s.ask ? `<aside class="ask" style="${hv(role('violet'))}"><div class="ask-l">${esc(s.ask.label || 'Decision needed')}</div>
      <p>${md(s.ask.text)}</p>${s.ask.meta ? `<div class="ask-m">${md(s.ask.meta)}</div>` : ''}</aside>` : ''}
  </main>`,

  kpis: s => `<main class="kpis${s.items.some(k => k.spark?.length) ? '' : ' nospark'}">${s.items.map((k, i) => {
    // Numbers in, text out: the script computes value, delta and direction so the spec carries no arithmetic.
    const f = k.format || {};
    const c = typeof k.before === 'number' && typeof k.now === 'number' ? change(k.before, k.now, f, k.change, k.better) : null;
    const value = fmt(k.now, f);
    const delta = c?.signed, good = c?.good;
    const target = typeof k.target === 'number' ? `Target: ${fmt(k.target, f)}` : '';
    return `
    <div class="tile" style="${hv(hue(i))}">
      <div class="k-l">${esc(k.label)}</div>
      <div class="k-v">${esc(value)}</div>
      ${deltaHtml(delta, good, k.vs)}
      ${target ? `<div class="k-t">${md(target)}</div>` : ''}
      ${k.spark?.length ? `<div class="k-s">${spark(k.spark, Math.floor((CONTENT_W - 24 * (s.items.length - 1)) / s.items.length) - 48,
        Math.max(48, Math.min(200, mainHeight(s) - 46 - 200 - (s.sparkLabel ? 26 : 0))), hue(i))}
        ${s.sparkLabel ? `<div class="k-sl">${esc(s.sparkLabel)}</div>` : ''}</div>` : ''}
    </div>`;
  }).join('')}</main>
    ${s.takeaway ? `<p class="takeaway">${md(s.takeaway)}</p>` : ''}`,

  trend: s => {
    const mh = mainHeight(s) - (s.series.length > 1 ? 34 : 0);
    return `<main class="trend"><div class="chart" style="width:${CONTENT_W}px">${legend(s.series)}
      ${lineChart({ ...s, w: CONTENT_W, h: mh })}</div></main>`;
  },

  compare: s => `<main class="cmp">
    <div class="legend"><span><i style="background:${th.context}"></i>${esc(s.beforeLabel || 'Before')}</span><span><i style="background:${th.accent}"></i>${esc(s.afterLabel || 'After')}</span></div>
    ${s.rows.map(r => {
      const f = r.format || {}, mx = Math.max(r.before, r.after);
      const { d, abs: changeText, good } = change(r.before, r.after, f, r.change, r.better);
      const bar = (v, c) => `<div class="cb-row"><div class="cb" style="width:calc((100% - 120px) * ${(v / mx).toFixed(4)});background:${c}"></div><span>${esc(fmt(v, f))}</span></div>`;
      return `<div class="c-row"><div class="c-lab">${esc(r.label)}${r.note ? `<small>${esc(r.note)}</small>` : ''}</div>
        <div class="c-bars">${bar(r.before, th.context)}${bar(r.after, th.accent)}</div>
        <div class="delta big ${good ? 'good' : 'bad'}" style="${hv(role(good ? 'green' : 'red'))}"><span class="arrow">${d < 0 ? '▼' : '▲'}</span>${changeText}</div></div>`;
    }).join('')}</main>`,

  next: s => `<main class="next">
    <div class="prio">${s.priorities.map((p, i) => `<div class="p-row" style="${hv(hue(i))}"><div><div class="p-t"><i class="dot"></i>${esc(p.title)}</div>${p.detail ? `<div class="p-d">${md(p.detail)}</div>` : ''}</div><div class="p-w">${esc(p.when || '')}</div></div>`).join('')}</div>
    ${s.asks ? `<aside class="ask" style="${hv(role('violet'))}"><div class="ask-l">${esc(s.asksLabel || 'Decisions needed')}</div>
      <ul>${s.asks.map(a => `<li>${md(a.text)}${a.owner ? `<span class="owner">${esc(a.owner)}</span>` : ''}</li>`).join('')}</ul></aside>` : ''}
  </main>`,
};

// ---------- page ----------

function css() {
  return `
@page{size:${W}px ${H}px;margin:0}
*{box-sizing:border-box}
html,body{margin:0}
body{background:#e6e6e2;font-family:${th.font};color:${th.ink};-webkit-print-color-adjust:exact;print-color-adjust:exact;-webkit-font-smoothing:antialiased}
.slide{width:${W}px;height:${H}px;background:${th.surface};position:relative;display:flex;flex-direction:column;padding:${PAD_TOP}px ${PAD_X}px 0;margin:24px auto;overflow:hidden}
body.single{background:${th.surface}}
body.single .slide{margin:0}
body.single .slide:not(.on){display:none}
@media print{body{background:none}.slide{margin:0;break-after:page}}
header h1{margin:0;font-family:${th.display};font-size:36px;line-height:1.18;font-weight:600;letter-spacing:-0.015em;max-width:1080px;text-wrap:balance}
.lede{margin:12px 0 0;font-size:19px;line-height:1.45;color:${th.ink2};max-width:980px}
main{flex:1;min-height:0;display:flex;gap:40px;padding:36px 0 28px;overflow:hidden}
footer{height:${FOOT}px;flex:none;border-top:1px solid ${th.grid};display:flex;align-items:center;gap:24px;font-size:12.5px;color:${th.muted}}
footer .src{flex:1}
strong{font-weight:600;color:${th.ink}}
svg text{font-family:${th.font}}
.tick{font-size:13px;fill:${th.muted};font-variant-numeric:tabular-nums}
.note{font-size:14px;fill:${th.ink2}}
.endv{font-size:20px;font-weight:600;fill:${th.ink}}
.legend{display:flex;gap:24px;font-size:14px;color:${th.ink2};margin-bottom:14px}
.legend i{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:8px;vertical-align:-2px}
.delta{font-size:17px;font-weight:600;margin-top:6px}
.delta.good{color:${th.good}}.delta.bad{color:${th.bad}}
.delta .arrow{font-size:.75em;margin-right:5px;vertical-align:1px}
.delta .vs{color:${th.muted};font-weight:400}
.takeaway{margin:0 0 26px;font-size:18px;color:${th.ink2}}
/* title */
.title-wrap{flex:1;display:flex;flex-direction:column;padding:8px 0 48px}
.t-org{font-size:17px;font-weight:600;color:${th.ink2}}
.t-main{flex:1;display:flex;flex-direction:column;justify-content:center}
.rule{width:56px;height:5px;border-radius:3px;background:${th.accent};margin-bottom:28px}
.t-h{margin:0;font-family:${th.display};font-size:60px;line-height:1.08;font-weight:700;letter-spacing:-0.02em;max-width:740px;text-wrap:balance}
.t-sub{margin:20px 0 0;font-size:24px;line-height:1.4;color:${th.ink2};max-width:900px}
.t-meta{font-size:16px;color:${th.muted}}
.title-wrap{position:relative}
.t-art{position:absolute;right:0;top:50%;transform:translateY(-50%);display:grid;grid-template-columns:repeat(3,104px);gap:20px}
.t-art i{display:block;width:104px;height:104px;border-radius:26px}
.t-art i.round{border-radius:50%}
/* summary */
.sum-points{flex:1;display:flex;flex-direction:column;gap:14px}
.sp{flex:1;display:flex;gap:32px;align-items:center;background:var(--bg);border-radius:14px;padding:0 32px}
.sp-v{width:200px;flex:none;font-size:46px;font-weight:700;letter-spacing:-0.02em;line-height:1;color:var(--ink)}
.sp-l{font-size:20px;font-weight:600;line-height:1.3}
.sp-d{font-size:16px;color:${th.ink2};margin-top:4px;line-height:1.4}
.ask{width:340px;flex:none;background:var(--bg);border-radius:14px;padding:28px 28px;display:flex;flex-direction:column}
.ask-l{font-size:15px;font-weight:600;color:var(--ink);margin-bottom:12px}
.ask p{margin:0;font-size:19px;line-height:1.45}
.ask-m{margin-top:auto;padding-top:16px;font-size:14px;color:${th.ink2};line-height:1.4}
.ask ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:16px}
.ask li{font-size:17px;line-height:1.4}
.owner{display:block;font-size:14px;color:${th.muted};margin-top:2px}
.chart{flex:none;display:flex;flex-direction:column;min-height:0}
.chart svg{display:block;overflow:visible}
/* kpis */
.kpis{gap:24px}
.tile{flex:1;background:var(--bg);border-radius:14px;padding:26px 24px 20px;display:flex;flex-direction:column;min-width:0}
.k-l{font-size:17px;color:var(--ink);font-weight:600}
.k-v{font-size:54px;font-weight:700;letter-spacing:-0.02em;margin-top:14px;line-height:1}
.k-t{font-size:14.5px;color:${th.ink2};margin-top:12px}
.k-s{margin-top:auto}
.kpis.nospark .tile{justify-content:center;padding:32px 30px}
.kpis.nospark .k-v{font-size:76px;margin-top:18px}
.kpis.nospark .delta{font-size:20px;margin-top:12px}
.k-sl{font-size:13px;color:${th.muted};margin-top:8px}
/* compare */
.cmp{flex-direction:column;gap:0}
.c-row{flex:1;display:flex;align-items:center;gap:32px;border-top:1px solid ${th.grid};max-height:120px}
.c-lab{width:260px;flex:none;font-size:19px;font-weight:600}
.c-lab small{display:block;font-size:14px;font-weight:400;color:${th.muted};margin-top:2px}
.c-bars{flex:1;display:flex;flex-direction:column;gap:8px}
.cb-row{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}
.cb{height:18px;border-radius:0 4px 4px 0;min-width:3px}
.delta.big{width:132px;flex:none;text-align:center;font-size:26px;margin:0;padding:10px 0;border-radius:12px;background:var(--bg);color:var(--ink)}
/* next */
.prio{flex:1;display:flex;flex-direction:column}
.p-row{flex:1;display:flex;justify-content:space-between;gap:24px;align-items:center;border-top:1px solid ${th.grid};max-height:200px}
.p-t{font-size:21px;font-weight:600;display:flex;align-items:center;gap:12px}
.dot{width:14px;height:14px;border-radius:50%;background:var(--mark);flex:none}
.p-d{font-size:16.5px;color:${th.ink2};margin-top:6px;line-height:1.4;max-width:600px;padding-left:26px}
.p-w{font-size:15px;font-weight:600;white-space:nowrap;background:var(--bg);color:var(--ink);padding:6px 14px;border-radius:999px}
#lint{display:none}
.k-v,.sp-v,.delta.big{font-family:${th.display}}
body.present{background:#101010;overflow:hidden;height:100vh}
body.present .slide{position:fixed;left:50%;top:50%;margin:0;transform:translate(-50%,-50%) scale(var(--scale,1));display:none;box-shadow:0 12px 48px rgba(0,0,0,.45)}
body.present .slide.on{display:flex}
#hud{display:none;position:fixed;right:18px;bottom:14px;font:13px/1 ${th.font};color:#8a8a8a;user-select:none}
body.present #hud{display:block}
@media print{body.present .slide{position:static;transform:none;display:flex;box-shadow:none}#hud{display:none!important}}`;
}

// In-page layout check: anything clipped by its box or pushed outside the slide body is an issue.
const LINT_JS = `
(function(){
  const q=new URLSearchParams(location.search);
  if(!q.has('lint')) return;
  const out=[], warn=[], sizes=[];
  document.querySelectorAll('.slide').forEach((s,i)=>{
    const n=i+1, sr=s.getBoundingClientRect(), limitB=sr.bottom-${FOOT}, limitR=sr.right-${PAD_X - 24};
    const m=s.querySelector('main');
    if(m){const cs=getComputedStyle(m); sizes.push(Math.floor(m.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom)));} else sizes.push(null);
    if(m && m.scrollHeight>m.clientHeight+2) out.push([n,'content taller than the slide body by '+(m.scrollHeight-m.clientHeight)+'px']);
    if(m && m.scrollWidth>m.clientWidth+2) out.push([n,'content wider than the slide body by '+(m.scrollWidth-m.clientWidth)+'px']);
    const h=s.querySelector('header h1');
    if(h){const lh=parseFloat(getComputedStyle(h).lineHeight); if(h.getBoundingClientRect().height>lh*2.2) out.push([n,'title wraps to 3+ lines; shorten it']);}
    if(m){
      // Leaf content (text and charts) should span most of the slide body; a big blank band looks unfinished.
      let top=1e9,bot=-1e9;
      m.querySelectorAll('*').forEach(el=>{
        const bg=getComputedStyle(el).backgroundColor;
        const leaf=el.tagName==='svg'||(!el.closest('svg')&&((!el.children.length&&el.textContent.trim())||(bg&&bg!=='rgba(0, 0, 0, 0)'&&bg!=='transparent')));
        if(!leaf) return; const r=el.getBoundingClientRect(); if(!r.height) return;
        top=Math.min(top,r.top); bot=Math.max(bot,r.bottom);
      });
      const mr=m.getBoundingClientRect(), cs=getComputedStyle(m), inner=mr.height-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom);
      if(bot>top && (bot-top)/inner<0.6) warn.push([n,Math.round(100-(bot-top)/inner*100)+'% of the slide body is empty; add content or pick a denser slide type']);
    }
    s.querySelectorAll('main text, main div, main span, main p, main li, main td').forEach(el=>{
      if(el.children.length && el.tagName!=='text') return;
      const r=el.getBoundingClientRect(); if(!r.width) return;
      if(r.bottom>limitB+1||r.right>limitR+1) out.push([n,'"'+(el.textContent||'').trim().slice(0,40)+'" runs outside the slide']);
      if(el.tagName!=='text' && el.scrollWidth>el.clientWidth+2 && getComputedStyle(el).overflow!=='visible') out.push([n,'"'+(el.textContent||'').trim().slice(0,40)+'" is clipped']);
    });
  });
  // A font is present when text set in it measures differently from the bare fallback.
  const probe=f=>{const c=document.createElement('canvas').getContext('2d');c.font='40px monospace';const a=c.measureText('Premium decks 0123').width;c.font='40px "'+f+'", monospace';return c.measureText('Premium decks 0123').width!==a;};
  const fonts=['Inter','Inter Display'].filter(f=>!probe(f));
  document.getElementById('lint').textContent=JSON.stringify({out,warn,sizes,fonts});
})();`;

// Presenter for deck.html: one slide at a time, scaled to the window. Screenshots (?only), lint and print skip it.
const PRESENT_JS = `
(function(){
  const q=new URLSearchParams(location.search), S=[...document.querySelectorAll('.slide')];
  if(q.has('only')){document.body.classList.add('single');S[q.get('only')-1].classList.add('on');return;}
  if(q.has('lint')||q.has('print')) return;
  document.body.classList.add('present');
  const hud=document.getElementById('hud');
  let i=Math.max(0,Math.min(S.length-1,(parseInt(location.hash.slice(1))||1)-1));
  const fit=()=>document.documentElement.style.setProperty('--scale',Math.min(innerWidth/${W},innerHeight/${H})*0.96);
  const go=n=>{i=Math.max(0,Math.min(S.length-1,n));S.forEach((el,k)=>el.classList.toggle('on',k===i));hud.textContent=(i+1)+' / '+S.length+'   ← → to move · F for fullscreen';history.replaceState(null,'','#'+(i+1));};
  addEventListener('resize',fit);
  addEventListener('keydown',e=>{
    if(['ArrowRight','ArrowDown','PageDown',' ','Enter'].includes(e.key)){e.preventDefault();go(i+1);}
    else if(['ArrowLeft','ArrowUp','PageUp','Backspace'].includes(e.key)){e.preventDefault();go(i-1);}
    else if(e.key==='Home')go(0); else if(e.key==='End')go(S.length-1);
    else if(e.key==='f'||e.key==='F'){document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();}
  });
  addEventListener('click',e=>go(e.clientX>innerWidth/2?i+1:i-1));
  fit();go(i);
})();`;

function slideHtml(s, n, deck) {
  if (!SLIDES[s.type]) throw new Error(`slide ${n}: unknown type "${s.type}"`);
  const body = SLIDES[s.type](s);
  if (s.type === 'title') return `<section class="slide">${body}</section>`;
  const src = s.source ?? deck.source;
  return `<section class="slide">
  <header><h1>${md(s.title)}</h1>${s.subtitle ? `<p class="lede">${md(s.subtitle)}</p>` : ''}</header>
  ${body}
  <footer><span class="src">${src ? 'Source: ' + esc(src) : ''}</span><span>${esc(deck.footer || '')}</span><span>${n}</span></footer>
</section>`;
}

// ---------- spec validation ----------

// Fields each slide type accepts. `items` maps array fields to the fields of each entry; `objs` does the same for objects;
// `nums` lists fields that must be numbers (or arrays of numbers).
const COMMON = ['type', 'title', 'subtitle', 'source'];
const SCHEMA = {
  title: { req: ['title'], opt: ['org', 'meta'] },
  summary: { req: ['title', 'points'], opt: ['ask'], items: { points: { req: ['value', 'label'], opt: ['detail'] } }, objs: { ask: { req: ['text'], opt: ['label', 'meta'] } } },
  kpis: { req: ['title', 'items'], opt: ['sparkLabel', 'takeaway'],
    items: { items: { req: ['label', 'now'], opt: ['before', 'format', 'better', 'change', 'vs', 'target', 'spark'], nums: ['now', 'before', 'target', 'spark'] } } },
  trend: { req: ['title', 'labels', 'series'], opt: ['format', 'zero', 'markers', 'target'],
    items: { series: { req: ['name', 'values'], opt: ['display'], nums: ['values'] }, markers: { req: ['at', 'label'] } }, objs: { target: { req: ['value'], opt: ['label'], nums: ['value'] } } },
  compare: { req: ['title', 'rows'], opt: ['beforeLabel', 'afterLabel'], items: { rows: { req: ['label', 'before', 'after'], opt: ['note', 'format', 'better', 'change'], nums: ['before', 'after'] } } },
  next: { req: ['title', 'priorities'], opt: ['asks', 'asksLabel'], items: { priorities: { req: ['title'], opt: ['detail', 'when'] }, asks: { req: ['text'], opt: ['owner'] } } },
};
const DECK_KEYS = ['title', 'footer', 'source', 'slides'];

function closest(word, options) {
  const dist = (a, b) => {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  };
  const best = options.map(o => [o, dist(word.toLowerCase(), o.toLowerCase())]).sort((x, y) => x[1] - y[1])[0];
  return best && best[1] <= 2 ? ` (did you mean "${best[0]}"?)` : '';
}

function checkFields(obj, rule, where, errs, extra = []) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) { errs.push(`${where} must be an object`); return; }
  const allowed = [...extra, ...(rule.req || []), ...(rule.opt || [])];
  for (const k of Object.keys(obj)) if (!allowed.includes(k) && !k.startsWith('_')) errs.push(`${where}: unknown field "${k}"${closest(k, allowed)}`);
  for (const k of rule.req || []) if (obj[k] === undefined || obj[k] === '') errs.push(`${where}: "${k}" is missing`);
  if (rule.oneOf && !rule.oneOf.some(k => obj[k] !== undefined)) errs.push(`${where}: needs "${rule.oneOf.join('" or "')}"`);
  for (const k of rule.nums || []) {
    const v = obj[k];
    if (v === undefined) continue;
    if (Array.isArray(v) ? v.some(x => typeof x !== 'number') : typeof v !== 'number') errs.push(`${where}: "${k}" must be ${Array.isArray(v) ? 'an array of numbers' : 'a number'}, without units or quotes`);
  }
  for (const [k, sub] of Object.entries(rule.items || {})) {
    if (obj[k] === undefined) continue;
    if (!Array.isArray(obj[k])) { errs.push(`${where}: "${k}" must be an array`); continue; }
    obj[k].forEach((it, j) => checkFields(it, sub, `${where} ${k}[${j}]`, errs));
  }
  for (const [k, sub] of Object.entries(rule.objs || {})) if (obj[k] !== undefined) checkFields(obj[k], sub, `${where} ${k}`, errs);
}

function validate(deck) {
  const errs = [];
  for (const k of Object.keys(deck)) if (!DECK_KEYS.includes(k)) errs.push(`deck: unknown field "${k}"${closest(k, DECK_KEYS)}`);
  if (!Array.isArray(deck.slides) || !deck.slides.length) return [...errs, 'deck: "slides" must be a non-empty array'];
  deck.slides.forEach((s, i) => {
    const where = `slide ${i + 1} (${s?.type ?? 'no type'})`, rule = SCHEMA[s?.type];
    if (!rule) { errs.push(`slide ${i + 1}: type "${s?.type}" is not one of ${Object.keys(SCHEMA).join(', ')}${closest(String(s?.type), Object.keys(SCHEMA))}`); return; }
    checkFields(s, rule, where, errs, COMMON);
    if (s.type === 'trend' && Array.isArray(s.series) && Array.isArray(s.labels)) s.series.forEach((se, j) => {
      if (Array.isArray(se?.values) && se.values.length !== s.labels.length) errs.push(`${where} series[${j}]: ${se.values.length} values for ${s.labels.length} labels`);
    });
  });
  return errs;
}

// ---------- chrome ----------

function findChrome() {
  const cands = [process.env.CHROME, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/Applications/Chromium.app/Contents/MacOS/Chromium',
    'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge', '/snap/bin/chromium'];
  for (const c of cands) if (c && fs.existsSync(c)) return c;
  throw new Error('no Chrome/Edge/Chromium found: set CHROME=/path/to/browser');
}
const chrome = (bin, args) => execFileSync(bin, ['--headless', '--disable-gpu', '--hide-scrollbars', ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 64 << 20 });

// ---------- main ----------

const args = process.argv.slice(2), pos = [];
let formatArg;
for (let i = 0; i < args.length; i++) {
  if (args[i].startsWith('--format')) formatArg = args[i].includes('=') ? args[i].split('=')[1] : args[++i];
  else pos.push(args[i]);
}
const [specPath, outArg] = pos;
if (!specPath) { console.error('usage: slides.mjs <deck.json> [out-dir] [--format pdf,png,html]'); process.exit(2); }
let deck;
try { deck = JSON.parse(fs.readFileSync(specPath, 'utf8')); }
catch (e) { console.error(`SPEC     ${specPath} is not valid JSON: ${e.message}`); process.exit(2); }
const specErrors = validate(deck);
if (specErrors.length) {
  console.error(specErrors.map(e => `SPEC     ${e}`).join('\n'));
  process.exit(2);
}
const FORMATS = ['pdf', 'png', 'html'];
const formats = String(formatArg || FORMATS.join(',')).split(',').map(x => x.trim().toLowerCase()).filter(Boolean);
for (const f of formats) if (!FORMATS.includes(f)) { console.error(`SPEC     unknown format "${f}"; use ${FORMATS.join(', ')}`); process.exit(2); }
const out = path.resolve(outArg || path.join(path.dirname(specPath), path.basename(specPath, '.json') + '-out'));
fs.mkdirSync(out, { recursive: true });

const htmlPath = path.join(out, 'deck.html');
const url = pathToFileURL(htmlPath).href;
const bin = findChrome();

function build() {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(deck.title || 'Deck')}</title><style>${css()}</style></head>
<body>${deck.slides.map((s, i) => slideHtml(s, i + 1, deck)).join('\n')}<div id="hud"></div><pre id="lint"></pre><script>${LINT_JS}${PRESENT_JS}</script></body></html>`;
  fs.writeFileSync(htmlPath, html);
  const dom = chrome(bin, ['--virtual-time-budget=3000', '--window-size=1400,900', '--dump-dom', `${url}?lint=1`]);
  const raw = (dom.match(/<pre id="lint">([\s\S]*?)<\/pre>/) || [])[1] || '{"out":[],"warn":[],"sizes":[],"fonts":[]}';
  return JSON.parse(raw.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&'));
}

// Pass 1 measures each slide body; pass 2 sizes charts to the measured space and re-checks layout.
build().sizes.forEach((h, i) => { if (h) deck.slides[i]._mh = h; });
const { out: layout, warn: layoutWarn = [], fonts: missingFonts = [] } = build();

if (formats.includes('png')) deck.slides.forEach((_, i) => {
  const png = path.join(out, `slide-${String(i + 1).padStart(2, '0')}.png`);
  chrome(bin, [`--screenshot=${png}`, `--window-size=${W},${H}`, '--force-device-scale-factor=2', `${url}?only=${i + 1}`]);
});
if (formats.includes('pdf')) chrome(bin, [`--print-to-pdf=${path.join(out, 'deck.pdf')}`, '--no-pdf-header-footer', '--print-to-pdf-no-header', `${url}?print=1`]);
if (!formats.includes('html')) fs.rmSync(htmlPath);

const made = { pdf: 'deck.pdf', png: 'slide-NN.png', html: 'deck.html (open it, arrow keys to present)' };
console.log(`deck: ${out}  (${deck.slides.length} slides: ${formats.map(f => made[f]).join(', ')})`);
if (missingFonts.length) console.log(`  font     ${missingFonts.join(' and ')} not installed, so the system font was used; run: brew install --cask font-inter`);
for (const [n, msg] of layoutWarn) console.log(`  layout   slide ${n}: ${msg}`);
for (const [n, msg] of layout) console.log(`  LAYOUT   slide ${n}: ${msg}`);
if (!layout.length && !layoutWarn.length) console.log('  lint: clean');
process.exit(layout.length ? 3 : 0);
