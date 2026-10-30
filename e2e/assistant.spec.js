// 0.18.0 — the assistant is its own panel (closes with ✕ / Esc, ⟲ starts over) and the organisation's background is a saved, validated choice.
// Runs against the same throw-away server as the other specs; the demo organisation is the default one.
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';

test.describe.serial('المساعد ومظهر المنصة', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
  });
  test.afterAll(async () => { await page.close(); });

  test('assistant opens apart from the details panel, answers from live data, closes with ✕ and Esc', async () => {
    await expect(page.locator('#ai')).toBeHidden();
    await page.click('#askBtn');
    await expect(page.locator('#ai')).toBeVisible();
    expect(await page.locator('.insp #clog').count()).toBe(0);   // no longer lives inside the details panel
    await page.fill('#ci', 'كم وحدة متاحة؟'); await page.press('#ci', 'Enter');
    await expect(page.locator('#clog .a:not(.pend)').last()).toContainText('متاحة');
    await page.click('#aiX');
    await expect(page.locator('#ai')).toBeHidden();
    await page.click('#askBtn');
    await expect(page.locator('#clog .q')).toHaveCount(1);       // closing keeps the conversation …
    await page.click('#aiNew');
    await expect(page.locator('#clog .q')).toHaveCount(0);       // … ⟲ starts a new one
    await page.focus('#ci'); await page.keyboard.press('Escape');
    await expect(page.locator('#ai')).toBeHidden();
  });

  test('an administrator picks a background; it is saved for the organisation and survives a reload', async () => {
    await page.click('[data-s="adm"]');
    await page.locator('.subt button', {hasText: 'المظهر والمساعد'}).click();
    await page.locator('.sw[data-bg="forest"]').click();
    await page.locator('.seg button', {hasText: 'شبكة'}).click();
    await expect(page.locator('html')).toHaveAttribute('data-bg', 'forest');
    await expect(page.locator('html')).toHaveAttribute('data-pat', 'grid');
    await page.locator('button', {hasText: 'حفظ للمؤسسة'}).click();
    await expect(page.locator('#toast')).toContainText('حُفظ');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-bg', 'forest');
    await page.waitForLoadState('networkidle');   // the boot's own refresh (dashboard, appearance) must finish before the next action, or it re-applies the saved look over the preview
    // restore the default so later specs and re-runs start from the standard look
    await page.click('[data-s="adm"]');
    await page.locator('.subt button', {hasText: 'المظهر والمساعد'}).click();
    await page.locator('button', {hasText: 'القيم الافتراضية'}).click();
    await expect(page.locator('html')).toHaveAttribute('data-bg', 'navy');   // the preview first — the saved look may still be arriving
    await page.locator('button', {hasText: 'حفظ للمؤسسة'}).click();
    await expect(page.locator('#toast')).toContainText('حُفظ');
    await expect(page.locator('html')).toHaveAttribute('data-bg', 'navy');
  });
});
