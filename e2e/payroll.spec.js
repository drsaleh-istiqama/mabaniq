// 0.26.0 — payroll in the browser: an unset insurance rate is shown as missing, a run is computed by one payroll officer and can only be approved by another,
// and the employee then finds his payslip in the portal. Same throw-away server as the other specs. The rates typed below are TEST values.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const NEW_PW = 'Pay-E2e-Portal-2026';
const prevMonth = () => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 7); };

const call = (page, method, path, body) => page.evaluate(async ([m, p, b]) => {
  const csrf = (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
  const r = await fetch('/api' + p, {method: m, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: b ? JSON.stringify(b) : undefined});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(m + ' ' + p + ' ' + r.status + ' ' + JSON.stringify(j));
  return j;
}, [method, path, body]);

async function signIn(browser, acct) {
  const ctx = await browser.newContext(), page = await ctx.newPage();
  await page.goto('/login');
  await page.fill('#u', acct.username); await page.fill('#p', acct.temporary_password); await page.click('#b');
  await page.fill('#pc', acct.temporary_password); await page.fill('#pn', NEW_PW); await page.fill('#pn2', NEW_PW);
  const [done] = await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/auth/password')), page.click('#pgo2')]);
  expect(done.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.locator('#whoName')).not.toHaveText('…');
  return {ctx, page};
}

test.describe.serial('الرواتب', () => {
  let admin;
  test.beforeAll(async ({browser}) => {
    admin = await browser.newPage();
    await admin.goto('/login');
    await admin.fill('#u', 'admin'); await admin.fill('#p', PASSWORD); await admin.click('#b');
    await expect(admin.locator('#whoName')).not.toHaveText('…');
    await admin.click('[data-s="pay"]');
  });
  test.afterAll(async () => { await admin.close(); });

  test('the insurance rates start unset, and the administrator enters them with a source', async () => {
    await admin.locator('.subt button', {hasText: 'المعدلات'}).click();
    await expect(admin.locator('#payB')).toContainText('معدلات لم تُدخَل بعد');
    await admin.click('[data-call="EXT.payRateForm"]');
    await admin.selectOption('#prK', 'pasi_ceiling');
    await admin.fill('#prV', '3000'); await admin.fill('#prD', '2000-01-01'); await admin.fill('#prN', 'قيمة اختبار للمواصفة');
    await admin.click('#prGo');
    await expect(admin.locator('#toast')).toContainText('حُفظ المعدل');
    for (const [k, v] of [['pasi_employee_pct', 7], ['pasi_employer_pct', 10.5]]) await call(admin, 'POST', '/hr/payroll/rates', {key: k, value: v, valid_from: '2000-01-01', note: 'قيمة اختبار للمواصفة'});
  });

  test('a run computed by the administrator is approved by a second payroll officer and the employee sees the payslip', async ({browser}) => {
    const e = await call(admin, 'POST', '/hr/employees', {name: 'موظف المسيّر', omani: true, hire_date: '2024-01-01', gender: 'male', iban: 'OM810180000001299123456', bank_name: 'بنك إسلامي', social_ins_no: 'SI-9', email: 'pay.e2e@example.test'});
    const housing = (await call(admin, 'GET', '/hr/payroll/components')).find(c => c.key === 'housing').id;
    await call(admin, 'POST', '/hr/payroll/structures', {employee_id: e.id, effective_from: '2024-01-01', basic: 500, lines: [{component_id: housing, amount: 100}]});

    await admin.locator('.subt button', {hasText: 'المسيّرات'}).click();
    await admin.fill('#prp', prevMonth());
    await admin.click('[data-call="EXT.payRunNew"]');
    await admin.click('[data-call="EXT.payRunDo"]');   // compute
    await expect(admin.locator('#payB')).toContainText('موظف المسيّر');
    await expect(admin.locator('#payB')).toContainText('565.000');
    await expect(admin.locator('#payB [data-call="EXT.payRunDo"][data-args*="approve"]')).toBeDisabled();   // not the computer of the run

    const p2 = await call(admin, 'POST', '/users', {username: 'e2e-pay2', name: 'مسؤول رواتب ثانٍ', role: 'payroll'});
    const acc = await call(admin, 'POST', `/hr/employees/${e.id}/account`);
    const second = await signIn(browser, {username: 'e2e-pay2', temporary_password: p2.temporary_password});
    await expect(second.page.locator('#payB')).toContainText('أُحتسب بواسطة');   // a payroll officer lands on the payroll screen
    await second.page.locator('#payB tbody tr', {hasText: prevMonth()}).click();
    second.page.on('dialog', d => d.accept());   // 0.28.1: the other people in the shared test database have no salary structure — the approver must acknowledge it
    await second.page.click('[data-call="EXT.payRunDo"][data-args*="approve"]');
    await expect(second.page.locator('#toast')).toContainText('اعتُمد');
    await expect(second.page.locator('#payB')).toContainText('معتمد');
    await second.ctx.close();

    const emp = await signIn(browser, acc);
    await emp.page.locator('.subt button', {hasText: 'قسائمي'}).click();
    await expect(emp.page.locator('#meB')).toContainText(prevMonth());
    await expect(emp.page.locator('#meB')).toContainText('565.000');
    await expect(emp.page.locator('#meB a[href*="/payslips/"]')).toBeVisible();
    await emp.ctx.close();
  });
});
