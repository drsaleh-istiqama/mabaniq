// 0.27.0 — the rest of the employee's life in the browser: an opening and a candidate, the bylaw that must exist (and be approved by someone else) before any penalty,
// and a full appraisal: the employee's self-review, the manager's review, HR's decision and the employee's acknowledgement. Same throw-away server as the other specs.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const NEW_PW = 'Life-E2e-Portal-2026';
const iso = d => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);

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

test.describe.serial('دورة الموظف', () => {
  let admin;
  test.beforeAll(async ({browser}) => {
    admin = await browser.newPage();
    await admin.goto('/login');
    await admin.fill('#u', 'admin'); await admin.fill('#p', PASSWORD); await admin.click('#b');
    await expect(admin.locator('#whoName')).not.toHaveText('…');
    await admin.click('[data-s="hr"]');
  });
  test.afterAll(async () => { await admin.close(); });

  test('an opening is drafted, opened and given a candidate; the discipline screen insists on an approved bylaw', async () => {
    await admin.locator('.subt button', {hasText: 'التوظيف'}).click();
    await admin.click('[data-call="EXT.recOpenForm"]');
    await admin.fill('#roT', 'مسؤول مشتريات للمواصفة'); await admin.fill('#roH', '1');
    await admin.click('#roGo');
    const row = admin.locator('#hrB tbody tr', {hasText: 'مسؤول مشتريات للمواصفة'});
    await expect(row).toContainText('مسودة');
    await row.locator('[data-call="EXT.recOpenSet"]', {hasText: 'فتح'}).click();
    await expect(row).toContainText('مفتوحة');
    await row.locator('[data-call="EXT.recCandForm"]').click();
    await admin.fill('#rcN', 'مرشحة المواصفة'); await admin.fill('#rcE', 'cand.e2e@example.test');
    await admin.click('#rcGo');
    await expect(admin.locator('#hrB')).toContainText('مرشحة المواصفة');
    await admin.locator('#hrB tbody tr', {hasText: 'مرشحة المواصفة'}).click();
    await expect(admin.locator('#ib')).toContainText('cand.e2e@example.test');
    await admin.click('#ix');

    await admin.locator('.subt button', {hasText: 'الجزاءات'}).click();
    await expect(admin.locator('#hrB')).toContainText('لا لائحة معتمدة');
    await admin.click('[data-call="EXT.dscRuleForm"]');
    await admin.fill('#drC', 'م-7'); await admin.fill('#drN', 'التأخر المتكرر'); await admin.fill('#drS', 'اللائحة المعتمدة — المادة 7');
    await admin.click('#drGo');
    const rule = admin.locator('#hrB tbody tr', {hasText: 'م-7'});
    await expect(rule).toContainText('مسودة');
    await expect(rule.locator('[data-call="EXT.dscRuleApprove"]')).toBeDisabled();   // the person who wrote it cannot approve it
  });

  test('an appraisal goes from the employee to the manager to HR and back to the employee', async ({browser}) => {
    const boss = await call(admin, 'POST', '/hr/employees', {name: 'مدير التقييم للمواصفة', omani: true, hire_date: '2023-01-01', gender: 'male', email: 'apr.boss@example.test'});
    const wk = await call(admin, 'POST', '/hr/employees', {name: 'موظف التقييم للمواصفة', omani: true, hire_date: '2023-02-01', gender: 'male', manager_id: boss.id, email: 'apr.wk@example.test'});
    const ab = await call(admin, 'POST', `/hr/employees/${boss.id}/account`), aw = await call(admin, 'POST', `/hr/employees/${wk.id}/account`);
    const y = new Date().getFullYear();
    await call(admin, 'POST', '/hr/appraisal-cycles', {name: `تقييم المواصفة ${y}`, year: y, start_date: `${y}-01-01`, end_date: iso(0)});
    await admin.locator('.subt button', {hasText: 'التقييم'}).click();
    await admin.locator('#hrB tbody tr', {hasText: `تقييم المواصفة ${y}`}).locator('[data-call="EXT.aprCycleDo"]', {hasText: 'فتح'}).click();
    await expect(admin.locator('#toast')).toContainText('أُضيف');

    const worker = await signIn(browser, aw);
    await worker.page.locator('.subt button', {hasText: 'تقييمي'}).click();
    const f = worker.page.locator('[id^="sf"]').first();
    await f.locator('.sgT').first().fill('تسليم المهام في موعدها');
    await f.locator('.sgW').first().fill('100');
    await f.locator('.sgS').first().fill('4');
    for (const i of [0, 1, 2, 3, 4]) await f.locator('.scS').nth(i).fill('4');
    await worker.page.locator('[id^="ss"]').first().click();
    await expect(worker.page.locator('#toast')).toContainText('أُرسل إلى مديرك');
    await worker.page.locator('.subt button', {hasText: 'تقييمي'}).click();
    await expect(worker.page.locator('#meB')).toContainText('عند المدير');
    await expect(worker.page.locator('#meB')).not.toContainText('المدير:');   // none of the manager's opinion yet

    const mgr = await signIn(browser, ab);
    await mgr.page.locator('.subt button', {hasText: 'فريقي'}).click();
    await mgr.page.locator('[data-call="EXT.aprReviewForm"]').click();
    await mgr.page.locator('.rvG').first().fill('5');
    for (const i of [0, 1, 2, 3, 4]) await mgr.page.locator('.rvC').nth(i).fill('4');
    await mgr.page.fill('#rvM', 'أداء قوي ومنتظم هذا العام');
    await mgr.page.click('#rvGo');
    await expect(mgr.page.locator('#toast')).toContainText('أُرسلت المراجعة');
    await mgr.ctx.close();

    await admin.locator('.subt button', {hasText: 'التقييم'}).click();
    await admin.locator('#hrB tbody tr', {hasText: 'موظف التقييم للمواصفة'}).click();
    await expect(admin.locator('#ib')).toContainText('أداء قوي ومنتظم');
    await admin.click('#ib [data-call="EXT.aprFinalForm"]');
    await admin.selectOption('#afD', 'raise'); await admin.fill('#afC', 'يُدرس في الميزانية القادمة');
    await admin.click('#afGo');
    await expect(admin.locator('#toast')).toContainText('اعتُمد التقييم');

    await worker.page.locator('.subt button', {hasText: 'تقييمي'}).click();
    await expect(worker.page.locator('#meB')).toContainText('أداء قوي ومنتظم');   // visible only now that HR has finalised
    await expect(worker.page.locator('#meB')).toContainText('4.7');   // 0.7 × 5 + 0.3 × 4
    await worker.ctx.close();
  });
});
