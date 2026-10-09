/* مبانيك — منطق الواجهة. كل البيانات تأتي من الـ API الحي. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const nf = new Intl.NumberFormat('ar-OM'), N = v => nf.format(Math.round(v || 0)).replace(/,/g, '٬');
const OMR = v => N(v) + '\u00a0ر.ع';
const K = v => Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('ar-OM', {maximumFractionDigits: 2}).replace(/[.,](?=[٠-٩\d])/g, '٫') + ' مليون' : Math.abs(v) >= 1e3 ? N(v / 1e3) + ' ألف' : N(v);
const AD = '٠١٢٣٤٥٦٧٨٩';
const ad = t => String(t ?? '').replace(/(^|[^A-Za-z\-\d])(\d[\d,.]*)/g, (m, p, n) => p + n.replace(/\d/g, x => AD[x]).replace(/,/g, '٬').replace(/\.(?=[٠-٩])/g, '٫'));
const tx = t => ad(esc(t));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
/* 0.5.0 — M7: تفويض الأحداث بدل onclick المضمّن (CSP بلا unsafe-inline) */
const J = v => esc(JSON.stringify(v));
const CALLS = {};
document.addEventListener('click', e => {
  const el = e.target.closest('[data-call]');
  if (!el) return;
  const [ns, fn] = el.dataset.call.includes('.') ? el.dataset.call.split('.') : [null, el.dataset.call];
  const f = ns ? (window[ns] || CALLS[ns] || {})[fn] : (CALLS[fn] || window[fn]);
  if (typeof f !== 'function') { console.warn('no handler', el.dataset.call); return; }
  e.preventDefault();
  f(...(el.dataset.args ? JSON.parse(el.dataset.args) : []));
});
const csrf = () => (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';

const fmtMonth = m => new Date(m + '-01').toLocaleDateString('ar-OM', {month: 'long', year: 'numeric'});
const fmtDate = d => d ? new Date(d).toLocaleDateString('ar-OM', {day: 'numeric', month: 'short', year: 'numeric'}) : '—';
const STAGES = ['جديد', 'مؤهَّل', 'معاينة', 'تفاوض', 'حجز'];
const ST = {a: 'متاحة', r: 'محجوزة', s: 'مباعة'};
const PLANS = {milestone: ['مربوطة بمراحل الإنشاء', '١٠٪ حجز ثم ١٥٪ عند كل مرحلة مُتحقق منها'],
  '6040': ['٦٠/٤٠', '٦٠٪ أثناء البناء و٤٠٪ عند التسليم'], murabaha: ['مرابحة عبر بنك شريك', '٢٠٪ مقدمًا والباقي تمويل متوافق مع الشريعة']};

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
const SCREEN_PERM = {ov: 'view', inv: 'inventory', crm: 'leads', fin: 'finance', con: 'construction', svc: 'service', log: 'audit', pre: 'permits', sal: 'kyc', bill: 'invoices', post: 'handover', rep: 'reports', adm: 'view'};
const SCREEN_ANY = {pre: ['permits', 'land'], post: ['handover', 'oa', 'leasing', 'service'], sal: ['kyc', 'brokers', 'market']};
const can = p => S.me?.perms.includes(p);
const canS = s => (SCREEN_ANY[s] || [SCREEN_PERM[s]]).some(can);
function go(s) {
  if (!canS(s)) s = canS('ov') ? 'ov' : 'rep';
  S.screen = s;
  $$('[data-s]').forEach(b => b.classList.toggle('on', b.dataset.s === s));
  $$('.scr').forEach(x => x.classList.toggle('on', x.id === s));
  localStorage.setItem('mbq-screen', s);
  ({ov: loadOverview, inv: loadInventory, crm: loadCRM, fin: loadFinance, con: () => { loadIPC(); EXT.l_conx(); }, svc: loadService, log: loadAudit,
    pre: () => EXT.l_pre(), sal: () => EXT.l_sal(), bill: () => EXT.l_bill(), post: () => EXT.l_post(), rep: () => EXT.l_rep(), adm: () => EXT.l_adm()})[s]?.()?.catch?.(e => toast(e.message, 1));
  crumb(); shell(s);
}
$$('[data-s]').forEach(b => b.onclick = e => { e.preventDefault(); document.body.classList.remove('nav-open'); go(b.dataset.s); });
const META = {
  ov: ['', 'لوحة القيادة', 'ما يحتاج قرارك اليوم، وصحة كل مشروع، وموقع المحفظة في دورة التطوير.'],
  pre: ['١ · الأرض والتراخيص', 'الأراضي والجدوى والتراخيص', 'تقييم الأراضي بدراسة جدوى، ومتابعة التراخيص لدى الجهات الحكومية حتى إصدارها.'],
  inv: ['٢ · البيع والإنشاء', 'المخزون والتسعير', 'مخطط الوحدات وحالتها، وأداء الشرائح وتوصيات تعديل الأسعار.'],
  crm: ['٢ · البيع والإنشاء', 'العملاء المحتملون', 'قمع المبيعات، والعملاء المحتملون مرتّبين بدرجة احتمال الشراء.'],
  sal: ['٢ · البيع والإنشاء', 'العقود والوسطاء', 'التحقق من هوية المشترين، وإصدار العقود وتوقيعها، والوسطاء والخصومات والسوق الثانوي.'],
  con: ['٢ · البيع والإنشاء', 'الإنشاء والمستخلصات', 'التحقق من نسب الإنجاز قبل الصرف، والجدول الزمني، وأوامر التغيير وتقارير الموقع.'],
  fin: ['عبر الدورة · المالية', 'السيولة والتعثر', 'أرصدة حسابات الضمان المتوقعة لاثني عشر شهرًا، والعملاء المعرّضون للتعثر.'],
  bill: ['عبر الدورة · المالية', 'الفواتير والضمان', 'الفواتير والضريبة، والغرامات والفسخ، والمطابقة البنكية وحساب الضمان والتصدير المحاسبي.'],
  post: ['٣ · التسليم والتشغيل', 'التسليم والأملاك', 'التسليم وملاحظات الفحص، ونقل الملكية، والمرافق واتحاد الملاك والتأجير.'],
  svc: ['٣ · التسليم والتشغيل', 'خدمة العملاء', 'طلبات الصيانة وإعادة البيع الواردة من تطبيق العميل.'],
  rep: ['الحوكمة', 'تقارير الممولين', 'تقرير البنك الممول بتقييم المخاطر، وتقرير المستثمرين بالربحية والتوزيعات.'],
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
  $('#phG').textContent = m[0]; $('#phT').textContent = m[1]; $('#phD').textContent = m[2];
  const st = STEP[s];
  $('#lc').innerHTML = st == null ? '' : CYCLE.map(([k, l], i) => `<li class="${i === st ? 'on' : i < st ? 'done' : ''}"><button data-go="${k}" ${canS(k) ? '' : 'disabled'}><span>${'١٢٣'[i]}</span>${l}</button></li>`).join('');
  $$('#lc [data-go]').forEach(b => b.onclick = () => go(b.dataset.go));
  document.title = m[1] + ' · مبانيك';
}
function stageOf(p) { return p.completed || p.build_pct >= 80 ? 2 : p.build_pct >= 10 ? 1 : 0; }
function renderCycle(P) {
  const cols = [['١ · الأرض والتراخيص', 'دراسة جدوى وترخيص وإطلاق'], ['٢ · البيع والإنشاء', 'بيع على الخارطة وتحصيل مربوط بالإنجاز'], ['٣ · التسليم والتشغيل', 'تسليم ونقل ملكية واتحاد ملاك وتأجير']];
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
    <div><small>مبيعات آخر ٣٠ يومًا</small><b>${K(k.sales_30d_value)} ر.ع</b><small>${N(k.sales_30d_count)} وحدة</small></div>
    <div><small>نسبة التحصيل (٩٠ يومًا)</small><b>${N(k.collection_rate)}٪</b><small>من الأقساط المستحقة</small></div>
    <div><small>فجوة السيولة المتوقعة</small><b style="color:${cash.gap ? 'var(--bad)' : 'var(--ok)'}">${cash.gap ? K(cash.gap) + ' ر.ع' : 'لا توجد'}</b><small>${cash.gap ? esc(cash.worst_project) + ' · ' + fmtMonth(cash.worst.month) : 'خلال ١٢ شهرًا'}</small></div>
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
  $('#segs').innerHTML = segs.map(s => `<tr><td>${esc(s.type)} · ${esc(s.view)}</td><td>${N(s.total)}</td><td>${N(s.available)}</td><td>${N(s.recent_sales)}</td><td><bdi>${s.demand_ratio.toLocaleString('ar-OM', {maximumFractionDigits: 1, minimumFractionDigits: 1})} ضعف</bdi></td>
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
  if (u.status === 'a' && can('book')) h += `<button class="btn p w" data-call="openBooking" data-args="${J([u.code])}">حجز الوحدة لعميل</button>`;
  if (u.booking) {
    const b = u.booking;
    h += `<dl class="kv"><dt>العميل</dt><dd>${esc(b.cname)}</dd><dt>الهاتف</dt><dd><span class="num">${esc(b.phone)}</span></dd><dt>خطة الدفع</dt><dd>${PLANS[b.plan][0]}</dd><dt>المسدَّد</dt><dd>${OMR(b.paid)} من ${OMR(b.total)}</dd>${b.status === 'pending' ? `<dt>مهلة الحجز</dt><dd>حتى ${fmtDate(b.expires)}</dd>` : ''}</dl>`;
    if (b.status === 'pending') h += `<div class="btns" style="margin-bottom:12px">${can('confirm') ? `<button class="btn p" data-call="confirmBooking" data-args="${J([b.id, u.code])}">تسجيل سداد العربون وتأكيد البيع</button>` : '<span class="muted">تأكيد البيع من صلاحية المالية.</span>'}${can('book') ? `<button class="btn" data-call="cancelBooking" data-args="${J([b.id, u.code])}">إلغاء الحجز</button>` : ''}</div>`;
    h += `<b>جدول الأقساط</b>` + b.installments.map(i => {
      const st = i.paid_amount >= i.amount - 1 ? pill('مدفوع', 'p-ok') : i.paid_amount > 0 ? pill('جزئي', 'p-w') : new Date(i.due_date) < new Date() ? pill('متأخر', 'p-b') : pill('قادم', '');
      return `<div class="inst"><span>${esc(i.label)}<br><span class="muted">${fmtDate(i.due_date)}</span></span><span>${OMR(i.amount)} ${st}</span></div>`;
    }).join('');
  }
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
  modal(`<h3>حجز الوحدة <span class="num">${esc(BK.code)}</span></h3><div class="muted">السعر ${OMR(BK.price)} · مهلة الحجز المبدئي ٧٢ ساعة</div>
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
  const next = l.score >= 75 ? 'أرسل عرض خطة دفع مربوطة بالإنجاز مع مهلة ٤٨ ساعة' : l.stage < 2 ? 'ادعه لمعاينة الوحدات المطابقة هذا الأسبوع' : 'تابِعه باتصال وأرسل مقارنة الوحدات المطابقة';
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
  $('#cashNote').innerHTML = !wp ? '<b class="k">✦</b> لا توجد فجوة سيولة متوقعة في أي حساب ضمان خلال ١٢ شهرًا.'
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
  const K2 = v => v === 0 ? '٠ ر.ع' : (v < 0 ? '−' : '') + K(Math.abs(v));
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
  $('#audit').innerHTML = a.map(x => `<tr><td>${new Date(x.at).toLocaleString('ar-OM', {dateStyle: 'medium', timeStyle: 'short'})}</td><td>${esc(x.actor)}</td><td>${esc(x.action)}</td><td>${esc(x.detail)}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">لا توجد إجراءات بعد.</td></tr>';
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
