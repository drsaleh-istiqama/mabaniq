// Initial-JS budget guard (Istiqama Map rule: ≤ 200 kB gzip for the first screen). Run after `vite build`.
// 0.14.0: the public landing page (landing.html, landing-en.html) is checked with the same JS budget, and every image it
// ships must be ≤ MABANIQ_IMG_BUDGET_KB (200) — screenshots are JPEG from tools/landing_shoot.mjs / landing_assets.py.
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {gzipSync} from 'node:zlib';
import {join} from 'node:path';

const BUDGET_KB = Number(process.env.MABANIQ_JS_BUDGET_KB || 200);
const IMG_KB = Number(process.env.MABANIQ_IMG_BUDGET_KB || 200);
const dist = join(process.cwd(), 'frontend', 'dist');
let failed = false;

function entry(name) {
  const html = readFileSync(join(dist, name), 'utf8');
  const assets = [...html.matchAll(/\/static\/(assets\/[^"]+\.(?:js|css))/g)].map(m => m[1]);
  if (!assets.length) { console.error(`no assets referenced from ${name}`); process.exit(1); }
  let js = 0, css = 0;
  for (const a of assets) {
    const gz = gzipSync(readFileSync(join(dist, a))).length;
    (a.endsWith('.js') ? (js += gz) : (css += gz));
    console.log(`${a.padEnd(48)} ${(gz / 1024).toFixed(1).padStart(7)} kB gzip`);
  }
  console.log(`${name}: initial JS ${(js / 1024).toFixed(1)} kB gzip (budget ${BUDGET_KB}) · CSS ${(css / 1024).toFixed(1)} kB gzip`);
  if (js / 1024 > BUDGET_KB) { console.error(`${name}: initial JS over budget`); failed = true; }
  const imgs = [...html.matchAll(/\/static\/(assets\/[^"]+\.(?:jpg|jpeg|png|webp|svg))/g)].map(m => m[1]);
  for (const i of new Set(imgs)) {
    const kb = statSync(join(dist, i)).size / 1024;
    if (kb > IMG_KB) { console.error(`${name}: ${i} is ${kb.toFixed(0)} kB > ${IMG_KB} kB`); failed = true; }
  }
  if (imgs.length) console.log(`${name}: ${new Set(imgs).size} images, all ≤ ${IMG_KB} kB`);
}

entry('index.html');
entry('landing.html');
entry('landing-en.html');
const fonts = readdirSync(join(dist, 'assets')).filter(f => f.endsWith('.woff2')).reduce((s, f) => s + statSync(join(dist, 'assets', f)).size, 0);
console.log(`fonts ${(fonts / 1024).toFixed(1)} kB (self-hosted)`);
if (failed) process.exit(1);
