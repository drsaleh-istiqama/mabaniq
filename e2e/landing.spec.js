// Public landing page (0.14.0) in a real browser: Arabic RTL root, the demo-request form submits through the page's own fetch
// (real CSP, same-origin check, own rate bucket) and the lead lands in the test server's outbox; the English twin is LTR.
import {readdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {expect, test} from '@playwright/test';

const DATA = process.env.MABANIQ_E2E_DATA;

function latestOutbox() {
  const dir = join(DATA, 'outbox');
  const files = readdirSync(dir).filter(f => f.endsWith('.json')).sort();
  return JSON.parse(readFileSync(join(dir, files[files.length - 1]), 'utf8'));
}

test('landing page: RTL, one H1, demo request reaches the outbox, /en is LTR', async ({page}) => {
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  await expect(page.locator('h1')).toHaveCount(1);
  await expect(page.locator('h1')).toContainText('من الحجز إلى التسليم');
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', /^http:\/\/127\.0\.0\.1:\d+\/$/);  // derived from the request origin, no placeholder left

  await page.click('a.btn[href="#demo"] >> nth=0');
  await page.fill('#dName', 'زائر تجريبي');
  await page.fill('#dCompany', 'شركة الاختبار للتطوير العقاري');
  await page.fill('#dEmail', 'visitor@example.om');
  await page.fill('#dPhone', '+968 9000 0000');
  await page.fill('#dProjects', '4');
  await page.fill('#dMessage', 'أريد رؤية التحصيل والسيولة');
  await page.click('#demoForm button[type="submit"]');
  await expect(page.locator('#demoMsg')).toHaveClass(/ok/);
  await expect(page.locator('#demoMsg')).toContainText('وصلنا طلبك');
  const mail = latestOutbox();
  expect(mail.kind).toBe('demo_request');
  expect(mail.text).toContain('شركة الاختبار للتطوير العقاري');
  expect(mail.text).toContain('visitor@example.om');

  await page.click('nav.nav-links a[hreflang="en"]');
  await expect(page).toHaveURL(/\/en$/);
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('h1')).toContainText('from booking to handover');
  expect(errors, errors.join('\n')).toEqual([]);
});
