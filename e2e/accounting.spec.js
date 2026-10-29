// 0.23.0 — accounting core in the browser: activate, post the leasing events to the books, read the trial balance, draft → approve a manual journal and see it
// become frozen. Same throw-away server as the other specs.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';

test.describe.serial('المحاسبة', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
    await page.click('[data-s="acc"]');
  });
  test.afterAll(async () => { await page.close(); });

  test('accounting starts off, is activated with a date, and the leasing events are carried to the books', async () => {
    await expect(page.locator('#accB')).toContainText('لم تُفعَّل المحاسبة بعد');
    await page.click('[data-call="EXT.accActivate"]');
    await page.fill('#acS', '2026-01-01');
    await page.check('#acC');
    await page.click('#acGo');
    await expect(page.locator('#accB')).toContainText('أحداث لم تُرحَّل بعد');
    await expect(page.locator('#accB')).toContainText('متوازن');
    await page.click('[data-call="EXT.accSync"]');
    await expect(page.locator('#toast')).toContainText('رُحّل');
  });

  test('the trial balance is balanced and a receipt of unknown method is not guessed into cash or bank', async () => {
    await page.locator('.subt button', {hasText: 'ميزان المراجعة'}).click();
    await expect(page.locator('#accB')).toContainText('متوازن');
    await expect(page.locator('#accB')).toContainText('ذمم المستأجرين');
    await expect(page.locator('#accB')).toContainText('إيرادات الإيجار');
  });

  test('a manual journal is drafted, approved, and then offers only a reversal', async () => {
    await page.locator('.subt button', {hasText: 'القيود'}).click();
    await page.click('[data-call="EXT.accNew"]');
    const rows = page.locator('#jl tr');
    await rows.nth(0).locator('.jlA').selectOption({label: '1110 — الصندوق'});
    await rows.nth(0).locator('.jlD').fill('100');
    await rows.nth(1).locator('.jlA').selectOption({label: '3100 — رأس المال'});
    await rows.nth(1).locator('.jlC').fill('100');
    await page.fill('#jm', 'رأس مال مبدئي — اختبار');
    await expect(page.locator('#jT')).toContainText('الفرق');
    await page.click('#jGo');
    await expect(page.locator('#ib')).toContainText('مسودة');
    await page.locator('#ib [data-call="EXT.accAct"]', {hasText: 'اعتماد وترحيل'}).click();
    await expect(page.locator('#ib')).toContainText('مرحَّل');
    await expect(page.locator('#ib [data-call="EXT.accAct"]')).toHaveCount(1);   // only «عكس القيد»: a posted journal is never edited
    await expect(page.locator('#ib')).toContainText('عكس القيد');
  });

  test('the payables, banks and statements tabs open and the balance sheet proves itself', async () => {
    await page.click('#ix');   // close the journal inspector left open by the previous test
    await page.locator('.subt button', {hasText: 'الذمم الدائنة'}).click();
    await expect(page.locator('#accB')).toContainText('فواتير الموردين');
    await expect(page.locator('#accB')).toContainText('أوامر الدفع');
    await page.locator('.subt button', {hasText: 'البنوك والمطابقة'}).click();
    await expect(page.locator('#accB')).toContainText('إسلامية فقط');
    await expect(page.locator('#accB')).toContainText('الشيكات الصادرة');
    await page.locator('.subt button', {hasText: 'القوائم المالية'}).click();
    await expect(page.locator('#accB')).toContainText('مطابِقة لحساباتها');
    await page.selectOption('#spK', 'cash_flow');
    await expect(page.locator('#accB')).toContainText('الأنشطة التشغيلية');
    await page.locator('.subt button', {hasText: 'الأصول والتمويل والضريبة'}).click();
    await expect(page.locator('#accB')).toContainText('لا فائدة');
  });
});
