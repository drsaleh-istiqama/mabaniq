const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const N = v => new Intl.NumberFormat('ar-OM-u-nu-latn').format(Math.round(v || 0));
const OMR = v => N(v) + '\u00a0ر.ع';
const WD = t => String(t ?? '').replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/(\d)٫(?=\d)/g, '$1.'); // الوحدة 3 — قرار ب: أرقام غربية في كل الواجهة؛ ثابت واحد يطبَّع هنا
const esc = s => WD(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const J = v => esc(JSON.stringify(v));
document.addEventListener('click', e => {
  const el = e.target.closest('[data-call]'); if (!el) return;
  const f = window[el.dataset.call] || ({unsheet, openContract, vote, payNow, gotoPay: () => document.querySelector('[data-t=pay]')?.click()})[el.dataset.call];
  if (typeof f !== 'function') return; e.preventDefault(); f(...(el.dataset.args ? JSON.parse(el.dataset.args) : []));
});

const D = d => d ? new Date(d).toLocaleDateString('ar-OM-u-nu-latn', {day: 'numeric', month: 'long', year: 'numeric'}) : '—';
const H = d => new Intl.DateTimeFormat('ar-SA-u-ca-islamic-umalqura-nu-latn', {day: 'numeric', month: 'long', year: 'numeric'}).format(d ? new Date(d) : new Date());
const PLAN = {milestone: 'مربوطة بمراحل الإنشاء', '6040': '60/40', murabaha: 'مرابحة عبر بنك شريك'};
const SVC = {new: ['جديد', 'p-bl'], in_progress: ['قيد التنفيذ', 'p-w'], done: ['مُنجز', 'p-ok']};
const RS = {pending: ['بانتظار موافقة المطوّر', 'p-w'], listed: ['معروضة في السوق الثانوي', 'p-ok'], rejected: ['مرفوض', 'p-b'], sold: ['بِيعت وتم التنازل', 'p-bl']};
let DATA, CUR = 0;
function toast(t, bad) { const e = $('#toast'); e.textContent = t; e.classList.toggle('bad', !!bad); e.classList.add('on'); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('on'), 3000); }
const csrf = () => (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
async function api(p, o = {}) {
  const r = await fetch('/api' + p, {...o, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf(), ...(o.headers || {})}, body: o.body ? JSON.stringify(o.body) : undefined});
  if (r.status === 401) { location.href = '/login'; throw new Error('انتهت الجلسة'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر تنفيذ الطلب');
  return j;
}
$$('nav button').forEach(b => b.onclick = () => { $$('nav button').forEach(x => x.classList.toggle('on', x === b)); $$('.tab').forEach(t => t.classList.toggle('on', t.id === 't-' + b.dataset.t)); scrollTo(0, 0); });
$('#out').onclick = async () => { await fetch('/api/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': csrf()}}); location.href = '/login'; };
$('#bk').onchange = e => { CUR = +e.target.value; render(); };

let EX = {notifications: [], contracts: [], handover: [], invoices: [], motions: [], documents: []};
let DOCS = {contracts: [], invoices: [], receipts: []}, PLANSV = [];
async function load() { const me = await api('/me'); if (me.must_change) return forcePw(); [DATA, EX, DOCS, PLANSV] = await Promise.all([api('/portal'), api('/portal/extra').catch(() => EX), api('/portal/docs').catch(() => DOCS), api('/portal/plans').catch(() => [])]); render(); if (DATA.consent_required) consentSheet(DATA.consent_required); }
async function consentSheet(version) {
  const n = await api('/privacy/notice');
  sheet(`<h2>إشعار الخصوصية</h2><div class="muted">الإصدار ${esc(n.version)} · ${esc(n.law)}</div>
   <div class="contract" style="max-height:40vh"><b>لماذا نعالج بياناتك</b>\n${n.purposes.map(x => '• ' + esc(x)).join('\n')}\n\n<b>ما نجمعه</b>\n${n.data.map(x => '• ' + esc(x)).join('\n')}\n\n<b>مدة الاحتفاظ</b>\n${esc(n.retention)}\n\n<b>حقوقك</b>\n${n.rights.map(x => '• ' + esc(x)).join('\n')}\n\n<b>التواصل</b>\n${esc(n.contact)}</div>
   <label class="chk"><input type="checkbox" id="ca"> قرأت إشعار الخصوصية وأوافق على معالجة بياناتي للأغراض المذكورة.</label>
   <div class="err" id="ce"></div><button class="btn w" id="cgo">تسجيل الموافقة</button>`);
  $('#sheet').onclick = null;
  $('#cgo').onclick = async () => { if (!$('#ca').checked) return $('#ce').textContent = 'يلزم الإقرار أولًا';
    try { await api('/portal/consent', {method: 'POST', body: {version, accept: true}}); unsheet(); $('#sheet').onclick = e => { if (e.target.id === 'sheet') unsheet(); }; toast('✓ سُجّلت موافقتك'); DATA.consent_required = null; } catch (e) { $('#ce').textContent = e.message; } };
}
const sheet = h => { $('#sh').innerHTML = h; $('#sheet').classList.add('on'); };
const unsheet = () => $('#sheet').classList.remove('on');
$('#sheet').onclick = e => { if (e.target.id === 'sheet') unsheet(); };
function forcePw() {
  sheet(`<h2>غيّر كلمة المرور المؤقتة</h2><div class="muted">هذا أول دخول لك. اختر كلمة مرور خاصة بك (10 أحرف على الأقل، حروف وأرقام).</div>
   <label>كلمة المرور الحالية</label><input id="pc" type="password" dir="ltr"><label>الجديدة</label><input id="pn" type="password" dir="ltr" autocomplete="new-password"><label>تأكيدها</label><input id="pn2" type="password" dir="ltr" autocomplete="new-password">
   <div class="err" id="pe"></div><button class="btn w" id="pgo">حفظ</button>`);
  $('#sheet').onclick = null;
  $('#pgo').onclick = async () => { if ($('#pn').value !== $('#pn2').value) return $('#pe').textContent = 'التأكيد لا يطابق';
    try { await api('/auth/password', {method: 'POST', body: {current: $('#pc').value, new: $('#pn').value}}); unsheet(); toast('✓ تغيّرت كلمة المرور'); $('#sheet').onclick = e => { if (e.target.id === 'sheet') unsheet(); }; load(); } catch (e) { $('#pe').textContent = e.message; } };
}
function render() {
  const first = DATA.customer.split(' ')[0];
  $('#hi').textContent = `أهلًا ${first}`;
  $('#hsub').textContent = `${H()} · ${D(new Date())}`;
  if (!DATA.bookings.length) { $$('.tab').forEach(t => t.innerHTML = '<div class="card empty muted">لا توجد وحدات مرتبطة بحسابك.</div>'); return; }
  const sel = $('#bk'); sel.hidden = DATA.bookings.length < 2;
  sel.innerHTML = DATA.bookings.map((b, i) => `<option value="${i}" ${i === CUR ? 'selected' : ''}>${esc(b.unit)} · ${esc(b.project)}</option>`).join('');
  const b = DATA.bookings[CUR];
  home(b); pay(b); svc(b); sell(b); more(b);
}
function ring(p) {
  const r = 34, c = 2 * Math.PI * r;
  return `<svg width="86" height="86" viewBox="0 0 86 86" aria-hidden="true"><circle cx="43" cy="43" r="${r}" fill="none" stroke="#E1E6EE" stroke-width="9"/><circle cx="43" cy="43" r="${r}" fill="none" stroke="#1E8A5A" stroke-width="9" stroke-linecap="round" stroke-dasharray="${c * p / 100} ${c}" transform="rotate(-90 43 43)"/></svg>`;
}
function home(b) {
  const cur = b.milestones.find(m => !m.done);
  $('#t-home').innerHTML = `
  <div class="card"><div class="row"><div><div class="muted">${esc(b.project)} · ${esc(b.location)}</div><h2 style="margin:2px 0">${esc(b.type)} <bdi>${esc(b.unit)}</bdi></h2>
    <div class="muted">${N(b.area)} م²${b.floor ? ' · الطابق ' + N(b.floor) : ''} · ${esc(b.view)}</div></div>
    ${b.status === 'confirmed' ? '<span class="pill p-ok">مؤكَّد</span>' : '<span class="pill p-w">حجز مبدئي</span>'}</div></div>
  <div class="card"><h2>تقدم بناء مشروعك</h2>
    <div class="ring">${ring(b.build_pct)}<div><b>${N(b.build_pct)}٪</b><div class="muted">التسليم المتوقع: ${D(b.handover)}</div>
    <div class="muted">النسبة مُتحقق منها بـ ${N(b.evidence_photos)} صورة من الموقع</div></div></div>
    <ul class="ms">${b.milestones.map(m => `<li><span class="d ${m.done ? 'y' : m === cur ? 'n' : ''}">${m.done ? '✓' : ''}</span><span style="flex:1">${m.name}</span><span class="muted">${m.done ? 'مكتملة' : m === cur ? 'جارية الآن' : 'لاحقًا'}</span></li>`).join('')}</ul></div>
  <div class="card"><div class="row"><h2 style="margin:0">ما سدّدته</h2><b style="color:var(--ok)">${N(100 * b.paid / b.total)}٪</b></div>
    <div class="bar"><i style="width:${100 * b.paid / b.total}%"></i></div><div class="row muted"><span>${OMR(b.paid)}</span><span>من ${OMR(b.total)}</span></div>
    ${b.next ? `<div class="ai">القسط القادم: <b>${OMR(b.next.amount - b.next.paid_amount)}</b> · ${esc(b.next.label)} · ${D(b.next.due_date)}</div><button class="btn w" data-call="gotoPay">ادفع الآن</button>` : '<div class="ai">✓ سدّدت جميع الأقساط. شكرًا لك.</div>'}</div>`;
}
function pay(b) {
  const firstUnpaid = b.installments.find(i => i.paid_amount < i.amount - 1);
  $('#t-pay').innerHTML = `<div class="card"><h2>جدول الدفعات</h2><div class="muted">خطة الدفع: ${PLAN[b.plan] || esc(b.plan)}</div>
   ${b.installments.map(i => {
     const paid = i.paid_amount >= i.amount - 1, late = !paid && new Date(i.due_date) < new Date();
     return `<div class="inst"><div class="row"><b>${esc(i.label)}</b><b>${OMR(i.amount)}</b></div>
      <div class="row"><span class="muted">${D(i.due_date)}</span>${paid ? `<span class="pill p-ok">مدفوع ${i.paid_date ? '· ' + D(i.paid_date) : ''}</span>` : late ? '<span class="pill p-b">متأخر</span>' : '<span class="pill p-bl">قادم</span>'}</div>
      ${i === firstUnpaid ? `<button class="btn w" style="margin-top:9px" data-call="payNow" data-args="${J([i.id, i.amount - i.paid_amount])}">ادفع ${OMR(i.amount - i.paid_amount)}</button>` : ''}</div>`; }).join('')}
   <p class="muted">الدفع هنا تجريبي (بيئة اختبار). في الإطلاق يُربط ببوابة دفع وطنية وبحساب الضمان مباشرة.</p></div>`;
}
async function payNow(id, amt) {
  try {
    const it = await api('/portal/pay/intent', {method: 'POST', body: {installment_id: id}});
    sheet(`<h2>بوابة الدفع (بيئة اختبار)</h2><div class="muted">${esc(it.note)}</div><div class="ai" style="font-size:20px;text-align:center"><b>${OMR(it.amount)}</b></div>
      <div class="muted">مرجع العملية: <bdi>${esc(it.intent)}</bdi></div><button class="btn w" id="pz">إتمام الدفع التجريبي</button><button class="btn w g" style="margin-top:8px" data-call="unsheet">إلغاء</button>`);
    $('#pz').onclick = async () => { $('#pz').disabled = true; try { const r = await api('/portal/pay/sandbox-complete', {method: 'POST', body: {intent: it.intent}}); unsheet(); toast(`✓ تم السداد · إيصال ${r.receipt || ''}`); await load(); } catch (e) { toast(e.message, 1); $('#pz').disabled = false; } };
  } catch (e) { toast(e.message, 1); }
}
function svc(b) {
  $('#t-svc').innerHTML = `<div class="card"><h2>طلب صيانة جديد</h2>
   <label for="sc">نوع الطلب</label><select id="sc">${['سباكة', 'كهرباء', 'تكييف', 'ملاحظة تشطيب', 'أخرى'].map(x => `<option>${x}</option>`).join('')}</select>
   <label for="sd">وصف المشكلة</label><textarea id="sd" placeholder="مثال: تسريب ماء تحت مغسلة المطبخ"></textarea>
   <div class="err" id="se"></div><button class="btn w" id="sgo">إرسال الطلب</button></div>
   <div class="card"><h2>طلباتي</h2>${b.service.map(s => `<div class="inst"><div class="row"><b>#${N(s.id)} · ${esc(s.category)}</b><span class="pill ${SVC[s.status][1]}">${SVC[s.status][0]}</span></div><div>${esc(s.description)}</div><div class="muted">أُرسل ${D(s.created)}${s.note ? ' · ملاحظة الفريق: ' + esc(s.note) : ''}</div></div>`).join('') || '<div class="muted">لا توجد طلبات.</div>'}</div>`;
  $('#sgo').onclick = async () => {
    const d = $('#sd').value.trim(); if (d.length < 5) return $('#se').textContent = 'اكتب وصفًا أوضح (5 أحرف على الأقل)';
    $('#sgo').disabled = true;
    try { const r = await api('/portal/service', {method: 'POST', body: {booking_id: b.booking_id, category: $('#sc').value, description: d}}); toast(`✓ استلمنا طلبك رقم ${N(r.id)}`); await load(); }
    catch (e) { $('#se').textContent = e.message; $('#sgo').disabled = false; }
  };
}
function sell(b) {
  const m = b.market_estimate || {}, open = b.resale.find(r => r.status !== 'rejected'), paidPct = 100 * b.paid / b.total;
  let h = `<div class="card"><h2>قيمة وحدتك اليوم ✦</h2>
   <div style="font-size:24px;font-weight:700">${OMR(m.low)} – ${OMR(m.high)}</div>
   <div class="muted">سعر شرائك ${OMR(b.price)} · التغير المقدّر <b style="color:${m.gain_pct >= 0 ? 'var(--ok)' : 'var(--bad)'}">${m.gain_pct >= 0 ? '+' : ''}${N(m.gain_pct)}٪</b></div>
   <div class="ai">أساس التقدير: ${esc(m.basis)}، مع علاوة تقدّم الإنشاء. التقدير استرشادي وليس تقييمًا معتمدًا.</div></div>`;
  if (open) h += `<div class="card"><h2>طلبك الحالي</h2><div class="row"><b>${OMR(open.ask_price)}</b><span class="pill ${RS[open.status][1]}">${RS[open.status][0]}</span></div><div class="muted">رسوم نقل الملكية للمطوّر: ${OMR(open.fee)} (2٪)</div></div>`;
  else if (b.status !== 'confirmed') h += `<div class="card muted">تُتاح إعادة البيع بعد تأكيد الشراء.</div>`;
  else if (paidPct < 30) h += `<div class="card muted">تُتاح إعادة البيع بعد سداد 30٪ من قيمة الوحدة. سدّدت حتى الآن ${N(paidPct)}٪.</div>`;
  else h += `<div class="card"><h2>اعرض وحدتك للبيع</h2><div class="muted">يُعرض طلبك على المطوّر للموافقة، ثم يظهر للمشترين في السوق الثانوي داخل مبانيك.</div>
     <label for="ap">السعر المطلوب (ر.ع)</label><input id="ap" inputmode="numeric" dir="ltr" style="text-align:right" value="${Math.round(m.mid || b.price)}">
     <div class="muted" id="fee"></div><div class="err" id="re"></div><button class="btn w" id="rgo">إرسال طلب إعادة البيع</button></div>`;
  $('#t-sell').innerHTML = h;
  const ap = $('#ap'); if (!ap) return;
  const upd = () => { const v = +ap.value.replace(/[^\d]/g, ''); $('#fee').textContent = v ? `رسوم نقل الملكية (2٪): ${OMR(v * .02)}` : ''; };
  ap.oninput = upd; upd();
  $('#rgo').onclick = async () => {
    const v = +ap.value.replace(/[^\d]/g, ''); if (!v) return $('#re').textContent = 'أدخل سعرًا صحيحًا';
    $('#rgo').disabled = true;
    try { await api('/portal/resale', {method: 'POST', body: {booking_id: b.booking_id, ask_price: v}}); toast('✓ أُرسل طلبك للمطوّر'); await load(); }
    catch (e) { $('#re').textContent = e.message; $('#rgo').disabled = false; }
  };
}
function more(b) {
  const k = EX.contracts.find(c => c.booking_id === b.booking_id), ho = EX.handover.find(x => x.booking_id === b.booking_id);
  const mo = EX.motions.filter(m => m.booking_id === b.booking_id);
  const nb = $('#nb'); const pending = (k && !k.customer_signed_at ? 1 : 0) + mo.filter(m => !m.my_vote).length; nb.hidden = !pending; nb.textContent = N(pending);
  $('#t-more').innerHTML = `
  <div class="card"><h2>عقد البيع</h2>${k ? `<div class="row"><b>${esc(k.number)}</b>${k.customer_signed_at ? `<span class="pill p-ok">موقَّع ${D(k.customer_signed_at)}</span>` : '<span class="pill p-w">بانتظار توقيعك</span>'}</div>
     <button class="btn w ${k.customer_signed_at ? 'g' : ''}" style="margin-top:10px" data-call="openContract" data-args="${J([b.booking_id])}">${k.customer_signed_at ? 'عرض العقد' : 'قراءة العقد وتوقيعه'}</button>` : '<div class="muted">يصدر العقد بعد استكمال التحقق من هويتك لدى فريق المبيعات.</div>'}</div>
  ${mo.length ? `<div class="card"><h2>تصويت اتحاد الملاك</h2>${mo.map(m => `<div class="inst"><b>${esc(m.title)}</b><div class="muted">يغلق ${D(m.closes)} · صوتك موزون بمساحة وحدتك</div>
     ${m.my_vote ? `<span class="pill p-ok">صوّتَّ: ${{yes: 'موافق', no: 'غير موافق', abstain: 'ممتنع'}[m.my_vote]}</span>` : `<div class="vote"><button class="btn" data-call="vote" data-args="${J([m.id, b.booking_id, 'yes'])}">موافق</button><button class="btn g" data-call="vote" data-args="${J([m.id, b.booking_id, 'no'])}">غير موافق</button><button class="btn g" data-call="vote" data-args="${J([m.id, b.booking_id, 'abstain'])}">ممتنع</button></div>`}</div>`).join('')}</div>` : ''}
  ${ho ? `<div class="card"><h2>التسليم</h2><div class="row"><span>الموعد</span><b>${D(ho.appointment)}</b></div>${ho.certificate_no ? `<div class="muted">شهادة ${esc(ho.certificate_no)} · ضمان التشطيب حتى ${D(ho.warranty_until)}</div>` : ''}
     ${ho.snags.length ? ho.snags.map(s => `<div class="inst row"><span>${esc(s.item)}</span><span class="pill ${s.status === 'open' ? 'p-w' : 'p-ok'}">${s.status === 'open' ? 'قيد الإصلاح' : 'أُصلحت'}</span></div>`).join('') : '<div class="muted">لا ملاحظات مسجلة.</div>'}</div>` : ''}
  <div class="card"><h2>الإشعارات</h2>${EX.notifications.map(n => `<div class="inst"><b>${esc(n.title)}</b><div>${esc(n.body)}</div><div class="muted">${D(n.created)}</div></div>`).join('') || '<div class="muted">لا إشعارات جديدة.</div>'}</div>
  ${planCard(b)}
  <div class="card"><h2>مستنداتي الرسمية</h2><div class="muted">نسخ PDF موقَّعة ومختومة إلكترونيًا برمز تحقق — للطباعة أو الحفظ.</div>
   ${DOCS.contracts.filter(c => c.booking_id === b.booking_id).map(c => `<div class="inst row"><span>عقد البيع <bdi>${esc(c.number)}</bdi> ${c.signed ? '<span class="pill p-ok">موقَّع</span>' : ''}</span><a class="pill p-bl" href="${c.pdf}" target="_blank" rel="noopener">PDF</a></div>`).join('')}
   ${DOCS.receipts.map(r => `<div class="inst row"><span>إيصال <bdi>${esc(r.receipt)}</bdi> · ${esc(r.label)} · ${OMR(r.amount)}</span><a class="pill p-bl" href="${r.pdf}" target="_blank" rel="noopener">PDF</a></div>`).join('') || '<div class="muted">لا إيصالات بعد.</div>'}</div>
  <div class="card"><h2>فواتيري</h2>${EX.invoices.map(v => `<div class="inst"><div class="row"><b><bdi>${esc(v.number)}</bdi></b><b>${OMR(v.total)}</b></div><div class="muted">${D(v.issued)} · ضريبة ${OMR(v.vat)} · ${esc(v.note)}</div>${(DOCS.invoices.find(x => x.number === v.number) || {}).pdf ? `<a class="pill p-bl" href="${DOCS.invoices.find(x => x.number === v.number).pdf}" target="_blank" rel="noopener">PDF</a>` : ''}</div>`).join('') || '<div class="muted">تصدر الفاتورة مع كل سداد.</div>'}</div>
  ${EX.documents.length ? `<div class="card"><h2>مستنداتي</h2>${EX.documents.map(d => `<div class="inst row"><span>${esc(d.title)}</span><a class="pill p-bl" href="/api/portal/documents/${d.id}" target="_blank" rel="noopener">فتح</a></div>`).join('')}</div>` : ''}
  <div class="card"><h2>خصوصيتي</h2><div class="muted">وفق قانون حماية البيانات الشخصية العُماني يحق لك طلب نسخة من بياناتك أو تصحيحها أو حذف ما لا يلزم حفظه نظامًا.</div>
   <button class="btn w g" style="margin-top:10px" id="pex">تنزيل نسخة من بياناتي</button>
   <select id="pk" style="margin-top:10px"><option value="correct">طلب تصحيح بيانات</option><option value="erase">طلب حذف بيانات</option></select><input id="pnote" placeholder="تفاصيل الطلب" style="margin-top:8px"><button class="btn w" style="margin-top:8px" id="pgo2">إرسال الطلب</button></div>
  <div class="card"><h2>أمان حسابي</h2><button class="btn w g" id="cpw">تغيير كلمة المرور</button><button class="btn w g" style="margin-top:8px" id="sall">تسجيل الخروج من كل الأجهزة الأخرى</button></div>`;
  $('#sall').onclick = async () => { try { const r = await api('/me/sessions/revoke', {method: 'POST', body: {others: true}}); toast(`✓ أُنهيت ${N(r.revoked)} جلسة على أجهزة أخرى`); } catch (e) { toast(e.message, 1); } };
  $('#pex').onclick = async () => { const d = await api('/portal/privacy/export'); const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 1)], {type: 'application/json'})); a.download = 'mabaniq-my-data.json'; a.click(); toast('✓ نُزّلت نسخة بياناتك'); };
  $('#pgo2').onclick = async () => { try { const r = await api('/portal/privacy', {method: 'POST', body: {kind: $('#pk').value, note: $('#pnote').value}}); toast('✓ استلمنا طلبك رقم ' + N(r.id)); } catch (e) { toast(e.message, 1); } };
  $('#cpw').onclick = () => { forcePw(); $('#sh h2').textContent = 'تغيير كلمة المرور'; $('#sh .muted').textContent = ''; $('#sheet').onclick = e => { if (e.target.id === 'sheet') unsheet(); }; };
}
const PK = {site: 'المخطط العام', floor: 'مخطط الطابق', unit: 'مخطط الوحدة', elevation: 'الواجهة', section: 'قطاع', render: 'التصور النهائي'};
function planView(p, hl) { return p.mime === 'application/pdf' ? `<a class="pill p-bl" href="${p.url}" target="_blank" rel="noopener">فتح ${esc(p.title)}</a>` : `<div class="plan"><img src="${p.url}" alt="${esc(p.title)}" loading="lazy">${(p.markers || []).map(m => `<span class="mk ${m.unit_code === hl ? 'hl' : ''}" style="left:${m.x}%;top:${m.y}%">وحدتك</span>`).join('')}</div>`; }
function planCard(b) {
  const pv = PLANSV.find(x => x.booking_id === b.booking_id); if (!pv || (!pv.floor_plan && !pv.unit_plan && !pv.others.length)) return '';
  return `<div class="card"><h2>وحدتي في المبنى</h2>${pv.floor_plan ? `<div class="muted">${esc(pv.floor_plan.title)}${pv.floor_plan.me ? ' — موقع وحدتك محدَّد بالعلامة' : ''}</div>${planView(pv.floor_plan, pv.unit)}` : ''}
   ${pv.unit_plan ? `<div class="muted" style="margin-top:10px">${esc(pv.unit_plan.title)}</div>${planView(pv.unit_plan)}` : ''}
   ${pv.others.length ? `<div class="muted" style="margin-top:10px">المشروع</div><div class="gal">${pv.others.map(o => `<figure>${planView(o)}<figcaption>${PK[o.kind] || o.kind}: ${esc(o.title)}</figcaption></figure>`).join('')}</div>` : ''}</div>`;
}
async function openContract(bid) {
  window.__pdf = `/api/portal/docs/contract/${bid}.pdf`;
  try {
    const k = await api('/portal/contract/' + bid);
    sheet(`<h2>عقد بيع ${esc(k.number)}</h2><div class="muted">بصمة النص: <bdi>${esc(k.sha256.slice(0, 16))}…</bdi></div><div class="contract">${esc(k.body)}</div>
      ${k.customer_signed_at ? `<div class="ai">✓ وقّعته في ${D(k.customer_signed_at)} · سلامة النص: ${k.integrity_ok ? 'مطابقة للأصل' : '⚠ غير مطابقة'}</div><button class="btn w g" data-call="unsheet">إغلاق</button>` :
      `<label>اكتب اسمك الكامل كما في الهوية</label><input id="tn"><label>أكّد كلمة مرورك للتوقيع</label><input id="tp" type="password" dir="ltr" autocomplete="current-password">
       <label class="chk"><input type="checkbox" id="ta"> قرأت العقد كاملًا وأوافق على جميع بنوده، وأقر بأن هذا التوقيع الإلكتروني ملزم لي.</label>
       <div class="err" id="te"></div><button class="btn w" id="tgo">توقيع العقد</button><button class="btn w g" style="margin-top:8px" data-call="unsheet">لاحقًا</button>`}`);
    if ($('#tgo')) $('#tgo').onclick = async () => { $('#tgo').disabled = true;
      try { await api(`/portal/contract/${bid}/sign`, {method: 'POST', body: {typed_name: $('#tn').value.trim(), accept: $('#ta').checked, password: $('#tp').value}}); unsheet(); toast('✓ وُقّع العقد. أُرسلت نسخة إلى المطوّر'); await load(); }
      catch (e) { $('#te').textContent = e.message; $('#tgo').disabled = false; } };
  } catch (e) { toast(e.message, 1); }
}
async function vote(mid, bid, v) { try { const r = await api(`/portal/oa/${mid}/vote`, {method: 'POST', body: {booking_id: bid, vote: v}}); toast(`✓ سُجّل صوتك (وزنه ${N(r.weight)}٪)`); await load(); } catch (e) { toast(e.message, 1); } }
load().catch(e => toast(e.message, 1));
