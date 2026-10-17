// In-page checks for an infographic. Runs after fonts load and writes its findings as JSON
// into a hidden pre element so render.sh can read them from the dumped DOM.
(() => {
  const RULES = /*RULES*/null;
  const errors = [], warnings = [];
  const canvas = document.querySelector('.canvas');

  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const [r, g, b, a = 1] = m[1].split(',').map(Number); return { r, g, b, a }; };
  const lum = ({ r, g, b }) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > .9) return c; } return { r: 255, g: 255, b: 255, a: 1 }; };
  const label = el => { const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30); return `<${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''}> "${t}"`; };

  function run() {
    if (!canvas) { errors.push('no element with class "canvas"'); return finish(); }
    const box = canvas.getBoundingClientRect();

    // 1. Inter is installed (a missing font silently falls back and changes every width).
    const probe = document.createElement('canvas').getContext('2d');
    const w = f => { probe.font = f; return probe.measureText('Illegal Wimm 0123').width; };
    if (w('16px Inter, monospace') === w('16px monospace')) warnings.push('Inter is not installed: text falls back to the system font (brew install --cask font-inter)');

    // 2. Everything stays inside the canvas, and nothing is clipped.
    if (canvas.scrollHeight > canvas.clientHeight + 1) errors.push(`content is ${canvas.scrollHeight - canvas.clientHeight}px taller than the canvas: cut content or shrink spacing`);
    if (canvas.scrollWidth > canvas.clientWidth + 1) errors.push(`content is ${canvas.scrollWidth - canvas.clientWidth}px wider than the canvas`);
    canvas.querySelectorAll('*').forEach(el => {
      if (el.closest('svg') && el.tagName.toLowerCase() !== 'svg') return;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      if (r.right > box.right + 1 || r.bottom > box.bottom + 1 || r.left < box.left - 1 || r.top < box.top - 1) errors.push(`outside the canvas: ${label(el)}`);
      if (el !== canvas && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) && getComputedStyle(el).overflow !== 'visible' && el.tagName.toLowerCase() !== 'svg')
        errors.push(`text or content clipped inside ${label(el)}`);
    });

    // 3. Text nodes: size, contrast, placeholders, overlap.
    const texts = [];
    const walker = document.createTreeWalker(canvas, NodeFilter.SHOW_TEXT);
    for (let n; (n = walker.nextNode());) {
      const s = n.textContent.trim(); if (!s) continue;
      const el = n.parentElement; if (!el || el.closest('script,style')) continue;
      const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      const range = document.createRange(); range.selectNodeContents(n);
      texts.push({ n, s, el, cs, rect: range.getBoundingClientRect() });
    }
    const seen = new Set();
    for (const t of texts) {
      const size = parseFloat(t.cs.fontSize);
      if (size < RULES.minFont && !seen.has('f' + label(t.el))) { seen.add('f' + label(t.el)); errors.push(`text under ${RULES.minFont}px (${size}px): ${label(t.el)}`); }
      const fg = parse(t.cs.color), bg = bgOf(t.el);
      if (fg) {
        const large = size >= 24 || (size >= 19 && +t.cs.fontWeight >= 700);
        const need = large ? RULES.minContrastLarge : RULES.minContrast, got = ratio(fg, bg);
        if (got < need && !seen.has('c' + label(t.el))) { seen.add('c' + label(t.el)); errors.push(`low contrast ${got.toFixed(1)}:1 (needs ${need}:1): ${label(t.el)}`); }
      }
      if (/\b(todo|lorem|ipsum|tbd)\b|sample data|x{3,}|\{\{|\}\}/i.test(t.s)) errors.push(`placeholder text left in: ${label(t.el)}`);
    }
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i], b = texts[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const ox = Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left);
      const oy = Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top);
      if (ox > 2 && oy > 2) errors.push(`text overlaps: ${label(a.el)} and ${label(b.el)}`);
    }

    // 4. Density: a slide read from five metres carries few words.
    const words = texts.reduce((n, t) => n + t.s.split(/\s+/).length, 0);
    if (words > 120) warnings.push(`${words} words on one canvas: aim for under 120`);
    finish();
  }

  function finish() {
    const pre = document.createElement('pre');
    pre.id = 'check-result'; pre.hidden = true;
    pre.textContent = JSON.stringify({ errors: [...new Set(errors)], warnings });
    document.body.appendChild(pre);
  }

  // Run once, whichever comes first: fonts ready or the load event plus a short wait.
  // A thrown error becomes a finding instead of silently losing the whole result.
  let done = false;
  const go = () => {
    if (done) return; done = true;
    try { run(); } catch (e) { errors.push('check script error: ' + e.message); finish(); }
  };
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(() => setTimeout(go, 50));
  window.addEventListener('load', () => setTimeout(go, 500));
})();
