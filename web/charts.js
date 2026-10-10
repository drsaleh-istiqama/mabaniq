// Mabaniq — SVG charts (Unit 7): bar, stacked, line, pie/donut. No external library (CSP self), RTL category order,
// Western digits, colours from CSS variables so light/dark themes just work, <title> tooltips, responsive via viewBox.
const PAL = ['var(--pri)', 'var(--blue)', 'var(--ok)', 'var(--bad)', 'var(--sold)', '#A078C8', '#8A94A6'];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmtN = (v, kind) => {
  const n = +v || 0;
  if (kind === 'money') return n >= 1e6 ? (n / 1e6).toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 2}) + ' مليون' : n >= 1e3 ? (n / 1e3).toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 1}) + ' ألف' : n.toLocaleString('ar-OM-u-nu-latn');
  if (kind === 'pct') return n.toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 1}) + '٪';
  return n.toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 2});
};
const niceMax = v => { if (v <= 0) return 1; const e = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * e) return m * e; return 10 * e; };
const trunc = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

export function render(el, ch) {
  if (!el) return;
  const t = ch.type || 'bar';
  const svg = t === 'pie' ? pie(ch) : t === 'line' ? line(ch) : bars(ch, t === 'stacked');
  el.innerHTML = `<div class="chart"><div class="ch-t">${esc(ch.title || '')}</div>${svg}${legend(ch)}</div>`;
}

function legend(ch) {
  const s = ch.series || [];
  if (ch.type === 'pie') return '';
  if (s.length < 2 && ch.type !== 'pie') return '';
  return `<div class="ch-l">${s.map((x, i) => `<span><i style="background:${PAL[i % PAL.length]}"></i>${esc(x.name)}</span>`).join('')}</div>`;
}

function bars(ch, stacked) {
  const labels = ch.labels || [], series = ch.series || [];
  if (!labels.length || !series.length) return '<div class="muted">لا بيانات.</div>';
  const W = 720, H = 260, padL = 54, padR = 12, padT = 12, padB = 44;
  const pw = W - padL - padR, ph = H - padT - padB;
  const max = niceMax(stacked ? Math.max(...labels.map((_, i) => series.reduce((a, s) => a + (+s.data[i] || 0), 0))) : Math.max(...series.flatMap(s => s.data.map(Number))));
  const n = labels.length, gw = pw / n, bw = gw * 0.68 / (stacked ? 1 : series.length);
  let out = `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img" aria-label="${esc(ch.title || '')}">`;
  for (let g = 0; g <= 4; g++) { const y = padT + ph - ph * g / 4; out += `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" class="grid"/><text x="${padL - 6}" y="${y + 4}" class="ax" text-anchor="end">${esc(fmtN(max * g / 4, ch.format))}</text>`; }
  labels.forEach((lab, i) => {
    const gx = padL + pw - (i + 1) * gw; // RTL: first category on the right
    let base = padT + ph;
    series.forEach((s, si) => {
      const v = +s.data[i] || 0, bh = max ? ph * v / max : 0;
      const x = stacked ? gx + gw * 0.16 : gx + gw * 0.16 + si * bw;
      const y = stacked ? base - bh : padT + ph - bh;
      out += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - (stacked ? 0 : 1.5)).toFixed(1)}" height="${bh.toFixed(1)}" rx="2" fill="${PAL[si % PAL.length]}"><title>${esc(s.name)} — ${esc(lab)}: ${esc(fmtN(v, ch.format))}</title></rect>`;
      if (stacked) base -= bh;
    });
    out += `<text x="${(gx + gw / 2).toFixed(1)}" y="${H - padB + 16}" class="ax" text-anchor="middle">${esc(trunc(lab, n > 10 ? 7 : 14))}</text>`;
  });
  return out + '</svg>';
}

function line(ch) {
  const labels = ch.labels || [], series = ch.series || [];
  if (!labels.length || !series.length) return '<div class="muted">لا بيانات.</div>';
  const W = 720, H = 260, padL = 54, padR = 12, padT = 12, padB = 40;
  const pw = W - padL - padR, ph = H - padT - padB;
  const all = series.flatMap(s => s.data.map(Number));
  const max = niceMax(Math.max(...all)), min = Math.min(0, ...all), rng = (max - min) || 1;
  const n = labels.length, step = pw / Math.max(n - 1, 1);
  let out = `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img" aria-label="${esc(ch.title || '')}">`;
  for (let g = 0; g <= 4; g++) { const val = min + rng * g / 4, y = padT + ph - ph * (val - min) / rng; out += `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" class="grid"/><text x="${padL - 6}" y="${y + 4}" class="ax" text-anchor="end">${esc(fmtN(val, ch.format))}</text>`; }
  series.forEach((s, si) => {
    const pts = labels.map((_, i) => [padL + pw - i * step, padT + ph - ph * ((+s.data[i] || 0) - min) / rng]);
    out += `<polyline fill="none" stroke="${PAL[si % PAL.length]}" stroke-width="2.2" points="${pts.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ')}"/>`;
    pts.forEach((p, i) => { out += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${PAL[si % PAL.length]}"><title>${esc(s.name)} — ${esc(labels[i])}: ${esc(fmtN(s.data[i], ch.format))}</title></circle>`; });
  });
  const every = Math.max(1, Math.ceil(n / 9));
  labels.forEach((lab, i) => { if (i % every) return; out += `<text x="${(padL + pw - i * step).toFixed(1)}" y="${H - padB + 16}" class="ax" text-anchor="middle">${esc(trunc(lab, 9))}</text>`; });
  return out + '</svg>';
}

function pie(ch) {
  const labels = ch.labels || [], data = ((ch.series || [])[0] || {}).data || [];
  const vals = data.map(v => Math.max(+v || 0, 0)), total = vals.reduce((a, b) => a + b, 0);
  if (!total) return '<div class="muted">لا بيانات.</div>';
  const W = 720, H = 240, cx = W - 130, cy = H / 2, r = 95, ri = 52;
  let a0 = -Math.PI / 2, out = `<svg viewBox="0 0 ${W} ${H}" class="ch" role="img" aria-label="${esc(ch.title || '')}">`;
  vals.forEach((v, i) => {
    if (!v) return;
    const a1 = a0 + 2 * Math.PI * v / total, large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (ang, rad) => [cx + rad * Math.cos(ang), cy + rad * Math.sin(ang)];
    const [x0, y0] = p(a0, r), [x1, y1] = p(a1, r), [x2, y2] = p(a1, ri), [x3, y3] = p(a0, ri);
    const d = vals.filter(Boolean).length === 1 ? `M ${cx - r} ${cy} A ${r} ${r} 0 1 1 ${cx + r} ${cy} A ${r} ${r} 0 1 1 ${cx - r} ${cy} M ${cx - ri} ${cy} A ${ri} ${ri} 0 1 0 ${cx + ri} ${cy} A ${ri} ${ri} 0 1 0 ${cx - ri} ${cy}`
      : `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(1)} ${y1.toFixed(1)} L ${x2.toFixed(1)} ${y2.toFixed(1)} A ${ri} ${ri} 0 ${large} 0 ${x3.toFixed(1)} ${y3.toFixed(1)} Z`;
    out += `<path d="${d}" fill="${PAL[i % PAL.length]}" fill-rule="evenodd" stroke="var(--pane)" stroke-width="1.5"><title>${esc(labels[i])}: ${esc(fmtN(v, ch.format))} (${(100 * v / total).toFixed(0)}٪)</title></path>`;
    a0 = a1;
  });
  out += `<text x="${cx}" y="${cy + 5}" class="ax big" text-anchor="middle">${esc(fmtN(total, ch.format))}</text>`;
  let ly = 28;
  vals.forEach((v, i) => { if (ly > H - 8 || !v) return; out += `<rect x="${W - 270}" y="${ly - 9}" width="10" height="10" rx="2" fill="${PAL[i % PAL.length]}"/><text x="${W - 278}" y="${ly}" class="ax" text-anchor="end">${esc(trunc(labels[i], 28))} · ${esc(fmtN(v, ch.format))} (${(100 * v / total).toFixed(0)}٪)</text>`; ly += 20; });
  return out + '</svg>';
}

export const formatValue = fmtN;
