// Initial-JS budget guard (Istiqama Map rule: ≤ 200 kB gzip for the first screen). Run after `vite build`.
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {gzipSync} from 'node:zlib';
import {join} from 'node:path';

const BUDGET_KB = Number(process.env.MABANIQ_JS_BUDGET_KB || 200);
const dist = join(process.cwd(), 'frontend', 'dist');
const html = readFileSync(join(dist, 'index.html'), 'utf8');
const assets = [...html.matchAll(/\/static\/(assets\/[^"]+\.(?:js|css))/g)].map(m => m[1]);
if (!assets.length) { console.error('no assets referenced from index.html'); process.exit(1); }
let js = 0, css = 0;
for (const a of assets) {
  const buf = readFileSync(join(dist, a));
  const gz = gzipSync(buf).length;
  (a.endsWith('.js') ? (js += gz) : (css += gz));
  console.log(`${a.padEnd(48)} ${(gz / 1024).toFixed(1).padStart(7)} kB gzip`);
}
const fonts = readdirSync(join(dist, 'assets')).filter(f => f.endsWith('.woff2')).reduce((s, f) => s + statSync(join(dist, 'assets', f)).size, 0);
console.log(`initial JS ${(js / 1024).toFixed(1)} kB gzip (budget ${BUDGET_KB}) · CSS ${(css / 1024).toFixed(1)} kB gzip · fonts ${(fonts / 1024).toFixed(1)} kB (self-hosted)`);
if (js / 1024 > BUDGET_KB) { console.error('initial JS over budget'); process.exit(1); }
