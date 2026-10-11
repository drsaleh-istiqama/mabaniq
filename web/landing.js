// مبانيك 0.14.0 — صفحة الهبوط: نموذج طلب العرض الحي + قائمة الهاتف. لا سكربت مضمّن ولا onclick (CSP script-src 'self').
const lang = document.documentElement.lang === 'en' ? 'en' : 'ar';
const T = {
  ar: {sending: 'جارٍ الإرسال…', send: 'أرسل الطلب', err: 'تعذّر إرسال الطلب. تحقق من الحقول ثم حاول مرة أخرى.',
       rate: 'وصلتنا طلبات كثيرة من هذا العنوان. حاول بعد قليل.', net: 'تعذّر الاتصال بالخادم. حاول مرة أخرى.'},
  en: {sending: 'Sending…', send: 'Send request', err: 'The request could not be sent. Check the fields and try again.',
       rate: 'Too many requests from this address. Please try again later.', net: 'Could not reach the server. Please try again.'},
}[lang];

const menu = document.getElementById('menu');
const links = document.getElementById('navLinks');
if (menu && links) {
  menu.addEventListener('click', () => {
    const open = links.classList.toggle('open');
    menu.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  links.addEventListener('click', e => { if (e.target.tagName === 'A') links.classList.remove('open'); });
}

const form = document.getElementById('demoForm');
if (form) {
  const btn = form.querySelector('button[type="submit"]');
  const msg = document.getElementById('demoMsg');
  const show = (text, ok) => { msg.textContent = text; msg.className = 'msg ' + (ok ? 'ok' : 'err'); msg.focus?.(); };
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form).entries());
    data.projects = Number(data.projects || 0);
    data.lang = lang;
    btn.disabled = true; btn.textContent = T.sending; msg.className = 'msg';
    try {
      const r = await fetch('/api/public/demo-request', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
      let json = null;
      try { json = await r.json(); } catch { /* no body */ }
      if (r.ok && json && json.ok) { show(json.message, true); form.reset(); }
      else if (r.status === 429) show(T.rate, false);
      else show(T.err, false);
    } catch { show(T.net, false); }
    finally { btn.disabled = false; btn.textContent = T.send; }
  });
}
