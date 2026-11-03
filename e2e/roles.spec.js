// 0.32.0 — الأدوار والصلاحيات من الواجهة (docs/DESIGN-roles-permissions.md): المصفوفة تُعرض بأقسامها، والخانة تُحفظ فور النقر، ودور مخصص يُنشأ من نسخة ويُسنَد لمستخدم
// ثم يُنقل منه ويُحذف، وحاجز المدير العام، وعرض الهاتف بدور واحد في كل مرة. يعمل على خادم الاختبار نفسه (مطوّر العرض الافتراضي).
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const TAG = String(Date.now()).slice(-6);
const ROLE = 'مسؤول مبيعات أول ' + TAG, USER = 'rl.' + TAG;
const box = (role, perm) => `#rmx input.rpm[data-role="${role}"][data-perm="${perm}"]`;

test.describe.serial('الأدوار والصلاحيات', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
  });
  test.afterAll(async () => { await page.close(); });

  const openRoles = async () => {
    await page.click('[data-s="adm"]');
    await page.locator('#adm .seg button', {hasText: 'الأدوار والصلاحيات'}).click();
    await expect(page.locator('#rmx')).toBeVisible();
  };

  test('the matrix lists the sections and the built-in roles exactly as the code always gave them; the general manager keeps admin and users', async () => {
    await openRoles();
    for (const s of ['عام', 'المخزون والبيانات الأساسية', 'المبيعات', 'المالية', 'الموارد البشرية', 'الحوكمة والإدارة']) await expect(page.locator('#rmx tr.rmx-s th', {hasText: s}).first()).toBeVisible();
    for (const r of ['مدير عام', 'مبيعات', 'مالية وتحصيل', 'مهندس موقع', 'محاسب', 'مسؤول رواتب']) await expect(page.locator('#rmx thead th .rmx-n', {hasText: r}).first()).toBeVisible();
    await expect(page.locator(box('sales', 'book'))).toBeChecked();                                      // today's behaviour: sales books
    await expect(page.locator(box('sales', 'admin'))).not.toBeChecked();
    await expect(page.locator(box('admin', 'users'))).toBeDisabled();                                    // the general manager keeps these two
    await expect(page.locator(box('admin', 'admin'))).toBeDisabled();
    await expect(page.locator(box('admin', 'users'))).toHaveAttribute('title', 'لا يُسحب من المدير العام');
    await expect(page.locator('#rmx thead th[data-role="admin"] .pill')).toHaveText('تحقق ثنائي');       // the five mandatory roles are marked
    await expect(page.locator('.rmx-foot')).toContainText('أدوار البوابات ثابتة');
  });

  test('a ticked box is saved at once and survives a reload; the API agrees', async () => {
    await openRoles();
    await page.locator(box('sales', 'leads')).uncheck();
    await expect(page.locator('#toast')).toContainText('سُحبت «العملاء المحتملون والحملات» من دور «مبيعات»');
    await page.reload(); await openRoles();
    await expect(page.locator(box('sales', 'leads'))).not.toBeChecked();
    const r = await (await page.request.get('/api/roles')).json();
    expect(r.roles.find(x => x.code === 'sales').perms).not.toContain('leads');
    await page.locator(box('sales', 'leads')).check();                                                    // give it back: the shared test server keeps its defaults
    await expect(page.locator('#toast')).toContainText('مُنحت «العملاء المحتملون والحملات» لدور «مبيعات»');
    const r2 = await (await page.request.get('/api/roles')).json();
    expect(r2.roles.find(x => x.code === 'sales').perms).toContain('leads');
  });

  test('a custom role is made from a copy, a sensitive permission brings the two-factor badge, a user is given the role, moved away from it, and the role is deleted', async () => {
    await openRoles();
    await page.click('[data-call="EXT.roleNew"]');
    await page.click('#mf_go');                                                                           // nothing typed: the form says what is missing
    await expect(page.locator('#mf_label_e')).toHaveText('«اسم الدور» إلزامي');
    await page.fill('#mf_label', 'اب');
    await expect(page.locator('#mf_label_e')).toContainText('3 أحرف على الأقل');                         // immediate, while typing
    await page.fill('#mf_label', ROLE); await page.selectOption('#mf_copy_from', 'sales');
    await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('أُضيف الدور «' + ROLE + '»');
    const head = page.locator('#rmx thead th', {hasText: ROLE});
    await expect(head).toBeVisible();
    const code = await head.getAttribute('data-role');
    await expect(page.locator(box(code, 'book'))).toBeChecked();                                          // copied from sales
    await expect(page.locator(box(code, 'accounting_approve'))).not.toBeChecked();
    await page.locator(box(code, 'accounting_approve')).check();
    await expect(head.locator('.pill')).toHaveText('تحقق ثنائي');                                         // a sensitive permission brings its protection with it
    await page.locator(box(code, 'accounting_approve')).uncheck();
    await expect(head.locator('.pill')).toHaveCount(0);

    await page.locator('#adm .seg button', {hasText: 'المستخدمون'}).click();                             // a user holding the role
    await page.click('[data-call="EXT.newUser"]');
    await expect(page.locator('#ur option').last()).toHaveText('مدير عام');                               // the manager is never the default
    await page.fill('#un', USER); await page.fill('#unm', 'مستخدم دور اختبار'); await page.selectOption('#ur', code);
    await page.click('#ugo');
    await expect(page.locator('#mbox h3')).toHaveText('أُنشئ المستخدم');
    await page.click('#mbox [data-call="closeModal"]');
    const row = page.locator('#admB tbody tr', {hasText: USER});
    await expect(row).toContainText(ROLE);                                                                // the screen shows the custom role's own name

    await page.locator('#adm .seg button', {hasText: 'الأدوار والصلاحيات'}).click();
    page.once('dialog', d => d.accept());
    await page.locator(`#rmx thead th[data-role="${code}"] [data-call="EXT.roleDel"]`).click();
    await expect(page.locator('#toast')).toContainText('للدور 1 مستخدم');                                  // refused while a user holds it
    await expect(head).toBeVisible();

    await page.locator('#adm .seg button', {hasText: 'المستخدمون'}).click();
    await page.locator('#admB tbody tr', {hasText: USER}).locator('[data-call="EXT.urole"]').click();
    await page.selectOption('#mf_role', 'sales'); await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('غُيّر دور المستخدم');
    await expect(page.locator('#admB tbody tr', {hasText: USER})).toContainText('مبيعات');
    await page.locator('#admB tbody tr', {hasText: USER}).locator('[data-call="EXT.uact"]').click();       // stop the test user…
    await expect(page.locator('#admB tbody tr', {hasText: USER})).toContainText('معطّل');                  // …and let the screen finish refreshing before moving on

    await page.locator('#adm .seg button', {hasText: 'الأدوار والصلاحيات'}).click();
    page.once('dialog', d => d.accept());
    await page.locator(`#rmx thead th[data-role="${code}"] [data-call="EXT.roleDel"]`).click();
    await expect(page.locator('#toast')).toHaveText('حُذف الدور «' + ROLE + '»');
    await expect(page.locator('#rmx thead th', {hasText: ROLE})).toHaveCount(0);
  });

  test('on a phone one role is shown at a time and the page does not scroll sideways', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await page.reload();                                                                                  // the app reopens on the screen it was left on (the side menu is folded away on a phone)
    await page.locator('#adm .seg button', {hasText: 'الأدوار والصلاحيات'}).click();
    await expect(page.locator('#rmx')).toBeVisible();
    await expect(page.locator('#rmFocus')).not.toHaveValue('all');
    await expect(page.locator('#rmx thead th[data-role]:not([hidden])')).toHaveCount(1);
    const w = await page.evaluate(() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth}));
    expect(w.doc).toBeLessThanOrEqual(w.win);
    await page.selectOption('#rmFocus', 'all');
    expect(await page.locator('#rmx thead th[data-role]:not([hidden])').count()).toBeGreaterThan(5);
    const w2 = await page.evaluate(() => ({doc: document.documentElement.scrollWidth, win: window.innerWidth}));
    expect(w2.doc).toBeLessThanOrEqual(w2.win);                                                            // the table scrolls inside its own frame
    await page.setViewportSize({width: 1280, height: 800});
  });
});
