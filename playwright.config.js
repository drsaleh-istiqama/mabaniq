// Playwright — critical-path e2e (Unit 3, acceptance item 16). `npm run e2e`.
// Starts the API on a throw-away SQLite file with a known demo password; CI installs Chromium, locally Chrome is used.
import {defineConfig} from '@playwright/test';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const PORT = Number(process.env.MABANIQ_E2E_PORT || 8831);
const DEMO_PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const db = join(mkdtempSync(join(tmpdir(), 'mbq-e2e-')), 'e2e.db');
const python = process.env.PYTHON || (process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : 'python');

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  expect: {timeout: 10_000},
  retries: process.env.CI ? 1 : 0,
  workers: 1, // one shared database — the tests are sequential by design
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'ar-OM',
    timezoneId: 'Asia/Muscat',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{name: 'chromium', use: {browserName: 'chromium', ...(process.env.CI ? {} : {channel: 'chrome'})}}],
  webServer: {
    command: `${python} -m uvicorn backend.app:app --host 127.0.0.1 --port ${PORT} --no-access-log`,
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      ...process.env,
      MABANIQ_DB: db,
      MABANIQ_DEMO_PASSWORD: DEMO_PASSWORD,
      MABANIQ_FORCE_PW_CHANGE: '0',
      MABANIQ_LOG_JSON: '0',
      MABANIQ_RATE_LOGIN: '60/60', // the suite logs in several times in a row from one address
      PYTHONIOENCODING: 'utf-8',
    },
  },
});
