/**
 * k6 load test — acceptance criterion 15: p95 of /api/decisions and /api/cash under 500 ms with 300 concurrent users.
 *
 * Each VU uses one of four demo staff sessions created in setup() (round-robin; the server keeps 5 sessions per user) and then behaves like a back-office user: dashboard (decisions + cash + projects),
 * inventory of one project, KYC queue, handover board, with 1–3 s of think time. Judged on the steady phase only.
 *
 * Environment: BASE_URL (http://127.0.0.1:8800), PASSWORD (MABANIQ_DEMO_PASSWORD of the target), VUS (300), RAMP (1m),
 * STEADY (3m), RAMP_DOWN (30s), THINK (1.0), OUT_DIR (./results).
 * The target must run with relaxed per-IP limits (all VUs share one address): MABANIQ_RATE_LOGIN=1000/60 MABANIQ_RATE_API=100000/60.
 */
import http from 'k6/http';
import {check, sleep} from 'k6';
import exec from 'k6/execution';
import {Trend} from 'k6/metrics';

const BASE = (__ENV.BASE_URL || 'http://127.0.0.1:8800').replace(/\/$/, '');
const PASSWORD = __ENV.PASSWORD || '';
const VUS = Number(__ENV.VUS || 300);
const THINK = Number(__ENV.THINK || 1);
const RAMP = __ENV.RAMP || '1m';
const STEADY = __ENV.STEADY || '3m';
const RAMP_DOWN = __ENV.RAMP_DOWN || '30s';
const OUT_DIR = (__ENV.OUT_DIR || './results').replace(/\\/g, '/');
const dur = s => { const m = /^(\d+(?:\.\d+)?)(ms|s|m|h)$/.exec(String(s)); return Number(m[1]) * {ms: 0.001, s: 1, m: 60, h: 3600}[m[2]]; };
const RAMP_S = dur(RAMP);
const STEADY_S = dur(STEADY);
const ACCOUNTS = ['admin', 'sales', 'finance', 'engineer'];  // investor1 has no `view` permission (own report endpoints only)
// what each role may open (server-side authz is real: a 403 here would be a test error, not a finding)
const ALLOWED = {admin: ['units', 'kyc', 'handover'], sales: ['units', 'kyc'], finance: [], engineer: []};
const ENDPOINTS = ['decisions', 'cash', 'projects', 'units', 'kyc', 'handover'];
const BUDGET = {decisions: 500, cash: 500};

const thresholds = {checks: ['rate>0.99']};
for (const e of ENDPOINTS) {
  thresholds[`http_req_duration{endpoint:${e},phase:steady}`] = [BUDGET[e] ? `p(95)<${BUDGET[e]}` : 'p(95)<60000'];
  thresholds[`http_req_failed{endpoint:${e},phase:steady}`] = ['rate<0.01'];
}
export const options = {
  scenarios: {office: {executor: 'ramping-vus', startVUs: 0, stages: [{duration: RAMP, target: VUS}, {duration: STEADY, target: VUS}, {duration: RAMP_DOWN, target: 0}], gracefulRampDown: '10s'}},
  thresholds,
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};
const steadyTrend = new Trend('steady_dashboard_ms', true);

export function setup() {
  if (!PASSWORD) throw new Error('PASSWORD (demo password of the target) is required');
  const sessions = [];
  for (const u of ACCOUNTS) {
    const r = http.post(`${BASE}/api/auth/login`, JSON.stringify({username: u, password: PASSWORD, tenant: 'jadwa'}), {headers: {'Content-Type': 'application/json'}});
    if (r.status !== 200) throw new Error(`login ${u} → ${r.status} ${r.body}`);
    const jar = http.cookieJar().cookiesForURL(BASE + '/');
    sessions.push({user: u, session: jar.mbq_session[0], csrf: jar.mbq_csrf[0], tenant: (jar.mbq_tenant || ['jadwa'])[0]});
    http.cookieJar().clear(BASE + '/');
  }
  const projects = JSON.parse(http.get(`${BASE}/api/projects`, {cookies: {mbq_session: sessions[0].session, mbq_tenant: sessions[0].tenant}}).body);
  return {sessions, projectIds: projects.map(p => p.id)};
}

function phase() {
  const t = (Date.now() - exec.scenario.startTime) / 1000;
  return t < RAMP_S ? 'ramp' : t < RAMP_S + STEADY_S ? 'steady' : 'down';
}

function get(path, endpoint, s) {
  const ph = phase();
  const r = http.get(`${BASE}${path}`, {cookies: {mbq_session: s.session, mbq_tenant: s.tenant}, tags: {endpoint, phase: ph}});
  check(r, {[`${endpoint} 200`]: x => x.status === 200});
  if (r.status !== 200 && __ITER < 1) console.warn(`non-200 ${endpoint}: ${r.status} ${String(r.body).slice(0, 160)} ${r.error || ''}`);
  if (ph === 'steady' && (endpoint === 'decisions' || endpoint === 'cash')) steadyTrend.add(r.timings.duration, {endpoint});
  return r;
}

export default function (data) {
  const s = data.sessions[(exec.vu.idInTest - 1) % data.sessions.length];
  get('/api/decisions', 'decisions', s);
  get('/api/cash', 'cash', s);
  get('/api/projects', 'projects', s);
  sleep((1 + Math.random() * 2) * THINK);
  const allowed = ALLOWED[s.user] || [];
  if (allowed.includes('units')) { const pid = data.projectIds[Math.floor(Math.random() * data.projectIds.length)]; get(`/api/units?project_id=${pid}`, 'units', s); }
  sleep((0.5 + Math.random()) * THINK);
  if (allowed.includes('kyc')) get('/api/kyc', 'kyc', s);
  if (allowed.includes('handover')) get('/api/handover', 'handover', s);
  sleep((1 + Math.random() * 2) * THINK);
}

export function handleSummary(data) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const pick = name => { const m = data.metrics[name]; return m ? m.values : null; };
  const out = {at: stamp, base: BASE, vus: VUS, ramp: RAMP, steady: STEADY, thresholds_ok: !Object.values(data.metrics).some(m => m.thresholds && Object.values(m.thresholds).some(t => !t.ok)),
    steady: Object.fromEntries(ENDPOINTS.map(e => [e, pick(`http_req_duration{endpoint:${e},phase:steady}`)])),
    all: pick('http_req_duration'), requests: pick('http_reqs'), failed: pick('http_req_failed')};
  return {[`${OUT_DIR}/k6-${stamp}.json`]: JSON.stringify(out, null, 1), stdout: textSummary(data)};
}

function textSummary(data) {
  const lines = [`k6 — ${VUS} VUs, ramp ${RAMP}, steady ${STEADY} → ${BASE}`];
  for (const e of ENDPOINTS) {
    const v = data.metrics[`http_req_duration{endpoint:${e},phase:steady}`]?.values;
    if (v) lines.push(`${e.padEnd(10)} steady p95 ${v['p(95)'].toFixed(0).padStart(6)} ms  p99 ${v['p(99)'].toFixed(0).padStart(6)} ms  med ${v.med.toFixed(0).padStart(5)} ms${BUDGET[e] ? `  (budget ${BUDGET[e]})` : ''}`);
  }
  const f = data.metrics.http_req_failed?.values; const n = data.metrics.http_reqs?.values;
  lines.push(`requests ${n ? n.count : 0}  failed ${(f ? f.rate * 100 : 0).toFixed(2)}%`);
  return lines.join('\n') + '\n';
}
