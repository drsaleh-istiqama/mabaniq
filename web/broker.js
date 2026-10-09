const $ = s => document.querySelector(s);
const N = v => new Intl.NumberFormat('ar-OM-u-nu-latn').format(Math.round(v || 0));
const OMR = v => N(v) + '\u00a0ر.ع';
const WD = t => String(t ?? '').replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/(\d)٫(?=\d)/g, '$1.'); // الوحدة 3 — قرار ب: أرقام غربية في كل الواجهة؛ ثابت واحد يطبَّع هنا
const esc = s => WD(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const D = d => d ? new Date(d).toLocaleDateString('ar-OM-u-nu-latn', {day: 'numeric', month: 'long', year: 'numeric'}) : '—';
const H = () => new Intl.DateTimeFormat('ar-SA-u-ca-islamic-umalqura-nu-latn', {day: 'numeric', month: 'long', year: 'numeric'}).format(new Date());
const STAGES = ['جديد', 'تواصل', 'معاينة', 'تفاوض', 'حجز'];
const CS = {due: ['مستحقة', 'p-w'], paid: ['مدفوعة', 'p-ok'], void: ['ملغاة', 'p-b'], clawback: ['مستردة', 'p-b']};
function toast(t, bad) { const e = $('#toast'); e.textContent = t; e.classList.toggle('bad', !!bad); e.classList.add('on'); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('on'), 3000); }
const csrf = () => (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
async function api(p, o = {}) {
  const r = await fetch('/api' + p, {...o, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf(), ...(o.headers || {})}, body: o.body ? JSON.stringify(o.body) : undefined});
  if (r.status === 401) { location.href = '/login'; throw new Error('انتهت الجلسة'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر تنفيذ الطلب');
  return j;
}
$('#out').onclick = async () => { await fetch('/api/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': csrf()}}); location.href = '/login'; };
let PROJ = [];
async function load() {
  const me = await api('/me');
  if (me.must_change) { location.href = '/login'; return; }
  const d = await api('/broker/portal');
  $('#hi').textContent = d.broker.name; $('#hsub').textContent = `ترخيص ${d.broker.license_no} · عمولة ${new Intl.NumberFormat('ar-OM-u-nu-latn',{maximumFractionDigits:1}).format(d.broker.rate * 100)}٪ · ${H()}`;
  const due = d.commissions.filter(c => c.status === 'due').reduce((a, c) => a + c.amount, 0), paid = d.commissions.filter(c => c.status === 'paid').reduce((a, c) => a + c.amount, 0);
  const projs = [...new Set(d.inventory.map(i => i.project))];
  $('#m').innerHTML = `
  <div class="card"><div class="k"><div><small>عملائي المسجلون</small><b>${N(d.leads.length)}</b></div><div><small>عمولات مستحقة</small><b>${OMR(due)}</b></div><div><small>عمولات مدفوعة</small><b>${OMR(paid)}</b></div></div></div>
  <div class="card"><h2>سجّل عميلًا جديدًا</h2><div class="muted">التسجيل محمي برقم الهاتف: أول من يسجّل العميل يحفظ حقه في العمولة.</div>
   <label for="n">اسم العميل</label><input id="n"><label for="p">الهاتف</label><input id="p" inputmode="tel" dir="ltr" style="text-align:right" placeholder="+968 9xxx xxxx">
   <label for="pr">المشروع</label><select id="pr"></select><label for="i">الاهتمام</label><input id="i" placeholder="مثال: شقة غرفتين بإطلالة بحرية"><label for="b">الميزانية التقريبية (ر.ع)</label><input id="b" inputmode="numeric" dir="ltr" style="text-align:right">
   <div class="err" id="e"></div><button class="btn" id="go">تسجيل العميل</button></div>
  <div class="card"><h2>المخزون المتاح للبيع</h2>${d.inventory.map(i => `<div class="row"><div><b>${esc(i.type)}</b> · ${esc(i.view)}<div class="muted">${esc(i.project)}</div></div><div style="text-align:left"><b>${N(i.available)}</b> متاحة<div class="muted">من ${OMR(i.from_price)}</div></div></div>`).join('') || '<div class="muted">لا يوجد مخزون متاح.</div>'}</div>
  <div class="card"><h2>عملائي</h2>${d.leads.map(l => `<div class="row"><div><b>${esc(l.name)}</b><div class="muted">${esc(l.interest || '')} · ${D(l.created)}</div></div><span class="pill p-bl">${STAGES[l.stage] || '—'}</span></div>`).join('') || '<div class="muted">لم تسجّل عملاء بعد.</div>'}</div>
  <div class="card"><h2>عمولاتي</h2>${d.commissions.map(c => `<div class="row"><div><b>الوحدة <bdi>${esc(c.unit)}</bdi></b><div class="muted">${c.paid_at ? 'صُرفت ' + D(c.paid_at) : 'تُصرف بعد تحصيل 20٪ من الثمن'}</div></div><div><b>${OMR(c.amount)}</b> <span class="pill ${CS[c.status][1]}">${CS[c.status][0]}</span></div></div>`).join('') || '<div class="muted">لا توجد عمولات بعد.</div>'}
   <div class="ai">تُسترد العمولة تلقائيًا إذا فُسخ عقد البيع قبل التسليم.</div></div>`;
  const ps = await api('/broker/projects').catch(() => null);
  PROJ = ps || [];
  $('#pr').innerHTML = PROJ.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  $('#go').onclick = async () => {
    const body = {name: $('#n').value.trim(), phone: $('#p').value.trim(), project_id: +$('#pr').value, interest: $('#i').value.trim(), budget: +($('#b').value.replace(/[^\d]/g, '') || 0)};
    $('#go').disabled = true; $('#e').textContent = '';
    try { await api('/broker/leads', {method: 'POST', body}); toast('✓ سُجّل العميل باسمك'); await load(); }
    catch (x) { $('#e').textContent = x.message; $('#go').disabled = false; }
  };
}
load().catch(e => toast(e.message, 1));
