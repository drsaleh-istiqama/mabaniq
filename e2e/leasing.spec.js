// 0.21.0 — integrated leasing: the screen opens, a lease is previewed, signed and collected on, and the receipt is offered as a PDF.
// Runs against the same throw-away server as the other specs; the demo organisation has the leasing module and a portfolio of vacant units.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';

test.describe.serial('الإيجارات المتكاملة', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
  });
  test.afterAll(async () => { await page.close(); });

  test('the leasing screen shows the portfolio overview and ageing', async () => {
    await page.click('[data-s="lea"]');
    await expect(page.locator('#leaB .kp')).toBeVisible();
    await expect(page.locator('#leaB')).toContainText('تعمير المتأخرات');
    await expect(page.locator('#leaB')).toContainText('الإشغال');
  });

  test('a lease is previewed, signed, collected on partially, and the receipt PDF is offered', async () => {
    await page.locator('.subt button', {hasText: 'العقود'}).click();
    await page.click('[data-call="EXT.leaNew"]');
    const unit = await page.locator('#nu option', {hasText: 'شاغرة'}).first().getAttribute('value');
    await page.selectOption('#nu', unit);
    await page.fill('#tn_name', 'شركة المسار للتجارة');
    await page.fill('#tn_phone', '+968 91112222');
    await page.fill('#ns', '2035-01-01'); await page.fill('#nm', '24'); await page.fill('#nr', '2400'); await page.fill('#ne', '10');
    await page.selectOption('#nf', '4'); await page.fill('#np', '30');
    await page.click('#npre');
    await expect(page.locator('#npv tbody tr')).toHaveCount(8);          // two years, four payments a year
    await expect(page.locator('#npv')).toContainText('الإجمالي');
    await page.click('#nsg');
    await expect(page.locator('#ih')).toContainText('LS-2035-');          // numbered, signed, schedule generated
    await expect(page.locator('#ib')).toContainText('جدول الدفعات');
    await page.locator('#ib [data-call="EXT.leaPay"]').first().click();
    await page.fill('#pa', '100'); await page.selectOption('#pm', 'cash'); await page.click('#pgo');
    await expect(page.locator('#mbox')).toContainText('سُجّل التحصيل');
    const href = await page.locator('#mbox a[href*="rent_receipt"]').getAttribute('href');
    const r = await page.request.get(href);
    expect(r.status()).toBe(200);
    expect((await r.body()).subarray(0, 4).toString()).toBe('%PDF');
  });

  test('the payments ledger lists the receipt and a cheque can be received', async () => {
    await page.click('[data-call="closeModal"]');
    await page.click('#ix');   // the details panel covers the page on a narrow window
    await page.locator('.subt button', {hasText: 'التحصيل'}).click();
    await expect(page.locator('#leaB')).toContainText('RC-');
    await page.locator('.subt button', {hasText: 'العقود'}).click();
    await page.locator('#leaB tr[data-id]').filter({hasText: 'شركة المسار'}).first().click();
    await page.locator('#ib [data-call="EXT.leaCheque"]').click();
    await page.fill('#qn', '880011'); await page.fill('#qb', 'بنك مسقط'); await page.fill('#qa', '300'); await page.fill('#qd', '2035-02-01');
    await page.click('#qgo');
    await expect(page.locator('#mbox')).toContainText('CQ-');
  });
});
