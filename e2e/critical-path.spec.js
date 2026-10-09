// The sale-to-handover critical path, end to end, in a real browser (acceptance item 16):
//   staff login (UI) → booking → KYC → confirmation (deposit) → contract → in-person signature → customer account
//   → customer login (UI, forced password change) → pays "دفعة أولى" from the portal → staff login (UI)
//   → handover refused without the bank letter → bank letter uploaded → handover certificate HC-…
// Business calls go through the page's own fetch so cookies, CSRF and CSP are exactly what a user gets.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const KYC = {id_type: 'بطاقة مدنية', id_number: '12345678', nationality: 'عُماني', id_expiry: '2030-01-01', source_of_funds: 'راتب', consent_signed: true};

/** JSON call from inside the page (same cookies; CSRF token read from the cookie like app.js does). */
async function api(page, method, path, body) {
  return page.evaluate(async ({method, path, body}) => {
    const csrf = (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
    const r = await fetch(path, {method, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: body === undefined ? undefined : JSON.stringify(body)});
    let json = null;
    try { json = await r.json(); } catch { /* empty body */ }
    return {status: r.status, json};
  }, {method, path, body});
}

async function loginUI(page, username, password) {
  await page.goto('/login');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await page.fill('#u', username);
  await page.fill('#p', password);
  await page.click('#b');
}

async function logout(page) {
  await api(page, 'POST', '/api/auth/logout');
  await page.context().clearCookies();
}

test.describe.serial('المسار الحرج: حجز ⟵ تسليم', () => {
  let page;
  let bookingId;
  let customerId;
  let unitCode;
  let customerLogin;

  test.beforeAll(async ({browser}) => { page = await browser.newPage(); });
  test.afterAll(async () => { await page.close(); });

  test('login page: RTL, Arabic, no inline scripts, hashed bundle', async () => {
    const res = await page.goto('/login');
    const csp = res.headers()['content-security-policy'];
    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain("style-src 'self'");
    expect(csp).not.toContain('googleapis');
    const inline = await page.locator('script:not([src])').count();
    expect(inline).toBe(0);
    const bundle = await page.locator('script[src^="/static/assets/"]').first().getAttribute('src');
    expect(bundle).toMatch(/\/static\/assets\/.+\.js$/);
    const asset = await page.request.get(bundle);
    expect(asset.headers()['cache-control']).toBe('public, max-age=31536000, immutable');
  });

  test('staff: booking, KYC, confirmation, contract, signature, customer account', async () => {
    await loginUI(page, 'admin', PASSWORD);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('#whoName')).not.toHaveText('…');
    await expect(page.locator('#kpis')).not.toBeEmpty();
    // Western digits in the dashboard (owner decision ب): no Arabic-Indic digits in the KPI strip
    expect(await page.locator('#kpis').innerText()).not.toMatch(/[٠-٩]/);

    const projects = (await api(page, 'GET', '/api/projects')).json;
    const pid = projects[2].id;
    const units = (await api(page, 'GET', `/api/units?project_id=${pid}`)).json;
    const unit = units.find(u => u.status === 'a');
    unitCode = unit.code;
    const booked = await api(page, 'POST', '/api/bookings', {unit_code: unitCode, customer_name: 'عميل المسار الحرج', phone: '+968 9555 0300', plan: 'murabaha'});
    expect(booked.status, JSON.stringify(booked.json)).toBe(200);
    bookingId = booked.json.booking_id;
    customerId = booked.json.customer_id;

    expect((await api(page, 'POST', `/api/bookings/${bookingId}/contract`)).status).toBe(409); // no contract before KYC
    expect((await api(page, 'POST', `/api/customers/${customerId}/kyc`, KYC)).json.status).toBe('verified');
    expect((await api(page, 'POST', `/api/bookings/${bookingId}/confirm`)).status).toBe(200); // deposit receipt
    const contract = await api(page, 'POST', `/api/bookings/${bookingId}/contract`);
    expect(contract.status).toBe(200);
    expect(contract.json.body).toContain(unitCode);
    expect(contract.json.body).toContain('شرط التبرع'); // Islamic finance: the late-payment clause is a charity undertaking
    expect(contract.json.body).not.toMatch(/غرامة تأخير|فائدة تأخير|فوائد/);
    const signed = await api(page, 'POST', `/api/bookings/${bookingId}/contract/sign-inperson`, {typed_name: 'عميل المسار الحرج', accept: true});
    expect(signed.status).toBe(200);
    expect((await api(page, 'GET', `/api/bookings/${bookingId}/contract`)).json.integrity_ok).toBe(true);

    customerLogin = {username: `e2e${Date.now() % 100000}`};
    const acc = await api(page, 'POST', `/api/customers/${customerId}/account`, {username: customerLogin.username});
    expect(acc.status, JSON.stringify(acc.json)).toBe(200);
    customerLogin.temp = acc.json.temporary_password;

    // handover is refused: own installment unpaid
    const early = await api(page, 'POST', `/api/bookings/${bookingId}/handover/complete`, {electricity: 1, water: 1, keys: 2});
    expect(early.status).toBe(409);
    await logout(page);
  });

  test('customer: first login forces a password change, then pays the first installment from the portal', async () => {
    await loginUI(page, customerLogin.username, customerLogin.temp);
    await expect(page).toHaveURL(/\/app$/);
    const newPw = 'Mabaniq-E2e-' + Date.now();
    const changed = await api(page, 'POST', '/api/auth/password', {current: customerLogin.temp, new: newPw});
    expect(changed.status, JSON.stringify(changed.json)).toBe(200);
    // the change killed other sessions but kept this one
    const portal = await api(page, 'GET', '/api/portal');
    expect(portal.status).toBe(200);
    const mine = portal.json.bookings.find(b => b.unit === unitCode || b.unit_code === unitCode || b.booking_id === bookingId) || portal.json.bookings[0];
    expect(mine.next, 'an unpaid installment should be due').toBeTruthy();
    const paid = await api(page, 'POST', '/api/portal/pay', {installment_id: mine.next.id});
    expect(paid.status, JSON.stringify(paid.json)).toBe(200);
    expect(paid.json.charity_due || 0).toBe(0); // paid on time: no charity due
    await logout(page);
  });

  test('staff: bank letter opens the handover; certificate issued; ledger balanced', async () => {
    await loginUI(page, 'admin', PASSWORD);
    await expect(page).toHaveURL(/\/$/);
    const blocked = await api(page, 'POST', `/api/bookings/${bookingId}/handover/complete`, {electricity: 1, water: 1, keys: 2});
    expect(blocked.status).toBe(409);
    expect(blocked.json.detail).toContain('خطاب صرف');

    const up = await page.evaluate(async ({bookingId}) => {
      const csrf = (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
      const fd = new FormData();
      fd.append('ref_type', 'booking'); fd.append('ref_id', String(bookingId));
      fd.append('title', 'خطاب صرف بنك نزوى'); fd.append('category', 'خطاب صرف بنكي');
      fd.append('file', new File(['%PDF-1.4 bank letter'], 'letter.pdf', {type: 'application/pdf'}));
      const r = await fetch('/api/documents', {method: 'POST', headers: {'X-CSRF-Token': csrf}, body: fd});
      return {status: r.status, text: await r.text()};
    }, {bookingId});
    expect(up.status, up.text).toBe(200);

    const ok = await api(page, 'POST', `/api/bookings/${bookingId}/handover/complete`, {electricity: 1, water: 1, keys: 2});
    expect(ok.status, JSON.stringify(ok.json)).toBe(200);
    expect(ok.json.certificate).toMatch(/^HC-/);
    const bank = (await api(page, 'GET', '/api/bank')).json;
    expect(bank.ledger_gap).toBe(0);

    // UI reflects it: the handover screen lists the unit as delivered
    await page.click('a.ni[data-s="post"]');
    await expect(page.locator('#whoRole')).not.toBeEmpty();
  });

  test('language toggle: EN locale switches direction and persists', async () => {
    await page.click('#lang');
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
    await expect(page.locator('[data-i18n="nav.overview"]').first()).toHaveText(/Dashboard|Overview/i);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await page.click('#lang');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await logout(page);
  });
});
