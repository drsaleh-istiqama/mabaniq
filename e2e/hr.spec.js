// 0.25.0 — human resources in the browser: HR creates an employee and a document with an expiry alert, gives two employees a login; the employee asks for leave in the
// portal, his manager approves it from «فريقي», and the days show as taken. Same throw-away server as the other specs.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const NEW_PW = 'Hr-E2e-Portal-2026';
const iso = d => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);

const call = (page, method, path, body) => page.evaluate(async ([m, p, b]) => {
  const csrf = (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
  const r = await fetch('/api' + p, {method: m, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: b ? JSON.stringify(b) : undefined});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(m + ' ' + p + ' ' + r.status + ' ' + JSON.stringify(j));
  return j;
}, [method, path, body]);

async function signIn(browser, user, pw) {
  const ctx = await browser.newContext(), page = await ctx.newPage();
  await page.goto('/login');
  await page.fill('#u', user); await page.fill('#p', pw); await page.click('#b');
  return {ctx, page};
}

test.describe.serial('الموارد البشرية', () => {
  let admin, boss, worker;
  test.beforeAll(async ({browser}) => {
    admin = await browser.newPage();
    await admin.goto('/login');
    await admin.fill('#u', 'admin'); await admin.fill('#p', PASSWORD); await admin.click('#b');
    await expect(admin.locator('#whoName')).not.toHaveText('…');
    await admin.click('[data-s="hr"]');
  });
  test.afterAll(async () => { await admin.close(); });

  test('HR creates an employee and a passport that is about to expire shows on the overview', async () => {
    await admin.locator('.subt button', {hasText: 'الموظفون'}).click();
    await admin.click('[data-call="EXT.hrEmpForm"]');
    await admin.fill('#fn', 'ماجد بن علي الشكيلي');
    await admin.fill('#fid', '90817263');
    await admin.fill('#fh', '2024-02-01');
    await admin.fill('#fib', 'OM810180000001299123456');
    await admin.click('#fGo');
    await expect(admin.locator('#hrB')).toContainText('ماجد بن علي الشكيلي');
    await expect(admin.locator('#hrB')).toContainText('EMP-');
    await admin.locator('#hrB tbody tr', {hasText: 'ماجد بن علي الشكيلي'}).click();
    await expect(admin.locator('#ib')).toContainText('90817263');   // HR opens the identity number; every opening is audited
    await admin.click('#ib [data-call="EXT.hrDocForm"]');
    await admin.selectOption('#hdk', 'passport');
    await admin.fill('#hdno', 'P9988776');
    await admin.fill('#hde', iso(20));
    await admin.click('#hdGo2');
    await expect(admin.locator('#ib')).toContainText('خلال 30 يومًا');
    await admin.click('#ix');
    await admin.locator('.subt button', {hasText: 'نظرة عامة'}).click();
    await expect(admin.locator('#hrB')).toContainText('جواز السفر');
    await expect(admin.locator('#hrB')).toContainText('قيم الإجازات مبدئية');
  });

  test('a leave request goes from the employee to his manager and the days are taken from the balance', async ({browser}) => {
    const hire = '2024-01-15';
    const b = await call(admin, 'POST', '/hr/employees', {name: 'المدير المباشر للاختبار', omani: true, hire_date: hire, gender: 'male', email: 'boss.e2e@example.test'});
    const w = await call(admin, 'POST', '/hr/employees', {name: 'الموظف طالب الإجازة', omani: true, hire_date: hire, gender: 'male', manager_id: b.id, email: 'worker.e2e@example.test'});
    const ab = await call(admin, 'POST', `/hr/employees/${b.id}/account`), aw = await call(admin, 'POST', `/hr/employees/${w.id}/account`);

    const sign = async (acct) => {
      const s = await signIn(browser, acct.username, acct.temporary_password);
      await s.page.fill('#pc', acct.temporary_password); await s.page.fill('#pn', NEW_PW); await s.page.fill('#pn2', NEW_PW);
      const [done] = await Promise.all([s.page.waitForResponse(r => r.url().endsWith('/api/auth/password')), s.page.click('#pgo2')]);  // wait for the change itself, not for an idle page
      expect(done.ok()).toBeTruthy();
      await s.page.goto('/');
      await expect(s.page.locator('#whoName')).not.toHaveText('…');
      return s;
    };
    worker = await sign(aw);
    await expect(worker.page.locator('#meB')).toContainText('أرصدة إجازاتي');
    await expect(worker.page.locator('[data-s="hr"]')).toBeHidden();   // the employee has no HR screen, only his portal
    await worker.page.locator('.subt button', {hasText: 'إجازاتي'}).click();
    await worker.page.selectOption('#ltk', 'bereavement');
    await worker.page.fill('#ltf', iso(10)); await worker.page.fill('#ltu', iso(11));
    await worker.page.click('#ltGo');
    await expect(worker.page.locator('#toast')).toContainText('أُرسل الطلب');
    await expect(worker.page.locator('#meB')).toContainText('عند المدير');

    boss = await sign(ab);
    await boss.page.locator('.subt button', {hasText: 'فريقي'}).click();
    await expect(boss.page.locator('#meB')).toContainText('الموظف طالب الإجازة');
    await boss.page.locator('#meB [data-call="EXT.hrDecide"]', {hasText: 'اعتماد'}).click();
    await expect(boss.page.locator('#toast')).toContainText('اعتُمدت الإجازة');

    await worker.page.locator('.subt button', {hasText: 'إجازاتي'}).click();
    await expect(worker.page.locator('#meB')).toContainText('معتمدة');
    await worker.ctx.close(); await boss.ctx.close();
  });
});
