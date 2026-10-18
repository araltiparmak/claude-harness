#!/usr/bin/env node
// Builds a presentation deck from a JSON spec.
// Usage: node slides.mjs <deck.json> [out-dir] [--format pdf,png,html]
// Writes deck.pdf, slide-NN.png (2x) and deck.html (a presenter: arrow keys, F for fullscreen), then prints a lint report.
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
const STATUS = {
  good: { color: '#0ca30c', glyph: 'check', label: 'On track' },
  warning: { color: '#fab219', glyph: 'bang', label: 'At risk' },
  critical: { color: '#d03b3b', glyph: 'cross', label: 'Off track' },
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
let th = DEFAULT_THEME;
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
const show = (v, f) => typeof v === 'number' ? fmt(v, f) : v;

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

function hbarPath(x0, y, len, t, r = 4) {
  r = Math.min(r, t / 2, len);
  return `M${x0},${y}H${x0 + len - r}Q${x0 + len},${y} ${x0 + len},${y + r}V${y + t - r}Q${x0 + len},${y + t} ${x0 + len - r},${y + t}H${x0}Z`;
}

function colPath(x, w, yTop, yBot, r = 4) {
  r = Math.min(r, (yBot - yTop) / 2, w / 2);
  return `M${x},${yBot}V${yTop + r}Q${x},${yTop} ${x + r},${yTop}H${x + w - r}Q${x + w},${yTop} ${x + w},${yTop + r}V${yBot}Z`;
}

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

function statusIcon(kind, size = 20) {
  const s = STATUS[kind] || STATUS.warning, c = size / 2;
  const glyph = {
    check: `<path d="M${c - 4.5},${c} l3,3 l6,-6.5" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`,
    bang: `<path d="M${c},${c - 5} V${c + 1}" stroke="#0b0b0b" stroke-width="2.2" stroke-linecap="round"/><circle cx="${c}" cy="${c + 4.6}" r="1.3" fill="#0b0b0b"/>`,
    cross: `<path d="M${c - 3.8},${c - 3.8} l7.6,7.6 M${c + 3.8},${c - 3.8} l-7.6,7.6" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>`,
  }[s.glyph];
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true"><circle cx="${c}" cy="${c}" r="${c}" fill="${statusHue(kind).mark}"/>${glyph}</svg>`;
}

// Target met: on track. Missed but improving: at risk. Missed and not improving: off track.
function autoStatus(r) {
  if (typeof r.now !== 'number' || typeof r.target !== 'number') return 'warning';
  const lower = r.better === 'lower', met = lower ? r.now <= r.target : r.now >= r.target;
  if (met) return 'good';
  const improving = typeof r.before === 'number' && (lower ? r.now < r.before : r.now > r.before);
  return improving ? 'warning' : 'critical';
}
const statusHue = kind => role({ good: 'green', warning: 'amber', critical: 'red' }[kind] || 'amber');

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

function barChart({ items, format = {}, highlight = [], w, h }) {
  const labW = Math.min(300, Math.max(...items.map(i => textW(i.label, 16, 600))) + 24);
  const valW = Math.max(...items.map(i => textW(i.display ?? fmt(i.value, format), 17, 600))) + 24;
  const iw = w - labW - valW, slot = h / items.length, t = Math.min(28, slot * 0.5);
  const max = Math.max(...items.map(i => i.value));
  let g = `<line x1="${labW}" x2="${labW}" y1="0" y2="${h}" stroke="${th.axis}"/>`;
  items.forEach((it, i) => {
    const cy = i * slot + slot / 2, len = Math.max(3, it.value / max * iw);
    const hl = it.highlight || highlight.includes(it.label);
    g += `<text x="${labW - 14}" y="${cy + 5.5}" text-anchor="end" class="lab${hl ? ' strong' : ''}">${esc(it.label)}</text>`;
    g += `<path d="${hbarPath(labW, cy - t / 2, len, t)}" fill="${hl ? th.accent : th.context}"/>`;
    g += `<text x="${labW + len + 10}" y="${cy + 6}" class="val">${esc(it.display ?? fmt(it.value, format))}</text>`;
  });
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">${g}</svg>`;
}

function waterfallChart({ start, steps, end, format = {}, better = 'higher', axisFrom, w, h }) {
  const cols = [{ label: start.label, a: 0, b: start.value, kind: 'start' }];
  let run = start.value;
  for (const s of steps) {
    cols.push({ label: s.label, a: run, b: run + s.value, delta: s.value, kind: (s.value >= 0) === (better === 'higher') ? 'good' : 'bad' });
    run += s.value;
  }
  cols.push({ label: end.label, a: 0, b: run, kind: 'end' });
  const vals = cols.flatMap(c => [c.a, c.b]);
  // axisFrom raises the baseline so small steps on a large total stay visible; the chart says so.
  const base = axisFrom ?? Math.min(0, ...vals);
  const tk = ticks(base, Math.max(...vals), 4);
  tk[0] = base;
  const slot = w / cols.length, maxChars = Math.max(10, Math.floor(slot / 9.5));
  const wrap = label => String(label).split(' ').reduce((rows, wd) => {
    const cur = rows.at(-1);
    if (cur && (cur + ' ' + wd).length > maxChars) rows.push(wd); else rows[rows.length - 1] = (cur ? cur + ' ' : '') + wd;
    return rows;
  }, ['']);
  const labelRows = Math.max(...cols.map(c => wrap(c.label).length));
  const T = 40, B = 30 + labelRows * 19 + (axisFrom !== undefined ? 22 : 0), ih = h - T - B, bw = Math.min(64, slot * 0.42);
  const y = v => T + ih - (v - tk[0]) / (tk.at(-1) - tk[0]) * ih;
  const fill = { start: role('violet').mark, end: th.accent, good: role('green').mark, bad: role('red').mark };
  const y0 = y(base);
  let g = `<line x1="0" x2="${w}" y1="${y0}" y2="${y0}" stroke="${th.axis}"/>`;
  if (axisFrom !== undefined) g += `<text x="0" y="${h - 4}" class="tick">Axis starts at ${esc(fmt(axisFrom, format))}</text>`;
  cols.forEach((c, i) => {
    const cx = i * slot + slot / 2, x0 = cx - bw / 2;
    const top = y(Math.max(c.a, c.b)), bot = Math.min(y0, y(Math.min(c.a, c.b)));
    g += c.kind === 'start' || c.kind === 'end'
      ? `<path d="${colPath(x0, bw, top, bot)}" fill="${fill[c.kind]}"/>`
      : `<rect x="${x0}" y="${top}" width="${bw}" height="${Math.max(2, bot - top)}" rx="3" fill="${fill[c.kind]}"/>`;
    if (i < cols.length - 1) {
      g += `<line x1="${x0 + bw}" x2="${cx + slot - bw / 2}" y1="${y(c.b)}" y2="${y(c.b)}" stroke="${th.axis}"/>`;
    }
    const label = c.delta === undefined ? fmt(c.b, format) : fmt(c.delta, format, true);
    g += `<text x="${cx}" y="${top - 12}" text-anchor="middle" class="${c.delta === undefined ? 'endv' : 'val'}">${esc(label)}</text>`;
    wrap(c.label).forEach((r, k) => {
      g += `<text x="${cx}" y="${y0 + 26 + k * 19}" text-anchor="middle" class="lab${c.delta === undefined ? ' strong' : ''}">${esc(r)}</text>`;
    });
  });
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">${g}</svg>`;
}

// ---------- slide types ----------

const sidePanel = items => `<aside class="side">${(items || []).map((c, i) => `
  <div class="callout" style="${hv(hue(i + 1))}"><div class="c-v">${esc(c.value)}</div><div class="c-l">${md(c.label)}</div></div>`).join('')}</aside>`;

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

  hero: s => {
    const mh = mainHeight(s), chartW = CONTENT_W - 48 - 440;
    return `<main class="hero">
      <div class="h-left">
        <div class="h-v">${esc(s.value)}</div>
        <div class="h-l">${md(s.label)}</div>
        ${s.before ? `<div class="h-ba"><div><span>${esc(s.beforeLabel || 'Before')}</span><b>${esc(s.before)}</b></div>
          <div class="h-arrow">→</div><div><span>${esc(s.afterLabel || 'After')}</span><b class="acc">${esc(s.after)}</b></div></div>` : ''}
        ${s.notes ? `<ul class="h-notes">${s.notes.map(n => `<li>${md(n)}</li>`).join('')}</ul>` : ''}
      </div>
      ${s.trend ? `<div class="chart" style="width:${chartW}px">
        ${s.trend.title ? `<div class="ch-t">${esc(s.trend.title)}</div>` : ''}
        ${lineChart({ ...s.trend, series: s.trend.series || [{ name: s.trend.title, values: s.trend.values }], w: chartW, h: mh - (s.trend.title ? 30 : 0) })}</div>` : ''}
    </main>`;
  },

  kpis: s => `<main class="kpis${s.items.some(k => k.spark?.length) ? '' : ' nospark'}">${s.items.map((k, i) => {
    // Numbers in, text out: the script computes value, delta and direction so the spec carries no arithmetic.
    const f = k.format || {};
    const c = typeof k.before === 'number' && typeof k.now === 'number' ? change(k.before, k.now, f, k.change, k.better) : null;
    const value = k.value ?? show(k.now, f);
    const delta = k.delta ?? c?.signed, good = k.good ?? c?.good;
    const target = typeof k.target === 'number' ? `Target: ${fmt(k.target, f)}` : k.target;
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
    const mh = mainHeight(s) - (s.series.length > 1 ? 34 : 0), chartW = s.side ? CONTENT_W - 40 - 300 : CONTENT_W;
    return `<main class="trend"><div class="chart" style="width:${chartW}px">${legend(s.series)}
      ${lineChart({ ...s, w: chartW, h: mh })}</div>${s.side ? sidePanel(s.side) : ''}</main>`;
  },

  bars: s => {
    const mh = mainHeight(s), chartW = s.side ? CONTENT_W - 40 - 300 : CONTENT_W;
    return `<main class="trend"><div class="chart" style="width:${chartW}px">${barChart({ ...s, w: chartW, h: mh })}</div>${s.side ? sidePanel(s.side) : ''}</main>`;
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

  waterfall: s => {
    const mh = mainHeight(s), chartW = s.side ? CONTENT_W - 40 - 300 : CONTENT_W;
    return `<main class="trend"><div class="chart" style="width:${chartW}px">${waterfallChart({ ...s, w: chartW, h: mh })}</div>${s.side ? sidePanel(s.side) : ''}</main>`;
  },

  scorecard: s => {
    const [prev, now] = s.periods || ['Last', 'Now'];
    const rowH = Math.max(52, Math.min(120, Math.floor((mainHeight(s) - 40) / s.rows.length)));
    const trend = s.rows.some(r => r.spark?.length);
    return `<main class="score"><table style="--row:${rowH}px">
      <thead><tr><th>Metric</th><th class="num">${esc(prev)}</th><th class="num">${esc(now)}</th><th class="num">Target</th>${trend ? '<th>Trend</th>' : ''}<th>Status</th></tr></thead>
      <tbody>${s.rows.map(r => {
        const f = r.format || {}, st = r.status || autoStatus(r);
        return `<tr>
        <td class="m">${esc(r.metric)}${r.note ? `<small>${esc(r.note)}</small>` : ''}</td>
        <td class="num mut">${esc(show(r.before, f))}</td><td class="num strong">${esc(show(r.now, f))}</td><td class="num mut">${esc(show(r.target, f))}</td>
        ${trend ? `<td>${spark(r.spark, 132, 36, statusHue(st))}</td>` : ''}
        <td><span class="st" style="${hv(statusHue(st))}">${statusIcon(st)}${esc(r.statusLabel || STATUS[st]?.label)}</span></td></tr>`;
      }).join('')}
      </tbody></table></main>`;
  },

  impact: s => `<main class="impact">${s.steps.map((st, i) => `
    ${i ? `<div class="chev"><svg width="28" height="28" viewBox="0 0 28 28"><path d="M9 5l9 9-9 9" fill="none" stroke="${th.axis}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>` : ''}
    <div class="step${i === s.steps.length - 1 ? ' last' : ''}" style="${hv(hue(i))}">
      <div class="s-l">${esc(st.label)}</div><div class="s-v">${esc(st.value)}</div>
      ${st.detail ? `<div class="s-d">${md(st.detail)}</div>` : ''}</div>`).join('')}
    </main>${s.footnote ? `<p class="takeaway small">${md(s.footnote)}</p>` : ''}`,

  wins: s => `<main class="wins" style="grid-template-columns:repeat(${s.items.length === 4 ? 2 : Math.min(3, s.items.length)},1fr)">${s.items.map((w, i) => `
    <div class="win" style="${hv(hue(i))}"><div class="w-m">${esc(w.metric)}</div><div class="w-t">${md(w.win)}</div><div class="w-team">${esc(w.team)}</div></div>`).join('')}
  </main>`,

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
.lab{font-size:16px;fill:${th.ink2}}.lab.strong{fill:${th.ink};font-weight:600}
.val{font-size:17px;font-weight:600;fill:${th.ink}}
.endv{font-size:20px;font-weight:600;fill:${th.ink}}
.legend{display:flex;gap:24px;font-size:14px;color:${th.ink2};margin-bottom:14px}
.legend i{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:8px;vertical-align:-2px}
.delta{font-size:17px;font-weight:600;margin-top:6px}
.delta.good{color:${th.good}}.delta.bad{color:${th.bad}}
.delta .arrow{font-size:.75em;margin-right:5px;vertical-align:1px}
.delta .vs{color:${th.muted};font-weight:400}
.takeaway{margin:0 0 26px;font-size:18px;color:${th.ink2}}
.takeaway.small{font-size:14px;color:${th.muted}}
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
/* hero */
.hero{gap:48px}
.h-left{width:440px;flex:none;display:flex;flex-direction:column;justify-content:center}
.h-v{font-size:120px;font-weight:700;letter-spacing:-0.04em;line-height:.95}
.h-l{font-size:22px;color:${th.ink2};margin-top:14px;line-height:1.35}
.h-ba{display:flex;align-items:flex-end;gap:20px;margin-top:30px;padding:18px 22px;background:${hue(0).bg};border-radius:14px;align-self:flex-start}
.h-ba span{display:block;font-size:14px;color:${th.muted};margin-bottom:4px}
.h-ba b{font-size:30px;font-weight:600}
.h-ba b.acc{color:${th.accentInk}}
.h-v{color:${th.accentInk}}
.h-arrow{font-size:26px;color:${th.muted};padding-bottom:2px}
.h-notes{margin:24px 0 0;padding-left:20px;font-size:16px;line-height:1.5;color:${th.ink2}}
.chart{flex:none;display:flex;flex-direction:column;min-height:0}
.ch-t{font-size:15px;font-weight:600;color:${th.ink2};margin-bottom:12px}
.chart svg{display:block;overflow:visible}
/* side callouts */
.side{width:300px;flex:none;display:flex;flex-direction:column}
.side{gap:16px}
.callout{flex:1;background:var(--bg);border-radius:14px;padding:22px 24px;max-height:220px}
.c-v{font-size:44px;font-weight:700;letter-spacing:-0.02em;line-height:1;color:var(--ink)}
.c-l{font-size:17px;color:${th.ink2};margin-top:10px;line-height:1.4}
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
/* scorecard */
.score{display:block}
table{width:100%;border-collapse:collapse;font-size:17px}
th{font-size:13.5px;font-weight:600;color:${th.muted};text-align:left;padding:0 12px 12px;border-bottom:1px solid ${th.axis}}
td{padding:0 12px;height:var(--row,62px);border-bottom:1px solid ${th.grid};vertical-align:middle}
th:first-child,td:first-child{padding-left:0}
.num{text-align:right;font-variant-numeric:tabular-nums}
td.mut{color:${th.ink2}}td.strong{font-weight:600}
td.m{font-weight:600}td.m small{display:block;font-weight:400;font-size:13.5px;color:${th.muted}}
.st{display:inline-flex;align-items:center;gap:9px;font-weight:600;font-size:16px;padding:6px 14px 6px 8px;border-radius:999px;background:var(--bg);color:var(--ink)}
/* impact */
.impact{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;grid-template-rows:1fr auto auto auto 1fr;gap:0 16px}
.impact>*{grid-row:1/-1}
.step{display:grid;grid-template-rows:subgrid;padding:0 28px;background:var(--bg);border-radius:14px}
.step>.s-l{grid-row:2}.step>.s-v{grid-row:3}.step>.s-d{grid-row:4}
.step.last{box-shadow:inset 0 0 0 2px var(--mark)}
.s-l{font-size:15px;font-weight:600;color:var(--ink)}
.s-v{font-size:40px;font-weight:700;letter-spacing:-0.015em;margin-top:12px;line-height:1.1}
.s-v{color:var(--ink)}
.s-d{font-size:18px;color:${th.ink2};margin-top:14px;line-height:1.45}
.chev{align-self:center}
/* wins */
.wins{display:grid;grid-template-columns:repeat(3,1fr);grid-auto-rows:1fr;gap:18px}
.win{background:var(--bg);border-radius:14px;padding:28px 30px;display:flex;flex-direction:column;justify-content:center}
.w-m{font-size:46px;font-weight:700;letter-spacing:-0.015em;line-height:1;color:var(--ink)}
.w-t{font-size:20px;margin-top:14px;line-height:1.35}
.w-team{font-size:14.5px;color:var(--ink);opacity:.8;margin-top:8px}
/* next */
.prio{flex:1;display:flex;flex-direction:column}
.p-row{flex:1;display:flex;justify-content:space-between;gap:24px;align-items:center;border-top:1px solid ${th.grid};max-height:200px}
.p-t{font-size:21px;font-weight:600;display:flex;align-items:center;gap:12px}
.dot{width:14px;height:14px;border-radius:50%;background:var(--mark);flex:none}
.p-d{font-size:16.5px;color:${th.ink2};margin-top:6px;line-height:1.4;max-width:600px;padding-left:26px}
.p-w{font-size:15px;font-weight:600;white-space:nowrap;background:var(--bg);color:var(--ink);padding:6px 14px;border-radius:999px}
#lint{display:none}
.h-v,.k-v,.sp-v,.c-v,.w-m,.s-v,.delta.big{font-family:${th.display}}
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
const SIDE = { req: ['value', 'label'] };
const COMMON = ['type', 'title', 'subtitle', 'source'];
const SCHEMA = {
  title: { req: ['title'], opt: ['org', 'meta'] },
  summary: { req: ['title', 'points'], opt: ['ask'], items: { points: { req: ['value', 'label'], opt: ['detail'] } }, objs: { ask: { req: ['text'], opt: ['label', 'meta'] } } },
  hero: { req: ['title', 'value', 'label'], opt: ['before', 'after', 'beforeLabel', 'afterLabel', 'notes', 'trend'],
    objs: { trend: { req: ['labels'], opt: ['title', 'values', 'series', 'format', 'zero', 'markers', 'target'], nums: ['values'], oneOf: ['values', 'series'],
      items: { series: { req: ['name', 'values'], opt: ['display'], nums: ['values'] }, markers: { req: ['at', 'label'] } }, objs: { target: { req: ['value'], opt: ['label'], nums: ['value'] } } } } },
  kpis: { req: ['title', 'items'], opt: ['sparkLabel', 'takeaway'],
    items: { items: { req: ['label'], opt: ['value', 'now', 'before', 'format', 'better', 'change', 'delta', 'good', 'vs', 'target', 'spark'], nums: ['spark'], oneOf: ['value', 'now'] } } },
  trend: { req: ['title', 'labels', 'series'], opt: ['format', 'zero', 'markers', 'target', 'side'],
    items: { series: { req: ['name', 'values'], opt: ['display'], nums: ['values'] }, markers: { req: ['at', 'label'] }, side: SIDE }, objs: { target: { req: ['value'], opt: ['label'], nums: ['value'] } } },
  bars: { req: ['title', 'items'], opt: ['format', 'highlight', 'side'], items: { items: { req: ['label', 'value'], opt: ['highlight', 'display'], nums: ['value'] }, side: SIDE } },
  compare: { req: ['title', 'rows'], opt: ['beforeLabel', 'afterLabel'], items: { rows: { req: ['label', 'before', 'after'], opt: ['note', 'format', 'better', 'change'], nums: ['before', 'after'] } } },
  waterfall: { req: ['title', 'start', 'steps', 'end'], opt: ['format', 'better', 'axisFrom', 'side'], nums: ['axisFrom'],
    items: { steps: { req: ['label', 'value'], nums: ['value'] }, side: SIDE }, objs: { start: { req: ['label', 'value'], nums: ['value'] }, end: { req: ['label'] } } },
  scorecard: { req: ['title', 'rows'], opt: ['periods'], items: { rows: { req: ['metric', 'before', 'now', 'target'], opt: ['note', 'status', 'statusLabel', 'spark', 'format', 'better'], nums: ['spark'] } } },
  impact: { req: ['title', 'steps'], opt: ['footnote'], items: { steps: { req: ['label', 'value'], opt: ['detail'] } } },
  wins: { req: ['title', 'items'], items: { items: { req: ['metric', 'win', 'team'] } } },
  next: { req: ['title', 'priorities'], opt: ['asks', 'asksLabel'], items: { priorities: { req: ['title'], opt: ['detail', 'when'] }, asks: { req: ['text'], opt: ['owner'] } } },
};
const DECK_KEYS = ['title', 'footer', 'source', 'theme', 'allowTerms', 'slides'];
const THEME_KEYS = ['startHue', 'palette'];

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
  for (const k of Object.keys(deck.theme || {})) if (!THEME_KEYS.includes(k)) errs.push(`theme: unknown field "${k}"${closest(k, THEME_KEYS)}`);
  const pal = deck.theme?.palette;
  if (pal !== undefined) {
    if (!Array.isArray(pal) || !pal.length) errs.push('theme: "palette" must be a non-empty array');
    else pal.forEach((h, j) => {
      checkFields(h, { req: ['name', 'bg', 'tint', 'mark', 'ink'] }, `theme palette[${j}]`, errs);
      // Colours go into style attributes unescaped, so accept hex only.
      for (const k of ['bg', 'tint', 'mark', 'ink']) if (h?.[k] !== undefined && !/^#[0-9a-f]{3,8}$/i.test(h[k])) errs.push(`theme palette[${j}]: "${k}" must be a hex colour like "#2453d6"`);
    });
  }
  if (!Array.isArray(deck.slides) || !deck.slides.length) return [...errs, 'deck: "slides" must be a non-empty array'];
  deck.slides.forEach((s, i) => {
    const where = `slide ${i + 1} (${s?.type ?? 'no type'})`, rule = SCHEMA[s?.type];
    if (!rule) { errs.push(`slide ${i + 1}: type "${s?.type}" is not one of ${Object.keys(SCHEMA).join(', ')}${closest(String(s?.type), Object.keys(SCHEMA))}`); return; }
    checkFields(s, rule, where, errs, COMMON);
    // Every series has one value per label: a trend slide, or a hero slide's trend.
    const chart = s.type === 'trend' ? s : s.type === 'hero' ? s.trend : undefined;
    if (chart && Array.isArray(chart.labels)) {
      const lists = Array.isArray(chart.series) ? chart.series.map((se, j) => [`series[${j}]`, se?.values]) : [['values', chart.values]];
      for (const [name, v] of lists) if (Array.isArray(v) && v.length !== chart.labels.length) errs.push(`${where} ${s.type === 'hero' ? 'trend ' : ''}${name}: ${v.length} values for ${chart.labels.length} labels`);
    }
  });
  return errs;
}

// ---------- title numbers ----------

// Numbers with a unit in the title ("77%", "$2.1M", "4×") should match something the slide shows or computes.
const unitNumbers = text => [...String(text).matchAll(/([$€£]?)(\d[\d,]*(?:\.\d+)?)\s?(%|K\b|M\b|B\b|×|x\b|pt\b)?/g)]
  .filter(m => m[1] || m[3]).map(m => ({ raw: m[0].trim(), v: parseFloat(m[2].replace(/,/g, '')), dp: (m[2].split('.')[1] || '').length }));

function slideCandidates(s) {
  const c = [];
  const walk = (v, key) => {
    if (key === 'title' || key === 'subtitle') return;
    if (typeof v === 'number') c.push(Math.abs(v));
    else if (typeof v === 'string') for (const m of String(v).matchAll(/\d[\d,]*(?:\.\d+)?/g)) c.push(parseFloat(m[0].replace(/,/g, '')));
    else if (Array.isArray(v)) v.forEach(x => walk(x));
    else if (v && typeof v === 'object') Object.entries(v).forEach(([k, x]) => walk(x, k));
  };
  walk(s);
  const pairs = [];
  (s.items || []).forEach(k => typeof k.before === 'number' && typeof k.now === 'number' && pairs.push([k.before, k.now]));
  (s.rows || []).forEach(r => typeof r.before === 'number' && typeof r.after === 'number' && pairs.push([r.before, r.after]));
  const labels = s.labels || s.trend?.labels || [], markers = s.markers || s.trend?.markers || [];
  for (const se of s.series || (s.trend ? [{ values: s.trend.values || [] }] : [])) {
    const v = se.values || [];
    if (v.length > 1) pairs.push([v[0], v.at(-1)]);
    for (const m of markers) { const i = labels.indexOf(m.at); if (i >= 0 && v[i] !== undefined) pairs.push([v[i], v.at(-1)]); }
  }
  // Titles often state a derived number ("21% ahead of plan", "3× faster", "$3.4M in total"),
  // so differences, ratios and sums of the numbers on the slide count too.
  const base = [...new Set(c)].slice(0, 40);
  for (const a of base) for (const b of base) if (a !== b && b) pairs.push([b, a]), c.push(a + b);
  for (const [a, b] of pairs) { const ch = change(a, b); c.push(Math.abs(ch.pct), Math.abs(ch.d)); if (a && b) c.push(b / a, a / b); }
  if (s.type === 'waterfall') {
    const st = s.steps.map(x => x.value), sum = a => a.reduce((x, y) => x + y, 0);
    c.push(Math.abs(sum(st)), sum(st.filter(x => x > 0)), Math.abs(sum(st.filter(x => x < 0))), s.start.value + sum(st));
  }
  if (s.type === 'scorecard') c.push(s.rows.length, s.rows.filter(r => (r.status || autoStatus(r)) === 'good').length);
  return c;
}

function checkTitleNumbers(s) {
  const cand = slideCandidates(s);
  // A title rounds, so "21%" accepts anything that rounds to 21 at the title's own precision.
  return unitNumbers(s.title).filter(({ v, dp }) => !cand.some(c => Math.abs(c - v) <= Math.max(0.011 * v, 0.5 * 10 ** -dp + 1e-9))).map(x => x.raw);
}

// ---------- content lint ----------

const LIMITS = { summary: ['points', 4], kpis: ['items', 4], wins: ['items', 6], bars: ['items', 8], compare: ['rows', 5], scorecard: ['rows', 7], waterfall: ['steps', 6], next: ['priorities', 4], impact: ['steps', 3] };
// Terms a company-wide audience may not know; a deck can allow some with "allowTerms".
const JARGON = ['ARR', 'MRR', 'P&L', 'Sev-1', 'Sev1', 'SLA', 'SLO', 'FTE', 'YoY', 'QoQ', 'p95', 'p99', 'MTTR', 'OKR', 'CAC', 'LTV'];
const DATA_TYPES = new Set(['summary', 'hero', 'kpis', 'trend', 'bars', 'compare', 'waterfall', 'scorecard', 'wins']);

function lintSpec(deck) {
  const out = [];
  deck.slides.forEach((s, i) => {
    const n = i + 1, t = s.title || '';
    if (!t) out.push([n, 'missing title']);
    if (s.type !== 'title' && t.length > 95) out.push([n, `title is ${t.length} chars; action titles stay under ~90`]);
    if (DATA_TYPES.has(s.type) && !/\d/.test(t)) out.push([n, 'title states no number; lead with the result']);
    if (DATA_TYPES.has(s.type) && !(s.source ?? deck.source)) out.push([n, 'no source; name the data source and period']);
    if (DATA_TYPES.has(s.type)) for (const raw of checkTitleNumbers(s)) out.push([n, `title says "${raw}" but nothing on the slide shows or computes it; check the number`]);
    const lim = LIMITS[s.type];
    if (lim && (s[lim[0]] || []).length > lim[1]) out.push([n, `${s[lim[0]].length} ${lim[0]}; max ${lim[1]} for a ${s.type} slide`]);
  });
  const allowed = new Set(deck.allowTerms || []);
  deck.slides.forEach((s, i) => {
    const text = JSON.stringify(s);
    for (const term of JARGON) {
      if (!allowed.has(term) && new RegExp(`(^|[^A-Za-z0-9])${term.replace(/[&-]/g, '\\$&')}([^A-Za-z0-9]|$)`).test(text)) {
        out.push([i + 1, `"${term}" may be unclear to a company-wide audience; spell it out or add it to allowTerms`]);
      }
    }
  });
  if (deck.slides.length > 12) out.push([0, `${deck.slides.length} slides; a review fits in 6 to 10`]);
  return out;
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
{
  const t = deck.theme || {};
  let palette = t.palette || PALETTE;
  // startHue rotates the palette so a deck can lead with any hue.
  const k = palette.findIndex(h => h.name === t.startHue);
  if (k > 0) palette = [...palette.slice(k), ...palette.slice(0, k)];
  th = { ...DEFAULT_THEME, palette, panel: palette[0].bg, accent: palette[0].mark, accentInk: palette[0].ink, accentWash: palette[0].bg };
}
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
const content = lintSpec(deck);
if (/Inter/.test(th.font) && missingFonts.length) console.log(`  font     ${missingFonts.join(' and ')} not installed, so the system font was used; run: brew install --cask font-inter`);
for (const [n, msg] of content) console.log(`  content  slide ${n}: ${msg}`);
for (const [n, msg] of layoutWarn) console.log(`  layout   slide ${n}: ${msg}`);
for (const [n, msg] of layout) console.log(`  LAYOUT   slide ${n}: ${msg}`);
if (!content.length && !layout.length && !layoutWarn.length) console.log('  lint: clean');
process.exit(layout.length ? 3 : 0);
