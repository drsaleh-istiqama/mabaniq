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
const AR = s => esc(s).replace(/\d/g, d => '٠١٢٣٤٥٦٧٨٩'[d]).replace(/(?<=[٠-٩]),(?=[٠-٩])/g, '٬');
const ND = (v, d = 2) => new Intl.NumberFormat('ar-OM', {maximumFractionDigits: d}).format(+v || 0).replace(/,/g, '٬');
const tryDo = async (fn, ok) => { try { const r = await fn(); if (ok) toast(typeof ok === 'function' ? ok(r) : ok); return r; } catch (e) { toast(e.message, 1); throw e; } };
const projOpts = (cur) => S.projects.map(p => `<option value="${p.id}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('');

const EXT = {
  cur: {pre: 'land', post: 'hand', sal: 'kyc', bill: 'inv', adm: 'users'},
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
  <div class="muted">حساسية الهامش (السعر × التكلفة)</div>${T(['السعر \\ التكلفة', '−١٠٪', 'كما هي', '+١٠٪'], s.sensitivity.map(r => `<tr><td>${r.price_change > 0 ? '+' : ''}${N(r.price_change * 100)}٪</td>${r.margins.map(m => `<td>${pill(pct(m), m >= 20 ? 'p-ok' : m >= 12 ? 'p-w' : 'p-b')}</td>`).join('')}</tr>`))}
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
  el.innerHTML = SUB('sal', [['kyc', 'التحقق والعقود'], ['brk', 'الوسطاء والعمولات'], ['mkt', 'السوق الثانوي'], ['disc', 'الخصومات'], ['wa', 'وكيل واتساب']], k) + '<div id="salB">…</div>';
  const B = $('#salB');
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
      insp('وسيط', `<h3>${esc(b.name)}</h3><dl class="kv"><dt>الترخيص</dt><dd>${esc(b.license_no)}</dd><dt>الهاتف</dt><dd><span class="num">${esc(b.phone)}</span></dd></dl><div class="ai">تُصرف العمولة بعد تحصيل ٢٠٪ من ثمن الوحدة، وتُسترد تلقائيًا إذا فُسخ العقد. تسجيل العميل محمي برقم الهاتف لمنع تنازع العمولات.</div>
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
    B.innerHTML = BOX('طلبات الخصم <span class="muted">المبيعات حتى ٢٪ · المالية حتى ٥٪ · ما زاد يعتمده المدير</span>', T(['الوحدة', 'النسبة', 'السبب', 'طلبه', 'الحالة', ''],
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
   <div class="btns" style="margin-top:12px"><button class="btn p" id="sgo3">توقيع حضوري</button></div>`}<div class="btns" style="margin-top:8px"><button class="btn" data-call="closeModal">إغلاق</button></div>`);
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
    B.innerHTML = KP([['عدد الفواتير', N(I.summary.n)], ['الصافي', K(I.summary.net) + ' ر.ع'], ['ضريبة القيمة المضافة', K(I.summary.vat) + ' ر.ع'], ['النسبة القياسية', '٥٪', 'قابلة للضبط']]) + `<div class="ai">${esc(I.note)}</div>`
      + BOX('الفواتير الصادرة', T(['الرقم', 'النوع', 'العميل', 'الصافي', 'الضريبة', 'الإجمالي', 'التاريخ', 'البيان'], I.invoices.map(v => `<tr><td><span class="num">${esc(v.number)}</span></td><td>${esc({installment: 'قسط', service_charge: 'رسوم خدمات', rent: 'إيجار', resale_fee: 'رسوم تنازل'}[v.kind] || v.kind)}</td><td>${esc(v.customer)}</td><td>${OMR(v.net)}</td><td>${OMR(v.vat)}</td><td>${OMR(v.total)}</td><td>${fmtDate(v.issued)}</td><td>${esc(v.note)}</td></tr>`), 'تصدر الفواتير تلقائيًا مع كل سداد.'));
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
      H.map((h, i) => { const o = h.snags.filter(s => s.status === 'open').length; return `<tr data-i="${i}"><td>${esc(h.customer)}</td><td><span class="num">${esc(h.unit)}</span></td><td>${fmtDate(h.appointment)}</td><td>${pct(h.paid_ratio)}</td><td>${o ? pill(N(o), 'p-b') : pill('٠', 'p-ok')}</td><td>${h.status === 'done' ? pill('سُلّمت', 'p-ok') : (() => { const r = []; if (h.paid_ratio < 100) r.push('متبقٍ ' + pct(100 - h.paid_ratio)); if (o) r.push(N(o) + ' ملاحظات'); return r.length ? pill('موقوف · ' + r.join(' · '), 'p-b') : pill('جاهز للتسليم', 'p-ok'); })()}</td></tr>`; })));
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
EXT.l_rep = async function () {
  const [L, I] = await Promise.all([api('/reports/lender'), api('/reports/investor')]);
  const col = r => r === 'أخضر' ? 'p-ok' : r === 'أصفر' ? 'p-w' : 'p-b';
  $('#rep').innerHTML = BOX(`تقرير الممول (البنك) <span class="muted">كما في ${fmtDate(L.as_of)}</span>`, T(['المشروع', 'الإنجاز', 'المبيعات', 'التحصيل', 'التغطية', 'عجز متوقع', 'فرق الإنجاز', 'التقييم'],
      L.projects.map(p => `<tr title="${esc(p.flags.join(' · '))}"><td>${esc(p.project)}</td><td>${pct(p.build_pct)}</td><td>${pct(p.sold_pct)}</td><td>${pct(p.collection_rate)}</td><td>${ND(p.coverage)}×</td><td>${p.cash_gap ? OMR(p.cash_gap) : '—'}</td><td>${p.claimed_vs_verified ? N(p.claimed_vs_verified) + ' نقاط' : '—'}</td><td>${pill(p.rating, col(p.rating))}</td></tr>`)))
    + `<div class="ai">${L.projects.filter(p => p.flags.length).map(p => `<b class="k">${esc(p.project)}:</b> ${p.flags.map(AR).join(' · ')}`).join('<br>') || 'لا ملاحظات.'}<br><span class="muted">${esc(L.method)}</span></div>`
    + BOX('تقرير المستثمرين', T(['المشروع', 'القيمة الإجمالية للمبيعات', 'المباع', 'التكلفة التقديرية', 'الربح التقديري', 'الهامش', 'التوزيعات'],
      I.projects.map(p => `<tr><td>${esc(p.project)}</td><td>${OMR(p.gdv)}</td><td>${OMR(p.sold_value)}</td><td>${OMR(p.est_cost)}</td><td>${OMR(p.est_profit)}</td><td>${pct(p.margin)}</td><td>${OMR(p.distributions)}</td></tr>`))) + `<div class="muted">${esc(I.note)}</div>`;
};

/* ================================================================ الإدارة والأمان */
EXT.l_adm = async function () {
  const k = this.cur.adm, el = $('#adm');
  el.innerHTML = SUB('adm', [['users', 'المستخدمون'], ['sec', 'أماني'], ['ops', 'السجل والنسخ والتكامل'], ['notif', 'الإشعارات'], ['priv', 'طلبات الخصوصية']].filter(([x]) => x === 'sec' || can('admin') || (x === 'notif' && can('notify'))), k) + '<div id="admB">…</div>';
  const B = $('#admB');
  if (k === 'users' && can('users')) {
    const U = await api('/users');
    B.innerHTML = BOX('المستخدمون والأدوار', T(['المستخدم', 'الاسم', 'الدور', 'الحالة', 'تحقق ثنائي', 'تغيير كلمة المرور', ''], U.map(u => `<tr><td><span class="num">${esc(u.username)}</span></td><td>${esc(u.name)}</td><td>${esc(u.role)}</td><td>${u.active ? pill('مفعّل', 'p-ok') : pill('معطّل', 'p-b')}</td><td>${u.totp_enabled ? '✓' : '—'}</td><td>${u.must_change ? pill('مطلوب', 'p-w') : fmtDate(u.pw_changed)}</td><td><button class="btn" data-call="EXT.ureset" data-args="${J([u.id])}">إعادة تعيين</button> <button class="btn" data-call="EXT.uact" data-args="${J([u.id, u.active ? 0 : 1])}">${u.active ? 'تعطيل' : 'تفعيل'}</button> <button class="btn" data-call="EXT.ukill" data-args="${J([u.id])}">إنهاء الجلسات</button>${u.totp_enabled ? ` <button class="btn" data-call="EXT.u2fa" data-args="${J([u.id])}">إعادة ضبط التحقق</button>` : ''}</td></tr>`)),
      '<button class="btn" data-call="EXT.newUser">+ مستخدم</button>');
  } else if (k === 'ops' && can('admin')) {
    const v = await api('/audit/verify');
    B.innerHTML = KP([['سلامة سجل التدقيق', v.ok ? '✓ سليم' : '⚠ مكسور', N(v.entries) + ' قيدًا · بصمة ' + (v.head || '')], ['السجل', 'إلحاق فقط', 'لا تعديل ولا حذف'], ['النسخ الاحتياطي', 'آخر ١٤ نسخة', 'مشفّر في الإنتاج'], ['واجهة التكامل', '/api/v1', 'مفاتيح قراءة فقط']])
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
    const SS = await api('/me/sessions');
    const ago = t => t ? fmtDate(new Date(t * 1000).toISOString()) : '—';
    B.innerHTML = BOX('أمان حسابي', `<div style="padding:14px"><p>التحقق الثنائي: <b>${S.me.totp_enabled ? 'مفعّل ✓' : 'غير مفعّل'}</b></p><div class="btns">${S.me.totp_enabled ? '' : '<button class="btn p" id="t2">تفعيل التحقق الثنائي</button>'}<button class="btn" id="cpw">تغيير كلمة المرور</button><button class="btn" id="sall">تسجيل الخروج من كل الأجهزة الأخرى</button></div><div id="t2r"></div></div>`)
      + BOX(`جلساتي <span class="muted">تنتهي الجلسة بعد ${N(SS.idle_minutes)} دقيقة بلا نشاط أو ${N(SS.absolute_hours)} ساعة كحد أقصى</span>`, T(['الجهاز', 'العنوان', 'بدأت', 'آخر نشاط', ''], SS.sessions.map(s => `<tr><td>${esc(s.label)}${s.current ? ' ' + pill('هذه الجلسة', 'p-ok') : ''}</td><td><span class="num">${esc(s.ip)}</span></td><td>${ago(s.created)}</td><td>${ago(s.last_seen)}</td><td>${s.current ? '' : `<button class="btn" data-call="EXT.skill" data-args="${J([s.id])}">إنهاء</button>`}</td></tr>`)));
    if ($('#t2')) $('#t2').onclick = () => EXT.setup2fa();
    $('#cpw').onclick = () => EXT.changePw(false);
    $('#sall').onclick = async () => { const r = await tryDo(() => api('/me/sessions/revoke', {method: 'POST', body: {others: true}})); toast(`أُنهيت ${N(r.revoked)} جلسة`); EXT.l_adm(); };
  }
};
EXT.ureset = async id => { if (!confirm('إعادة تعيين كلمة المرور وإنهاء جلسات المستخدم؟')) return; const r = await tryDo(() => api(`/users/${id}/reset`, {method: 'POST'})); modal(`<h3>كلمة مرور مؤقتة</h3><p>للمستخدم <b>${esc(r.username)}</b>:</p><div class="ai"><span class="num" style="user-select:all">${esc(r.temporary_password)}</span></div><p class="muted">تُعرض مرة واحدة، ويُلزم بتغييرها عند الدخول.</p><button class="btn" data-call="closeModal">إغلاق</button>`); };
EXT.skill = async id => { await tryDo(() => api('/me/sessions/revoke', {method: 'POST', body: {id}}), 'أُنهيت الجلسة'); EXT.l_adm(); };
EXT.ukill = async id => { if (!confirm('إنهاء كل جلسات هذا المستخدم فورًا (جهاز مفقود / مغادرة)؟')) return; const r = await tryDo(() => api(`/users/${id}/sessions/revoke`, {method: 'POST'})); toast(`أُنهيت ${N(r.revoked)} جلسة`); };
EXT.u2fa = async id => { if (!confirm('إعادة ضبط التحقق الثنائي لهذا المستخدم؟ تُبطل رموزه وتُنهى جلساته، ويعيد التفعيل عند الدخول.')) return; await tryDo(() => api(`/users/${id}/2fa/reset`, {method: 'POST'}), 'أُعيد ضبط التحقق الثنائي'); EXT.l_adm(); };
EXT.uact = async (id, a) => { await tryDo(() => api(`/users/${id}/active`, {method: 'POST', body: {active: !!a}}), 'حُدّث المستخدم'); EXT.l_adm(); };
EXT.newUser = () => { modal(`<h3>مستخدم جديد</h3><label>اسم المستخدم (إنجليزي)</label><input id="un" dir="ltr"><label>الاسم</label><input id="unm"><label>الدور</label><select id="ur"><option value="sales">مبيعات</option><option value="finance">مالية</option><option value="engineer">مهندس</option><option value="investor">مستثمر/ممول</option><option value="admin">مدير</option></select><div class="err" id="ue"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="ugo">إنشاء</button><button class="btn" data-call="closeModal">إلغاء</button></div>`);
  $('#ugo').onclick = async () => { try { const r = await api('/users', {method: 'POST', body: {username: $('#un').value.trim().toLowerCase(), name: $('#unm').value, role: $('#ur').value}}); modal(`<h3>أُنشئ المستخدم</h3><div class="ai"><b>${esc(r.username)}</b><br>كلمة المرور المؤقتة: <span class="num" style="user-select:all">${esc(r.temporary_password)}</span></div><p class="muted">${esc(r.note)}</p><button class="btn" data-call="closeModal">إغلاق</button>`); EXT.l_adm(); } catch (e) { $('#ue').textContent = e.message; } }; };
EXT.setup2fa = async () => {
  const r = await tryDo(() => api('/auth/2fa/setup', {method: 'POST'}));
  modal(`<h3>تفعيل التحقق الثنائي</h3><p>أضف الحساب في تطبيق المصادقة (Google Authenticator أو Microsoft Authenticator) بالمفتاح التالي:</p><div class="ai"><span class="num" style="user-select:all;word-break:break-all">${esc(r.secret)}</span></div><label>أدخل الرمز المكوّن من ٦ أرقام</label><input id="otp" inputmode="numeric" dir="ltr" maxlength="6"><div class="err" id="oe"></div><div class="btns" style="margin-top:12px"><button class="btn p" id="ogo2">تفعيل</button><button class="btn" data-call="closeModal">لاحقًا</button></div>`);
  $('#ogo2').onclick = async () => { try { const en = await api('/auth/2fa/enable', {method: 'POST', body: {otp: $('#otp').value.trim()}}); S.me = await api('/me');
      modal(`<h3>✓ فُعّل التحقق الثنائي — احفظ رموز الاسترداد</h3><p class="muted">${esc(en.note)} تُعرض مرة واحدة فقط.</p><div class="ai"><div class="num" style="user-select:all;line-height:2;direction:ltr;text-align:left">${en.recovery_codes.map(esc).join('<br>')}</div></div><button class="btn p" id="rcok">حفظتها</button>`);
      $('#rcok').onclick = () => { closeModal(); if (S.screen === 'adm') EXT.l_adm(); else location.reload(); }; } catch (e) { $('#oe').textContent = e.message; } };
};
EXT.changePw = forced => {
  modal(`<h3>${forced ? 'غيّر كلمة المرور المؤقتة للمتابعة' : 'تغيير كلمة المرور'}</h3>${forced ? '<p class="muted">هذا أول دخول لك. اختر كلمة مرور خاصة (١٠ أحرف على الأقل تجمع حروفًا وأرقامًا).</p>' : ''}
   <label>كلمة المرور الحالية</label><input id="pc" type="password" autocomplete="current-password" dir="ltr"><label>كلمة المرور الجديدة</label><input id="pn" type="password" autocomplete="new-password" dir="ltr"><label>تأكيدها</label><input id="pn2" type="password" autocomplete="new-password" dir="ltr"><div class="err" id="pe2"></div>
   <div class="btns" style="margin-top:12px"><button class="btn p" id="pgo2">حفظ</button>${forced ? '' : '<button class="btn" data-call="closeModal">إلغاء</button>'}</div>`);
  $('#pgo2').onclick = async () => { if ($('#pn').value !== $('#pn2').value) return $('#pe2').textContent = 'التأكيد لا يطابق'; try { await api('/auth/password', {method: 'POST', body: {current: $('#pc').value, new: $('#pn').value}}); toast('✓ تغيّرت كلمة المرور'); closeModal(); if (forced) location.reload(); } catch (e) { $('#pe2').textContent = e.message; } };
};

/* توجيه كل قسم إلى أول تبويب فرعي مسموح للدور الحالي */
['pre', 'sal', 'bill', 'post'].forEach(id => { const f = EXT['l_' + id]; EXT['l_' + id] = function () {
  const order = Object.keys(SUBP).filter(x => x.startsWith(id + '.')).map(x => x.split('.')[1]);
  if (!subOk(id, this.cur[id])) this.cur[id] = order.find(k => subOk(id, k)) || this.cur[id];
  return f.call(this); }; });

window.EXT = EXT;
