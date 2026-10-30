import * as CH from './charts.js';
import {t, applyI18n, toggleLang, lang} from './i18n.js';
/* مبانيك — منطق الواجهة. كل البيانات تأتي من الـ API الحي. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const nf = new Intl.NumberFormat('ar-OM-u-nu-latn'), N = v => nf.format(Math.round(v || 0));
const OMR = v => v == null ? '—' : N(v) + '\u00a0ر.ع';
const K = v => Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 2}) + ' مليون' : Math.abs(v) >= 1e3 ? N(v / 1e3) + ' ألف' : N(v);
const WD = t => String(t ?? '').replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/(\d)٫(?=\d)/g, '$1.'); // الوحدة 3 — قرار ب: أرقام غربية في كل الواجهة؛ ثابت واحد يطبَّع هنا
const tx = t => esc(t);
const esc = s => WD(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
/* 0.5.0 — M7: تفويض الأحداث بدل onclick المضمّن (CSP بلا unsafe-inline) */
const J = v => esc(JSON.stringify(v));
const CALLS = {};
document.addEventListener('click', e => {
  const el = e.target.closest('[data-call]');
  if (!el) return;
  const [ns, fn] = el.dataset.call.includes('.') ? el.dataset.call.split('.') : [null, el.dataset.call];
  const obj = ns ? (CALLS[ns] || window[ns] || {}) : null;
  const f = obj ? obj[fn] : (CALLS[fn] || window[fn]);
  if (typeof f !== 'function') { console.warn('no handler', el.dataset.call); return; }
  e.preventDefault();
  f.apply(obj, el.dataset.args ? JSON.parse(el.dataset.args) : []);  // keep `this` for namespaced handlers (EXT.sub uses this.cur)
});
const csrf = () => (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';

const fmtMonth = m => new Date(m + '-01').toLocaleDateString('ar-OM-u-nu-latn', {month: 'long', year: 'numeric'});
const fmtDate = d => d ? new Date(d).toLocaleDateString('ar-OM-u-nu-latn', {day: 'numeric', month: 'short', year: 'numeric'}) : '—';
const STAGES = ['جديد', 'مؤهَّل', 'معاينة', 'تفاوض', 'حجز'];
const ST = {a: 'متاحة', r: 'محجوزة', s: 'مباعة'};
const PLANS = {milestone: ['مربوطة بمراحل الإنشاء', '10٪ حجز ثم 15٪ عند كل مرحلة مُتحقق منها'],
  '6040': ['60/40', '60٪ أثناء البناء و40٪ عند التسليم'], murabaha: ['مرابحة عبر بنك شريك', '20٪ مقدمًا والباقي تمويل متوافق مع الشريعة']};

async function api(path, opt = {}) {
  const r = await fetch('/api' + path, {...opt, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf(), ...(opt.headers || {})},
    body: opt.body ? JSON.stringify(opt.body) : undefined});
  if (r.status === 401) { location.href = '/login'; throw new Error('انتهت الجلسة'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر تنفيذ الطلب');
  return j;
}
function toast(t, bad) { const e = $('#toast'); e.textContent = t; e.classList.toggle('bad', !!bad); e.classList.add('on'); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('on'), 2800); }
function insp(title, html) { $('#ih').textContent = title; $('#ib').innerHTML = html; document.body.classList.add('io'); }
function sel(tr) { tr?.parentNode?.querySelectorAll('tr').forEach(x => x.classList.remove('sel')); tr?.classList.add('sel'); }
const pill = (t, c) => `<span class="pill ${c}">${t}</span>`;
const scoreC = v => v >= 75 ? 'p-ok' : v >= 50 ? 'p-w' : 'p-b';

/* ---------------- الحالة والتنقل ---------------- */
const S = {screen: 'ov', projects: [], proj: null, bld: null, plan: 0, me: null};
const SCREEN_PERM = {hr: 'hr', pay: 'hr_payroll', me: 'hr_self', lp: 'lessee', acc: 'accounting', pmg: 'leasing_pm', lea: 'leasing', ov: 'view', inv: 'inventory', crm: 'leads', fin: 'finance', con: 'construction', svc: 'service', log: 'audit', pre: 'permits', sal: 'kyc', bill: 'invoices', post: 'handover', rep: 'reports', mk: 'leads', adm: 'view'};
const SCREEN_ANY = {pre: ['permits', 'land'], post: ['handover', 'oa', 'leasing', 'service'], sal: ['kyc', 'brokers', 'market'], rep: ['reports', 'finance', 'view'], mk: ['leads', 'inventory', 'reports']};  // Unit 7: reports for every staff role (the API filters by permission), marketing for sales/inventory/reports
const can = p => S.me?.perms.includes(p);
const SCREEN_MOD = {hr: ['hr'], pay: ['hr'], me: ['hr'], lp: ['leasing'], acc: ['accounting'], pmg: ['leasing'], lea: ['leasing'], pre: ['land'], inv: [], crm: ['sales'], mk: ['marketing'], sal: ['sales'], con: ['construction'], post: ['handover', 'leasing'], svc: ['handover'], fin: ['finance'], bill: ['finance'], rep: ['reports']};  // 0.20.0: a screen needs one of its modules (none listed = core)
const modOn = m => (S.me?.modules || []).includes(m);
const canS = s => (SCREEN_ANY[s] || [SCREEN_PERM[s]]).some(can) && (!(SCREEN_MOD[s] || []).length || SCREEN_MOD[s].some(modOn)) && (s !== 'me' || !!S.me?.employee_id) && (s !== 'lp' || !!S.me?.lessee_id);  // 0.25.0: the portal needs a login that is linked to an employee file
function go(s) {
  if (!canS(s)) s = canS('ov') ? 'ov' : canS('lp') ? 'lp' : canS('me') ? 'me' : canS('pay') ? 'pay' : 'rep';
  S.screen = s;
  $$('[data-s]').forEach(b => b.classList.toggle('on', b.dataset.s === s));
  $$('.scr').forEach(x => x.classList.toggle('on', x.id === s));
  localStorage.setItem('mbq-screen', s);
  ({ov: loadOverview, inv: loadInventory, crm: loadCRM, fin: loadFinance, con: () => { loadIPC(); EXT.l_conx(); }, svc: loadService, log: loadAudit,
    acc: () => EXT.l_acc(), hr: () => EXT.l_hr(), pay: () => EXT.l_pay(), me: () => EXT.l_me(), lp: () => EXT.l_lp(), pmg: () => EXT.l_pm(), lea: () => EXT.l_lea(), pre: () => EXT.l_pre(), sal: () => EXT.l_sal(), bill: () => EXT.l_bill(), post: () => EXT.l_post(), rep: () => EXT.l_rep(), mk: () => EXT.l_mk(), adm: () => EXT.l_adm()})[s]?.()?.catch?.(e => toast(e.message, 1));
  crumb(); shell(s);
}
$$('[data-s]').forEach(b => b.onclick = e => { e.preventDefault(); document.body.classList.remove('nav-open'); go(b.dataset.s); });
const META = {
  ov: ['', 'لوحة القيادة', 'ما يحتاج قرارك اليوم، وصحة كل مشروع، وموقع المحفظة في دورة التطوير.'],
  pre: ['1 · الأرض والتراخيص', 'الأراضي والجدوى والتراخيص', 'تقييم الأراضي بدراسة جدوى، ومتابعة التراخيص لدى الجهات الحكومية حتى إصدارها.'],
  inv: ['2 · البيع والإنشاء', 'المخزون والتسعير', 'مخطط الوحدات وحالتها، وأداء الشرائح وتوصيات تعديل الأسعار.'],
  crm: ['2 · البيع والإنشاء', 'العملاء المحتملون', 'قمع المبيعات، والعملاء المحتملون مرتّبين بدرجة احتمال الشراء.'],
  sal: ['2 · البيع والإنشاء', 'العقود والوسطاء', 'التحقق من هوية المشترين، وإصدار العقود وتوقيعها، والوسطاء والخصومات والسوق الثانوي.'],
  con: ['2 · البيع والإنشاء', 'الإنشاء والمستخلصات', 'التحقق من نسب الإنجاز قبل الصرف، والجدول الزمني، وأوامر التغيير وتقارير الموقع.'],
  fin: ['عبر الدورة · المالية', 'السيولة والتعثر', 'أرصدة حسابات الضمان المتوقعة لاثني عشر شهرًا، والعملاء المعرّضون للتعثر.'],
  bill: ['عبر الدورة · المالية', 'الفواتير والضمان', 'الفواتير والضريبة، والغرامات والفسخ، والمطابقة البنكية وحساب الضمان والتصدير المحاسبي.'],
  hr: ['عبر الدورة · الموارد البشرية', 'الموارد البشرية', 'الهيكل والموظفون ووثائقهم وتنبيهات انتهائها، والإجازات والحضور وطلبات الموظفين.'],
  pay: ['عبر الدورة · الموارد البشرية', 'الرواتب', 'مسيّر الرواتب والتأمينات وملف تحويل الأجور، والسلف والقروض الحسنة بلا فائدة، ومكافأة نهاية الخدمة والمخالصة.'],
  me: ['عبر الدورة · الموارد البشرية', 'بوابتي', 'ملفي وأرصدة إجازاتي وطلباتي، وفريقي إن كان لي مرؤوسون.'],
  acc: ['عبر الدورة · المالية', 'المحاسبة', 'دليل الحسابات والقيود المزدوجة وميزان المراجعة ودفتر الأستاذ، مع ترحيل أحداث التأجير تلقائيًا.'],
  pmg: ['3 · التسليم والتشغيل', 'محفظتي (مدير عقاري)', 'العقود والتحصيل والمتأخرات والصيانة داخل نطاقك فقط.'],
  lp: ['بوابة المستأجر', 'بوابتي (مستأجر)', 'عقودي ودفعاتي وإيصالاتي وكشف حسابي، وطلبات الصيانة — لملفك وحده.'],
  lea: ['3 · التسليم والتشغيل', 'الإيجارات', 'المحفظة والعقود والمستأجرون والتحصيل والشيكات والمتأخرات.'],
  post: ['3 · التسليم والتشغيل', 'التسليم والأملاك', 'التسليم وملاحظات الفحص، ونقل الملكية، والمرافق واتحاد الملاك والتأجير.'],
  svc: ['3 · التسليم والتشغيل', 'خدمة العملاء', 'طلبات الصيانة وإعادة البيع الواردة من تطبيق العميل.'],
  mk: ['2 · البيع والإنشاء', 'تسويق المشاريع', 'حالة كل مشروع تسويقيًا، الحملات وقياسها، استوديو الإعلانات، والتنبيهات من حركة السوق.'],
  rep: ['الحوكمة', 'التقارير والتحليلات', 'تقرير البنك الممول بتقييم المخاطر، وتقرير المستثمرين بالربحية والتوزيعات.'],
  log: ['الحوكمة', 'سجل التدقيق', 'كل إجراء مسجّل بوقته ومنفّذه في سجل متسلسل يكشف أي تعديل.'],
  adm: ['الحوكمة', 'الإدارة والأمان', 'المستخدمون والصلاحيات، والتحقق الثنائي، والنسخ الاحتياطي والإشعارات والخصوصية.']};
const CYCLE = [['pre', 'الأرض والتراخيص'], ['inv', 'البيع والإنشاء'], ['post', 'التسليم والتشغيل']];
const STEP = {lea: 2, pre: 0, inv: 1, crm: 1, sal: 1, con: 1, post: 2, svc: 2};
function crumb() {
  const p = S.projects.find(x => x.id === S.proj), m = META[S.screen] || ['', ''];
  $('#crumb').innerHTML = S.screen === 'inv' && p ? `${esc(m[1])} / <b>${esc(p.name)}</b>${S.bld && p.kind === 'tower' ? ' / المبنى ' + esc(S.bld) : ''}` : `<b>${esc(m[1])}</b>`;
}
function shell(s) {
  const m = META[s] || ['', '', ''];
  $('#phG').textContent = lang() === 'en' ? t('meta.' + s + '.g', m[0]) : m[0]; $('#phT').textContent = lang() === 'en' ? t('meta.' + s + '.t', m[1]) : m[1]; $('#phD').textContent = lang() === 'en' ? t('meta.' + s + '.d', m[2]) : m[2];
  const st = STEP[s];
  $('#lc').innerHTML = st == null ? '' : CYCLE.map(([k, l], i) => `<li class="${i === st ? 'on' : i < st ? 'done' : ''}"><button data-go="${k}" ${canS(k) ? '' : 'disabled'}><span>${i + 1}</span>${l}</button></li>`).join('');
  $$('#lc [data-go]').forEach(b => b.onclick = () => go(b.dataset.go));
  document.title = m[1] + ' · مبانيك';
}
function stageOf(p) { return p.completed || p.build_pct >= 80 ? 2 : p.build_pct >= 10 ? 1 : 0; }
function renderCycle(P) {
  const cols = [['1 · الأرض والتراخيص', 'دراسة جدوى وترخيص وإطلاق'], ['2 · البيع والإنشاء', 'بيع على الخارطة وتحصيل مربوط بالإنجاز'], ['3 · التسليم والتشغيل', 'تسليم ونقل ملكية واتحاد ملاك وتأجير']];
  $('#cycle').innerHTML = cols.map(([t, d], i) => { const L = P.filter(p => stageOf(p) === i);
    return `<div class="cc"><div class="ct"><b>${t}</b><small>${d}</small></div>${L.map(p => `<button class="pc" data-p="${p.id}"><b>${esc(p.name)}</b><span class="mt"><small>الإنجاز</small><span class="bar2"><i style="width:${p.build_pct}%"></i></span><small>${N(p.build_pct)}٪</small></span><span class="mt"><small>المبيع</small><span class="bar2 s"><i style="width:${p.sold_pct}%"></i></span><small>${N(p.sold_pct)}٪</small></span><small>${N(p.total_units)} وحدة${p.completed ? ' · مُسلَّم' : ''}</small></button>`).join('') || '<div class="muted" style="padding:6px 2px">لا مشاريع حاليًا</div>'}</div>`; }).join('');
  $$('#cycle .pc').forEach(b => b.onclick = () => { S.proj = +b.dataset.p; S.bld = null; go('inv'); loadSide(); });
}
$('#theme').onclick = () => { document.body.classList.toggle('light'); localStorage.setItem('mbq-theme', document.body.classList.contains('light') ? 'l' : 'd'); if (S.screen === 'fin') loadFinance(); };
$('#ix').onclick = () => { document.body.classList.remove('io'); $$('tr.sel').forEach(x => x.classList.remove('sel')); };
$('#askBtn').onclick = () => aiOpen($('#ai').hidden);
$('#hb').onclick = () => document.body.classList.toggle('nav-open');
$('#scrim').onclick = () => { document.body.classList.remove('nav-open', 'io'); $$('tr.sel').forEach(x => x.classList.remove('sel')); };
$('.sb-brand').onclick = () => document.body.classList.remove('nav-open');
$('#logout').onclick = async () => { await fetch('/api/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': csrf()}}); location.href = '/login'; };
$('#resetBtn').onclick = async () => { if (!confirm('إعادة البيانات التجريبية لحالتها الأولى؟')) return; await api('/reset', {method: 'POST'}); toast('أُعيدت البيانات'); refreshAll(); };

/* ---------------- الشجرة والعدادات ---------------- */
async function loadSide() {
  S.projects = (await api('/projects')).sort((a, b) => (a.completed - b.completed) || (a.build_pct - b.build_pct));
  if (!S.proj) S.proj = S.projects[0].id;
  const color = p => p.sold_pct >= 65 ? 'var(--ok)' : p.sold_pct >= 55 ? 'var(--pri)' : 'var(--bad)';
  $('#projTree').innerHTML = S.projects.map(p => `<div class="ti ${p.id === S.proj && S.screen === 'inv' ? 'on' : ''}" data-p="${p.id}"><span><i class="dot" style="background:${color(p)}"></i>${esc(p.name)}</span><small>${N(p.total_units)} وحدة</small></div>`).join('');
  $$('#projTree .ti').forEach(t => t.onclick = () => { S.proj = +t.dataset.p; S.bld = null; go('inv'); loadSide(); });
  const opt = (p, path) => can(p) ? api(path) : Promise.resolve(null);
  const [risk, dec, leads, ipcs] = await Promise.all([opt('finance', '/risk'), api('/decisions'), opt('leads', '/leads'), opt('construction', '/ipcs')]);
  const setC = (id, v) => { const el = $(id); if (!el) return; el.textContent = v ? N(v) : ''; el.classList.toggle('hidden', !v); };
  setC('#cRisk', risk?.length); setC('#cDec', dec.filter(d => !d.done).length);
  setC('#cHot', leads?.filter(l => l.score >= 75).length); setC('#cIpc', ipcs?.filter(i => i.status === 'pending').length);
}
$$('.ti[data-go]').forEach(t => t.onclick = () => go(t.dataset.go));

/* ---------------- نظرة عامة ---------------- */
let DEC = [];
async function loadOverview() {
  const D = await api('/dashboard');   // 0.20.0: widgets of the modules that are on
  const fm = {omr: v => K(v) + ' ر.ع', pct: v => N(v) + '٪', n: v => N(v), text: v => esc(v)};
  $('#kpis').innerHTML = D.tiles.map(t => `<div><small>${esc(t.label)}</small><b${t.tone === 'bad' ? ' style="color:var(--bad)"' : t.tone === 'warn' ? ' style="color:var(--warn,#b7791f)"' : t.tone === 'ok' ? ' style="color:var(--ok)"' : ''}>${!t.value && t.zero_text ? esc(t.zero_text) : fm[t.unit](t.value)}</b><small>${esc(t.sub || '')}${t.sub_month ? ' · ' + fmtMonth(t.sub_month) : ''}</small></div>`).join('');
  const dec = D.decisions;
  DEC = dec;
  $('#qc').textContent = N(dec.filter(d => !d.done).length) + ' مفتوحة';
  $('#dq').innerHTML = dec.map((d, i) => `<tr data-i="${i}" class="${d.done ? 'done' : ''}"><td>${tx(d.title)}</td><td>${pill(esc(d.source), 'p-bl')}</td><td>${K(d.impact)} ر.ع<br><span class="muted">${esc(d.impact_label)}</span></td><td>${pill(d.priority, d.priority === 'حرجة' ? 'p-b' : 'p-w')}</td><td>${d.done ? pill(d.done === 'approve' ? '✓ معتمد' : 'متجاهَل', d.done === 'approve' ? 'p-ok' : '') : pill('مفتوح', 'p-w')}</td></tr>`).join('');
  $$('#dq tr').forEach(tr => tr.onclick = () => { sel(tr); showDecision(DEC[+tr.dataset.i]); });
  $('#cycBox').hidden = $('#phBox').hidden = !D.develop;
  if (D.develop) {
    const projects = await api('/projects');
    renderCycle(projects);
    const byP = Object.fromEntries((D.cash?.projects || []).map(p => [p.project_id, p]));
    $('#ph').innerHTML = projects.map(p => { const c = byP[p.id]; return `<tr data-p="${p.id}"><td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.location)} · ${N(p.total_units)} ${p.kind === 'villa' ? 'فيلا' : p.kind === 'land' ? 'قطعة أرض' : 'وحدة'}</span></td>
    <td><span class="bar-s"><i style="width:${p.build_pct}%"></i></span>${N(p.build_pct)}٪</td><td>${N(p.sold_pct)}٪</td><td>${N(p.available)}</td>
    <td>${c ? N(c.sales_pace) + ' / ' + N(p.planned_monthly_sales) + ' شهريًا' : '—'}</td>
    <td>${c ? (c.gap ? pill('عجز ' + K(c.gap), 'p-b') : pill('سليم', 'p-ok')) : '—'}</td></tr>`; }).join('');
    $$('#ph tr').forEach(tr => tr.onclick = () => { S.proj = +tr.dataset.p; S.bld = null; go('inv'); });
  }
  $('#leaseBox').hidden = !D.lease_properties;
  if (D.lease_properties) {
    $('#pl').innerHTML = D.lease_properties.map(p => `<tr data-p="${p.id}"><td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.location || '')}</span></td><td>${N(p.leased)} / ${N(p.units)}</td><td><span class="bar-s"><i style="width:${p.occupancy}%"></i></span>${N(p.occupancy)}٪</td><td>${OMR(p.annual_rent)}</td><td>${p.arrears ? pill(OMR(p.arrears), 'p-b') : pill('لا متأخرات', 'p-ok')}</td></tr>`).join('');
    $$('#pl tr').forEach(tr => tr.onclick = () => { S.proj = +tr.dataset.p; S.bld = null; go('inv'); });
  }
}
function showDecision(d) {
  let act = '';
  if (!d.done && !can('decide')) act = `<span class="muted">اعتماد القرارات من صلاحية الإدارة والمالية.</span>`;
  else if (!d.done) {
    if (String(d.kind).startsWith('lease_')) act = `<button class="btn p" data-call="go" data-args="${J(['post'])}">فتح الإيجارات</button> <button class="btn" data-call="decide" data-args="${J([d.key, 'approve'])}">تكليف الفريق بالمتابعة</button> <button class="btn" data-call="decide" data-args="${J([d.key, 'dismiss'])}">تجاهل</button>`;
    else if (d.kind === 'ipc') act = `<button class="btn p" data-call="go" data-args="${J(['con'])}">فتح المستخلص للمراجعة</button>`;
    else if (d.kind === 'cash') act = `<button class="btn p" data-call="go" data-args="${J(['fin'])}">عرض الرادار وخطة المعالجة</button> <button class="btn" data-call="decide" data-args="${J([d.key, 'approve'])}">اعتماد الخطة</button>`;
    else act = `<button class="btn p" data-call="decide" data-args="${J([d.key, 'approve'])}">اعتماد وتنفيذ</button> <button class="btn" data-call="decide" data-args="${J([d.key, 'dismiss'])}">تجاهل</button>`;
  }
  insp('قرار مقترح', `<h3>${tx(d.title)}</h3><div class="ai"><b class="k">✦ لماذا؟</b> ${tx(d.why)}</div>
    <dl class="kv"><dt>المصدر</dt><dd>${esc(d.source)}</dd><dt>${esc(d.impact_label)}</dt><dd>${OMR(d.impact)}</dd><dt>الأولوية</dt><dd>${d.priority}</dd></dl>
    <div class="btns">${d.done ? pill(d.done === 'approve' ? '✓ اتُّخذ القرار' : 'تم التجاهل', 'p-ok') : act}</div>
    <p class="muted" style="margin-top:14px">كل قرار يُسجَّل في سجل التدقيق مع وقته ومنفّذه.</p>`);
}
async function decide(key, action) {
  try { const r = await api('/decisions/act', {method: 'POST', body: {key, action}}); toast(r.detail || 'تم'); await loadOverview(); loadSide(); const d = DEC.find(x => x.key === key); if (d) showDecision(d); }
  catch (e) { toast(e.message, 1); }
}

/* ---------------- المخزون ---------------- */
let UNITS = [];
async function loadInventory() {
  const p = S.projects.find(x => x.id === S.proj) || S.projects[0];
  $('#selProj').innerHTML = S.projects.map(x => `<option value="${x.id}" ${x.id === p.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('');
  UNITS = await api(`/units?project_id=${p.id}`);
  const blds = [...new Set(UNITS.map(u => u.building))];
  if (!S.bld || !blds.includes(S.bld)) S.bld = blds[0];
  $('#selBld').style.display = p.kind === 'tower' && blds.length > 1 ? '' : 'none';
  $('#selBld').innerHTML = blds.map(b => `<option ${b === S.bld ? 'selected' : ''}>${b}</option>`).join('');
  renderHeat(p);
  const segs = await api(`/pricing/${p.id}`);
  $('#segs').innerHTML = segs.map(s => `<tr><td>${esc(s.type)} · ${esc(s.view)}</td><td>${N(s.total)}</td><td>${N(s.available)}</td><td>${N(s.recent_sales)}</td><td><bdi>${s.demand_ratio.toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 1, minimumFractionDigits: 1})} ضعف</bdi></td>
    <td>${s.suggested_change > 0 ? pill('رفع ' + N(s.suggested_change * 100) + '٪', 'p-ok') : s.suggested_change < 0 ? pill('خفض/حافز ' + N(-s.suggested_change * 100) + '٪', 'p-b') : pill('إبقاء', '')}</td></tr>`).join('');
  crumb();
}
function renderHeat(p) {
  const fs = $('#fStat').value, ai = $('#fAi').checked;
  const list = UNITS.filter(u => u.building === S.bld);
  const dim = u => (fs && u.status !== fs) || (ai && !u.ai_change);
  const cell = u => `<button class="cell ${u.status} ${dim(u) ? 'dim' : ''} ${u.ai_change > 0 ? 'up' : u.ai_change < 0 ? 'dn' : ''}" data-c="${u.code}" aria-label="${u.code} ${ST[u.status]}">${u.code.split('-').pop()}</button>`;
  const h = $('#heat');
  if (p.kind === 'villa' || p.kind === 'land') {
    h.className = 'heat villas'; h.style.gridTemplateColumns = '';
    h.innerHTML = list.map(cell).join('');
    $('#invTitle').textContent = p.kind === 'land' ? 'المخطط العام لقطع الأرض' : 'المخطط العام للفلل';
  } else {
    const known = list.filter(u => u.floor !== null && u.floor !== undefined), unknown = list.filter(u => u.floor === null || u.floor === undefined);
    const cols = Math.max(1, ...known.map(u => u.pos), unknown.length ? Math.min(14, unknown.length) : 1);
    h.className = 'heat'; h.style.gridTemplateColumns = `44px repeat(${cols},1fr)`;
    const floors = [...new Set(known.map(u => u.floor))].sort((a, b) => b - a);
    h.innerHTML = floors.map(f => `<span class="fl">ط ${N(f)}</span>` + known.filter(u => u.floor === f).sort((a, b) => a.pos - b.pos).map(cell).join('')).join('');
    // 0.19.0 — units whose floor is not supplied (off-plan developers publish the unit mix, not the floor plan): one labelled band per type,
    // wrapped into rows, instead of inventing floors
    const types = [...new Set(unknown.map(u => u.type))];
    h.innerHTML += types.map(tp => {
      const us = unknown.filter(u => u.type === tp).sort((a, b) => a.pos - b.pos);
      let out = '';
      for (let i = 0; i < us.length; i += cols) {
        const row = us.slice(i, i + cols);
        out += `<span class="fl" title="${esc(tp)} — الطابق غير مزوَّد">${i ? '' : esc(tp.split(' ')[0])}</span>` + row.map(cell).join('') + '<span></span>'.repeat(cols - row.length);
      }
      return out;
    }).join('');
    $('#invTitle').textContent = `مخطط المبنى ${S.bld}`;
  }
  const c = st => list.filter(u => u.status === st).length;
  $('#invCount').textContent = `متاحة ${N(c('a'))} · محجوزة ${N(c('r'))} · مباعة ${N(c('s'))}`;
  $$('#heat .cell').forEach(b => b.onclick = () => { $$('#heat .cell').forEach(x => x.classList.remove('on')); b.classList.add('on'); showUnit(b.dataset.c); });
}
$('#selProj').onchange = e => { S.proj = +e.target.value; S.bld = null; loadInventory(); loadSide(); };
$('#selBld').onchange = e => { S.bld = e.target.value; renderHeat(S.projects.find(x => x.id === S.proj)); crumb(); };
$('#fStat').onchange = $('#fAi').onchange = () => renderHeat(S.projects.find(x => x.id === S.proj));

async function showUnit(code) {
  const u = await api('/units/' + encodeURIComponent(code));
  const stPill = u.lease ? pill('مؤجَّرة', 'p-bl') : u.retained ? pill('محفظة التأجير — شاغرة', 'p-w') : pill(ST[u.status], u.status === 'a' ? 'p-ok' : u.status === 'r' ? 'p-w' : 'p-bl');
  let h = `<h3><span class="num">${esc(u.code)}</span> ${stPill}</h3>
   <dl class="kv"><dt>النوع</dt><dd>${esc(u.type)}</dd><dt>المساحة</dt><dd>${u.area == null ? 'غير مزوَّدة' : N(u.area) + ' م²'}</dd>${u.floor ? `<dt>الطابق</dt><dd>${N(u.floor)}</dd>` : ''}<dt>الموقع/الإطلالة</dt><dd>${esc(u.view)}</dd><dt>السعر</dt><dd>${OMR(u.price)}</dd><dt>سعر المتر</dt><dd>${u.price != null && u.area ? OMR(u.price / u.area) : '—'}</dd></dl>`;
  if (u.retained) h += u.lease ? `<div class="ai"><b class="k">محفظة التأجير:</b> المستأجر <b>${esc(u.lease.tenant)}</b> · الإيجار السنوي <b>${OMR(u.lease.annual_rent)}</b> (${N(u.lease.frequency)} دفعات في السنة) · العقد من ${fmtDate(u.lease.start)} إلى ${fmtDate(u.lease.end)}${u.lease.arrears ? ` · متأخرات ${pill(OMR(u.lease.arrears), 'p-b')}` : ' · لا متأخرات'}${u.lease.next_due ? ` · الدفعة القادمة ${fmtDate(u.lease.next_due)}` : ''}<br><span class="muted">العقد والدفعات والتحصيل في «التسليم والأملاك ← التأجير».</span></div>`
    : `<div class="ai"><b class="k">محفظة التأجير:</b> وحدة شاغرة معروضة للإيجار — يُنشأ عقدها من «التسليم والأملاك ← التأجير».</div>`;
  if (u.suggestion) {
    const s = u.suggestion;
    h += `<div class="ai"><b class="k">✦ التسعير الديناميكي:</b> ${s.change ? `${s.change > 0 ? 'رفع' : 'خفض'} ${N(Math.abs(s.change * 100))}٪ ← <b>${OMR(s.price)}</b>` : 'السعر الحالي متوافق مع الطلب.'}<br><span class="muted">${tx(s.reason)}</span></div>`;
  }
  if (u.status === 'a' && can('book') && !u.retained) h += `<div class="btns"><button class="btn p" data-call="openBooking" data-args="${J([u.code])}">حجز الوحدة لعميل</button><button class="btn" data-call="EXT.newQuote" data-args="${J([u.code])}">عرض سعر</button></div>`;
  if (u.booking) {
    const b = u.booking;
    h += `<dl class="kv"><dt>العميل</dt><dd>${esc(b.cname)}</dd><dt>الهاتف</dt><dd><span class="num">${esc(b.phone)}</span></dd><dt>خطة الدفع</dt><dd>${PLANS[b.plan][0]}</dd><dt>المسدَّد</dt><dd>${OMR(b.paid)} من ${OMR(b.total)}</dd>${b.status === 'pending' ? `<dt>مهلة الحجز</dt><dd>حتى ${fmtDate(b.expires)}</dd>` : ''}</dl>`;
    if (b.status === 'pending') h += `<div class="btns" style="margin-bottom:12px">${can('confirm') ? `<button class="btn p" data-call="confirmBooking" data-args="${J([b.id, u.code])}">تسجيل سداد العربون وتأكيد البيع</button>` : '<span class="muted">تأكيد البيع من صلاحية المالية.</span>'}${can('book') ? `<button class="btn" data-call="cancelBooking" data-args="${J([b.id, u.code])}">إلغاء الحجز</button>` : ''}</div>`;
    h += `<b>جدول الأقساط</b>` + b.installments.map(i => {
      const st = i.paid_amount >= i.amount - 1 ? pill('مدفوع', 'p-ok') : i.paid_amount > 0 ? pill('جزئي', 'p-w') : new Date(i.due_date) < new Date() ? pill('متأخر', 'p-b') : pill('قادم', '');
      return `<div class="inst"><span>${esc(i.label)}<br><span class="muted">${fmtDate(i.due_date)}</span></span><span>${OMR(i.amount)} ${st}</span></div>`;
    }).join('');
  }
  const UP = await api(`/units/${encodeURIComponent(code)}/plans`).catch(() => null);
  if (UP && (UP.floor_plan || UP.unit_plan || UP.others.length)) {
    h += `<b>موقع الوحدة ومخططاتها</b>`;
    if (UP.floor_plan) h += `<div class="muted" style="margin:6px 0 4px">${esc(UP.floor_plan.title)}${UP.floor_plan.me ? '' : ' — لم يُحدَّد موقع الوحدة بعد'}</div>` + planImg(UP.floor_plan, UP.floor_plan.markers, u.code);
    if (UP.unit_plan) h += `<div class="muted" style="margin:10px 0 4px">${esc(UP.unit_plan.title)}</div>` + planImg(UP.unit_plan, [], null);
    if (UP.others.length) h += `<div class="btns" style="margin-top:8px">${UP.others.map(o => `<a class="btn" href="${o.url}" target="_blank" rel="noopener">${PLAN_KINDS[o.kind] || o.kind}: ${esc(o.title)}</a>`).join('')}</div>`;
  } else h += `<div class="muted" style="margin-top:8px">لا مخططات مرفوعة لهذا المشروع — <button class="link" data-call="EXT.plans">المخططات</button></div>`;
  if (u.booking && u.booking.id) h += `<div style="margin-top:10px"><b>مستندات الحجز</b> ${docBtns('contract', u.booking.id)}</div>`;
  insp('وحدة', h);
}

/* ---------------- الحجز ---------------- */
const modal = (html) => { $('#mbox').innerHTML = html; $('#modal').classList.add('on'); };
const closeModal = () => $('#modal').classList.remove('on');
$('#modal').onclick = e => { if (e.target.id === 'modal') closeModal(); };
let BK = {};
async function openBooking(code, lead) {
  const u = await api('/units/' + encodeURIComponent(code));
  BK = {code, price: u.price, plan: 'milestone', name: lead?.name || '', phone: lead?.phone || '', lead_id: lead?.id || null};
  renderBk();
}
function renderBk() {
  modal(`<h3>حجز الوحدة <span class="num">${esc(BK.code)}</span></h3><div class="muted">السعر ${OMR(BK.price)} · مهلة الحجز المبدئي 72 ساعة</div>
   <label for="bn">اسم العميل</label><input id="bn" value="${esc(BK.name)}" placeholder="الاسم الكامل">
   <label for="bp">رقم الهاتف</label><input id="bp" dir="ltr" style="text-align:right" value="${esc(BK.phone)}" placeholder="+968 9xxx xxxx">
   <label>خطة الدفع</label><div class="plans">${Object.entries(PLANS).map(([k, v]) => `<button type="button" class="plan ${BK.plan === k ? 'on' : ''}" data-k="${k}"><b>${v[0]}</b>${k === 'milestone' ? ' ' + pill('موصى بها', 'p-ok') : ''}<small>${v[1]}</small></button>`).join('')}</div>
   <div class="err" id="berr"></div>
   <div class="btns" style="margin-top:14px;justify-content:space-between"><button class="btn" data-call="closeModal">إلغاء</button><button class="btn p" id="bgo">إنشاء الحجز وجدول الأقساط</button></div>`);
  $$('.plan').forEach(b => b.onclick = () => { BK.name = $('#bn').value; BK.phone = $('#bp').value; BK.plan = b.dataset.k; renderBk(); });
  $('#bgo').onclick = submitBk; $('#bn').focus();
}
async function submitBk() {
  BK.name = $('#bn').value.trim(); BK.phone = $('#bp').value.trim();
  if (BK.name.length < 2) return $('#berr').textContent = 'أدخل اسم العميل';
  if (BK.phone.replace(/\D/g, '').length < 8) return $('#berr').textContent = 'أدخل رقم هاتف صحيحًا';
  $('#bgo').disabled = true;
  try {
    const r = await api('/bookings', {method: 'POST', body: {unit_code: BK.code, customer_name: BK.name, phone: BK.phone, plan: BK.plan, lead_id: BK.lead_id}});
    modal(`<h3>✓ تم الحجز المبدئي</h3><p>العربون المطلوب <b>${OMR(r.deposit)}</b> قبل ${fmtDate(r.expires)}، وإلا تُحرَّر الوحدة تلقائيًا.</p>
      <b>جدول الأقساط المُنشأ</b>${r.schedule.map(s => `<div class="inst"><span>${esc(s.label)} <span class="muted">${fmtDate(s.due)}</span></span><span>${OMR(s.amount)}</span></div>`).join('')}
      <p class="muted">في الإصدار التالي: يُرسل العقد للتوقيع الرقمي ورابط الدفع للعميل عبر واتساب تلقائيًا.</p>
      <button class="btn p w" data-call="closeModal">تم</button>`);
    toast('حُجزت ' + BK.code);
    refreshAll(); showUnit(BK.code);
  } catch (e) { $('#berr').textContent = e.message; $('#bgo').disabled = false; }
}
async function confirmBooking(id, code) { try { await api(`/bookings/${id}/confirm`, {method: 'POST'}); toast('تأكد البيع وسُجّل العربون'); refreshAll(); showUnit(code); } catch (e) { toast(e.message, 1); } }
async function cancelBooking(id, code) { if (!confirm('إلغاء الحجز وتحرير الوحدة؟')) return; try { await api(`/bookings/${id}/cancel`, {method: 'POST'}); toast('أُلغي الحجز'); refreshAll(); showUnit(code); } catch (e) { toast(e.message, 1); } }

/* ---------------- المبيعات ---------------- */
let LEADS = [];
async function loadCRM() {
  LEADS = await api('/leads');
  $('#pipe').innerHTML = STAGES.map((s, i) => `<div><small>${s}</small><b>${N(LEADS.filter(l => l.stage === i).length)}</b></div>`).join('');
  $('#leads').innerHTML = LEADS.map((l, i) => `<tr data-i="${i}"><td><b>${esc(l.name)}</b></td><td>${esc(l.interest)}</td><td>${esc(l.pname)}</td><td>${STAGES[l.stage]}</td><td>${esc(l.channel)}</td><td>${fmtDate(l.last_contact)}</td><td>${pill(N(l.score) + '٪', scoreC(l.score))}</td></tr>`).join('');
  $$('#leads tr').forEach(tr => tr.onclick = () => { sel(tr); showLead(LEADS[+tr.dataset.i]); });
}
async function showLead(l) {
  const m = await api(`/leads/${l.id}/matches`);
  const next = l.score >= 75 ? 'أرسل عرض خطة دفع مربوطة بالإنجاز مع مهلة 48 ساعة' : l.stage < 2 ? 'ادعه لمعاينة الوحدات المطابقة هذا الأسبوع' : 'تابِعه باتصال وأرسل مقارنة الوحدات المطابقة';
  insp('عميل محتمل', `<h3>${esc(l.name)} ${pill(N(l.score) + '٪', scoreC(l.score))}</h3>
   <dl class="kv"><dt>الهاتف</dt><dd><span class="num">${esc(l.phone)}</span></dd><dt>الاهتمام</dt><dd>${esc(l.interest)}</dd><dt>الميزانية</dt><dd>${OMR(l.budget)}</dd><dt>القناة</dt><dd>${esc(l.channel)}</dd><dt>التفاعلات</dt><dd>${N(l.interactions)}</dd></dl>
   <label class="muted">المرحلة</label><div class="seg" style="margin:6px 0 12px;flex-wrap:wrap">${STAGES.map((s, i) => `<button class="${i === l.stage ? 'on' : ''}" data-call="setStage" data-args="${J([l.id, i])}">${s}</button>`).join('')}</div>
   <div class="ai"><b class="k">✦ الخطوة التالية:</b> ${next}.</div>
   <b>✦ أنسب الوحدات المتاحة</b>${m.map(u => `<div class="inst"><span><span class="num">${esc(u.code)}</span><br><span class="muted">${esc(u.type)} · ${esc(u.view)}</span></span><span>${OMR(u.price)} <button class="btn" style="min-height:30px;padding:3px 10px" data-call="openBooking" data-args="${J([u.code, LEADS.find(x=>x.id===(+l.id))])}">حجز</button></span></div>`).join('') || '<p class="muted">لا وحدات متاحة مطابقة.</p>'}`);
}
async function setStage(id, st) { const l = await api(`/leads/${id}/stage`, {method: 'POST', body: {stage: st}}); toast(`نُقل إلى «${STAGES[st]}» · الدرجة الجديدة ${N(l.score)}٪`); await loadCRM(); const x = LEADS.find(y => y.id === id); if (x) showLead(x); }

/* ---------------- المالية ---------------- */
$$('[data-plan]').forEach(b => b.onclick = () => { S.plan = +b.dataset.plan; $$('[data-plan]').forEach(x => x.classList.toggle('on', x === b)); loadFinance(); });
async function loadFinance() {
  const [cash, risk] = await Promise.all([api('/cash?plan=' + (S.plan ? 'true' : 'false')), api('/risk')]);
  drawCash(cash);
  const wp = cash.projects.find(p => p.gap_before > 0);
  $('#cashNote').innerHTML = !wp ? '<b class="k">✦</b> لا توجد فجوة سيولة متوقعة في أي حساب ضمان خلال 12 شهرًا.'
    : S.plan ? `<b class="k">✦ بعد خطة المعالجة:</b> عجز «${esc(wp.name)}» ينخفض من ${OMR(wp.gap_before)} إلى <b>${OMR(wp.gap)}</b>.<ul>${cash.actions.map(a => `<li>${tx(a)}</li>`).join('')}</ul>${wp.gap > 0 ? 'العجز المتبقي يحتاج سحبًا إضافيًا من تسهيل التمويل أو ضخ حقوق ملكية.' : ''}`
    : (() => { const first = wp.series.find(x => x.balance < 0); const drv = wp.series.flatMap(x => x.drivers);
        return `<b class="k">✦ تنبيه مبكر:</b> حساب ضمان «${esc(wp.name)}» يدخل في العجز من <b>${fmtMonth(first.month)}</b>${drv.length ? ' مع ' + esc(drv[0]) : ''}، ويبلغ العجز ذروته <b>${OMR(wp.gap)}</b> في ${fmtMonth(wp.worst.month)}. سرعة البيع الحالية ${N(wp.sales_pace)} وحدة شهريًا. اضغط «بعد خطة المعالجة».`; })();
  $('#risk').innerHTML = risk.map((r, i) => `<tr data-i="${i}"><td><b>${esc(r.customer)}</b><br><span class="muted">${esc(r.project)}</span></td><td><span class="num">${esc(r.unit)}</span></td><td>${OMR(r.next_amount)}</td><td>${fmtDate(r.next_due)}</td><td>${r.overdue ? OMR(r.overdue) : '—'}</td><td>${pill(N(r.score) + '٪', r.score >= 70 ? 'p-b' : 'p-w')}</td><td>${tx(r.action)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">لا يوجد عملاء معرّضون للتعثر.</td></tr>';
  $$('#risk tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); const r = risk[+tr.dataset.i];
    insp('مخاطر تعثر', `<h3>${esc(r.customer)} ${pill(N(r.score) + '٪', 'p-b')}</h3><div class="ai"><b class="k">✦ الأسباب:</b><ul>${r.reasons.map(x => `<li>${tx(x)}</li>`).join('')}</ul><b class="k">المقترح:</b> ${tx(r.action)} قبل ${fmtDate(r.next_due)}.</div><button class="btn p" data-call="showUnit" data-args="${J([r.unit])}">فتح ملف الوحدة والأقساط</button>`); });
}
function drawCash(cash) {
  const cs = getComputedStyle(document.body), col = v => cs.getPropertyValue(v).trim();
  const W = 900, H = 320, L = 24, R = 96, T = 44, B = 40;   // محور القيم على اليمين (بداية القراءة في RTL)
  const ser = cash.projects.map(p => p.series.map(s => s.balance));
  const all = ser.flat(); let mx = Math.max(...all, 0), mn = Math.min(...all, 0);
  const K2 = v => v === 0 ? '0 ر.ع' : (v < 0 ? '−' : '') + K(Math.abs(v));
  const pad = (mx - mn) * .08 || 1; mx += pad; mn -= mn < 0 ? pad : 0;
  const span = mx - mn, n = cash.series.length;
  const X = i => W - R - i * ((W - L - R) / (n - 1)), Y = v => T + (mx - v) / span * (H - T - B);
  const colors = ['--blue', '--pri', '--ok', '--bad'];
  const raw = span / 5, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1, 2, 5, 10].map(k => k * mag).find(s => s >= raw);
  let g = '';
  const ticks = []; for (let v = Math.ceil(mn / step) * step; v <= mx; v += step) ticks.push(v);
  for (let i = 0; i < ticks.length; i++) if (Object.is(ticks[i], -0)) ticks[i] = 0;
  if (mn < 0 && !ticks.some(v => v < 0)) { const nm = Math.pow(10, Math.floor(Math.log10(-mn))); ticks.unshift(-Math.floor(-mn * .9 / nm) * nm || -nm / 2); }
  for (const v of ticks)
    g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${col('--line')}"/><text x="${W - R + 10}" y="${Y(v) + 4}" font-size="12" fill="${col('--muted')}" text-anchor="start">${K2(v)}</text>`;
  g += `<line x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}" stroke="${col('--bad')}" stroke-width="1.5" stroke-dasharray="5 4"/><text x="${L}" y="${Y(0) - 6}" font-size="11" fill="${col('--bad')}" text-anchor="start">خط الصفر</text>`;
  cash.series.forEach((s, i) => g += `<text x="${X(i)}" y="${H - 12}" font-size="12" fill="${col('--muted')}" text-anchor="middle">${fmtMonth(s.month)}</text>`);
  ser.forEach((arr, k) => {
    const c = col(colors[k % 4]);
    g += `<path d="${arr.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1)).join('')}" fill="none" stroke="${c}" stroke-width="2.5" stroke-linejoin="round"/>`;
    arr.forEach((v, i) => g += `<circle cx="${X(i)}" cy="${Y(v)}" r="${v < 0 ? 4.5 : 3}" fill="${c}" stroke="${v < 0 ? col('--bad') : 'none'}" stroke-width="2"><title>${esc(cash.projects[k].name)} · ${fmtMonth(cash.series[i].month)}: ${OMR(v)}</title></circle>`);
    const lx = W - R - k * 170;   // مفتاح الألوان: المربع يمين النص
    g += `<rect x="${lx - 14}" y="12" width="14" height="10" rx="2" fill="${c}"/><text x="${lx - 22}" y="21" font-size="13" fill="${col('--ink')}" text-anchor="end">${esc(cash.projects[k].name)}</text>`;
  });
  const sv = $('#chart'); sv.setAttribute('viewBox', `0 0 ${W} ${H}`); sv.setAttribute('preserveAspectRatio', 'xMidYMid meet'); sv.innerHTML = g;
}

/* ---------------- المستخلصات ---------------- */
let IPC = [];
async function loadIPC() {
  IPC = await api('/ipcs');
  $('#ipc').innerHTML = IPC.map((i, k) => { const v = i.verification, gap = v.items.length && i.claimed_pct - v.verified_pct >= 3;
    return `<tr data-k="${k}"><td>${N(i.no)}</td><td>${esc(i.pname)}</td><td>${esc(i.contractor)}</td><td>${esc(i.stage)}</td><td>${N(i.claimed_pct)}٪</td><td>${v.items.length ? pill(N(v.verified_pct) + '٪', gap ? 'p-b' : 'p-ok') : (i.approved_pct != null ? N(i.approved_pct) + '٪' : '—')}</td><td>${OMR(i.stage_value * i.claimed_pct / 100)}</td><td>${i.status === 'pending' ? pill('بانتظار الاعتماد', 'p-w') : pill('معتمد ' + N(i.approved_pct) + '٪', 'p-ok')}</td></tr>`; }).join('');
  $$('#ipc tr').forEach(tr => tr.onclick = () => { sel(tr); showIPC(IPC[+tr.dataset.k]); });
}
function showIPC(i) {
  const v = i.verification;
  let h = `<h3>المستخلص ${N(i.no)} — ${esc(i.pname)}</h3><dl class="kv"><dt>المقاول</dt><dd>${esc(i.contractor)}</dd><dt>المرحلة</dt><dd>${esc(i.stage)}</dd><dt>قيمة المرحلة</dt><dd>${OMR(i.stage_value)}</dd><dt>النسبة المعلنة</dt><dd>${N(i.claimed_pct)}٪</dd></dl>`;
  if (v.items.length) {
    h += `<div class="ai"><b class="k">✦ التحقق من الإنجاز (${N(v.evidence_photos)} دليل مصوّر):</b> النسبة المُتحققة <b>${N(v.verified_pct)}٪</b>. المطلوب صرفه ${OMR(v.claimed_amount)}، والمستحق فعليًا <b>${OMR(v.verified_amount)}</b> (فرق ${OMR(v.gap_amount)}).</div>
      <div class="items">${v.items.map(it => `<div class="it"><div class="row"><span>${esc(it.item)} <span class="muted">وزن ${N(it.weight * 100)}٪ · ${N(it.evidence)} صورة</span></span><b>${N(it.verified_pct)}٪</b></div><div class="prog"><i style="width:${it.verified_pct}%"></i></div></div>`).join('')}</div>
      <p class="muted">${esc(v.note)}</p>`;
  }
  if (i.status === 'pending') h += can('approve_ipc') ? `<button class="btn p w" data-call="approveIPC" data-args="${J([i.id])}">اعتماد المستخلص بالنسبة المُتحققة</button>` : '<p class="muted">الاعتماد من صلاحية المدير العام. يمكنك مراجعة الأدلة وإرفاق ملاحظاتك.</p>';
  else h += pill('✓ معتمد بنسبة ' + N(i.approved_pct) + '٪', 'p-ok');
  insp('مستخلص', h);
}
async function approveIPC(id) { try { const r = await api(`/ipcs/${id}/approve`, {method: 'POST'}); toast(r.detail + ' · ' + OMR(r.amount)); await loadIPC(); showIPC(IPC.find(x => x.id === id)); loadSide(); } catch (e) { toast(e.message, 1); } }

/* ---------------- خدمة العملاء ---------------- */
const SV = {new: ['جديد', 'p-bl'], in_progress: ['قيد التنفيذ', 'p-w'], done: ['مُنجز', 'p-ok']};
const RSS = {pending: ['بانتظار القرار', 'p-w'], listed: ['معروضة', 'p-ok'], rejected: ['مرفوض', 'p-b'], sold: ['تم التنازل', 'p-bl']};
let SVCD = {requests: [], resale: []};
async function loadService() {
  SVCD = await api('/service');
  $('#svcT').innerHTML = SVCD.requests.map((r, i) => `<tr data-i="${i}"><td>${N(r.id)}</td><td>${esc(r.customer)}</td><td><span class="num">${esc(r.unit)}</span></td><td>${esc(r.category)}</td><td>${esc(r.description)}</td><td>${fmtDate(r.created)}</td><td>${pill(SV[r.status][0], SV[r.status][1])}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">لا توجد طلبات.</td></tr>';
  $$('#svcT tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); showSvc(SVCD.requests[+tr.dataset.i]); });
  $('#rsT').innerHTML = SVCD.resale.map((r, i) => `<tr data-i="${i}"><td>${esc(r.customer)}</td><td><span class="num">${esc(r.unit)}</span></td><td>${OMR(r.list_price)}</td><td>${OMR(r.ask_price)}</td><td>${OMR(r.fee)}</td><td>${pill(RSS[r.status][0], RSS[r.status][1])}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">لا توجد طلبات.</td></tr>';
  $$('#rsT tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); showResale(SVCD.resale[+tr.dataset.i]); });
}
function showSvc(r) {
  insp('طلب صيانة', `<h3>#${N(r.id)} · ${esc(r.category)} ${pill(SV[r.status][0], SV[r.status][1])}</h3>
   <dl class="kv"><dt>العميل</dt><dd>${esc(r.customer)}</dd><dt>الوحدة</dt><dd><span class="num">${esc(r.unit)}</span> · ${esc(r.project)}</dd><dt>الوصف</dt><dd>${esc(r.description)}</dd><dt>آخر تحديث</dt><dd>${fmtDate(r.updated)}</dd></dl>
   ${r.status !== 'done' ? `<label for="sn">ملاحظة تظهر للعميل</label><input id="sn" value="${esc(r.note || '')}" placeholder="مثال: الفني يزورك الأحد صباحًا">
   <div class="btns" style="margin-top:10px">${r.status === 'new' ? `<button class="btn" data-call="svcSet" data-args="${J([r.id, 'in_progress'])}">بدء التنفيذ</button>` : ''}<button class="btn p" data-call="svcSet" data-args="${J([r.id, 'done'])}">تم الإنجاز</button></div>` : `<p class="muted">${esc(r.note || '')}</p>`}`);
}
async function svcSet(id, st) { try { await api(`/service/${id}/status`, {method: 'POST', body: {status: st, note: $('#sn')?.value || ''}}); toast('حُدّث الطلب، ويراه العميل في تطبيقه'); await loadService(); showSvc(SVCD.requests.find(x => x.id === id)); } catch (e) { toast(e.message, 1); } }
function showResale(r) {
  const diff = 100 * (r.ask_price - r.list_price) / r.list_price;
  insp('إعادة بيع', `<h3><span class="num">${esc(r.unit)}</span> ${pill(RSS[r.status][0], RSS[r.status][1])}</h3>
   <dl class="kv"><dt>البائع</dt><dd>${esc(r.customer)}</dd><dt>السعر المطلوب</dt><dd>${OMR(r.ask_price)}</dd><dt>سعر قائمتك الحالي</dt><dd>${OMR(r.list_price)}</dd><dt>رسوم النقل للمطوّر</dt><dd>${OMR(r.fee)}</dd></dl>
   <div class="ai"><b class="k">✦ ملاحظة:</b> السعر المطلوب ${diff >= 0 ? 'أعلى' : 'أقل'} من سعر قائمتك بنسبة ${N(Math.abs(diff))}٪. ${diff < -3 ? 'قد ينافس مخزونك المتاح؛ فكّر في الموافقة مع حد أدنى للسعر.' : 'لا يضغط على أسعار مخزونك المتاح.'}</div>
   ${r.status === 'pending' && can('decide') ? `<div class="btns"><button class="btn p" data-call="resaleAct" data-args="${J([r.id, 'listed'])}">موافقة ونشر</button><button class="btn" data-call="resaleAct" data-args="${J([r.id, 'rejected'])}">رفض</button></div>` : ''}`);
}
async function resaleAct(id, a) { try { await api(`/resale/${id}`, {method: 'POST', body: {action: a}}); toast(a === 'listed' ? 'نُشرت الوحدة في السوق الثانوي' : 'رُفض الطلب'); await loadService(); showResale(SVCD.resale.find(x => x.id === id)); } catch (e) { toast(e.message, 1); } }

/* ---------------- السجل ---------------- */
async function loadAudit() {
  const a = await api('/audit?limit=100');
  $('#audit').innerHTML = a.map(x => `<tr><td>${new Date(x.at).toLocaleString('ar-OM-u-nu-latn', {dateStyle: 'medium', timeStyle: 'short'})}</td><td>${esc(x.actor)}</td><td>${esc(x.action)}</td><td>${esc(x.detail)}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">لا توجد إجراءات بعد.</td></tr>';
}

/* ---------------- المساعد ---------------- */
// لوحة مستقلة عن لوحة التفاصيل: تُفتح بالزر وتُغلق بـ✕ أو Esc، و«⟲» تبدأ محادثة جديدة (تمسح السجل والسياق).
const AI = {hist: [], intent: null, busy: false};
const AI_SUGG = [['ما ملخص المحفظة؟', 'view'], ['كم وحدة متاحة؟', 'inventory'], ['من الأعلى احتمالًا للشراء؟', 'leads'], ['ما المتأخرات وفجوة السيولة؟', 'finance'], ['ما حال الإنشاء والمستخلصات؟', 'construction'], ['كيف أحجز وحدة؟', 'inventory']];
function aiFmt(t) {
  return String(t || '').split('\n').map(l => l.trim() ? `<div class="ln${/^(•|\d+\. )/.test(l) ? ' li' : ''}">${esc(l).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\b([A-Z]{2,5}-[A-Z0-9-]+)\b/g, '<bdi dir="ltr">$1</bdi>')}</div>` : '<div class="sp"></div>').join('');
}
function aiSugg(list) {
  const L = (list && list.length ? list : AI_SUGG.filter(([, p]) => can(p)).map(x => x[0])).slice(0, 4);
  $('#aiSugg').innerHTML = L.map(q => `<button type="button" class="chip" data-call="aiAsk" data-args="${J([q])}">${esc(q)}</button>`).join('');
}
function aiWelcome() {
  AI.hist = []; AI.intent = null; $('#aiMode').textContent = '';
  $('#clog').innerHTML = '<div class="a"><div class="ln">أجيب من بيانات مؤسستك الحية: المخزون والمبيعات والعملاء المحتملون والتحصيل والإنشاء والتسليم والتأجير. ويمكنك أن تسألني أيضًا كيف تنفّذ مهمة في المنصة.</div></div>';
  aiSugg();
}
function aiOpen(on = true) {
  const a = $('#ai'); a.hidden = !on; document.body.classList.toggle('ai-on', on); $('#askBtn').setAttribute('aria-expanded', String(on));
  if (on) { if (!$('#clog').children.length) aiWelcome(); $('#ci').focus(); } else $('#askBtn').focus();
}
async function aiAsk(q) {
  q = (q || '').trim(); if (!q || AI.busy) return; AI.busy = true; $('#ci').value = '';
  const log = $('#clog'); log.insertAdjacentHTML('beforeend', `<div class="q">${esc(q)}</div><div class="a pend"><span class="ln">…</span></div>`);
  const pend = log.lastElementChild; log.scrollTop = log.scrollHeight; $('#aiSugg').innerHTML = '';
  try {
    const r = await api('/assistant', {method: 'POST', body: {q, history: AI.hist.slice(-4), intent: AI.intent}});
    pend.classList.remove('pend'); pend.innerHTML = `${aiFmt(r.answer)}<small>المصدر: ${esc(r.source)}</small>`;
    AI.hist.push({q, a: String(r.answer).slice(0, 1200)}); if (r.intent) AI.intent = r.intent;
    $('#aiMode').textContent = r.mode === 'llm' ? '· بنموذج لغوي' : ''; aiSugg(r.suggestions);
  } catch (err) { pend.classList.remove('pend'); pend.textContent = err.message; aiSugg(); }
  AI.busy = false; log.scrollTop = log.scrollHeight;
}
CALLS.aiAsk = aiAsk;
$('#cf').onsubmit = e => { e.preventDefault(); aiAsk($('#ci').value); };
$('#aiX').onclick = () => aiOpen(false);
$('#aiNew').onclick = () => { aiWelcome(); $('#ci').focus(); };

/* ---------------- مظهر المنصة (خلفية المؤسسة) ---------------- */
// القيم تأتي من /api/appearance (قائمة بيضاء في الخادم)؛ الألوان نفسها في shell.css عبر html[data-bg]. تُخزَّن نسخة في المتصفح لتفادي وميض اللون الافتراضي.
let UI = null;
function applyUI(u) {
  if (!u) return; const h = document.documentElement; UI = u;
  h.dataset.bg = u.preset || 'navy'; h.dataset.pat = u.pattern || 'none'; h.dataset.fit = u.fit || 'cover';
  h.style.setProperty('--ps', (u.size || 24) + 'px'); h.style.setProperty('--pstr', String(u.strength ?? 40));
  h.style.setProperty('--bgimg', u.image_doc ? `url("/api/appearance/image?v=${u.image_doc}${can('admin') ? '&doc=' + u.image_doc : ''}")` : 'none');
  const forced = u.mode === 'dark' || u.mode === 'light';
  let lightPref = false; try { lightPref = localStorage.getItem('mbq-theme') === 'l'; } catch (e) { /* التخزين محجوب */ }
  document.body.classList.toggle('light', forced ? u.mode === 'light' : lightPref);
  $('#theme')?.classList.toggle('hidden', forced);
}
async function loadUI() {
  const u = await api('/appearance'); EXT.uiOpt = u.options; applyUI(u);
  try { localStorage.setItem('mbq-ui', JSON.stringify(u)); } catch (e) { /* التخزين محجوب */ }
  return u;
}
try { applyUI(JSON.parse(localStorage.getItem('mbq-ui') || 'null')); } catch (e) { /* أول زيارة */ }

/* ---------------- لوحة الأوامر ---------------- */
const CMDS0 = [['صندوق القرارات', () => go('ov')], ['مخطط الوحدات', () => go('inv')], ['العملاء المحتملون', () => go('crm')], ['رادار السيولة', () => go('fin')], ['عملاء معرّضون للتعثر', () => go('fin')], ['المستخلصات', () => go('con')], ['سجل التدقيق', () => go('log')], ['الأراضي ودراسات الجدوى', () => go('pre')], ['التحقق من الهوية والعقود', () => go('sal')], ['الوسطاء والعمولات', () => { EXT.cur.sal = 'brk'; go('sal'); }], ['الفواتير وضريبة القيمة المضافة', () => go('bill')], ['حساب الضمان', () => { EXT.cur.bill = 'esc'; go('bill'); }], ['التسليم والعيوب', () => go('post')], ['اتحاد الملاك', () => { EXT.cur.post = 'oa'; go('post'); }], ['التأجير', () => { EXT.cur.post = 'lease'; go('post'); }], ['تقرير الممول', () => go('rep')], ['تفعيل التحقق الثنائي', () => { EXT.cur.adm = 'sec'; go('adm'); }], ['تبديل الوضع الفاتح/الداكن', () => $('#theme').click()]];
let PAL = [], palIdx = 0;
const CMD_PERM = {'الأراضي ودراسات الجدوى': 'permits', 'التحقق من الهوية والعقود': 'kyc', 'الوسطاء والعمولات': 'brokers', 'الفواتير وضريبة القيمة المضافة': 'invoices', 'حساب الضمان': 'finance', 'التسليم والعيوب': 'handover', 'اتحاد الملاك': 'oa', 'التأجير': 'leasing', 'تقرير الممول': 'reports', 'صندوق القرارات': 'view', 'مخطط الوحدات': 'inventory', 'العملاء المحتملون': 'leads', 'رادار السيولة': 'finance', 'عملاء معرّضون للتعثر': 'finance', 'المستخلصات': 'construction', 'سجل التدقيق': 'audit'};
const CMDS = { filter: f => CMDS0.filter(c => !CMD_PERM[c[0]] || can(CMD_PERM[c[0]])).filter(f) };
async function renderPal(q) {
  PAL = CMDS.filter(c => c[0].includes(q)).map(c => ({label: c[0], sub: 'أمر', run: c[1]}));
  if (q.length >= 2) {
    const r = await api('/search?q=' + encodeURIComponent(q)).catch(() => []);
    PAL = PAL.concat(r.map(x => ({label: x.label, sub: {unit: 'وحدة', lead: 'عميل محتمل', customer: 'مشترٍ'}[x.type] + ' · ' + x.sub,
      run: x.type === 'lead' ? async () => { go('crm'); await loadCRM(); showLead(LEADS.find(l => l.id === x.ref)); } : () => showUnit(x.ref)})));
  }
  palIdx = 0; drawPal();
}
function drawPal() { $('#pl').innerHTML = PAL.map((c, i) => `<div class="it ${i === palIdx ? 'on' : ''}" data-i="${i}"><span>${esc(c.label)}</span><span class="muted">${esc(c.sub)}</span></div>`).join('') || '<div class="it muted">لا نتائج</div>'; $$('#pl .it[data-i]').forEach(e => e.onclick = () => runPal(+e.dataset.i)); }
function runPal(i) { const c = PAL[i]; pal(0); c?.run(); }
function pal(o) { $('#pal').classList.toggle('on', !!o); if (o) { $('#pi').value = ''; renderPal(''); $('#pi').focus(); } }
$('#cmdBtn').onclick = () => pal(1);
$('#pi').oninput = e => renderPal(e.target.value.trim());
$('#pi').onkeydown = e => { if (e.key === 'ArrowDown') { palIdx = Math.min(PAL.length - 1, palIdx + 1); drawPal(); } if (e.key === 'ArrowUp') { palIdx = Math.max(0, palIdx - 1); drawPal(); } if (e.key === 'Enter') runPal(palIdx); };
$('#pal').onclick = e => { if (e.target.id === 'pal') pal(0); };
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#ai').hidden && $('#ai').contains(document.activeElement)) { aiOpen(false); return; } if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); pal(1); } if (e.key === 'Escape') { pal(0); closeModal(); document.body.classList.remove('io', 'nav-open'); } });

/* ---------------- تشغيل ---------------- */
async function refreshAll() { if (can('view')) await loadSide(); else $('#pfSec').classList.add('hidden'); go(S.screen); }
function groupsVis() { $$('.side .grp').forEach(g => { if (g.id === 'pfSec') return; g.classList.toggle('hidden', !g.querySelector('.ni:not(.hidden)')); }); }
(async () => {
  if (localStorage.getItem('mbq-theme') === 'l') document.body.classList.add('light');
  S.screen = localStorage.getItem('mbq-screen') || 'ov';
  try {
    S.me = await api('/me');
    loadUI().catch(() => {});
    $('#whoName').textContent = S.me.name; $('#whoRole').textContent = S.me.role_label;
    $$('[data-s]').forEach(b => b.classList.toggle('hidden', !canS(b.dataset.s)));
    $('#resetBtn').classList.toggle('hidden', !can('admin')); groupsVis();
    if (S.me.role === 'broker') { location.href = '/broker'; return; }
    if (S.me.role === 'investor') { S.screen = 'rep'; }
    if (S.me.role === 'property_manager') { S.screen = 'pmg'; }
    if (S.me.role === 'employee') { S.screen = 'me'; }
    if (S.me.role === 'lessee') { S.screen = 'lp'; }
    if (S.me.role === 'payroll' && !S.me.employee_id) { S.screen = 'pay'; }
    if (S.me.must_change) { EXT.changePw(true); return; }
    if (S.me.needs_2fa) { await EXT.setup2fa(); $('#mbox').insertAdjacentHTML('afterbegin', '<div class="ai"><b class="k">مطلوب:</b> التحقق الثنائي إلزامي لدورك قبل الوصول إلى البيانات.</div>'); return; }
    await refreshAll(); } catch (e) { toast('تعذّر الاتصال بالخادم: ' + e.message, 1); }
})();

/* تسمية خلايا الجداول لعرضها كبطاقات على الشاشات الضيقة */
function labelTables(root) { (root || document).querySelectorAll('.tw table').forEach(t => { const h = [...t.querySelectorAll('thead th')].map(x => x.textContent.trim()); t.querySelectorAll('tbody tr').forEach(r => [...r.children].forEach((c, i) => { if (!c.hasAttribute('data-l')) c.setAttribute('data-l', h[i] || ''); })); }); }
new MutationObserver(() => { clearTimeout(window.__lt); window.__lt = setTimeout(() => labelTables(), 30); }).observe(document.getElementById('body'), {childList: true, subtree: true});

CALLS.gotoPay = () => document.querySelector('[data-t=pay]')?.click();


/* ======================= app2 (merged in Unit 3 — one ES module, no shared globals) ======================= */
/* مبانيك — شاشات الوحدات الموسّعة (تعتمد على أدوات app.js: api, $, $$, esc, N, OMR, K, pill, insp, toast, modal, closeModal, can, fmtDate) */
const T = (heads, rows, empty = 'لا توجد بيانات.') => `<div class="tw"><table><thead><tr>${heads.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${heads.length}" class="muted">${empty}</td></tr>`}</tbody></table></div>`;
const BOX = (title, inner, extra = '') => `<div class="box"><div class="hd"><span>${title}</span>${extra}</div>${inner}</div>`;
const KP = items => `<div class="kp">${items.map(([l, v, s]) => `<div><small>${l}</small><b>${v}</b><small>${s || ''}</small></div>`).join('')}</div>`;
const SUBP = {'pre.land': ['land'], 'pre.permit': ['permits'], 'sal.kyc': ['kyc'], 'sal.brk': ['brokers'], 'sal.mkt': ['market', 'decide'], 'sal.disc': ['decide', 'book'], 'sal.wa': ['leads'],
  'bill.inv': ['invoices'], 'bill.pen': ['finance'], 'bill.bank': ['finance'], 'bill.esc': ['finance', 'reports'], 'bill.erp': ['invoices'],
  'post.hand': ['handover', 'service'], 'post.title': ['handover', 'finance'], 'post.fm': ['service', 'handover'], 'post.oa': ['oa'], 'post.lease': ['leasing']};
const SUBM = {'post.hand': ['handover'], 'post.title': ['handover'], 'post.fm': ['handover', 'leasing'], 'post.oa': ['handover']};  // 0.20.0: a sub-tab also needs one of its modules
const subOk = (id, k) => (!SUBP[id + '.' + k] || SUBP[id + '.' + k].some(p => can(p))) && (!SUBM[id + '.' + k] || SUBM[id + '.' + k].some(modOn));
const SUB0 = (id, tabs, cur) => `<div class="seg subt" style="margin-bottom:14px">${tabs.map(([k, l]) => `<button class="${k === cur ? 'on' : ''}" data-call="EXT.sub" data-args="${J([id, k])}">${l}</button>`).join('')}</div>`;
const SUB = (id, tabs, cur) => { const t = tabs.filter(([k]) => subOk(id, k)); return t.length > 1 ? SUB0(id, t, cur) : ''; };
const pct = v => N(v) + '٪';
const AR = s => esc(s);
const ND = (v, d = 2) => new Intl.NumberFormat('ar-OM-u-nu-latn', {maximumFractionDigits: d}).format(+v || 0);
const tryDo = async (fn, ok) => { try { const r = await fn(); if (ok) toast(typeof ok === 'function' ? ok(r) : ok); return r; } catch (e) { toast(e.message, 1); throw e; } };
const projOpts = (cur) => S.projects.map(p => `<option value="${p.id}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('');

const EXT = {
  cur: {hr: 'ov', pay: 'runs', me: 'me', lp: 'ls', pm: 'ls', lea: 'ov', pre: 'land', post: 'hand', sal: 'kyc', bill: 'inv', adm: 'users', rep: 'ready', mk: 'board'},
  data: {},
  sub(id, k) { this.cur[id] = k; this.load(id); },
  load(id) { return this['l_' + id](); },
};

/* ================================================================ ما قبل التطوير */
EXT.l_pre = async function () {
  const tabs = [['land', 'الأراضي ودراسات الجدوى', 'land'], ['permit', 'التراخيص والجهات الحكومية', 'permits']].filter(t => can(t[2]));
  if (!tabs.some(t => t[0] === this.cur.pre)) this.cur.pre = tabs[0][0];
  const k = this.cur.pre, el = $('#pre');
  el.innerHTML = (tabs.length > 1 ? SUB('pre', tabs, k) : '') + '<div id="preB">…</div>';
  if (k === 'land') {
    const L = this.data.lands = await api('/lands');
    $('#preB').innerHTML = BOX('الأراضي تحت الدراسة', T(['الأرض', 'الموقع', 'المساحة م²', 'الاستخدام', 'معامل البناء', 'السعر', 'الحالة', 'آخر دراسة'],
      L.map((l, i) => { const s = l.studies[0]?.results; return `<tr data-i="${i}"><td>${esc(l.name)}</td><td>${esc(l.location)}</td><td>${N(l.area)}</td><td>${esc(l.zoning)}</td><td>${N(l.far)}</td><td>${OMR(l.price)}</td><td>${pill(esc(l.status), 'p-bl')}</td><td>${s ? pill('هامش ' + pct(s.margin), s.margin >= 20 ? 'p-ok' : s.margin >= 12 ? 'p-w' : 'p-b') : '<span class="muted">—</span>'}</td></tr>`; })));
    $$('#preB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); EXT.showLand(L[+tr.dataset.i]); });
  } else {
    const P = await api('/permits');
    $('#preB').innerHTML = BOX('التراخيص <span class="muted">البلدية · الإسكان والتخطيط العمراني · الدفاع المدني · البيئة · المرافق</span>',
      T(['المشروع', 'الجهة', 'نوع الترخيص', 'المرجع', 'الحالة', 'الصدور', 'الانتهاء', 'تنبيه'],
        P.map((p, i) => `<tr data-i="${i}"><td>${esc(p.project)}</td><td>${esc(p.authority)}</td><td>${esc(p.kind)}</td><td><span class="num">${esc(p.ref || '—')}</span></td><td>${pill(p.status_label, p.status === 'issued' ? 'p-ok' : p.status === 'not_started' ? 'p-bl' : 'p-w')}</td><td>${fmtDate(p.issued)}</td><td>${fmtDate(p.expires)}</td><td>${p.alert ? pill(esc(p.alert), 'p-b') : ''}</td></tr>`)));
    $$('#preB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); EXT.showPermit(P[+tr.dataset.i]); });
  }
};
EXT.showLand = function (l) {
  const s = l.studies[0]?.results;
  insp('أرض ودراسة جدوى', `<h3>${esc(l.name)}</h3><dl class="kv"><dt>الموقع</dt><dd>${esc(l.location)}</dd><dt>المساحة</dt><dd>${N(l.area)} م²</dd><dt>الاستخدام</dt><dd>${esc(l.zoning)} · ${N(l.max_floors)} طوابق</dd><dt>السعر المطلوب</dt><dd>${OMR(l.price)}</dd></dl>
   <div class="ai"><b class="k">✦ دراسة جدوى سريعة</b> — عدّل الافتراضات واحسب: الإيرادات، التكاليف، ذروة التمويل، IRR، القيمة الحالية، وتحليل الحساسية.</div>
   <label>سعر البيع ر.ع/م²</label><input id="fs" value="620" inputmode="numeric"><label>تكلفة البناء ر.ع/م²</label><input id="fc" value="260" inputmode="numeric">
   <label>نسبة البيع على الخريطة</label><input id="fp" value="0.6"><label>مدة المشروع (شهر)</label><input id="fm" value="30" inputmode="numeric">
   <div class="btns" style="margin-top:10px"><button class="btn p" id="fgo" ${can('land') ? '' : 'disabled'}>احسب الجدوى</button></div><div id="fres">${s ? EXT.feasHtml(s) : ''}</div>`);
  $('#fgo').onclick = async () => {
    const r = await tryDo(() => api(`/lands/${l.id}/feasibility`, {method: 'POST', body: {sell_price_sqm: +$('#fs').value, build_cost_sqm: +$('#fc').value, presale_pct: +$('#fp').value, months: +$('#fm').value}}), 'حُسبت الدراسة وحُفظت');
    $('#fres').innerHTML = EXT.feasHtml(r);
  };
};
EXT.feasHtml = s => `<h3 style="margin-top:14px">${esc(s.verdict)}</h3><dl class="kv"><dt>المبيعات المتوقعة</dt><dd>${OMR(s.revenue)}</dd><dt>إجمالي التكلفة</dt><dd>${OMR(s.total_cost)}</dd><dt>الربح</dt><dd>${OMR(s.profit)} · هامش ${pct(s.margin)}</dd><dt>العائد الداخلي IRR</dt><dd>${s.irr == null ? '—' : pct(s.irr)}</dd><dt>ذروة التمويل</dt><dd>${OMR(s.peak_funding)}</dd><dt>سعر التعادل</dt><dd>${N(s.breakeven_sqm)} ر.ع/م²</dd></dl>
  <div class="muted">حساسية الهامش (السعر × التكلفة)</div>${T(['السعر \\ التكلفة', '−10٪', 'كما هي', '+10٪'], s.sensitivity.map(r => `<tr><td>${r.price_change > 0 ? '+' : ''}${N(r.price_change * 100)}٪</td>${r.margins.map(m => `<td>${pill(pct(m), m >= 20 ? 'p-ok' : m >= 12 ? 'p-w' : 'p-b')}</td>`).join('')}</tr>`))}
  <div class="ai">${s.reasons.map(AR).join('<br>')}</div>`;
EXT.showPermit = function (p) {
  insp('ترخيص', `<h3>${esc(p.kind)}</h3><dl class="kv"><dt>المشروع</dt><dd>${esc(p.project)}</dd><dt>الجهة</dt><dd>${esc(p.authority)}</dd><dt>الحالة</dt><dd>${esc(p.status_label)}</dd><dt>المرجع</dt><dd>${esc(p.ref || '—')}</dd></dl>
   ${p.alert ? `<div class="ai"><b class="k">تنبيه:</b> ${esc(p.alert)}</div>` : ''}
   ${can('permits') ? `<label>تحديث الحالة</label><select id="ps"><option value="submitted">مقدَّم</option><option value="in_review">قيد المراجعة</option><option value="issued">صادر</option><option value="rejected">مرفوض</option></select><label>رقم المرجع</label><input id="pr" value="${esc(p.ref || '')}"><label>تاريخ الانتهاء</label><input id="pe" type="date" value="${esc(p.expires || '')}">
   <div class="btns" style="margin-top:10px"><button class="btn p" id="pgo">حفظ</button></div>` : ''}`);
  if ($('#pgo')) $('#pgo').onclick = async () => { await tryDo(() => api(`/permits/${p.id}`, {method: 'POST', body: {status: $('#ps').value, ref: $('#pr').value, expires: $('#pe').value || null}}), 'حُدّث الترخيص'); EXT.l_pre(); };
};

/* ================================================================ الإنشاء (تفاصيل المشروع) */
EXT.l_conx = async function () {
  const box = $('#conx'); if (!box) return;
  const pid = EXT.conP || S.projects[0].id;
  const d = await api(`/construction/${pid}`);
  const s = d.schedule;
  const min = Math.min(...s.tasks.map(t => +new Date(t.planned_start))), max = Math.max(...s.tasks.map(t => +new Date(t.planned_end)));
  const now = Date.now(), X = v => 100 * (v - min) / (max - min);
  const gantt = `<div class="gantt">${s.tasks.map(t => { const a = X(+new Date(t.planned_start)), b = X(+new Date(t.planned_end)); return `<div class="gr"><span class="gn">${esc(t.name)}</span><div class="gt"><i style="inset-inline-start:${a}%;width:${b - a}%"></i><i class="gp ${t.late_days > 7 ? 'late' : ''}" style="inset-inline-start:${a}%;width:${(b - a) * t.pct / 100}%"></i></div><span class="gs">${pill(t.status, t.status === 'متأخر' ? 'p-b' : t.status === 'مكتمل' ? 'p-ok' : t.status === 'جارٍ' ? 'p-w' : 'p-bl')}</span></div>`; }).join('')}<div class="gnow" style="inset-inline-start:calc(180px + (100% - 290px) * ${X(now) / 100})"></div></div>`;
  box.innerHTML = `<div class="toolbar"><select id="conP">${projOpts(pid)}</select><span class="muted">${esc(d.contract?.contractor || '')}</span></div>
   ${KP([['مؤشر أداء الجدول SPI', ND(s.spi), s.spi < .95 ? 'متأخر' : 'ضمن الخطة'], ['التأخير المتوقع', N(s.forecast_delay_days) + ' يومًا', 'تمديد معتمد ' + N(d.extension_days)], ['الالتزام الحالي', K(d.committed), 'المتوقع عند الإكمال ' + K(d.eac)], ['محتجز ضمان حسن التنفيذ', K(d.retention_held), d.delay_penalty ? 'غرامة تأخير محتملة ' + K(d.delay_penalty) : 'لا غرامة']])}
   ${BOX('الجدول الزمني (جانت) والمسار الحرج', gantt)}
   ${BOX('أوامر التغيير', T(['رقم', 'العنوان', 'السبب', 'التكلفة', 'المدة', 'الحالة', ''], d.change_orders.map(c => `<tr><td>${N(c.no)}</td><td>${esc(c.title)}</td><td>${esc(c.reason)}</td><td>${OMR(c.cost)}</td><td>${N(c.days)} يوم</td><td>${pill({approved: 'معتمد', pending: 'معلق', rejected: 'مرفوض'}[c.status], c.status === 'approved' ? 'p-ok' : c.status === 'pending' ? 'p-w' : 'p-b')}</td><td>${c.status === 'pending' && can('approve_ipc') ? `<button class="btn" data-call="EXT.co" data-args="${J([c.id, 'approve'])}">اعتماد</button> <button class="btn" data-call="EXT.co" data-args="${J([c.id, 'reject'])}">رفض</button>` : ''}</td></tr>`)),
      can('construction') ? '<button class="btn" data-call="EXT.newCO">+ أمر تغيير</button>' : '')}
   ${BOX('الميزانية', T(['البند', 'المبلغ'], d.budget.map(b => `<tr><td>${esc(b.category)}</td><td>${OMR(b.amount)}</td></tr>`)))}
   ${BOX('عدم المطابقة (NCR)', T(['العنوان', 'الموقع', 'الخطورة', 'الحالة', ''], d.ncrs.map(n => `<tr><td>${esc(n.title)}</td><td>${esc(n.location)}</td><td>${pill({minor: 'بسيطة', major: 'جسيمة', critical: 'حرجة'}[n.severity], n.severity === 'minor' ? 'p-w' : 'p-b')}</td><td>${n.status === 'open' ? pill('مفتوح', 'p-b') : pill('مغلق', 'p-ok')}</td><td>${n.status === 'open' && can('construction') ? `<button class="btn" data-call="EXT.ncrClose" data-args="${J([n.id])}">إغلاق</button>` : ''}</td></tr>`)))}
   ${BOX('تقارير الموقع اليومية', T(['اليوم', 'العمالة', 'الطقس', 'الأعمال', 'المعوقات', 'الصور'], d.site_reports.map(r => `<tr><td>${fmtDate(r.day)}</td><td>${N(r.workers)}</td><td>${esc(r.weather)}</td><td>${esc(r.work_done)}</td><td>${esc(r.issues || '—')}</td><td>${N(r.photos)}</td></tr>`)),
      can('construction') ? '<button class="btn" data-call="EXT.newSite">+ تقرير اليوم</button>' : '')}
   <div class="ai">${d.reasons.filter(Boolean).map(AR).join('<br>')}</div>`;
  $('#conP').onchange = e => { EXT.conP = +e.target.value; EXT.l_conx(); };
};
EXT.co = async (id, a) => { await tryDo(() => api(`/change-orders/${id}/decide`, {method: 'POST', body: {action: a}}), 'سُجّل القرار'); EXT.l_conx(); };
EXT.ncrClose = async id => { await tryDo(() => api(`/ncrs/${id}/close`, {method: 'POST'}), 'أُغلق التقرير'); EXT.l_conx(); };
EXT.newCO = () => { modal(`<h3>أمر تغيير جديد</h3><label>العنوان</label><input id="ct"><label>السبب</label><input id="cr" value="طلب المالك"><label>التكلفة (ر.ع)</label><input id="cc" inputmode="numeric"><label>أثره على المدة (يوم)</label><input id="cd" value="0" inputmode="numeric"><div class="err" id="ce"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="cgo">رفع للاعتماد</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#cgo').onclick = async () => { try { await api('/change-orders', {method: 'POST', body: {project_id: EXT.conP || S.projects[0].id, title: $('#ct').value, reason: $('#cr').value, cost: +$('#cc').value, days: +$('#cd').value}}); closeModal(); toast('رُفع أمر التغيير'); EXT.l_conx(); } catch (e) { $('#ce').textContent = e.message; } }; };
EXT.newSite = () => { modal(`<h3>تقرير الموقع اليومي</h3><label>عدد العمالة</label><input id="sw" inputmode="numeric"><label>الطقس</label><input id="sh" value="مشمس"><label>الأعمال المنجزة</label><input id="sd"><label>المعوقات</label><input id="si"><label>عدد الصور</label><input id="sp" value="0" inputmode="numeric"><div class="err" id="se2"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="sgo2">حفظ</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#sgo2').onclick = async () => { try { await api('/site-reports', {method: 'POST', body: {project_id: EXT.conP || S.projects[0].id, workers: +$('#sw').value, weather: $('#sh').value, work_done: $('#sd').value, issues: $('#si').value, photos: +$('#sp').value}}); closeModal(); toast('حُفظ التقرير'); EXT.l_conx(); } catch (e) { $('#se2').textContent = e.message; } }; };

/* ================================================================ المبيعات الموسّعة */
EXT.l_sal = async function () {
  const k = this.cur.sal, el = $('#sal');
  el.innerHTML = SUB('sal', [['kyc', 'التحقق والعقود'], ['quotes', 'عروض الأسعار'], ['brk', 'الوسطاء والعمولات'], ['mkt', 'السوق الثانوي'], ['disc', 'الخصومات'], ['wa', 'وكيل واتساب']], k) + '<div id="salB">…</div>';
  const B = $('#salB');
  if (k === 'quotes') return EXT.l_quotes(B);
  if (k === 'kyc') {
    const Q = await api('/kyc');
    B.innerHTML = BOX('الحجوزات بانتظار التحقق من الهوية (KYC) وإصدار العقد', T(['العميل', 'الوحدة', 'الهوية', 'الجنسية', 'حالة التحقق', 'المخاطر', 'الحجز'],
      Q.map((q, i) => `<tr data-i="${i}"><td>${esc(q.name)}</td><td><span class="num">${esc(q.unit)}</span></td><td>${esc(q.id_type || '—')} ${q.id_number_masked ? '<span class="num">' + esc(q.id_number_masked) + '</span>' : ''}</td><td>${esc(q.nationality || '—')}</td><td>${pill({verified: 'موثَّق', pending: 'بانتظار', review: 'عناية معززة', rejected: 'مرفوض'}[q.kyc_status] || '—', q.kyc_status === 'verified' ? 'p-ok' : q.kyc_status === 'pending' ? 'p-bl' : 'p-b')}</td><td>${esc(q.kyc_risk || '—')}</td><td>${pill(q.booking_status === 'pending' ? 'مبدئي' : 'مؤكد', 'p-w')}</td></tr>`), 'لا توجد حالات معلقة.'));
    $$('#salB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); EXT.showKyc(Q[+tr.dataset.i]); });
  } else if (k === 'brk') {
    const Bs = await api('/brokers');
    B.innerHTML = BOX('الوسطاء المعتمدون', T(['الوسيط', 'الترخيص', 'النسبة', 'العملاء المسجلون', 'الصفقات', 'مستحقة', 'مدفوعة'],
      Bs.map((b, i) => `<tr data-i="${i}"><td>${esc(b.name)}</td><td><span class="num">${esc(b.license_no)}</span></td><td>${ND(b.rate * 100, 1)}٪</td><td>${N(b.leads)}</td><td>${N(b.n)}</td><td>${OMR(b.due)}</td><td>${OMR(b.paid)}</td></tr>`)),
      can('admin') ? '<button class="btn" data-call="EXT.newBroker">+ وسيط</button>' : '');
    $$('#salB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); const b = Bs[+tr.dataset.i];
      insp('وسيط', `<h3>${esc(b.name)}</h3><dl class="kv"><dt>الترخيص</dt><dd>${esc(b.license_no)}</dd><dt>الهاتف</dt><dd><span class="num">${esc(b.phone)}</span></dd></dl><div class="ai">تُصرف العمولة بعد تحصيل 20٪ من ثمن الوحدة، وتُسترد تلقائيًا إذا فُسخ العقد. تسجيل العميل محمي برقم الهاتف لمنع تنازع العمولات.</div>
      ${T(['الوحدة', 'العمولة', 'الحالة', ''], b.commissions.map(c => `<tr><td><span class="num">${esc(c.unit)}</span></td><td>${OMR(c.amount)}</td><td>${pill({due: 'مستحقة', paid: 'مدفوعة', void: 'ملغاة', clawback: 'استرداد'}[c.status], c.status === 'paid' ? 'p-ok' : 'p-w')}</td><td>${c.status === 'due' && can('finance') ? `<button class="btn" data-call="EXT.payCom" data-args="${J([c.id])}">صرف</button>` : ''}</td></tr>`))}`); });
  } else if (k === 'mkt') {
    const M = await api('/market');
    B.innerHTML = BOX('السوق الثانوي <span class="muted">وحدات يعيد ملاكها بيعها بموافقة المطوّر</span>', T(['الوحدة', 'المشروع', 'البائع', 'السعر المطلوب', 'سعر القائمة', 'العروض', 'الحالة'],
      M.map((m, i) => `<tr data-i="${i}"><td><span class="num">${esc(m.unit)}</span></td><td>${esc(m.project)}</td><td>${esc(m.seller)}</td><td>${OMR(m.ask_price)}</td><td>${OMR(m.list_price)}</td><td>${N(m.offers.length)}</td><td>${pill(m.status === 'sold' ? 'تم التنازل' : 'معروضة', m.status === 'sold' ? 'p-ok' : 'p-bl')}</td></tr>`), 'لا توجد وحدات معروضة. توافق على طلبات إعادة البيع من شاشة خدمة العملاء.'));
    const SS = await api('/resale-settlements').catch(() => []);
    if (SS.length) B.insertAdjacentHTML('beforeend', BOX('تسويات التنازل <span class="muted">ما يدفعه المشتري للبائع = سعر التنازل − الأقساط المتبقية التي يتحملها</span>', T(['الوحدة', 'البائع', 'المشتري', 'هوية المشتري', 'سعر التنازل', 'أقساط يتحملها المشتري', 'مستحق للبائع', 'الحالة', ''],
      SS.map(s => `<tr><td><span class="num">${esc(s.unit)}</span></td><td>${esc(s.seller)}</td><td>${esc(s.buyer)}</td><td>${pill(s.buyer_kyc === 'verified' ? 'موثَّقة' : 'بانتظار التحقق', s.buyer_kyc === 'verified' ? 'p-ok' : 'p-w')}</td><td>${OMR(s.price)}</td><td>${OMR(s.unpaid_installments)}</td><td>${OMR(s.equity_due_to_seller)}</td><td>${pill(s.status === 'settled' ? 'مسوّاة' : 'مفتوحة', s.status === 'settled' ? 'p-ok' : 'p-w')}</td><td>${s.status === 'open' && can('finance') ? `<button class="btn" data-call="EXT.settle" data-args="${J([s.id])}">تسجيل التسوية</button>` : ''}</td></tr>`))));
    $$('#salB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); EXT.showListing(M[+tr.dataset.i]); });
  } else if (k === 'disc') {
    const D = await api('/discounts');
    B.innerHTML = BOX('طلبات الخصم <span class="muted">المبيعات حتى 2٪ · المالية حتى 5٪ · ما زاد يعتمده المدير</span>', T(['الوحدة', 'النسبة', 'السبب', 'طلبه', 'الحالة', ''],
      D.map(d => `<tr><td><span class="num">${esc(d.unit)}</span></td><td>${ND(d.pct * 100, 1)}٪</td><td>${esc(d.reason)}</td><td>${esc(d.requested_by)}</td><td>${pill({approved: 'معتمد', pending: 'معلق', rejected: 'مرفوض'}[d.status], d.status === 'approved' ? 'p-ok' : d.status === 'pending' ? 'p-w' : 'p-b')}</td><td>${d.status === 'pending' && can('admin') ? `<button class="btn" data-call="EXT.disc" data-args="${J([d.id, 'approve'])}">اعتماد</button> <button class="btn" data-call="EXT.disc" data-args="${J([d.id, 'reject'])}">رفض</button>` : ''}</td></tr>`)));
  } else {
    const C = await api('/wa/conversations');
    B.innerHTML = BOX('محاكي وكيل واتساب <span class="muted">يرد بالعربية ويطابق المخزون ويحجز المعاينات · محرك قواعد</span>', `<div style="padding:14px"><div class="toolbar"><input id="wp" value="+968 9123 4567" style="max-width:180px" class="inp"><input id="wt" class="inp" style="flex:1" placeholder="اكتب رسالة العميل… مثال: ابغى شقة غرفتين بميزانية 80 الف"><button class="btn p" id="wgo">إرسال</button></div><div id="wlog" class="walog"></div></div>`)
      + BOX('آخر المحادثات', T(['الوقت', 'الرقم', 'الاتجاه', 'النص'], C.map(m => `<tr><td>${fmtDate(m.at)}</td><td><span class="num">${esc(m.phone)}</span></td><td>${m.direction === 'in' ? 'وارد' : 'رد آلي'}</td><td style="white-space:pre-line">${esc(m.body)}</td></tr>`)));
    $('#wgo').onclick = async () => { const t = $('#wt').value.trim(); if (!t) return; $('#wlog').insertAdjacentHTML('beforeend', `<div class="wi">${esc(t)}</div>`); $('#wt').value = '';
      const r = await tryDo(() => api('/wa/simulate', {method: 'POST', body: {phone: $('#wp').value, text: t}}));
      $('#wlog').insertAdjacentHTML('beforeend', `<div class="wo">${esc(r.reply)}<small>النية: ${esc(r.intent.intent)}${r.intent.bedrooms ? ' · غرف ' + r.intent.bedrooms : ''}${r.intent.budget ? ' · ميزانية ' + N(r.intent.budget) : ''}</small></div>`); };
    $('#wt').onkeydown = e => { if (e.key === 'Enter') $('#wgo').click(); };
  }
};
EXT.showKyc = async function (q) {
  if (can('kyc')) { try { const d = await api(`/customers/${q.id}/kyc`); q = {...q, ...d}; } catch (e) { toast(e.message, 1); } }  // الرقم الكامل بطلب مسجَّل في سجل التدقيق
  insp('التحقق من الهوية والعقد', `<h3>${esc(q.name)}</h3><dl class="kv"><dt>الوحدة</dt><dd>${esc(q.unit)}</dd><dt>الهاتف</dt><dd><span class="num">${esc(q.phone)}</span></dd><dt>ملاحظات الفحص</dt><dd>${esc(q.kyc_note || '—')}</dd></dl>
   ${can('kyc') ? `<label>نوع الهوية</label><select id="kt"><option>بطاقة مدنية</option><option>جواز سفر</option><option>بطاقة مقيم</option></select><label>رقم الهوية</label><input id="kn" value="${esc(q.id_number || '')}"><label>الجنسية</label><input id="ka" value="${esc(q.nationality || 'عُماني')}"><label>تاريخ انتهاء الهوية</label><input id="ke" type="date" value="${esc(q.id_expiry || '')}"><label>مصدر الأموال</label><select id="kf"><option>راتب</option><option>تجارة</option><option>تمويل بنكي</option><option>إرث</option><option>استثمار</option></select><label class="chk" style="margin-top:10px"><input type="checkbox" id="kp"> شخص معرّض سياسيًا (PEP)</label><label class="chk" style="margin-top:6px"><input type="checkbox" id="kc" ${q.consent_at ? 'checked disabled' : ''}> وقّع العميل إقرار الخصوصية ورقيًا بحضوري${q.consent_at ? ' (مسجَّلة)' : ' — وإلا يوافق من تطبيقه'}</label>
   <div class="btns" style="margin-top:10px"><button class="btn p" id="kgo">فحص واعتماد الهوية</button></div><div id="kres"></div>` : ''}
   <hr style="border:0;border-top:1px solid var(--line);margin:16px 0"><div class="btns">${q.kyc_status === 'review' && can('admin') ? `<button class="btn" data-call="EXT.kycDecide" data-args="${J([q.id, 'verified'])}">اعتماد رغم المخاطر</button><button class="btn" data-call="EXT.kycDecide" data-args="${J([q.id, 'rejected'])}">رفض</button>` : ''}
   ${can('book') ? `<button class="btn p" data-call="EXT.contract" data-args="${J([q.booking_id])}">العقد والتوقيع</button>` : ''}</div>`);
  if ($('#kgo')) $('#kgo').onclick = async () => {
    const r = await tryDo(() => api(`/customers/${q.id}/kyc`, {method: 'POST', body: {id_type: $('#kt').value, id_number: $('#kn').value, nationality: $('#ka').value, id_expiry: $('#ke').value, source_of_funds: $('#kf').value, pep: $('#kp').checked, consent_signed: $('#kc').checked}}));
    $('#kres').innerHTML = `<div class="ai"><b class="k">النتيجة: ${{verified: 'موثَّق ✓', review: 'يحتاج عناية معززة', rejected: 'مرفوض'}[r.status]}</b> · المخاطر ${esc(r.risk)}<br>${r.reasons.map(esc).join('<br>')}</div>`;
    EXT.l_sal();
  };
};
EXT.kycDecide = async (id, a) => { const note = prompt('سبب القرار (يُسجل في سجل التدقيق):'); if (!note) return; await tryDo(() => api(`/customers/${id}/kyc/decide`, {method: 'POST', body: {action: a, note}}), 'سُجّل القرار'); EXT.l_sal(); };
EXT.contract = async bid => {
  let k = await api(`/bookings/${bid}/contract`).catch(() => null);
  if (!k) k = await tryDo(() => api(`/bookings/${bid}/contract`, {method: 'POST'}), 'صدر العقد').catch(() => null);
  if (!k) return;
  modal(`<h3>عقد البيع ${esc(k.number)}</h3><div class="muted">بصمة النص SHA-256: <span class="num">${esc((k.sha256 || '').slice(0, 24))}…</span></div>
   <pre class="contract">${esc(k.body)}</pre>
   ${k.customer_signed_at ? `<div class="ai">✓ وقّعه المشتري في ${fmtDate(k.customer_signed_at)} · سلامة النص: ${k.integrity_ok ? 'مطابقة' : '⚠ غير مطابقة'}</div>` :
   `<div class="ai">يستطيع العميل التوقيع عن بعد من تطبيقه، أو التوقيع الحضوري هنا بحضورك.</div><label>اسم المشتري كما في العقد</label><input id="sn"><label class="chk" style="margin-top:8px"><input type="checkbox" id="sa"> قرأ المشتري العقد ووافق عليه</label><div class="err" id="se3"></div>
   <div class="btns" style="margin-top:12px"><button class="btn p" id="sgo3">توقيع حضوري</button></div>`}<div class="btns" style="margin-top:8px">${docBtns('contract', bid)}<button class="btn" data-call="closeModal">إغلاق</button></div>`);
  if ($('#sgo3')) $('#sgo3').onclick = async () => { try { await api(`/bookings/${bid}/contract/sign-inperson`, {method: 'POST', body: {typed_name: $('#sn').value, accept: $('#sa').checked}}); closeModal(); toast('✓ وُقّع العقد وسُجّل في سجل التدقيق'); } catch (e) { $('#se3').textContent = e.message; } };
};
EXT.payCom = async id => { await tryDo(() => api(`/commissions/${id}/pay`, {method: 'POST'}), 'صُرفت العمولة'); EXT.l_sal(); };
EXT.disc = async (id, a) => { await tryDo(() => api(`/discounts/${id}/decide`, {method: 'POST', body: {action: a}}), 'سُجّل القرار'); EXT.l_sal(); };
EXT.newBroker = () => { modal(`<h3>تسجيل وسيط</h3><label>الاسم التجاري</label><input id="bn"><label>رقم ترخيص الوساطة</label><input id="bl"><label>الهاتف</label><input id="bp"><label>نسبة العمولة (مثال 0.02)</label><input id="br" value="0.02"><div class="err" id="be"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="bgo">حفظ</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#bgo').onclick = async () => { try { await api('/brokers', {method: 'POST', body: {name: $('#bn').value, license_no: $('#bl').value, phone: $('#bp').value, rate: +$('#br').value}}); closeModal(); toast('سُجّل الوسيط'); EXT.l_sal(); } catch (e) { $('#be').textContent = e.message; } }; };
EXT.showListing = function (m) {
  insp('إعلان سوق ثانوي', `<h3><span class="num">${esc(m.unit)}</span> · ${esc(m.type)}</h3><dl class="kv"><dt>البائع</dt><dd>${esc(m.seller)}</dd><dt>السعر المطلوب</dt><dd>${OMR(m.ask_price)}</dd><dt>رسوم التنازل</dt><dd>${OMR(m.fee)}</dd></dl>
   ${T(['المشتري', 'العرض', 'الحالة', ''], m.offers.map(o => `<tr><td>${esc(o.buyer_name)}</td><td>${OMR(o.price)}</td><td>${esc({open: 'مفتوح', accepted: 'مقبول', closed: 'مغلق'}[o.status])}</td><td>${o.status === 'open' && can('decide') ? `<button class="btn p" data-call="EXT.accept" data-args="${J([o.id])}">قبول وإتمام التنازل</button>` : ''}</td></tr>`), 'لا عروض بعد.')}
   ${m.status === 'listed' && can('market') ? `<label>اسم المشتري</label><input id="on"><label>هاتفه</label><input id="op"><label>السعر المعروض</label><input id="ov" inputmode="numeric" value="${Math.round(m.ask_price)}"><div class="btns" style="margin-top:10px"><button class="btn" id="ogo">تسجيل عرض</button></div>` : ''}`);
  if ($('#ogo')) $('#ogo').onclick = async () => { await tryDo(() => api(`/market/${m.id}/offers`, {method: 'POST', body: {buyer_name: $('#on').value, buyer_phone: $('#op').value, price: +$('#ov').value}}), 'سُجّل العرض'); EXT.l_sal(); };
};
EXT.settle = async id => { const ref = prompt('مرجع تحويل المبلغ من المشتري إلى البائع:'); if (!ref) return; await tryDo(() => api(`/resale-settlements/${id}/settle`, {method: 'POST', body: {reference: ref}}), 'سُجّلت التسوية'); EXT.l_sal(); };
EXT.accept = async id => { if (!confirm('إتمام التنازل؟ ينتقل العقد والأقساط المتبقية للمشتري الجديد، وتُفتح تسوية بين البائع والمشتري، ولا تسليم قبل توثيق هوية المشتري.')) return; const r = await tryDo(() => api(`/market/offers/${id}/accept`, {method: 'POST'})); toast(r.note); EXT.l_sal(); };

/* ================================================================ الفوترة والتحصيل */
EXT.l_bill = async function () {
  const k = this.cur.bill, el = $('#bill');
  el.innerHTML = SUB('bill', [['inv', 'الفواتير والضريبة'], ['pen', 'تبرعات التأخير (شرط التبرع) والفسخ'], ['bank', 'المطابقة البنكية'], ['esc', 'حساب الضمان'], ['erp', 'التصدير المحاسبي']], k) + '<div id="billB">…</div>';
  const B = $('#billB');
  if (k === 'inv') {
    const I = await api('/invoices');
    B.innerHTML = KP([['عدد الفواتير', N(I.summary.n)], ['الصافي', K(I.summary.net) + ' ر.ع'], ['ضريبة القيمة المضافة', K(I.summary.vat) + ' ر.ع'], ['النسبة القياسية', '5٪', 'قابلة للضبط']]) + `<div class="ai">${esc(I.note)}</div>`
      + BOX('الفواتير الصادرة', T(['الرقم', 'النوع', 'العميل', 'الصافي', 'الضريبة', 'الإجمالي', 'التاريخ', 'البيان', ''], I.invoices.map(v => `<tr><td><span class="num">${esc(v.number)}</span></td><td>${esc({installment: 'قسط', service_charge: 'رسوم خدمات', rent: 'إيجار', resale_fee: 'رسوم تنازل'}[v.kind] || v.kind)}</td><td>${esc(v.customer)}</td><td>${OMR(v.net)}</td><td>${OMR(v.vat)}</td><td>${OMR(v.total)}</td><td>${fmtDate(v.issued)}</td><td>${esc(v.note)}</td><td>${v.id ? docBtns('invoice', v.id) : ''}</td></tr>`), 'تصدر الفواتير تلقائيًا مع كل سداد.'));
    const R = await api('/receipts');
    B.innerHTML += BOX('الإيصالات الصادرة <span class="muted">إيصال استلام لكل دفعة — طباعة أو إرسال للعميل</span>', T(['الإيصال', 'العميل', 'الوحدة', 'عن', 'المبلغ', 'التاريخ', 'الطريقة', ''], R.map(r => `<tr><td><span class="num">${esc(r.receipt)}</span></td><td>${esc(r.customer)}</td><td><span class="num">${esc(r.code)}</span></td><td>${esc(r.label)}</td><td>${OMR(r.amount)}</td><td>${fmtDate(r.at)}</td><td>${esc(r.method || '')}</td><td>${docBtns('receipt', r.id)}</td></tr>`), 'لا دفعات مسجلة.'));
  } else if (k === 'pen') {
    const [P, C] = await Promise.all([api('/penalties'), api('/charity')]);
    const CS = {due: ['مستحق على العميل', 'p-w'], collected: ['محصَّل (أمانة)', 'p-bl'], disbursed: ['صُرف للجهة الخيرية', 'p-ok'], waived: ['معفى', '']};
    B.innerHTML = KP([['تبرعات تأخير متوقعة', OMR(P.total), 'على الأقساط المتأخرة حاليًا'], ['النسبة الشهرية', pct(P.rate * 100), 'بعد ' + N(P.grace_days) + ' يومًا سماح'], ['في حساب الأمانة', OMR(P.charity.collected), 'بانتظار الصرف'], ['صُرف لجهات خيرية', OMR(P.charity.disbursed)]])
      + `<div class="ai"><b class="k">${esc(P.treatment_label)}</b><br>${esc(P.note)}</div>`
      + BOX('الأقساط المتأخرة وتبرع التأخير المتوقع', T(['العميل', 'الوحدة', 'القسط', 'غير المسدد', 'أيام التأخير', 'التبرع المتوقع', ''], P.items.map(p => `<tr><td>${esc(p.customer)}</td><td><span class="num">${esc(p.unit)}</span></td><td>${esc(p.label)}</td><td>${OMR(p.unpaid)}</td><td>${N(p.late_days)}</td><td>${p.waived ? pill('معفاة', 'p-bl') : OMR(p.penalty)}</td><td>${!p.waived && p.penalty && can('decide') ? `<button class="btn" data-call="EXT.waive" data-args="${J([p.installment_id])}">إعفاء</button>` : ''}</td></tr>`)))
      + BOX('دفتر تبرعات التأخير <span class="muted">أمانة لجهة خيرية — لا يدخل الإيرادات</span>', T(['العميل', 'الوحدة', 'القسط', 'المبلغ', 'الحالة', 'الجهة', ''], C.items.map(d => `<tr><td>${esc(d.customer)}</td><td><span class="num">${esc(d.unit)}</span></td><td>${esc(d.label)}</td><td>${OMR(d.amount)}</td><td>${pill(CS[d.status][0], CS[d.status][1])}</td><td>${esc(d.beneficiary || '—')}</td><td>${can('finance') ? d.status === 'due' ? `<button class="btn" data-call="EXT.chCollect" data-args="${J([d.id])}">تحصيل</button>` : d.status === 'collected' ? `<button class="btn" data-call="EXT.chDisburse" data-args="${J([d.id])}">صرف للجهة</button>` : '' : ''}</td></tr>`), 'لا تبرعات تأخير مسجلة — تُقيَّد تلقائيًا عند سداد قسط متأخر.'));
  } else if (k === 'bank') {
    const Bk = await api('/bank');
    B.innerHTML = BOX('استيراد كشف حساب بنكي <span class="muted">سطر لكل حركة: التاريخ، المبلغ، المرجع</span>', `<div style="padding:14px"><textarea id="bt" class="inp" rows="5" style="width:100%" placeholder="2026-10-08, 9600, MBQ-H-000123"></textarea><div class="btns" style="margin-top:8px"><button class="btn p" id="bgo2">مطابقة</button><button class="btn" id="bdemo">مثال من الدفعات غير المطابقة</button></div><div id="bres"></div></div>`)
      + BOX('دفعات بانتظار المطابقة', T(['الإيصال', 'المبلغ', 'التاريخ', 'الطريقة'], Bk.unreconciled_payments.map(p => `<tr><td><span class="num">${esc(p.receipt)}</span></td><td>${OMR(p.amount)}</td><td>${fmtDate(p.at)}</td><td>${esc(p.method)}</td></tr>`), 'كل الدفعات مطابقة.'))
      + BOX('آخر الحركات المستوردة', T(['التاريخ', 'المبلغ', 'المرجع', 'المطابقة'], Bk.lines.map(l => `<tr><td>${fmtDate(l.day)}</td><td>${OMR(l.amount)}</td><td><span class="num">${esc(l.reference)}</span></td><td>${l.matched_payment ? pill('مطابقة', 'p-ok') : pill('غير مطابقة', 'p-b')}</td></tr>`)));
    $('#bdemo').onclick = () => { $('#bt').value = Bk.unreconciled_payments.slice(0, 3).map(p => `${p.at.slice(0, 10)}, ${p.amount}, ${p.receipt}`).concat(['2026-10-01, 1234, UNKNOWN']).join('\n'); };
    $('#bgo2').onclick = async () => {
      const lines = $('#bt').value.split('\n').map(x => x.split(',').map(s => s.trim())).filter(x => x.length >= 2 && x[0]).map(([day, amount, reference]) => ({day, amount: +amount, reference: reference || ''}));
      const r = await tryDo(() => api('/bank/import', {method: 'POST', body: {lines}}));
      toast(`مطابقة ${N(r.matched)} من ${N(r.imported)} · غير مطابقة ${N(r.unmatched)}`); EXT.l_bill();
    };
  } else if (k === 'esc') {
    const pid = EXT.escP || S.projects[0].id, e = await api(`/escrow/${pid}`);
    B.innerHTML = `<div class="toolbar"><select id="escP">${projOpts(pid)}</select></div>` + KP([['حساب الضمان', e.account], ['مقبوضات المشترين', K(e.buyer_receipts_to_date) + ' ر.ع'], ['مصروف للمقاول', K(e.contractor_releases) + ' ر.ع'], ['ضمان حسن التنفيذ المحتجز', K(e.retention_held) + ' ر.ع']])
      + `<div class="ai">${esc(e.rule)}</div>` + BOX('المستخلصات المعتمدة المصروفة من الضمان', T(['رقم', 'المرحلة', 'النسبة المعتمدة', 'قيمة المرحلة'], e.certified_ipcs.map(i => `<tr><td>${N(i.no)}</td><td>${esc(i.stage)}</td><td>${pct(i.approved_pct)}</td><td>${OMR(i.stage_value)}</td></tr>`)));
    $('#escP').onchange = ev => { EXT.escP = +ev.target.value; EXT.l_bill(); };
  } else {
    const j = await api('/export/erpnext');
    B.innerHTML = BOX('تصدير قيود اليومية إلى ERPNext <span class="muted">Journal Entry · حساب الضمان مدين / دفعات العملاء المقدمة دائن</span>', `<div style="padding:14px"><p>${N(j.count)} قيدًا جاهزًا للاستيراد.</p><div class="btns"><a class="btn p" href="/api/export/erpnext?fmt=csv">تنزيل CSV</a></div><pre class="contract" style="max-height:260px">${esc(JSON.stringify(j.entries.slice(0, 2), null, 1))}</pre></div>`);
  }
};
EXT.chCollect = async id => { const ref = prompt('مرجع التحصيل (رقم الحوالة/الإيصال):'); if (!ref) return; await tryDo(() => api(`/charity/${id}/collect`, {method: 'POST', body: {reference: ref}}), 'حُصّل إلى حساب الأمانة'); EXT.l_bill(); };
EXT.chDisburse = async id => { const ben = prompt('الجهة الخيرية المستفيدة (المعتمدة من هيئة الرقابة الشرعية):'); if (!ben) return; const ref = prompt('مرجع التحويل:'); if (!ref) return; await tryDo(() => api(`/charity/${id}/disburse`, {method: 'POST', body: {reference: ref, beneficiary: ben}}), 'صُرف للجهة الخيرية'); EXT.l_bill(); };
EXT.waive = async id => { if (!confirm('إعفاء العميل من تبرع التأخير على هذا القسط؟')) return; await tryDo(() => api(`/installments/${id}/waive`, {method: 'POST'}), 'سُجّل الإعفاء'); EXT.l_bill(); };

/* ================================================================ ما بعد البيع */
EXT.l_post = async function () {
  const tabs = [['hand', 'التسليم والعيوب'], ['title', 'نقل الملكية'], ['fm', 'إدارة المرافق'], ['oa', 'اتحاد الملاك']], el = $('#post');
  if (!subOk('post', this.cur.post)) this.cur.post = (tabs.find(([x]) => subOk('post', x)) || tabs[0])[0];  // 0.20.0: land on the first tab the organisation has
  const k = this.cur.post;
  el.innerHTML = SUB('post', tabs, k) + '<div id="postB">…</div>';
  const B = $('#postB');
  if (k === 'hand') {
    const H = await api('/handover');
    B.innerHTML = BOX('مواعيد التسليم <span class="muted">شروط التسليم: سداد كامل + إغلاق الملاحظات + عقد موقَّع</span>', T(['العميل', 'الوحدة', 'الموعد', 'المسدد', 'ملاحظات مفتوحة', 'الحالة'],
      H.map((h, i) => { const o = h.snags.filter(s => s.status === 'open').length; return `<tr data-i="${i}"><td>${esc(h.customer)}</td><td><span class="num">${esc(h.unit)}</span></td><td>${fmtDate(h.appointment)}</td><td>${pct(h.paid_ratio)}</td><td>${o ? pill(N(o), 'p-b') : pill('0', 'p-ok')}</td><td>${h.status === 'done' ? pill('سُلّمت', 'p-ok') : (() => { const r = []; if (h.paid_ratio < 100) r.push('متبقٍ ' + pct(100 - h.paid_ratio)); if (o) r.push(N(o) + ' ملاحظات'); return r.length ? pill('موقوف · ' + r.join(' · '), 'p-b') : pill('جاهز للتسليم', 'p-ok'); })()}</td></tr>`; })));
    $$('#postB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); EXT.showHand(H[+tr.dataset.i]); });
  } else if (k === 'title') {
    const Ti = await api('/titles');
    B.innerHTML = BOX('نقل الملكية وإصدار السندات', T(['العميل', 'الوحدة', 'الحالة', 'رسوم التسجيل', 'رقم السند', ''], Ti.map(t => `<tr><td>${esc(t.customer)}</td><td><span class="num">${esc(t.unit)}</span></td><td>${pill({ready: 'جاهز للتقديم', submitted: 'مقدَّم للوزارة', issued: 'صدر السند'}[t.status], t.status === 'issued' ? 'p-ok' : 'p-w')}</td><td>${t.fee ? OMR(t.fee) : '—'}</td><td>${esc(t.deed_no || '—')}</td><td>${can('handover') && t.status !== 'issued' ? `<button class="btn" data-call="EXT.title" data-args="${J([t.id, t.status === 'ready' ? 'submitted' : 'issued'])}">${t.status === 'ready' ? 'تقديم للوزارة' : 'تسجيل صدور السند'}</button>` : ''}</td></tr>`), 'تظهر الوحدات هنا بعد تسليمها.'));
  } else if (k === 'fm') {
    const F = await api('/fm');
    B.innerHTML = BOX('أصول المرافق المشتركة والصيانة الوقائية', T(['الأصل', 'المشروع', 'الفئة', 'آخر صيانة', 'الصيانة القادمة', ''], F.assets.map(a => `<tr><td>${esc(a.name)}</td><td>${esc(a.project)}</td><td>${esc(a.category)}</td><td>${fmtDate(a.last_service)}</td><td>${a.overdue ? pill('متأخرة ' + fmtDate(a.next_service), 'p-b') : fmtDate(a.next_service)}</td><td></td></tr>`)))
      + BOX('أوامر العمل', T(['العنوان', 'الاستحقاق', 'الحالة', ''], F.work_orders.map(w => `<tr><td>${esc(w.title)}</td><td>${fmtDate(w.due)}</td><td>${w.status === 'done' ? pill('منجز', 'p-ok') : pill('مفتوح', 'p-w')}</td><td>${w.status === 'open' && can('service') ? `<button class="btn" data-call="EXT.wo" data-args="${J([w.id])}">إنجاز</button>` : ''}</td></tr>`)));
  } else if (k === 'oa') {
    const pid = EXT.oaP || (S.projects.find(p => p.completed) || S.projects.find(p => p.kind === 'villa') || S.projects[0]).id, o = await api(`/oa/${pid}`);
    B.innerHTML = `<div class="toolbar"><select id="oaP">${projOpts(pid)}</select>${can('oa') ? '<button class="btn p" id="oaBill">إصدار مطالبات السنة</button>' : ''}</div>`
      + KP([['الملاك', N(o.owners)], ['ميزانية ' + N(o.year), OMR(o.budget_total)], ['المعدل', ND(o.rate_per_sqm) + ' ر.ع/م²'], ['المحصّل', OMR(o.collected), 'من ' + OMR(o.billed)]]) + `<div class="ai">${esc(o.rule)}</div>`
      + BOX('بنود الميزانية', T(['البند', 'المبلغ'], o.budget.map(b => `<tr><td>${esc(b.line)}</td><td>${OMR(b.amount)}</td></tr>`)))
      + BOX('التصويت الإلكتروني', T(['البند', 'يغلق', 'المشاركة', 'نعم', 'لا', 'النتيجة'], o.motions.map(m => `<tr><td>${esc(m.title)}</td><td>${fmtDate(m.closes)}</td><td>${pct(m.turnout)} (${N(m.votes)})</td><td>${pct(m.yes)}</td><td>${pct(m.no)}</td><td>${!m.quorum_met ? pill('النصاب لم يكتمل', 'p-w') : m.passed ? pill('مُقر', 'p-ok') : pill('مرفوض', 'p-b')}</td></tr>`)))
      + BOX('مطالبات الملاك', T(['المالك', 'الوحدة', 'المطالبة', 'المسدد'], o.charges.slice(0, 50).map(c => `<tr><td>${esc(c.owner)}</td><td><span class="num">${esc(c.unit)}</span></td><td>${OMR(c.amount)}</td><td>${OMR(c.paid)}</td></tr>`), 'لم تصدر مطالبات لهذه السنة بعد.'));
    $('#oaP').onchange = ev => { EXT.oaP = +ev.target.value; EXT.l_post(); };
    if ($('#oaBill')) $('#oaBill').onclick = async () => { await tryDo(() => api(`/oa/${pid}/bill`, {method: 'POST'}), r => `صدرت ${N(r.owners)} مطالبة`); EXT.l_post(); };
  } else {
    const L = await api('/leasing');
    B.innerHTML = KP([['وحدات محفظة التأجير', N(L.units.length)], ['نسبة الإشغال', pct(L.occupancy)], ['الإيجار السنوي', OMR(L.annual_rent)], ['متأخرات', OMR(L.arrears)]])
      + BOX('عقود الإيجار', T(['الوحدة', 'المستأجر', 'من', 'إلى', 'الإيجار السنوي', 'متأخرات', 'تنبيه'], L.leases.map((l, i) => `<tr data-i="${i}"><td><span class="num">${esc(l.unit)}</span></td><td>${esc(l.tenant)}</td><td>${fmtDate(l.start)}</td><td>${fmtDate(l.end)}</td><td>${OMR(l.annual_rent)}</td><td>${l.arrears ? pill(OMR(l.arrears), 'p-b') : '—'}</td><td>${l.renewal_alert ? pill(esc(l.renewal_alert), 'p-w') : ''}</td></tr>`)),
        can('leasing') ? '<button class="btn" data-call="EXT.newLease">+ عقد إيجار</button>' : '');
    EXT.data.leasing = L;
    $$('#postB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); const l = L.leases[+tr.dataset.i];
      insp('عقد إيجار', `<h3>${esc(l.tenant)}</h3><dl class="kv"><dt>الوحدة</dt><dd>${esc(l.unit)}</dd><dt>مرجع البلدية</dt><dd>${esc(l.municipality_ref || 'لم يوثق بعد')}</dd><dt>التأمين</dt><dd>${OMR(l.deposit)}</dd></dl>${T(['الاستحقاق', 'المبلغ', 'الحالة', ''], l.dues.map(d => `<tr><td>${fmtDate(d.due)}</td><td>${OMR(d.amount)}</td><td>${d.paid >= d.amount ? pill('مسدد', 'p-ok') : new Date(d.due) < new Date() ? pill('متأخر', 'p-b') : pill('قادم', 'p-bl')}</td><td>${d.paid < d.amount && can('leasing') ? `<button class="btn" data-call="EXT.rent" data-args="${J([d.id])}">تحصيل</button>` : ''}</td></tr>`))}`); });
  }
};
EXT.showHand = function (h) {
  insp('تسليم وحدة', `<h3><span class="num">${esc(h.unit)}</span> · ${esc(h.customer)}</h3><dl class="kv"><dt>الموعد</dt><dd>${fmtDate(h.appointment)}</dd><dt>المسدد</dt><dd>${pct(h.paid_ratio)}</dd>${h.certificate_no ? `<dt>شهادة التسليم</dt><dd>${esc(h.certificate_no)}</dd><dt>ضمان التشطيب</dt><dd>حتى ${fmtDate(h.warranty_until)}</dd><dt>الضمان الإنشائي</dt><dd>حتى ${fmtDate(h.structural_until)}</dd>` : ''}</dl>
   <b>ملاحظات الفحص قبل التسليم</b>${T(['الملاحظة', 'المكان', 'الحالة', ''], h.snags.map(s => `<tr><td>${esc(s.item)}</td><td>${esc(s.location)}</td><td>${s.status === 'open' ? pill('مفتوحة', 'p-b') : pill('مُصلحة', 'p-ok')}</td><td>${s.status === 'open' && can('handover') ? `<button class="btn" data-call="EXT.fix" data-args="${J([s.id])}">أُصلحت</button>` : ''}</td></tr>`))}
   ${h.status !== 'done' && can('handover') ? `<label>إضافة ملاحظة</label><input id="hn" placeholder="مثال: خدش في باب غرفة النوم"><div class="btns" style="margin-top:8px"><button class="btn" id="hadd">إضافة</button></div>
   <hr style="border:0;border-top:1px solid var(--line);margin:14px 0"><label>قراءة عداد الكهرباء</label><input id="he" inputmode="numeric" value="0"><label>قراءة عداد الماء</label><input id="hw" inputmode="numeric" value="0"><label>عدد المفاتيح</label><input id="hk" inputmode="numeric" value="3"><div class="err" id="herr"></div><div class="btns" style="margin-top:10px"><button class="btn p" id="hgo">إتمام التسليم وإصدار الشهادة</button></div>` : ''}`);
  if ($('#hadd')) $('#hadd').onclick = async () => { await tryDo(() => api('/snags', {method: 'POST', body: {booking_id: h.booking_id, item: $('#hn').value, location: ''}}), 'أُضيفت الملاحظة'); EXT.l_post(); };
  if ($('#hgo')) $('#hgo').onclick = async () => { try { const r = await api(`/bookings/${h.booking_id}/handover/complete`, {method: 'POST', body: {electricity: +$('#he').value, water: +$('#hw').value, keys: +$('#hk').value}}); toast('✓ سُلّمت الوحدة · شهادة ' + r.certificate); EXT.l_post(); } catch (e) { $('#herr').textContent = e.message; } };
};
EXT.fix = async id => { await tryDo(() => api(`/snags/${id}/fix`, {method: 'POST'}), 'أُغلقت الملاحظة'); EXT.l_post(); };
EXT.title = async (id, st) => { const deed = st === 'issued' ? prompt('رقم سند الملكية:') : ''; if (st === 'issued' && !deed) return; await tryDo(() => api(`/titles/${id}`, {method: 'POST', body: {status: st, deed_no: deed}}), 'حُدّثت الحالة'); EXT.l_post(); };
EXT.wo = async id => { const c = prompt('تكلفة الصيانة (ر.ع):', '0'); if (c == null) return; await tryDo(() => api(`/work-orders/${id}/done`, {method: 'POST', body: {cost: +c}}), 'أُنجز أمر العمل وجُدولت الصيانة القادمة'); EXT.l_post(); };
EXT.rent = async id => { await tryDo(() => api(`/rent-dues/${id}/pay`, {method: 'POST'}), 'حُصّل الإيجار وصدرت فاتورة'); EXT.l_post(); };
EXT.newLease = () => { const L = EXT.data.leasing, used = new Set(L.leases.filter(l => l.status === 'active').map(l => l.unit_id)), free = L.units.filter(u => !used.has(u.id));
  modal(`<h3>عقد إيجار جديد</h3><label>الوحدة</label><select id="lu">${free.map(u => `<option value="${u.id}">${esc(u.code)} · ${esc(u.type)}</option>`).join('')}</select><label>اسم المستأجر</label><input id="ln"><label>الهاتف</label><input id="lp"><label>رقم الهوية</label><input id="li"><label>تاريخ البداية</label><input id="ls" type="date"><label>المدة (شهر)</label><input id="lm" value="12"><label>الإيجار السنوي</label><input id="lr" inputmode="numeric"><label>عدد الدفعات في السنة</label><select id="lf"><option>1</option><option>2</option><option selected>4</option><option>12</option></select><div class="err" id="le"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="lgo">حفظ</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#lgo').onclick = async () => { try { await api('/leases', {method: 'POST', body: {unit_id: +$('#lu').value, tenant_name: $('#ln').value, tenant_phone: $('#lp').value, tenant_id_number: $('#li').value, start: $('#ls').value, months: +$('#lm').value, annual_rent: +$('#lr').value, frequency: +$('#lf').value}}); closeModal(); toast('سُجّل العقد — يلزم توثيقه لدى البلدية'); EXT.l_post(); } catch (e) { $('#le').textContent = e.message; } }; };

/* ================================================================ الإيجارات المتكاملة (0.21.0) */
const LMETH = {cash: 'نقدًا', cheque: 'شيك', transfer: 'تحويل بنكي', card: 'بطاقة', other: 'أخرى'};
const LUSE = {residential: 'سكني', commercial: 'تجاري', office: 'مكتب', warehouse: 'مستودع', land: 'أرض'};
const LSTP = {leased: 'p-ok', prep: 'p-bl', vacant: 'p-w', maintenance: 'p-b', not_leasable: 'p-b'};
const LLSP = {active: 'p-ok', draft: 'p-w', expired: 'p-b', terminated: 'p-b', renewed: 'p-bl', evicted: 'p-b'};
const LCQP = {held: 'p-w', deposited: 'p-bl', cleared: 'p-ok', bounced: 'p-b', returned: 'p-w', cancelled: 'p-w'};
const methOpts = (sel = '') => '<option value="">غير موثَّقة</option>' + Object.entries(LMETH).map(([k, v]) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${v}</option>`).join('');
const LDOC = (kind, id, label) => `<a class="btn" href="/api/docs/${kind}/${id}.pdf" target="_blank" rel="noopener">${label}</a>`;
const num = v => (v === '' || v == null) ? null : +v;

EXT.l_lea = async function () {
  const tabs = [['ov', 'نظرة عامة'], ['ls', 'العقود'], ['un', 'الوحدات'], ['tn', 'المستأجرون'], ['cq', 'الشيكات'], ['py', 'التحصيل'], ['ar', 'المتأخرات والتبرع'], ['mt', 'الصيانة والمصاريف'], ['ow', 'الملاك والكشوف'], ...(can('leasing_approve') ? [['im', 'الاستيراد']] : [])], el = $('#lea'), k = this.cur.lea, W = can('leasing');
  el.innerHTML = SUB0('lea', tabs, k) + '<div id="leaB">…</div>';
  const B = $('#leaB');
  if (k === 'ov') {
    const [o, ag] = await Promise.all([api('/lea/overview'), api('/lea/aging')]);
    B.innerHTML = KP([['الإشغال', pct(o.occupancy), `${N(o.leased)} من ${N(o.units)} وحدة`], ['الإيجار السنوي', OMR(o.annual_rent)], ['المتأخرات', OMR(o.arrears)],
        ['مستحق هذا الشهر', OMR(o.month.expected), 'محصَّل ' + OMR(o.month.collected)], ['عقود تنتهي خلال 90 يومًا', N(o.expiring['90']), `منها ${N(o.expiring['30'])} خلال 30 يومًا`],
        ['شيكات حان إيداعها', N(o.cheques.held_due), `مرتجع ${N(o.cheques.bounced)} · مودَع ${N(o.cheques.deposited)}`]])
      + BOX('تعمير المتأخرات', T(['المدة', 'الاستحقاقات', 'المبلغ'], o.aging.map(b => `<tr><td>${esc(b.label)}</td><td>${N(b.count)}</td><td>${b.amount ? pill(OMR(b.amount), 'p-b') : '—'}</td></tr>`)),
        W ? '<button class="btn" data-call="EXT.leaRemind">تشغيل التذكيرات</button>' : '')
      + BOX('العقود المتأخرة', T(['العقد', 'الوحدة', 'المستأجر', 'المتأخر', 'أقدم تأخير'], ag.leases.map(x => `<tr data-id="${x.lease_id}"><td><span class="num">${esc(x.number)}</span></td><td>${esc(x.unit)}</td><td>${esc(x.tenant)}</td><td>${pill(OMR(x.amount), 'p-b')}</td><td>${N(x.oldest_days)} يومًا</td></tr>`), 'لا متأخرات.'));
    $$('#leaB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.leaOpen(+tr.dataset.id); });
  } else if (k === 'ls') {
    const st = this.leaSt || '', q = this.leaQ || '', L = await api(`/lea/leases?status=${st}&q=${encodeURIComponent(q)}`);
    B.innerHTML = `<div class="toolbar"><select id="lst"><option value="">كل الحالات</option>${[['draft', 'مسودة'], ['active', 'ساري'], ['expired', 'منتهٍ'], ['terminated', 'مُنهى']].map(([a, b]) => `<option value="${a}" ${a === st ? 'selected' : ''}>${b}</option>`).join('')}</select> <input id="lq" placeholder="بحث: رقم العقد أو الوحدة أو المستأجر" value="${esc(q)}"></div>`
      + BOX('عقود الإيجار', T(['العقد', 'الوحدة', 'المستأجر', 'من', 'إلى', 'الإيجار السنوي', 'الحالة', 'متأخرات'], L.map(l => `<tr data-id="${l.id}"><td><span class="num">${esc(l.number)}</span></td><td>${esc(l.unit)}</td><td>${esc(l.tenant)}</td><td>${fmtDate(l.start)}</td><td>${fmtDate(l.end)}</td><td>${OMR(l.annual_rent)}</td><td>${pill(esc(l.status_label), LLSP[l.status] || 'p-w')}${l.days_left != null && l.days_left <= 90 ? ' ' + pill(`${N(l.days_left)} يومًا`, 'p-w') : ''}</td><td>${l.arrears ? pill(OMR(l.arrears), 'p-b') : '—'}</td></tr>`), 'لا عقود مطابقة.'),
        W ? '<button class="btn p" data-call="EXT.leaNew">+ عقد جديد</button>' : '');
    $('#lst').onchange = e => { EXT.leaSt = e.target.value; EXT.l_lea(); };
    $('#lq').onchange = e => { EXT.leaQ = e.target.value; EXT.l_lea(); };
    $$('#leaB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.leaOpen(+tr.dataset.id); });
  } else if (k === 'un') {
    const U = (await api('/lea/units')).units;
    B.innerHTML = KP([['وحدات المحفظة', N(U.length)], ['مؤجَّرة', N(U.filter(u => u.state === 'leased').length)], ['شاغرة', N(U.filter(u => u.state === 'vacant').length)], ['صيانة / غير قابلة', N(U.filter(u => ['maintenance', 'not_leasable'].includes(u.state)).length)]])
      + BOX('الوحدات', T(['الوحدة', 'المشروع', 'الاستخدام', 'الحالة', 'المستأجر', 'المالك', 'عدّادات', 'شاغرة منذ'], U.map((u, i) => `<tr data-i="${i}"><td><span class="num">${esc(u.code)}</span><br><span class="muted">${esc(u.type || '')}${u.area ? ' · ' + N(u.area) + ' م²' : ''}</span></td><td>${esc(u.project)}</td><td>${esc(LUSE[u.use] || u.use || '—')}</td><td>${pill(esc(u.state_label), LSTP[u.state])}</td><td>${u.lease ? esc(u.lease.tenant) : '—'}</td><td>${esc(u.owner || '—')}</td><td>${N(u.meters.length)}</td><td>${u.vacant_since ? fmtDate(u.vacant_since) + ` <span class="muted">(${N(u.vacant_days)} يومًا)</span>` : '—'}</td></tr>`)));
    $$('#leaB tr[data-i]').forEach(tr => tr.onclick = () => { sel(tr); EXT.leaUnit(U[+tr.dataset.i]); });
  } else if (k === 'tn') {
    const q = this.leaTq || '', T_ = await api(`/lea/tenants?q=${encodeURIComponent(q)}`);
    B.innerHTML = `<div class="toolbar"><input id="ltq" placeholder="بحث بالاسم أو الهاتف أو السجل التجاري" value="${esc(q)}"></div>`
      + BOX('المستأجرون', T(['المستأجر', 'النوع', 'الهاتف', 'الهوية', 'عقود', 'تقييم', ''], T_.map(t => `<tr data-id="${t.id}"><td><b>${esc(t.name)}</b></td><td>${t.kind === 'company' ? 'شركة' : 'فرد'}</td><td>${esc(t.phone || '—')}</td><td><span class="num">${esc(t.id_number || t.cr_number || '—')}</span></td><td>${N(t.leases)} (${N(t.active)} ساري)</td><td>${esc(t.rating || '—')}</td><td>${t.blacklisted ? pill('قائمة سوداء', 'p-b') : ''}</td></tr>`), 'لا مستأجرين.'),
        W ? '<button class="btn p" data-call="EXT.leaTenantForm">+ مستأجر</button>' : '');
    $('#ltq').onchange = e => { EXT.leaTq = e.target.value; EXT.l_lea(); };
    $$('#leaB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.leaTenant(+tr.dataset.id); });
  } else if (k === 'cq') {
    const st = this.leaCs || '', C = await api('/lea/cheques' + (st ? '?status=' + st : ''));
    B.innerHTML = `<div class="toolbar"><select id="cst"><option value="">كل الحالات</option>${[['held', 'محفوظة'], ['deposited', 'مودَعة'], ['cleared', 'مصروفة'], ['bounced', 'مرتجعة'], ['returned', 'أُعيدت']].map(([a, b]) => `<option value="${a}" ${a === st ? 'selected' : ''}>${b}</option>`).join('')}</select></div>`
      + BOX('الشيكات المستلمة', T(['الشيك', 'البنك', 'المستأجر', 'العقد', 'المبلغ', 'الاستحقاق', 'الحالة', ''], C.map(q => {
        const a = q.status === 'held' ? [['deposit', 'إيداع'], ['return', 'إعادة']] : q.status === 'deposited' ? [['clear', 'صرف'], ['bounce', 'ارتجاع']] : q.status === 'cleared' ? [['bounce', 'ارتجاع']] : q.status === 'bounced' ? [['return', 'إعادة']] : [];
        return `<tr><td><span class="num">${esc(q.number)}</span></td><td>${esc(q.bank)}</td><td>${esc(q.tenant)}<br><span class="muted">${esc(q.unit)}</span></td><td>${esc(q.lease_no)}</td><td>${OMR(q.amount)}</td><td>${fmtDate(q.due_date)}</td><td>${pill(esc(q.status_label), LCQP[q.status])}${q.bounce_reason ? `<br><span class="muted">${esc(q.bounce_reason)}</span>` : ''}</td><td>${LDOC('cheque_receipt', q.id, 'إيصال')} ${W ? a.map(([x, l]) => `<button class="btn" data-call="EXT.leaCheqAct" data-args="${J([q.id, x])}">${l}</button>`).join(' ') : ''}</td></tr>`;
      }), 'لا شيكات.'));
    $('#cst').onchange = e => { EXT.leaCs = e.target.value; EXT.l_lea(); };
  } else if (k === 'py') {
    const P = await api('/lea/payments?limit=200');
    B.innerHTML = BOX('دفتر التحصيل', T(['الإيصال', 'التاريخ', 'العقد', 'المستأجر', 'المبلغ', 'الطريقة', 'المرجع', ''], P.map(p => `<tr><td>${p.receipt_no ? `<span class="num">${esc(p.receipt_no)}</span>` : p.reverses_id ? pill('حركة عكسية', 'p-w') : '—'}</td><td>${fmtDate(p.paid_on)}</td><td>${esc(p.lease_no || '')}<br><span class="muted">${esc(p.unit)}</span></td><td>${esc(p.tenant)}</td><td>${p.amount < 0 ? pill(OMR(p.amount), 'p-b') : OMR(p.amount)}</td><td>${esc(p.method_label)}</td><td>${esc(p.reference || p.note || '')}</td><td>${p.receipt_no ? LDOC('rent_receipt', p.id, 'إيصال') : ''} ${W && p.amount > 0 ? `<button class="btn" data-call="EXT.leaReverse" data-args="${J([p.id])}">عكس</button>` : ''}</td></tr>`), 'لا حركات.'));
  } else if (k === 'ar') {
    await EXT.leaArrearsTab(B);
  } else if (k === 'mt') {
    await EXT.leaMaintTab(B);
  } else if (k === 'ow') {
    await EXT.leaOwnersTab(B);
  } else if (k === 'im') {
    await EXT.leaImportTab(B);
  }
};

EXT.leaRemind = async () => { await tryDo(() => api('/lea/reminders/run', {method: 'POST'}), r => `${N(r.created)} تنبيه جديد`); EXT.l_lea(); };

EXT.leaOpen = async function (id) {
  const [d, ops] = await Promise.all([api('/lea/leases/' + id), api(`/lea/leases/${id}/ops`)]), W = can('leasing'), t = d.tenant;
  const dues = d.dues.map(x => `<tr><td>${fmtDate(x.due)}<br><span class="muted">${esc(x.label || '')}</span></td><td>${OMR(x.amount)}</td><td>${OMR(x.paid)}</td><td>${x.state === 'paid' ? pill('مسدد', 'p-ok') : x.state === 'late' ? pill('متأخر', 'p-b') : pill('قادم', 'p-bl')}${x.cheque ? '<br>' + pill('شيك ' + esc(x.cheque.number), 'p-w') : ''}</td><td>${x.balance > 0.0005 && W && d.status !== 'draft' ? `<button class="btn" data-call="EXT.leaPay" data-args="${J([d.id, x.id, x.balance])}">تحصيل</button>` : ''}</td></tr>`);
  insp(`${d.number} · ${d.unit}`, `<h3>${esc(t.name)}</h3><div class="btns" style="margin-bottom:10px">${pill(esc(d.status_label), LLSP[d.status] || 'p-w')} ${LDOC('lease', d.id, 'عقد الإيجار PDF')}${d.status === 'draft' && W ? ` <button class="btn p" data-call="EXT.leaSign" data-args="${J([d.id])}">توقيع العقد وتوليد الدفعات</button>` : ''}</div>
   <dl class="kv"><dt>الفترة</dt><dd>${fmtDate(d.start)} ← ${fmtDate(d.end)}</dd><dt>بداية احتساب الإيجار</dt><dd>${fmtDate(d.rent_start)}${d.prep_free_days ? ` (تجهيز ${N(d.prep_free_days)} يومًا)` : ''}</dd><dt>الإيجار السنوي</dt><dd>${d.terms.map(x => `س${x.year_no}: ${OMR(x.annual_rent)}`).join(' · ')}</dd><dt>التأمين</dt><dd>${d.deposit ? OMR(d.deposit) : '—'}</dd><dt>مرجع البلدية</dt><dd>${esc(d.municipality_ref || 'لم يُوثَّق بعد')}</dd><dt>الرصيد</dt><dd>مستحق ${OMR(d.totals.billed)} · مسدد ${OMR(d.totals.paid)} · متأخر ${d.totals.arrears ? pill(OMR(d.totals.arrears), 'p-b') : '—'}</dd></dl>
   ${W && d.status !== 'draft' ? `<div class="btns" style="margin:10px 0"><button class="btn p" data-call="EXT.leaPay" data-args="${J([d.id, null, d.totals.balance])}">تحصيل دفعة (تُوزَّع على الأقدم)</button> <button class="btn" data-call="EXT.leaCheque" data-args="${J([d.id])}">استلام شيك</button></div>` : ''}
   ${EXT.leaOpsHtml(d, ops)}
   <b>جدول الدفعات</b>${T(['الاستحقاق', 'المبلغ', 'المسدد', 'الحالة', ''], dues)}
   <b>حركات التحصيل</b>${T(['الإيصال', 'التاريخ', 'المبلغ', 'الطريقة'], d.payments.map(p => `<tr><td>${p.receipt_no ? LDOC('rent_receipt', p.id, esc(p.receipt_no)) : pill(p.reverses_id ? 'عكسية' : 'مرحَّلة', 'p-w')}</td><td>${fmtDate(p.paid_on)}</td><td>${p.amount < 0 ? pill(OMR(p.amount), 'p-b') : OMR(p.amount)}</td><td>${esc(LMETH[p.method] || 'غير موثَّقة')}</td></tr>`), 'لا حركات.')}
   ${d.cheques.length ? `<b>الشيكات</b>${T(['الشيك', 'المبلغ', 'الاستحقاق', 'الحالة'], d.cheques.map(q => `<tr><td>${esc(q.number)} · ${esc(q.bank)}</td><td>${OMR(q.amount)}</td><td>${fmtDate(q.due_date)}</td><td>${pill(esc(q.status), LCQP[q.status])}</td></tr>`))}` : ''}
   <b>السجل</b>${T(['الوقت', 'الحدث'], d.events.map(e => `<tr><td>${esc((e.at || '').slice(0, 16).replace('T', ' '))}</td><td>${esc(e.detail || e.kind)}<br><span class="muted">${esc(e.by_user || '')}</span></td></tr>`), '—')}`);
};

EXT.leaSign = async id => { await tryDo(() => api(`/lea/leases/${id}/sign`, {method: 'POST'}), 'وُقِّع العقد وولِّدت الدفعات'); EXT.l_lea(); EXT.leaOpen(id); };

EXT.leaPay = (lid, did, bal) => {
  modal(`<h3>${did ? 'تحصيل استحقاق' : 'تحصيل دفعة على العقد'}</h3><label>المبلغ (ر.ع) — المتبقي ${OMR(bal)}</label><input id="pa" inputmode="decimal" value="${bal}"><label>طريقة السداد</label><select id="pm">${methOpts()}</select>
   <label>تاريخ السداد الفعلي</label><input id="pd" type="date" max="${new Date().toISOString().slice(0, 10)}" value="${new Date().toISOString().slice(0, 10)}"><label>المرجع (رقم الحوالة / الإيصال)</label><input id="pr"><label>ملاحظة</label><input id="pn">
   <div class="err" id="pe"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="pgo">تسجيل التحصيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#pgo').onclick = async () => { try { const r = await api('/lea/payments', {method: 'POST', body: {lease_id: lid, amount: +$('#pa').value, due_id: did, method: $('#pm').value || null, paid_on: $('#pd').value || null, reference: $('#pr').value, note: $('#pn').value}});
    modal(`<h3>✓ سُجّل التحصيل</h3><p>الإيصال <b class="num">${esc(r.receipt_no)}</b> · ${OMR(r.amount)}</p><div class="btns">${LDOC('rent_receipt', r.first_id, 'فتح الإيصال PDF')} <button class="btn" data-call="closeModal">إغلاق</button></div>`); EXT.l_lea(); EXT.leaOpen(lid); } catch (e) { $('#pe').textContent = e.message; } };
};

EXT.leaReverse = async id => { const reason = prompt('سبب عكس الحركة (يُسجَّل في التدقيق):'); if (!reason) return; await tryDo(() => api(`/lea/payments/${id}/reverse`, {method: 'POST', body: {reason}}), 'سُجّلت حركة عكسية'); EXT.l_lea(); };

EXT.leaCheque = lid => {
  modal(`<h3>استلام شيك</h3><label>رقم الشيك</label><input id="qn"><label>البنك</label><input id="qb"><label>الفرع</label><input id="qf"><label>القيمة (ر.ع)</label><input id="qa" inputmode="decimal"><label>تاريخ استحقاق الشيك</label><input id="qd" type="date"><label>الساحب (إن اختلف عن المستأجر)</label><input id="qw">
   <div class="err" id="qe"></div><p class="muted">استلام الشيك حفظ لدى الشركة فقط؛ لا يُحتسب سدادًا قبل صرفه.</p><div class="btns" style="margin-top:12px"><button class="btn p" id="qgo">تسجيل الاستلام</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#qgo').onclick = async () => { try { const r = await api('/lea/cheques', {method: 'POST', body: {lease_id: lid, number: $('#qn').value, bank: $('#qb').value, branch: $('#qf').value, amount: +$('#qa').value, due_date: $('#qd').value, drawer: $('#qw').value}});
    modal(`<h3>✓ سُجّل الشيك</h3><p>إيصال الاستلام <b class="num">${esc(r.receipt_no)}</b></p><div class="btns">${LDOC('cheque_receipt', r.id, 'فتح الإيصال PDF')} <button class="btn" data-call="closeModal">إغلاق</button></div>`); EXT.l_lea(); EXT.leaOpen(lid); } catch (e) { $('#qe').textContent = e.message; } };
};

EXT.leaCheqAct = async (id, act) => {
  let body = {};
  if (act === 'bounce' || act === 'return') { const reason = prompt(act === 'bounce' ? 'سبب الارتجاع:' : 'سبب إعادة الشيك للمستأجر:'); if (!reason) return; body = {reason}; }
  await tryDo(() => api(`/lea/cheques/${id}/${act}`, {method: 'POST', body}), {deposit: 'أُودع الشيك', clear: 'صُرف الشيك وسُجّل التحصيل', bounce: 'سُجّل الارتجاع وعُكس التحصيل', return: 'أُعيد الشيك'}[act]); EXT.l_lea();
};

EXT.leaUnit = async function (u) {
  const O = await api('/lea/owners'), W = can('leasing');
  insp(`وحدة ${u.code}`, `<h3>${esc(u.project)} · ${esc(u.type || '')}</h3><dl class="kv"><dt>الحالة</dt><dd>${pill(esc(u.state_label), LSTP[u.state])}</dd><dt>المستأجر</dt><dd>${u.lease ? esc(u.lease.tenant) + ` (${esc(u.lease.number)})` : '—'}</dd><dt>شاغرة منذ</dt><dd>${u.vacant_since ? fmtDate(u.vacant_since) : '—'}</dd></dl>
   ${W ? `<label>المالك</label><select id="uo">${O.map(o => `<option value="${o.id}" ${o.id === u.owner_id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>
   <label>تجاوز يدوي للحالة</label><select id="us"><option value="none">بلا (تُشتق من العقود)</option><option value="prep" ${u.lease_state === 'prep' ? 'selected' : ''}>فترة تجهيز</option><option value="maintenance" ${u.lease_state === 'maintenance' ? 'selected' : ''}>صيانة</option><option value="not_leasable" ${u.lease_state === 'not_leasable' ? 'selected' : ''}>غير قابلة للتأجير</option></select>
   <label>الاستخدام</label><select id="uu">${Object.entries(LUSE).map(([a, b]) => `<option value="${a}" ${a === u.use ? 'selected' : ''}>${b}</option>`).join('')}</select><label>مواقف السيارات</label><input id="up" inputmode="numeric" value="${u.parking_bays ?? ''}">
   <div class="btns" style="margin-top:10px"><button class="btn p" id="ugo">حفظ</button></div>
   <hr style="border:0;border-top:1px solid var(--line);margin:14px 0"><b>العدّادات</b>${T(['النوع', 'الرقم', 'المزوّد', ''], u.meters.map(m => `<tr><td>${esc({water: 'ماء', electricity: 'كهرباء', gas: 'غاز', other: 'أخرى'}[m.kind] || m.kind)}${m.shared ? ' (مشترك)' : ''}</td><td>${esc(m.number)}</td><td>${esc(m.provider || '')}</td><td><button class="btn" data-call="EXT.leaMeterDel" data-args="${J([m.id])}">حذف</button></td></tr>`), 'لا عدّادات.')}
   <div class="btns" style="margin-top:8px"><select id="mk"><option value="electricity">كهرباء</option><option value="water">ماء</option><option value="gas">غاز</option><option value="other">أخرى</option></select> <input id="mn" placeholder="رقم العدّاد"> <button class="btn" id="mgo">إضافة</button></div>` : ''}`);
  if ($('#ugo')) $('#ugo').onclick = async () => { await tryDo(() => api('/lea/units/' + u.id, {method: 'POST', body: {owner_id: +$('#uo').value, lease_state: $('#us').value, use: $('#uu').value, parking_bays: num($('#up').value)}}), 'حُفظت الوحدة'); EXT.l_lea(); };
  if ($('#mgo')) $('#mgo').onclick = async () => { await tryDo(() => api(`/lea/units/${u.id}/meters`, {method: 'POST', body: {kind: $('#mk').value, number: $('#mn').value}}), 'أُضيف العدّاد'); EXT.l_lea(); };
};
EXT.leaMeterDel = async id => { await tryDo(() => api('/lea/meters/' + id, {method: 'DELETE'}), 'حُذف العدّاد'); EXT.l_lea(); };

const tenantFields = (t = {}) => `<label>الاسم</label><input id="tn_name" value="${esc(t.name || '')}"><label>النوع</label><select id="tn_kind"><option value="individual" ${t.kind !== 'company' ? 'selected' : ''}>فرد</option><option value="company" ${t.kind === 'company' ? 'selected' : ''}>شركة</option></select>
  <label>الهاتف</label><input id="tn_phone" value="${esc(t.phone || '')}"><label>رقم الهوية</label><input id="tn_id" value="${esc(t.id_number || '')}"><label>السجل التجاري (للشركات)</label><input id="tn_cr" value="${esc(t.cr_number || '')}">
  <label>الممثل القانوني</label><input id="tn_rep" value="${esc(t.rep_name || '')}"><label>البريد</label><input id="tn_mail" value="${esc(t.email || '')}"><label>العنوان</label><input id="tn_addr" value="${esc(t.address || '')}">`;
const tenantBody = () => ({name: $('#tn_name').value, kind: $('#tn_kind').value, phone: $('#tn_phone').value, id_number: $('#tn_id').value, cr_number: $('#tn_cr').value, rep_name: $('#tn_rep').value, email: $('#tn_mail').value, address: $('#tn_addr').value});

EXT.leaTenantForm = (t) => {
  modal(`<h3>${t && t.id ? 'تعديل مستأجر' : 'مستأجر جديد'}</h3>${tenantFields(t || {})}<div class="err" id="te"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="tgo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#tgo').onclick = async () => { try { await api('/lea/tenants' + (t && t.id ? '/' + t.id : ''), {method: 'POST', body: tenantBody()}); closeModal(); toast('حُفظ المستأجر'); EXT.l_lea(); } catch (e) { $('#te').textContent = e.message; } };
};

EXT.leaTenant = async function (id) {
  const t = await api('/lea/tenants/' + id), W = can('leasing');
  insp(t.name, `<dl class="kv"><dt>النوع</dt><dd>${t.kind === 'company' ? 'شركة' : 'فرد'}</dd><dt>الهاتف</dt><dd>${esc(t.phone || '—')}</dd><dt>الهوية</dt><dd><span class="num">${esc(t.id_number || '—')}</span></dd><dt>السجل التجاري</dt><dd>${esc(t.cr_number || '—')}</dd><dt>الممثل</dt><dd>${esc(t.rep_name || '—')}</dd><dt>البريد</dt><dd>${esc(t.email || '—')}</dd></dl>
   ${t.blacklisted ? `<p>${pill('قائمة سوداء', 'p-b')} ${esc(t.blacklist_reason || '')}</p>` : ''}
   <div class="btns" style="margin:10px 0">${W ? `<button class="btn" data-call="EXT.leaTenantEdit" data-args="${J([id])}">تعديل</button> <button class="btn" data-call="EXT.leaBlack" data-args="${J([id, !t.blacklisted])}">${t.blacklisted ? 'رفع من القائمة السوداء' : 'إدراج في القائمة السوداء'}</button> <button class="btn" data-call="EXT.leaAccount" data-args="${J([id])}">حساب البوابة</button>` : ''} <button class="btn" data-call="EXT.leaStatement" data-args="${J([id])}">كشف حساب</button></div>
   <b>عقود المستأجر</b>${T(['العقد', 'الوحدة', 'الحالة', 'الإيجار'], t.leases.map(l => `<tr><td><button class="link" data-call="EXT.leaOpen" data-args="${J([l.id])}">${esc(l.number)}</button></td><td>${esc(l.unit)}</td><td>${esc(l.status)}</td><td>${OMR(l.annual_rent)}</td></tr>`), 'لا عقود.')}`);
};
EXT.leaTenantEdit = async id => { EXT.leaTenantForm(await api('/lea/tenants/' + id)); };
EXT.leaBlack = async (id, on) => { const reason = prompt(on ? 'سبب الإدراج (إلزامي):' : 'سبب الرفع:'); if (!reason) return; await tryDo(() => api(`/lea/tenants/${id}/${on ? 'blacklist' : 'unblacklist'}`, {method: 'POST', body: {reason}}), 'تم'); EXT.l_lea(); EXT.leaTenant(id); };
EXT.leaStatement = async id => {
  const s = await api(`/lea/tenants/${id}/statement`);
  modal(`<h3>كشف حساب ${esc(s.tenant)}</h3>${s.leases.map(l => `<b>${esc(l.number)} · ${esc(l.unit)}</b>${T(['التاريخ', 'البيان', 'مدين', 'دائن'], l.entries.map(e => `<tr><td>${fmtDate(e.date)}</td><td>${esc(e.label)}</td><td>${e.debit ? OMR(e.debit) : ''}</td><td>${e.credit ? OMR(e.credit) : ''}</td></tr>`))}`).join('')}<p><b>الرصيد المستحق: ${OMR(s.balance)}</b></p><div class="btns"><button class="btn" data-call="closeModal">إغلاق</button></div>`);
};

EXT.leaOwnerForm = () => {
  modal(`<h3>مالك جديد</h3><label>الاسم</label><input id="on"><label>الهاتف</label><input id="op"><label>رقم الهوية / السجل</label><input id="oi"><label>الآيبان</label><input id="ob"><label>عمولة الإدارة (٪)</label><input id="of" inputmode="decimal" value="0"><label>أساس العمولة</label><select id="ox"><option value="collected">المحصَّل</option><option value="invoiced">المفوتَر</option></select>
   <div class="err" id="oe"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="ogo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#ogo').onclick = async () => { try { await api('/lea/owners', {method: 'POST', body: {name: $('#on').value, phone: $('#op').value, id_number: $('#oi').value, iban: $('#ob').value, mgmt_fee_pct: +$('#of').value, mgmt_basis: $('#ox').value}}); closeModal(); toast('أُضيف المالك'); EXT.l_lea(); } catch (e) { $('#oe').textContent = e.message; } };
};

EXT.leaNew = async function () {
  const [U, T_] = await Promise.all([api('/lea/units'), api('/lea/tenants')]);
  modal(`<h3>عقد إيجار جديد</h3><label>الوحدة</label><select id="nu">${U.units.map(u => `<option value="${u.id}">${esc(u.code)} · ${esc(u.state_label)}${u.owner ? ' · ' + esc(u.owner) : ''}</option>`).join('')}</select>
   <label>المستأجر</label><select id="nt"><option value="">— مستأجر جديد —</option>${T_.map(t => `<option value="${t.id}">${esc(t.name)}${t.blacklisted ? ' (قائمة سوداء)' : ''}</option>`).join('')}</select><div id="ntf">${tenantFields()}</div>
   <div class="g2"><div><label>بداية العقد</label><input id="ns" type="date"></div><div><label>المدة (شهرًا)</label><input id="nm" inputmode="numeric" value="12"></div>
   <div><label>الإيجار السنوي للسنة الأولى (ر.ع)</label><input id="nr" inputmode="decimal"></div><div><label>زيادة سنوية (٪)</label><input id="ne" inputmode="decimal" value="0"></div>
   <div><label>دفعات في السنة</label><select id="nf"><option value="12" selected>12 (شهري)</option><option value="4">4 (ربع سنوي)</option><option value="2">2 (نصف سنوي)</option><option value="1">1 (سنوي)</option></select></div><div><label>تجهيز مجاني (أيام)</label><input id="np" inputmode="numeric" value="0"></div>
   <div><label>التأمين (ر.ع)</label><input id="nd" inputmode="decimal" value="0"></div><div><label>مرجع توثيق البلدية</label><input id="nb"></div></div>
   <label><input type="checkbox" id="nc"> شرط التبرع بالتأخير (بنص العقد)</label><label>سبب تجاوز القائمة السوداء (للمدير فقط)</label><input id="no">
   <div id="npv"></div><div class="err" id="nerr"></div><div class="btns" style="margin-top:12px"><button class="btn" id="npre">معاينة الجدول</button> <button class="btn" id="ndr">حفظ مسودة</button> <button class="btn p" id="nsg">حفظ وتوقيع</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#nt').onchange = e => { $('#ntf').hidden = !!e.target.value; };
  const body = sign => ({unit_id: +$('#nu').value, tenant_id: $('#nt').value ? +$('#nt').value : null, tenant: $('#nt').value ? null : tenantBody(), start: $('#ns').value, months: +$('#nm').value, annual_rent: +$('#nr').value, escalation_pct: +$('#ne').value,
    frequency: +$('#nf').value, prep_free_days: +$('#np').value, deposit: +$('#nd').value, charity_clause: $('#nc').checked, municipality_ref: $('#nb').value, override_reason: $('#no').value, sign});
  $('#npre').onclick = async () => { try { const r = await api('/lea/leases/preview', {method: 'POST', body: {...body(false), tenant: null, tenant_id: null}}); $('#nerr').textContent = '';
    $('#npv').innerHTML = `<p class="muted">النهاية ${fmtDate(r.end)} · بداية احتساب الإيجار ${fmtDate(r.rent_start)} · الإجمالي ${OMR(r.total)}</p>` + T(['الدفعة', 'الاستحقاق', 'المبلغ'], r.schedule.map(d => `<tr><td>${esc(d.label)}</td><td>${fmtDate(d.due)}</td><td>${OMR(d.amount)}</td></tr>`)); } catch (e) { $('#nerr').textContent = e.message; } };
  const save = sign => async () => { try { const r = await api('/lea/leases', {method: 'POST', body: body(sign)}); closeModal(); toast(sign ? 'وُقِّع العقد وولِّدت الدفعات' : 'حُفظت المسودة'); EXT.cur.lea = 'ls'; EXT.l_lea(); EXT.leaOpen(r.id); } catch (e) { $('#nerr').textContent = e.message; } };
  $('#ndr').onclick = save(false); $('#nsg').onclick = save(true);
};

/* ================================================================ عمليات الإيجار (0.22.0) */
const tdy = () => new Date().toISOString().slice(0, 10);
const A_ = () => can('leasing_approve');
const NK = {reminder: 'تذكير', formal: 'إنذار رسمي', final: 'إنذار نهائي'};
const lines = v => (v || '').split('\n').map(s => s.trim()).filter(Boolean);
const errBox = id => `<div class="err" id="${id}"></div>`;
const goBtns = (go, extra = '') => `<div class="btns" style="margin-top:12px"><button class="btn p" id="${go}">${extra || 'تنفيذ'}</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`;
const post = (path, body) => api(path, {method: 'POST', body});
const after = (lid, msg) => { closeModal(); toast(msg); EXT.l_lea(); if (lid) EXT.leaOpen(lid); };

/* أزرار العمليات داخل نافذة العقد + أقسام المحاضر والإنذارات والخطط */
EXT.leaOpsHtml = (d, ops) => {
  const W = can('leasing'), act = d.status === 'active', closed = ['expired', 'terminated', 'evicted'].includes(d.status);
  const b = [];
  if (W && (act || d.status === 'expired') && !ops.renewed_to) b.push(['leaRenew', 'تجديد العقد']);
  if (W && act) b.push(['leaTerm', 'إنهاء مبكر']);
  if (act && A_() && ops.arrears > 0.0005) b.push(['leaEvict', 'إخلاء']);
  if (W && d.status !== 'draft' && !ops.handovers.some(h => h.kind === 'in')) b.push(['leaHand', 'محضر تسليم', 'in']);
  if (W && (closed || (act && d.end < tdy())) && !ops.handovers.some(h => h.kind === 'out')) b.push(['leaHand', 'محضر استلام', 'out']);
  if (W && closed && ['held', 'recorded'].includes(ops.deposit.state)) b.push(['leaSettle', 'تسوية التأمين']);
  if (W && ops.arrears > 0.0005 && d.status !== 'draft') b.push(['leaNotice', 'إنذار متأخرات']);
  if (A_() && ops.arrears > 0.0005 && d.status !== 'draft') b.push(['leaPlan', 'خطة سداد']);
  const dep = ops.deposit.state ? `<dt>حالة التأمين</dt><dd>${esc({held: 'محفوظ', recorded: 'مسجَّل', carried: 'انتقل للعقد المجدِّد', transferred: 'انتقل للعقد المجدِّد', returned: 'رُدّ كاملًا', partly_settled: 'رُدّ بعد خصومات', settled: 'استُنفد بخصومات موثَّقة'}[ops.deposit.state] || ops.deposit.state)}${ops.deposit.refund != null ? ` · المردود ${OMR(ops.deposit.refund)} · الخصومات ${OMR(ops.deposit.deducted)}` : ''}</dd>` : '';
  return `<dl class="kv">${dep}${ops.renewed_to ? `<dt>جُدِّد بـ</dt><dd><button class="link" data-call="EXT.leaOpen" data-args="${J([ops.renewed_to.id])}">${esc(ops.renewed_to.number)}</button></dd>` : ''}${d.renewed_from ? `<dt>تجديد لعقد سابق</dt><dd><button class="link" data-call="EXT.leaOpen" data-args="${J([d.renewed_from])}">عرض</button></dd>` : ''}</dl>`
    + (b.length ? `<div class="btns" style="margin:10px 0">${b.map(([fn, l, k]) => `<button class="btn" data-call="EXT.${fn}" data-args="${J(k ? [d.id, k] : [d.id])}">${l}</button>`).join(' ')}</div>` : '')
    + (ops.handovers.length ? `<b>محاضر التسليم والاستلام</b>${T(['المحضر', 'التاريخ', 'مفاتيح', 'قراءات'], ops.handovers.map(h => `<tr><td>${LDOC('handover_report', h.id, h.kind === 'in' ? 'تسليم' : 'استلام')}</td><td>${fmtDate(h.at)}</td><td>${h.keys ?? '—'}</td><td>${h.readings.map(r => `${esc(r.number || '')}: ${r.reading}${r.consumption != null ? ` (+${r.consumption})` : ''}`).join(' · ') || '—'}</td></tr>`))}` : '')
    + (ops.notices.length ? `<b>الإنذارات</b>${T(['الإنذار', 'المبلغ', 'المهلة', 'التسليم'], ops.notices.map(n => `<tr><td>${LDOC('arrears_notice', n.id, esc(n.number))}<br><span class="muted">${esc(n.kind_label)}</span></td><td>${OMR(n.amount)}</td><td>${fmtDate(n.cure_by)}</td><td>${n.sent_at ? fmtDate(n.sent_at) : W ? `<button class="btn" data-call="EXT.leaSent" data-args="${J([n.id, d.id])}">سُلِّم</button>` : '—'}</td></tr>`))}` : '')
    + (ops.plans.length ? `<b>خطط السداد</b>${T(['الخطة', 'المبلغ', 'المسدَّد', 'الحالة'], ops.plans.map(p => `<tr><td>#${p.id} · ${fmtDate(p.agreed_on)}</td><td>${OMR(p.total)}</td><td>${OMR(p.paid)}</td><td>${pill({active: 'جارية', completed: 'مكتملة', broken: 'متعثرة'}[p.state], {active: 'p-bl', completed: 'p-ok', broken: 'p-b'}[p.state])}</td></tr>`))}` : '')
    + (ops.charity.length ? `<b>تبرعات التأخير (ليست إيرادًا)</b>${T(['المبلغ', 'أيام التأخر', 'الحالة'], ops.charity.map(c => `<tr><td>${OMR(c.amount)}</td><td>${N(c.late_days)}</td><td>${esc({due: 'مستحق', collected: 'محصَّل', disbursed: 'مصروف', waived: 'مُعفى'}[c.status] || c.status)}</td></tr>`))}` : '');
};

EXT.leaRenew = lid => {
  modal(`<h3>تجديد العقد</h3><p class="muted">عقد جديد يبدأ في اليوم التالي لنهاية الحالي ويستمر عليه؛ ينتقل التأمين مع المستأجر ولا يُفوتَر تأمين ثانٍ.</p><label>المدة (شهرًا)</label><input id="rm" inputmode="numeric" value="12"><label>الإيجار السنوي للسنة الأولى (اتركه فارغًا ليبقى آخر إيجار)</label><input id="rr" inputmode="decimal">
   <label>زيادة سنوية (٪)</label><input id="re" inputmode="decimal" value="0"><label>تجهيز مجاني (أيام)</label><input id="rp" inputmode="numeric" value="0"><label><input type="checkbox" id="rs" checked> توقيع العقد الجديد الآن</label>${errBox('rerr')}${goBtns('rgo', 'تجديد')}`);
  $('#rgo').onclick = async () => { try { const r = await post(`/lea/leases/${lid}/renew`, {months: +$('#rm').value, annual_rent: num($('#rr').value), escalation_pct: +$('#re').value, prep_free_days: +$('#rp').value, sign: $('#rs').checked}); closeModal(); toast('جُدِّد العقد'); EXT.cur.lea = 'ls'; EXT.l_lea(); EXT.leaOpen(r.id); } catch (e) { $('#rerr').textContent = e.message; } };
};

EXT.leaTerm = lid => {
  modal(`<h3>إنهاء العقد مبكرًا</h3><p class="muted">تُلغى الدفعات التي تستحق بعد تاريخ الإنهاء (يبقى ما سُدِّد منها)، وتُلغى الشيكات المحفوظة المرتبطة بها.</p><label>تاريخ الإنهاء</label><input id="tt" type="date" value="${tdy()}"><label>السبب (إلزامي)</label><input id="tn"><label><input type="checkbox" id="tp"> احتساب الفترة الجارية بالأيام المستعملة فقط</label>
   ${A_() ? '<label>مبلغ إنهاء متفق عليه (اختياري — قرار مدير)</label><input id="tf" inputmode="decimal" value="0">' : ''}${errBox('terr')}${goBtns('tgo', 'إنهاء العقد')}`);
  $('#tgo').onclick = async () => { try { const r = await post(`/lea/leases/${lid}/terminate`, {on: $('#tt').value, note: $('#tn').value, prorate_last: $('#tp').checked, fee: $('#tf') ? +$('#tf').value : 0}); after(lid, `أُنهي العقد · أُلغيت ${N(r.cancelled_dues)} دفعة (${OMR(r.cancelled_amount)})`); } catch (e) { $('#terr').textContent = e.message; } };
};
EXT.leaEvict = lid => {
  modal(`<h3>إخلاء المستأجر</h3><p class="muted">لا يتم إلا بعد إنذار نهائي انقضت مهلته مع بقاء المتأخرات — قرارك مسجَّل في التدقيق.</p><label>التاريخ</label><input id="et" type="date" value="${tdy()}"><label>مبررات القرار</label><input id="en">${errBox('eerr')}${goBtns('ego', 'تأكيد الإخلاء')}`);
  $('#ego').onclick = async () => { try { await post(`/lea/leases/${lid}/evict`, {on: $('#et').value, note: $('#en').value}); after(lid, 'سُجّل الإخلاء'); } catch (e) { $('#eerr').textContent = e.message; } };
};

EXT.leaHand = async (lid, kind) => {
  const d = await api('/lea/leases/' + lid), U = (await api('/lea/units')).units.find(u => u.id === d.unit_id), ms = U ? U.meters : [];
  modal(`<h3>${kind === 'in' ? 'محضر تسليم العين للمستأجر' : 'محضر استلام العين من المستأجر'}</h3><label>التاريخ</label><input id="hd" type="date" value="${tdy()}"><label>عدد المفاتيح</label><input id="hk" inputmode="numeric">
   <label>حالة العين (سطر لكل بند: البند: الحالة)</label><textarea id="hc" rows="4" placeholder="الجدران: سليمة&#10;المكيفات: تعمل"></textarea>
   ${ms.length ? '<b>قراءات العدّادات</b>' + ms.map(m => `<label>${esc({water: 'ماء', electricity: 'كهرباء', gas: 'غاز', other: 'أخرى'}[m.kind] || m.kind)} ${esc(m.number)}</label><input class="hr" data-m="${m.id}" inputmode="decimal">`).join('') : '<p class="muted">لا عدّادات مسجَّلة لهذه الوحدة (أضفها من تبويب الوحدات).</p>'}
   ${kind === 'out' ? '<label>الخصومات المقترحة من التأمين (سطر لكل خصم: البند | المبلغ | المستند المثبت)</label><textarea id="hx" rows="3" placeholder="إصلاح باب | 50 | فاتورة 114"></textarea>' : ''}<label>ملاحظات</label><input id="hn">${errBox('herr')}${goBtns('hgo', 'حفظ المحضر')}`);
  $('#hgo').onclick = async () => { try {
    const condition = Object.fromEntries(lines($('#hc').value).map(l => { const i = l.indexOf(':'); return i > 0 ? [l.slice(0, i).trim(), l.slice(i + 1).trim()] : [l, '—']; }));
    const readings = [...document.querySelectorAll('.hr')].filter(i => i.value !== '').map(i => ({meter_id: +i.dataset.m, reading: +i.value}));
    const deductions = kind === 'out' ? lines($('#hx').value).map(l => { const p = l.split('|').map(s => s.trim()); return {label: p[0], amount: +p[1], ref: p[2] || ''}; }) : [];
    const r = await post(`/lea/leases/${lid}/handover`, {kind, at: $('#hd').value, keys: num($('#hk').value), condition, readings, deductions, notes: $('#hn').value});
    modal(`<h3>✓ سُجّل المحضر</h3><div class="btns">${LDOC('handover_report', r.id, 'فتح المحضر PDF')} <button class="btn" data-call="closeModal">إغلاق</button></div>`); EXT.leaOpen(lid); } catch (e) { $('#herr').textContent = e.message; } };
};

EXT.leaSettle = async lid => {
  const ops = await api(`/lea/leases/${lid}/ops`), o = ops.deposit, ho = ops.handovers.find(h => h.kind === 'out');
  modal(`<h3>تسوية التأمين</h3><p>التأمين المحصَّل: <b>${OMR(o.basis)}</b> — المردود = التأمين − خصومات موثَّقة بمستند. لا مصادرة تقديرية.</p>
   ${ho && ho.deductions.length ? `<p class="muted">الخصومات المدوَّنة في محضر الاستلام تُطبَّق إن تركت الخانة فارغة:<br>${ho.deductions.map(x => `${esc(x.label)} ${OMR(x.amount)} (${esc(x.ref)})`).join('<br>')}</p>` : ''}
   <label>خصومات جديدة (سطر لكل خصم: البند | المبلغ | المستند | رقم استحقاق متأخر لسداده من التأمين — اختياري)</label><textarea id="sx" rows="3"></textarea>${errBox('serr')}${goBtns('sgo', 'تسوية')}`);
  $('#sgo').onclick = async () => { try {
    const ded = lines($('#sx').value).map(l => { const p = l.split('|').map(s => s.trim()); return {label: p[0], amount: +p[1], ref: p[2] || '', due_id: p[3] ? +p[3] : null}; });
    const r = await post(`/lea/leases/${lid}/deposit/settle`, {deductions: ded.length ? ded : null}); after(lid, `سُوّي التأمين · المردود ${OMR(r.refund)} · الخصومات ${OMR(r.deducted)}`); } catch (e) { $('#serr').textContent = e.message; } };
};

EXT.leaNotice = lid => {
  modal(`<h3>إنذار متأخرات</h3><p class="muted">يصدر برقم متسلسل بمبلغ المتأخرات اليوم. الإنذار النهائي يسبقه إنذار رسمي. الصيغة تنتظر اعتماد المستشار القانوني.</p><label>النوع</label><select id="nk">${Object.entries(NK).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select><label>مهلة السداد (أيام — اتركها فارغة للافتراضي)</label><input id="nd" inputmode="numeric"><label>ملاحظة</label><input id="nn">${errBox('nerr2')}${goBtns('ngo', 'إصدار')}`);
  $('#ngo').onclick = async () => { try { const r = await post(`/lea/leases/${lid}/notices`, {kind: $('#nk').value, cure_days: num($('#nd').value), note: $('#nn').value}); modal(`<h3>✓ صدر الإنذار ${esc(r.number)}</h3><div class="btns">${LDOC('arrears_notice', r.id, 'فتح الإنذار PDF')} <button class="btn" data-call="closeModal">إغلاق</button></div>`); EXT.leaOpen(lid); } catch (e) { $('#nerr2').textContent = e.message; } };
};
EXT.leaSent = async (nid, lid) => { const v = prompt('طريقة التسليم: hand (باليد) / registered (بريد مسجَّل) / email / whatsapp', 'hand'); if (!v) return; await tryDo(() => post(`/lea/notices/${nid}/sent`, {via: v}), 'سُجّل التسليم'); EXT.leaOpen(lid); };

EXT.leaPlan = async lid => {
  const d = await api('/lea/leases/' + lid), late = d.dues.filter(x => x.state === 'late' && x.balance > 0.0005 && x.kind !== 'deposit');
  modal(`<h3>خطة سداد للمتأخرات</h3><p class="muted">يُعاد توزيع المتبقي نفسه على أقساط جديدة — بلا فوائد ولا رسوم؛ ومجموع الأقساط يساوي المتبقي تمامًا. تحتاج اعتماد المدير.</p>
   ${late.map(x => `<label><input type="checkbox" class="pd" value="${x.id}" data-b="${x.balance}" checked> ${fmtDate(x.due)} — ${OMR(x.balance)}</label>`).join('')}
   <div class="g2"><div><label>عدد الأقساط</label><input id="pc" inputmode="numeric" value="3"></div><div><label>تاريخ أول قسط</label><input id="pf" type="date" value="${tdy()}"></div></div><label>ملاحظة</label><input id="pn2"><div id="ppv" class="muted"></div>${errBox('perr')}${goBtns('pgo', 'اعتماد الخطة')}`);
  const build = () => { const ids = [...document.querySelectorAll('.pd:checked')], tot = Math.round(ids.reduce((s, i) => s + +i.dataset.b, 0) * 1000), n = Math.max(1, +$('#pc').value || 1), base = Math.floor(tot / n), out = [];
    for (let i = 0; i < n; i++) { const dt_ = new Date($('#pf').value || tdy()); dt_.setMonth(dt_.getMonth() + i); out.push({due: dt_.toISOString().slice(0, 10), amount: (i === n - 1 ? tot - base * (n - 1) : base) / 1000}); } return {ids: ids.map(i => +i.value), inst: out, tot: tot / 1000}; };
  const show = () => { const b = build(); $('#ppv').textContent = `المجموع ${OMR(b.tot)} على ${b.inst.length} قسط، أولها ${OMR(b.inst[0].amount)}`; };
  $$('.pd, #pc, #pf').forEach(e => e.onchange = show); show();
  $('#pgo').onclick = async () => { try { const b = build(); await post(`/lea/leases/${lid}/plans`, {due_ids: b.ids, installments: b.inst, note: $('#pn2').value}); after(lid, 'اعتُمدت خطة السداد'); } catch (e) { $('#perr').textContent = e.message; } };
};

/* المتأخرات والتبرعات والخطط */
EXT.leaArrearsTab = async B => {
  const [ag, N_, P, C] = await Promise.all([api('/lea/aging'), api('/lea/notices'), api('/lea/plans'), api('/lea/charity')]);
  B.innerHTML = BOX('العقود المتأخرة', T(['العقد', 'الوحدة', 'المستأجر', 'المتأخر', 'أقدم تأخير'], ag.leases.map(x => `<tr data-id="${x.lease_id}"><td><span class="num">${esc(x.number)}</span></td><td>${esc(x.unit)}</td><td>${esc(x.tenant)}</td><td>${pill(OMR(x.amount), 'p-b')}</td><td>${N(x.oldest_days)} يومًا</td></tr>`), 'لا متأخرات.'))
    + BOX('الإنذارات الصادرة', T(['الإنذار', 'العقد', 'المستأجر', 'المبلغ', 'المهلة', 'الحالة', ''], N_.map(n => `<tr><td><span class="num">${esc(n.number)}</span><br><span class="muted">${esc(n.kind_label)}</span></td><td>${esc(n.lease_no)}<br><span class="muted">${esc(n.unit)}</span></td><td>${esc(n.tenant)}</td><td>${OMR(n.amount)}</td><td>${fmtDate(n.cure_by)}</td><td>${pill({cured: 'سُدِّد', expired: 'انقضت المهلة', running: 'جارية'}[n.state], {cured: 'p-ok', expired: 'p-b', running: 'p-w'}[n.state])}</td><td>${LDOC('arrears_notice', n.id, 'PDF')}</td></tr>`), 'لا إنذارات.'))
    + BOX('خطط السداد', T(['الخطة', 'العقد', 'المستأجر', 'المبلغ', 'المسدَّد', 'الحالة'], P.map(p => `<tr><td>#${p.id}<br><span class="muted">${fmtDate(p.agreed_on)}</span></td><td>${esc(p.lease_no)}<br><span class="muted">${esc(p.unit)}</span></td><td>${esc(p.tenant)}</td><td>${OMR(p.total)}</td><td>${OMR(p.paid)}</td><td>${pill({active: 'جارية', completed: 'مكتملة', broken: 'متعثرة'}[p.state], {active: 'p-bl', completed: 'p-ok', broken: 'p-b'}[p.state])}</td></tr>`), 'لا خطط.'))
    + BOX('تبرعات التأخير (التزام تعاقدي — ليست إيرادًا)', `<p class="muted">${esc(C.note)}</p>` + KP([['مستحقة', OMR(C.totals.due)], ['محصَّلة', OMR(C.totals.collected)], ['مصروفة', OMR(C.totals.disbursed)]])
      + T(['العقد', 'المستأجر', 'المبلغ', 'أيام التأخر', 'الحالة', ''], C.items.map(c => `<tr><td>${esc(c.lease_no)}<br><span class="muted">${esc(c.unit)}</span></td><td>${esc(c.tenant)}</td><td>${OMR(c.amount)}</td><td>${N(c.late_days)}</td><td>${esc({due: 'مستحق', collected: 'محصَّل', disbursed: 'مصروف', waived: 'مُعفى'}[c.status] || c.status)}</td><td>${c.status === 'due' && can('leasing') && c.amount > 0 ? `<button class="btn" data-call="EXT.leaCharity" data-args="${J([c.id, 'collect'])}">تحصيل</button>` : ''}${c.status === 'collected' && A_() ? `<button class="btn" data-call="EXT.leaCharity" data-args="${J([c.id, 'disburse'])}">صرف للجهة الخيرية</button>` : ''}</td></tr>`), 'لا تبرعات.'));
  $$('#leaB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.leaOpen(+tr.dataset.id); });
};
EXT.leaCharity = async (id, act) => {
  const reference = prompt(act === 'collect' ? 'مرجع التحصيل (رقم الإيصال/الحوالة):' : 'مرجع الصرف:'); if (!reference) return;
  const beneficiary = act === 'disburse' ? prompt('الجهة الخيرية المستفيدة:') : ''; if (act === 'disburse' && !beneficiary) return;
  await tryDo(() => post(`/lea/charity/${id}/${act}`, {reference, beneficiary: beneficiary || ''}), 'تم'); EXT.l_lea();
};

/* الصيانة والمصاريف */
EXT.leaMaintTab = async B => {
  const [M, E, V] = await Promise.all([api('/lea/maint'), api('/lea/expenses'), api('/lea/vendors')]), W = can('leasing');
  B.innerHTML = BOX('طلبات الصيانة', T(['الطلب', 'الوحدة', 'الأولوية', 'الحالة', 'المهلة', 'أوامر العمل', ''], M.map(m => `<tr><td>#${m.id} · ${esc(m.category || '')}<br><span class="muted">${esc((m.description || '').slice(0, 60))}</span></td><td>${esc(m.unit)}</td><td>${esc(m.priority_label)}</td><td>${pill(esc(m.status_label), m.late ? 'p-b' : 'p-w')}</td><td>${fmtDate(m.sla_due)}${m.late ? ' ' + pill('متأخر', 'p-b') : ''}</td>
      <td>${m.orders.map(o => `${esc(o.vendor || 'بلا مورّد')} · ${OMR(o.cost)} · ${esc(o.charge_label)}${o.done_at ? ' ✓' : W ? ` <button class="btn" data-call="EXT.leaDone" data-args="${J([o.id, o.cost])}">إنجاز</button>` : ''}`).join('<br>') || '—'}</td>
      <td>${W && !['done', 'closed', 'rejected'].includes(m.status) ? `<button class="btn" data-call="EXT.leaOrder" data-args="${J([m.id])}">أمر عمل</button>` : ''}${W && m.status === 'done' ? `<button class="btn" data-call="EXT.leaMaintSt" data-args="${J([m.id, 'closed'])}">إغلاق</button>` : ''}${W && m.status === 'new' ? `<button class="btn" data-call="EXT.leaMaintSt" data-args="${J([m.id, 'rejected'])}">رفض</button>` : ''}</td></tr>`), 'لا طلبات.'),
      W ? '<button class="btn p" data-call="EXT.leaMaintForm">+ طلب صيانة</button> <button class="btn" data-call="EXT.leaVendorForm">+ مورّد</button>' : '')
    + BOX('المصاريف', T(['التاريخ', 'الوحدة', 'البند', 'المبلغ', 'على', 'المورّد'], E.map(e => `<tr><td>${fmtDate(e.spent_on)}</td><td>${esc(e.unit || '—')}</td><td>${esc(e.category)}<br><span class="muted">${esc(e.description || '')}</span></td><td>${OMR(e.amount)}</td><td>${e.charge_owner ? (e.charge_tenant ? 'المالك (يُسترد من المستأجر)' : 'المالك') : 'الشركة'}</td><td>${esc(e.vendor || '—')}</td></tr>`), 'لا مصاريف.'),
      W ? '<button class="btn p" data-call="EXT.leaExpenseForm">+ مصروف</button>' : '')
    + BOX('الموردون', T(['المورّد', 'التخصص', 'الهاتف', 'الآيبان'], V.map(v => `<tr><td>${esc(v.name)}</td><td>${esc(v.trade || '—')}</td><td>${esc(v.phone || '—')}</td><td><span class="num">${esc(v.iban || '—')}</span></td></tr>`), 'لا موردين.'));
};
EXT.leaMaintSt = async (id, st) => { const note = st === 'rejected' ? prompt('سبب الرفض:') : ''; if (st === 'rejected' && !note) return; await tryDo(() => post(`/lea/maint/${id}/status`, {status: st, note: note || ''}), 'تم'); EXT.l_lea(); };
EXT.leaMaintForm = async () => {
  const U = (await api('/lea/units')).units;
  modal(`<h3>طلب صيانة</h3><label>الوحدة</label><select id="mu">${U.map(u => `<option value="${u.id}">${esc(u.code)}${u.lease ? ' · ' + esc(u.lease.tenant) : ''}</option>`).join('')}</select><label>التصنيف</label><input id="mc" placeholder="تكييف / سباكة / كهرباء …"><label>الوصف</label><input id="md"><label>الأولوية</label><select id="mp"><option value="normal">عادي</option><option value="urgent">عاجل (يوم)</option><option value="high">مرتفع (3 أيام)</option><option value="low">منخفض (14 يومًا)</option></select><label>مصدر الطلب</label><select id="ms"><option value="staff">الموظف</option><option value="tenant">المستأجر</option></select>${errBox('merr')}${goBtns('mgo', 'تسجيل')}`);
  $('#mgo').onclick = async () => { try { await post('/lea/maint', {unit_id: +$('#mu').value, category: $('#mc').value, description: $('#md').value, priority: $('#mp').value, source: $('#ms').value}); after(0, 'سُجّل الطلب'); } catch (e) { $('#merr').textContent = e.message; } };
};
EXT.leaOrder = async mid => {
  const V = await api('/lea/vendors');
  modal(`<h3>أمر عمل</h3><label>المورّد</label><select id="ov"><option value="">—</option>${V.map(v => `<option value="${v.id}">${esc(v.name)}</option>`).join('')}</select><label>التكلفة المتوقعة (ر.ع)</label><input id="oc" inputmode="decimal" value="0"><label>التحميل</label><select id="ot"><option value="owner">على المالك</option><option value="company">على الشركة</option><option value="tenant">على المستأجر (يُسترد منه)</option></select><label>سند التحميل على المستأجر (بند العقد / محضر المعاينة)</label><input id="ob2">${errBox('oerr')}${goBtns('ogo2', 'إصدار الأمر')}`);
  $('#ogo2').onclick = async () => { try { await post(`/lea/maint/${mid}/orders`, {vendor_id: num($('#ov').value), cost: +$('#oc').value, charge_to: $('#ot').value, basis: $('#ob2').value}); after(0, 'صدر أمر العمل'); } catch (e) { $('#oerr').textContent = e.message; } };
};
EXT.leaDone = (oid, cost) => {
  modal(`<h3>إنجاز أمر العمل</h3><p class="muted">يُقيَّد المصروف، وإن كان على المستأجر يُفوتَر استحقاقًا (يحتاج اعتماد المدير).</p><label>التكلفة الفعلية (ر.ع)</label><input id="dc" inputmode="decimal" value="${cost || ''}"><label>مرجع المستند (فاتورة المورّد)</label><input id="dr">${errBox('derr')}${goBtns('dgo', 'إنجاز')}`);
  $('#dgo').onclick = async () => { try { await post(`/lea/maint/orders/${oid}/done`, {cost: num($('#dc').value), doc_ref: $('#dr').value}); after(0, 'أُنجز الأمر وقُيّد المصروف'); } catch (e) { $('#derr').textContent = e.message; } };
};
EXT.leaVendorForm = () => {
  modal(`<h3>مورّد جديد</h3><label>الاسم</label><input id="vn"><label>التخصص</label><input id="vt"><label>الهاتف</label><input id="vp"><label>الآيبان</label><input id="vi">${errBox('verr')}${goBtns('vgo', 'حفظ')}`);
  $('#vgo').onclick = async () => { try { await post('/lea/vendors', {name: $('#vn').value, trade: $('#vt').value, phone: $('#vp').value, iban: $('#vi').value}); after(0, 'أُضيف المورّد'); } catch (e) { $('#verr').textContent = e.message; } };
};
EXT.leaExpenseForm = async () => {
  const U = (await api('/lea/units')).units;
  modal(`<h3>مصروف عقار</h3><label>الوحدة</label><select id="xu">${U.map(u => `<option value="${u.id}">${esc(u.code)}</option>`).join('')}</select><label>البند</label><input id="xc"><label>المبلغ (ر.ع)</label><input id="xa" inputmode="decimal"><label>التاريخ</label><input id="xd" type="date" value="${tdy()}"><label><input type="checkbox" id="xo" checked> يُحمَّل على المالك (وإلا فهو على الشركة)</label><label>المستند</label><input id="xr">${errBox('xerr')}${goBtns('xgo', 'قيد المصروف')}`);
  $('#xgo').onclick = async () => { try { await post('/lea/expenses', {unit_id: +$('#xu').value, category: $('#xc').value, amount: +$('#xa').value, spent_on: $('#xd').value, charge_owner: $('#xo').checked, doc_ref: $('#xr').value}); after(0, 'قُيّد المصروف'); } catch (e) { $('#xerr').textContent = e.message; } };
};

/* الملاك وكشوفهم */
EXT.leaOwnersTab = async B => {
  const O = await api('/lea/owners'), W = can('leasing');
  B.innerHTML = BOX('الملاك', T(['المالك', 'النوع', 'الهاتف', 'الهوية', 'عمولة الإدارة', 'وحدات', ''], O.map(o => `<tr><td><b>${esc(o.name)}</b></td><td>${o.kind === 'own' ? 'الشركة (مملوك)' : 'مالك آخر'}</td><td>${esc(o.phone || '—')}</td><td><span class="num">${esc(o.id_number || '—')}</span></td><td>${o.kind === 'own' ? '—' : pct(o.mgmt_fee_pct) + ' من ' + (o.mgmt_basis === 'collected' ? 'المحصَّل' : 'المفوتَر')}</td><td>${N(o.units)}</td><td><button class="btn" data-call="EXT.leaOwnerStmt" data-args="${J([o.id, o.name])}">كشف شهري</button></td></tr>`)),
    W ? '<button class="btn p" data-call="EXT.leaOwnerForm">+ مالك</button>' : '');
  if (A_()) { const S_ = await api('/lea/scopes'); B.insertAdjacentHTML('beforeend', BOX('نطاق المديرين العقاريين الخارجيين', `<p class="muted">المدير العقاري يرى ويحصّل داخل نطاقه فقط (مشروع و/أو مالك). أنشئ حسابه من «الإدارة ← المستخدمون» بدور «مدير عقاري».</p>` + T(['المستخدم', 'المشروع', 'المالك', ''], S_.map(s => `<tr><td>${esc(s.user)} <span class="muted">${esc(s.username)}</span></td><td>${esc(s.project || 'كل المشاريع')}</td><td>${esc(s.owner || 'كل الملاك')}</td><td><button class="btn" data-call="EXT.leaScopeDel" data-args="${J([s.id])}">إلغاء</button></td></tr>`), 'لا نطاقات.'), '<button class="btn p" data-call="EXT.leaScopeForm">+ نطاق</button>')); }
};
EXT.leaScopeDel = async id => { await tryDo(() => api('/lea/scopes/' + id, {method: 'DELETE'}), 'أُلغي النطاق'); EXT.l_lea(); };
EXT.leaScopeForm = async () => {
  const [us, O, P] = await Promise.all([api('/users'), api('/lea/owners'), api('/projects')]);
  modal(`<h3>نطاق مدير عقاري</h3><label>المستخدم</label><select id="su">${us.filter(u => u.role === 'property_manager').map(u => `<option value="${u.id}">${esc(u.name)} (${esc(u.username)})</option>`).join('')}</select><label>المشروع (اختياري)</label><select id="sp"><option value="">كل المشاريع</option>${P.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select><label>المالك (اختياري)</label><select id="so"><option value="">كل الملاك</option>${O.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('')}</select><p class="muted">يلزم اختيار مشروع أو مالك على الأقل.</p>${errBox('scerr')}${goBtns('scgo', 'حفظ')}`);
  $('#scgo').onclick = async () => { try { await post('/lea/scopes', {user_id: +$('#su').value, project_id: num($('#sp').value), owner_id: num($('#so').value)}); after(0, 'حُفظ النطاق'); } catch (e) { $('#scerr').textContent = e.message; } };
};
EXT.leaOwnerStmt = async (oid, name, period) => {
  period = period || tdy().slice(0, 7);
  const s = await api(`/lea/owners/${oid}/statement?period=${period}`);
  modal(`<h3>كشف ${esc(name)}</h3><label>الشهر</label><input id="sm" type="month" value="${period}">
   ${KP([['المحصَّل', OMR(s.collected)], ['المصاريف', OMR(s.expenses)], ['العمولة ' + pct(s.owner.pct), OMR(s.commission)], ['الصافي', OMR(s.net)]])}
   <p class="muted">الصافي = المحصَّل − المصاريف المحمَّلة على المالك − عمولة الإدارة. الودائع لا تدخل.</p>
   ${T(['الوحدة', 'المستأجر', 'المحصَّل'], s.units.map(u => `<tr><td>${esc(u.unit)}</td><td>${esc(u.tenant)}</td><td>${OMR(u.collected)}</td></tr>`), 'لا تحصيل في هذا الشهر.')}
   ${s.issued.length ? '<b>الكشوف الصادرة</b>' + T(['الكشف', 'الصافي', 'الحالة', ''], s.issued.map(x => `<tr><td>${LDOC('owner_statement', x.id, esc(x.number))}${x.kind === 'adjustment' ? ' <span class="muted">(تعديلي)</span>' : ''}</td><td>${OMR(x.net)}</td><td>${x.status === 'transferred' ? pill('حُوِّل', 'p-ok') : 'صادر'}</td><td>${x.status === 'issued' && x.net > 0 && A_() ? `<button class="btn" data-call="EXT.leaTransfer" data-args="${J([x.id, oid, name, period])}">تسجيل التحويل</button>` : ''}</td></tr>`)) : ''}
   ${errBox('smerr')}<div class="btns" style="margin-top:12px">${A_() ? '<button class="btn p" id="smgo">إصدار الكشف</button>' : ''} <button class="btn" data-call="closeModal">إغلاق</button></div>`);
  $('#sm').onchange = e => EXT.leaOwnerStmt(oid, name, e.target.value);
  if ($('#smgo')) $('#smgo').onclick = async () => { try { await post(`/lea/owners/${oid}/statements`, {period}); toast('صدر الكشف'); EXT.leaOwnerStmt(oid, name, period); } catch (e) { $('#smerr').textContent = e.message; } };
};
EXT.leaTransfer = async (sid, oid, name, period) => { const ref = prompt('مرجع تحويل الصافي للمالك:'); if (!ref) return; await tryDo(() => post(`/lea/statements/${sid}/transferred`, {ref}), 'سُجّل التحويل'); EXT.leaOwnerStmt(oid, name, period); };

/* الاستيراد */
EXT.leaImportTab = async B => {
  const kinds = [['units', 'الوحدات'], ['tenants', 'المستأجرون'], ['leases', 'العقود'], ['payments', 'المدفوعات'], ['cheques', 'الشيكات']], bt = await api('/lea/import/batches');
  B.innerHTML = BOX('استيراد من Excel / CSV', `<p class="muted">الترتيب: الوحدات ← المستأجرون ← العقود ← المدفوعات والشيكات. الفحص المسبق لا يكتب شيئًا؛ ولا يُنفَّذ الاستيراد إلا بعد تأكيدك. الصيغ ممنوعة؛ 5000 صف و5 ميغابايت كحد أقصى. لا يُعدَّل ما أُدخل يدويًا — التعارض يُبلَّغ ولا يُطبَّق.</p>
    <div class="toolbar"><select id="ik">${kinds.map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select> <a class="btn" id="itpl" href="/api/lea/import/units/template.xlsx">تنزيل القالب</a> <input type="file" id="if" accept=".xlsx,.csv"> <button class="btn p" id="idry">فحص مسبق</button></div><div id="irep"></div>`)
    + BOX('الدفعات المنفَّذة', T(['#', 'النوع', 'الملف', 'جديد/محدَّث', 'تعارض', 'بواسطة', 'الوقت'], bt.map(x => `<tr><td>${x.id}</td><td>${esc(x.kind)}</td><td>${esc(x.filename || '')}</td><td>${N(x.rows_ok)}</td><td>${N(x.rows_conflict)}</td><td>${esc(x.by_user || '')}</td><td>${esc((x.at || '').slice(0, 16).replace('T', ' '))}</td></tr>`), 'لا دفعات.'));
  $('#ik').onchange = e => { $('#itpl').href = `/api/lea/import/${e.target.value}/template.xlsx`; };
  const send = async (confirm) => {
    const f = $('#if').files[0]; if (!f) { toast('اختر ملفًا', 1); return null; }
    const fd = new FormData(); fd.append('file', f); if (confirm) fd.append('confirm', confirm);
    const r = await fetch(`/api/lea/import/${$('#ik').value}`, {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}), j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر الاستيراد'); return j;
  };
  const show = j => {
    const c = j.counts; $('#irep').innerHTML = `<hr style="border:0;border-top:1px solid var(--line);margin:12px 0">${KP([['صفوف', N(j.rows)], ['جديدة', N(c.insert)], ['محدَّثة', N(c.update)], ['متجاوَزة (موجودة)', N(c.skip)], ['تعارض', N(c.conflict)], ['أخطاء', N(j.errors.length)]])}
      ${j.committed ? `<p>${pill('✓ نُفِّذ — الدفعة ' + j.batch, 'p-ok')}</p>` : j.mode === 'blocked' ? `<p>${pill('لم يُنفَّذ: أصلح الأخطاء أولًا', 'p-b')}</p>` : ''}
      ${j.errors.length ? '<b>الأخطاء</b>' + T(['الصف', 'العمود', 'السبب'], j.errors.slice(0, 100).map(e => `<tr><td>${e.row}</td><td>${esc(e.col)}</td><td>${esc(e.reason)}</td></tr>`)) : ''}
      ${j.conflicts.length ? '<b>تعارضات (لم تُطبَّق)</b>' + T(['الصف', 'السبب'], j.conflicts.slice(0, 100).map(e => `<tr><td>${e.row}</td><td>${esc(e.reason)}</td></tr>`)) : ''}
      ${!j.committed && !j.errors.length ? `<div class="btns" style="margin-top:10px"><button class="btn p" id="icommit">تنفيذ الاستيراد (${N(c.insert + c.update)} صف)</button></div>` : ''}`;
    if ($('#icommit')) $('#icommit').onclick = async () => { try { const r = await send(j.sha256); show(r); if (r.committed) toast('تم الاستيراد'); } catch (e) { toast(e.message, 1); } };
  };
  $('#idry').onclick = async () => { try { const j = await send(''); if (j) show(j); } catch (e) { toast(e.message, 1); } };
};

/* ================================================================ المدير العقاري الخارجي (/api/pm) */
EXT.l_pm = async function () {
  const k = this.cur.pm, el = $('#pmg');
  const tabs = [['ls', 'عقودي'], ['ag', 'المتأخرات'], ['ex', 'تنتهي قريبًا'], ['vc', 'الشاغر'], ['mt', 'الصيانة']];
  const o = await api('/pm/overview');
  el.innerHTML = KP([['وحدات في نطاقك', N(o.units)], ['مؤجَّرة', N(o.leased)], ['شاغرة', N(o.vacant)], ['المتأخرات', OMR(o.arrears)], ['محصَّل هذا الشهر', OMR(o.collected_month)]]) + SUB0('pm', tabs, k) + '<div id="pmB">…</div>';
  const B = $('#pmB');
  if (k === 'ls') {
    const L = await api('/pm/leases');
    B.innerHTML = BOX('عقودك', T(['العقد', 'الوحدة', 'المستأجر', 'الهاتف', 'المتأخر'], L.map(l => `<tr data-id="${l.id}"><td><span class="num">${esc(l.number)}</span></td><td>${esc(l.unit)}</td><td>${esc(l.tenant)}</td><td>${esc(l.phone || '—')}</td><td>${l.arrears ? pill(OMR(l.arrears), 'p-b') : pill('لا متأخر', 'p-ok')}</td></tr>`), 'لا عقود في نطاقك.'));
    $$('#pmB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.pmOpen(+tr.dataset.id); });
  } else if (k === 'ag') {
    const a = await api('/pm/aging');
    B.innerHTML = KP([['إجمالي المتأخر', OMR(a.total)]].concat(a.buckets.map(b => [b.label, OMR(b.amount), N(b.count) + ' دفعة'])))
      + BOX('بحسب العقد', T(['العقد', 'الوحدة', 'المستأجر', 'الهاتف', 'المتأخر', 'أقدم تأخير'], a.leases.map(l => `<tr data-id="${l.lease_id}"><td><span class="num">${esc(l.number)}</span></td><td>${esc(l.unit)}</td><td>${esc(l.tenant)}</td><td>${esc(l.phone || '—')}</td><td>${OMR(l.amount)}</td><td>${N(l.oldest_days)} يومًا</td></tr>`), 'لا متأخرات في نطاقك.'));
    $$('#pmB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.pmOpen(+tr.dataset.id); });
  } else if (k === 'ex') {
    const x = await api('/pm/expiring');
    B.innerHTML = BOX('عقود تنتهي خلال 90 يومًا', T(['العقد', 'الوحدة', 'المستأجر', 'الهاتف', 'تنتهي', 'المتبقي'], x.map(l => `<tr data-id="${l.id}"><td><span class="num">${esc(l.number)}</span></td><td>${esc(l.unit)}</td><td>${esc(l.tenant)}</td><td>${esc(l.phone || '—')}</td><td>${fmtDate(l.end)}</td><td>${pill(N(l.days_left) + ' يومًا', l.days_left <= 30 ? 'p-b' : 'p-w')}</td></tr>`), 'لا عقود تنتهي قريبًا.'));
    $$('#pmB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.pmOpen(+tr.dataset.id); });
  } else if (k === 'vc') {
    const v = await api('/pm/vacant');
    B.innerHTML = BOX('وحدات شاغرة في نطاقك', T(['الوحدة', 'النوع', 'المساحة', 'العقار', 'شاغرة منذ'], v.map(u => `<tr><td><span class="num">${esc(u.code)}</span></td><td>${esc(u.type || '—')}</td><td>${u.area ? N(u.area) + ' م²' : '—'}</td><td>${esc(u.project)}</td><td>${u.vacant_since ? fmtDate(u.vacant_since) : '—'}</td></tr>`), 'لا وحدات شاغرة.'));
  } else if (k === 'mt') {
    const m = await api('/pm/maint');
    B.innerHTML = BOX('طلبات الصيانة في نطاقك', T(['الوحدة', 'الفئة', 'الوصف', 'الأولوية', 'الحال', 'الموعد'], m.map(r => `<tr><td>${esc(r.unit)}</td><td>${esc(r.category)}</td><td>${esc(r.description)}</td><td>${esc(r.priority_label)}</td><td>${pill(esc(r.status_label), r.late ? 'p-b' : 'p-bl')}</td><td>${r.sla_due ? fmtDate(r.sla_due) : '—'}${r.late ? ' ' + pill('متأخر', 'p-b') : ''}</td></tr>`), 'لا طلبات.'));
  }
};
EXT.pmOpen = async id => {
  const d = await api('/pm/leases/' + id);
  insp(`${d.number} · ${d.unit}`, `<h3>${esc(d.tenant.name)}</h3><p class="muted">${esc(d.tenant.phone || '')}</p><dl class="kv"><dt>الفترة</dt><dd>${fmtDate(d.start)} ← ${fmtDate(d.end)}</dd><dt>الرصيد</dt><dd>مستحق ${OMR(d.totals.billed)} · مسدد ${OMR(d.totals.paid)} · متأخر ${d.totals.arrears ? pill(OMR(d.totals.arrears), 'p-b') : '—'}</dd></dl>
   <div class="btns" style="margin:10px 0"><button class="btn p" data-call="EXT.pmPay" data-args="${J([d.id, d.totals.balance])}">تسجيل مبلغ استلمته</button></div>
   <b>الدفعات</b>${T(['الاستحقاق', 'المبلغ', 'المسدد', 'الحالة'], d.dues.map(x => `<tr><td>${fmtDate(x.due)}</td><td>${OMR(x.amount)}</td><td>${OMR(x.paid)}</td><td>${x.state === 'paid' ? pill('مسدد', 'p-ok') : x.state === 'late' ? pill('متأخر', 'p-b') : pill('قادم', 'p-bl')}</td></tr>`))}
   <b>حركات التحصيل</b>${T(['الإيصال', 'التاريخ', 'المبلغ', 'الطريقة'], d.payments.map(p => `<tr><td>${esc(p.receipt_no || '—')}</td><td>${fmtDate(p.paid_on)}</td><td>${OMR(p.amount)}</td><td>${esc(LMETH[p.method] || 'غير موثَّقة')}</td></tr>`), 'لا حركات.')}`);
};
EXT.pmPay = (lid, bal) => {
  modal(`<h3>تسجيل مبلغ استلمته</h3><p class="muted">الشيكات لا تُسجَّل هنا؛ تسلّمها للمكتب فيدير دورتها (إيداع ثم صرف).</p><label>المبلغ (ر.ع) — المتبقي ${OMR(bal)}</label><input id="mpa" inputmode="decimal"><label>طريقة السداد</label><select id="mpm"><option value="cash">نقدًا</option><option value="transfer">تحويل بنكي</option><option value="card">بطاقة</option><option value="other">أخرى</option></select><label>تاريخ الاستلام</label><input id="mpd" type="date" max="${tdy()}" value="${tdy()}"><label>المرجع</label><input id="mpr">${errBox('mpe')}${goBtns('mpgo', 'تسجيل')}`);
  $('#mpgo').onclick = async () => { try { const r = await post('/pm/payments', {lease_id: lid, amount: +$('#mpa').value, method: $('#mpm').value, paid_on: $('#mpd').value, reference: $('#mpr').value}); closeModal(); toast(`سُجّل · الإيصال ${r.receipt_no}`); EXT.l_pm(); EXT.pmOpen(lid); } catch (e) { $('#mpe').textContent = e.message; } };
};

/* ================================================================ بوابة المستأجر (0.28.0) — /api/lessee: ملفّه وحده */
const LP_DUE = {paid: ['مسدد', 'p-ok'], late: ['متأخر', 'p-b'], upcoming: ['قادم', 'p-bl']};
const LP_CHQ = {held: 'لدى المكتب', deposited: 'مودَع', cleared: 'صُرف', bounced: 'مرتجع', returned: 'أُعيد إليك'};
const lpPdf = (href, label) => href ? `<a class="btn" href="${href}" target="_blank" rel="noopener">${label}</a>` : '—';
EXT.l_lp = async function () {
  const k = this.cur.lp, el = $('#lp');
  const tabs = [['ls', 'عقودي'], ['st', 'كشف حسابي'], ['nt', 'الإنذارات'], ['mt', 'الصيانة']];
  const me = await api('/lessee/me');
  const consent = me.consent_required ? `<div class="ai"><b class="k">إشعار الخصوصية:</b> نحفظ بيانات عقودك ومدفوعاتك لتنفيذ عقد الإيجار ولا نستعملها لغير ذلك. <a href="/privacy" target="_blank" rel="noopener">اقرأ الإشعار</a> ثم أقرّ به. <button class="btn p" data-call="EXT.lpConsent" data-args="${J([me.consent_required])}">أقرّ بقراءته</button></div>` : '';
  el.innerHTML = KP([['المستأجر', esc(me.name)], ['عقودي', N(me.leases)], ['الرصيد المتبقي', OMR(me.balance)], ['المتأخر', me.arrears ? `<span style="color:var(--bad)">${OMR(me.arrears)}</span>` : 'لا متأخرات']]) + consent + SUB0('lp', tabs, k) + '<div id="lpB">…</div>';
  const B = $('#lpB');
  if (k === 'ls') {
    const L = await api('/lessee/leases');
    B.innerHTML = BOX('عقودي', T(['العقد', 'الوحدة', 'الفترة', 'الحالة', 'الإيجار السنوي', 'الدفعة القادمة', 'المتأخر'], L.map(l => `<tr data-id="${l.id}"><td><span class="num">${esc(l.number)}</span></td><td>${esc(l.unit)} · ${esc(l.project)}</td><td>${fmtDate(l.start)} ← ${fmtDate(l.end)}</td><td>${pill(esc(l.status_label), l.status === 'active' ? 'p-ok' : 'p-w')}</td><td>${OMR(l.annual_rent)}</td><td>${l.next_due ? `${fmtDate(l.next_due.due)} · ${OMR(l.next_due.amount)}` : '—'}</td><td>${l.arrears ? pill(OMR(l.arrears), 'p-b') : '—'}</td></tr>`), 'لا عقود.'));
    $$('#lpB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.lpOpen(+tr.dataset.id); });
  } else if (k === 'st') {
    const s = await api('/lessee/statement');
    B.innerHTML = s.leases.map(l => BOX(`${esc(l.number)} · ${esc(l.unit)}`, T(['التاريخ', 'البيان', 'مدين', 'دائن'], l.entries.map(e => `<tr><td>${fmtDate(e.date)}</td><td>${esc(e.label)}</td><td>${e.debit ? OMR(e.debit) : ''}</td><td>${e.credit ? OMR(e.credit) : ''}</td></tr>`), 'لا حركات.'), `<span class="muted">الرصيد ${OMR(l.totals.balance)}</span>`)).join('') + `<p><b>الرصيد الإجمالي: ${OMR(s.balance)}</b></p>`;
  } else if (k === 'nt') {
    const n = await api('/lessee/notices');
    B.innerHTML = BOX('الإنذارات المُسلَّمة إليك', T(['الرقم', 'النوع', 'العقد', 'التاريخ', 'مهلة السداد', 'المبلغ', ''], n.map(x => `<tr><td><span class="num">${esc(x.number)}</span></td><td>${esc(x.kind_label)}</td><td>${esc(x.lease_no)}</td><td>${fmtDate(x.issued)}</td><td>${fmtDate(x.cure_by)}</td><td>${OMR(x.amount)}</td><td>${lpPdf(x.pdf, 'نسخة PDF')}</td></tr>`), 'لا إنذارات.'));
  } else if (k === 'mt') {
    const m = await api('/lessee/maintenance');
    B.innerHTML = BOX('طلبات الصيانة', T(['الوحدة', 'الفئة', 'الوصف', 'الحال', 'الموعد المستهدف', 'قُدّم'], m.map(r => `<tr><td>${esc(r.unit)}</td><td>${esc(r.category)}</td><td>${esc(r.description)}</td><td>${pill(esc(r.status_label), r.status === 'done' || r.status === 'closed' ? 'p-ok' : 'p-bl')}</td><td>${r.sla_due ? fmtDate(r.sla_due) : '—'}</td><td>${fmtDate(r.created)}</td></tr>`), 'لا طلبات.'), '<button class="btn p" data-call="EXT.lpMaintForm">+ طلب صيانة</button>');
  }
};
EXT.lpOpen = async id => {
  const d = await api('/lessee/leases/' + id);
  insp(`${d.number} · ${d.unit}`, `<dl class="kv"><dt>الحالة</dt><dd>${esc(d.status_label)}</dd><dt>الفترة</dt><dd>${fmtDate(d.start)} ← ${fmtDate(d.end)}</dd><dt>الإيجار السنوي</dt><dd>${OMR(d.annual_rent)}</dd><dt>التأمين</dt><dd>${OMR(d.deposit)}</dd><dt>العقار</dt><dd>${esc(d.project)}</dd><dt>الرصيد</dt><dd>مستحق ${OMR(d.totals.billed)} · مسدد ${OMR(d.totals.paid)} · متبقٍ ${OMR(d.totals.balance)}</dd></dl>
   <div class="btns" style="margin:10px 0">${lpPdf(d.pdf, 'عقد الإيجار (PDF)')} ${d.status === 'active' ? `<button class="btn p" data-call="EXT.lpMaintForm" data-args="${J([d.id])}">طلب صيانة</button>` : ''}</div>
   <b>الدفعات</b>${T(['الاستحقاق', 'البيان', 'المبلغ', 'المسدد', 'الحالة'], d.dues.map(x => `<tr><td>${fmtDate(x.due)}</td><td>${esc(x.label || (x.kind === 'deposit' ? 'تأمين' : 'إيجار'))}</td><td>${OMR(x.amount)}</td><td>${OMR(x.paid)}</td><td>${pill(...LP_DUE[x.state])}${x.cheque ? ' <small class="muted">شيك ' + esc(x.cheque.number) + '</small>' : ''}</td></tr>`))}
   <b>الإيصالات</b>${T(['الإيصال', 'التاريخ', 'المبلغ', 'الطريقة', ''], d.payments.map(p => `<tr><td>${esc(p.receipt_no || '—')}</td><td>${fmtDate(p.paid_on)}</td><td>${OMR(p.amount)}</td><td>${esc(p.method)}</td><td>${lpPdf(p.pdf, 'إيصال')}</td></tr>`), 'لا مدفوعات.')}
   ${d.cheques.length ? '<b>شيكاتي</b>' + T(['الرقم', 'البنك', 'المبلغ', 'الاستحقاق', 'الحال', ''], d.cheques.map(q => `<tr><td>${esc(q.number)}</td><td>${esc(q.bank)}</td><td>${OMR(q.amount)}</td><td>${fmtDate(q.due_date)}</td><td>${esc(LP_CHQ[q.status] || q.status)}</td><td>${lpPdf(q.pdf, 'إيصال استلام')}</td></tr>`)) : ''}`);
};
EXT.lpConsent = async v => { await tryDo(() => post('/lessee/consent', {version: v, accept: true}), 'سُجّل إقرارك'); EXT.l_lp(); };
EXT.lpMaintForm = async function (lid) {
  const L = (await api('/lessee/leases')).filter(l => l.status === 'active');
  if (!L.length) { toast('لا عقد ساريًا لرفع طلب صيانة عليه', 1); return; }
  modal(`<h3>طلب صيانة</h3>${HS('lmL', 'العقد', L.map(l => [l.id, `${l.number} · ${l.unit}`]), lid || L[0].id)}${HS('lmC', 'الفئة', ['سباكة', 'كهرباء', 'تكييف', 'نظافة وأمن', 'مرافق ومصاعد', 'ملاحظة في العين المؤجرة', 'أخرى'].map(x => [x, x]), 'سباكة')}<label for="lmD">الوصف</label><textarea id="lmD" rows="4" maxlength="600"></textarea><label><input type="checkbox" id="lmU"> عاجل (تعطّل يمنع الانتفاع بالعين)</label><div class="err" id="lmE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="lmGo">إرسال</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#lmGo').onclick = async () => { try { const r = await post('/lessee/maintenance', {lease_id: +$('#lmL').value, category: $('#lmC').value, description: $('#lmD').value.trim(), urgent: $('#lmU').checked}); closeModal(); toast('أُرسل الطلب — الموعد المستهدف ' + fmtDate(r.sla_due)); EXT.l_lp(); } catch (e) { $('#lmE').textContent = e.message; } };
};
EXT.leaAccount = async id => {
  const a = await api(`/lea/tenants/${id}/account`);
  if (a.exists) {
    if (!confirm(`للمستأجر حساب (${a.username}). هل تريد إعادة تعيين كلمة مروره المؤقتة؟`)) return;
    const r = await post(`/lea/tenants/${id}/account/reset`, {});
    modal(`<h3>كلمة مرور مؤقتة جديدة</h3><p>اسم المستخدم: <b class="num" dir="ltr">${esc(r.username)}</b></p><p>كلمة المرور: <b class="num" dir="ltr">${esc(r.temporary_password)}</b></p><p class="muted">تُعرض مرة واحدة فقط، ويُلزم المستأجر بتغييرها عند أول دخول. سلّمها إليه بوسيلة آمنة.</p><div class="btns"><button class="btn p" data-call="closeModal">تم</button></div>`);
    return;
  }
  if (!confirm('إنشاء حساب بوابة لهذا المستأجر؟')) return;
  const r = await post(`/lea/tenants/${id}/account`, {});
  modal(`<h3>حساب بوابة المستأجر</h3><p>اسم المستخدم: <b class="num" dir="ltr">${esc(r.username)}</b></p><p>كلمة المرور المؤقتة: <b class="num" dir="ltr">${esc(r.temporary_password)}</b></p><p class="muted">${esc(r.note)}</p><div class="btns"><button class="btn p" data-call="closeModal">تم</button></div>`);
};

/* ---- بوابة الموظف: حضوري وسلفي (0.28.0) */
const ATT_LBL = {present: ['حضور', 'p-ok'], absent: ['غياب', 'p-b'], late: ['تأخر', 'p-w'], leave: ['إجازة', 'p-bl'], holiday: ['عطلة', 'p-bl'], remote: ['عن بُعد', 'p-ok']};
EXT.meAtt = async B => {
  const mo = EXT.data.attMonth || new Date().toISOString().slice(0, 7);
  const a = await api('/hr/me/attendance?month=' + encodeURIComponent(mo));
  B.innerHTML = BOX('حضوري', `<label for="attM">الشهر</label><input id="attM" type="month" value="${esc(a.month)}">`
    + KP(Object.keys(ATT_LBL).filter(k => a.counts[k]).map(k => [ATT_LBL[k][0], N(a.counts[k])]))
    + T(['اليوم', 'الحالة', 'دخول', 'خروج', 'ملاحظة'], a.days.map(d => `<tr><td>${fmtDate(d.day)}</td><td>${pill(...(ATT_LBL[d.status] || [esc(d.status), 'p-w']))}</td><td>${esc(d.check_in || '—')}</td><td>${esc(d.check_out || '—')}</td><td>${esc(d.note || '')}</td></tr>`), 'لا أيام مسجَّلة في هذا الشهر.'));
  $('#attM').onchange = e => { EXT.data.attMonth = e.target.value; EXT.l_me(); };
};
const LOAN_KIND = {advance: 'سلفة على الراتب', qard_hasan: 'قرض حسن'};
const LOAN_ST = {pending: ['بانتظار الاعتماد', 'p-w'], active: ['جارٍ سداده', 'p-bl'], paid: ['مسدَّد', 'p-ok'], cancelled: ['ملغى', 'p-w']};
EXT.meLoans = async B => {
  const L = await api('/hr/me/loans');
  B.innerHTML = BOX('سلفي وقروضي', T(['النوع', 'المبلغ', 'الأقساط', 'المتبقي', 'بداية الخصم', 'الحال'], L.map(l => `<tr><td>${esc(LOAN_KIND[l.kind] || l.kind)}</td><td>${OMR(l.amount)}</td><td>${N(l.installments)}</td><td>${OMR(l.remaining)}</td><td>${esc(l.start_period)}</td><td>${pill(...(LOAN_ST[l.status] || [esc(l.status), 'p-w']))}</td></tr>`), 'لا سلف ولا قروض.'))
    + L.filter(l => l.schedule.length).map(l => BOX(`جدول ${esc(LOAN_KIND[l.kind] || l.kind)} ${OMR(l.amount)}`, T(['القسط', 'الشهر', 'المبلغ', 'الحال'], l.schedule.map(i => `<tr><td>${N(i.no)}</td><td>${esc(i.period)}</td><td>${OMR(i.amount)}</td><td>${esc({due: 'مستحق', deducted: 'خُصم', waived: 'أُعفي', settled: 'سُوّي'}[i.status] || i.status)}</td></tr>`)))).join('')
    + '<p class="muted">الخصم من الراتب بلا فائدة ولا رسوم — قرض حسن.</p>';
};

/* ================================================================ التقارير */
EXT.l_lender = async function (el) {
  const [L, I] = await Promise.all([api('/reports/lender'), api('/reports/investor')]);
  const col = r => r === 'أخضر' ? 'p-ok' : r === 'أصفر' ? 'p-w' : 'p-b';
  el.innerHTML = BOX(`تقرير الممول (البنك) <span class="muted">كما في ${fmtDate(L.as_of)}</span>`, T(['المشروع', 'الإنجاز', 'المبيعات', 'التحصيل', 'التغطية', 'عجز متوقع', 'فرق الإنجاز', 'التقييم'],
      L.projects.map(p => `<tr title="${esc(p.flags.join(' · '))}"><td>${esc(p.project)}</td><td>${pct(p.build_pct)}</td><td>${pct(p.sold_pct)}</td><td>${pct(p.collection_rate)}</td><td>${ND(p.coverage)}×</td><td>${p.cash_gap ? OMR(p.cash_gap) : '—'}</td><td>${p.claimed_vs_verified ? N(p.claimed_vs_verified) + ' نقاط' : '—'}</td><td>${pill(p.rating, col(p.rating))}</td></tr>`)))
    + `<div class="ai">${L.projects.filter(p => p.flags.length).map(p => `<b class="k">${esc(p.project)}:</b> ${p.flags.map(AR).join(' · ')}`).join('<br>') || 'لا ملاحظات.'}<br><span class="muted">${esc(L.method)}</span></div>`
    + BOX('تقرير المستثمرين', T(['المشروع', 'القيمة الإجمالية للمبيعات', 'المباع', 'التكلفة التقديرية', 'الربح التقديري', 'الهامش', 'التوزيعات'],
      I.projects.map(p => `<tr><td>${esc(p.project)}</td><td>${OMR(p.gdv)}</td><td>${OMR(p.sold_value)}</td><td>${OMR(p.est_cost)}</td><td>${OMR(p.est_profit)}</td><td>${pct(p.margin)}</td><td>${OMR(p.distributions)}</td></tr>`))) + `<div class="muted">${esc(I.note)}</div>`;
};

/* ================================================================ الإدارة والأمان */
EXT.l_adm = async function () {
  const k = this.cur.adm, el = $('#adm');
  el.innerHTML = SUB('adm', [['users', 'المستخدمون'], ['mods', 'الوحدات والترخيص'], ['sec', 'أماني'], ['brand', 'هوية المستندات والختم'], ['look', 'المظهر والمساعد'], ['ops', 'السجل والنسخ والتكامل'], ['notif', 'الإشعارات'], ['priv', 'طلبات الخصوصية']].filter(([x]) => x === 'sec' || can('admin') || (x === 'notif' && can('notify'))), k) + '<div id="admB">…</div>';
  const B = $('#admB');
  if (k === 'users' && can('users')) {
    const U = await api('/users');
    B.innerHTML = BOX('المستخدمون والأدوار', T(['المستخدم', 'الاسم', 'البريد', 'الدور', 'الحالة', 'تحقق ثنائي', 'تغيير كلمة المرور', ''], U.map(u => `<tr><td><span class="num">${esc(u.username)}</span></td><td>${esc(u.name)}</td><td><span class="num">${esc(u.email || '—')}</span>${u.google_linked ? ' <span class="pill p-ok">Google</span>' : ''} <button class="link" data-call="EXT.uemail" data-args="${J([u.id, u.email || ''])}">تعديل</button></td><td>${esc(u.role)}</td><td>${u.active ? pill('مفعّل', 'p-ok') : pill('معطّل', 'p-b')}</td><td>${u.totp_enabled ? '✓' : '—'}</td><td>${u.must_change ? pill('مطلوب', 'p-w') : fmtDate(u.pw_changed)}</td><td><button class="btn" data-call="EXT.ureset" data-args="${J([u.id])}">إعادة تعيين</button> <button class="btn" data-call="EXT.uact" data-args="${J([u.id, u.active ? 0 : 1])}">${u.active ? 'تعطيل' : 'تفعيل'}</button> <button class="btn" data-call="EXT.ukill" data-args="${J([u.id])}">إنهاء الجلسات</button>${u.totp_enabled ? ` <button class="btn" data-call="EXT.u2fa" data-args="${J([u.id])}">إعادة ضبط التحقق</button>` : ''}</td></tr>`)),
      '<button class="btn" data-call="EXT.newUser">+ مستخدم</button>');
  } else if (k === 'mods' && can('admin')) {
    const [M, L] = await Promise.all([api('/modules'), api('/license')]);
    const ttl = Object.fromEntries(M.modules.map(m => [m.key, m.title]));
    B.innerHTML = BOX('الوحدات المفعَّلة <span class="muted">إطفاء وحدة يُخفي شاشاتها ومساراتها وصلاحياتها دون حذف أي بيانات، وإعادة تفعيلها تعيد كل شيء</span>',
      T(['الوحدة', 'ما تشمله', 'تعتمد على', 'الترخيص', 'مفعَّلة'], M.modules.map(m => `<tr><td><b>${esc(m.title)}</b></td><td>${esc(m.desc)}</td><td>${m.deps.length ? m.deps.map(d => esc(ttl[d])).join('، ') : '—'}</td>
        <td>${!m.available ? pill('قريبًا', 'p-bl') : m.licensed ? pill('مرخَّصة', 'p-ok') : pill('غير مرخَّصة', 'p-w')}</td>
        <td>${m.available && m.licensed ? `<input type="checkbox" class="modchk" data-k="${m.key}" ${m.enabled ? 'checked' : ''} aria-label="${esc(m.title)}">` : '—'}</td></tr>`))
      + `<div class="btns" style="padding:12px 14px"><span class="muted">باقات جاهزة:</span> ${M.bundles.map(b => `<button class="btn" data-b="${esc(b.key)}">${esc(b.title)}</button>`).join(' ')} <button class="btn p" id="modsave">حفظ</button></div>`)
      + BOX('الترخيص وسجل التغييرات', `<div style="padding:14px"><p>المرخَّص لمؤسستكم: ${L.licensed.map(x => esc(x.title)).join('، ')}.${L.not_licensed.length ? ' غير مرخَّص: ' + L.not_licensed.map(x => esc(x.title)).join('، ') + '.' : ''}${L.soon.length ? ' قيد التطوير: ' + L.soon.map(x => esc(x.title)).join('، ') + '.' : ''}</p></div>`
        + T(['الوقت', 'المنفّذ', 'الإجراء', 'الوحدة'], L.log.map(r => `<tr><td>${esc(r.at)}</td><td>${esc(r.actor)}</td><td>${esc(r.action)}</td><td>${esc(r.detail)}</td></tr>`)));
    const bundle = Object.fromEntries(M.bundles.map(b => [b.key, b.modules]));
    $$('#admB [data-b]').forEach(b => b.onclick = () => $$('#admB .modchk').forEach(x => { x.checked = bundle[b.dataset.b].includes(x.dataset.k); }));
    $('#modsave').onclick = async () => { await tryDo(() => api('/modules', {method: 'POST', body: {modules: [...$$('#admB .modchk:checked')].map(x => x.dataset.k)}})); toast('حُفظت الوحدات'); location.reload(); };
  } else if (k === 'brand' && can('admin')) {
    const b = await api('/admin/brand');
    const f = (id, l, v, ph = '') => `<label>${l}</label><input id="${id}" value="${esc(v || '')}" placeholder="${ph}">`;
    const img = (d) => d ? `<img src="/api/documents/${d}" alt="" style="height:56px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:4px">` : '<span class="muted">لم تُرفع</span>';
    B.innerHTML = BOX('ترويسة المستندات الصادرة (عروض الأسعار، العقود، الفواتير، الإيصالات)', `<div style="padding:14px"><div class="grid2">${f('brn', 'اسم المطوّر كما يظهر في المستندات', b.name)}${f('brcr', 'رقم السجل التجاري', b.cr)}${f('brvat', 'الرقم الضريبي', b.vat)}${f('brad', 'العنوان', b.address)}${f('brph', 'الهاتف', b.phone)}${f('brem', 'البريد', b.email)}${f('brsg', 'اسم المفوَّض بالتوقيع', b.signatory)}${f('brst', 'صفته', b.signatory_title)}</div>
      <div class="btns" style="margin-top:12px"><button class="btn p" id="brsave">حفظ</button></div></div>`)
      + BOX('الشعار والختم والتوقيع المعتمد <span class="muted">صور PNG/JPEG بخلفية بيضاء أو شفافة؛ تُطبع في كل مستند</span>', `<div style="padding:14px" class="grid3">${['logo', 'stamp', 'sign'].map(k => `<div><b>${{logo: 'الشعار', stamp: 'الختم', sign: 'التوقيع'}[k]}</b><div style="margin:8px 0">${img(b[k + '_doc'])}</div><input type="file" id="br_${k}" accept=".png,.jpg,.jpeg"><button class="btn" data-call="EXT.brandUpload" data-args="${J([k])}">رفع</button></div>`).join('')}</div>`);
    $('#brsave').onclick = async () => { await tryDo(() => api('/admin/brand', {method: 'POST', body: {name: $('#brn').value, cr: $('#brcr').value, vat: $('#brvat').value, address: $('#brad').value, phone: $('#brph').value, email: $('#brem').value, signatory: $('#brsg').value, signatory_title: $('#brst').value}}), 'حُفظت الترويسة'); };
  } else if (k === 'look' && can('admin')) {
    const [U, AC] = await Promise.all([api('/appearance'), api('/admin/assistant')]);
    EXT.uiOpt = U.options; EXT.ui = {preset: U.preset, pattern: U.pattern, fit: U.fit, mode: U.mode, size: U.size, strength: U.strength, image_doc: U.image_doc}; EXT.aiCfg = AC;
    applyUI(EXT.ui); lookRender();
  } else if (k === 'ops' && can('admin')) {
    const v = await api('/audit/verify');
    B.innerHTML = KP([['سلامة سجل التدقيق', v.ok ? '✓ سليم' : '⚠ مكسور', N(v.entries) + ' قيدًا · بصمة ' + (v.head || '')], ['السجل', 'إلحاق فقط', 'لا تعديل ولا حذف'], ['النسخ الاحتياطي', 'آخر 14 نسخة', 'مشفّر في الإنتاج'], ['واجهة التكامل', '/api/v1', 'مفاتيح قراءة فقط']])
      + `<div class="btns"><button class="btn p" id="bk1">نسخة احتياطية الآن</button><button class="btn" id="ak1">إنشاء مفتاح API</button></div><div id="opsR"></div>`;
    $('#bk1').onclick = async () => { const r = await tryDo(() => api('/admin/backup', {method: 'POST'})); $('#opsR').innerHTML = `<div class="ai">✓ ${esc(r.file)}</div>`; };
    $('#ak1').onclick = async () => { const r = await tryDo(() => api('/admin/api-keys', {method: 'POST'})); $('#opsR').innerHTML = `<div class="ai"><b class="k">المفتاح (يُعرض مرة واحدة):</b><br><span class="num" style="user-select:all">${esc(r.key)}</span><br>${esc(r.note)}</div>`; };
  } else if (k === 'notif') {
    const Nn = await api('/notifications');
    B.innerHTML = `<div class="btns" style="margin-bottom:12px"><button class="btn p" id="nrun">تشغيل التذكيرات الآن</button></div>` + BOX('الإشعارات', T(['الوقت', 'الجمهور', 'القناة', 'العنوان', 'النص', 'الحالة'], Nn.map(n => `<tr><td>${fmtDate(n.created)}</td><td>${n.audience === 'customer' ? 'عميل' : 'فريق'}</td><td>${esc(n.channel)}</td><td>${esc(n.title)}</td><td>${esc(n.body)}</td><td>${pill('في الطابور', 'p-bl')}</td></tr>`)));
    $('#nrun').onclick = async () => { const r = await tryDo(() => api('/notifications/run', {method: 'POST'})); toast(`أُنشئ ${N(r.created)} إشعار`); EXT.l_adm(); };
  } else if (k === 'priv' && can('admin')) {
    const P = await api('/privacy');
    B.innerHTML = BOX('طلبات أصحاب البيانات (قانون حماية البيانات الشخصية)', T(['العميل', 'النوع', 'التاريخ', 'الحالة', 'ملاحظة'], P.map(p => `<tr><td>${esc(p.name)}</td><td>${esc({export: 'نسخة من بياناتي', erase: 'حذف', correct: 'تصحيح'}[p.kind])}</td><td>${fmtDate(p.created)}</td><td>${pill('مفتوح', 'p-w')}</td><td>${esc(p.note)}</td></tr>`)));
  } else {
    EXT.cur.adm = 'sec';
    const [SS, ID] = await Promise.all([api('/me/sessions'), api('/me/identity')]);
    const ago = t => t ? fmtDate(new Date(t * 1000).toISOString()) : '—';
    B.innerHTML = BOX('أمان حسابي', `<div style="padding:14px"><p>التحقق الثنائي: <b>${S.me.totp_enabled ? 'مفعّل ✓' : 'غير مفعّل'}</b></p><div class="btns">${S.me.totp_enabled ? '' : '<button class="btn p" id="t2">تفعيل التحقق الثنائي</button>'}<button class="btn" id="cpw">تغيير كلمة المرور</button><button class="btn" id="sall">تسجيل الخروج من كل الأجهزة الأخرى</button></div><div id="t2r"></div></div>`)
      + BOX(`جلساتي <span class="muted">تنتهي الجلسة بعد ${N(SS.idle_minutes)} دقيقة بلا نشاط أو ${N(SS.absolute_hours)} ساعة كحد أقصى</span>`, T(['الجهاز', 'العنوان', 'بدأت', 'آخر نشاط', ''], SS.sessions.map(s => `<tr><td>${esc(s.label)}${s.current ? ' ' + pill('هذه الجلسة', 'p-ok') : ''}</td><td><span class="num">${esc(s.ip)}</span></td><td>${ago(s.created)}</td><td>${ago(s.last_seen)}</td><td>${s.current ? '' : `<button class="btn" data-call="EXT.skill" data-args="${J([s.id])}">إنهاء</button>`}</td></tr>`)));
    B.innerHTML += BOX('هويتي الخارجية', `<div style="padding:14px"><p>البريد الإلكتروني: <b class="num">${esc(ID.email || '—')}</b> ${ID.email ? (ID.email_verified ? pill('موثَّق', 'p-ok') : pill('غير موثَّق', 'p-w')) : ''} <button class="link" id="idEm">تعديل</button></p> <p class="muted">البريد يتيح استعادة كلمة المرور ورابط دخول لمرة واحدة والدخول عبر Google (للحسابات بلا تحقق ثنائي).</p> <div class="btns">${ID.methods.google ? (ID.google_linked ? '<button class="btn" id="gUn">فصل حساب Google</button>' : `<a class="btn p" href="/auth/google/start?t=${encodeURIComponent(S.me.tenant || 'jadwa')}&link=1">ربط حساب Google</a>`) : '<span class="muted">الدخول عبر Google غير مفعّل على هذا الخادم.</span>'}</div></div>`);
    $('#idEm').onclick = async () => { const v = prompt('بريدك الإلكتروني (فارغ للحذف)', ID.email || ''); if (v === null) return; await tryDo(() => api('/me/email', {method: 'POST', body: {email: v.trim()}}), 'حُدّث البريد'); EXT.l_adm(); };
    if ($('#gUn')) $('#gUn').onclick = async () => { if (!confirm('فصل حساب Google عن حسابك؟')) return; await tryDo(() => api('/me/google/unlink', {method: 'POST'}), 'فُصل الحساب'); EXT.l_adm(); };
    if ($('#t2')) $('#t2').onclick = () => EXT.setup2fa();
    $('#cpw').onclick = () => EXT.changePw(false);
    $('#sall').onclick = async () => { const r = await tryDo(() => api('/me/sessions/revoke', {method: 'POST', body: {others: true}})); toast(`أُنهيت ${N(r.revoked)} جلسة`); EXT.l_adm(); };
  }
};
function lookRender() {
  const U = EXT.ui, O = EXT.uiOpt, A = EXT.aiCfg, lt = document.body.classList.contains('light') ? ' lt' : '';
  const seg = (key, opts) => `<div class="seg">${Object.entries(opts).map(([v, l]) => `<button class="${U[key] === v ? 'on' : ''}" data-call="EXT.lookSet" data-args="${J([key, v])}">${esc(l)}</button>`).join('')}</div>`;
  const sw = Object.entries(O.presets).map(([id, l]) => `<button class="sw${lt}${U.preset === id ? ' on' : ''}" data-bg="${id}" data-call="EXT.lookSet" data-args="${J(['preset', id])}" aria-pressed="${U.preset === id}"><span class="spv"><i></i><b></b><u></u></span><em>${esc(l)}</em></button>`).join('');
  const img = U.image_doc ? `<img src="/api/appearance/image?v=${U.image_doc}&doc=${U.image_doc}" alt="" style="height:56px;border:1px solid var(--line);border-radius:8px">` : '<span class="muted">لم تُرفع صورة</span>';
  const patNote = U.pattern === 'none' ? '' : `<div class="grid2" style="margin-top:12px"><div><label>${U.pattern === 'image' && U.fit !== 'tile' ? 'حجم الصورة غير مستخدم مع «تغطية/احتواء»' : 'حجم النقش / البلاطة'} <b class="num" id="lkSizeV">${U.size}</b> px</label><input type="range" id="lkSize" min="${O.limits.size[0]}" max="${O.limits.size[1]}" value="${U.size}"></div>
    <div><label>${U.pattern === 'image' ? 'ظهور الصورة' : 'وضوح النقش'} <b class="num" id="lkStrV">${U.strength}</b>٪</label><input type="range" id="lkStr" min="${O.limits.strength[0]}" max="${O.limits.strength[1]}" value="${U.strength}"></div></div>`;
  const imgBox = U.pattern === 'image' || U.image_doc ? `<div style="margin-top:14px"><b>صورة المؤسسة</b><div style="margin:8px 0">${img}</div>
    <input type="file" id="lkFile" accept=".png,.jpg,.jpeg"> <button class="btn" data-call="EXT.lookUpload">رفع</button> ${U.image_doc ? '<button class="btn" data-call="EXT.lookNoImg">إزالة الصورة</button>' : ''}
    <div style="margin-top:8px">${seg('fit', O.fits)}</div><p class="muted">الظهور المرتفع يُضعف قراءة النصوص؛ يُنصح بما دون 40٪. صور PNG/JPEG حتى 5 ميجابايت.</p></div>` : '';
  const offLLM = !A.key_configured;
  $('#admB').innerHTML = BOX('خلفية المنصة <span class="muted">المعاينة فورية ولا تُحفظ لجميع مستخدمي المؤسسة إلا بزر «حفظ»</span>',
    `<div style="padding:14px"><div class="swg">${sw}</div>
     <div class="grid2" style="margin-top:14px"><div><b>النقش</b><div style="margin-top:6px">${seg('pattern', O.patterns)}</div></div><div><b>الوضع</b><div style="margin-top:6px">${seg('mode', O.modes)}</div></div></div>${patNote}${imgBox}
     <div class="btns" style="margin-top:14px"><button class="btn p" data-call="EXT.lookSave">حفظ للمؤسسة</button><button class="btn" data-call="EXT.lookReset">القيم الافتراضية</button><button class="btn" data-call="EXT.lookCancel">تراجع عن المعاينة</button></div></div>`)
    + BOX('المساعد الذكي <span class="muted">' + (A.active ? 'النموذج اللغوي يعمل' : 'المحرك المحلي يعمل') + '</span>',
    `<div style="padding:14px"><p>المحرك المحلي يجيب بلا مغادرة أي بيانات للخادم. تفعيل النموذج اللغوي يتيح فهمًا أوسع للأسئلة الحرّة؛ ويُرسل أرقامًا مجمَّعة فقط، ولا يُرسل هاتفًا ولا هوية ولا بريدًا.</p>
     <label style="display:flex;gap:8px;align-items:center;margin:10px 0"><input type="checkbox" id="aiLlm" ${A.llm ? 'checked' : ''} ${offLLM ? 'disabled' : ''} data-ai="llm"> استخدام نموذج لغوي لفهم أوسع للأسئلة</label>
     ${offLLM ? '<p class="muted">لم يُضبط مفتاح النموذج في بيئة التشغيل (MABANIQ_AI_KEY) — اطلب ذلك من مسؤول الاستضافة؛ حتى ذلك الحين يعمل المحرك المحلي.</p>' : `<p class="muted">النموذج: <span class="num">${esc(A.model)}</span></p>`}
     <label style="display:flex;gap:8px;align-items:center;margin:10px 0"><input type="checkbox" id="aiNames" ${A.names ? 'checked' : ''} data-ai="names"> السماح بإرسال أسماء العملاء إلى النموذج (الافتراضي: تُحجب وتظهر «عميل #رقم»)</label>
     <p class="muted">${esc(A.note)}</p></div>`);
  const live = (id, key, out) => { const el = $(id); if (el) el.oninput = e => { U[key] = +e.target.value; $(out).textContent = e.target.value; applyUI(U); }; };
  live('#lkSize', 'size', '#lkSizeV'); live('#lkStr', 'strength', '#lkStrV');
  $$('[data-ai]').forEach(el => el.onchange = async () => { try { EXT.aiCfg = await api('/admin/assistant', {method: 'POST', body: {[el.dataset.ai]: el.checked}}); toast('حُفظ إعداد المساعد'); } catch (e) { toast(e.message, 1); } lookRender(); });
}
EXT.lookSet = (key, val) => { EXT.ui[key] = val; if (key === 'pattern' && val === 'image' && !EXT.ui.image_doc) toast('ارفع صورة المؤسسة ثم احفظ'); applyUI(EXT.ui); lookRender(); };
EXT.lookSave = async () => { const r = await tryDo(() => api('/admin/appearance', {method: 'POST', body: EXT.ui}), 'حُفظ مظهر المنصة لكل مستخدمي المؤسسة'); EXT.ui = {...EXT.ui, ...r}; applyUI(r); try { localStorage.setItem('mbq-ui', JSON.stringify(r)); } catch (e) { /* محجوب */ } lookRender(); };
EXT.lookReset = () => { EXT.ui = {preset: 'navy', pattern: 'none', fit: 'cover', mode: 'user', size: 24, strength: 30, image_doc: 0}; applyUI(EXT.ui); lookRender(); };
EXT.lookCancel = async () => { const u = await loadUI(); EXT.ui = {preset: u.preset, pattern: u.pattern, fit: u.fit, mode: u.mode, size: u.size, strength: u.strength, image_doc: u.image_doc}; lookRender(); };
EXT.lookNoImg = () => { EXT.ui.image_doc = 0; if (EXT.ui.pattern === 'image') EXT.ui.pattern = 'none'; applyUI(EXT.ui); lookRender(); };
EXT.lookUpload = async () => {
  const f = $('#lkFile').files[0]; if (!f) return toast('اختر صورة', 1);
  const fd = new FormData(); fd.append('ref_type', 'brand'); fd.append('ref_id', '0'); fd.append('title', 'خلفية المنصة'); fd.append('category', 'هوية'); fd.append('file', f);
  try { const r = await fetch('/api/documents', {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || 'تعذّر الرفع');
    EXT.ui.image_doc = j.id; EXT.ui.pattern = 'image'; applyUI(EXT.ui); lookRender(); toast('رُفعت الصورة — اضغط «حفظ للمؤسسة» لاعتمادها'); } catch (e) { toast(e.message, 1); }
};
EXT.brandUpload = async kind => { const f = $(`#br_${kind}`).files[0]; if (!f) return toast('اختر صورة', 1); const fd = new FormData(); fd.append('ref_type', 'brand'); fd.append('ref_id', '0'); fd.append('title', {logo: 'الشعار', stamp: 'الختم', sign: 'التوقيع'}[kind]); fd.append('category', 'هوية'); fd.append('file', f);
  try { const r = await fetch('/api/documents', {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || 'تعذّر الرفع'); await api('/admin/brand', {method: 'POST', body: {[kind + '_doc']: j.id}}); toast('رُفعت الصورة'); EXT.l_adm(); } catch (e) { toast(e.message, 1); } };
EXT.ureset = async id => { if (!confirm('إعادة تعيين كلمة المرور وإنهاء جلسات المستخدم؟')) return; const r = await tryDo(() => api(`/users/${id}/reset`, {method: 'POST'})); modal(`<h3>كلمة مرور مؤقتة</h3><p>للمستخدم <b>${esc(r.username)}</b>:</p><div class="ai"><span class="num" style="user-select:all">${esc(r.temporary_password)}</span></div><p class="muted">تُعرض مرة واحدة، ويُلزم بتغييرها عند الدخول.</p><button class="btn" data-call="closeModal">إغلاق</button>`); };
EXT.skill = async id => { await tryDo(() => api('/me/sessions/revoke', {method: 'POST', body: {id}}), 'أُنهيت الجلسة'); EXT.l_adm(); };
EXT.ukill = async id => { if (!confirm('إنهاء كل جلسات هذا المستخدم فورًا (جهاز مفقود / مغادرة)؟')) return; const r = await tryDo(() => api(`/users/${id}/sessions/revoke`, {method: 'POST'})); toast(`أُنهيت ${N(r.revoked)} جلسة`); };
EXT.u2fa = async id => { if (!confirm('إعادة ضبط التحقق الثنائي لهذا المستخدم؟ تُبطل رموزه وتُنهى جلساته، ويعيد التفعيل عند الدخول.')) return; await tryDo(() => api(`/users/${id}/2fa/reset`, {method: 'POST'}), 'أُعيد ضبط التحقق الثنائي'); EXT.l_adm(); };
EXT.uemail = async (id, cur) => { const v = prompt('البريد الإلكتروني للمستخدم (فارغ للحذف) — يتيح استعادة كلمة المرور ورابط الدخول والدخول عبر Google', cur || ''); if (v === null) return; await tryDo(() => api(`/users/${id}/email`, {method: 'POST', body: {email: v.trim()}}), 'حُدّث البريد'); EXT.l_adm(); };
EXT.uact = async (id, a) => { await tryDo(() => api(`/users/${id}/active`, {method: 'POST', body: {active: !!a}}), 'حُدّث المستخدم'); EXT.l_adm(); };
EXT.newUser = () => { modal(`<h3>مستخدم جديد</h3><label>اسم المستخدم (إنجليزي)</label><input id="un" dir="ltr"><label>الاسم</label><input id="unm"><label>البريد الإلكتروني (اختياري — لاستعادة كلمة المرور ورابط الدخول وGoogle)</label><input id="uem" dir="ltr" type="email"><label>الدور</label><select id="ur"><option value="sales">مبيعات</option><option value="finance">مالية</option><option value="engineer">مهندس</option><option value="investor">مستثمر/ممول</option><option value="admin">مدير</option></select><div class="err" id="ue"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="ugo">إنشاء</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#ugo').onclick = async () => { try { const r = await api('/users', {method: 'POST', body: {username: $('#un').value.trim().toLowerCase(), name: $('#unm').value, role: $('#ur').value, email: ($('#uem').value || '').trim() || null}}); modal(`<h3>أُنشئ المستخدم</h3><div class="ai"><b>${esc(r.username)}</b><br>كلمة المرور المؤقتة: <span class="num" style="user-select:all">${esc(r.temporary_password)}</span></div><p class="muted">${esc(r.note)}</p><button class="btn" data-call="closeModal">إغلاق</button>`); EXT.l_adm(); } catch (e) { $('#ue').textContent = e.message; } }; };
EXT.setup2fa = async () => {
  const r = await tryDo(() => api('/auth/2fa/setup', {method: 'POST'}));
  modal(`<h3>تفعيل التحقق الثنائي</h3><p>أضف الحساب في تطبيق المصادقة (Google Authenticator أو Microsoft Authenticator) بالمفتاح التالي:</p><div class="ai"><span class="num" style="user-select:all;word-break:break-all">${esc(r.secret)}</span></div><label>أدخل الرمز المكوّن من 6 أرقام</label><input id="otp" inputmode="numeric" dir="ltr" maxlength="6"><div class="err" id="oe"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="ogo2">تفعيل</button><button class="btn" data-call="closeModal">لاحقًا</button></div>`);
  $('#ogo2').onclick = async () => { try { const en = await api('/auth/2fa/enable', {method: 'POST', body: {otp: $('#otp').value.trim()}}); S.me = await api('/me');
      modal(`<h3>✓ فُعّل التحقق الثنائي — احفظ رموز الاسترداد</h3><p class="muted">${esc(en.note)} تُعرض مرة واحدة فقط.</p><div class="ai"><div class="num" style="user-select:all;line-height:2;direction:ltr;text-align:left">${en.recovery_codes.map(esc).join('<br>')}</div></div><button class="btn p" id="rcok">حفظتها</button>`);
      $('#rcok').onclick = () => { closeModal(); if (S.screen === 'adm') EXT.l_adm(); else location.reload(); }; } catch (e) { $('#oe').textContent = e.message; } };
};
EXT.changePw = forced => {
  modal(`<h3>${forced ? 'غيّر كلمة المرور المؤقتة للمتابعة' : 'تغيير كلمة المرور'}</h3>${forced ? '<p class="muted">هذا أول دخول لك. اختر كلمة مرور خاصة (10 أحرف على الأقل تجمع حروفًا وأرقامًا).</p>' : ''}
   <label>كلمة المرور الحالية</label><input id="pc" type="password" autocomplete="current-password" dir="ltr"><label>كلمة المرور الجديدة</label><input id="pn" type="password" autocomplete="new-password" dir="ltr"><label>تأكيدها</label><input id="pn2" type="password" autocomplete="new-password" dir="ltr"><div class="err" id="pe2"></div>
   <div class="btns" style="margin-top:12px"><button class="btn p" id="pgo2">حفظ</button>${forced ? '' : '<button class="btn" data-call="closeModal">إلغاء</button>'}</div>`);
  $('#pgo2').onclick = async () => { if ($('#pn').value !== $('#pn2').value) return $('#pe2').textContent = 'التأكيد لا يطابق'; try { await api('/auth/password', {method: 'POST', body: {current: $('#pc').value, new: $('#pn').value}}); toast('✓ تغيّرت كلمة المرور'); closeModal(); if (forced) location.reload(); } catch (e) { $('#pe2').textContent = e.message; } };
};

/* توجيه كل قسم إلى أول تبويب فرعي مسموح للدور الحالي */
['pre', 'sal', 'bill', 'post'].forEach(id => { const f = EXT['l_' + id]; EXT['l_' + id] = function () {
  const order = Object.keys(SUBP).filter(x => x.startsWith(id + '.')).map(x => x.split('.')[1]);
  if (!subOk(id, this.cur[id])) this.cur[id] = order.find(k => subOk(id, k)) || this.cur[id];
  return f.call(this); }; });


/* ---- Unit 3: delegated handlers are registered here (module scope, nothing on window) */
Object.assign(CALLS, {approveIPC, cancelBooking, closeModal, confirmBooking, decide, go, openBooking, resaleAct, setStage, showUnit, svcSet, EXT});
applyI18n();
const langBtn = document.getElementById('lang');
if (langBtn) { langBtn.textContent = lang() === 'ar' ? 'EN' : 'ع'; langBtn.onclick = () => toggleLang(); }

/* ---------------- الوحدة 6: المستندات (PDF · بريد · واتساب) ---------------- */
const DOCK = {quote: 'عرض السعر', contract: 'العقد', invoice: 'الفاتورة', receipt: 'الإيصال'};
const docBtns = (kind, id) => `<span class="btns docb"><a class="btn" href="/api/docs/${kind}/${id}.pdf" target="_blank" rel="noopener">PDF</a><button class="btn" data-call="EXT.docSend" data-args="${J([kind, id, 'email'])}">بريد</button><button class="btn" data-call="EXT.docSend" data-args="${J([kind, id, 'whatsapp'])}">واتساب</button></span>`;
EXT.docSend = async (kind, id, channel) => {
  const label = channel === 'email' ? 'البريد الإلكتروني للمستلم (فارغ = بريد العميل المسجَّل)' : 'رقم واتساب المستلم (فارغ = هاتف العميل المسجَّل)';
  const to = prompt(`إرسال ${DOCK[kind]} عبر ${channel === 'email' ? 'البريد' : 'واتساب'}\n${label}`, '');
  if (to === null) return;
  try {
    const r = await api(`/docs/${kind}/${id}/send`, {method: 'POST', body: {channel, to: to.trim() || null}});
    if (channel === 'whatsapp') { window.open(r.wa_url, '_blank', 'noopener'); toast('فُتح واتساب بالرسالة والرابط (صالح 30 يومًا)'); }
    else toast(r.delivered ? `أُرسل إلى ${r.to}` : `سُجّل الإرسال إلى ${r.to} (صندوق الصادر — البريد غير مهيّأ على هذا الخادم)`);
  } catch (e) { toast(e.message, 1); }
};

/* ---------------- الوحدة 6: عروض الأسعار ---------------- */
const QS = {issued: ['ساري', 'p-ok'], expired: ['منتهٍ', 'p-w'], converted: ['تحوّل إلى حجز', 'p-bl'], cancelled: ['ملغى', '']};
EXT.l_quotes = async function (B) {
  const Q = await api('/quotes');
  B.innerHTML = BOX('عروض الأسعار', T(['الرقم', 'العميل', 'الوحدة', 'الخطة', 'السعر', 'صالح حتى', 'الحالة', ''], Q.map(q => `<tr><td><span class="num">${esc(q.number)}</span></td><td>${esc(q.customer_name)}<br><span class="muted num">${esc(q.phone)}</span></td><td><span class="num">${esc(q.code)}</span><br><span class="muted">${esc(q.project)}</span></td><td>${PLANS[q.plan] ? PLANS[q.plan][0] : esc(q.plan)}</td><td>${OMR(q.price)}${q.discount_pct ? `<br><span class="muted">خصم ${N(q.discount_pct * 100)}٪</span>` : ''}</td><td>${fmtDate(q.valid_until)}</td><td>${pill(...(QS[q.status] || [q.status, '']))}</td>
    <td>${docBtns('quote', q.id)}${q.status === 'issued' && can('book') ? ` <button class="btn p" data-call="EXT.quoteConvert" data-args="${J([q.id, q.number])}">تحويل إلى حجز</button> <button class="btn" data-call="EXT.quoteCancel" data-args="${J([q.id])}">إلغاء</button>` : ''}${q.booking_id ? ` <span class="muted">حجز ${N(q.booking_id)}</span>` : ''}</td></tr>`), 'لم يصدر عرض سعر بعد.'),
    can('book') ? '<button class="btn p" data-call="EXT.newQuote">+ عرض سعر</button>' : '');
};
EXT.newQuote = async (code) => {
  if (!UNITS.length) UNITS = await api(`/units?project_id=${S.proj || S.projects[0].id}`).catch(() => []);  // the inventory screen may not have been opened yet
  const avail = UNITS.filter(u => u.status === 'a');
  const opts = (avail.length ? avail : []).map(u => `<option value="${esc(u.code)}" ${u.code === code ? 'selected' : ''}>${esc(u.code)} · ${esc(u.type)} · ${OMR(u.price)}</option>`).join('');
  const pj = S.projects.find(x => x.id === (S.proj || S.projects[0].id));
  modal(`<h3>عرض سعر جديد</h3><label>الوحدة المتاحة في ${esc(pj ? pj.name : 'المشروع')} <span class="muted">(غيّر المشروع من شاشة المخزون)</span></label>${opts ? `<select id="qu">${opts}</select>` : `<input id="qu" value="${esc(code || '')}" placeholder="رمز الوحدة" dir="ltr">`}
   <label>اسم العميل</label><input id="qn"><label>الهاتف</label><input id="qp" dir="ltr" placeholder="+968 9xxx xxxx"><label>البريد الإلكتروني (اختياري — للإرسال)</label><input id="qe" dir="ltr" type="email">
   <label>خطة السداد</label><select id="qpl">${Object.entries(PLANS).map(([k, v]) => `<option value="${k}">${v[0]}</option>`).join('')}</select>
   <label>خصم ٪ (صلاحيتك: ${can('decide') ? '15' : '2'}٪ كحد أقصى)</label><input id="qd" type="number" min="0" max="15" step="0.5" value="0" dir="ltr"><label>مدة الصلاحية بالأيام</label><input id="qv" type="number" min="1" max="60" value="7" dir="ltr"><label>ملاحظات تظهر في العرض</label><input id="qno">
   <div class="err" id="qerr"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="qgo">إصدار العرض</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#qgo').onclick = async () => { try {
    const q = await api('/quotes', {method: 'POST', body: {unit_code: $('#qu').value.trim(), customer_name: $('#qn').value.trim(), phone: $('#qp').value.trim(), email: $('#qe').value.trim() || null, plan: $('#qpl').value, discount_pct: (+$('#qd').value || 0) / 100, valid_days: +$('#qv').value || 7, notes: $('#qno').value.trim() || null}});
    modal(`<h3>✓ صدر ${esc(q.number)}</h3><p>السعر <b>${OMR(q.price)}</b> · صالح حتى ${fmtDate(q.valid_until)}.</p>${docBtns('quote', q.id)}<div class="btns" style="margin-top:12px"><button class="btn" data-call="closeModal">إغلاق</button></div>`);
    if (S.screen === 'sal') EXT.l_sal();
  } catch (e) { $('#qerr').textContent = e.message; } };
};
EXT.quoteConvert = async (id, number) => { if (!confirm(`تحويل ${number} إلى حجز مبدئي بالسعر المعروض؟ تُحجز الوحدة لثلاثة أيام حتى سداد العربون.`)) return; const r = await tryDo(() => api(`/quotes/${id}/convert`, {method: 'POST'}), 'أُنشئ الحجز'); if (r) { toast(`حجز ${N(r.booking_id)} · العربون ${OMR(r.deposit)}`); EXT.l_sal(); } };
EXT.quoteCancel = async id => { if (!confirm('إلغاء عرض السعر؟')) return; await tryDo(() => api(`/quotes/${id}/cancel`, {method: 'POST'}), 'أُلغي العرض'); EXT.l_sal(); };

/* ---------------- الوحدة 6: المخططات ---------------- */
const PLAN_KINDS = {site: 'المخطط العام للموقع', floor: 'مخطط طابق', unit: 'مخطط نموذج الوحدة', elevation: 'واجهة', section: 'قطاع', render: 'تصور نهائي', structural: 'مخطط إنشائي', mep: 'كهروميكانيكي'};
const planImg = (p, markers, hl, cls = '') => p.mime === 'application/pdf'
  ? `<a class="btn" href="${p.url}" target="_blank" rel="noopener">فتح ${esc(p.title)} (PDF)</a>`
  : `<div class="plan ${cls}" data-plan="${p.id}"><img src="${p.url}" alt="${esc(p.title)}">${(markers || []).map(m => `<span class="mk ${m.unit_code === hl ? 'hl' : ''} ${m.st || ''}" style="left:${m.x}%;top:${m.y}%" title="${esc(m.unit_code)}">${esc(m.unit_code.split('-').pop())}</span>`).join('')}</div>`;
EXT.plans = async () => {
  const p = S.projects.find(x => x.id === S.proj) || S.projects[0];
  const P = await api(`/plans?project_id=${p.id}`);
  const st = Object.fromEntries(UNITS.map(u => [u.code, u.status]));
  let h = `<h3>مخططات ${esc(p.name)}</h3>`;
  if (can('docs')) h += `<div class="ai"><b class="k">رفع مخطط:</b> <select id="plk">${Object.entries(PLAN_KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select> <input id="plt" placeholder="العنوان" style="width:160px"> <input id="plb" placeholder="المبنى" style="width:70px"> <input id="plf" placeholder="الطابق" style="width:60px" dir="ltr"> <input id="plu" placeholder="نموذج الوحدة (للنماذج)" style="width:150px"> <input type="file" id="plfile" accept=".png,.jpg,.jpeg,.pdf"> <button class="btn p" id="plgo">رفع</button><div class="muted">PDF أو PNG أو JPEG حتى 5 ميجابايت. المخططات الإنشائية والكهروميكانيكية داخلية لا يراها العملاء.</div></div>`;
  h += P.length ? P.map(x => `<div class="box"><div class="hd"><span>${esc(x.title)} <span class="muted">${PLAN_KINDS[x.kind] || x.kind}${x.building ? ' · ' + esc(x.building) : ''}${x.floor !== null && x.floor !== undefined ? ' · ط ' + N(x.floor) : ''}${x.unit_type ? ' · ' + esc(x.unit_type) : ''}</span> ${x.public ? pill('يراه العملاء', 'p-ok') : pill('داخلي', '')}</span>
      <span class="btns">${x.kind === 'floor' && can('inventory') && x.mime !== 'application/pdf' ? `<button class="btn" data-call="EXT.planMark" data-args="${J([x.id])}">تحديد مواقع الوحدات</button>` : ''}${can('docs') ? `<button class="btn" data-call="EXT.planRemove" data-args="${J([x.id])}">إزالة</button>` : ''}</span></div>
      <div style="padding:10px">${planImg(x, x.markers.map(m => ({...m, st: st[m.unit_code] || ''})), null)}</div></div>`).join('') : '<div class="muted">لا مخططات بعد لهذا المشروع.</div>';
  insp('المخططات', h);
  if ($('#plgo')) $('#plgo').onclick = async () => { const f = $('#plfile').files[0]; if (!f || !$('#plt').value.trim()) return toast('اختر ملفًا واكتب عنوانًا', 1);
    const fd = new FormData(); fd.append('project_id', p.id); fd.append('kind', $('#plk').value); fd.append('title', $('#plt').value.trim()); fd.append('building', $('#plb').value.trim()); fd.append('floor', $('#plf').value.trim()); fd.append('unit_type', $('#plu').value.trim()); fd.append('file', f);
    try { const r = await fetch('/api/plans', {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || 'تعذّر الرفع'); toast('رُفع المخطط'); EXT.plans(); } catch (e) { toast(e.message, 1); } };
};
EXT.planRemove = async id => { if (!confirm('إزالة المخطط من المشروع؟ يبقى الملف في سجل المستندات.')) return; await tryDo(() => api(`/plans/${id}/remove`, {method: 'POST'}), 'أُزيل'); EXT.plans(); };
EXT.planMark = async id => {
  const P = await api(`/plans?project_id=${S.proj}`); const x = P.find(q => q.id === id); if (!x) return;
  let markers = x.markers.map(m => ({...m}));
  const list = UNITS.filter(u => (!x.building || u.building === x.building) && (x.floor === null || x.floor === undefined || u.floor === x.floor));
  const draw = () => { modal(`<h3>مواقع الوحدات — ${esc(x.title)}</h3><p class="muted">اختر الوحدة ثم اضغط موضعها على المخطط. اضغط على علامة قائمة لإزالتها.</p>
    <div class="toolbar"><select id="mku">${list.map(u => `<option value="${esc(u.code)}">${esc(u.code)} · ${esc(u.type)}</option>`).join('')}</select><span class="muted">${N(markers.length)} وحدة محددة</span></div>
    ${planImg(x, markers, null, 'edit')}<div class="btns" style="margin-top:12px"><button class="btn p" id="mksave">حفظ</button><button class="btn" data-call="closeModal">إغلاق</button></div>`);
    const box = document.querySelector('.plan.edit');
    box.onclick = ev => { const mk = ev.target.closest('.mk'); if (mk) { markers = markers.filter(m => m.unit_code !== mk.title); return draw(); }
      const r = box.querySelector('img').getBoundingClientRect(); const xp = (ev.clientX - r.left) / r.width * 100, yp = (ev.clientY - r.top) / r.height * 100; if (xp < 0 || xp > 100 || yp < 0 || yp > 100) return;
      const code = $('#mku').value; markers = markers.filter(m => m.unit_code !== code).concat([{unit_code: code, x: +xp.toFixed(2), y: +yp.toFixed(2)}]); draw(); };
    $('#mksave').onclick = async () => { await tryDo(() => api(`/plans/${id}/markers`, {method: 'POST', body: {markers}}), 'حُفظت المواقع'); closeModal(); EXT.plans(); };
  };
  draw();
};

/* ================================================================ الوحدة 7: التقارير والتحليلات */
const RF = {money: v => OMR(v), pct: v => (v === null || v === undefined ? '—' : N(v) + '٪'), num: v => (typeof v === 'number' ? (Number.isInteger(v) ? N(v) : ND(v)) : esc(v)), int: v => N(v), date: v => (v ? fmtDate(v) : '—'), bool: v => (v ? 'نعم' : 'لا'), text: v => esc(v ?? '—'), enum: v => esc(v ?? '—')};
const fmtCell = (v, t) => (v === null || v === undefined || v === '') ? '—' : (RF[t] || RF.text)(v);
let REP = {cat: null, doc: null, ctx: null};
EXT.l_rep = async function () {
  const k = this.cur.rep, el = $('#rep');
  el.innerHTML = SUB('rep', [['ready', 'التقارير الجاهزة'], ['custom', 'منشئ التقارير'], ['saved', 'المحفوظة والمجدولة'], ['lender', 'تقارير الممولين']], k) + '<div id="repB">…</div>';
  const B = $('#repB');
  if (!REP.cat) REP.cat = await api('/reports/catalog');
  if (k === 'lender') return EXT.l_lender(B);
  if (k === 'saved') return EXT.repSaved(B);
  if (k === 'custom') return EXT.repBuilder(B);
  const groups = {};
  for (const r of REP.cat.ready) (groups[r.group] = groups[r.group] || []).push(r);
  B.innerHTML = Object.entries(groups).map(([g, items]) => BOX(g, `<div class="rcards">${items.map(r => `<button class="rcard" data-call="EXT.repOpen" data-args="${J(['ready', r.key])}"><b>${esc(r.title)}</b><span>${esc(r.desc)}</span></button>`).join('')}</div>`)).join('')
    + BOX('تقارير خارجية', `<div class="rcards">${REP.cat.links.map(l => `<button class="rcard" data-call="EXT.sub" data-args="${J(['rep', 'lender'])}"><b>${esc(l.title)}</b><span>للبنك الممول والمستثمرين</span></button>`).join('')}</div>`)
    + '<div id="repView"></div>';
};
EXT.repOpen = async (kind, ref, params = {}, savedId = null) => {
  const B = $('#repB');
  if (!B) return;
  REP.ctx = {kind, ref, params, savedId};
  let doc;
  try { doc = kind === 'ready' ? await api(`/reports/ready/${ref}?` + new URLSearchParams(params)) : kind === 'saved' ? await api(`/reports/saved/${savedId}/run?` + new URLSearchParams(params)) : await api('/reports/custom/run', {method: 'POST', body: ref}); }
  catch (e) { return toast(e.message, 1); }
  REP.doc = doc;
  const pOpts = `<option value="">كل المشاريع</option>` + REP.cat.projects.map(p => `<option value="${p.id}" ${String(params.project_id) === String(p.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
  B.innerHTML = `<div class="toolbar"><button class="btn" data-call="EXT.sub" data-args="${J(['rep', kind === 'custom' ? 'custom' : 'ready'])}">← رجوع</button>
    ${kind !== 'custom' ? `<label>من</label><input type="date" id="rpFrom" value="${esc(params.from || '')}"><label>إلى</label><input type="date" id="rpTo" value="${esc(params.to || '')}"><select id="rpProj">${pOpts}</select><button class="btn p" id="rpRun">تحديث</button>` : ''}
    <span class="btns" style="margin-inline-start:auto"><button class="btn" data-call="EXT.repExport" data-args="${J(['csv'])}">CSV</button><button class="btn" data-call="EXT.repExport" data-args="${J(['pdf'])}">PDF</button>${can('reports') && kind !== 'saved' ? `<button class="btn" data-call="EXT.repSave">حفظ</button>` : ''}${savedId && can('reports') ? `<button class="btn" data-call="EXT.repSchedule" data-args="${J([savedId])}">جدولة بالبريد</button>` : ''}</span></div>`
    + renderDoc(doc);
  doc.charts.forEach((ch, i) => CH.render($(`#ch${i}`), ch));
  if ($('#rpRun')) $('#rpRun').onclick = () => EXT.repOpen(kind, ref, {from: $('#rpFrom').value, to: $('#rpTo').value, project_id: $('#rpProj').value}, savedId);
};
function renderDoc(doc) {
  const kp = doc.kpis && doc.kpis.length ? KP(doc.kpis.slice(0, 4).map(k => [k.label, fmtCell(k.value, k.format || 'num'), k.hint || ''])) : '';
  const charts = doc.charts.length ? `<div class="chgrid">${doc.charts.map((c, i) => `<div class="box"><div id="ch${i}" class="chbox"></div></div>`).join('')}</div>` : '';
  const tables = doc.tables.map((t, ti) => BOX(`${esc(t.title)} <span class="muted">${N(t.rows.length)} صف</span>`, T(t.columns.map(c => esc(c.label)), t.rows.slice(0, 400).map(r => `<tr>${t.columns.map(c => `<td>${fmtCell(r[c.key], c.type)}</td>`).join('')}</tr>`)), `<button class="btn" data-call="EXT.repExport" data-args="${J(['csv', ti])}">CSV</button>`)).join('');
  const notes = (doc.notes || []).filter(Boolean).map(n => `<div class="muted">• ${esc(n)}</div>`).join('');
  return `<h2 style="margin:6px 0 2px">${esc(doc.title)}</h2><div class="muted" style="margin-bottom:12px">${esc(doc.subtitle || '')}</div>${kp}${charts}${tables}${notes}`;
}
EXT.repExport = async (format, table = 0) => {
  const c = REP.ctx; if (!c) return;
  const body = {format, table, kind: c.kind, ref: c.kind === 'ready' ? c.ref : null, spec: c.kind === 'custom' ? c.ref : null, params: c.params || {}, saved_id: c.savedId};
  try {
    const r = await fetch('/api/reports/export', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf()}, body: JSON.stringify(body)});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'تعذّر التصدير');
    const blob = await r.blob(); const url = URL.createObjectURL(blob);
    if (format === 'pdf') window.open(url, '_blank', 'noopener'); else { const a = document.createElement('a'); a.href = url; a.download = (REP.doc?.title || 'report') + '.csv'; a.click(); }
  } catch (e) { toast(e.message, 1); }
};
EXT.repSave = async () => {
  const c = REP.ctx; const name = prompt('اسم التقرير المحفوظ', REP.doc?.title || ''); if (!name) return;
  await tryDo(() => api('/reports/saved', {method: 'POST', body: {name, kind: c.kind, ref: c.kind === 'ready' ? c.ref : null, spec: c.kind === 'custom' ? c.ref : null, params: c.params || {}, shared: true}}), 'حُفظ التقرير');
};
EXT.repSaved = async (B) => {
  const [S_, SC] = await Promise.all([api('/reports/saved'), api('/reports/schedules')]);
  B.innerHTML = BOX('التقارير المحفوظة', T(['الاسم', 'النوع', 'المالك', 'مشترك', ''], S_.map(s => `<tr><td>${esc(s.name)}</td><td>${s.kind === 'ready' ? 'جاهز: ' + esc(s.ref) : 'مخصّص: ' + esc(s.spec?.dataset)}</td><td>${esc(s.owner)}</td><td>${s.shared ? 'نعم' : 'لا'}</td>
      <td class="btns"><button class="btn p" data-call="EXT.repOpen" data-args="${J(['saved', null, s.params || {}, s.id])}">فتح</button>${can('reports') ? `<button class="btn" data-call="EXT.repSchedule" data-args="${J([s.id])}">جدولة</button><button class="btn" data-call="EXT.repRemove" data-args="${J([s.id])}">حذف</button>` : ''}</td></tr>`), 'لا تقارير محفوظة بعد — افتح تقريرًا واضغط «حفظ».'))
    + BOX('الجدولة بالبريد', T(['التقرير', 'الدورية', 'الساعة', 'المستلمون', 'الصيغة', 'التالي', 'آخر إرسال', ''], SC.map(s => `<tr><td>${esc(s.report_name)}</td><td>${{daily: 'يوميًا', weekly: 'أسبوعيًا (الأحد)', monthly: 'شهريًا'}[s.cadence]}</td><td>${N(s.hour)}:00</td><td><span class="num">${esc(s.recipients)}</span></td><td>${esc(s.format)}</td><td>${esc(s.next_run || '')}</td><td>${esc(s.last_run || '—')}${s.last_error ? ` <span class="pill p-b" title="${esc(s.last_error)}">خطأ</span>` : ''}</td>
      <td>${can('reports') ? `<button class="btn" data-call="EXT.schedRemove" data-args="${J([s.id])}">إلغاء</button>` : ''}</td></tr>`), 'لا جدولة بعد.'));
};
EXT.repRemove = async id => { if (!confirm('حذف التقرير المحفوظ وجدولاته؟')) return; await tryDo(() => api(`/reports/saved/${id}/remove`, {method: 'POST'}), 'حُذف'); EXT.l_rep(); };
EXT.schedRemove = async id => { await tryDo(() => api(`/reports/schedules/${id}/remove`, {method: 'POST'}), 'أُلغيت الجدولة'); EXT.l_rep(); };
EXT.repSchedule = id => {
  modal(`<h3>جدولة تقرير بالبريد</h3><label>الدورية</label><select id="scC"><option value="daily">يوميًا</option><option value="weekly" selected>أسبوعيًا (صباح الأحد)</option><option value="monthly">شهريًا (أول الشهر)</option></select>
   <label>الساعة (0–23)</label><input id="scH" type="number" min="0" max="23" value="7" dir="ltr"><label>المستلمون (بريد، افصل بفاصلة)</label><input id="scR" dir="ltr" placeholder="ceo@…, cfo@…"><label>الصيغة</label><select id="scF"><option value="pdf">PDF</option><option value="csv">CSV</option></select>
   <div class="err" id="scE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="scGo">جدولة</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#scGo').onclick = async () => { try { await api('/reports/schedules', {method: 'POST', body: {report_id: id, cadence: $('#scC').value, hour: +$('#scH').value, recipients: $('#scR').value, format: $('#scF').value}}); closeModal(); toast('جُدول التقرير'); EXT.cur.rep = 'saved'; EXT.l_rep(); } catch (e) { $('#scE').textContent = e.message; } };
};
/* منشئ التقارير */
let RB = {ds: null, cols: [], filters: [], groups: [], aggs: [], sort: null, chart: 'bar'};
EXT.repBuilder = (B) => {
  const ds = REP.cat.datasets; if (!RB.ds) RB.ds = ds[0]?.key;
  const d = ds.find(x => x.key === RB.ds) || ds[0];
  const colOpt = (sel, numOnly = false) => d.columns.filter(c => !numOnly || ['num', 'money', 'int', 'pct'].includes(c.type)).map(c => `<option value="${c.key}" ${sel === c.key ? 'selected' : ''}>${esc(c.label)}</option>`).join('');
  const ops = t => (t === 'text' || t === 'enum') ? [['eq', 'يساوي'], ['ne', 'لا يساوي'], ['contains', 'يحتوي'], ['null', 'فارغ'], ['notnull', 'غير فارغ']] : (t === 'date') ? [['between', 'بين'], ['gte', 'من'], ['lte', 'إلى']] : [['eq', '='], ['ne', '≠'], ['gte', '≥'], ['lte', '≤'], ['between', 'بين']];
  B.innerHTML = `<div class="box"><div class="hd">1 · مجموعة البيانات</div><div style="padding:14px"><select id="rbDs">${ds.map(x => `<option value="${x.key}" ${x.key === d.key ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
    <div class="muted" style="margin-top:8px">الأعمدة: ${d.columns.map(c => `<label class="chk"><input type="checkbox" class="rbCol" value="${c.key}" ${RB.cols.length ? (RB.cols.includes(c.key) ? 'checked' : '') : 'checked'}> ${esc(c.label)}</label>`).join(' ')}</div></div></div>
   <div class="box"><div class="hd">2 · الفلاتر <button class="btn" id="rbAddF">+ فلتر</button></div><div style="padding:14px" id="rbF">${RB.filters.map((f, i) => `<div class="toolbar"><select class="rbFc" data-i="${i}">${colOpt(f.col)}</select><select class="rbFo" data-i="${i}">${ops((d.columns.find(c => c.key === f.col) || {}).type).map(([k, l]) => `<option value="${k}" ${f.op === k ? 'selected' : ''}>${l}</option>`).join('')}</select><input class="rbFv" data-i="${i}" value="${esc(Array.isArray(f.value) ? f.value.join(' , ') : (f.value ?? ''))}" placeholder="القيمة (للـ«بين»: أ , ب)"><button class="btn" data-call="EXT.rbDelF" data-args="${J([i])}">×</button></div>`).join('') || '<div class="muted">بلا فلاتر — كل الصفوف.</div>'}</div></div>
   <div class="box"><div class="hd">3 · التجميع والمقاييس <span class="muted">اتركه فارغًا لعرض الصفوف كما هي</span></div><div style="padding:14px">
    <div class="toolbar"><label>تجميع حسب</label><select id="rbG"><option value="">—</option>${colOpt(RB.groups[0]?.col)}</select><select id="rbGb"><option value="">كما هو</option><option value="month" ${RB.groups[0]?.bucket === 'month' ? 'selected' : ''}>شهر</option><option value="year" ${RB.groups[0]?.bucket === 'year' ? 'selected' : ''}>سنة</option><option value="day" ${RB.groups[0]?.bucket === 'day' ? 'selected' : ''}>يوم</option></select>
     <label>ثم</label><select id="rbG2"><option value="">—</option>${colOpt(RB.groups[1]?.col)}</select></div>
    <div class="toolbar"><label>المقاييس</label><label class="chk"><input type="checkbox" id="rbCount" ${RB.aggs.some(a => a.fn === 'count') || !RB.aggs.length ? 'checked' : ''}> العدد</label>
     <select id="rbAggFn"><option value="sum">مجموع</option><option value="avg">متوسط</option><option value="min">أدنى</option><option value="max">أعلى</option></select><select id="rbAggCol">${colOpt(null, true)}</select><button class="btn" id="rbAddA">+ مقياس</button>
     <span id="rbAggs">${RB.aggs.filter(a => a.fn !== 'count').map((a, i) => `<span class="pill p-bl">${{sum: 'مجموع', avg: 'متوسط', min: 'أدنى', max: 'أعلى'}[a.fn]} ${esc((d.columns.find(c => c.key === a.col) || {}).label)} <button class="link" data-call="EXT.rbDelA" data-args="${J([i])}">×</button></span>`).join(' ')}</span></div></div></div>
   <div class="box"><div class="hd">4 · الرسم البياني والترتيب</div><div style="padding:14px" class="toolbar"><select id="rbChart"><option value="bar">أعمدة</option><option value="stacked">أعمدة مكدّسة</option><option value="line">خط</option><option value="pie">دائري</option><option value="none">بلا رسم</option></select>
    <label>ترتيب</label><select id="rbSort"><option value="">افتراضي</option>${d.columns.map(c => `<option value="${c.key}">${esc(c.label)}</option>`).join('')}</select><select id="rbDir"><option value="desc">تنازلي</option><option value="asc">تصاعدي</option></select>
    <label>حد الصفوف</label><input id="rbLim" type="number" value="500" min="1" max="5000" dir="ltr" style="width:90px"><input id="rbTitle" placeholder="عنوان التقرير (اختياري)" style="min-width:220px"><button class="btn p" id="rbRun">تشغيل</button></div></div><div id="rbOut"></div>`;
  $('#rbChart').value = RB.chart;
  $('#rbDs').onchange = e => { RB = {ds: e.target.value, cols: [], filters: [], groups: [], aggs: [], sort: null, chart: 'bar'}; EXT.repBuilder(B); };
  $('#rbAddF').onclick = () => { readRB(); RB.filters.push({col: d.columns[0].key, op: 'eq', value: ''}); EXT.repBuilder(B); };
  $('#rbAddA').onclick = () => { readRB(); RB.aggs.push({fn: $('#rbAggFn').value, col: $('#rbAggCol').value}); EXT.repBuilder(B); };
  $('#rbRun').onclick = async () => {
    readRB();
    const spec = {dataset: RB.ds, columns: RB.cols.length === d.columns.length ? [] : RB.cols, filters: RB.filters.map(f => ({col: f.col, op: f.op, value: f.op === 'between' ? String(f.value).split(',').map(x => x.trim()) : (f.op === 'null' || f.op === 'notnull') ? null : f.value})),
      group_by: RB.groups, aggs: RB.groups.length ? (($('#rbCount').checked ? [{fn: 'count'}] : []).concat(RB.aggs.filter(a => a.fn !== 'count'))) : [], sort: RB.sort ? [RB.sort] : [], limit: +$('#rbLim').value || 500,
      chart: {type: RB.chart, x: RB.groups[0] ? (RB.groups[0].bucket ? `${RB.groups[0].col}_${RB.groups[0].bucket}` : RB.groups[0].col) : null, y: []}, title: $('#rbTitle').value.trim() || null};
    REP.ctx = {kind: 'custom', ref: spec, params: {}};
    try { const doc = await api('/reports/custom/run', {method: 'POST', body: spec}); REP.doc = doc; $('#rbOut').innerHTML = `<div class="toolbar"><span class="btns"><button class="btn" data-call="EXT.repExport" data-args="${J(['csv'])}">CSV</button><button class="btn" data-call="EXT.repExport" data-args="${J(['pdf'])}">PDF</button>${can('reports') ? '<button class="btn" data-call="EXT.repSave">حفظ</button>' : ''}</span></div>` + renderDoc(doc); doc.charts.forEach((ch, i) => CH.render($(`#ch${i}`), ch)); $('#rbOut').scrollIntoView({behavior: 'smooth'}); }
    catch (e) { toast(e.message, 1); }
  };
  function readRB() {
    RB.cols = $$('.rbCol:checked').map(x => x.value);
    RB.filters = $$('.rbFc').map((sel, i) => ({col: sel.value, op: $$('.rbFo')[i].value, value: $$('.rbFv')[i].value}));
    RB.groups = []; if ($('#rbG').value) RB.groups.push({col: $('#rbG').value, bucket: $('#rbGb').value || null}); if ($('#rbG2').value) RB.groups.push({col: $('#rbG2').value});
    RB.chart = $('#rbChart').value; RB.sort = $('#rbSort').value ? {col: $('#rbSort').value, dir: $('#rbDir').value} : null;
  }
  EXT.rbDelF = i => { readRB(); RB.filters.splice(i, 1); EXT.repBuilder(B); };
  EXT.rbDelA = i => { readRB(); RB.aggs.splice(i, 1); EXT.repBuilder(B); };
};

/* ================================================================ الوحدة 7: تسويق المشاريع */
const MKS = {launch: 'p-bl', steady: 'p-ok', near_complete: 'p-w', slow: 'p-b', completed: '', sold_out: 'p-ok'};
let MK = {meta: null, board: null};
EXT.l_mk = async function () {
  const k = this.cur.mk, el = $('#mk');
  el.innerHTML = SUB('mk', [['board', 'لوحة التسويق'], ['camp', 'الحملات'], ['studio', 'استوديو الإعلانات'], ['alerts', 'التنبيهات التسويقية']], k) + '<div id="mkB">…</div>';
  const B = $('#mkB');
  if (!MK.meta) MK.meta = await api('/campaigns/meta');
  if (k === 'camp') return EXT.mkCampaigns(B);
  if (k === 'studio') return EXT.mkStudio(B);
  if (k === 'alerts') return EXT.mkAlerts(B);
  const b = await api('/marketing/board'); MK.board = b;
  const sum = b.summary;
  B.innerHTML = KP([['إطلاق', N(sum.launch)], ['ضعيف البيع', N(sum.slow), 'يحتاج تدخلًا'], ['شبه مكتمل', N(sum.near_complete)], ['مستقر/مكتمل', N(sum.steady + sum.completed + sum.sold_out)]])
    + `<div class="mkgrid">${b.projects.map(p => `<div class="box mkcard"><div class="hd"><span><b>${esc(p.project)}</b> <span class="muted">${esc(p.location)}</span></span>${pill(p.status_label, MKS[p.status])}</div>
      <div class="mkk"><div><small>متاح</small><b>${N(p.available)}</b><small>من ${N(p.total)} · ${N(p.sold_pct)}٪ مبيع</small></div><div><small>وتيرة 30 يومًا</small><b>${N(p.pace30)}</b><small>${p.planned_monthly ? 'مخطط ' + N(p.planned_monthly) + (p.pace_ratio !== null ? ' · ' + ND(p.pace_ratio, 2) + '×' : '') : '—'}</small></div>
        <div><small>الطلب النسبي</small><b>${ND(p.demand_ratio, 2)}×</b><small>↑${N(p.raise_segments)} ↓${N(p.cut_segments)} شرائح</small></div><div><small>عملاء 30 يومًا</small><b>${N(p.leads30)}</b><small>${p.conversion90 !== null ? 'تحويل 90 يومًا ' + N(p.conversion90) + '٪' : 'لا بيانات تحويل'} · متوقفون ${N(p.stale_leads)}</small></div></div>
      <div class="bar-s" title="الإنجاز ${N(p.build_pct)}٪"><i style="width:${p.build_pct}%"></i></div><div class="muted" style="font-size:12px;margin:4px 0 8px">الإنجاز ${N(p.build_pct)}٪ · قيمة غير المباع ${OMR(p.unsold_value)} · في السوق ${N(p.days_on_market)} يومًا · حملات نشطة ${N(p.active_campaigns)}</div>
      ${p.flags.length ? `<div class="ai">${p.flags.map(f => '⚠ ' + esc(f)).join('<br>')}</div>` : ''}
      <details><summary class="muted">الإجراءات المقترحة (${N(p.actions.length)})</summary><ul class="acts">${p.actions.map(a => `<li><b>${esc(a.title)}</b><div class="muted">${esc(a.detail)}</div></li>`).join('')}</ul></details>
      <div class="btns" style="margin-top:8px">${can('leads') ? `<button class="btn p" data-call="EXT.mkNewCampaign" data-args="${J([p.project_id, p.status])}">حملة جديدة</button><button class="btn" data-call="EXT.mkStudioFor" data-args="${J([p.project_id, p.status])}">إعلان</button>` : ''}<button class="btn" data-call="EXT.repOpenFromMk" data-args="${J([p.project_id])}">تقرير المبيعات</button></div></div>`).join('')}</div>`;
};
EXT.repOpenFromMk = pid => { EXT.cur.rep = 'ready'; go('rep'); setTimeout(() => EXT.repOpen('ready', 'sales', {project_id: pid}), 400); };
const camStatus = {draft: ['مسودة', ''], active: ['نشطة', 'p-ok'], paused: ['متوقفة', 'p-w'], done: ['منتهية', 'p-bl']};
EXT.mkCampaigns = async (B, openId = null) => {
  const C = await api('/campaigns');
  B.innerHTML = BOX('الحملات', T(['الحملة', 'المشروع', 'الهدف', 'القنوات', 'الجمهور', 'الميزانية', 'عملاء', 'عروض', 'حجوزات', 'كلفة العميل', 'الحالة', ''], C.map(c => `<tr><td><b>${esc(c.name)}</b><br><span class="muted num">${esc(c.utm)}</span></td><td>${esc(c.project)}</td><td>${esc(c.objective_label)}</td><td>${c.channel_labels.map(esc).join('، ')}</td><td>${esc(c.audience_label)}</td><td>${OMR(c.budget)}</td><td>${N(c.metrics.leads)}</td><td>${N(c.metrics.quotes)}</td><td>${N(c.metrics.bookings)}<br><span class="muted">${OMR(c.metrics.value)}</span></td><td>${c.metrics.cpl !== null ? OMR(c.metrics.cpl) : '—'}</td><td>${pill(...camStatus[c.status])}</td>
      <td class="btns"><button class="btn p" data-call="EXT.mkOpen" data-args="${J([c.id])}">فتح</button></td></tr>`), 'لا حملات بعد.'), can('leads') ? '<button class="btn p" data-call="EXT.mkNewCampaign">+ حملة</button>' : '') + '<div id="mkDetail"></div>';
  if (openId) EXT.mkOpen(openId);
};
EXT.mkOpen = async id => {
  const [c, a] = await Promise.all([api(`/campaigns/${id}`), api(`/campaigns/${id}/audience`)]);
  const D = $('#mkDetail'); if (!D) return;
  D.innerHTML = BOX(`${esc(c.name)} <span class="muted">${esc(c.project)} · ${esc(c.objective_label)} · رمز التتبع <span class="num">${esc(c.utm)}</span></span>`, `<div style="padding:14px">
    ${KP([['عملاء منسوبون', N(c.metrics.leads), 'عبر رمز التتبع'], ['عروض أسعار', N(c.metrics.quotes)], ['حجوزات', N(c.metrics.bookings), OMR(c.metrics.value)], ['كلفة العميل', c.metrics.cpl !== null ? OMR(c.metrics.cpl) : '—', 'الميزانية ' + OMR(c.budget)]])}
    <div class="muted">العرض: ${esc(c.offer_text || '—')} · الرسالة: ${esc(c.message || '—')} · ${esc(c.start_date || '')} ← ${esc(c.end_date || '')}</div>
    <div class="ai" style="margin-top:10px"><b class="k">الجمهور (${esc(c.audience_label)}):</b> ${N(a.count)} مستلمًا · ${N(a.with_phone)} بهاتف · ${N(a.with_email)} ببريد</div>
    ${c.creatives.length ? `<div class="muted">إعلانات مرتبطة: ${c.creatives.map(x => `<a href="/api/documents/${x.document_id}" target="_blank" rel="noopener">${esc(x.headline || x.template)}</a>`).join(' · ')}</div>` : ''}
    ${can('leads') ? `<div class="toolbar" style="margin-top:10px"><select id="mkCr"><option value="">بلا إعلان مرفق</option>${c.creatives.map(x => `<option value="${x.id}">${esc(x.headline || x.template)} (${esc(x.size)})</option>`).join('')}</select><input id="mkMsg" placeholder="نص الرسالة (اختياري — يُستعمل نص الحملة)" style="min-width:260px">
      <button class="btn p" data-call="EXT.mkSend" data-args="${J([c.id, 'whatsapp'])}">إرسال واتساب</button><button class="btn" data-call="EXT.mkSend" data-args="${J([c.id, 'email'])}">إرسال بريد</button>
      ${c.status !== 'done' ? `<button class="btn" data-call="EXT.mkStatus" data-args="${J([c.id, c.status === 'active' ? 'paused' : 'active'])}">${c.status === 'active' ? 'إيقاف مؤقت' : 'تفعيل'}</button><button class="btn" data-call="EXT.mkStatus" data-args="${J([c.id, 'done'])}">إنهاء</button>` : ''}</div>` : ''}
    <div id="mkSendOut"></div>
    <details style="margin-top:10px"><summary class="muted">قائمة المستلمين</summary>${T(['الاسم', 'الهاتف', 'البريد', 'النوع'], a.recipients.slice(0, 200).map(r => `<tr><td>${esc(r.name)}</td><td><span class="num">${esc(r.phone || '—')}</span></td><td><span class="num">${esc(r.email || '—')}</span></td><td>${esc(r.kind)}</td></tr>`))}</details></div>`);
  D.scrollIntoView({behavior: 'smooth'});
};
EXT.mkStatus = async (id, st) => { await tryDo(() => api(`/campaigns/${id}/status`, {method: 'POST', body: {status: st}}), 'حُدّثت الحالة'); EXT.mkCampaigns($('#mkB'), id); };
EXT.mkSend = async (id, channel) => {
  if (!confirm(channel === 'whatsapp' ? 'إنشاء روابط واتساب لكل مستلم (حتى 200)؟ تُفتح واحدًا واحدًا من جهازك.' : 'إرسال بريد لكل مستلم له بريد؟')) return;
  const r = await tryDo(() => api(`/campaigns/${id}/send`, {method: 'POST', body: {channel, creative_id: +$('#mkCr').value || null, message: $('#mkMsg').value.trim() || null, limit: 200}}));
  if (!r) return;
  $('#mkSendOut').innerHTML = `<div class="ai">${channel === 'email' ? `أُرسل ${N(r.sent)} بريدًا · تخطّي ${N(r.skipped)} بلا بريد` : `${N(r.sent)} رابط مراسلة جاهز · تخطّي ${N(r.skipped)} بلا هاتف<br><span class="muted">${esc(r.note)}</span>`}</div>`
    + (channel === 'whatsapp' ? `<div class="wal">${r.items.map(it => `<a class="btn" href="${it.wa_url}" target="_blank" rel="noopener">${esc(it.name)} · <span class="num">${esc(it.phone)}</span></a>`).join('')}</div>` : '');
};
EXT.mkNewCampaign = (pid = null, status = null) => {
  const m = MK.meta; const projs = (MK.board?.projects || REP.cat?.projects || S.projects).map(p => ({id: p.project_id || p.id, name: p.project || p.name}));
  const objDefault = {launch: 'launch', near_complete: 'near_complete', slow: 'slow', completed: 'near_complete'}[status] || 'awareness';
  modal(`<h3>حملة تسويقية جديدة</h3><label>المشروع</label><select id="cmP">${projs.map(p => `<option value="${p.id}" ${p.id === pid ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select><label>اسم الحملة</label><input id="cmN">
   <label>الهدف</label><select id="cmO">${Object.entries(m.objectives).map(([k, v]) => `<option value="${k}" ${k === objDefault ? 'selected' : ''}>${v}</option>`).join('')}</select>
   <label>القنوات</label><div>${Object.entries(m.channels).map(([k, v]) => `<label class="chk"><input type="checkbox" class="cmCh" value="${k}" ${['whatsapp', 'instagram'].includes(k) ? 'checked' : ''}> ${v}</label>`).join(' ')}</div>
   <label>الجمهور</label><select id="cmA">${Object.entries(m.segments).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
   <div class="grid2"><div><label>الميزانية (ر.ع)</label><input id="cmB" type="number" value="0" dir="ltr"></div><div><label>من</label><input id="cmS" type="date"></div><div><label>إلى</label><input id="cmE" type="date"></div></div>
   <label>العرض/الحافز (هيكلي، بلا فائدة)</label><input id="cmOf" placeholder="مثال: تأجيل الدفعة الثانية 3 أشهر · إعفاء من رسوم نقل الملكية"><label>نص الرسالة للمستلمين</label><textarea id="cmM" rows="3"></textarea>
   <div class="err" id="cmErr"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="cmGo">إنشاء</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#cmGo').onclick = async () => { try { const c = await api('/campaigns', {method: 'POST', body: {project_id: +$('#cmP').value, name: $('#cmN').value.trim(), objective: $('#cmO').value, channels: $$('.cmCh:checked').map(x => x.value), audience: $('#cmA').value, budget: +$('#cmB').value || 0, start_date: $('#cmS').value || null, end_date: $('#cmE').value || null, offer_text: $('#cmOf').value.trim() || null, message: $('#cmM').value.trim() || null}}); closeModal(); toast(`أُنشئت الحملة · رمز التتبع ${c.utm}`); EXT.cur.mk = 'camp'; EXT.l_mk().then(() => EXT.mkOpen(c.id)); } catch (e) { $('#cmErr').textContent = e.message; } };
};
EXT.mkStudioFor = (pid, status) => { EXT.cur.mk = 'studio'; MK.studioPid = pid; MK.studioTpl = {launch: 'launch', near_complete: 'ready', slow: 'offer', completed: 'ready', sold_out: 'progress'}[status] || 'teaser'; EXT.l_mk(); };
EXT.mkStudio = async (B) => {
  const m = MK.meta; const projs = S.projects;
  const [C, L] = await Promise.all([api('/creatives'), api('/campaigns')]);
  B.innerHTML = BOX('تصميم إعلان', `<div style="padding:14px"><div class="grid2">
    <div><label>المشروع</label><select id="adP">${projs.map(p => `<option value="${p.id}" ${p.id === MK.studioPid ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
    <div><label>القالب</label><select id="adT">${Object.entries(m.templates).map(([k, v]) => `<option value="${k}" ${k === MK.studioTpl ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
    <div><label>المقاس</label><select id="adS">${Object.entries(m.sizes).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
    <div><label>الألوان</label><select id="adC">${m.palettes.map(p => `<option value="${p}">${{gold: 'ذهبي داكن', green: 'أخضر', blue: 'أزرق', sand: 'رملي فاتح'}[p] || p}</option>`).join('')}</select></div>
    <div><label>العنوان (اختياري — يُولَّد من القالب)</label><input id="adH"></div><div><label>السطر الثاني</label><input id="adSub"></div>
    <div><label>نص العرض (لقالب العرض)</label><input id="adOf" placeholder="إعفاء من رسوم نقل الملكية"></div><div><label>العرض ساري حتى</label><input id="adU" type="date"></div>
    <div><label>زر الدعوة</label><input id="adCta" placeholder="احجز معاينتك"></div><div><label>خطة السداد المعروضة</label><select id="adPl"><option value="">—</option><option value="6040">60/40</option><option value="milestone">مرتبطة بمراحل الإنجاز</option><option value="murabaha">مرابحة بنكية</option></select></div>
    <div><label>صورة خلفية (اختياري — PNG/JPEG، مثل التصور النهائي)</label><input type="file" id="adBg" accept=".png,.jpg,.jpeg"></div><div><label>ربط بحملة</label><select id="adCamp"><option value="">—</option>${L.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="adGo">توليد الإعلان</button></div><div class="muted" style="margin-top:6px">النص يُركَّب برمجيًا بخط المنصة؛ لا صور أشخاص ولا نصوص مولَّدة بالصور. العروض الربوية مرفوضة.</div></div>`)
    + BOX('الإعلانات المولَّدة', `<div class="gal adgal">${C.map(c => `<figure><img src="${c.png_url || c.pdf_url}" alt="" loading="lazy"><figcaption><b>${esc(c.template_label)}</b> · ${esc(c.project)} · ${esc(c.size)}<div class="btns" style="margin-top:4px"><a class="btn" href="${c.png_url}" download>PNG</a><a class="btn" href="${c.pdf_url}" target="_blank" rel="noopener">PDF</a><button class="btn" data-call="EXT.adSend" data-args="${J([c.id, 'whatsapp'])}">واتساب</button><button class="btn" data-call="EXT.adSend" data-args="${J([c.id, 'email'])}">بريد</button></div></figcaption></figure>`).join('') || '<div class="muted">لم يُولَّد إعلان بعد.</div>'}</div>`);
  $('#adGo').onclick = async () => {
    let bg = null; const f = $('#adBg').files[0];
    try {
      if (f) { const fd = new FormData(); fd.append('ref_type', 'campaign'); fd.append('ref_id', $('#adP').value); fd.append('title', 'خلفية إعلان'); fd.append('category', 'إعلان'); fd.append('file', f);
        const r = await fetch('/api/documents', {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}); const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'تعذّر رفع الصورة'); bg = j.id; }
      const cr = await api('/creatives', {method: 'POST', body: {project_id: +$('#adP').value, campaign_id: +$('#adCamp').value || null, template: $('#adT').value, size: $('#adS').value, palette: $('#adC').value, headline: $('#adH').value.trim() || null, subline: $('#adSub').value.trim() || null, cta: $('#adCta').value.trim() || null, offer: $('#adOf').value.trim() || null, until: $('#adU').value || null, bg_document_id: bg, plan: $('#adPl').value || null}});
      modal(`<h3>✓ الإعلان جاهز</h3><img src="${cr.png_url}" alt="" style="max-width:100%;border-radius:10px"><div class="btns" style="margin-top:10px"><a class="btn p" href="${cr.png_url}" download>تنزيل PNG</a><a class="btn" href="${cr.pdf_url}" target="_blank" rel="noopener">PDF للطباعة</a><button class="btn" data-call="EXT.adSend" data-args="${J([cr.id, 'whatsapp'])}">واتساب</button><button class="btn" data-call="EXT.adSend" data-args="${J([cr.id, 'email'])}">بريد</button><button class="btn" data-call="closeModal">إغلاق</button></div>`);
      EXT.l_mk();
    } catch (e) { toast(e.message, 1); }
  };
};
EXT.adSend = async (id, channel) => {
  const to = prompt(channel === 'whatsapp' ? 'رقم واتساب المستلم' : 'بريد المستلم', ''); if (!to) return;
  const r = await tryDo(() => api(`/creatives/${id}/send`, {method: 'POST', body: {channel, to: to.trim()}}));
  if (r && channel === 'whatsapp') window.open(r.wa_url, '_blank', 'noopener'); else if (r) toast(r.delivered ? 'أُرسل' : 'سُجّل في صندوق الصادر (البريد غير مهيّأ)');
};
EXT.mkAlerts = async (B) => {
  const A_ = await api('/marketing/alerts');
  const sev = {high: ['عالٍ', 'p-b'], medium: ['متوسط', 'p-w'], low: ['منخفض', 'p-bl']};
  B.innerHTML = `<div class="toolbar">${can('notify') ? '<button class="btn p" id="mkRun">تسجيل التنبيهات في الإشعارات الآن</button>' : ''}<span class="muted">تُحسب حيًّا من حركة السوق: الوتيرة، الطلب النسبي، تدفق العملاء، أعمار المخزون، العروض، الحملات — ويُسجَّلها النظام يوميًا في الإشعارات.</span></div>`
    + BOX(`التنبيهات التسويقية <span class="muted">${N(A_.length)}</span>`, T(['الخطورة', 'المشروع', 'التنبيه', 'التفاصيل', 'الإجراء المقترح'], A_.map(a => `<tr><td>${pill(...sev[a.severity])}</td><td>${esc(a.project)}</td><td><b>${esc(a.title)}</b></td><td>${esc(a.detail)}</td><td>${esc(a.action)}</td></tr>`), 'لا تنبيهات الآن — حركة المشاريع ضمن المخطط.'));
  if ($('#mkRun')) $('#mkRun').onclick = async () => { const r = await tryDo(() => api('/marketing/alerts/run', {method: 'POST'})); toast(`سُجّل ${N(r.created)} تنبيهًا جديدًا`); };
};

/* ================================================================ المحاسبة — النواة المحاسبية (0.23.0) */
EXT.cur.acc = 'ov';
const ACC_TYPE = {asset: 'أصول', liability: 'التزامات', equity: 'حقوق ملكية', revenue: 'إيرادات', expense: 'مصروفات'};
const ACC_JST = {draft: ['مسودة', 'p-w'], pending: ['بانتظار الاعتماد', 'p-bl'], posted: ['مرحَّل', 'p-ok'], reversed: ['معكوس', 'p-b']};
const A3 = v => new Intl.NumberFormat('ar-OM-u-nu-latn', {minimumFractionDigits: 3, maximumFractionDigits: 3}).format(+v || 0);
const ACCAP = () => can('accounting_approve');
const accToday = () => new Date().toISOString().slice(0, 10);

EXT.l_acc = async function () {
  const tabs = [['ov', 'نظرة عامة'], ['tb', 'ميزان المراجعة'], ['jr', 'القيود'], ['gl', 'دفتر الأستاذ'], ['ap', 'الذمم الدائنة'], ['bk', 'البنوك والمطابقة'], ['rp', 'القوائم المالية'], ['as', 'الأصول والتمويل والضريبة'], ['ch', 'دليل الحسابات'], ['st', 'الافتتاحي والفترات']], el = $('#acc'), k = this.cur.acc;
  el.innerHTML = SUB0('acc', tabs, k) + '<div id="accB">…</div>';
  const B = $('#accB');
  if (k === 'ov') {
    const s = await api('/acc/status');
    if (!s.active) {
      B.innerHTML = BOX('تفعيل المحاسبة', `<p>لم تُفعَّل المحاسبة بعد، ولا يُرحَّل أي حدث إلى الدفاتر قبل التفعيل. عند التفعيل يُبذر الدليل العُماني الافتراضي، وتبدأ الدفاتر من التاريخ الذي تختاره: <b>الأحداث السابقة له لا تُرحَّل</b> — تدخل في رصيد افتتاحي واحد من ميزان مراجعة موثَّق.</p>`
        + (ACCAP() ? '<div class="btns"><button class="btn p" data-call="EXT.accActivate">تفعيل المحاسبة…</button></div>' : '<p class="muted">يفعّلها المدير العام.</p>'));
      return;
    }
    const u = s.unposted, bad = Math.abs(s.ledger_diff) > 0.0005, jc = s.journals;
    B.innerHTML = KP([['بدء المحاسبة', fmtDate(s.start)], ['الحسابات', N(s.accounts)], ['قيود مرحَّلة', N((jc.posted || 0) + (jc.reversed || 0))], ['بانتظار الاعتماد', N(jc.pending || 0)], ['مسودات', N(jc.draft || 0)],
        ['توازن الدفتر', bad ? pill('مختل ' + A3(s.ledger_diff), 'p-b') : pill('متوازن', 'p-ok')]])
      + BOX('أحداث لم تُرحَّل بعد', u.total ? T(['النوع', 'العدد'], Object.entries(u.counts).filter(([, v]) => v).map(([a, v]) => `<tr><td>${esc({dues: 'استحقاقات مستحقة', payments: 'حركات تحصيل', charity: 'تبرعات التأخير', expenses: 'مصروفات عقارات', statements: 'كشوف الملاك', deposits: 'تسويات التأمين', payroll: 'رواتب وسلف ومخالصات'}[a])}</td><td>${pill(N(v), 'p-w')}</td></tr>`))
        : '<p class="muted">كل أحداث التأجير مرحَّلة إلى الدفاتر.</p>', can('accounting') ? '<button class="btn p" data-call="EXT.accSync">ترحيل الآن</button>' : '')
      + BOX('الرصيد الافتتاحي', s.opening ? `<p>مرحَّل بالقيد <span class="num">${esc(s.opening.number)}</span> بتاريخ ${fmtDate(s.opening.jdate)}.</p>` : '<p class="muted">لم يُدخل بعد — من تبويب «الافتتاحي والفترات».</p>');
  } else if (k === 'tb') {
    const to = this.accTo || accToday(), frm = this.accFrm || to.slice(0, 4) + '-01-01', tb = await api(`/acc/trial-balance?frm=${frm}&to=${to}`);
    B.innerHTML = `<div class="toolbar"><label>من</label> <input id="tbf" type="date" value="${frm}"> <label>إلى</label> <input id="tbt" type="date" value="${to}"> <a class="btn" href="/api/acc/trial-balance?csv=1&frm=${frm}&to=${to}">تصدير CSV</a></div>`
      + BOX('ميزان المراجعة ' + (tb.balanced ? pill('متوازن', 'p-ok') : pill('غير متوازن', 'p-b')), T(['الرمز', 'الحساب', 'افتتاحي', 'مدين', 'دائن', 'ختامي'],
        tb.accounts.map(a => `<tr data-id="${a.id}" style="${a.postable ? '' : 'font-weight:700'}"><td><span class="num">${esc(a.code)}</span></td><td>${esc(a.name)}</td><td>${A3(a.opening)}</td><td>${A3(a.debit)}</td><td>${A3(a.credit)}</td><td><b>${A3(a.closing)}</b></td></tr>`)
        .concat([`<tr style="font-weight:700"><td></td><td>الإجمالي</td><td>${A3(tb.totals.opening)}</td><td>${A3(tb.totals.debit)}</td><td>${A3(tb.totals.credit)}</td><td>${A3(tb.totals.closing)}</td></tr>`]), 'لا حركات في المدة.'));
    $('#tbf').onchange = e => { EXT.accFrm = e.target.value; EXT.l_acc(); }; $('#tbt').onchange = e => { EXT.accTo = e.target.value; EXT.l_acc(); };
    $$('#accB tr[data-id]').forEach(tr => tr.onclick = () => { EXT.accGl = +tr.dataset.id; EXT.cur.acc = 'gl'; EXT.l_acc(); });
  } else if (k === 'jr') {
    const st = this.accSt || '', R = await api(`/acc/journals?limit=200${st ? '&status=' + st : ''}`);
    B.innerHTML = `<div class="toolbar"><select id="jst"><option value="">كل الحالات</option>${Object.entries(ACC_JST).map(([a, [b]]) => `<option value="${a}" ${a === st ? 'selected' : ''}>${b}</option>`).join('')}</select></div>`
      + BOX(`القيود <span class="muted">${N(R.total)}</span>`, T(['الرقم', 'التاريخ', 'البيان', 'النوع', 'المبلغ', 'الحالة'], R.items.map(j => `<tr data-id="${j.id}"><td><span class="num">${esc(j.number || 'مسودة #' + j.id)}</span></td><td>${fmtDate(j.jdate)}</td><td>${esc(j.memo || '')}</td><td>${esc({manual: 'يدوي', auto: 'تلقائي', opening: 'افتتاحي', reversal: 'عكسي'}[j.kind])}</td><td>${A3(j.total)}</td><td>${pill(...ACC_JST[j.status])}</td></tr>`), 'لا قيود.'),
        can('accounting') ? '<button class="btn p" data-call="EXT.accNew">+ قيد يدوي</button>' : '');
    $('#jst').onchange = e => { EXT.accSt = e.target.value; EXT.l_acc(); };
    $$('#accB tr[data-id]').forEach(tr => tr.onclick = () => { sel(tr); EXT.accJ(+tr.dataset.id); });
  } else if (k === 'gl') {
    const A = await api('/acc/accounts'), id = this.accGl || (A.find(a => a.postable) || {}).id, to = this.accGlTo || accToday(), frm = this.accGlFrm || to.slice(0, 4) + '-01-01';
    const g = id ? await api(`/acc/ledger/${id}?frm=${frm}&to=${to}`) : null;
    B.innerHTML = `<div class="toolbar"><select id="glA">${A.map(a => `<option value="${a.id}" ${a.id === id ? 'selected' : ''}>${esc(a.code)} — ${esc(a.name)}</option>`).join('')}</select> <label>من</label> <input id="glf" type="date" value="${frm}"> <label>إلى</label> <input id="glt" type="date" value="${to}">${id ? ` <a class="btn" href="/api/acc/ledger/${id}?csv=1&frm=${frm}&to=${to}">تصدير CSV</a>` : ''}</div>`
      + (g ? BOX(`${esc(g.account.name)} — رصيد افتتاحي ${A3(g.opening)}`, T(['التاريخ', 'القيد', 'البيان', 'مدين', 'دائن', 'الرصيد'], g.lines.map(l => `<tr data-id="${l.journal_id}"><td>${fmtDate(l.jdate)}</td><td><span class="num">${esc(l.number)}</span></td><td>${esc(l.memo || l.journal_memo || '')}</td><td>${l.debit ? A3(l.debit) : ''}</td><td>${l.credit ? A3(l.credit) : ''}</td><td><b>${A3(l.balance)}</b></td></tr>`), 'لا حركات في المدة.')
        + `<p class="muted">الرصيد الختامي <b>${A3(g.closing)}</b> (موجب = مدين).</p>`) : '');
    const re = () => { EXT.accGl = +$('#glA').value; EXT.accGlFrm = $('#glf').value; EXT.accGlTo = $('#glt').value; EXT.l_acc(); };
    ['#glA', '#glf', '#glt'].forEach(s => $(s).onchange = re);
    $$('#accB tr[data-id]').forEach(tr => tr.onclick = () => EXT.accJ(+tr.dataset.id));
  } else if (k === 'ch') {
    const [A, M] = await Promise.all([api('/acc/accounts?balances=1'), api('/acc/mapping')]);
    B.innerHTML = BOX('دليل الحسابات', T(['الرمز', 'الحساب', 'النوع', 'الرصيد', 'الربط', ''], A.map(a => `<tr style="${a.postable ? '' : 'font-weight:700'}${a.active ? '' : ';opacity:.5'}"><td><span class="num">${esc(a.code)}</span></td><td>${esc(a.name)}</td><td>${esc(ACC_TYPE[a.type])}</td><td>${a.postable ? A3(a.balance) : ''}</td><td>${a.system_key ? `<span class="muted">${esc(a.system_key)}</span>` : ''}</td><td>${ACCAP() && a.postable ? `<button class="btn" data-call="EXT.accRebind" data-args="${J([a.id, a.system_key || ''])}">ربط حدث</button>` : ''}</td></tr>`)),
        ACCAP() ? '<button class="btn p" data-call="EXT.accNewAcc">+ حساب</button>' : '')
      + BOX('ما تُرحَّل إليه الأحداث', T(['الحدث / الغرض', 'الحساب المربوط'], M.map(m => `<tr><td>${esc(m.purpose)}<br><span class="muted">${esc(m.key)}</span></td><td>${m.account ? `<span class="num">${esc(m.account.code)}</span> ${esc(m.account.name)}` : pill('غير مربوط', 'p-b')}</td></tr>`)));
  } else if (k === 'st') {
    const [s, P] = await Promise.all([api('/acc/status'), api('/acc/periods')]);
    B.innerHTML = BOX('الرصيد الافتتاحي', s.opening ? `<p>مرحَّل بالقيد <span class="num">${esc(s.opening.number)}</span> بتاريخ ${fmtDate(s.opening.jdate)}. لتصحيحه اعكس القيد من تبويب القيود ثم أدخله من جديد.</p>`
        : !s.active ? '<p class="muted">فعّل المحاسبة أولًا.</p>' : ACCAP() ? `<p>يُدخل من <b>ميزان مراجعة موثَّق</b> في يوم قبل بدء المحاسبة (${fmtDate(s.start)}). اكتب سطرًا لكل حساب: <span class="num">رمز الحساب, مدين, دائن</span>. لا تُخمَّن الأرقام.</p><label>مصدر الأرقام (مثال: ميزان المراجعة المدقق 2025)</label><input id="opS"><label>الأسطر</label><textarea id="opL" rows="8" placeholder="1121,5000,0&#10;3100,0,5000" style="direction:ltr;width:100%"></textarea><div class="err" id="opE"></div><div class="btns" style="margin-top:10px"><button class="btn p" data-call="EXT.accOpen">ترحيل الرصيد الافتتاحي</button></div>` : '<p class="muted">يدخله المدير العام.</p>')
      + BOX('الفترات المحاسبية', T(['الفترة', 'الحالة', 'قيود مرحَّلة', 'مسودات', ''], P.map(p => `<tr><td>${p.year}-${String(p.month).padStart(2, '0')}</td><td>${p.status === 'closed' ? pill('مقفلة', 'p-b') : pill('مفتوحة', 'p-ok')}</td><td>${N(p.journals)}</td><td>${N(p.open_journals)}</td><td>${ACCAP() ? `<button class="btn" data-call="EXT.accPeriod" data-args="${J([p.year, p.month, p.status === 'closed' ? 'reopen' : 'close'])}">${p.status === 'closed' ? 'إعادة فتح' : 'إقفال'}</button>` : ''}</td></tr>`), 'لا فترات بعد — تُنشأ مع أول قيد.')) + EXT.accYearBox(s);
  } else if (k === 'ap') { await EXT.accAp(B);
  } else if (k === 'bk') { await EXT.accBk(B);
  } else if (k === 'rp') { await EXT.accRp(B);
  } else if (k === 'as') { await EXT.accAs(B);
  }
};

EXT.accActivate = () => {
  modal(`<h3>تفعيل المحاسبة</h3><label>تاريخ بدء المحاسبة</label><input id="acS" type="date" max="${accToday()}" value="${accToday().slice(0, 4)}-01-01">
   <p class="muted">كل ما قبل هذا التاريخ يدخل في الرصيد الافتتاحي ولا يُرحَّل. لا يُغيَّر التاريخ بعد ترحيل أول قيد.</p><label><input id="acC" type="checkbox"> أؤكد التفعيل بهذا التاريخ</label>
   <div class="err" id="acE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="acGo">تفعيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#acGo').onclick = async () => { try { await api('/acc/activate', {method: 'POST', body: {start: $('#acS').value, confirm: $('#acC').checked}}); closeModal(); toast('فُعّلت المحاسبة'); EXT.l_acc(); } catch (e) { $('#acE').textContent = e.message; } };
};
EXT.accSync = async () => { const r = await tryDo(() => api('/acc/sync', {method: 'POST'})); toast(`رُحّل ${N(Object.values(r.posted).reduce((a, b) => a + b, 0))} قيدًا${r.errors.length ? ' — ' + r.errors.length + ' خطأ: ' + r.errors[0] : ''}`, !!r.errors.length); EXT.l_acc(); };

EXT.accNew = async () => {
  const A = (await api('/acc/accounts')).filter(a => a.postable && a.active), opts = '<option value="">— الحساب —</option>' + A.map(a => `<option value="${a.id}">${esc(a.code)} — ${esc(a.name)}</option>`).join('');
  const row = () => `<tr><td><select class="jlA">${opts}</select></td><td><input class="jlD" inputmode="decimal" placeholder="0.000"></td><td><input class="jlC" inputmode="decimal" placeholder="0.000"></td><td><input class="jlM"></td></tr>`;
  modal(`<h3>قيد يدوي</h3><label>التاريخ</label><input id="jd" type="date" max="${accToday()}" value="${accToday()}"><label>البيان</label><input id="jm" maxlength="300">
   <div class="tw"><table><thead><tr><th>الحساب</th><th>مدين</th><th>دائن</th><th>ملاحظة</th></tr></thead><tbody id="jl">${row()}${row()}</tbody></table></div>
   <div class="btns"><button class="btn" id="jAdd">+ سطر</button> <span id="jT" class="muted"></span></div><div class="err" id="jE"></div>
   <div class="btns" style="margin-top:12px"><button class="btn p" id="jGo">حفظ مسودة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  const tot = () => { const d = $$('.jlD').reduce((a, x) => a + (+x.value || 0), 0), c = $$('.jlC').reduce((a, x) => a + (+x.value || 0), 0); $('#jT').textContent = `مدين ${A3(d)} · دائن ${A3(c)} · الفرق ${A3(d - c)}`; };
  $('#jl').oninput = tot; $('#jAdd').onclick = () => { $('#jl').insertAdjacentHTML('beforeend', row()); };
  $('#jGo').onclick = async () => {
    const lines = $$('#jl tr').map(tr => ({account: +tr.querySelector('.jlA').value, debit: +tr.querySelector('.jlD').value || 0, credit: +tr.querySelector('.jlC').value || 0, memo: tr.querySelector('.jlM').value})).filter(l => l.account);
    try { const r = await post('/acc/journals', {date: $('#jd').value, memo: $('#jm').value.trim(), lines}); closeModal(); toast('حُفظت المسودة'); EXT.cur.acc = 'jr'; await EXT.l_acc(); EXT.accJ(r.id); } catch (e) { $('#jE').textContent = e.message; }
  };
};

EXT.accJ = async id => {
  const j = await api('/acc/journals/' + id), me = S.me, W = can('accounting'), AP = ACCAP();
  const btn = (act, label, cls = '') => `<button class="btn ${cls}" data-call="EXT.accAct" data-args="${J([id, act])}">${label}</button>`;
  insp(j.number || `مسودة #${j.id}`, `<div class="btns" style="margin-bottom:10px">${pill(...ACC_JST[j.status])} <span class="muted">${esc({manual: 'قيد يدوي', auto: 'قيد تلقائي', opening: 'رصيد افتتاحي', reversal: 'قيد عكسي'}[j.kind])}</span></div>
   <dl class="kv"><dt>التاريخ</dt><dd>${fmtDate(j.jdate)}</dd><dt>البيان</dt><dd>${esc(j.memo || '')}</dd><dt>أنشأه</dt><dd>${esc(j.created_by || '—')}</dd><dt>اعتمده</dt><dd>${esc(j.approved_by || '—')}</dd>${j.reject_note ? `<dt>سبب الرفض</dt><dd>${esc(j.reject_note)}</dd>` : ''}${j.reversal_of ? `<dt>يعكس القيد</dt><dd>#${j.reversal_of}</dd>` : ''}${j.reversed_by ? `<dt>عُكس بالقيد</dt><dd>#${j.reversed_by}</dd>` : ''}</dl>`
   + T(['الحساب', 'مدين', 'دائن', 'الطرف'], j.lines.map(l => `<tr><td><span class="num">${esc(l.account_code)}</span> ${esc(l.account_name)}${l.cc_code ? `<br><span class="muted">${esc(l.cc_code)}</span>` : ''}</td><td>${l.debit ? A3(l.debit) : ''}</td><td>${l.credit ? A3(l.credit) : ''}</td><td>${esc(l.party_name || '')}</td></tr>`))
   + (j.attachments.length ? `<p>المرفقات: ${j.attachments.map(a => esc(a.title)).join('، ')}</p>` : '')
   + `<div class="btns" style="margin-top:10px">${j.status === 'draft' && j.kind === 'manual' && W ? btn('submit', 'تقديم للاعتماد', 'p') + ' ' + btn('delete', 'حذف المسودة') + ` <button class="btn" data-call="EXT.accAttach" data-args="${J([id])}">إرفاق مستند</button>` : ''}
   ${(j.status === 'pending' || (j.status === 'draft' && me.role === 'admin')) && j.kind === 'manual' && AP ? btn('approve', 'اعتماد وترحيل', 'p') : ''}${j.status === 'pending' && AP ? ' ' + btn('reject', 'رفض') : ''}
   ${j.status === 'posted' && ['manual', 'opening'].includes(j.kind) && AP ? btn('reverse', 'عكس القيد') : ''}</div>`);
};
EXT.accAct = async (id, act) => {
  const o = {submit: ['/submit', null, 'قُدّم للاعتماد'], approve: ['/approve', null, 'اعتُمد ورُحّل'], delete: ['', 'DELETE', 'حُذفت المسودة'], reject: ['/reject', 'note', 'رُفض'], reverse: ['/reverse', 'reason', 'عُكس القيد']}[act];
  let body; if (o[1] === 'note') { const note = prompt('سبب الرفض:'); if (!note) return; body = {note}; } else if (o[1] === 'reason') { const reason = prompt('سبب عكس القيد (يُسجَّل):'); if (!reason) return; body = {reason}; }
  await tryDo(() => api('/acc/journals/' + id + o[0], {method: o[1] === 'DELETE' ? 'DELETE' : 'POST', body}), o[2]); EXT.l_acc(); if (act !== 'delete') EXT.accJ(id);
};
EXT.accAttach = id => {
  modal(`<h3>إرفاق مستند بالقيد</h3><input id="atF" type="file"><label>العنوان</label><input id="atT" value="مستند قيد"><div class="err" id="atE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="atGo">رفع</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#atGo').onclick = async () => {
    const f = $('#atF').files[0]; if (!f) { $('#atE').textContent = 'اختر ملفًا'; return; }
    const fd = new FormData(); fd.append('ref_type', 'journal'); fd.append('ref_id', id); fd.append('title', $('#atT').value || 'مستند قيد'); fd.append('category', 'محاسبة'); fd.append('file', f);
    try { const r = await fetch('/api/documents', {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || 'تعذّر الرفع'); closeModal(); toast('رُفع المستند'); EXT.accJ(id); } catch (e) { $('#atE').textContent = e.message; }
  };
};
EXT.accNewAcc = () => {
  modal(`<h3>حساب جديد</h3><label>الرمز</label><input id="naC"><label>الاسم</label><input id="naN"><label>النوع</label><select id="naT">${Object.entries(ACC_TYPE).map(([a, b]) => `<option value="${a}">${b}</option>`).join('')}</select>
   <label><input id="naP" type="checkbox" checked> قابل للترحيل (حساب تفصيلي)</label><div class="err" id="naE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="naGo">إضافة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#naGo').onclick = async () => { try { await post('/acc/accounts', {code: $('#naC').value.trim(), name: $('#naN').value.trim(), type: $('#naT').value, postable: $('#naP').checked}); closeModal(); toast('أُضيف الحساب'); EXT.l_acc(); } catch (e) { $('#naE').textContent = e.message; } };
};
EXT.accRebind = async (id, cur) => {
  const key = prompt('مفتاح الحدث الذي يُرحَّل إلى هذا الحساب (اتركه فارغًا لفك الربط)، مثل bank_main أو rev_rent:', cur); if (key == null) return;
  await tryDo(() => api('/acc/accounts/' + id, {method: 'PATCH', body: {system_key: key.trim()}}), 'حُدّث الربط'); EXT.l_acc();
};
EXT.accOpen = async () => {
  const lines = $('#opL').value.split('\n').map(s => s.trim()).filter(Boolean).map(s => { const [code, d, c] = s.split(/[,\t;]/).map(x => x.trim()); return {code, debit: +d || 0, credit: +c || 0}; });
  try { const r = await post('/acc/opening', {lines, source: $('#opS').value.trim()}); toast('رُحّل الرصيد الافتتاحي ' + r.number); EXT.l_acc(); } catch (e) { $('#opE').textContent = e.message; }
};
EXT.accPeriod = async (y, m, act) => {
  const body = act === 'reopen' ? {reason: prompt('سبب إعادة فتح الفترة (يُدقَّق):') || ''} : undefined; if (act === 'reopen' && !body.reason) return;
  await tryDo(() => api(`/acc/periods/${y}/${m}/${act}`, {method: 'POST', body}), act === 'close' ? 'أُقفلت الفترة' : 'أُعيد فتحها'); EXT.l_acc();
};

/* ================================================================ المحاسبة — الاكتمال (0.24.0) */
const BILL_ST = {draft: ['مسودة', 'p-w'], approved: ['معتمدة', 'p-bl'], partly_paid: ['مسدَّدة جزئيًا', 'p-w'], paid: ['مسدَّدة', 'p-ok'], void: ['ملغاة', 'p-b']};
const ORD_ST = {pending: ['بانتظار الاعتماد', 'p-w'], approved: ['معتمد', 'p-bl'], executed: ['نُفِّذ', 'p-ok'], rejected: ['مرفوض', 'p-b']};
const PAY_M = {transfer: 'تحويل بنكي', cheque: 'شيك', cash: 'نقدًا', card: 'بطاقة'};

EXT.accAp = async function (B) {
  const [bills, orders, vendors, ag] = await Promise.all([api('/acc/bills'), api('/acc/orders'), api('/acc/vendors'), api('/acc/ap-aging')]), W = can('accounting'), AP = ACCAP();
  B.innerHTML = KP([['المستحق للموردين', OMR(ag.total)], ['متأخر 1–30 يومًا', OMR(ag.buckets.d1_30)], ['متأخر 31–60', OMR(ag.buckets.d31_60)], ['متأخر أكثر من 60', OMR(ag.buckets.d61_90 + ag.buckets.d90p)], ['أوامر دفع بانتظار الاعتماد', N(orders.filter(o => o.status === 'pending' || o.status === 'approved').length)]])
    + BOX('فواتير الموردين', T(['الرقم', 'المورّد', 'التاريخ', 'الإجمالي', 'المدفوع', 'الحالة', ''], bills.map(b => `<tr><td><span class="num">${esc(b.number || 'مسودة #' + b.id)}</span></td><td>${esc(b.vendor)}</td><td>${fmtDate(b.bill_date)}</td><td>${A3(b.total)}</td><td>${A3(b.paid)}</td><td>${pill(...BILL_ST[b.status])}</td>
        <td>${b.status === 'draft' && AP ? `<button class="btn p" data-call="EXT.accBillAct" data-args="${J([b.id, 'approve'])}">اعتماد</button>` : ''}${['approved', 'partly_paid'].includes(b.status) && W ? ` <button class="btn" data-call="EXT.accOrderNew" data-args="${J([b.id, +(b.total - b.paid).toFixed(3)])}">أمر دفع</button>` : ''}${['draft', 'approved'].includes(b.status) && AP && !b.paid ? ` <button class="btn" data-call="EXT.accBillAct" data-args="${J([b.id, 'void'])}">إلغاء</button>` : ''}</td></tr>`), 'لا فواتير.'),
      W ? '<button class="btn p" data-call="EXT.accBillNew">+ فاتورة مورّد</button> <button class="btn" data-call="EXT.accVendorNew">+ مورّد</button>' : '')
    + BOX('أوامر الدفع', T(['الرقم', 'المورّد', 'المبلغ', 'الطريقة', 'الاعتماد', 'الحالة', ''], orders.map(o => `<tr><td><span class="num">${esc(o.number)}</span></td><td>${esc(o.vendor)}</td><td>${A3(o.amount)}</td><td>${esc(PAY_M[o.method])}</td>
        <td>${esc(o.approver1 || '—')}${o.needs_second ? '<br><span class="muted">يلزم معتمد ثانٍ: ' + esc(o.approver2 || 'لم يعتمد بعد') + '</span>' : ''}</td><td>${pill(...ORD_ST[o.status])}</td>
        <td>${AP && o.status === 'pending' ? `<button class="btn p" data-call="EXT.accOrderAct" data-args="${J([o.id, 'approve'])}">اعتماد</button> <button class="btn" data-call="EXT.accOrderAct" data-args="${J([o.id, 'reject'])}">رفض</button>` : ''}${o.status === 'approved' && W ? `<button class="btn p" data-call="EXT.accOrderAct" data-args="${J([o.id, 'execute'])}">تنفيذ الدفع</button>` : ''}</td></tr>`), 'لا أوامر دفع.'))
    + BOX('الموردون', T(['المورّد', 'الرقم الضريبي', 'السجل التجاري', 'المستحق له'], vendors.map(v => `<tr><td>${esc(v.name)}</td><td>${esc(v.tax_no || '—')}</td><td>${esc(v.cr_number || '—')}</td><td>${v.owed ? pill(A3(v.owed), 'p-w') : '—'}</td></tr>`), 'لا موردين.'));
};
EXT.accVendorNew = () => {
  modal(`<h3>مورّد جديد</h3><label>الاسم</label><input id="vnN"><label>الرقم الضريبي</label><input id="vnT"><label>السجل التجاري</label><input id="vnC"><label>الآيبان (إسلامي فقط — يُحفظ مشفّرًا)</label><input id="vnI">
   <div class="err" id="vnE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="vnGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#vnGo').onclick = async () => { try { await post('/acc/vendors', {name: $('#vnN').value.trim(), tax_no: $('#vnT').value.trim(), cr_number: $('#vnC').value.trim(), iban: $('#vnI').value.trim()}); closeModal(); toast('أُضيف المورّد'); EXT.l_acc(); } catch (e) { $('#vnE').textContent = e.message; } };
};
EXT.accBillNew = async () => {
  const [V, A] = await Promise.all([api('/acc/vendors'), api('/acc/accounts')]), exp = A.filter(a => a.postable && a.active && ['expense', 'asset'].includes(a.type));
  const row = () => `<tr><td><select class="blA">${exp.map(a => `<option value="${a.id}">${esc(a.code)} — ${esc(a.name)}</option>`).join('')}</select></td><td><input class="blM" inputmode="decimal" placeholder="0.000"></td><td><input class="blD"></td></tr>`;
  modal(`<h3>فاتورة مورّد</h3><label>المورّد</label><select id="bnV">${V.map(v => `<option value="${v.id}">${esc(v.name)}</option>`).join('')}</select><label>تاريخ الفاتورة</label><input id="bnD" type="date" max="${accToday()}" value="${accToday()}">
   <label>تاريخ الاستحقاق</label><input id="bnU" type="date"><label>رقم فاتورة المورّد</label><input id="bnR"><label>ضريبة القيمة المضافة</label><select id="bnX"><option value="out_of_scope">خارج النطاق</option><option value="standard">خاضعة 5٪ (ضريبة مدخلات)</option><option value="zero">صفرية</option><option value="exempt">معفاة</option></select>
   <div class="tw"><table><thead><tr><th>الحساب</th><th>المبلغ قبل الضريبة</th><th>بيان</th></tr></thead><tbody id="bnL">${row()}</tbody></table></div><div class="btns"><button class="btn" id="bnAdd">+ سطر</button></div>
   <div class="err" id="bnE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="bnGo">حفظ مسودة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#bnAdd').onclick = () => $('#bnL').insertAdjacentHTML('beforeend', row());
  $('#bnGo').onclick = async () => {
    const lines = $$('#bnL tr').map(tr => ({account: +tr.querySelector('.blA').value, amount: +tr.querySelector('.blM').value || 0, description: tr.querySelector('.blD').value})).filter(l => l.amount > 0);
    try { await post('/acc/bills', {vendor_id: +$('#bnV').value, bill_date: $('#bnD').value, due_date: $('#bnU').value || null, vendor_ref: $('#bnR').value, vat_class: $('#bnX').value, lines}); closeModal(); toast('حُفظت المسودة'); EXT.l_acc(); } catch (e) { $('#bnE').textContent = e.message; }
  };
};
EXT.accBillAct = async (id, act) => {
  let body; if (act === 'void') { const reason = prompt('سبب إلغاء الفاتورة:'); if (!reason) return; body = {reason}; }
  await tryDo(() => api(`/acc/bills/${id}/${act}`, {method: 'POST', body}), act === 'approve' ? 'اعتُمدت ورُحّلت' : 'أُلغيت'); EXT.l_acc();
};
EXT.accOrderNew = async (bid, left) => {
  const B = (await api('/acc/banks')).filter(b => b.active);
  modal(`<h3>أمر دفع</h3><label>المبلغ (المتبقي ${A3(left)})</label><input id="onA" inputmode="decimal" value="${left}"><label>الطريقة</label><select id="onM">${Object.entries(PAY_M).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
   <label>الحساب البنكي</label><select id="onB">${B.map(b => `<option value="${b.id}">${esc(b.name)}</option>`).join('')}</select><label>المرجع</label><input id="onR"><label>رقم الشيك (للشيك)</label><input id="onC"><label>تاريخ استحقاق الشيك</label><input id="onD" type="date">
   <p class="muted">لا يعتمد المُنشئ أمره، وفوق حد الضبط (5000 ر.ع) يلزم معتمدان مختلفان.</p><div class="err" id="onE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="onGo">إنشاء</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#onGo').onclick = async () => { try { await post('/acc/orders', {bill_id: bid, amount: +$('#onA').value, method: $('#onM').value, bank_account_id: +$('#onB').value, reference: $('#onR').value, cheque_number: $('#onC').value, cheque_due: $('#onD').value || null}); closeModal(); toast('أُنشئ أمر الدفع'); EXT.l_acc(); } catch (e) { $('#onE').textContent = e.message; } };
};
EXT.accOrderAct = async (id, act) => {
  let body = act === 'execute' ? {} : undefined; if (act === 'reject') { const note = prompt('سبب الرفض:'); if (!note) return; body = {note}; }
  await tryDo(() => api(`/acc/orders/${id}/${act}`, {method: 'POST', body}), {approve: 'سُجّل الاعتماد', reject: 'رُفض الأمر', execute: 'نُفِّذ الدفع ورُحّل'}[act]); EXT.l_acc();
};

EXT.accBk = async function (B) {
  const banks = await api('/acc/banks'), id = this.accBank && banks.some(b => b.id === this.accBank) ? this.accBank : (banks[0] || {}).id, W = can('accounting');
  const [lines, rec, cq] = id ? await Promise.all([api(`/acc/banks/${id}/lines?limit=100`), api(`/acc/banks/${id}/recons`), api('/acc/cheques-out')]) : [[], [], []];
  B.innerHTML = BOX('الحسابات البنكية والصناديق (إسلامية فقط)', T(['الحساب', 'النوع', 'الآيبان', 'الرصيد في الدفاتر'], banks.map(b => `<tr data-b="${b.id}" class="${b.id === id ? 'sel' : ''}"><td>${esc(b.name)}<br><span class="muted">${esc(b.account_code)}</span></td><td>${esc({bank: 'بنك', cash: 'صندوق', escrow: 'ضمان', charity: 'تبرعات'}[b.kind])}</td><td>${esc(b.iban || '—')}</td><td>${A3(b.balance)}</td></tr>`)),
      ACCAP() ? '<button class="btn p" data-call="EXT.accBankNew">+ حساب بنكي</button>' : '')
    + (id ? BOX('كشف الحساب والمطابقة', `<div class="toolbar">${W ? `<input id="bkF" type="file" accept=".csv,.xlsx"> <button class="btn p" data-call="EXT.accStmtImport" data-args="${J([id])}">استيراد كشف</button> <button class="btn" data-call="EXT.accAutoMatch" data-args="${J([id])}">مطابقة آلية</button>` : ''}</div>
        <p class="muted">أعمدة الملف: التاريخ، البيان، المرجع، المبلغ (موجب داخل وسالب خارج) — أو عمودا مدين ودائن — والرصيد اختياريًا. استيراد الملف نفسه مرتين لا يكرّر شيئًا.</p>`
        + T(['التاريخ', 'البيان', 'المرجع', 'المبلغ', 'الحالة', ''], lines.map(l => `<tr><td>${fmtDate(l.line_date)}</td><td>${esc(l.description || '')}</td><td>${esc(l.reference || '')}</td><td>${A3(l.amount)}</td><td>${pill({unmatched: 'غير مطابَق', matched: 'مطابَق ' + (l.journal_number || ''), ignored: 'متجاوَز'}[l.status], {unmatched: 'p-w', matched: 'p-ok', ignored: 'p-b'}[l.status])}</td><td>${l.status === 'matched' && W ? `<button class="btn" data-call="EXT.accUnmatch" data-args="${J([id, l.id])}">فك</button>` : ''}</td></tr>`), 'لا أسطر مستوردة.'))
      + BOX('مطابقة نهاية الفترة', `<div class="toolbar"><label>حتى</label> <input id="rcE" type="date" value="${accToday()}"> <label>رصيد الكشف</label> <input id="rcS" inputmode="decimal" placeholder="0.000"> <button class="btn" data-call="EXT.accRecon" data-args="${J([id])}">احسب</button></div><div id="rcOut"></div>`
        + T(['حتى', 'رصيد الكشف', 'رصيد الدفاتر', 'أُغلقت بواسطة'], rec.map(r => `<tr><td>${fmtDate(r.period_end)}</td><td>${A3(r.statement_balance)}</td><td>${A3(r.book_balance)}</td><td>${esc(r.closed_by || '')}</td></tr>`), 'لا مطابقات مغلقة.'))
      + BOX('الشيكات الصادرة', T(['الشيك', 'المستفيد', 'المبلغ', 'الاستحقاق', 'الحالة', ''], cq.map(q => `<tr><td><span class="num">${esc(q.number)}</span><br><span class="muted">${esc(q.bank || '')}</span></td><td>${esc(q.payee || '')}</td><td>${A3(q.amount)}</td><td>${fmtDate(q.due_date)}</td><td>${pill({issued: 'صادر', cleared: 'صُرف', cancelled: 'ملغى'}[q.status] || esc(q.status), q.status === 'cleared' ? 'p-ok' : 'p-w')}</td><td>${q.status === 'issued' && W ? `<button class="btn" data-call="EXT.accChequeCleared" data-args="${J([q.id])}">صُرف</button>` : ''}</td></tr>`), 'لا شيكات صادرة.')) : '');
  $$('#accB tr[data-b]').forEach(tr => tr.onclick = () => { EXT.accBank = +tr.dataset.b; EXT.l_acc(); });
};
EXT.accBankNew = () => {
  modal(`<h3>حساب بنكي جديد</h3><label>الاسم</label><input id="bkN"><label>البنك</label><input id="bkB"><label>الآيبان (يُحفظ مشفّرًا)</label><input id="bkI"><label>النوع</label><select id="bkK"><option value="bank">بنك</option><option value="cash">صندوق</option><option value="escrow">ضمان</option><option value="charity">تبرعات خيرية</option></select>
   <label><input id="bkS" type="checkbox"> أؤكد أن الحساب إسلامي (بنك أو نافذة إسلامية) — لا تُقبل حسابات تقليدية</label><div class="err" id="bkE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="bkGo">إضافة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#bkGo').onclick = async () => { try { await post('/acc/banks', {name: $('#bkN').value.trim(), bank: $('#bkB').value.trim(), iban: $('#bkI').value.trim(), kind: $('#bkK').value, islamic: $('#bkS').checked}); closeModal(); toast('أُضيف الحساب'); EXT.l_acc(); } catch (e) { $('#bkE').textContent = e.message; } };
};
EXT.accStmtImport = async id => {
  const f = $('#bkF').files[0]; if (!f) return toast('اختر ملف الكشف', 1);
  const fd = new FormData(); fd.append('file', f);
  try { const r = await fetch(`/api/acc/banks/${id}/import`, {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || 'تعذّر الاستيراد'); toast(`جديد ${N(j.new)} · مكرر ${N(j.duplicate)}`); EXT.l_acc(); } catch (e) { toast(e.message, 1); }
};
EXT.accAutoMatch = async id => { const r = await tryDo(() => post(`/acc/banks/${id}/auto-match`, {})); toast(`طابق ${N(r.matched)} · ملتبس ${N(r.ambiguous)} (يُترك لك)`); EXT.l_acc(); };
EXT.accUnmatch = async (id, sid) => { await tryDo(() => post(`/acc/banks/${id}/lines/${sid}/unmatch`, {}), 'فُكّت المطابقة'); EXT.l_acc(); };
EXT.accChequeCleared = async id => { await tryDo(() => post(`/acc/cheques-out/${id}/cleared`, {}), 'سُجّل الصرف'); EXT.l_acc(); };
EXT.accRecon = async id => {
  const end = $('#rcE').value, sb = $('#rcS').value; if (sb === '') return toast('اكتب رصيد الكشف', 1);
  const r = await tryDo(() => api(`/acc/banks/${id}/recon?end=${end}&statement_balance=${sb}`));
  $('#rcOut').innerHTML = KP([['رصيد الدفاتر', A3(r.book_balance)], ['رصيد الكشف', A3(r.statement_balance)], ['في الدفاتر ولم يصل البنك', A3(r.in_transit)], ['في الكشف ولم تُسجَّل', A3(r.not_in_books)], ['الفرق', r.balanced ? pill('متوازنة', 'p-ok') : pill(A3(r.difference), 'p-b')]])
    + (r.balanced && ACCAP() ? `<div class="btns"><button class="btn p" data-call="EXT.accReconClose" data-args="${J([id, end, +sb])}">إغلاق المطابقة</button></div>` : '<p class="muted">لا تُغلق المطابقة حتى يكون الفرق صفرًا: سجّل في الدفاتر ما ظهر في الكشف ولم يُسجَّل، أو طابق ما تبقّى.</p>');
};
EXT.accReconClose = async (id, end, sb) => { await tryDo(() => post(`/acc/banks/${id}/recon/close`, {end, statement_balance: sb}), 'أُغلقت المطابقة'); EXT.l_acc(); };

const STMT = {balance_sheet: 'قائمة المركز المالي', income_statement: 'قائمة الدخل', cash_flow: 'التدفقات النقدية', equity_changes: 'التغير في حقوق الملكية'};
EXT.accRp = async function (B) {
  const kind = this.accStmt || 'balance_sheet', to = this.accTo || accToday(), frm = this.accFrm || to.slice(0, 4) + '-01-01', q = `frm=${frm}&to=${to}`;
  const s = await api(`/acc/statements/${kind}?${q}`);
  const proof = {balance_sheet: s.balanced, cash_flow: s.reconciled, equity_changes: s.reconciled}[kind];
  B.innerHTML = `<div class="toolbar"><select id="spK">${Object.entries(STMT).map(([k, v]) => `<option value="${k}" ${k === kind ? 'selected' : ''}>${v}</option>`).join('')}</select> <label>من</label> <input id="spF" type="date" value="${frm}"> <label>إلى</label> <input id="spT" type="date" value="${to}">
     <a class="btn" href="/api/acc/statements/${kind}?${q}&fmt=pdf" target="_blank" rel="noopener">PDF</a> <a class="btn" href="/api/acc/statements/${kind}?${q}&fmt=xlsx">Excel</a> <a class="btn" href="/api/acc/statements/${kind}?${q}&fmt=csv">CSV</a></div>`
    + BOX(`${s.title} ${proof === undefined ? '' : proof ? pill('مطابِقة لحساباتها', 'p-ok') : pill('غير متطابقة — راجع', 'p-b')}`, T(s.columns, s.rows.map(r => `<tr style="${r.bold ? 'font-weight:700' : ''}"><td style="padding-inline-start:${r.level * 18 + 8}px">${esc(r.cells[0])}</td><td>${r.cells[1] === '' ? '' : A3(r.cells[1])}</td></tr>`)))
    + (s.notes ? s.notes.map(n => `<p class="muted">${esc(n.text)}: <b>${A3(n.amount)}</b></p>`).join('') : '');
  $('#spK').onchange = e => { EXT.accStmt = e.target.value; EXT.l_acc(); }; $('#spF').onchange = e => { EXT.accFrm = e.target.value; EXT.l_acc(); }; $('#spT').onchange = e => { EXT.accTo = e.target.value; EXT.l_acc(); };
};

EXT.accAs = async function (B) {
  const [assets, fin, vat] = await Promise.all([api('/acc/assets'), api('/acc/finance'), api('/acc/vat')]), W = can('accounting'), AP = ACCAP();
  B.innerHTML = BOX('الأصول الثابتة', T(['الرمز', 'الأصل', 'التكلفة', 'المتراكم', 'الدفترية', 'القسط الشهري', 'الحالة', ''], assets.map(a => `<tr><td><span class="num">${esc(a.code)}</span></td><td>${esc(a.name)}</td><td>${A3(a.cost)}</td><td>${A3(a.accumulated)}</td><td>${A3(a.book_value)}</td><td>${A3(a.monthly)}</td><td>${a.status === 'active' ? pill('نشط', 'p-ok') : pill('مُخرَج', 'p-w')}</td><td>${a.status === 'active' && AP ? `<button class="btn" data-call="EXT.accDispose" data-args="${J([a.id])}">بيع/إخراج</button>` : ''}</td></tr>`), 'لا أصول مسجَّلة.'),
      (AP ? '<button class="btn p" data-call="EXT.accAssetNew">+ أصل</button> ' : '') + (W ? '<button class="btn" data-call="EXT.accDepRun">تشغيل إهلاك شهر</button>' : ''))
    + BOX('التمويل الإسلامي (هامش معلوم — لا فائدة)', T(['العقد', 'الجهة', 'الأصل', 'الهامش', 'الأقساط', 'المتبقي', 'الحالة', ''], fin.map(f => `<tr><td>${esc({murabaha: 'مرابحة', ijara: 'إجارة', installment: 'بيع بالتقسيط', istisna: 'استصناع'}[f.kind])} #${f.id}</td><td>${esc(f.counterparty)}</td><td>${A3(f.principal)}</td><td>${A3(f.markup_total)}</td><td>${N(f.paid_n)}/${N(f.n)}</td><td>${A3(f.remaining)}</td><td>${f.status === 'closed' ? pill('مغلق', 'p-ok') : pill('قائم', 'p-bl')}</td>
        <td>${f.status === 'active' && W ? `<button class="btn" data-call="EXT.accFinPay" data-args="${J([f.id, (f.installments.find(i => !i.paid_on) || {}).no])}">سداد القسط التالي</button>` : ''}</td></tr>`), 'لا عقود تمويل.'), AP ? '<button class="btn p" data-call="EXT.accFinNew">+ عقد تمويل</button>' : '')
    + BOX('إقرارات ضريبة القيمة المضافة', T(['الفترة', 'مخرجات', 'مدخلات', 'الصافي', 'مرجع الهيئة'], vat.map(v => `<tr><td>${v.year} ر${v.quarter}</td><td>${A3(v.output_vat)}</td><td>${A3(v.input_vat)}</td><td>${A3(v.net)}</td><td>${esc(v.ref || '')}</td></tr>`), 'لم يُقدَّم إقرار.'),
      AP ? '<button class="btn p" data-call="EXT.accVat">احسب إقرار ربع…</button>' : '');
};
EXT.accAssetNew = () => {
  modal(`<h3>أصل ثابت</h3><p class="muted">يسجّل الأصل طريقة إهلاكه فقط؛ الشراء نفسه يُقيَّد بفاتورة المورّد أو بقيد (حساب المعدات 1520).</p><label>الرمز</label><input id="asC"><label>الاسم</label><input id="asN"><label>التكلفة (ر.ع)</label><input id="asK" inputmode="decimal"><label>تاريخ الشراء</label><input id="asD" type="date" max="${accToday()}"><label>العمر بالأشهر</label><input id="asL" inputmode="numeric"><label>القيمة التخريدية</label><input id="asS" inputmode="decimal" value="0">
   <div class="err" id="asE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="asGo">تسجيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#asGo').onclick = async () => { try { await post('/acc/assets', {code: $('#asC').value.trim(), name: $('#asN').value.trim(), cost: +$('#asK').value, acquired: $('#asD').value, life_months: +$('#asL').value, salvage: +$('#asS').value || 0}); closeModal(); toast('سُجّل الأصل'); EXT.l_acc(); } catch (e) { $('#asE').textContent = e.message; } };
};
EXT.accDepRun = async () => { const p = prompt('الشهر (YYYY-MM):', accToday().slice(0, 7)); if (!p) return; const r = await tryDo(() => post('/acc/depreciation/run', {period: p})); toast(`${N(r.assets)} أصل · ${A3(r.total)} ر.ع`); EXT.l_acc(); };
EXT.accDispose = async id => {
  const proceeds = +prompt('عوائد البيع (0 للإتلاف):', '0') || 0, body = {on: accToday(), proceeds};
  if (proceeds > 0) { const b = (await api('/acc/banks'))[0]; body.bank_account_id = b.id; }
  const r = await tryDo(() => post(`/acc/assets/${id}/dispose`, body)); toast(`القيمة الدفترية ${A3(r.book_value)} · ${r.gain_loss >= 0 ? 'ربح' : 'خسارة'} ${A3(Math.abs(r.gain_loss))}`); EXT.l_acc();
};
EXT.accFinNew = async () => {
  const B = (await api('/acc/banks')).filter(b => b.active);
  modal(`<h3>عقد تمويل إسلامي</h3><p class="muted">الهامش مبلغ معلوم سلفًا يُدخل هنا؛ لا نسبة ولا فائدة متراكمة ولا سعر متغيّر.</p><label>النوع</label><select id="fnK"><option value="murabaha">مرابحة</option><option value="ijara">إجارة</option><option value="installment">بيع بالتقسيط</option><option value="istisna">استصناع</option></select>
   <label>الجهة</label><input id="fnC"><label>الأصل (المبلغ المستلم)</label><input id="fnP" inputmode="decimal"><label>الهامش الإجمالي المعلوم</label><input id="fnM" inputmode="decimal" value="0"><label>تاريخ البدء</label><input id="fnD" type="date" max="${accToday()}" value="${accToday()}">
   <label>الحساب البنكي</label><select id="fnB">${B.map(b => `<option value="${b.id}">${esc(b.name)}</option>`).join('')}</select><label>الأقساط (سطر لكل قسط: التاريخ, المبلغ)</label><textarea id="fnL" rows="5" style="direction:ltr;width:100%" placeholder="2026-12-01,280&#10;2027-01-01,280"></textarea>
   <div class="err" id="fnE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="fnGo">تسجيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#fnGo').onclick = async () => {
    const installments = $('#fnL').value.split('\n').map(s => s.trim()).filter(Boolean).map(s => { const [due, amount] = s.split(/[,;\t]/).map(x => x.trim()); return {due, amount: +amount}; });
    try { await post('/acc/finance', {kind: $('#fnK').value, counterparty: $('#fnC').value.trim(), principal: +$('#fnP').value, markup_total: +$('#fnM').value || 0, start_date: $('#fnD').value, bank_account_id: +$('#fnB').value, installments}); closeModal(); toast('سُجّل العقد'); EXT.l_acc(); } catch (e) { $('#fnE').textContent = e.message; }
  };
};
EXT.accFinPay = async (id, no) => { if (!no) return; await tryDo(() => post(`/acc/finance/${id}/installments/${no}/pay`, {}), 'سُدّد القسط'); EXT.l_acc(); };
EXT.accVat = async () => {
  const y = +prompt('السنة:', new Date().getFullYear()) || 0, q = +prompt('الربع (1–4):', '1') || 0; if (!y || !q) return;
  const v = await tryDo(() => api(`/acc/vat/${y}/${q}`));
  modal(`<h3>إقرار ${y} ر${q}</h3>${KP([['ضريبة المخرجات', A3(v.output_vat)], ['ضريبة المدخلات', A3(v.input_vat)], ['الصافي', A3(v.net)]])}${v.warnings.map(w => `<p class="err" style="display:block">${esc(w)}</p>`).join('')}
   ${T(['البند', 'القيمة'], Object.entries(v.boxes).map(([k, x]) => `<tr><td>${esc({sales_standard: 'مبيعات خاضعة', sales_zero: 'مبيعات صفرية', sales_exempt: 'مبيعات معفاة', purchases_standard: 'مشتريات خاضعة', purchases_zero: 'مشتريات صفرية', purchases_exempt: 'مشتريات معفاة', output_vat: 'ضريبة المخرجات', input_vat: 'ضريبة المدخلات'}[k])}</td><td>${A3(x)}</td></tr>`))}
   ${v.filed ? '<p>قُدِّم هذا الإقرار: ' + esc(v.filed.ref) + '</p>' : '<label>مرجع إقرار الهيئة بعد التقديم الفعلي</label><input id="vtR"><div class="err" id="vtE"></div><div class="btns"><button class="btn p" id="vtGo">تسجيل التقديم وترحيل التسوية</button></div>'}<div class="btns" style="margin-top:8px"><button class="btn" data-call="closeModal">إغلاق</button></div>`);
  if (!v.filed) $('#vtGo').onclick = async () => { try { await post(`/acc/vat/${y}/${q}/file`, {ref: $('#vtR').value.trim()}); closeModal(); toast('سُجّل التقديم'); EXT.l_acc(); } catch (e) { $('#vtE').textContent = e.message; } };
};
EXT.accYearBox = s => ACCAP() && s.active ? BOX('إقفال السنة المالية والتصدير', `<p>إقفال السنة يرحّل صافي الربح إلى الأرباح المرحّلة بقيد واحد ويقفل أشهرها؛ قوائم الدخل والتدفقات للسنة المقفلة تبقى كما هي.</p><div class="btns"><button class="btn p" data-call="EXT.accYearClose">إقفال سنة…</button> <a class="btn" href="/api/acc/export/erpnext">تصدير ERPNext (JSON)</a></div>`) : '';
EXT.accYearClose = async () => {
  const y = +prompt('السنة المراد إقفالها:', new Date().getFullYear() - 1) || 0; if (!y || !confirm('إقفال السنة ' + y + ' يقفل كل أشهرها. متابعة؟')) return;
  const r = await tryDo(() => post('/acc/year-close', {year: y}), 'أُقفلت السنة'); toast(`صافي الربح المرحَّل ${A3(r.net_profit)}`); EXT.l_acc();
};

/* ================================================================ الموارد البشرية — النواة (0.25.0) */
const HR_ST = {active: ['على رأس العمل', 'p-ok'], on_leave: ['في إجازة', 'p-w'], terminated: ['منتهي الخدمة', 'p-b']};
const HR_LV = {pending: ['بانتظار القرار', 'p-w'], approved: ['معتمدة', 'p-ok'], rejected: ['مرفوضة', 'p-b'], cancelled: ['ملغاة', 'p-bl']};
const HR_LVL = {expired: ['منتهية', 'p-b'], critical: ['خلال 30 يومًا', 'p-w'], soon: ['خلال 90 يومًا', 'p-bl']};
const HR_DOCS = {passport: 'جواز السفر', resident_card: 'البطاقة المدنية / الإقامة', work_permit: 'تصريح العمل', labour_card: 'بطاقة العمل', health_insurance: 'التأمين الصحي', contract: 'عقد العمل', certificate: 'شهادة', other: 'أخرى'};
const HR_ATT = {present: 'حاضر', absent: 'غائب', late: 'متأخر', leave: 'إجازة', holiday: 'عطلة', remote: 'عن بُعد'};
const HR_RQ = {letter: 'خطاب', advance: 'سلفة', other: 'أخرى'}, HR_RQS = {pending: ['بانتظار', 'p-w'], approved: ['معتمد', 'p-ok'], rejected: ['مرفوض', 'p-b'], done: ['منجز', 'p-bl']};
const hrDay = () => new Date().toISOString().slice(0, 10);
const HF = (id, label, val = '', type = 'text', extra = '') => `<label for="${id}">${label}</label><input id="${id}" type="${type}" value="${esc(val ?? '')}" ${extra}>`;
const HS = (id, label, opts, val) => `<label for="${id}">${label}</label><select id="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(val ?? '') ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
const hrUpload = async (path, file) => {
  const fd = new FormData(); fd.append('file', file);
  const r = await fetch('/api' + path, {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}), j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر الرفع');
  return j;
};
const hrNote = txt => `<p class="muted" style="margin:4px 0 10px">${txt}</p>`;
const F2 = v => (+v || 0).toLocaleString('ar-OM-u-nu-latn', {maximumFractionDigits: 2});  // leave days can be fractional (monthly accrual): never rounded to a whole day on screen
const hrDays = n => n === 1 ? 'يوم' : n === 2 ? 'يومان' : n >= 3 && n <= 10 ? 'أيام' : 'يومًا';
const hrAgo = d => d < 0 ? `منذ ${N(-d)} ${hrDays(-d)}` : d === 0 ? 'اليوم' : `بعد ${N(d)} ${hrDays(d)}`;
const hrBal = b => `<tr><td>${esc(b.name)}</td><td>${F2(b.entitled)}</td><td>${F2(b.carried)}</td><td>${F2(b.adjusted)}</td><td>${F2(b.taken)}</td><td>${F2(b.pending)}</td><td><b>${F2(b.remaining)}</b></td></tr>`;
const HR_BAL_HEAD = ['النوع', 'المستحق', 'المرحَّل', 'التعديل', 'المأخوذ', 'بانتظار القرار', 'المتبقي'];
const hrAlertRows = al => al.map(a => `<tr data-call="EXT.hrEmp" data-args="${J([a.employee_id])}" style="cursor:pointer"><td>${pill(...HR_LVL[a.level])}</td><td>${esc(a.name)} <small class="muted">${esc(a.number)}</small></td><td>${esc(a.label)}</td><td>${fmtDate(a.date)}</td><td>${hrAgo(a.days_left)}</td></tr>`);
const hrLeaveRows = (L, who) => L.map(r => `<tr><td>${who ? esc(r.name) + ' <small class="muted">' + esc(r.number) + '</small>' : esc(r.type_name)}</td>${who ? '<td>' + esc(r.type_name) + '</td>' : ''}<td>${fmtDate(r.from_date)} ← ${fmtDate(r.to_date)}</td><td>${F2(r.days)}</td>
  <td>${pill(esc(r.status_label), HR_LV[r.status][1])}${r.needs_doc && !r.doc_id && r.status === 'pending' ? ' <small class="muted">يلزمه مرفق</small>' : ''}</td><td class="btns">${hrLeaveActions(r)}</td></tr>`);
function hrLeaveActions(r) {
  const out = [], mine = S.me.employee_id === r.employee_id;
  if (r.status === 'pending' && !mine && (can('hr') || (can('hr_manager') && r.manager_id === S.me.employee_id && r.stage === 'manager'))) out.push(`<button class="btn p" data-call="EXT.hrDecide" data-args="${J([r.id, 'approve'])}">اعتماد</button> <button class="btn" data-call="EXT.hrDecide" data-args="${J([r.id, 'reject'])}">رفض</button>`);
  if (r.needs_doc && (r.status === 'pending' || r.status === 'approved') && (mine || can('hr'))) out.push(`<button class="btn" data-call="EXT.hrAttach" data-args="${J([r.id])}">${r.doc_id ? 'استبدال المرفق' : 'إرفاق'}</button>`);
  if ((r.status === 'pending' && mine) || (r.status === 'approved' && (can('hr') || (mine && r.from_date > hrDay())))) out.push(`<button class="btn" data-call="EXT.hrCancel" data-args="${J([r.id, r.status === 'approved' && !(mine && r.from_date > hrDay())])}">إلغاء</button>`);
  if (r.doc_id && can('hr') && can('docs')) out.push(`<a class="btn" href="/api/documents/${r.doc_id}" target="_blank" rel="noopener">المرفق</a>`);
  return out.join(' ');
}
EXT.hrDecide = async (id, action) => {
  let note = ''; if (action === 'reject') { note = prompt('سبب الرفض (إلزامي):', '') || ''; if (!note.trim()) return; }
  await tryDo(() => post(`/hr/leave/requests/${id}/decide`, {action, note}), r => r.status === 'approved' ? 'اعتُمدت الإجازة' : r.status === 'rejected' ? 'رُفضت الإجازة' : 'اعتمدها المدير — بانتظار الموارد البشرية'); EXT.hrRefresh();
};
EXT.hrCancel = async (id, needReason) => {
  let reason = ''; if (needReason) { reason = prompt('سبب الإلغاء (إلزامي):', '') || ''; if (!reason.trim()) return; }
  await tryDo(() => post(`/hr/leave/requests/${id}/cancel`, {reason}), 'أُلغي الطلب'); EXT.hrRefresh();
};
EXT.hrAttach = id => {
  const f = document.createElement('input'); f.type = 'file'; f.accept = '.pdf,.png,.jpg,.jpeg';
  f.onchange = async () => { if (f.files[0]) { await tryDo(() => hrUpload(`/hr/leave/requests/${id}/attachment`, f.files[0]), 'أُرفق الملف'); EXT.hrRefresh(); } };
  f.click();
};
EXT.hrRefresh = () => S.screen === 'me' ? EXT.l_me() : EXT.l_hr();

EXT.l_hr = async function () {
  const tabs = [['ov', 'نظرة عامة'], ['emp', 'الموظفون'], ['org', 'الهيكل'], ['lv', 'الإجازات'], ['att', 'الحضور'], ['rq', 'الطلبات'], ['rec', 'التوظيف'], ['apr', 'التقييم'], ['trn', 'التدريب'], ['dsc', 'الجزاءات'], ['cfg', 'العطل والإعدادات']], el = $('#hr'), k = this.cur.hr;
  el.innerHTML = SUB0('hr', tabs, k) + '<div id="hrB">…</div>';
  const B = $('#hrB');
  if (k === 'ov') {
    const [s, al, ty] = await Promise.all([api('/hr/summary'), api('/hr/alerts'), api('/hr/leave/types')]);
    const prov = ty.filter(t => t.current && t.provisional);
    B.innerHTML = KP([['العاملون', N(s.headcount)], ['العُمانيون', s.omani_pct == null ? '—' : N(s.omani) + ' (' + s.omani_pct.toLocaleString('ar-OM-u-nu-latn') + '٪)', 'نسبة معلوماتية'], ['في إجازة اليوم', N(s.on_leave_today)], ['عقود محددة المدة', N(s.contracts.fixed)],
        ['تعيينات آخر 90 يومًا', N(s.hired_90d)], ['وثائق منتهية أو خلال 30 يومًا', N(s.expiring_30)], ['إجازات بانتظار القرار', N(s.pending_leave)], ['طلبات بانتظار القرار', N(s.pending_requests)]])
      + (prov.length ? BOX('تنبيه: قيم الإجازات مبدئية', `<p>${N(prov.length)} من أنواع الإجازات بقيم وضعتها المنصة ولم يؤكدها مختص بقانون العمل بعد. راجعها من تبويب «الإجازات» ثم اضغط «اعتماد القيم».</p>`) : '')
      + BOX(`ما ينتهي قريبًا <span class="muted">${N(al.length)}</span>`, T(['الحال', 'الموظف', 'البند', 'التاريخ', 'المدة'], hrAlertRows(al), 'لا وثائق أو عقود تنتهي خلال 90 يومًا.'))
      + BOX('العاملون حسب القسم', T(['القسم', 'العدد'], s.by_department.map(d => `<tr><td>${esc(d.department)}</td><td>${N(d.n)}</td></tr>`), 'لا موظفين بعد.'));
    const b = $('#cHr'); if (b) { const n = s.pending_leave + s.pending_requests; b.textContent = n ? N(n) : ''; b.classList.toggle('hidden', !n); }
  } else if (k === 'emp') {
    const st = this.hrSt || 'current', q = this.hrQ || '', L = await api(`/hr/employees?status=${st}${q ? '&q=' + encodeURIComponent(q) : ''}`);
    B.innerHTML = `<div class="toolbar"><input id="hq" placeholder="بحث بالاسم أو الرقم" value="${esc(q)}"> <select id="hst"><option value="current" ${st === 'current' ? 'selected' : ''}>على رأس العمل</option><option value="terminated" ${st === 'terminated' ? 'selected' : ''}>منتهو الخدمة</option></select> <button class="btn p" data-call="EXT.hrEmpForm">+ موظف</button></div>`
      + T(['الرقم', 'الاسم', 'القسم', 'المسمى', 'المدير المباشر', 'التعيين', 'الحال', 'الدخول'], L.map(e => `<tr data-call="EXT.hrEmp" data-args="${J([e.id])}" style="cursor:pointer"><td>${esc(e.number)}</td><td>${esc(e.name)}</td><td>${esc(e.department || '—')}</td><td>${esc(e.position || '—')}</td><td>${esc(e.manager || '—')}</td><td>${fmtDate(e.hire_date)}</td><td>${pill(...HR_ST[e.status])}</td><td>${e.username ? esc(e.username) : '<span class="muted">—</span>'}</td></tr>`), 'لا موظفين.');
    $('#hq').onchange = e => { EXT.hrQ = e.target.value.trim(); EXT.l_hr(); }; $('#hst').onchange = e => { EXT.hrSt = e.target.value; EXT.l_hr(); };
  } else if (k === 'org') {
    const [D, P, tree] = await Promise.all([api('/hr/departments'), api('/hr/positions'), api('/hr/tree')]);
    const node = d => `<li><b>${esc(d.name)}</b> <small class="muted">${d.head ? 'رئيسه: ' + esc(d.head) + ' · ' : ''}${N(d.people.length)} موظف</small>${d.children.length ? '<ul>' + d.children.map(node).join('') + '</ul>' : ''}</li>`;
    B.innerHTML = BOX('الأقسام', T(['القسم', 'يتبع', 'الرئيس', 'مركز الكلفة', 'العاملون', ''], D.map(d => `<tr><td>${esc(d.name)} ${d.active ? '' : pill('موقوف', 'p-b')}</td><td>${esc(d.parent || '—')}</td><td>${esc(d.head || '—')}</td><td>${esc(d.cost_center || '—')}</td><td>${N(d.headcount)}</td>
        <td><button class="btn" data-call="EXT.hrDeptForm" data-args="${J([d.id])}">تعديل</button></td></tr>`), 'لا أقسام.'), '<button class="btn p" data-call="EXT.hrDeptForm" data-args="[0]">+ قسم</button>')
      + BOX('المسميات الوظيفية', T(['المسمى', 'القسم', 'الدرجة', 'العدد المعتمد', 'المشغول', ''], P.map(p => `<tr><td>${esc(p.title)} ${p.active ? '' : pill('موقوف', 'p-b')}</td><td>${esc(p.department || '—')}</td><td>${esc(p.grade || '—')}</td><td>${N(p.headcount)}</td><td>${p.filled > p.headcount ? pill(N(p.filled) + ' (فوق المعتمد)', 'p-w') : N(p.filled)}</td>
        <td><button class="btn" data-call="EXT.hrPosForm" data-args="${J([p.id])}">تعديل</button></td></tr>`), 'لا مسميات.'), '<button class="btn p" data-call="EXT.hrPosForm" data-args="[0]">+ مسمى</button>')
      + BOX('الهيكل', `<ul class="tree">${tree.departments.map(node).join('') || '<li class="muted">لا أقسام.</li>'}</ul>${tree.unassigned.length ? '<p class="muted">بلا قسم: ' + tree.unassigned.map(p => esc(p.name)).join('، ') + '</p>' : ''}`);
  } else if (k === 'lv') {
    const st = this.hrLvSt ?? 'pending', [R, ty] = await Promise.all([api(`/hr/leave/requests${st ? '?status=' + st : ''}`), api('/hr/leave/types')]);
    B.innerHTML = `<div class="toolbar"><select id="lvs">${[['pending', 'بانتظار القرار'], ['approved', 'المعتمدة'], ['rejected', 'المرفوضة'], ['cancelled', 'الملغاة'], ['', 'الكل']].map(([v, l]) => `<option value="${v}" ${v === st ? 'selected' : ''}>${l}</option>`).join('')}</select> <button class="btn p" data-call="EXT.hrLeaveForm">+ تسجيل إجازة لموظف</button></div>`
      + T(['الموظف', 'النوع', 'المدة', 'الأيام', 'الحال', ''], hrLeaveRows(R, true), 'لا طلبات.')
      + BOX('أنواع الإجازات وأرصدتها', hrNote('كل نوع نسخ بتاريخ سريان؛ تغيير القاعدة نسخة جديدة لا تعديل. القيم التي وضعتها المنصة موسومة «مبدئية» حتى يؤكدها مختص بقانون العمل.')
        + T(['النوع', 'مدفوعة', 'أيام السنة', 'الاستحقاق', 'الاحتساب', 'مرفق', 'تعتمدها الموارد', 'السريان', 'الحال', ''], ty.filter(t => t.current).map(t => `<tr><td>${esc(t.name)} <small class="muted">${esc(t.key)}</small></td><td>${t.paid ? 'نعم' : 'لا'}</td><td>${F2(t.days_per_year)}</td><td>${{annual: 'سنوي', monthly: 'شهري', event: 'لكل حدث'}[t.accrual]}</td><td>${t.day_count === 'working' ? 'عمل' : 'تقويمي'}</td><td>${t.needs_doc ? 'نعم' : '—'}</td><td>${t.needs_hr ? 'نعم' : '—'}</td><td>${fmtDate(t.valid_from)}</td>
          <td>${t.provisional ? pill('مبدئية', 'p-w') : pill('مؤكدة', 'p-ok')}</td><td>${t.provisional ? `<button class="btn" data-call="EXT.hrTypeConfirm" data-args="${J([t.id])}">اعتماد القيم</button>` : ''}</td></tr>`)), '<button class="btn" data-call="EXT.hrTypeForm">+ نسخة جديدة</button>');
    $('#lvs').onchange = e => { EXT.hrLvSt = e.target.value; EXT.l_hr(); };
  } else if (k === 'att') {
    const day = this.hrAttDay || hrDay(), month = this.hrAttMonth || day.slice(0, 7), [D, M] = await Promise.all([api(`/hr/attendance?day=${day}`), api(`/hr/attendance/month?month=${month}`)]);
    B.innerHTML = `<div class="toolbar"><label>اليوم</label> <input id="ad" type="date" max="${hrDay()}" value="${day}"> <label>ملخص شهر</label> <input id="am" type="month" value="${month}"></div>`
      + BOX('سجل اليوم', hrNote('اليوم الذي لا علامة له لا يُعدّ غيابًا حتى تقرر الموارد البشرية.') + T(['الموظف', 'الحال', 'الدخول', 'الخروج', ''], D.map(r => `<tr data-e="${r.employee_id}"><td>${esc(r.name)} <small class="muted">${esc(r.number)}</small></td>
        <td>${r.source === 'leave' ? pill('إجازة معتمدة', 'p-bl') : `<select class="as"><option value="">—</option>${['present', 'late', 'remote', 'absent', 'holiday'].map(s => `<option value="${s}" ${r.status === s ? 'selected' : ''}>${HR_ATT[s]}</option>`).join('')}</select>`}</td>
        <td>${r.source === 'leave' ? '' : `<input class="ai" type="time" value="${esc(r.check_in || '')}">`}</td><td>${r.source === 'leave' ? '' : `<input class="ao" type="time" value="${esc(r.check_out || '')}">`}</td>
        <td>${r.source === 'leave' ? '' : `<button class="btn" data-call="EXT.hrAttSave" data-args="${J([r.employee_id])}">حفظ</button>`} <small class="muted">${r.source ? ({manual: 'يدوي', import: 'استيراد', device: 'جهاز'}[r.source] || '') : ''}</small></td></tr>`), 'لا موظفين.'))
      + BOX(`ملخص ${esc(month)}`, T(['الموظف', 'حاضر', 'متأخر', 'عن بُعد', 'إجازة', 'غائب', 'عطلة', 'أيام عمل بلا علامة'], M.map(r => `<tr><td>${esc(r.name)}</td><td>${N(r.present)}</td><td>${N(r.late)}</td><td>${N(r.remote)}</td><td>${N(r.leave)}</td><td>${N(r.absent)}</td><td>${N(r.holiday)}</td><td>${r.unrecorded ? pill(N(r.unrecorded), 'p-w') : '0'}</td></tr>`), 'لا بيانات.'))
      + BOX('استيراد من جهاز البصمة', `${hrNote('ملف xlsx أو csv بأعمدة: رقم الموظف، التاريخ، الدخول، الخروج، الحالة (اختياري). إعادة رفع الملف نفسه لا تغيّر شيئًا، ولا يُستبدل يوم سجّلته الموارد البشرية بيدها أو إجازة معتمدة.')}<div class="toolbar"><input id="af" type="file" accept=".csv,.xlsx"> <label><input id="adr" type="checkbox" checked> تجربة بلا حفظ</label> <button class="btn p" data-call="EXT.hrAttImport">استيراد</button></div><div id="aiR"></div>`);
    $('#ad').onchange = e => { EXT.hrAttDay = e.target.value; EXT.hrAttMonth = e.target.value.slice(0, 7); EXT.l_hr(); }; $('#am').onchange = e => { EXT.hrAttMonth = e.target.value; EXT.l_hr(); };
  } else if (k === 'rq') {
    const R = await api('/hr/requests');
    B.innerHTML = T(['الموظف', 'النوع', 'التفاصيل', 'المبلغ', 'الحال', ''], R.map(q => `<tr><td>${esc(q.name)} <small class="muted">${esc(q.number)}</small></td><td>${HR_RQ[q.kind]}</td><td>${esc(q.details)}</td><td>${q.amount ? OMR(q.amount) : '—'}</td><td>${pill(...HR_RQS[q.status])}${q.decision_note ? ' <small class="muted">' + esc(q.decision_note) + '</small>' : ''}</td>
      <td>${q.status === 'pending' ? `<button class="btn p" data-call="EXT.hrReqDecide" data-args="${J([q.id, 'approved'])}">اعتماد</button> <button class="btn" data-call="EXT.hrReqDecide" data-args="${J([q.id, 'rejected'])}">رفض</button>` : q.status === 'approved' ? `<button class="btn" data-call="EXT.hrReqDecide" data-args="${J([q.id, 'done'])}">تم الإنجاز</button>` : ''}</td></tr>`), 'لا طلبات.');
  } else if (k === 'cfg') {
    const y = this.hrYear || new Date().getFullYear(), [H, S_] = await Promise.all([api(`/hr/holidays?year=${y}`), api('/hr/settings')]);
    const dn = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد'];
    B.innerHTML = BOX('العطل الرسمية', `<div class="toolbar"><label>السنة</label> <input id="hy" type="number" min="2000" max="2100" value="${y}"> <button class="btn p" data-call="EXT.hrHolForm">+ عطلة</button></div>${hrNote('العطل بالتقويم الهجري تُدخل يدويًا كل سنة. إضافة عطلة لا تغيّر أيام إجازة اعتُمدت من قبل.')}`
        + T(['اليوم', 'العطلة', ''], H.map(h => `<tr><td>${fmtDate(h.day)}</td><td>${esc(h.name)}</td><td><button class="btn" data-call="EXT.hrHolDel" data-args="${J([h.id])}">حذف</button></td></tr>`), 'لا عطل مسجلة لهذه السنة.'))
      + BOX('الدوام', `<label>أيام الراحة الأسبوعية</label><div>${dn.map((n, i) => `<label style="display:inline-block;margin-inline-end:12px"><input type="checkbox" class="wk" value="${i}" ${S_.weekend.includes(i) ? 'checked' : ''}> ${n}</label>`).join('')}</div>`
        + HF('hws', 'بدء الدوام', S_.work_start, 'time') + HF('hlg', 'سماح التأخير (دقائق)', S_.late_grace, 'number', 'min="0" max="120"') + '<div class="btns" style="margin-top:10px"><button class="btn p" data-call="EXT.hrSetSave">حفظ</button></div>');
    $('#hy').onchange = e => { EXT.hrYear = +e.target.value; EXT.l_hr(); };
  } else if (k === 'rec') { await EXT.hrRec(B); } else if (k === 'apr') { await EXT.hrApr(B); } else if (k === 'trn') { await EXT.hrTrn(B); } else if (k === 'dsc') { await EXT.hrDsc(B); }
};

EXT.hrAttSave = async eid => {
  const tr = $(`#hrB tr[data-e="${eid}"]`), status = tr.querySelector('.as').value, ci = tr.querySelector('.ai').value, co = tr.querySelector('.ao').value;
  if (!status && !ci && !co) { toast('اختر حالة أو أدخل وقتًا', 1); return; }
  await tryDo(() => post('/hr/attendance', {employee_id: eid, day: EXT.hrAttDay || hrDay(), status: status || null, check_in: ci, check_out: co}), 'حُفظ'); EXT.l_hr();
};
EXT.hrAttImport = async () => {
  const f = $('#af').files[0]; if (!f) { toast('اختر ملفًا', 1); return; }
  const r = await tryDo(() => hrUpload(`/hr/attendance/import?dry=${$('#adr').checked}`, f));
  $('#aiR').innerHTML = KP([[r.dry ? 'سيُضاف' : 'أُضيف', N(r.new)], ['حُدّث', N(r.updated)], ['مكرر', N(r.duplicate)], ['متروك (يدوي/إجازة)', N(r.skipped_manual)], ['أخطاء', N(r.error_count)]]) + (r.errors.length ? T(['الصف', 'السبب'], r.errors.map(e => `<tr><td>${N(e.row)}</td><td>${esc(e.reason)}</td></tr>`)) : '');
  if (!r.dry) EXT.l_hr();
};
EXT.hrReqDecide = async (id, status) => {
  let note = ''; if (status === 'rejected' || status === 'approved') { note = prompt(status === 'rejected' ? 'سبب الرفض (إلزامي):' : 'ملاحظة (اختياري):', '') || ''; if (status === 'rejected' && !note.trim()) return; }
  await tryDo(() => post(`/hr/requests/${id}/decide`, {status, note}), 'سُجّل القرار'); EXT.l_hr();
};
EXT.hrSetSave = async () => {
  const weekend = $$('.wk').filter(x => x.checked).map(x => +x.value);
  await tryDo(() => api('/hr/settings', {method: 'PUT', body: {weekend, work_start: $('#hws').value || '08:00', late_grace: +$('#hlg').value || 0}}), 'حُفظت الإعدادات');
};
EXT.hrHolForm = () => {
  modal(`<h3>عطلة رسمية</h3>${HF('hhd', 'اليوم', '', 'date')}${HF('hhn', 'الاسم', '', 'text', 'maxlength="80"')}<div class="err" id="hhE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="hhGo">إضافة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#hhGo').onclick = async () => { try { await post('/hr/holidays', {day: $('#hhd').value, name: $('#hhn').value.trim()}); closeModal(); toast('أُضيفت العطلة'); EXT.l_hr(); } catch (e) { $('#hhE').textContent = e.message; } };
};
EXT.hrHolDel = async id => { if (!confirm('حذف العطلة؟')) return; await tryDo(() => api('/hr/holidays/' + id, {method: 'DELETE'}), 'حُذفت'); EXT.l_hr(); };
EXT.hrTypeConfirm = async id => { if (!confirm('تؤكد أن القيم راجعها مختص بقانون العمل؟')) return; await tryDo(() => post(`/hr/leave/types/${id}/confirm`), 'اعتُمدت القيم'); EXT.l_hr(); };
EXT.hrTypeForm = async () => {
  const ty = (await api('/hr/leave/types')).filter(t => t.current);
  modal(`<h3>نسخة جديدة من نوع إجازة</h3>${HS('htk', 'النوع', ty.map(t => [t.key, t.name]).concat([['', '— نوع جديد —']]), 'annual')}<div id="htN" class="hidden">${HF('htkn', 'مفتاح النوع (حروف لاتينية)', '', 'text', 'maxlength="30"')}</div>${HF('htn', 'الاسم', '', 'text')}
    ${HF('htd', 'أيام السنة', '30', 'number', 'min="0" step="0.5"')}${HS('hta', 'الاستحقاق', [['monthly', 'شهري (يتراكم)'], ['annual', 'سنوي'], ['event', 'لكل حدث']], 'monthly')}${HS('htc', 'احتساب الأيام', [['working', 'أيام العمل'], ['calendar', 'أيام تقويمية']], 'working')}
    ${HF('htm', 'حد الترحيل للسنة التالية', '0', 'number', 'min="0"')}${HF('hts', 'أشهر الخدمة المطلوبة', '0', 'number', 'min="0"')}${HS('htg', 'خاصة بـ', [['', 'الجميع'], ['male', 'الرجال'], ['female', 'النساء']], '')}
    <label><input type="checkbox" id="htp" checked> مدفوعة</label> <label><input type="checkbox" id="htdoc"> تلزمها وثيقة</label> <label><input type="checkbox" id="hthr"> تعتمدها الموارد البشرية بعد المدير</label> <label><input type="checkbox" id="htneg"> يجوز تجاوز الرصيد</label> <label><input type="checkbox" id="hto"> مرة واحدة طوال الخدمة</label>
    ${HF('htv', 'تاريخ السريان', hrDay(), 'date')}<div class="err" id="htE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="htGo">حفظ النسخة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  const fill = () => { const t = ty.find(x => x.key === $('#htk').value); $('#htN').classList.toggle('hidden', !!t); if (!t) return; $('#htn').value = t.name; $('#htd').value = t.days_per_year; $('#hta').value = t.accrual; $('#htc').value = t.day_count; $('#htm').value = t.carry_over_max; $('#hts').value = t.min_service_months; $('#htg').value = t.gender_only || ''; $('#htp').checked = !!t.paid; $('#htdoc').checked = !!t.needs_doc; $('#hthr').checked = !!t.needs_hr; $('#htneg').checked = !!t.allow_negative; $('#hto').checked = !!(t.rules && t.rules.once_in_service); };
  $('#htk').onchange = fill; fill();
  $('#htGo').onclick = async () => {
    try { await post('/hr/leave/types', {key: $('#htk').value || $('#htkn').value.trim(), name: $('#htn').value.trim(), paid: $('#htp').checked, days_per_year: +$('#htd').value || 0, accrual: $('#hta').value, day_count: $('#htc').value, carry_over_max: +$('#htm').value || 0,
      min_service_months: +$('#hts').value || 0, gender_only: $('#htg').value || null, needs_doc: $('#htdoc').checked, needs_hr: $('#hthr').checked, allow_negative: $('#htneg').checked, once_in_service: $('#hto').checked, valid_from: $('#htv').value}); closeModal(); toast('أُضيفت النسخة'); EXT.l_hr(); } catch (e) { $('#htE').textContent = e.message; }
  };
};
EXT.hrLeaveForm = async () => {
  const [E, ty] = await Promise.all([api('/hr/employees?status=current'), api('/hr/leave/types')]);
  modal(`<h3>تسجيل إجازة لموظف</h3>${HS('hle', 'الموظف', E.map(e => [e.id, `${e.number} — ${e.name}`]), '')}${HS('hlt', 'النوع', ty.filter(t => t.current && t.active).map(t => [t.key, t.name]), 'annual')}${HF('hlf', 'من', hrDay(), 'date')}${HF('hlu', 'إلى', hrDay(), 'date')}${HF('hlr', 'السبب', '', 'text', 'maxlength="300"')}
    <label><input type="checkbox" id="hla"> سجّلها معتمدة (مكالمة، تقرير طبي سُلّم)</label><div class="err" id="hlE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="hlGo">تسجيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#hlGo').onclick = async () => { try { await post('/hr/leave/requests', {employee_id: +$('#hle').value, type_key: $('#hlt').value, from_date: $('#hlf').value, to_date: $('#hlu').value, reason: $('#hlr').value.trim(), approve: $('#hla').checked}); closeModal(); toast('سُجّل الطلب'); EXT.l_hr(); } catch (e) { $('#hlE').textContent = e.message; } };
};
EXT.hrDeptForm = async id => {
  const [D, E, cc] = await Promise.all([api('/hr/departments'), api('/hr/employees?status=current'), api('/acc/cost-centers').catch(() => [])]), d = D.find(x => x.id === id) || {};
  modal(`<h3>${id ? 'تعديل قسم' : 'قسم جديد'}</h3>${HF('hdn', 'الاسم', d.name, 'text', 'maxlength="80"')}${HS('hdp', 'يتبع قسم', [['', '— لا شيء —']].concat(D.filter(x => x.id !== id).map(x => [x.id, x.name])), d.parent_id)}${HS('hdh', 'رئيس القسم', [['', '— لا أحد —']].concat(E.map(e => [e.id, e.name])), d.head_employee_id)}
    ${cc.length ? HS('hdc', 'مركز الكلفة', [['', '— لا شيء —']].concat(cc.map(x => [x.id, x.name])), d.cost_center_id) : ''}${id ? `<label><input type="checkbox" id="hda" ${d.active ? 'checked' : ''}> نشط</label>` : ''}<div class="err" id="hdE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="hdGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#hdGo').onclick = async () => {
    const body = {name: $('#hdn').value.trim(), parent_id: +$('#hdp').value || null, head_employee_id: +$('#hdh').value || null, cost_center_id: $('#hdc') ? (+$('#hdc').value || null) : null};
    try { if (id) { body.active = $('#hda').checked; await api('/hr/departments/' + id, {method: 'PATCH', body}); } else await post('/hr/departments', body); closeModal(); toast('حُفظ'); EXT.l_hr(); } catch (e) { $('#hdE').textContent = e.message; }
  };
};
EXT.hrPosForm = async id => {
  const [P, D] = await Promise.all([api('/hr/positions'), api('/hr/departments')]), p = P.find(x => x.id === id) || {};
  modal(`<h3>${id ? 'تعديل مسمى' : 'مسمى وظيفي جديد'}</h3>${HF('hpt', 'المسمى', p.title, 'text', 'maxlength="80"')}${id ? '' : HS('hpd', 'القسم', [['', '— بلا قسم —']].concat(D.filter(d => d.active).map(d => [d.id, d.name])), '')}${HF('hpg', 'الدرجة', p.grade, 'text', 'maxlength="20"')}${HF('hph', 'العدد المعتمد', p.headcount ?? 1, 'number', 'min="0"')}
    ${id ? `<label><input type="checkbox" id="hpa" ${p.active ? 'checked' : ''}> نشط</label>` : ''}<div class="err" id="hpE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="hpGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#hpGo').onclick = async () => {
    try { if (id) await api('/hr/positions/' + id, {method: 'PATCH', body: {title: $('#hpt').value.trim(), grade: $('#hpg').value.trim(), headcount: +$('#hph').value || 0, active: $('#hpa').checked}});
      else await post('/hr/positions', {title: $('#hpt').value.trim(), department_id: +$('#hpd').value || null, grade: $('#hpg').value.trim(), headcount: +$('#hph').value || 0}); closeModal(); toast('حُفظ'); EXT.l_hr(); } catch (e) { $('#hpE').textContent = e.message; }
  };
};

/* ---- ملف الموظف (لوحة التفاصيل) */
EXT.hrEmp = async id => {
  const [e, bal] = await Promise.all([api('/hr/employees/' + id), api(`/hr/employees/${id}/leave-balances`)]), ro = e.status === 'terminated';
  insp(`${e.number} — ${e.name}`, `${KP([['الحال', HR_ST[e.status][0]], ['القسم', esc(e.department || '—')], ['المسمى', esc(e.position || '—')], ['المدير', esc(e.manager || '—')]])}
    ${T(['البيان', 'القيمة'], [['الاسم بالإنجليزية', e.name_en], ['الجنسية', e.nationality], ['الهوية', e.id_number], ['الميلاد', e.dob && fmtDate(e.dob)], ['الهاتف', e.phone], ['البريد', e.email], ['العنوان', e.address], ['التعيين', fmtDate(e.hire_date)], ['العقد', {permanent: 'دائم', fixed: 'محدد المدة', part: 'جزئي'}[e.contract_type] + (e.contract_end ? ' حتى ' + fmtDate(e.contract_end) : '')], ['نهاية التجربة', e.probation_end && fmtDate(e.probation_end)],
        ['البنك', [e.bank_name, e.iban].filter(Boolean).join(' · ')], ['التأمينات', e.social_ins_no], ['للطوارئ', e.emergency_contact], ['حساب الدخول', e.username]].map(([a, b]) => `<tr><td>${a}</td><td dir="auto">${b ? esc(b) : '—'}</td></tr>`))}
    ${BOX('الوثائق', T(['الوثيقة', 'الرقم', 'تنتهي', 'الحال', ''], e.documents.map(d => `<tr><td>${esc(d.kind_label)}</td><td dir="ltr">${esc(d.number || '—')}</td><td>${d.expires ? fmtDate(d.expires) : '—'}</td><td>${d.level && d.level !== 'ok' ? pill(...HR_LVL[d.level]) : d.expires ? pill('سارية', 'p-ok') : ''}</td>
        <td>${d.document_id ? `<a class="btn" href="/api/documents/${d.document_id}" target="_blank" rel="noopener">الملف</a> ` : ''}<button class="btn" data-call="EXT.hrDocDel" data-args="${J([d.id, id])}">حذف</button></td></tr>`), 'لا وثائق.'), ro ? '' : `<button class="btn" data-call="EXT.hrDocForm" data-args="${J([id])}">+ وثيقة</button>`)}
    ${BOX(`أرصدة الإجازات ${new Date().getFullYear()}`, T(HR_BAL_HEAD, bal.map(hrBal), 'لا أرصدة.'), ro ? '' : `<button class="btn" data-call="EXT.hrAdjust" data-args="${J([id])}">تعديل رصيد</button>`)}
    ${ro ? `<p class="muted">انتهت الخدمة ${fmtDate(e.terminated_on)} — ${esc(e.termination_note || '')}</p>` : `<div class="btns"><button class="btn p" data-call="EXT.hrEmpForm" data-args="${J([id])}">تعديل الملف</button> ${e.username ? `<button class="btn" data-call="EXT.hrAcct" data-args="${J([id, 'reset'])}">إعادة تعيين كلمة المرور</button>` : `<button class="btn" data-call="EXT.hrAcct" data-args="${J([id, 'create'])}">إنشاء حساب دخول</button>`} <button class="btn" data-call="EXT.hrTerminate" data-args="${J([id])}">إنهاء الخدمة</button></div>`}`);
};
EXT.hrAcct = async (id, what) => {
  const r = await tryDo(() => post(`/hr/employees/${id}/account${what === 'reset' ? '/reset' : ''}`));
  modal(`<h3>حساب الموظف</h3><p>اسم المستخدم: <b dir="ltr">${esc(r.username)}</b></p><p>كلمة المرور المؤقتة: <b dir="ltr">${esc(r.temporary_password)}</b></p><p class="muted">تُعرض مرة واحدة فقط، ويُلزم الموظف بتغييرها عند أول دخول.</p><div class="btns"><button class="btn p" data-call="closeModal">تم</button></div>`); EXT.l_hr();
};
EXT.hrTerminate = async id => {
  const d = prompt('تاريخ انتهاء الخدمة (YYYY-MM-DD):', hrDay()); if (!d) return; const note = prompt('سبب انتهاء الخدمة (إلزامي):', ''); if (!note || !note.trim()) return;
  if (!confirm('إنهاء الخدمة نهائي: يُغلق حساب الدخول وتُلغى الإجازات اللاحقة. متابعة؟')) return;
  await tryDo(() => post(`/hr/employees/${id}/status`, {status: 'terminated', date: d, note}), 'انتهت الخدمة'); document.body.classList.remove('io'); EXT.l_hr();
};
EXT.hrAdjust = async id => {
  const key = prompt('نوع الإجازة (مثل annual):', 'annual'); if (!key) return; const delta = +prompt('الفرق بالأيام (موجب يزيد، سالب ينقص):', '0'); if (!delta) return; const note = prompt('سبب التعديل (إلزامي):', ''); if (!note || note.trim().length < 3) return;
  await tryDo(() => post('/hr/leave/adjust', {employee_id: id, type_key: key.trim(), year: new Date().getFullYear(), delta, note: note.trim()}), 'عُدّل الرصيد'); EXT.hrEmp(id);
};
EXT.hrDocDel = async (did, eid) => { if (!confirm('حذف سجل الوثيقة؟ الملف المرفوع يبقى في المستندات.')) return; await tryDo(() => api('/hr/documents/' + did, {method: 'DELETE'}), 'حُذف'); EXT.hrEmp(eid); };
EXT.hrDocForm = id => {
  modal(`<h3>وثيقة موظف</h3>${HS('hdk', 'النوع', Object.entries(HR_DOCS), 'passport')}${HF('hdno', 'الرقم', '', 'text', 'maxlength="60" dir="ltr"')}${HF('hdi', 'تاريخ الإصدار', '', 'date')}${HF('hde', 'تاريخ الانتهاء', '', 'date')}<label for="hdf">صورة الوثيقة (اختياري — PDF أو صورة)</label><input id="hdf" type="file" accept=".pdf,.png,.jpg,.jpeg">
    <div class="err" id="hdE2"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="hdGo2">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#hdGo2').onclick = async () => {
    try {
      let document_id = null; const f = $('#hdf').files[0];
      if (f) { const fd = new FormData(); fd.append('ref_type', 'employee'); fd.append('ref_id', id); fd.append('title', HR_DOCS[$('#hdk').value]); fd.append('category', 'وثائق الموظف'); fd.append('file', f);
        const r = await fetch('/api/documents', {method: 'POST', headers: {'X-CSRF-Token': csrf()}, body: fd}), j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'تعذّر الرفع'); document_id = j.id; }
      await post(`/hr/employees/${id}/documents`, {kind: $('#hdk').value, number: $('#hdno').value.trim(), issued: $('#hdi').value, expires: $('#hde').value, document_id}); closeModal(); toast('أُضيفت الوثيقة'); EXT.hrEmp(id);
    } catch (e) { $('#hdE2').textContent = e.message; }
  };
};
EXT.hrEmpForm = async id => {
  const [D, P, E] = await Promise.all([api('/hr/departments'), api('/hr/positions'), api('/hr/employees?status=current')]), e = id ? await api('/hr/employees/' + id) : {omani: 1, contract_type: 'permanent', hire_date: hrDay()};
  const opt = (L, f) => [['', '— لا شيء —']].concat(L.filter(x => x.active !== 0).map(f));
  modal(`<h3>${id ? 'تعديل ملف موظف' : 'موظف جديد'}</h3><div class="grid2">${HF('fn', 'الاسم', e.name, 'text', 'maxlength="120"')}${HF('fne', 'الاسم بالإنجليزية', e.name_en, 'text', 'dir="ltr"')}
    <div><label><input type="checkbox" id="fo" ${e.omani ? 'checked' : ''}> عُماني</label></div>${HF('fna', 'الجنسية', e.nationality)}${HS('fg', 'الجنس', [['', '—'], ['male', 'ذكر'], ['female', 'أنثى']], e.gender)}${HS('fm', 'الحالة الاجتماعية', [['', '—'], ['single', 'أعزب'], ['married', 'متزوج'], ['divorced', 'مطلق'], ['widowed', 'أرمل']], e.marital)}
    ${HF('fid', 'رقم الهوية', e.id_number, 'text', 'dir="ltr"')}${HF('fdb', 'تاريخ الميلاد', e.dob, 'date')}${HF('fp', 'الهاتف', e.phone, 'text', 'dir="ltr"')}${HF('fe', 'البريد', e.email, 'email', 'dir="ltr"')}</div>${HF('fa', 'العنوان', e.address)}
    <div class="grid2">${HS('fd', 'القسم', opt(D, d => [d.id, d.name]), e.department_id)}${HS('fpo', 'المسمى', opt(P, p => [p.id, p.title + (p.department ? ' — ' + p.department : '')]), e.position_id)}${HS('fmg', 'المدير المباشر', opt(E.filter(x => x.id !== id), x => [x.id, x.name]), e.manager_id)}
    ${HF('fh', 'تاريخ التعيين', e.hire_date, 'date')}${HS('fc', 'نوع العقد', [['permanent', 'دائم'], ['fixed', 'محدد المدة'], ['part', 'دوام جزئي']], e.contract_type)}${HF('fce', 'نهاية العقد', e.contract_end, 'date')}${HF('fpe', 'نهاية التجربة', e.probation_end, 'date')}</div>
    <div class="grid2">${HF('fb', 'البنك', e.bank_name)}${HF('fib', 'IBAN', e.iban, 'text', 'dir="ltr"')}${HF('fsi', 'رقم التأمينات', e.social_ins_no, 'text', 'dir="ltr"')}<div><label><input type="checkbox" id="fpa" ${e.pasi_applies ? 'checked' : ''}> تُطبَّق عليه الحماية الاجتماعية</label></div></div>${HF('fem', 'جهة اتصال للطوارئ', e.emergency_contact)}
    <div class="err" id="fE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="fGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#fGo').onclick = async () => {
    const n = v => +v || null, body = {name: $('#fn').value.trim(), name_en: $('#fne').value.trim(), omani: $('#fo').checked, nationality: $('#fna').value.trim(), gender: $('#fg').value || null, marital: $('#fm').value || null, id_number: $('#fid').value.trim(), dob: $('#fdb').value,
      phone: $('#fp').value.trim(), email: $('#fe').value.trim(), address: $('#fa').value.trim(), department_id: n($('#fd').value), position_id: n($('#fpo').value), manager_id: n($('#fmg').value), hire_date: $('#fh').value, contract_type: $('#fc').value,
      contract_end: $('#fce').value, probation_end: $('#fpe').value, bank_name: $('#fb').value.trim(), iban: $('#fib').value.trim(), social_ins_no: $('#fsi').value.trim(), pasi_applies: $('#fpa').checked, emergency_contact: $('#fem').value.trim()};
    try { const r = id ? await api('/hr/employees/' + id, {method: 'PATCH', body}) : await post('/hr/employees', body); closeModal(); toast(id ? 'حُفظ الملف' : 'أُنشئ الملف ' + r.number + (r.warnings.length ? ' — ' + r.warnings[0] : '')); EXT.l_hr(); if (id) EXT.hrEmp(id); } catch (e) { $('#fE').textContent = e.message; }
  };
};

/* ---- بوابة الموظف */
EXT.l_me = async function () {
  const tabs = [['me', 'بياناتي'], ['lv', 'إجازاتي'], ['pay', 'قسائمي'], ['rq', 'طلباتي'], ['apr', 'تقييمي'], ['trn', 'تدريبي'], ['att', 'حضوري'], ['ln', 'سلفي'], ['dsc', 'إشعاراتي']].concat(can('hr_manager') ? [['tm', 'فريقي']] : []), el = $('#me'), k = this.cur.me;
  el.innerHTML = SUB0('me', tabs, k) + '<div id="meB">…</div>';
  const B = $('#meB');
  if (k === 'me') {
    const m = await api('/hr/me');
    B.innerHTML = KP([['الرقم الوظيفي', esc(m.number)], ['القسم', esc(m.department || '—')], ['المسمى', esc(m.position || '—')], ['المدير المباشر', esc(m.manager || '—')], ['تاريخ التعيين', fmtDate(m.hire_date)], ['إجازات بانتظار القرار', N(m.open_requests)]])
      + (m.alerts.length ? BOX('وثائقك التي تنتهي قريبًا', T(['الحال', 'البند', 'التاريخ', 'المدة'], m.alerts.map(a => `<tr><td>${pill(...HR_LVL[a.level])}</td><td>${esc(a.label)}</td><td>${fmtDate(a.date)}</td><td>${hrAgo(a.days_left)}</td></tr>`))) : '')
      + BOX(`أرصدة إجازاتي ${new Date().getFullYear()}`, T(HR_BAL_HEAD, m.balances.map(hrBal), 'لا أرصدة.'))
      + BOX('وثائقي', T(['الوثيقة', 'تنتهي', ''], m.documents.map(d => `<tr><td>${esc(d.kind_label)}</td><td>${d.expires ? fmtDate(d.expires) : '—'}</td><td>${d.document_id ? `<a class="btn" href="/api/hr/me/documents/${d.id}/file" target="_blank" rel="noopener">الملف</a>` : ''}</td></tr>`), 'لا وثائق مسجلة.'))
      + BOX('بياناتي', `${T(['البيان', 'القيمة'], [['الاسم', m.name], ['الهوية', m.id_number], ['البنك', [m.bank_name, m.iban].filter(Boolean).join(' · ')], ['التأمينات', m.social_ins_no]].map(([a, b]) => `<tr><td>${a}</td><td dir="auto">${b ? esc(b) : '—'}</td></tr>`))}${hrNote('الهوية والبنك والتأمينات تتغير عبر الموارد البشرية (من تبويب «طلباتي»).')}
        <div class="grid2">${HF('mp', 'الهاتف', m.phone, 'text', 'dir="ltr"')}${HF('me_', 'البريد', m.email, 'email', 'dir="ltr"')}</div>${HF('ma', 'العنوان', m.address)}${HF('mem', 'جهة اتصال للطوارئ', m.emergency_contact)}<div class="btns" style="margin-top:10px"><button class="btn p" data-call="EXT.meSave">حفظ بياناتي</button></div>`);
  } else if (k === 'lv') {
    const [ty, L, m] = await Promise.all([api('/hr/me/leave-types'), api('/hr/me/leave'), api('/hr/me')]);
    B.innerHTML = BOX('طلب إجازة', `<div class="grid2">${HS('ltk', 'النوع', ty.map(t => [t.key, t.name]), 'annual')}${HF('ltf', 'من', hrDay(), 'date')}${HF('ltu', 'إلى', hrDay(), 'date')}${HF('ltr', 'السبب', '', 'text', 'maxlength="300"')}</div><div id="ltN" class="muted"></div><div class="err" id="ltE"></div><div class="btns" style="margin-top:10px"><button class="btn p" id="ltGo">إرسال الطلب</button></div>`)
      + BOX('أرصدتي', T(HR_BAL_HEAD, m.balances.map(hrBal), 'لا أرصدة.')) + BOX('طلباتي', T(['النوع', 'المدة', 'الأيام', 'الحال', ''], hrLeaveRows(L, false), 'لا طلبات.'));
    const note = () => { const t = ty.find(x => x.key === $('#ltk').value); $('#ltN').textContent = t ? [t.needs_doc ? 'يلزمه مرفق بعد الإرسال.' : '', t.needs_hr ? 'تعتمده الموارد البشرية بعد مديرك.' : '', t.provisional ? 'قيمه مبدئية.' : ''].filter(Boolean).join(' ') : ''; };
    $('#ltk').onchange = note; note();
    $('#ltGo').onclick = async () => { try { await post('/hr/me/leave', {type_key: $('#ltk').value, from_date: $('#ltf').value, to_date: $('#ltu').value, reason: $('#ltr').value.trim()}); toast('أُرسل الطلب'); EXT.l_me(); } catch (e) { $('#ltE').textContent = e.message; } };
  } else if (k === 'att') { await EXT.meAtt(B); } else if (k === 'ln') { await EXT.meLoans(B); } else if (k === 'apr') { await EXT.meApr(B); } else if (k === 'trn') { await EXT.meTrn(B); } else if (k === 'dsc') { await EXT.meDsc(B); } else if (k === 'pay') {
    await EXT.mePayslips(B);
  } else if (k === 'rq') {
    const R = await api('/hr/me/requests');
    B.innerHTML = BOX('طلب جديد', `<div class="grid2">${HS('rqk', 'النوع', [['letter', 'خطاب (تعريف، شهادة عمل)'], ['advance', 'سلفة'], ['other', 'أخرى (تغيير بيانات، استفسار)']], 'letter')}${HF('rqa', 'المبلغ (للسلفة فقط)', '', 'number', 'min="0" step="0.001"')}</div>${HF('rqd', 'التفاصيل', '', 'text', 'maxlength="500"')}<div class="err" id="rqE"></div><div class="btns" style="margin-top:10px"><button class="btn p" id="rqGo">إرسال</button></div>`)
      + BOX('طلباتي', T(['النوع', 'التفاصيل', 'المبلغ', 'الحال'], R.map(q => `<tr><td>${HR_RQ[q.kind]}</td><td>${esc(q.details)}</td><td>${q.amount ? OMR(q.amount) : '—'}</td><td>${pill(...HR_RQS[q.status])}${q.decision_note ? ' <small class="muted">' + esc(q.decision_note) + '</small>' : ''}</td></tr>`), 'لا طلبات.'));
    $('#rqGo').onclick = async () => { try { await post('/hr/me/requests', {kind: $('#rqk').value, details: $('#rqd').value.trim(), amount: +$('#rqa').value || null}); toast('أُرسل الطلب'); EXT.l_me(); } catch (e) { $('#rqE').textContent = e.message; } };
  } else if (k === 'tm') {
    const [T_, L] = await Promise.all([api('/hr/team'), api('/hr/team/leave?status=pending')]);
    B.innerHTML = BOX(`بانتظار قرارك <span class="muted">${N(L.length)}</span>`, T(['الموظف', 'النوع', 'المدة', 'الأيام', 'الحال', ''], hrLeaveRows(L, true), 'لا طلبات بانتظارك.'))
      + BOX('فريقي', T(['الرقم', 'الموظف', 'المسمى', 'الهاتف', 'رصيد السنوية', 'اليوم'], T_.map(t => `<tr><td>${esc(t.number)}</td><td>${esc(t.name)}</td><td>${esc(t.position || '—')}</td><td dir="ltr">${esc(t.phone || '—')}</td><td>${t.annual_remaining == null ? '—' : F2(t.annual_remaining)}</td><td>${t.away_today ? pill('في إجازة', 'p-bl') : pill('متاح', 'p-ok')}</td></tr>`), 'لا مرؤوسين مباشرين لك.'));
    B.insertAdjacentHTML('afterbegin', await EXT.meReviews());
    const b = $('#cMe'); if (b) { b.textContent = L.length ? N(L.length) : ''; b.classList.toggle('hidden', !L.length); }
  }
};
EXT.meSave = async () => { await tryDo(() => api('/hr/me', {method: 'PATCH', body: {phone: $('#mp').value, email: $('#me_').value, address: $('#ma').value, emergency_contact: $('#mem').value}}), r => r.changed.length ? 'حُفظت بياناتك' : 'لا تغيير'); };

/* ================================================================ الرواتب (0.26.0) */
EXT.cur.pay = 'runs';
const PAY_ST = {draft: ['مسودة', 'p-bl'], computed: ['محتسب', 'p-w'], approved: ['معتمد', 'p-ok'], paid: ['مدفوع', 'p-ok']};
const PAY_LOAN = {pending: ['بانتظار الاعتماد', 'p-w'], active: ['جارٍ', 'p-ok'], paid: ['مسدَّد', 'p-bl'], cancelled: ['ملغى', 'p-b']};
const PAY_TST = {draft: ['مسودة', 'p-w'], approved: ['معتمدة', 'p-ok'], paid: ['مدفوعة', 'p-bl']};
const P3 = v => new Intl.NumberFormat('ar-OM-u-nu-latn', {minimumFractionDigits: 3, maximumFractionDigits: 3}).format(+v || 0);
const payMonth = () => new Date().toISOString().slice(0, 7);
const payPrev = () => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 7); };
const payBanks = () => api('/acc/banks').catch(() => []);
const payWarn = w => (w || []).map(x => `<small class="${x.blocker ? 'bad' : 'muted'}">${x.blocker ? '⛔ ' : ''}${esc(x.msg)}</small>`).join('<br>');

EXT.l_pay = async function () {
  const tabs = [['runs', 'المسيّرات'], ['sal', 'هياكل الرواتب'], ['adj', 'التسويات'], ['loan', 'السلف والقروض الحسنة'], ['rates', 'المعدلات'], ['end', 'نهاية الخدمة']], el = $('#pay'), k = this.cur.pay;
  el.innerHTML = SUB0('pay', tabs, k) + '<div id="payB">…</div>';
  const B = $('#payB');
  if (k === 'runs') {
    const rid = this.payRun;
    if (rid) return EXT.payRunView(rid);
    const R = await api('/hr/payroll/runs');
    B.innerHTML = `<div class="toolbar"><input id="prp" type="month" value="${payPrev()}" max="${payMonth()}"> <button class="btn p" data-call="EXT.payRunNew">+ مسيّر</button></div>`
      + T(['الشهر', 'الحال', 'القسائم', 'الإجمالي', 'الصافي', 'عوائق', 'أُحتسب بواسطة', 'اعتُمد بواسطة'], R.map(r => `<tr data-call="EXT.payRunOpen" data-args="${J([r.id])}" style="cursor:pointer"><td>${esc(r.period)}</td><td>${pill(...PAY_ST[r.status])}</td><td>${N(r.headcount)}</td><td>${P3(r.gross)}</td><td>${P3(r.net)}</td><td>${r.blockers ? pill(N(r.blockers), 'p-b') : '0'}</td><td>${esc(r.computed_by || '—')}</td><td>${esc(r.approved_by || '—')}</td></tr>`), 'لا مسيّرات بعد.');
  } else if (k === 'sal') {
    const S_ = await api('/hr/payroll/salaries');
    B.innerHTML = hrNote('فتح هذه القائمة مسجَّل في التدقيق. الراتب لا يراه إلا من لديه صلاحية الرواتب وصاحبه.') + `<div class="toolbar"><button class="btn p" data-call="EXT.paySalForm">+ هيكل راتب جديد</button></div>`
      + T(['الرقم', 'الموظف', 'القسم', 'سريان الهيكل', 'الأساسي', 'البدلات', 'الإجمالي', 'التأمينات', ''], S_.map(s => `<tr><td>${esc(s.number)}</td><td>${esc(s.name)}</td><td>${esc(s.department || '—')}</td><td>${s.effective_from ? fmtDate(s.effective_from) : pill('بلا هيكل', 'p-b')}</td><td>${s.basic == null ? '—' : P3(s.basic)}</td><td>${s.allowances == null ? '—' : P3(s.allowances)}</td><td><b>${s.total == null ? '—' : P3(s.total)}</b></td><td>${s.pasi_applies ? 'نعم' : '—'}</td>
        <td><button class="btn" data-call="EXT.paySalForm" data-args="${J([s.employee_id])}">هيكل جديد</button></td></tr>`), 'لا موظفين.');
  } else if (k === 'adj') {
    const p = this.payAdjP || payMonth(), A_ = await api(`/hr/payroll/adjustments?period=${p}`);
    B.innerHTML = `<div class="toolbar"><label>الشهر</label> <input id="adp" type="month" value="${p}"> <button class="btn p" data-call="EXT.payAdjForm" data-args="${J([p])}">+ تسوية</button></div>${hrNote('استحقاق أو استقطاع لمرة واحدة في شهر لم يُعتمد مسيّره (مكافأة، جزاء، تصحيح). بعد الاعتماد تُسجَّل في الشهر التالي.')}`
      + T(['الموظف', 'النوع', 'البند', 'المبلغ', 'ملاحظة', ''], A_.map(a => `<tr><td>${esc(a.name)} <small class="muted">${esc(a.number)}</small></td><td>${a.kind === 'earning' ? pill('استحقاق', 'p-ok') : pill('استقطاع', 'p-w')}</td><td>${esc(a.item)}</td><td>${P3(a.amount)}</td><td>${esc(a.note || '')}</td><td><button class="btn" data-call="EXT.payAdjDel" data-args="${J([a.id])}">حذف</button></td></tr>`), 'لا تسويات في هذا الشهر.');
    $('#adp').onchange = e => { EXT.payAdjP = e.target.value; EXT.l_pay(); };
  } else if (k === 'loan') {
    const L = await api('/hr/payroll/loans');
    B.innerHTML = hrNote('لا فائدة ولا رسوم على أي سلفة أو قرض حسن: يُسدَّد المبلغ المصروف بالتمام، ويُخصم قسطه من الراتب. يعتمد القرضَ شخصٌ غير من أنشأه.') + `<div class="toolbar"><button class="btn p" data-call="EXT.payLoanForm">+ سلفة / قرض حسن</button></div>`
      + T(['الموظف', 'النوع', 'المبلغ', 'الأقساط', 'يبدأ', 'المتبقي', 'الحال', ''], L.map(l => `<tr><td>${esc(l.name)} <small class="muted">${esc(l.number)}</small></td><td>${l.kind === 'advance' ? 'سلفة' : 'قرض حسن'}</td><td>${P3(l.amount)}</td><td>${N(l.installments)}</td><td>${esc(l.start_period)}</td><td>${P3(l.outstanding)}</td><td>${pill(...PAY_LOAN[l.status])}</td>
        <td>${l.status === 'pending' ? `<button class="btn p" data-call="EXT.payLoanApprove" data-args="${J([l.id])}">اعتماد وصرف</button> ` : ''}${l.status === 'pending' || (l.status === 'active' && !l.disburse_journal_id) ? `<button class="btn" data-call="EXT.payLoanCancel" data-args="${J([l.id])}">إلغاء</button>` : ''}<button class="btn" data-call="EXT.payLoanView" data-args="${J([l.id])}">الجدول</button></td></tr>`), 'لا سلف أو قروض.');
  } else if (k === 'rates') {
    const R = await api('/hr/payroll/rates'), unset = R.filter(r => r.current && r.value == null);
    B.innerHTML = (unset.length ? BOX('معدلات لم تُدخَل بعد', `<p>${unset.map(r => esc(r.label)).join('، ')} — لا يُعتمد مسيّر لعامل خاضع للتأمينات الاجتماعية قبل إدخالها. تُدخَل بمصدرها (نشرة أو لائحة أو مراجعة مختص)؛ لا تضع المنصة رقمًا من عندها.</p>`) : '')
      + `<div class="toolbar"><button class="btn p" data-call="EXT.payRateForm">+ معدل جديد</button></div>`
      + T(['المعدل', 'القيمة', 'سريان', 'الحال', 'المصدر', 'أدخله'], R.map(r => `<tr><td>${esc(r.label)}</td><td>${r.value == null ? pill('لم يُدخَل', 'p-b') : F2(r.value)}</td><td>${fmtDate(r.valid_from)}${r.current ? ' ' + pill('الحالي', 'p-ok') : ''}</td><td>${r.provisional ? pill('مبدئي', 'p-w') : pill('مؤكد', 'p-ok')}</td><td>${esc(r.note || '')}</td><td>${esc(r.created_by || '—')}</td></tr>`), 'لا معدلات.')
      + BOX('بدلات الرواتب', T(['البدل', 'يدخل في وعاء التأمينات'], (await api('/hr/payroll/components')).map(c => `<tr><td>${esc(c.name)}</td><td>${c.pasi_base ? 'نعم' : '—'}</td></tr>`)), '<button class="btn" data-call="EXT.payCompForm">+ بدل</button>');
  } else if (k === 'end') {
    const [R, Tm] = await Promise.all([api('/hr/eosb/rules'), api('/hr/terminations')]);
    if (this.payTerm) return EXT.payTermView(this.payTerm);
    B.innerHTML = BOX('قواعد مكافأة نهاية الخدمة', hrNote('لا تضع المنصة قاعدة من عندها: بلا قاعدة تكون المكافأة «غير معلومة» ولا تُعتمد مخالصة. تُدخَل القاعدة بشرائح (أيام من الأجر الأساسي عن كل سنة) ومصدرها.')
        + T(['الفئة', 'سريان', 'الشرائح', 'سقف (أشهر)', 'المصدر'], R.map(r => `<tr><td>${r.grp === 'omani' ? 'العُمانيون' : 'الوافدون'}</td><td>${fmtDate(r.valid_from)}${r.current ? ' ' + pill('الحالية', 'p-ok') : ''}</td><td>${r.tiers.map(t => (t.to_years == null ? 'ما بعد ذلك' : 'حتى ' + N(t.to_years) + ' سنوات') + ': ' + F2(t.days_per_year) + ' يومًا').join(' · ')}</td><td>${r.cap_months ? F2(r.cap_months) : '—'}</td><td>${esc(r.note || '')}</td></tr>`), 'لا قواعد مُدخَلة.'), '<button class="btn p" data-call="EXT.payRuleForm">+ قاعدة</button>')
      + BOX('المخالصات', `<div class="toolbar"><button class="btn p" data-call="EXT.payTermForm">+ مخالصة نهاية خدمة</button></div>` + T(['الموظف', 'تاريخ النهاية', 'السبب', 'المكافأة', 'الصافي', 'الحال'], Tm.map(t => `<tr data-call="EXT.payTermOpen" data-args="${J([t.id])}" style="cursor:pointer"><td>${esc(t.name)} <small class="muted">${esc(t.number)}</small></td><td>${fmtDate(t.end_date)}</td><td>${({resignation: 'استقالة', termination: 'إنهاء من صاحب العمل', end_of_contract: 'انتهاء العقد', retirement: 'تقاعد', death: 'وفاة', other: 'أخرى'})[t.kind]}</td><td>${P3(t.eosb_amount)}</td><td>${P3(t.net)}</td><td>${pill(...PAY_TST[t.status])}</td></tr>`), 'لا مخالصات.'));
  }
};
EXT.payRunOpen = id => { EXT.payRun = id; EXT.l_pay(); };
EXT.payRunBack = () => { EXT.payRun = null; EXT.l_pay(); };
EXT.payRunNew = async () => { const r = await tryDo(() => post('/hr/payroll/runs', {period: $('#prp').value}), 'أُنشئ المسيّر'); EXT.payRun = r.id; EXT.l_pay(); };
EXT.payRunView = async function (rid) {
  const B = $('#payB'), r = await api('/hr/payroll/runs/' + rid), me = S.me.username;
  B.innerHTML = `<div class="toolbar"><button class="btn" data-call="EXT.payRunBack">← المسيّرات</button> <b>${esc(r.period)}</b> ${pill(...PAY_ST[r.status])}
      ${r.status === 'draft' || r.status === 'computed' ? `<button class="btn p" data-call="EXT.payRunDo" data-args="${J([rid, 'compute'])}">${r.status === 'draft' ? 'احتساب' : 'إعادة الاحتساب'}</button>` : ''}
      ${r.status === 'computed' ? `<button class="btn p" data-call="EXT.payRunDo" data-args="${J([rid, 'approve'])}" ${r.computed_by === me ? 'disabled title="لا تعتمد مسيّرًا احتسبته"' : ''}>اعتماد</button>` : ''}
      ${r.status === 'approved' ? `<button class="btn p" data-call="EXT.payRunPay" data-args="${J([rid])}">تسجيل الدفع</button>` : ''}
      ${r.status === 'approved' || r.status === 'paid' ? `<button class="btn" data-call="EXT.payWps" data-args="${J([rid])}">ملف تحويل الأجور</button>` : ''}</div>`
    + KP([['القسائم', N(r.headcount)], ['الإجمالي', P3(r.gross)], ['الصافي', P3(r.net)], ['تأمينات العامل', P3(r.pasi_employee)], ['تأمينات صاحب العمل', P3(r.pasi_employer)], ['عوائق', N(r.blockers)]])
    + (r.computed_by ? hrNote(`احتسبه ${esc(r.computed_by)}${r.approved_by ? ' · اعتمده ' + esc(r.approved_by) : ' · يعتمده شخص آخر لديه صلاحية الرواتب'}${r.paid_on ? ' · دُفع ' + fmtDate(r.paid_on) : ''}`) : '')
    + (r.missing.length ? BOX('خارج المسيّر', T(['الموظف', 'السبب'], r.missing.map(m => `<tr><td>${esc(m.name)} <small class="muted">${esc(m.number)}</small></td><td>${esc(m.reason)}</td></tr>`))) : '')
    + T(['الموظف', 'الإجمالي', 'تسويات', 'غياب', 'تأمينات العامل', 'قسط سلفة', 'الصافي', 'تنبيهات', ''], r.payslips.map(s => `<tr><td>${esc(s.name)} <small class="muted">${esc(s.number)}</small></td><td>${P3(s.gross)}</td><td>${P3(s.adj_earn - s.adj_ded)}</td><td>${P3(s.absence_ded)}${s.absence_days ? ' <small class="muted">(' + F2(s.absence_days) + ' يوم)</small>' : ''}</td><td>${P3(s.pasi_employee)}</td><td>${P3(s.loan_ded)}</td><td><b>${P3(s.net)}</b></td><td>${payWarn(s.warnings)}</td>
      <td><a class="btn" href="/api/hr/payroll/payslips/${s.id}.pdf" target="_blank" rel="noopener">قسيمة</a></td></tr>`), 'اضغط «احتساب».');
};
EXT.payRunDo = async (rid, what) => {
  try { const r = await tryDo(() => post(`/hr/payroll/runs/${rid}/${what}${EXT.data.confirmMissing === rid ? '?confirm_missing=1' : ''}`).catch(e => { if (what === 'approve' && e.message.startsWith('موظفون بلا هيكل') && confirm(e.message + '\n\nهل تعتمد المسيّر بدون هؤلاء؟')) { EXT.data.confirmMissing = rid; return post(`/hr/payroll/runs/${rid}/approve?confirm_missing=1`); } throw e; }), what === 'compute' ? (x => `احتُسب: ${N(x.headcount)} قسيمة${x.blockers ? ' — عوائق ' + N(x.blockers) : ''}`) : (x => x.note || 'اعتُمد المسيّر')); if (what === 'compute' && r.skipped.length) toast(`${N(r.skipped.length)} موظفًا بلا هيكل راتب`, 1); } catch (e) { /* toast shown */ }
  EXT.payRunView(rid);
};
EXT.payRunPay = async rid => {
  const banks = (await payBanks()).filter(b => b.active);
  modal(`<h3>تسجيل دفع الرواتب</h3>${HF('ppd', 'تاريخ الدفع', hrDay(), 'date')}${banks.length ? HS('ppb', 'الحساب البنكي (يُرحَّل منه الدفع إلى المحاسبة)', [['', '— بلا ترحيل —']].concat(banks.map(b => [b.id, b.name])), '') : hrNote('المحاسبة غير مفعَّلة أو لا صلاحية لك عليها: يُسجَّل الدفع بلا قيد.')}<div class="err" id="ppE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="ppGo">تسجيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#ppGo').onclick = async () => { try { const r = await post(`/hr/payroll/runs/${rid}/pay`, {paid_on: $('#ppd').value, bank_account_id: $('#ppb') ? (+$('#ppb').value || null) : null}); closeModal(); toast(r.note || 'سُجّل الدفع', !!r.note); EXT.payRunView(rid); } catch (e) { $('#ppE').textContent = e.message; } };
};
EXT.payWps = async rid => {
  const w = await tryDo(() => api(`/hr/payroll/runs/${rid}/wps`));
  modal(`<h3>ملف تحويل الأجور — ${esc(w.period)}</h3>${KP([['السطور', N(w.lines.length)], ['الإجمالي', P3(w.total)], ['الحالة', w.ready ? 'جاهز' : 'يحتاج إصلاحًا']])}
    ${w.problems.length ? T(['الموظف', 'المشكلة', 'الخطورة'], w.problems.map(p => `<tr><td>${esc(p.name)} <small class="muted">${esc(p.number)}</small></td><td>${esc(p.msg)}</td><td>${p.error ? pill('يمنع التصدير', 'p-b') : pill('تنبيه', 'p-w')}</td></tr>`)) : '<p>لا مشكلات.</p>'}
    ${hrNote('الصيغة ملف CSV عام؛ تُضبط صيغة كل بنك عند تزويدنا بها. الملف يحمل بصمة تُسجَّل في التدقيق.')}<div class="btns" style="margin-top:12px">${w.ready ? `<a class="btn p" href="/api/hr/payroll/runs/${rid}/wps?fmt=csv">تنزيل الملف</a>` : ''} <button class="btn" data-call="closeModal">إغلاق</button></div>`);
};
EXT.paySalForm = async eid => {
  const [S_, C] = await Promise.all([api('/hr/payroll/salaries'), api('/hr/payroll/components')]), cur = S_.find(x => x.employee_id === eid), allow = C.filter(c => c.kind === 'earning' && !c.system);
  modal(`<h3>هيكل راتب جديد</h3>${HS('psE', 'الموظف', S_.map(s => [s.employee_id, `${s.number} — ${s.name}`]), eid || '')}${HF('psD', 'يسري من', hrDay(), 'date')}${HF('psB', 'الأجر الأساسي (ر.ع)', cur && cur.basic != null ? cur.basic : '', 'number', 'min="0" step="0.001"')}
    ${allow.map(c => HF('psL' + c.id, c.name + (c.pasi_base ? ' (في وعاء التأمينات)' : ''), '', 'number', 'min="0" step="0.001"')).join('')}${HF('psN', 'ملاحظة', '', 'text', 'maxlength="200"')}<div class="err" id="psErr"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="psGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#psGo').onclick = async () => {
    try { await post('/hr/payroll/structures', {employee_id: +$('#psE').value, effective_from: $('#psD').value, basic: +$('#psB').value || 0, note: $('#psN').value.trim(), lines: allow.map(c => ({component_id: c.id, amount: +$('#psL' + c.id).value || 0})).filter(l => l.amount > 0)}); closeModal(); toast('حُفظ الهيكل'); EXT.l_pay(); } catch (e) { $('#psErr').textContent = e.message; }
  };
};
EXT.payAdjForm = async p => {
  const S_ = await api('/hr/payroll/salaries');
  modal(`<h3>تسوية راتب — ${esc(p)}</h3>${HS('paE', 'الموظف', S_.map(s => [s.employee_id, `${s.number} — ${s.name}`]), '')}${HS('paK', 'النوع', [['earning', 'استحقاق'], ['deduction', 'استقطاع']], 'earning')}${HF('paN', 'البند', '', 'text', 'maxlength="60"')}${HF('paA', 'المبلغ (ر.ع)', '', 'number', 'min="0" step="0.001"')}${HF('paT', 'ملاحظة', '', 'text')}
    <div class="err" id="paErr"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="paGo">إضافة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#paGo').onclick = async () => { try { await post('/hr/payroll/adjustments', {employee_id: +$('#paE').value, period: p, kind: $('#paK').value, name: $('#paN').value.trim(), amount: +$('#paA').value || 0, note: $('#paT').value.trim()}); closeModal(); toast('أُضيفت التسوية'); EXT.l_pay(); } catch (e) { $('#paErr').textContent = e.message; } };
};
EXT.payAdjDel = async id => { if (!confirm('حذف التسوية؟')) return; await tryDo(() => api('/hr/payroll/adjustments/' + id, {method: 'DELETE'}), 'حُذفت'); EXT.l_pay(); };
EXT.payLoanForm = async () => {
  const S_ = await api('/hr/payroll/salaries');
  modal(`<h3>سلفة / قرض حسن</h3>${HS('plE', 'الموظف', S_.map(s => [s.employee_id, `${s.number} — ${s.name}`]), '')}${HS('plK', 'النوع', [['advance', 'سلفة (حتى 12 قسطًا)'], ['qard_hasan', 'قرض حسن']], 'advance')}${HF('plA', 'المبلغ (ر.ع)', '', 'number', 'min="0" step="0.001"')}${HF('plN', 'عدد الأقساط', '3', 'number', 'min="1" max="60"')}${HF('plS', 'أول قسط في شهر', payMonth(), 'month')}${HF('plR', 'السبب', '', 'text', 'maxlength="200"')}
    ${hrNote('لا فائدة ولا رسوم: يُسدَّد المبلغ بالتمام.')}<div class="err" id="plErr"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="plGo">إنشاء الطلب</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#plGo').onclick = async () => { try { await post('/hr/payroll/loans', {employee_id: +$('#plE').value, kind: $('#plK').value, amount: +$('#plA').value || 0, installments: +$('#plN').value || 1, start_period: $('#plS').value, reason: $('#plR').value.trim()}); closeModal(); toast('أُنشئ الطلب — يعتمده شخص آخر'); EXT.l_pay(); } catch (e) { $('#plErr').textContent = e.message; } };
};
EXT.payLoanApprove = async id => {
  const banks = (await payBanks()).filter(b => b.active);
  modal(`<h3>اعتماد وصرف</h3>${HF('plD', 'تاريخ الصرف', hrDay(), 'date')}${banks.length ? HS('plB', 'يُصرف من', [['', '— بلا ترحيل —']].concat(banks.map(b => [b.id, b.name])), '') : ''}<div class="err" id="plE2"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="plGo2">اعتماد</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#plGo2').onclick = async () => { try { const r = await post(`/hr/payroll/loans/${id}/approve`, {disbursed_on: $('#plD').value, bank_account_id: $('#plB') ? (+$('#plB').value || null) : null}); closeModal(); toast(r.note || 'اعتُمد وصُرف', !!r.note); EXT.l_pay(); } catch (e) { $('#plE2').textContent = e.message; } };
};
EXT.payLoanCancel = async id => { const reason = prompt('سبب الإلغاء:', ''); if (!reason || reason.trim().length < 3) return; await tryDo(() => post(`/hr/payroll/loans/${id}/cancel`, {reason}), 'أُلغي'); EXT.l_pay(); };
EXT.payLoanView = async id => {
  const l = await api('/hr/payroll/loans/' + id);
  modal(`<h3>جدول السداد</h3>${KP([['المبلغ', P3(l.amount)], ['الأقساط', N(l.installments)], ['الحال', PAY_LOAN[l.status][0]]])}${T(['القسط', 'الشهر', 'المبلغ', 'الحال'], l.schedule.map(s => `<tr><td>${N(s.no)}</td><td>${esc(s.period)}</td><td>${P3(s.amount)}</td><td>${({due: 'مستحق', deducted: 'خُصم', waived: 'أُسقط', settled: 'سُوّي في المخالصة'})[s.status]}</td></tr>`), 'لم يُعتمد بعد.')}<div class="btns"><button class="btn p" data-call="closeModal">إغلاق</button></div>`);
};
EXT.payRateForm = () => {
  modal(`<h3>معدل جديد</h3>${HS('prK', 'المعدل', [['pasi_employee_pct', 'حصة العامل من التأمينات ٪'], ['pasi_employer_pct', 'حصة صاحب العمل من التأمينات ٪'], ['pasi_ceiling', 'سقف الأجر الخاضع للتأمينات (ر.ع)'], ['day_divisor', 'قاسم الأجر اليومي']], 'pasi_employee_pct')}${HF('prV', 'القيمة', '', 'number', 'step="0.001"')}${HF('prD', 'يسري من', hrDay(), 'date')}${HF('prN', 'المصدر (نشرة، لائحة، مختص)', '', 'text', 'maxlength="200"')}
    <div class="err" id="prE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="prGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#prGo').onclick = async () => { try { await post('/hr/payroll/rates', {key: $('#prK').value, value: +$('#prV').value, valid_from: $('#prD').value, note: $('#prN').value.trim()}); closeModal(); toast('حُفظ المعدل'); EXT.l_pay(); } catch (e) { $('#prE').textContent = e.message; } };
};
EXT.payCompForm = () => {
  modal(`<h3>بدل جديد</h3>${HF('pcK', 'المفتاح (حروف لاتينية)', '', 'text', 'maxlength="30" dir="ltr"')}${HF('pcN', 'الاسم', '', 'text')}<label><input type="checkbox" id="pcP"> يدخل في وعاء التأمينات</label><div class="err" id="pcE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="pcGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#pcGo').onclick = async () => { try { await post('/hr/payroll/components', {key: $('#pcK').value.trim(), name: $('#pcN').value.trim(), pasi_base: $('#pcP').checked}); closeModal(); toast('أُضيف البدل'); EXT.l_pay(); } catch (e) { $('#pcE').textContent = e.message; } };
};
EXT.payRuleForm = () => {
  modal(`<h3>قاعدة مكافأة نهاية الخدمة</h3>${HS('pgG', 'الفئة', [['expat', 'الوافدون'], ['omani', 'العُمانيون']], 'expat')}${HF('pgD', 'يسري من', hrDay(), 'date')}
    <label>الشرائح (أيام من الأجر الأساسي عن كل سنة خدمة)</label><div id="pgT"><div class="grid2"><input class="pgY" type="number" step="0.5" placeholder="حتى سنة (فارغ = ما بعده)"><input class="pgP" type="number" step="0.5" placeholder="أيام عن كل سنة"></div></div><button class="btn" id="pgAdd">+ شريحة</button>
    ${HF('pgC', 'سقف بأشهر الأجر (اختياري)', '', 'number', 'step="0.5"')}${HF('pgN', 'المصدر (مادة القانون، تعميم، مختص)', '', 'text', 'maxlength="300"')}<div class="err" id="pgE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="pgGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#pgAdd').onclick = () => $('#pgT').insertAdjacentHTML('beforeend', '<div class="grid2"><input class="pgY" type="number" step="0.5" placeholder="حتى سنة (فارغ = ما بعده)"><input class="pgP" type="number" step="0.5" placeholder="أيام عن كل سنة"></div>');
  $('#pgGo').onclick = async () => {
    const ys = $$('.pgY'), ps = $$('.pgP'), tiers = ys.map((y, i) => ({to_years: y.value === '' ? null : +y.value, days_per_year: +ps[i].value || 0})).filter(t => t.days_per_year > 0);
    try { await post('/hr/eosb/rules', {grp: $('#pgG').value, valid_from: $('#pgD').value, tiers, cap_months: +$('#pgC').value || null, note: $('#pgN').value.trim()}); closeModal(); toast('حُفظت القاعدة'); EXT.l_pay(); } catch (e) { $('#pgE').textContent = e.message; }
  };
};
EXT.payTermForm = async () => {
  const S_ = await api('/hr/payroll/salaries');
  modal(`<h3>مخالصة نهاية خدمة</h3>${HS('ptE', 'الموظف', S_.map(s => [s.employee_id, `${s.number} — ${s.name}`]), '')}${HF('ptD', 'تاريخ النهاية', hrDay(), 'date')}${HS('ptK', 'السبب', [['resignation', 'استقالة'], ['termination', 'إنهاء من صاحب العمل'], ['end_of_contract', 'انتهاء العقد'], ['retirement', 'تقاعد'], ['death', 'وفاة'], ['other', 'أخرى']], 'resignation')}${HF('ptN', 'ملاحظة', '', 'text', 'maxlength="300"')}
    ${HF('ptU', 'مستحقات أخرى (ر.ع)', '0', 'number', 'min="0" step="0.001"')}${HF('ptX', 'استقطاعات أخرى (ر.ع)', '0', 'number', 'min="0" step="0.001"')}<div class="err" id="ptErr"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="ptGo">إعداد المسودة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#ptGo').onclick = async () => { try { const r = await post('/hr/terminations', {employee_id: +$('#ptE').value, end_date: $('#ptD').value, kind: $('#ptK').value, note: $('#ptN').value.trim(), other_dues: +$('#ptU').value || 0, other_deductions: +$('#ptX').value || 0}); closeModal(); EXT.payTerm = r.id; EXT.l_pay(); } catch (e) { $('#ptErr').textContent = e.message; } };
};
EXT.payTermOpen = id => { EXT.payTerm = id; EXT.l_pay(); };
EXT.payTermBack = () => { EXT.payTerm = null; EXT.l_pay(); };
EXT.payTermView = async function (id) {
  const t = await api('/hr/terminations/' + id), me = S.me.username, B = $('#payB'), bad = t.warnings.some(w => w.blocker);
  B.innerHTML = `<div class="toolbar"><button class="btn" data-call="EXT.payTermBack">← المخالصات</button> <b>${esc(t.name)}</b> ${pill(...PAY_TST[t.status])}
      ${t.status === 'draft' ? `<button class="btn" data-call="EXT.payTermEdit" data-args="${J([id])}">تعديل المبالغ</button> <button class="btn p" data-call="EXT.payTermApprove" data-args="${J([id])}" ${bad || t.created_by === me ? 'disabled' : ''} title="${bad ? 'عوائق' : t.created_by === me ? 'لا تعتمد مخالصة أعددتها' : ''}">اعتماد وإنهاء الخدمة</button>` : ''}
      ${t.status === 'approved' ? `<button class="btn p" data-call="EXT.payTermPay" data-args="${J([id])}">تسجيل الدفع</button>` : ''}<a class="btn" href="/api/hr/terminations/${id}.pdf" target="_blank" rel="noopener">المخالصة PDF</a></div>`
    + KP([['تاريخ النهاية', fmtDate(t.end_date)], ['سنوات الخدمة', F2(t.service_years)], ['آخر أجر أساسي', P3(t.last_basic)], ['صافي المخالصة', P3(t.net)]])
    + (t.warnings.length ? BOX('تنبيهات', t.warnings.map(w => `<p class="${w.blocker ? 'bad' : 'muted'}">${w.blocker ? '⛔ ' : ''}${esc(w.msg)}</p>`).join('')) : '')
    + BOX('الحساب خطوة بخطوة', T(['البند', 'التفصيل', 'المبلغ'], t.eosb_steps.map(s => `<tr><td>مكافأة نهاية الخدمة</td><td>${F2(s.years)} سنة × ${F2(s.days_per_year)} يومًا = ${F2(s.days)} يومًا</td><td>${P3(s.amount)}</td></tr>`).concat([
        `<tr><td>مكافأة نهاية الخدمة — المجموع</td><td></td><td><b>${P3(t.eosb_amount)}</b></td></tr>`, `<tr><td>بدل رصيد الإجازة</td><td>${F2(t.leave_days)} يومًا</td><td>${P3(t.leave_payout)}</td></tr>`, `<tr><td>مستحقات أخرى</td><td></td><td>${P3(t.other_dues)}</td></tr>`,
        `<tr><td>أقساط سلف وقروض حسنة</td><td>تُخصم</td><td>−${P3(t.loans_due)}</td></tr>`, `<tr><td>استقطاعات أخرى</td><td>تُخصم</td><td>−${P3(t.other_deductions)}</td></tr>`])))
    + BOX('إخلاء الطرف', t.clearance.map((x, i) => `<label style="display:block"><input type="checkbox" class="ptC" data-i="${i}" ${x.done ? 'checked' : ''} ${t.status === 'paid' ? 'disabled' : ''}> ${esc(x.item)}</label>`).join('') + (t.status !== 'paid' ? '<div class="btns" style="margin-top:8px"><button class="btn" data-call="EXT.payTermClear" data-args="' + J([id]) + '">حفظ الإخلاء</button></div>' : ''));
};
EXT.payTermClear = async id => {
  const t = await api('/hr/terminations/' + id), items = t.clearance.map((x, i) => ({item: x.item, done: $$('.ptC')[i].checked}));
  await tryDo(() => post(`/hr/terminations/${id}/recalc`, {clearance: items}), 'حُفظ الإخلاء'); EXT.payTermView(id);
};
EXT.payTermEdit = async id => {
  const t = await api('/hr/terminations/' + id);
  modal(`<h3>تعديل المبالغ</h3>${HF('peD', 'تاريخ النهاية', t.end_date, 'date')}${HF('peU', 'مستحقات أخرى', t.other_dues, 'number', 'min="0" step="0.001"')}${HF('peX', 'استقطاعات أخرى', t.other_deductions, 'number', 'min="0" step="0.001"')}<div class="err" id="peE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="peGo">إعادة الحساب</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#peGo').onclick = async () => { try { await post(`/hr/terminations/${id}/recalc`, {end_date: $('#peD').value, other_dues: +$('#peU').value || 0, other_deductions: +$('#peX').value || 0}); closeModal(); EXT.payTermView(id); } catch (e) { $('#peE').textContent = e.message; } };
};
EXT.payTermApprove = async id => {
  if (!confirm('الاعتماد ينهي خدمة الموظف نهائيًا: يُغلق حسابه وتُلغى إجازاته اللاحقة وتُسوّى أقساطه. متابعة؟')) return;
  const r = await tryDo(() => post(`/hr/terminations/${id}/approve`), x => x.note || 'اعتُمدت المخالصة وانتهت الخدمة'); EXT.payTermView(id);
};
EXT.payTermPay = async id => {
  const banks = (await payBanks()).filter(b => b.active);
  modal(`<h3>تسجيل دفع المخالصة</h3>${HF('pyD', 'تاريخ الدفع', hrDay(), 'date')}${banks.length ? HS('pyB', 'من حساب', [['', '— بلا ترحيل —']].concat(banks.map(b => [b.id, b.name])), '') : ''}<div class="err" id="pyE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="pyGo">تسجيل</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#pyGo').onclick = async () => { try { const r = await post(`/hr/terminations/${id}/pay`, {paid_on: $('#pyD').value, bank_account_id: $('#pyB') ? (+$('#pyB').value || null) : null}); closeModal(); toast(r.note || 'سُجّل الدفع', !!r.note); EXT.payTermView(id); } catch (e) { $('#pyE').textContent = e.message; } };
};

/* ---- قسائمي في بوابة الموظف */
EXT.mePayslips = async function (B) {
  const L = await api('/hr/me/payslips'), sal = await api('/hr/me/salary');
  B.innerHTML = (sal ? BOX('راتبي الحالي', KP([['الأساسي', P3(sal.basic)], ['البدلات', P3(sal.total - sal.basic)], ['الإجمالي', P3(sal.total)], ['سريان الهيكل', fmtDate(sal.effective_from)]])) : '')
    + BOX('قسائمي', T(['الشهر', 'الإجمالي', 'الاستقطاعات', 'الصافي', 'الحال', ''], L.map(s => `<tr><td>${esc(s.period)}</td><td>${P3(s.gross + s.adj_earn)}</td><td>${P3(s.absence_ded + s.pasi_employee + s.loan_ded + s.adj_ded)}</td><td><b>${P3(s.net)}</b></td><td>${s.status === 'paid' ? pill('مدفوعة', 'p-ok') : pill('معتمدة', 'p-bl')}</td><td><a class="btn" href="/api/hr/me/payslips/${s.id}.pdf" target="_blank" rel="noopener">القسيمة PDF</a></td></tr>`), 'لا قسائم معتمدة بعد.'));
};

/* ================================================================ بقية دورة الموظف (0.27.0): التوظيف والتقييم والتدريب والجزاءات */
const REC_ST = {applied: ['تقدّم', 'p-bl'], screening: ['فرز', 'p-bl'], interview: ['مقابلة', 'p-w'], offer: ['عرض', 'p-w'], hired: ['عُيّن', 'p-ok'], rejected: ['مرفوض', 'p-b'], withdrawn: ['انسحب', 'p-b']};
const REC_NEXT = {applied: 'screening', screening: 'interview', interview: 'offer'};
const OPN_ST = {draft: ['مسودة', 'p-bl'], open: ['مفتوحة', 'p-ok'], closed: ['مغلقة', 'p-w'], filled: ['مكتملة', 'p-ok'], cancelled: ['ملغاة', 'p-b']};
const APR_ST = {self: ['ذاتي', 'p-w'], manager: ['عند المدير', 'p-w'], hr: ['عند الموارد', 'p-bl'], final: ['معتمد', 'p-ok'], ack: ['أُقرّ به', 'p-ok']};
const CYC_ST = {draft: ['مسودة', 'p-bl'], open: ['مفتوحة', 'p-ok'], closed: ['مغلقة', 'p-b']};
const APR_DEC = {none: 'بلا قرار', promotion: 'ترقية', raise: 'زيادة', training: 'تدريب', improvement_plan: 'خطة تحسين', no_action: 'لا إجراء'};
const TRN_ST = {planned: ['مخطط', 'p-bl'], completed: ['أُتمّت', 'p-ok'], cancelled: ['ملغاة', 'p-b'], no_show: ['لم يحضر', 'p-b']};
const CMP_ST = {valid: ['سارية', 'p-ok'], expiring: ['تنتهي قريبًا', 'p-w'], expired: ['منتهية', 'p-b'], missing: ['لم تُؤخذ', 'p-b']};
const DSC_ST = {open: ['قيد الدراسة', 'p-bl'], proposed: ['مقترح', 'p-w'], issued: ['صادر', 'p-ok'], appealed: ['متظلَّم منه', 'p-w'], revoked: ['ملغى', 'p-b'], closed: ['مغلق بلا جزاء', 'p-bl']};
const DSC_KIND = {warning: 'إنذار كتابي', deduction: 'خصم من الأجر', suspension: 'إيقاف عن العمل'};

/* ---- التوظيف */
EXT.hrRec = async function (B) {
  const oid = this.recOpening || '', [O, C] = await Promise.all([api('/hr/recruitment/openings'), api('/hr/recruitment/candidates' + (oid ? '?opening_id=' + oid : ''))]);
  B.innerHTML = `<div class="toolbar"><button class="btn p" data-call="EXT.recOpenForm">+ وظيفة شاغرة</button> <button class="btn" data-call="EXT.recRetention">محو بيانات المرفوضين</button></div>`
    + T(['الوظيفة', 'القسم', 'العدد', 'الحال', 'مرشحون', 'نشطون', 'عُيّنوا', ''], O.map(o => `<tr data-call="EXT.recFilter" data-args="${J([o.id])}" style="cursor:pointer" class="${o.id == oid ? 'sel' : ''}"><td>${esc(o.title)}</td><td>${esc(o.department || '—')}</td><td>${N(o.headcount)}</td><td>${pill(...OPN_ST[o.status])}</td><td>${N(o.candidates)}</td><td>${N(o.active)}</td><td>${N(o.hired)}</td>
      <td>${o.status === 'draft' || o.status === 'closed' ? `<button class="btn" data-call="EXT.recOpenSet" data-args="${J([o.id, 'open'])}">فتح</button> ` : ''}${o.status === 'open' ? `<button class="btn" data-call="EXT.recOpenSet" data-args="${J([o.id, 'closed'])}">إغلاق</button> <button class="btn p" data-call="EXT.recCandForm" data-args="${J([o.id])}">+ مرشح</button>` : ''}${o.status === 'draft' || o.status === 'open' ? ` <button class="btn" data-call="EXT.recOpenSet" data-args="${J([o.id, 'cancelled'])}">إلغاء</button>` : ''}</td></tr>`), 'لا وظائف شاغرة.')
    + BOX(`المرشحون${oid ? '' : ' (الكل)'} <span class="muted">${N(C.length)}</span>`, T(['المرشح', 'الوظيفة', 'المرحلة', 'مقابلات', 'متوسط الدرجات', ''], C.map(x => `<tr data-call="EXT.recCand" data-args="${J([x.id])}" style="cursor:pointer"><td>${esc(x.name)}</td><td>${esc(x.opening)}</td><td>${pill(...REC_ST[x.stage])}</td><td>${N(x.interviews_done)}</td><td>${x.avg_score == null ? '—' : F2(x.avg_score)}</td><td>${x.cv_document_id ? 'سيرة ✓' : ''}</td></tr>`), 'لا مرشحين.'));
};
EXT.recFilter = id => { EXT.recOpening = EXT.recOpening == id ? '' : id; EXT.l_hr(); };
EXT.recOpenSet = async (id, status) => { await tryDo(() => post(`/hr/recruitment/openings/${id}/status`, {status}), 'حُدّثت الوظيفة'); EXT.l_hr(); };
EXT.recOpenForm = async () => {
  const [D, P] = await Promise.all([api('/hr/departments'), api('/hr/positions')]);
  modal(`<h3>وظيفة شاغرة</h3>${HF('roT', 'المسمى', '', 'text', 'maxlength="120"')}${HS('roD', 'القسم', [['', '—']].concat(D.filter(d => d.active).map(d => [d.id, d.name])), '')}${HS('roP', 'المسمى الوظيفي المعتمد', [['', '—']].concat(P.filter(p => p.active).map(p => [p.id, p.title])), '')}${HF('roH', 'العدد المطلوب', '1', 'number', 'min="1"')}${HF('roC', 'آخر موعد للتقديم', '', 'date')}${HF('roR', 'المتطلبات', '', 'text', 'maxlength="2000"')}
    <div class="err" id="roE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="roGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#roGo').onclick = async () => { try { await post('/hr/recruitment/openings', {title: $('#roT').value.trim(), department_id: +$('#roD').value || null, position_id: +$('#roP').value || null, headcount: +$('#roH').value || 1, closes_on: $('#roC').value, requirements: $('#roR').value.trim()}); closeModal(); toast('أُضيفت الوظيفة (مسودة — افتحها للتقديم)'); EXT.l_hr(); } catch (e) { $('#roE').textContent = e.message; } };
};
EXT.recCandForm = id => {
  modal(`<h3>مرشح جديد</h3>${HF('rcN', 'الاسم', '', 'text', 'maxlength="120"')}${HF('rcP', 'الهاتف', '', 'text', 'dir="ltr"')}${HF('rcE', 'البريد', '', 'email', 'dir="ltr"')}${HF('rcS', 'المصدر', '', 'text')}<div class="err" id="rcErr"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="rcGo">إضافة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#rcGo').onclick = async () => { try { await post('/hr/recruitment/candidates', {opening_id: id, name: $('#rcN').value.trim(), phone: $('#rcP').value.trim(), email: $('#rcE').value.trim(), source: $('#rcS').value.trim()}); closeModal(); toast('أُضيف المرشح'); EXT.l_hr(); } catch (e) { $('#rcErr').textContent = e.message; } };
};
EXT.recCand = async id => {
  const x = await api('/hr/recruitment/candidates/' + id), live = ['applied', 'screening', 'interview', 'offer'].includes(x.stage);
  insp(x.name, `${KP([['المرحلة', REC_ST[x.stage][0]], ['الوظيفة', esc(x.opening)], ['الهاتف', esc(x.phone || '—')], ['البريد', esc(x.email || '—')]])}${x.anonymized ? '<p class="muted">محوت بياناته بعد مدة الاحتفاظ.</p>' : ''}
    ${x.cv_document_id ? `<a class="btn" href="/api/documents/${x.cv_document_id}" target="_blank" rel="noopener">السيرة الذاتية</a>` : live ? `<button class="btn" data-call="EXT.recCv" data-args="${J([id])}">رفع السيرة</button>` : ''}
    ${BOX('المقابلات', T(['الموعد', 'النوع', 'المحاور', 'الحال', 'الدرجة', ''], x.interviews.map(i => `<tr><td>${esc(i.scheduled_at)}</td><td>${esc(i.kind)}</td><td>${esc(i.interviewer || '—')}</td><td>${esc(i.status)}</td><td>${i.score ?? '—'}</td><td>${i.status === 'scheduled' ? `<button class="btn" data-call="EXT.recResult" data-args="${J([i.id, id])}">النتيجة</button>` : ''}</td></tr>`), 'لا مقابلات.'), live && ['screening', 'interview'].includes(x.stage) ? `<button class="btn" data-call="EXT.recInterviewForm" data-args="${J([id])}">+ مقابلة</button>` : '')}
    ${x.notes ? `<p>${esc(x.notes)}</p>` : ''}${x.reject_reason ? `<p class="muted">سبب الرفض: ${esc(x.reject_reason)}</p>` : ''}
    <div class="btns">${REC_NEXT[x.stage] ? `<button class="btn p" data-call="EXT.recStage" data-args="${J([id, REC_NEXT[x.stage]])}">← ${REC_ST[REC_NEXT[x.stage]][0]}</button>` : ''}${x.stage === 'offer' ? `<button class="btn p" data-call="EXT.recHire" data-args="${J([id])}">تعيين</button>` : ''}${live ? ` <button class="btn" data-call="EXT.recStage" data-args="${J([id, 'rejected'])}">رفض</button> <button class="btn" data-call="EXT.recStage" data-args="${J([id, 'withdrawn'])}">انسحاب</button>` : ''}</div>`);
};
EXT.recStage = async (id, stage) => {
  let reason = ''; if (stage === 'rejected') { reason = prompt('سبب الرفض (إلزامي):', '') || ''; if (!reason.trim()) return; }
  await tryDo(() => post(`/hr/recruitment/candidates/${id}/stage`, {stage, reason}), 'حُدّثت المرحلة'); EXT.recCand(id); EXT.l_hr();
};
EXT.recCv = id => { const f = document.createElement('input'); f.type = 'file'; f.accept = '.pdf,.png,.jpg,.jpeg'; f.onchange = async () => { if (f.files[0]) { await tryDo(() => hrUpload(`/hr/recruitment/candidates/${id}/cv`, f.files[0]), 'رُفعت السيرة'); EXT.recCand(id); } }; f.click(); };
EXT.recInterviewForm = id => {
  modal(`<h3>مقابلة</h3>${HF('riD', 'الموعد', hrDay(), 'date')}${HF('riT', 'الوقت', '10:00', 'time')}${HS('riK', 'النوع', [['in_person', 'حضورية'], ['online', 'عن بُعد'], ['phone', 'هاتفية'], ['technical', 'فنية']], 'in_person')}${HF('riI', 'المحاور', '', 'text')}<div class="err" id="riE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="riGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#riGo').onclick = async () => { try { await post(`/hr/recruitment/candidates/${id}/interviews`, {scheduled_at: $('#riD').value + ' ' + $('#riT').value, kind: $('#riK').value, interviewer: $('#riI').value.trim()}); closeModal(); EXT.recCand(id); EXT.l_hr(); } catch (e) { $('#riE').textContent = e.message; } };
};
EXT.recResult = async (iid, cid) => {
  const s = +prompt('درجة المقابلة من 1 إلى 5:', '3'); if (!s) return; const notes = prompt('ملاحظات:', '') || '';
  await tryDo(() => post(`/hr/recruitment/interviews/${iid}/result`, {score: s, notes}), 'سُجّلت النتيجة'); EXT.recCand(cid);
};
EXT.recHire = id => {
  modal(`<h3>تعيين المرشح</h3>${HF('rhD', 'تاريخ المباشرة', hrDay(), 'date')}<label><input type="checkbox" id="rhO"> عُماني</label>${HS('rhG', 'الجنس', [['', '—'], ['male', 'ذكر'], ['female', 'أنثى']], '')}${HS('rhC', 'نوع العقد', [['permanent', 'دائم'], ['fixed', 'محدد المدة'], ['part', 'جزئي']], 'permanent')}${HF('rhE', 'نهاية العقد', '', 'date')}${HF('rhP', 'نهاية التجربة', '', 'date')}
    <p class="muted">يُفتح ملف الموظف بقسمه ومسماه من الوظيفة، وتنتقل السيرة إلى ملفه وتُمحى بيانات الاتصال من التوظيف.</p><div class="err" id="rhErr"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="rhGo">تعيين</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#rhGo').onclick = async () => { try { const r = await post(`/hr/recruitment/candidates/${id}/hire`, {hire_date: $('#rhD').value, omani: $('#rhO').checked, gender: $('#rhG').value || null, contract_type: $('#rhC').value, contract_end: $('#rhE').value, probation_end: $('#rhP').value}); closeModal(); document.body.classList.remove('io'); toast('فُتح ملف ' + r.number); EXT.l_hr(); } catch (e) { $('#rhErr').textContent = e.message; } };
};
EXT.recRetention = async () => {
  const r = await api('/hr/recruitment/retention');
  modal(`<h3>محو بيانات المرشحين غير المعيَّنين</h3><p>تُمحى بيانات من رُفض أو انسحب بعد <b>${N(r.days)}</b> يومًا (الاسم والهاتف والبريد والملاحظات وملف السيرة) تلقائيًا كل يوم. لا يقل الحد عن 30 يومًا، والمحو لا رجعة فيه.</p>${HF('rrD', 'مدة الاحتفاظ بالأيام', r.days, 'number', 'min="30"')}<div class="err" id="rrE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="rrSave">حفظ المدة</button> <button class="btn" id="rrNow">امحُ المستحق الآن</button> <button class="btn" data-call="closeModal">إغلاق</button></div>`);
  $('#rrSave').onclick = async () => { try { await api('/hr/recruitment/retention', {method: 'PUT', body: {days: +$('#rrD').value}}); closeModal(); toast('حُفظت المدة'); } catch (e) { $('#rrE').textContent = e.message; } };
  $('#rrNow').onclick = async () => { if (!confirm('محو لا رجعة فيه. متابعة؟')) return; try { const x = await post('/hr/recruitment/purge', {days: +$('#rrD').value}); closeModal(); toast('مُحي ' + N(x.erased) + ' مرشحًا'); EXT.l_hr(); } catch (e) { $('#rrE').textContent = e.message; } };
};

/* ---- التقييم السنوي */
EXT.hrApr = async function (B) {
  const cyc = this.aprCycle || '', Cy = await api('/hr/appraisal-cycles'), A_ = await api('/hr/appraisals' + (cyc ? '?cycle_id=' + cyc : ''));
  B.innerHTML = `<div class="toolbar"><button class="btn p" data-call="EXT.aprCycleForm">+ دورة تقييم</button></div>` + hrNote('الدرجة الكلية تُحسب ولا تُكتب: 70٪ للأهداف الموزونة و30٪ للكفاءات على مقياس 1–5. القرار (ترقية، زيادة…) يُسجَّل هنا ولا يغيّر راتبًا.')
    + T(['الدورة', 'السنة', 'الحال', 'التقييمات', 'اكتمل', ''], Cy.map(k => `<tr data-call="EXT.aprFilter" data-args="${J([k.id])}" style="cursor:pointer" class="${k.id == cyc ? 'sel' : ''}"><td>${esc(k.name)}</td><td>${N(k.year)}</td><td>${pill(...CYC_ST[k.status])}</td><td>${N(k.total)}</td><td>${N(k.done)}</td>
      <td>${k.status !== 'closed' ? `<button class="btn p" data-call="EXT.aprCycleDo" data-args="${J([k.id, 'open'])}">${k.status === 'draft' ? 'فتح وتوليد التقييمات' : 'إضافة الناقص'}</button> ` : ''}${k.status === 'open' ? `<button class="btn" data-call="EXT.aprCycleDo" data-args="${J([k.id, 'close'])}">إغلاق</button>` : ''}</td></tr>`), 'لا دورات.')
    + BOX(`التقييمات <span class="muted">${N(A_.length)}</span>`, T(['الموظف', 'المراجع', 'الحال', 'الدرجة', 'التصنيف', 'القرار'], A_.map(a => `<tr data-call="EXT.aprView" data-args="${J([a.id])}" style="cursor:pointer"><td>${esc(a.name)} <small class="muted">${esc(a.number)}</small></td><td>${esc(a.reviewer || '—')}</td><td>${pill(...APR_ST[a.status])}</td><td>${a.overall == null ? '—' : F2(a.overall)}</td><td>${esc(a.rating || '—')}</td><td>${a.status === 'final' || a.status === 'ack' ? APR_DEC[a.decision] : '—'}</td></tr>`), 'لا تقييمات.'));
};
EXT.aprFilter = id => { EXT.aprCycle = EXT.aprCycle == id ? '' : id; EXT.l_hr(); };
EXT.aprCycleForm = () => {
  const y = new Date().getFullYear();
  modal(`<h3>دورة تقييم</h3>${HF('acN', 'الاسم', 'تقييم ' + y, 'text')}${HF('acY', 'السنة', y, 'number')}${HF('acS', 'من', y + '-01-01', 'date')}${HF('acE', 'إلى', y + '-12-31', 'date')}<div class="err" id="acE2"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="acGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#acGo').onclick = async () => { try { await post('/hr/appraisal-cycles', {name: $('#acN').value.trim(), year: +$('#acY').value, start_date: $('#acS').value, end_date: $('#acE').value}); closeModal(); toast('أُنشئت الدورة'); EXT.l_hr(); } catch (e) { $('#acE2').textContent = e.message; } };
};
EXT.aprCycleDo = async (id, what) => {
  if (what === 'close') { try { await post(`/hr/appraisal-cycles/${id}/close`, {force: false}); toast('أُغلقت الدورة'); } catch (e) { if (confirm(e.message + '\nأغلق بتجاوز صريح؟')) { await tryDo(() => post(`/hr/appraisal-cycles/${id}/close`, {force: true}), 'أُغلقت الدورة'); } } EXT.l_hr(); return; }
  const r = await tryDo(() => post(`/hr/appraisal-cycles/${id}/open`)); toast('أُضيف ' + N(r.added) + ' تقييمًا'); EXT.l_hr();
};
const aprGoals = a => T(['الهدف', 'الوزن', 'ذاتي', 'المدير'], a.goals.map(g => `<tr><td>${esc(g.title)}</td><td>${N(g.weight)}٪</td><td>${g.self_score ?? '—'}</td><td>${g.mgr_score ?? '—'}</td></tr>`), 'لا أهداف بعد.')
  + T(['الكفاءة', 'ذاتي', 'المدير'], a.competencies.map(k => `<tr><td>${esc(k.name)}</td><td>${k.self_score ?? '—'}</td><td>${k.mgr_score ?? '—'}</td></tr>`));
EXT.aprView = async id => {
  const a = await api('/hr/appraisals/' + id);
  insp(`${a.name} — ${a.cycle}`, `${KP([['الحال', APR_ST[a.status][0]], ['الدرجة', a.overall == null ? '—' : F2(a.overall)], ['التصنيف', esc(a.rating || '—')], ['القرار', a.status === 'final' || a.status === 'ack' ? APR_DEC[a.decision] : '—']])}${aprGoals(a)}
    ${a.self_comment ? `<p><b>الموظف:</b> ${esc(a.self_comment)}</p>` : ''}${a.manager_comment ? `<p><b>المدير:</b> ${esc(a.manager_comment)}</p>` : ''}${a.hr_comment ? `<p><b>الموارد البشرية:</b> ${esc(a.hr_comment)}</p>` : ''}
    <div class="btns">${a.status === 'hr' ? `<button class="btn p" data-call="EXT.aprFinalForm" data-args="${J([id])}">اعتماد وقرار</button>` : ''}${a.status === 'manager' && !a.reviewer_id ? `<button class="btn p" data-call="EXT.aprReviewForm" data-args="${J([id, true])}">مراجعة (لا مدير)</button>` : ''}</div>`);
};
EXT.aprFinalForm = id => {
  modal(`<h3>اعتماد التقييم</h3>${HS('afD', 'القرار', Object.entries(APR_DEC), 'none')}${HF('afC', 'تعليق الموارد البشرية', '', 'text', 'maxlength="1500"')}${hrNote('القرار يُسجَّل فقط ولا يغيّر راتبًا.')}<div class="err" id="afE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="afGo">اعتماد</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#afGo').onclick = async () => { try { await post(`/hr/appraisals/${id}/finalize`, {decision: $('#afD').value, hr_comment: $('#afC').value.trim()}); closeModal(); document.body.classList.remove('io'); toast('اعتُمد التقييم'); EXT.l_hr(); } catch (e) { $('#afE').textContent = e.message; } };
};
/* مراجعة المدير (وللموارد البشرية حين لا مدير) */
EXT.aprReviewForm = async (id, asHr) => {
  const a = await api(asHr ? '/hr/appraisals/' + id : '/hr/team-appraisals').then(x => asHr ? x : x.find(y => y.id === id));
  modal(`<h3>مراجعة تقييم ${esc(a.name)}</h3>${T(['الهدف (الوزن)', 'ذاتي', 'درجتك'], a.goals.map((g, i) => `<tr><td>${esc(g.title)} (${N(g.weight)}٪)</td><td>${g.self_score}</td><td><input class="rvG" type="number" min="1" max="5" style="width:70px"></td></tr>`))}
    ${T(['الكفاءة', 'ذاتي', 'درجتك'], a.competencies.map(k => `<tr><td>${esc(k.name)}</td><td>${k.self_score}</td><td><input class="rvC" type="number" min="1" max="5" style="width:70px"></td></tr>`))}${HF('rvM', 'تعليقك', '', 'text', 'maxlength="1500"')}<div class="err" id="rvE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="rvGo">إرسال</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#rvGo').onclick = async () => { try { await api(`/hr/${asHr ? 'appraisals' : 'team/appraisals'}/${id}/review`, {method: 'PUT', body: {goal_scores: $$('.rvG').map(x => +x.value || 0), competency_scores: $$('.rvC').map(x => +x.value || 0), manager_comment: $('#rvM').value.trim(), submit: true}}); closeModal(); toast('أُرسلت المراجعة'); EXT.hrRefresh(); } catch (e) { $('#rvE').textContent = e.message; } };
};

/* ---- التدريب */
EXT.hrTrn = async function (B) {
  const [Co, R, Cm] = await Promise.all([api('/hr/training/courses'), api('/hr/training/records'), api('/hr/training/compliance')]), bad = Cm.filter(x => x.state !== 'valid');
  B.innerHTML = `<div class="toolbar"><button class="btn p" data-call="EXT.trnCourseForm">+ دورة</button> <button class="btn" data-call="EXT.trnRecForm">+ سجل تدريب</button></div>`
    + (bad.length ? BOX(`الدورات الإلزامية — ما يحتاج متابعة <span class="muted">${N(bad.length)}</span>`, T(['الموظف', 'الدورة', 'الحال', 'المدة'], bad.map(x => `<tr><td>${esc(x.name)} <small class="muted">${esc(x.number)}</small></td><td>${esc(x.course)}</td><td>${pill(...CMP_ST[x.state])}</td><td>${x.days_left == null ? '—' : hrAgo(x.days_left)}</td></tr>`))) : '')
    + BOX('الدورات', T(['الدورة', 'الجهة', 'الساعات', 'صلاحية الشهادة', 'إلزامية', 'أُتمّت'], Co.map(t => `<tr><td>${esc(t.title)}</td><td>${esc(t.provider || '—')}</td><td>${F2(t.hours)}</td><td>${t.cert_valid_months ? N(t.cert_valid_months) + ' شهرًا' : '—'}</td><td>${t.mandatory ? 'نعم' : '—'}</td><td>${N(t.completed)}</td></tr>`), 'لا دورات.'))
    + BOX('السجلات', T(['الموظف', 'الدورة', 'الحال', 'التاريخ', 'الدرجة', 'تنتهي الشهادة'], R.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.course)}</td><td>${pill(...TRN_ST[r.status])}</td><td>${fmtDate(r.completed_on || r.planned_on)}</td><td>${r.score ?? '—'}</td><td>${r.cert_expires ? fmtDate(r.cert_expires) + ' ' + (r.days_left < 0 ? pill('منتهية', 'p-b') : r.days_left <= 90 ? pill(hrAgo(r.days_left), 'p-w') : '') : '—'}</td></tr>`), 'لا سجلات.'));
};
EXT.trnCourseForm = () => {
  modal(`<h3>دورة تدريبية</h3>${HF('tcT', 'العنوان', '', 'text', 'maxlength="120"')}${HF('tcP', 'الجهة المقدِّمة', '')}${HF('tcH', 'الساعات', '8', 'number', 'min="0"')}${HF('tcV', 'صلاحية الشهادة بالأشهر (اختياري)', '', 'number', 'min="1"')}<label><input type="checkbox" id="tcM"> إلزامية لكل العاملين</label><div class="err" id="tcE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="tcGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#tcGo').onclick = async () => { try { await post('/hr/training/courses', {title: $('#tcT').value.trim(), provider: $('#tcP').value.trim(), hours: +$('#tcH').value || 0, cert_valid_months: +$('#tcV').value || null, mandatory: $('#tcM').checked}); closeModal(); toast('أُضيفت الدورة'); EXT.l_hr(); } catch (e) { $('#tcE').textContent = e.message; } };
};
EXT.trnRecForm = async () => {
  const [Co, E] = await Promise.all([api('/hr/training/courses'), api('/hr/employees?status=current')]);
  modal(`<h3>سجل تدريب</h3>${HS('trE', 'الموظف', E.map(e => [e.id, `${e.number} — ${e.name}`]), '')}${HS('trC', 'الدورة', Co.map(t => [t.id, t.title]), '')}${HS('trS', 'الحال', [['planned', 'مخطط'], ['completed', 'أُتمّت'], ['no_show', 'لم يحضر'], ['cancelled', 'ملغاة']], 'completed')}${HF('trP', 'التاريخ المخطط', '', 'date')}${HF('trD', 'تاريخ الإتمام', hrDay(), 'date')}${HF('trN', 'رقم الشهادة', '')}${HF('trX', 'انتهاء الشهادة (يُحسب من الدورة إن تُرك فارغًا)', '', 'date')}
    <div class="err" id="trErr"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="trGo">حفظ</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#trGo').onclick = async () => { try { await post('/hr/training/records', {employee_id: +$('#trE').value, course_id: +$('#trC').value, status: $('#trS').value, planned_on: $('#trP').value, completed_on: $('#trD').value, certificate_no: $('#trN').value.trim(), cert_expires: $('#trX').value}); closeModal(); toast('سُجّل'); EXT.l_hr(); } catch (e) { $('#trErr').textContent = e.message; } };
};

/* ---- الجزاءات */
EXT.hrDsc = async function (B) {
  const [Ru, Ca] = await Promise.all([api('/hr/discipline/rules'), api('/hr/discipline/cases')]), appr = Ru.filter(r => r.status === 'approved');
  B.innerHTML = (appr.length ? '' : BOX('لا لائحة معتمدة', '<p>لا يجوز إصدار أي جزاء قبل أن تُدخَل مواد اللائحة المعتمدة رسميًا في المنشأة ويعتمدها شخص ثانٍ. أدخل المواد بمصدرها (رقم اللائحة والمادة) أدناه.</p>'))
    + BOX('مواد اللائحة', T(['الرمز', 'المادة', 'النوع', 'الحد الأقصى', 'المصدر', 'الحال', ''], Ru.map(r => `<tr><td>${esc(r.code)}</td><td>${esc(r.name)}</td><td>${DSC_KIND[r.kind]}</td><td>${r.kind === 'warning' ? '—' : F2(r.max_days) + ' يومًا'}</td><td>${esc(r.source)}</td><td>${r.status === 'approved' ? pill('معتمدة منذ ' + r.valid_from, 'p-ok') : r.status === 'draft' ? pill('مسودة', 'p-w') : pill('موقوفة', 'p-b')}</td>
        <td>${r.status === 'draft' ? `<button class="btn p" data-call="EXT.dscRuleApprove" data-args="${J([r.id])}" ${r.created_by === S.me.username ? 'disabled title="لا تعتمد مادة أنشأتها"' : ''}>اعتماد</button>` : r.status === 'approved' ? `<button class="btn" data-call="EXT.dscRuleRetire" data-args="${J([r.id])}">إيقاف</button>` : ''}</td></tr>`), 'لا مواد.'), '<button class="btn p" data-call="EXT.dscRuleForm">+ مادة</button>')
    + BOX(`القضايا <span class="muted">${N(Ca.length)}</span>`, T(['الرقم', 'الموظف', 'الواقعة', 'المادة', 'الحال', ''], Ca.map(x => `<tr data-call="EXT.dscCase" data-args="${J([x.id])}" style="cursor:pointer"><td>${esc(x.number)}</td><td>${esc(x.emp_name)}</td><td>${fmtDate(x.incident_date)}</td><td>${esc(x.rule_code || '—')}</td><td>${pill(...DSC_ST[x.status])}</td><td></td></tr>`), 'لا قضايا.'), '<button class="btn p" data-call="EXT.dscCaseForm">+ قضية</button>');
};
EXT.dscRuleForm = () => {
  modal(`<h3>مادة من اللائحة</h3>${HF('drC', 'الرمز', '', 'text', 'maxlength="20"')}${HF('drN', 'المادة (مثل: التأخر المتكرر)', '', 'text', 'maxlength="120"')}${HS('drK', 'نوع الجزاء', Object.entries(DSC_KIND), 'warning')}${HF('drM', 'الحد الأقصى للأيام (للخصم والإيقاف)', '0', 'number', 'min="0" step="0.5"')}${HF('drS', 'المصدر (اللائحة المعتمدة والمادة)', '', 'text', 'maxlength="300"')}
    <div class="err" id="drE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="drGo">حفظ كمسودة</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#drGo').onclick = async () => { try { await post('/hr/discipline/rules', {code: $('#drC').value.trim(), name: $('#drN').value.trim(), kind: $('#drK').value, max_days: +$('#drM').value || 0, source: $('#drS').value.trim()}); closeModal(); toast('حُفظت المسودة — يعتمدها شخص آخر'); EXT.l_hr(); } catch (e) { $('#drE').textContent = e.message; } };
};
EXT.dscRuleApprove = id => {
  modal(`<h3>اعتماد مادة</h3><p>تؤكد أن نص المادة يطابق اللائحة المعتمدة في المنشأة.</p>${HF('daV', 'تاريخ سريان اللائحة نفسها', hrDay(), 'date')}<div class="err" id="daE"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="daGo">اعتماد</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#daGo').onclick = async () => { try { await post(`/hr/discipline/rules/${id}/approve`, {valid_from: $('#daV').value}); closeModal(); toast('اعتُمدت المادة'); EXT.l_hr(); } catch (e) { $('#daE').textContent = e.message; } };
};
EXT.dscRuleRetire = async id => { if (!confirm('إيقاف المادة؟ لا يُصدر بها جزاء جديد.')) return; await tryDo(() => post(`/hr/discipline/rules/${id}/retire`), 'أُوقفت'); EXT.l_hr(); };
EXT.dscCaseForm = async () => {
  const E = await api('/hr/employees?status=current');
  modal(`<h3>قضية تأديبية</h3>${HS('dcE', 'الموظف', E.map(e => [e.id, `${e.number} — ${e.name}`]), '')}${HF('dcD', 'تاريخ الواقعة', hrDay(), 'date')}${HF('dcT', 'وصف الواقعة', '', 'text', 'maxlength="2000"')}${HF('dcW', 'الشهود', '', 'text')}<div class="err" id="dcErr"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="dcGo">فتح القضية</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#dcGo').onclick = async () => { try { const r = await post('/hr/discipline/cases', {employee_id: +$('#dcE').value, incident_date: $('#dcD').value, description: $('#dcT').value.trim(), witnesses: $('#dcW').value.trim()}); closeModal(); toast('فُتحت ' + r.number); EXT.l_hr(); } catch (e) { $('#dcErr').textContent = e.message; } };
};
EXT.dscCase = async id => {
  const x = await api('/hr/discipline/cases/' + id), me = S.me.username;
  insp(`${x.number} — ${x.emp_name}`, `${KP([['الحال', DSC_ST[x.status][0]], ['الواقعة', fmtDate(x.incident_date)], ['المادة', esc(x.rule_code ? x.rule_code + ' · ' + x.rule_name : '—')], ['الجزاء', x.rule_kind ? DSC_KIND[x.rule_kind] + (x.penalty_days ? ' ' + F2(x.penalty_days) + ' يومًا' : '') + (x.apply_period ? ' · ' + x.apply_period : '') : '—']])}
    <p>${esc(x.description)}</p>${x.witnesses ? `<p class="muted">الشهود: ${esc(x.witnesses)}</p>` : ''}${x.statement ? `<p><b>أقوال الموظف:</b> ${esc(x.statement)}</p>` : ''}${x.appeal_text ? `<p><b>تظلّمه:</b> ${esc(x.appeal_text)}</p>` : ''}${x.applied_run_id ? '<p class="muted">طُبّق الخصم في مسيّر الرواتب.</p>' : ''}
    <div class="btns">${x.status === 'open' ? `<button class="btn" data-call="EXT.dscStatement" data-args="${J([id])}">أقوال الموظف</button> <button class="btn p" data-call="EXT.dscPropose" data-args="${J([id])}">اقتراح جزاء</button> <button class="btn" data-call="EXT.dscClose" data-args="${J([id])}">إغلاق بلا جزاء</button>` : ''}
      ${x.status === 'proposed' ? `<button class="btn p" data-call="EXT.dscIssue" data-args="${J([id])}" ${x.proposed_by === me ? 'disabled title="لا تُصدر ما اقترحته"' : ''}>إصدار</button> <button class="btn" data-call="EXT.dscClose" data-args="${J([id])}">إغلاق بلا جزاء</button>` : ''}
      ${x.status === 'appealed' ? `<button class="btn p" data-call="EXT.dscDecide" data-args="${J([id, 'upheld'])}" ${x.issued_by === me ? 'disabled title="من أصدر لا يبتّ في التظلم"' : ''}>رفض التظلم</button> <button class="btn" data-call="EXT.dscDecide" data-args="${J([id, 'revoked'])}" ${x.issued_by === me ? 'disabled' : ''}>قبول التظلم وإلغاء الجزاء</button>` : ''}</div>`);
};
EXT.dscStatement = async id => { const s = prompt('أقوال الموظف (أو: رفض الإدلاء بأقواله):', ''); if (!s || s.trim().length < 3) return; await tryDo(() => post(`/hr/discipline/cases/${id}/statement`, {statement: s.trim()}), 'سُجّلت الأقوال'); EXT.dscCase(id); };
EXT.dscClose = async id => { const n = prompt('سبب الإغلاق بلا جزاء:', ''); if (!n || n.trim().length < 3) return; await tryDo(() => post(`/hr/discipline/cases/${id}/close`, {note: n.trim()}), 'أُغلقت'); document.body.classList.remove('io'); EXT.l_hr(); };
EXT.dscIssue = async id => { if (!confirm('إصدار الجزاء يُبلَّغ به الموظف ويحقّ له التظلم. متابعة؟')) return; await tryDo(() => post(`/hr/discipline/cases/${id}/issue`), 'صدر الجزاء'); EXT.dscCase(id); EXT.l_hr(); };
EXT.dscDecide = async (id, decision) => { await tryDo(() => post(`/hr/discipline/cases/${id}/appeal-decision`, {decision}), 'سُجّل القرار'); EXT.dscCase(id); EXT.l_hr(); };
EXT.dscPropose = async id => {
  const R = (await api('/hr/discipline/rules')).filter(r => r.status === 'approved');
  if (!R.length) { toast('لا مواد معتمدة في اللائحة', 1); return; }
  modal(`<h3>اقتراح جزاء</h3>${HS('dpR', 'المادة', R.map(r => [r.id, `${r.code} — ${r.name} (${DSC_KIND[r.kind]}${r.max_days ? '، حتى ' + F2(r.max_days) + ' يومًا' : ''})`]), '')}${HF('dpD', 'عدد الأيام (للخصم والإيقاف)', '', 'number', 'min="0" step="0.5"')}${HF('dpP', 'شهر الخصم (للخصم)', payMonth(), 'month')}<div class="err" id="dpE"></div>
    <div class="btns" style="margin-top:12px"><button class="btn p" id="dpGo">اقتراح</button> <button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#dpGo').onclick = async () => { try { await post(`/hr/discipline/cases/${id}/propose`, {rule_id: +$('#dpR').value, penalty_days: +$('#dpD').value || 0, apply_period: $('#dpP').value}); closeModal(); EXT.dscCase(id); EXT.l_hr(); } catch (e) { $('#dpE').textContent = e.message; } };
};

/* ---- بوابة الموظف: تقييمي وتدريبي وإشعاراتي */
EXT.meApr = async function (B) {
  const L = await api('/hr/me/appraisals');
  B.innerHTML = L.map(a => BOX(`${esc(a.cycle)} ${pill(...APR_ST[a.status])}`, (a.status === 'self' && a.cycle_status === 'open' ? `<div id="sf${a.id}"></div>` : `${KP([['الدرجة', a.overall == null ? '—' : F2(a.overall)], ['التصنيف', esc(a.rating || '—')], ['القرار', a.decision && a.decision !== 'none' ? APR_DEC[a.decision] : '—']])}${aprGoals(a)}${a.manager_comment ? `<p><b>مديري:</b> ${esc(a.manager_comment)}</p>` : ''}${a.hr_comment ? `<p><b>الموارد البشرية:</b> ${esc(a.hr_comment)}</p>` : ''}${a.status === 'self' ? '' : a.status === 'final' ? `<div class="btns"><button class="btn p" data-call="EXT.meAck" data-args="${J([a.id])}">أقرّ بالاطلاع</button></div>` : ''}`))).join('') || '<p class="muted">لا تقييمات مفتوحة لك.</p>';
  L.filter(a => a.status === 'self' && a.cycle_status === 'open').forEach(a => EXT.meAprForm(a));
};
EXT.meAprForm = a => {
  const box = $('#sf' + a.id), goals = a.goals.length ? a.goals : [{title: '', weight: 100, self_score: null}];
  const row = g => `<tr><td><input class="sgT" value="${esc(g.title)}" placeholder="الهدف"></td><td><input class="sgW" type="number" min="1" max="100" value="${g.weight}" style="width:70px"></td><td><input class="sgS" type="number" min="1" max="5" value="${g.self_score ?? ''}" style="width:70px"></td></tr>`;
  box.innerHTML = hrNote('أدخل أهدافك (حتى 7) بأوزان مجموعها 100، وقيّم نفسك من 1 إلى 5. لا ترى تقييم مديرك قبل أن تعتمده الموارد البشرية.')
    + T(['الهدف', 'الوزن ٪', 'تقييمي'], goals.map(row)).replace('<tbody>', '<tbody id="sgb' + a.id + '">')
    + T(['الكفاءة', 'تقييمي (1–5)'], a.competencies.map(k => `<tr><td class="scN">${esc(k.name)}</td><td><input class="scS" type="number" min="1" max="5" value="${k.self_score ?? ''}" style="width:70px"></td></tr>`))
    + HF('sc' + a.id, 'تعليقي', a.self_comment || '', 'text', 'maxlength="1500"') + `<div class="err" id="se${a.id}"></div><div class="btns" style="margin-top:10px"><button class="btn" id="sa${a.id}">+ هدف</button> <button class="btn" id="sv${a.id}">حفظ مسودة</button> <button class="btn p" id="ss${a.id}">إرسال إلى مديري</button></div>`;
  $('#sa' + a.id).onclick = () => $('#sgb' + a.id).insertAdjacentHTML('beforeend', row({title: '', weight: 0, self_score: null}));
  const send = async submit => {
    const goals2 = $$('#sf' + a.id + ' .sgT').map((t, i) => ({title: t.value.trim(), weight: +$$('#sf' + a.id + ' .sgW')[i].value || 0, self_score: +$$('#sf' + a.id + ' .sgS')[i].value || null})).filter(g => g.title);
    const comps = $$('#sf' + a.id + ' .scN').map((n, i) => ({name: n.textContent, self_score: +$$('#sf' + a.id + ' .scS')[i].value || null}));
    try { await api(`/hr/me/appraisals/${a.id}/self`, {method: 'PUT', body: {goals: goals2, competencies: comps, self_comment: $('#sc' + a.id).value.trim(), submit}}); toast(submit ? 'أُرسل إلى مديرك' : 'حُفظت المسودة'); EXT.l_me(); } catch (e) { $('#se' + a.id).textContent = e.message; }
  };
  $('#sv' + a.id).onclick = () => send(false); $('#ss' + a.id).onclick = () => send(true);
};
EXT.meAck = async id => { const c = prompt('ملاحظتك على التقييم (اختياري):', '') || ''; await tryDo(() => post(`/hr/me/appraisals/${id}/ack`, {comment: c}), 'سُجّل إقرارك'); EXT.l_me(); };
EXT.meTrn = async function (B) {
  const r = await api('/hr/me/training');
  B.innerHTML = (r.mandatory_missing.length ? BOX('دورات إلزامية ناقصة أو منتهية', `<p>${r.mandatory_missing.map(esc).join('، ')}</p>`) : '') + T(['الدورة', 'الحال', 'التاريخ', 'الدرجة', 'تنتهي الشهادة'], r.records.map(x => `<tr><td>${esc(x.course)}</td><td>${pill(...TRN_ST[x.status])}</td><td>${fmtDate(x.completed_on || x.planned_on)}</td><td>${x.score ?? '—'}</td><td>${x.cert_expires ? fmtDate(x.cert_expires) : '—'}</td></tr>`), 'لا سجلات تدريب.');
};
EXT.meDsc = async function (B) {
  const L = await api('/hr/me/discipline');
  B.innerHTML = hrNote('هنا ما صدر بحقك فقط. لك التظلم خلال مدة محددة من الإصدار، ويبتّ فيه شخص غير من أصدر.') + T(['الرقم', 'الواقعة', 'المادة', 'الجزاء', 'الحال', ''], L.map(x => `<tr><td>${esc(x.number)}</td><td>${fmtDate(x.incident_date)}<br><small class="muted">${esc(x.description)}</small></td><td>${esc(x.rule_code || '')} ${esc(x.rule_name || '')}</td><td>${x.rule_kind ? DSC_KIND[x.rule_kind] + (x.penalty_days ? ' ' + F2(x.penalty_days) + ' يومًا' : '') : '—'}</td><td>${pill(...DSC_ST[x.status])}${x.appeal_decision ? ' <small class="muted">' + (x.appeal_decision === 'upheld' ? 'رُفض تظلمك' : 'قُبل تظلمك') + '</small>' : ''}</td>
      <td>${x.can_appeal ? `<button class="btn" data-call="EXT.meAppeal" data-args="${J([x.id])}">تظلّم</button>` : ''}</td></tr>`), 'لا إشعارات تأديبية.');
};
EXT.meAppeal = async id => { const t = prompt('نص التظلم (10 أحرف على الأقل):', ''); if (!t || t.trim().length < 10) return; await tryDo(() => post(`/hr/me/discipline/${id}/appeal`, {text: t.trim()}), 'قُدّم التظلم'); EXT.l_me(); };
EXT.meReviews = async function (B) {   // appraisals waiting for me as a manager (inside «فريقي»)
  const L = await api('/hr/team-appraisals');
  return BOX(`تقييمات بانتظار مراجعتك <span class="muted">${N(L.filter(a => a.status === 'manager').length)}</span>`, T(['الموظف', 'الدورة', 'الحال', ''], L.map(a => `<tr><td>${esc(a.name)}</td><td>${esc(a.cycle)}</td><td>${pill(...APR_ST[a.status])}</td><td>${a.status === 'manager' ? `<button class="btn p" data-call="EXT.aprReviewForm" data-args="${J([a.id, false])}">مراجعة</button>` : ''}</td></tr>`), 'لا تقييمات بانتظارك.'));
};
