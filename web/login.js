// Login page: password (username or e-mail) · TOTP step · forgot/reset · one-time e-mail link · Google. No inline script (CSP).
const $ = id => document.getElementById(id);
const q = new URLSearchParams(location.search);
const ERR = {
  link: 'الرابط غير صالح أو منتهٍ — اطلب رابطًا جديدًا.',
  'link-2fa': 'هذا الحساب محمي بالتحقق الثنائي؛ ادخل بكلمة المرور ورمز التحقق.',
  'link-session': 'لربط حساب Google سجّل الدخول أولًا ثم اربطه من «أماني».',
  state: 'انتهت صلاحية محاولة الدخول عبر Google أو بدأت من متصفح آخر — أعد المحاولة.',
  google: 'تعذّر إتمام الدخول عبر Google. حاول مجددًا أو ادخل بكلمة المرور.',
  'google-denied': 'أُلغيت الموافقة في Google.',
  'google-unknown': 'لا يوجد حساب في مبانيك بهذا البريد. اطلب من مدير المنصة إضافة بريدك إلى حسابك ثم أعد المحاولة.',
  'google-taken': 'حساب Google هذا مرتبط بمستخدم آخر.',
  aud: 'استجابة Google غير متوقعة.', nonce: 'استجابة Google غير متوقعة.', unverified: 'بريد Google غير موثَّق.',
};
let mode = 'login', needOtp = false, methods = {password: true};
const show = (el, on) => $(el).classList.toggle('hid', !on);

function setMode(m) {
  mode = m; $('e').textContent = ''; show('msg', false);
  for (const s of ['s1', 's2', 'sForgot', 'sMagic', 'sReset']) show(s, false);
  show('goBack', m !== 'login'); show('goForgot', m === 'login'); show('goMagic', m === 'login' && !!methods.email_link); show('gbtn', m === 'login' && !!methods.google);
  const lead = $('lead'), b = $('b');
  if (m === 'login') { show('s1', true); lead.textContent = 'منصة المطوّر العقاري من جدوى. سجّل الدخول بحساب الموظف أو العميل أو الوسيط.'; b.textContent = 'دخول'; }
  if (m === 'otp') { show('s2', true); lead.textContent = 'حسابك محمي بالتحقق الثنائي. أدخل الرمز الحالي من تطبيق المصادقة أو رمز استرداد.'; b.textContent = 'تحقق ودخول'; $('o').focus(); }
  if (m === 'forgot') { show('sForgot', true); lead.textContent = 'استعادة كلمة المرور'; b.textContent = 'أرسل رابط الاستعادة'; $('fi').value = $('u').value; $('fi').focus(); }
  if (m === 'magic') { show('sMagic', true); lead.textContent = 'الدخول برابط إلى بريدك'; b.textContent = 'أرسل رابط الدخول'; $('mi').focus(); }
  if (m === 'reset') { show('sReset', true); lead.textContent = 'اختر كلمة مرور جديدة'; b.textContent = 'تعيين ودخول'; $('n1').focus(); }
}

fetch('/api/tenants').then(r => r.json()).then(ts => {
  $('t').innerHTML = ts.map(t => `<option value="${t.code}">${t.name.replace(/[<>&"]/g, '')}</option>`).join('');
  const last = q.get('t') || localStorage.getItem('mbq-tenant'); if (last && ts.some(t => t.code === last)) $('t').value = last;
  $('gbtn').href = '/auth/google/start?t=' + encodeURIComponent($('t').value || 'jadwa');
}).catch(() => { $('t').innerHTML = '<option value="jadwa">جدوى</option>'; });
$('t').addEventListener('change', () => { $('gbtn').href = '/auth/google/start?t=' + encodeURIComponent($('t').value || 'jadwa'); });
fetch('/api/auth/methods').then(r => r.json()).then(m => { methods = m; setMode(q.get('reset') ? 'reset' : 'login'); }).catch(() => setMode(q.get('reset') ? 'reset' : 'login'));

if (q.get('err')) { $('e').textContent = ERR[q.get('err')] || 'تعذّر تسجيل الدخول.'; history.replaceState(null, '', '/login'); }
$('goForgot').onclick = () => setMode('forgot');
$('goMagic').onclick = () => setMode('magic');
$('goBack').onclick = () => setMode('login');

async function post(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({}));
  return {r, j};
}
function note(text, link) {
  const m = $('msg'); m.innerHTML = ''; m.append(text);
  if (link) { const a = document.createElement('a'); a.href = link; a.textContent = 'فتح الرابط (وضع العرض)'; a.className = 'demo'; m.append(document.createElement('br'), a); }
  show('msg', true);
}

$('f').onsubmit = async ev => {
  ev.preventDefault(); const b = $('b'), e = $('e'); b.disabled = true; e.textContent = '';
  const tenant = $('t').value || 'jadwa';
  const need = (id, msg) => { if (!$(id).value.trim()) { $(id).focus(); throw new Error(msg); } };
  try {
    if (mode === 'login' || mode === 'otp') { need('u', 'أدخل اسم المستخدم أو البريد'); need('p', 'أدخل كلمة المرور'); if (mode === 'otp') need('o', 'أدخل رمز التحقق'); }
    if (mode === 'forgot') need('fi', 'أدخل اسم المستخدم أو البريد');
    if (mode === 'magic') need('mi', 'أدخل بريدك الإلكتروني');
    if (mode === 'reset') { need('n1', 'أدخل كلمة المرور الجديدة'); need('n2', 'أكّد كلمة المرور'); }
    if (mode === 'forgot') {
      const {r, j} = await post('/api/auth/password/forgot', {identifier: $('fi').value.trim().toLowerCase(), tenant});
      if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر إرسال الرابط');
      note(j.message, j.demo_link); b.disabled = false; return;
    }
    if (mode === 'magic') {
      const {r, j} = await post('/api/auth/email/request', {email: $('mi').value.trim().toLowerCase(), tenant});
      if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر إرسال الرابط');
      note(j.message, j.demo_link); b.disabled = false; return;
    }
    if (mode === 'reset') {
      if ($('n1').value !== $('n2').value) throw new Error('كلمتا المرور غير متطابقتين');
      const {r, j} = await post('/api/auth/password/reset', {token: q.get('reset'), new: $('n1').value, tenant});
      if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر تعيين كلمة المرور');
      history.replaceState(null, '', '/login'); q.delete('reset');
      setMode('login'); $('u').value = j.username; $('p').value = $('n1').value; note('عُيّنت كلمة المرور الجديدة. يجري الدخول…');
      $('f').requestSubmit(); return;
    }
    const body = {username: $('u').value.trim().toLowerCase(), password: $('p').value, tenant};
    if (needOtp) body.otp = $('o').value.trim();
    const {r, j} = await post('/api/auth/login', body);
    if (r.status === 401 && j.detail === 'OTP_REQUIRED') { needOtp = true; setMode('otp'); b.disabled = false; return; }
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر تسجيل الدخول');
    localStorage.setItem('mbq-tenant', body.tenant);
    location.href = j.role === 'customer' ? '/app' : j.role === 'broker' ? '/broker' : '/';
  } catch (x) { e.textContent = x.message; b.disabled = false; if (needOtp) { $('o').value = ''; $('o').focus(); } }
};
