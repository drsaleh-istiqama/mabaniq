// Static checks on the web sources (portable replacement for the shell loops; CI and `npm run check` share it):
//   1. every web/*.js parses (node --check) — CSP forbids inline scripts, so every script is a file
//   2. no inline handlers (onclick=…) and no inline <script> bodies in web/*.html
//   3. no Arabic-Indic digits hard-coded in web sources or locales (owner decision ب: Western digits; WD() normalises server strings)
import {execFileSync} from 'node:child_process';
import {readdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';

const web = join(process.cwd(), 'web');
let failures = 0;
const fail = msg => { failures++; console.error('✗ ' + msg); };

for (const f of readdirSync(web).filter(f => f.endsWith('.js'))) {
  try { execFileSync(process.execPath, ['--check', join(web, f)], {stdio: 'pipe'}); console.log('✓ parses   ' + f); }
  catch (e) { fail(`${f}: ${e.stderr?.toString() || e.message}`); }
}
for (const f of readdirSync(web).filter(f => f.endsWith('.html'))) {
  const s = readFileSync(join(web, f), 'utf8');
  if (/\son[a-z]+="/i.test(s)) fail(`${f}: inline event handler`);
  if (/<script(?![^>]*\bsrc=)[^>]*>\s*\S/.test(s)) fail(`${f}: inline <script> body`);
  if (!/<html[^>]*\bdir="rtl"/.test(s) || !/<html[^>]*\blang="ar"/.test(s)) fail(`${f}: <html> must declare dir="rtl" lang="ar"`);
  console.log('✓ html     ' + f);
}
const digitFiles = [...readdirSync(web).filter(f => /\.(js|html)$/.test(f)).map(f => join(web, f)),
  ...readdirSync(join(web, 'locales')).map(f => join(web, 'locales', f))];
for (const p of digitFiles) {
  const lines = readFileSync(p, 'utf8').split('\n');
  lines.forEach((l, i) => {
    if (/[٠-٩]/.test(l) && !/\[٠-٩\]|'٠١٢٣٤٥٦٧٨٩'/.test(l)) fail(`${p.replace(process.cwd(), '.')}:${i + 1}: Arabic-Indic digit in source`);
  });
}
console.log(failures ? `${failures} failure(s)` : '✓ digits   Western only');
process.exit(failures ? 1 : 0);
