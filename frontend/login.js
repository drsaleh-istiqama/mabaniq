const $ = id => document.getElementById(id);
fetch('/api/tenants').then(r => r.json()).then(ts => {
  $('t').innerHTML = ts.map(t => `<option value="${t.code}">${t.name.replace(/[<>&"]/g, '')}</option>`).join('');
  const last = localStorage.getItem('mbq-tenant'); if (last && ts.some(t => t.code === last)) $('t').value = last;
}).catch(() => { $('t').innerHTML = '<option value="jadwa">جدوى</option>'; });
let needOtp = false;
$('f').onsubmit = async ev => {
  ev.preventDefault(); const b = $('b'), e = $('e'); b.disabled = true; e.textContent = '';
  const body = {username: $('u').value.trim().toLowerCase(), password: $('p').value, tenant: $('t').value || 'jadwa'};
  if (needOtp) body.otp = $('o').value.trim();
  try {
    const r = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (r.status === 401 && j.detail === 'OTP_REQUIRED') {
      needOtp = true; $('s1').classList.add('hid'); $('s2').classList.remove('hid'); $('lead').textContent = 'حسابك محمي بالتحقق الثنائي. أدخل الرمز الحالي من تطبيق المصادقة.';
      b.textContent = 'تحقق ودخول'; b.disabled = false; $('o').focus(); return;
    }
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر تسجيل الدخول');
    localStorage.setItem('mbq-tenant', body.tenant);
    location.href = j.role === 'customer' ? '/app' : j.role === 'broker' ? '/broker' : '/';
  } catch (x) { e.textContent = x.message; b.disabled = false; if (needOtp) { $('o').value = ''; $('o').focus(); } }
};
