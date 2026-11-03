// 0.30.0 — التحديث الجزئي من الواجهة (docs/DESIGN-partial-update.md): الترخيص لا يعلن «حُدّث» كذبًا، ويُفرَّغ رقمه وانتهاؤه بزر «مسح»،
// وحالته الحالية محدّدة في القائمة، والحقل المقنَّع للمالك لا يُمحى إلا بمسح صريح. يعمل على خادم الاختبار نفسه (مطوّر العرض الافتراضي).
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';

test.describe.serial('التحديث الجزئي', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
  });
  test.afterAll(async () => { await page.close(); });

  test('the permit form selects the current status, clears the reference and expiry with «مسح», and a save that changes nothing says so', async () => {
    await page.click('[data-s="pre"]');
    await page.locator('.subt button', {hasText: 'التراخيص'}).click();
    const row = page.locator('#preB tr[data-i]').filter({hasText: 'قيد المراجعة'}).first();
    await expect(row).toBeVisible();
    const statusBefore = (await row.locator('td').nth(4).innerText()).trim();
    await row.click();
    await expect(page.locator('#ps')).toBeVisible();
    expect((await page.locator('#ps option:checked').innerText()).trim()).toBe(statusBefore);          // not silently «مقدَّم»

    await page.fill('#pr', 'E2E-PU-1'); await page.fill('#pe', '2031-05-05'); await page.click('#pgo');
    await expect(page.locator('#toast')).toHaveText('حُدّث: الرقم المرجعي، تاريخ الانتهاء');
    await expect(page.locator('#pr')).toHaveValue('E2E-PU-1');                                         // the panel is re-shown with the stored values
    await expect(page.locator('#ib .kv')).toContainText(statusBefore);                                  // …and the status was not touched

    await page.click('.fld:has(#pr) button'); await page.click('.fld:has(#pe) button');
    await expect(page.locator('#pr')).toHaveValue(''); await expect(page.locator('#pe')).toHaveValue('');
    await page.click('#pgo');
    await expect(page.locator('#toast')).toHaveText('حُدّث: الرقم المرجعي، تاريخ الانتهاء');
    await expect(page.locator('#pr')).toHaveValue(''); await expect(page.locator('#pe')).toHaveValue('');   // really empty now, not «kept»
    const stored = await page.evaluate(async () => (await (await fetch('/api/permits')).json()).find(p => p.kind && p.ref === 'E2E-PU-1'));
    expect(stored).toBeUndefined();

    await page.click('#pgo');                                                                           // nothing changed
    await expect(page.locator('#toast')).toHaveText('لم يتغيّر شيء');
  });

  test('an owner\'s saved IBAN survives an edit that does not touch it, and goes only when «مسح» is pressed', async () => {
    const name = 'مالك واجهة التحديث ' + Date.now();
    const oid = await page.evaluate(async n => {
      const csrf = (document.cookie.match(/(?:^|; )mbq_csrf=([^;]+)/) || [])[1] || '';
      const r = await fetch('/api/lea/owners', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({name: n, kind: 'third_party', id_number: 'ID-4455667', iban: 'OM81BANK000011223344', phone: '99000011', mgmt_fee_pct: 3, mgmt_basis: 'collected'})});
      return (await r.json()).id;
    }, name);
    const ibanOf = () => page.evaluate(async id => (await (await fetch('/api/lea/owners')).json()).find(o => o.id === id).iban, oid);
    if (await page.locator('#ix').isVisible()) await page.click('#ix');                                  // the details panel of the previous test covers the page
    await page.click('[data-s="lea"]');
    await page.locator('.subt button', {hasText: 'الملاك'}).click();
    const edit = () => page.locator('#leaB tr').filter({hasText: name}).locator('button', {hasText: 'تعديل'}).click();

    await edit();
    await expect(page.locator('#ob')).toHaveAttribute('placeholder', /محفوظ/);                         // the form says a value is stored
    await page.fill('#op', '98765432');
    await page.click('#ogo');
    await expect(page.locator('#toast')).toHaveText('حُدّث: الهاتف');
    expect(await ibanOf()).toBeTruthy();                                                               // the IBAN was not in the request: it stayed

    await edit();
    await page.click('.fld:has(#ob) button');
    await expect(page.locator('#ob')).toHaveAttribute('placeholder', 'سيُمسح عند الحفظ');
    await page.click('#ogo');
    await expect(page.locator('#toast')).toHaveText('حُدّث: الآيبان');
    expect(await ibanOf()).toBeFalsy();

    await edit();
    await page.click('#ogo');
    await expect(page.locator('#toast')).toHaveText('لم يتغيّر شيء');
  });
});
