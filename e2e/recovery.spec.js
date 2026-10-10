// Password recovery through the real UI: admin gives the sales account an e-mail → "forgot password" → the link lands in the
// test server's outbox (no SMTP in tests) → the reset form sets a new password → sign-in with it works and the old one fails.
import {readdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const DATA = process.env.MABANIQ_E2E_DATA;

function latestOutbox() {
  const dir = join(DATA, 'outbox');
  const files = readdirSync(dir).filter(f => f.endsWith('.json')).sort();
  return JSON.parse(readFileSync(join(dir, files[files.length - 1]), 'utf8'));
}

test('forgot password → e-mailed link → new password → sign in', async ({page, request}) => {
  // admin sets the e-mail (API, as the users screen does)
  const login = await request.post('/api/auth/login', {data: {username: 'admin', password: PASSWORD, tenant: 'jadwa'}});
  expect(login.ok()).toBeTruthy();
  const users = await (await request.get('/api/users')).json();
  const sales = users.find(u => u.username === 'sales');
  const csrf = (await request.storageState()).cookies.find(c => c.name === 'mbq_csrf').value;
  expect((await request.post(`/api/users/${sales.id}/email`, {data: {email: 'sales@example.om'}, headers: {'X-CSRF-Token': csrf}})).ok()).toBeTruthy();

  await page.goto('/login');
  await expect(page.locator('#goForgot')).toBeVisible();
  await page.click('#goForgot');
  await page.fill('#fi', 'sales');
  await page.click('#b');
  await expect(page.locator('#msg')).toContainText('وصلته رسالة');
  const mail = latestOutbox();
  expect(mail.to).toBe('sales@example.om');
  expect(mail.link).toContain('/login?reset=');

  const newPw = 'Recovered-Pass-' + Date.now();
  await page.goto(mail.link.replace(/^https?:\/\/[^/]+/, ''));
  await expect(page.locator('#sReset')).toBeVisible();
  await page.fill('#n1', newPw);
  await page.fill('#n2', newPw);
  await page.click('#b');
  await expect(page).toHaveURL(/\/$/);  // reset → automatic sign-in → dashboard
  await expect(page.locator('#whoName')).not.toHaveText('…');

  // the old password no longer works; the link is single-use
  const old = await request.post('/api/auth/login', {data: {username: 'sales', password: PASSWORD, tenant: 'jadwa'}});
  expect(old.status()).toBe(401);
  const again = await request.post('/api/auth/password/reset', {data: {token: new URL(mail.link).searchParams.get('reset'), new: 'Other-Pass-2026-x', tenant: 'jadwa'}});
  expect(again.status()).toBe(400);
});
