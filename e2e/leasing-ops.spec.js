// 0.22.0 — leasing operations in the browser: the new tabs open, a lease is renewed from its window, a maintenance request is raised, an owner statement is previewed,
// and the import tab offers a dry-run. Same throw-away server as the other specs.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';

test.describe.serial('عمليات الإيجار', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
    await page.click('[data-s="lea"]');
  });
  test.afterAll(async () => { await page.close(); });

  test('the arrears, maintenance, owners and import tabs open', async () => {
    await page.locator('.subt button', {hasText: 'المتأخرات والتبرع'}).click();
    await expect(page.locator('#leaB')).toContainText('الإنذارات الصادرة');
    await expect(page.locator('#leaB')).toContainText('خطط السداد');
    await expect(page.locator('#leaB')).toContainText('ليست إيرادًا');
    await page.locator('.subt button', {hasText: 'الصيانة والمصاريف'}).click();
    await expect(page.locator('#leaB')).toContainText('طلبات الصيانة');
    await page.locator('.subt button', {hasText: 'الاستيراد'}).click();
    await expect(page.locator('#idry')).toBeVisible();
    await expect(page.locator('#leaB')).toContainText('لا يُعدَّل ما أُدخل يدويًا');
  });

  test('a signed lease is renewed from its window and the new lease continues it', async () => {
    await page.locator('.subt button', {hasText: 'العقود'}).click();
    await page.click('[data-call="EXT.leaNew"]');
    const unit = await page.locator('#nu option', {hasText: 'شاغرة'}).first().getAttribute('value');
    await page.selectOption('#nu', unit);
    await page.fill('#tn_name', 'شركة الامتداد للتجارة');
    await page.fill('#tn_phone', '+968 91113333');
    await page.fill('#ns', '2036-01-01'); await page.fill('#nm', '12'); await page.fill('#nr', '1200');
    await page.selectOption('#nf', '4');
    await page.click('#nsg');
    await expect(page.locator('#ih')).toContainText('LS-2036-');
    await page.locator('#ib [data-call="EXT.leaRenew"]').click();
    await page.fill('#rm', '12'); await page.fill('#rr', '1300');
    await page.click('#rgo');
    await expect(page.locator('#ih')).toContainText('LS-2037-');          // the renewal starts the day after the old lease ends
    await expect(page.locator('#ib')).toContainText('تجديد لعقد سابق');
  });

  test('a maintenance request is raised and an owner statement previewed', async () => {
    await page.click('#ix');
    await page.locator('.subt button', {hasText: 'الصيانة والمصاريف'}).click();
    await page.click('[data-call="EXT.leaMaintForm"]');
    await page.fill('#mc', 'تكييف'); await page.fill('#md', 'المكيف لا يبرّد في غرفة الاجتماعات');
    await page.selectOption('#mp', 'urgent');
    await page.click('#mgo');
    await expect(page.locator('#leaB')).toContainText('تكييف');
    await page.locator('.subt button', {hasText: 'الملاك والكشوف'}).click();
    await page.locator('#leaB [data-call="EXT.leaOwnerStmt"]').first().click();
    await expect(page.locator('#mbox')).toContainText('الصافي = المحصَّل');
    await page.click('[data-call="closeModal"]');
  });
});
