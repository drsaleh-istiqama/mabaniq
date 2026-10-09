/* Unit 3 — shell internationalisation. Arabic is the source of truth (RTL); English covers the navigation shell, page
   headers, login and the customer app chrome. Deep screens stay Arabic until their strings are moved here (tracked in PROGRESS). */
import ar from './locales/ar.json';
import en from './locales/en.json';

const DICT = {ar, en};
const KEY = 'mbq-lang';

export function lang() {
  try { return localStorage.getItem(KEY) === 'en' ? 'en' : 'ar'; } catch { return 'ar'; }
}

export function t(key, fallback = '') {
  const d = DICT[lang()] || ar;
  return d[key] ?? ar[key] ?? fallback ?? key;
}

export function applyI18n(root = document) {
  const l = lang();
  document.documentElement.lang = l;
  document.documentElement.dir = l === 'en' ? 'ltr' : 'rtl';
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const v = DICT[l] && DICT[l][el.dataset.i18n];
    if (v) el.textContent = v;
    else if (l === 'ar' && ar[el.dataset.i18n]) el.textContent = ar[el.dataset.i18n];
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const v = t(el.dataset.i18nPlaceholder);
    if (v) el.setAttribute('placeholder', v);
  });
}

export function toggleLang() {
  const next = lang() === 'ar' ? 'en' : 'ar';
  try { localStorage.setItem(KEY, next); } catch { /* storage may be blocked */ }
  location.reload();
}
