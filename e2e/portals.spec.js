// 0.28.0 — the portals in the browser: the office opens a login for a tenant, the tenant signs in to a screen that is theirs alone (lease, receipt link, statement, a maintenance
// request they file), the employee's new attendance and loans tabs open, the manager's tabs open, and the dashboard carries the books and people tiles. Same throw-away server.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const NEW_PW = 'Portal-E2e-Tenant-2026';
const iso = d => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);

const call = (page, method, path, body) => page.evaluate(async ([m, p, b]) => {
  const csrf = (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
  const r = await fetch('/api' + p, {method: m, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: b ? JSON.stringify(b) : undefined});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(m + ' ' + p + ' ' + r.status + ' ' + JSON.stringify(j));
  return j;
}, [method, path, body]);

async function signIn(browser, username, temp) {
  const ctx = await browser.newContext(), page = await ctx.newPage();
  await page.goto('/login');
  await page.fill('#u', username); await page.fill('#p', temp); await page.click('#b');
  await page.fill('#pc', temp); await page.fill('#pn', NEW_PW); await page.fill('#pn2', NEW_PW);
  const [done] = await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/auth/password')), page.click('#pgo2')]);
  expect(done.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.locator('#whoName')).not.toHaveText('…');
  return {ctx, page};
}

test.describe.serial('البوابات', () => {
  let admin;
  test.beforeAll(async ({browser}) => {
    admin = await browser.newPage();
    await admin.goto('/login');
    await admin.fill('#u', 'admin'); await admin.fill('#p', PASSWORD); await admin.click('#b');
    await expect(admin.locator('#whoName')).not.toHaveText('…');
  });
  test.afterAll(async () => { await admin.close(); });

  test('the dashboard shows the people and books tiles and the new reports are listed', async () => {
    await expect(admin.locator('#kpis')).toContainText('على رأس العمل');
    await admin.click('[data-s="rep"]');
    await expect(admin.locator('#rep')).toContainText('ميزان المراجعة');
    await expect(admin.locator('#rep')).toContainText('القوى العاملة');
  });

  test('the office opens a login for a tenant who then sees only their own lease and files a maintenance request', async ({browser}) => {
    const units = (await call(admin, 'GET', '/lea/units')).units;
    const vacant = units.find(u => u.state === 'vacant');
    expect(vacant).toBeTruthy();
    const lease = await call(admin, 'POST', '/lea/leases', {unit_id: vacant.id, tenant: {name: 'مستأجرة البوابة للمواصفة', phone: '+968 91110000', id_number: 'PORTALE2E'}, start: iso(-30), months: 12, annual_rent: 2400, frequency: 4, sign: true});
    await call(admin, 'POST', '/lea/payments', {lease_id: lease.id, amount: 100, method: 'cash'});
    const tid = (await call(admin, 'GET', '/lea/leases/' + lease.id)).tenant_id;

    await admin.click('[data-s="lea"]');
    await admin.locator('.subt button', {hasText: 'المستأجرون'}).click();
    await admin.locator('#leaB tbody tr', {hasText: 'مستأجرة البوابة للمواصفة'}).click();
    admin.once('dialog', d => d.accept());
    await admin.locator('#ib [data-call="EXT.leaAccount"]').click();
    const modal = admin.locator('#mbox');
    await expect(modal).toContainText('كلمة المرور المؤقتة');
    const username = (await modal.locator('b.num').nth(0).innerText()).trim();
    const temp = (await modal.locator('b.num').nth(1).innerText()).trim();
    expect(username).toBe('ten' + String(tid).padStart(4, '0'));
    await admin.click('[data-call="closeModal"]');

    const t = await signIn(browser, username, temp);
    const p = t.page;
    await expect(p.locator('#lp')).toContainText('مستأجرة البوابة للمواصفة');
    await expect(p.locator('#lp')).toContainText('إشعار الخصوصية');
    await p.locator('[data-call="EXT.lpConsent"]').click();
    await expect(p.locator('#lp')).not.toContainText('إشعار الخصوصية');
    for (const s of ['hr', 'acc', 'lea', 'inv', 'fin']) await expect(p.locator(`[data-s="${s}"]`)).toBeHidden();
    await p.locator('#lpB tbody tr').first().click();
    await expect(p.locator('#ib')).toContainText('الإيصالات');
    await expect(p.locator('#ib a[href*="/api/lessee/docs/rent_receipt/"]')).toHaveCount(1);
    await expect(p.locator('#ib a[href*="/api/lessee/docs/lease/"]')).toHaveCount(1);
    await p.click('#ix');
    await p.locator('.subt button', {hasText: 'كشف حسابي'}).click();
    await expect(p.locator('#lpB')).toContainText('الرصيد');
    await p.locator('.subt button', {hasText: 'الصيانة'}).click();
    await p.click('#lpB [data-call="EXT.lpMaintForm"]');
    await p.fill('#lmD', 'تسرّب مياه من سقف غرفة الاجتماعات');
    await p.click('#lmGo');
    await expect(p.locator('#toast')).toContainText('أُرسل الطلب');
    await expect(p.locator('#lpB')).toContainText('تسرّب مياه');
    // the office receives it like any request
    await admin.click('#ix');
    await admin.locator('.subt button', {hasText: 'الصيانة والمصاريف'}).click();
    await expect(admin.locator('#leaB')).toContainText('تسرّب مياه من سقف');
    await t.ctx.close();
  });

  test('the employee portal opens its attendance and loans tabs', async ({browser}) => {
    const e = await call(admin, 'POST', '/hr/employees', {name: 'موظفة البوابة للمواصفة', omani: true, hire_date: '2023-03-01', gender: 'female', email: 'portal.emp.e2e@example.test'});
    const acct = await call(admin, 'POST', `/hr/employees/${e.id}/account`);
    const w = await signIn(browser, acct.username, acct.temporary_password);
    await w.page.locator('.subt button', {hasText: 'حضوري'}).click();
    await expect(w.page.locator('#meB')).toContainText('حضوري');
    await w.page.locator('.subt button', {hasText: 'سلفي'}).click();
    await expect(w.page.locator('#meB')).toContainText('لا سلف ولا قروض');
    await expect(w.page.locator('#meB')).toContainText('قرض حسن');
    await w.ctx.close();
  });
});
