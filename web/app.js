import * as CH from './charts.js';
import {t, applyI18n, toggleLang, lang} from './i18n.js';
/* مبانيك — منطق الواجهة. كل البيانات تأتي من الـ API الحي. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const nf = new Intl.NumberFormat('ar-OM-u-nu-latn'), N = v => nf.format(Math.round(v || 0));
const OMR = v => N(v) + '\u00a0ر.ع';
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
const SCREEN_PERM = {ov: 'view', inv: 'inventory', crm: 'leads', fin: 'finance', con: 'construction', svc: 'service', log: 'audit', pre: 'permits', sal: 'kyc', bill: 'invoices', post: 'handover', rep: 'reports', mk: 'leads', adm: 'view'};
const SCREEN_ANY = {pre: ['permits', 'land'], post: ['handover', 'oa', 'leasing', 'service'], sal: ['kyc', 'brokers', 'market'], rep: ['reports', 'finance', 'view'], mk: ['leads', 'inventory', 'reports']};  // Unit 7: reports for every staff role (the API filters by permission), marketing for sales/inventory/reports
const can = p => S.me?.perms.includes(p);
const canS = s => (SCREEN_ANY[s] || [SCREEN_PERM[s]]).some(can);
function go(s) {
  if (!canS(s)) s = canS('ov') ? 'ov' : 'rep';
  S.screen = s;
  $$('[data-s]').forEach(b => b.classList.toggle('on', b.dataset.s === s));
  $$('.scr').forEach(x => x.classList.toggle('on', x.id === s));
  localStorage.setItem('mbq-screen', s);
  ({ov: loadOverview, inv: loadInventory, crm: loadCRM, fin: loadFinance, con: () => { loadIPC(); EXT.l_conx(); }, svc: loadService, log: loadAudit,
    pre: () => EXT.l_pre(), sal: () => EXT.l_sal(), bill: () => EXT.l_bill(), post: () => EXT.l_post(), rep: () => EXT.l_rep(), mk: () => EXT.l_mk(), adm: () => EXT.l_adm()})[s]?.()?.catch?.(e => toast(e.message, 1));
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
  post: ['3 · التسليم والتشغيل', 'التسليم والأملاك', 'التسليم وملاحظات الفحص، ونقل الملكية، والمرافق واتحاد الملاك والتأجير.'],
  svc: ['3 · التسليم والتشغيل', 'خدمة العملاء', 'طلبات الصيانة وإعادة البيع الواردة من تطبيق العميل.'],
  mk: ['2 · البيع والإنشاء', 'تسويق المشاريع', 'حالة كل مشروع تسويقيًا، الحملات وقياسها، استوديو الإعلانات، والتنبيهات من حركة السوق.'],
  rep: ['الحوكمة', 'التقارير والتحليلات', 'تقرير البنك الممول بتقييم المخاطر، وتقرير المستثمرين بالربحية والتوزيعات.'],
  log: ['الحوكمة', 'سجل التدقيق', 'كل إجراء مسجّل بوقته ومنفّذه في سجل متسلسل يكشف أي تعديل.'],
  adm: ['الحوكمة', 'الإدارة والأمان', 'المستخدمون والصلاحيات، والتحقق الثنائي، والنسخ الاحتياطي والإشعارات والخصوصية.']};
const CYCLE = [['pre', 'الأرض والتراخيص'], ['inv', 'البيع والإنشاء'], ['post', 'التسليم والتشغيل']];
const STEP = {pre: 0, inv: 1, crm: 1, sal: 1, con: 1, post: 2, svc: 2};
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
$('#askBtn').onclick = () => insp('المساعد الذكي', '<p class="muted">اسأل عن بياناتك الحية في الأسفل، مثل: «ما المشروع الأخطر؟» أو «فجوة السيولة» أو «مبيعات هذا الشهر».</p>');
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
  const [k, dec, projects] = await Promise.all([api('/kpis'), api('/decisions'), api('/projects')]);
  renderCycle(projects);
  const cash = await api('/cash');
  $('#kpis').innerHTML = `
    <div><small>مبيعات آخر 30 يومًا</small><b>${K(k.sales_30d_value)} ر.ع</b><small>${N(k.sales_30d_count)} وحدة</small></div>
    <div><small>نسبة التحصيل (90 يومًا)</small><b>${N(k.collection_rate)}٪</b><small>من الأقساط المستحقة</small></div>
    <div><small>فجوة السيولة المتوقعة</small><b style="color:${cash.gap ? 'var(--bad)' : 'var(--ok)'}">${cash.gap ? K(cash.gap) + ' ر.ع' : 'لا توجد'}</b><small>${cash.gap ? esc(cash.worst_project) + ' · ' + fmtMonth(cash.worst.month) : 'خلال 12 شهرًا'}</small></div>
    <div><small>المخزون المتاح</small><b>${N(k.available)}</b><small>من ${N(k.total_units)} وحدة</small></div>`;
  DEC = dec;
  $('#qc').textContent = N(dec.filter(d => !d.done).length) + ' مفتوحة';
  $('#dq').innerHTML = dec.map((d, i) => `<tr data-i="${i}" class="${d.done ? 'done' : ''}"><td>${tx(d.title)}</td><td>${pill(esc(d.source), 'p-bl')}</td><td>${K(d.impact)} ر.ع<br><span class="muted">${esc(d.impact_label)}</span></td><td>${pill(d.priority, d.priority === 'حرجة' ? 'p-b' : 'p-w')}</td><td>${d.done ? pill(d.done === 'approve' ? '✓ معتمد' : 'متجاهَل', d.done === 'approve' ? 'p-ok' : '') : pill('مفتوح', 'p-w')}</td></tr>`).join('');
  $$('#dq tr').forEach(tr => tr.onclick = () => { sel(tr); showDecision(DEC[+tr.dataset.i]); });
  const byP = Object.fromEntries(cash.projects.map(p => [p.project_id, p]));
  $('#ph').innerHTML = projects.map(p => `<tr data-p="${p.id}"><td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.location)} · ${N(p.total_units)} ${p.kind === 'villa' ? 'فيلا' : 'وحدة'}</span></td>
    <td><span class="bar-s"><i style="width:${p.build_pct}%"></i></span>${N(p.build_pct)}٪</td><td>${N(p.sold_pct)}٪</td><td>${N(p.available)}</td>
    <td>${N(byP[p.id].sales_pace)} / ${N(p.planned_monthly_sales)} شهريًا</td>
    <td>${byP[p.id].gap ? pill('عجز ' + K(byP[p.id].gap), 'p-b') : pill('سليم', 'p-ok')}</td></tr>`).join('');
  $$('#ph tr').forEach(tr => tr.onclick = () => { S.proj = +tr.dataset.p; S.bld = null; go('inv'); });
}
function showDecision(d) {
  let act = '';
  if (!d.done && !can('decide')) act = `<span class="muted">اعتماد القرارات من صلاحية الإدارة والمالية.</span>`;
  else if (!d.done) {
    if (d.kind === 'ipc') act = `<button class="btn p" data-call="go" data-args="${J(['con'])}">فتح المستخلص للمراجعة</button>`;
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
  if (p.kind === 'villa') {
    h.className = 'heat villas'; h.style.gridTemplateColumns = '';
    h.innerHTML = list.map(cell).join('');
    $('#invTitle').textContent = 'المخطط العام للفلل';
  } else {
    const cols = Math.max(...list.map(u => u.pos));
    h.className = 'heat'; h.style.gridTemplateColumns = `44px repeat(${cols},1fr)`;
    const floors = [...new Set(list.map(u => u.floor))].sort((a, b) => b - a);
    h.innerHTML = floors.map(f => `<span class="fl">ط ${N(f)}</span>` + list.filter(u => u.floor === f).sort((a, b) => a.pos - b.pos).map(cell).join('')).join('');
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
  let h = `<h3><span class="num">${esc(u.code)}</span> ${pill(ST[u.status], u.status === 'a' ? 'p-ok' : u.status === 'r' ? 'p-w' : 'p-bl')}</h3>
   <dl class="kv"><dt>النوع</dt><dd>${esc(u.type)}</dd><dt>المساحة</dt><dd>${N(u.area)} م²</dd>${u.floor ? `<dt>الطابق</dt><dd>${N(u.floor)}</dd>` : ''}<dt>الموقع/الإطلالة</dt><dd>${esc(u.view)}</dd><dt>السعر</dt><dd>${OMR(u.price)}</dd><dt>سعر المتر</dt><dd>${OMR(u.price / u.area)}</dd></dl>`;
  if (u.suggestion) {
    const s = u.suggestion;
    h += `<div class="ai"><b class="k">✦ التسعير الديناميكي:</b> ${s.change ? `${s.change > 0 ? 'رفع' : 'خفض'} ${N(Math.abs(s.change * 100))}٪ ← <b>${OMR(s.price)}</b>` : 'السعر الحالي متوافق مع الطلب.'}<br><span class="muted">${tx(s.reason)}</span></div>`;
  }
  if (u.status === 'a' && can('book')) h += `<div class="btns"><button class="btn p" data-call="openBooking" data-args="${J([u.code])}">حجز الوحدة لعميل</button><button class="btn" data-call="EXT.newQuote" data-args="${J([u.code])}">عرض سعر</button></div>`;
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
$('#cf').onsubmit = async e => {
  e.preventDefault(); const q = $('#ci').value.trim(); if (!q) return; $('#ci').value = '';
  const log = $('#clog'); log.insertAdjacentHTML('beforeend', `<div class="q">${esc(q)}</div><div class="a" id="pend">…</div>`); log.scrollTop = 1e6;
  try { const r = await api('/assistant', {method: 'POST', body: {q}}); const p = $('#pend'); p.removeAttribute('id'); p.innerHTML = `${tx(r.answer)}<small>المصدر: ${esc(r.source)}</small>`; }
  catch (err) { $('#pend').textContent = err.message; }
  log.scrollTop = 1e6;
};

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
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); pal(1); } if (e.key === 'Escape') { pal(0); closeModal(); document.body.classList.remove('io', 'nav-open'); } });

/* ---------------- تشغيل ---------------- */
async function refreshAll() { if (can('view')) await loadSide(); else $('#pfSec').classList.add('hidden'); go(S.screen); }
function groupsVis() { $$('.side .grp').forEach(g => { if (g.id === 'pfSec') return; g.classList.toggle('hidden', !g.querySelector('.ni:not(.hidden)')); }); }
(async () => {
  if (localStorage.getItem('mbq-theme') === 'l') document.body.classList.add('light');
  S.screen = localStorage.getItem('mbq-screen') || 'ov';
  try {
    S.me = await api('/me');
    $('#whoName').textContent = S.me.name; $('#whoRole').textContent = S.me.role_label;
    $$('[data-s]').forEach(b => b.classList.toggle('hidden', !canS(b.dataset.s)));
    $('#resetBtn').classList.toggle('hidden', !can('admin')); groupsVis();
    if (S.me.role === 'broker') { location.href = '/broker'; return; }
    if (S.me.role === 'investor') { S.screen = 'rep'; }
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
const subOk = (id, k) => !SUBP[id + '.' + k] || SUBP[id + '.' + k].some(p => can(p));
const SUB0 = (id, tabs, cur) => `<div class="seg subt" style="margin-bottom:14px">${tabs.map(([k, l]) => `<button class="${k === cur ? 'on' : ''}" data-call="EXT.sub" data-args="${J([id, k])}">${l}</button>`).join('')}</div>`;
const SUB = (id, tabs, cur) => { const t = tabs.filter(([k]) => subOk(id, k)); return t.length > 1 ? SUB0(id, t, cur) : ''; };
const pct = v => N(v) + '٪';
const AR = s => esc(s);
const ND = (v, d = 2) => new Intl.NumberFormat('ar-OM-u-nu-latn', {maximumFractionDigits: d}).format(+v || 0);
const tryDo = async (fn, ok) => { try { const r = await fn(); if (ok) toast(typeof ok === 'function' ? ok(r) : ok); return r; } catch (e) { toast(e.message, 1); throw e; } };
const projOpts = (cur) => S.projects.map(p => `<option value="${p.id}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('');

const EXT = {
  cur: {pre: 'land', post: 'hand', sal: 'kyc', bill: 'inv', adm: 'users', rep: 'ready', mk: 'board'},
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
  const k = this.cur.post, el = $('#post');
  el.innerHTML = SUB('post', [['hand', 'التسليم والعيوب'], ['title', 'نقل الملكية'], ['fm', 'إدارة المرافق'], ['oa', 'اتحاد الملاك'], ['lease', 'التأجير']], k) + '<div id="postB">…</div>';
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
  el.innerHTML = SUB('adm', [['users', 'المستخدمون'], ['sec', 'أماني'], ['brand', 'هوية المستندات والختم'], ['ops', 'السجل والنسخ والتكامل'], ['notif', 'الإشعارات'], ['priv', 'طلبات الخصوصية']].filter(([x]) => x === 'sec' || can('admin') || (x === 'notif' && can('notify'))), k) + '<div id="admB">…</div>';
  const B = $('#admB');
  if (k === 'users' && can('users')) {
    const U = await api('/users');
    B.innerHTML = BOX('المستخدمون والأدوار', T(['المستخدم', 'الاسم', 'البريد', 'الدور', 'الحالة', 'تحقق ثنائي', 'تغيير كلمة المرور', ''], U.map(u => `<tr><td><span class="num">${esc(u.username)}</span></td><td>${esc(u.name)}</td><td><span class="num">${esc(u.email || '—')}</span>${u.google_linked ? ' <span class="pill p-ok">Google</span>' : ''} <button class="link" data-call="EXT.uemail" data-args="${J([u.id, u.email || ''])}">تعديل</button></td><td>${esc(u.role)}</td><td>${u.active ? pill('مفعّل', 'p-ok') : pill('معطّل', 'p-b')}</td><td>${u.totp_enabled ? '✓' : '—'}</td><td>${u.must_change ? pill('مطلوب', 'p-w') : fmtDate(u.pw_changed)}</td><td><button class="btn" data-call="EXT.ureset" data-args="${J([u.id])}">إعادة تعيين</button> <button class="btn" data-call="EXT.uact" data-args="${J([u.id, u.active ? 0 : 1])}">${u.active ? 'تعطيل' : 'تفعيل'}</button> <button class="btn" data-call="EXT.ukill" data-args="${J([u.id])}">إنهاء الجلسات</button>${u.totp_enabled ? ` <button class="btn" data-call="EXT.u2fa" data-args="${J([u.id])}">إعادة ضبط التحقق</button>` : ''}</td></tr>`)),
      '<button class="btn" data-call="EXT.newUser">+ مستخدم</button>');
  } else if (k === 'brand' && can('admin')) {
    const b = await api('/admin/brand');
    const f = (id, l, v, ph = '') => `<label>${l}</label><input id="${id}" value="${esc(v || '')}" placeholder="${ph}">`;
    const img = (d) => d ? `<img src="/api/documents/${d}" alt="" style="height:56px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:4px">` : '<span class="muted">لم تُرفع</span>';
    B.innerHTML = BOX('ترويسة المستندات الصادرة (عروض الأسعار، العقود، الفواتير، الإيصالات)', `<div style="padding:14px"><div class="grid2">${f('brn', 'اسم المطوّر كما يظهر في المستندات', b.name)}${f('brcr', 'رقم السجل التجاري', b.cr)}${f('brvat', 'الرقم الضريبي', b.vat)}${f('brad', 'العنوان', b.address)}${f('brph', 'الهاتف', b.phone)}${f('brem', 'البريد', b.email)}${f('brsg', 'اسم المفوَّض بالتوقيع', b.signatory)}${f('brst', 'صفته', b.signatory_title)}</div>
      <div class="btns" style="margin-top:12px"><button class="btn p" id="brsave">حفظ</button></div></div>`)
      + BOX('الشعار والختم والتوقيع المعتمد <span class="muted">صور PNG/JPEG بخلفية بيضاء أو شفافة؛ تُطبع في كل مستند</span>', `<div style="padding:14px" class="grid3">${['logo', 'stamp', 'sign'].map(k => `<div><b>${{logo: 'الشعار', stamp: 'الختم', sign: 'التوقيع'}[k]}</b><div style="margin:8px 0">${img(b[k + '_doc'])}</div><input type="file" id="br_${k}" accept=".png,.jpg,.jpeg"><button class="btn" data-call="EXT.brandUpload" data-args="${J([k])}">رفع</button></div>`).join('')}</div>`);
    $('#brsave').onclick = async () => { await tryDo(() => api('/admin/brand', {method: 'POST', body: {name: $('#brn').value, cr: $('#brcr').value, vat: $('#brvat').value, address: $('#brad').value, phone: $('#brph').value, email: $('#brem').value, signatory: $('#brsg').value, signatory_title: $('#brst').value}}), 'حُفظت الترويسة'); };
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
