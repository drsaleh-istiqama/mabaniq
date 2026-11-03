// 0.31.0 — البيانات الأساسية من الواجهة (docs/DESIGN-master-data-forms.md): مشروع ومبنى ووحدة وعميل ومقاول وعقد ومهمة تُنشأ وتُعدَّل وتُوقَف من الاستمارات،
// والتحقق فوري أثناء الكتابة، وتغيير سعر وحدة عليها حجز لا يمر إلا بسبب موثَّق. يعمل على خادم الاختبار نفسه (مطوّر العرض الافتراضي).
import {expect, test} from '@playwright/test';

const PASSWORD = process.env.MABANIQ_DEMO_PASSWORD || 'E2e-Demo-Pass-2026';
const TAG = String(Date.now()).slice(-6);
const CODE = 'E' + TAG, NAME = 'مشروع اختبار ' + TAG;

test.describe.serial('البيانات الأساسية', () => {
  let page;
  test.beforeAll(async ({browser}) => {
    page = await browser.newPage();
    await page.goto('/login');
    await page.fill('#u', 'admin'); await page.fill('#p', PASSWORD); await page.click('#b');
    await expect(page.locator('#whoName')).not.toHaveText('…');
  });
  test.afterAll(async () => { await page.close(); });

  test('a project, a unit and a documented price change; the unit is edited, stopped and restored', async () => {
    await page.click('[data-s="inv"]');
    await page.click('#mdInv');
    await expect(page.locator('#mbox h3')).toHaveText('إدارة المخزون');
    await page.click('#mbox [data-call="EXT.mdProject"]');
    await page.click('#mf_go');                                                                         // nothing typed: the form says what is missing
    await expect(page.locator('#mf_code_e')).toHaveText('«رمز المشروع» إلزامي');
    await expect(page.locator('#mf_name_e')).toHaveText('«اسم المشروع» إلزامي');
    await page.fill('#mf_code', 'x');
    await expect(page.locator('#mf_code_e')).toContainText('حروف إنجليزية وأرقام');                     // immediate, while typing
    await page.fill('#mf_code', CODE.toLowerCase()); await page.fill('#mf_name', NAME); await page.fill('#mf_handover', '2031-01-01');
    await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('أُضيف المشروع ' + CODE);
    await expect(page.locator('#mbox h3')).toHaveText('إدارة المخزون');                                    // back to the panel it came from
    await expect(page.locator('#mbox')).toContainText(NAME);
    await page.click('#mbox [data-call="closeModal"]');

    await page.locator('#projTree .ti', {hasText: NAME}).click();
    await expect(page.locator('#heat')).toContainText('لا وحدات في هذا المشروع بعد');                      // an empty project is a state, not an error
    await page.click('#mdUnit');
    await page.fill('#mf_code', CODE + '-A1'); await page.fill('#mf_building', 'ب1'); await page.fill('#mf_floor', '2'); await page.fill('#mf_pos', '1');
    await page.fill('#mf_type', 'غرفتان وصالة'); await page.fill('#mf_area', '88.5'); await page.fill('#mf_view', 'بحر'); await page.fill('#mf_price', '95000');
    await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('أُضيفت الوحدة ' + CODE + '-A1');
    await expect(page.locator('#ih')).toHaveText('وحدة');
    await expect(page.locator('#ib')).toContainText(CODE + '-A1');
    await expect(page.locator('#heat .cell')).toHaveCount(1);

    await page.click('#ib [data-call="EXT.mdPrice"]');                                                  // price change: the reason is mandatory
    await page.fill('#mf_price', '99000'); await page.click('#mf_go');
    await expect(page.locator('#mf_reason_e')).toContainText('إلزامي');
    await page.fill('#mf_reason', 'تسعير بقرار لجنة المبيعات'); await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('حُدّث: السعر');
    await expect(page.locator('#ib')).toContainText('99,000');

    await page.click('#ib [data-call="EXT.mdUnitEdit"]');                                               // edit: only what changed is sent; nothing changed says so
    await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('لم يتغيّر شيء');
    await page.click('#ib [data-call="EXT.mdUnitEdit"]');
    await page.fill('#mf_view', 'جبل'); await page.click('.fld:has(#mf_type) button');                  // change one, clear one
    await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('حُدّث: النوع، الإطلالة');
    await expect(page.locator('#ib')).toContainText('جبل');                                             // the card re-draws itself with the stored values

    page.once('dialog', d => d.accept());
    await page.click('#ib [data-call="EXT.mdAct"]');                                                    // stop: leaves the working list, keeps its history
    await expect(page.locator('#toast')).toContainText('أُوقف');
    await expect(page.locator('#heat')).toContainText('لا وحدات');
    await page.click('#mdInv');
    await expect(page.locator('#mbox')).toContainText('وحدات موقوفة');
    await page.click('#mbox [data-call="EXT.mdAct"][data-args*="restore"][data-args*="-A1"]');
    await expect(page.locator('#toast')).toContainText('استُعيد');
    await page.click('#mbox [data-call="closeModal"]');
    await expect(page.locator('#heat .cell')).toHaveCount(1);
  });

  test('a customer is made with the identity block through the shared path, and its contact data is edited', async () => {
    const name = 'عميل واجهة ' + TAG;
    if (await page.locator('#ix').isVisible()) await page.click('#ix');                                  // the unit card of the previous test may still be open
    await page.click('[data-s="sal"]');
    await page.locator('.subt button', {hasText: 'العملاء'}).click();
    await page.click('#salB [data-call="EXT.mdCustomer"]');
    await page.fill('#mf_name', name); await page.fill('#mf_phone', '+968 9111 2233');
    await page.check('#mf_with_kyc');
    await page.click('#mf_go');
    await expect(page.locator('#mf_id_number_e')).toContainText('إلزامي');                                // the identity block is required only once it is switched on
    await page.fill('#mf_id_number', '12345678'); await page.fill('#mf_nationality', 'عُماني'); await page.fill('#mf_id_expiry', '2032-01-01'); await page.fill('#mf_source_of_funds', 'راتب');
    await page.check('#mf_consent_signed');
    await page.click('#mf_go');
    await expect(page.locator('#toast')).toContainText('أُضيف العميل — الهوية:');
    await expect(page.locator('#salB')).toContainText(name);
    const row = page.locator('#salB tr', {hasText: name});
    await row.locator('[data-call="EXT.mdCustomer"]').click();
    await page.fill('#mf_phone', '+968 9444 5566'); await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('حُدّث: الهاتف');
  });

  test('a contractor, a contract and a schedule are made; the weights cannot pass one hundred per cent', async () => {
    await page.click('[data-s="con"]');
    await page.selectOption('#conP', {label: NAME});
    await page.click('[data-call="EXT.mdContractors"]');
    await page.click('#mbox [data-call="EXT.mdContractor"]');
    await page.fill('#mf_name', 'مقاول واجهة ' + TAG); await page.fill('#mf_cr_number', 'CR-' + TAG); await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('أُضيف المقاول');
    await page.click('#mbox [data-call="closeModal"]');

    await page.click('#conx [data-call="EXT.mdContract"]');
    await page.selectOption('#mf_contractor_id', {label: 'مقاول واجهة ' + TAG});
    await page.fill('#mf_value', '450000'); await page.fill('#mf_start', '2026-01-01'); await page.fill('#mf_finish', '2027-06-30'); await page.click('#mf_go');
    await expect(page.locator('#toast')).toHaveText('أُضيف عقد المقاول');
    await expect(page.locator('#conx')).toContainText('450,000');

    for (const [nm, a, b, w] of [['الحفريات', '2026-01-01', '2026-03-31', '60'], ['الهيكل', '2026-04-01', '2026-11-30', '30']]) {
      await page.click('#conx [data-call="EXT.mdTask"]:has-text("+ مهمة")');
      await page.fill('#mf_name', nm); await page.fill('#mf_planned_start', a); await page.fill('#mf_planned_end', b); await page.fill('#mf_weight', w); await page.click('#mf_go');
      await expect(page.locator('#toast')).toHaveText('أُضيفت المهمة');
    }
    await page.click('#conx [data-call="EXT.mdTask"]:has-text("+ مهمة")');
    await page.fill('#mf_name', 'التشطيب'); await page.fill('#mf_planned_start', '2026-12-01'); await page.fill('#mf_planned_end', '2027-05-30'); await page.fill('#mf_weight', '30'); await page.click('#mf_go');
    await expect(page.locator('#mf_err')).toContainText('يتجاوز 100');                                   // 60 + 30 + 30 > 100: the form says how much is left
    await expect(page.locator('#mf_err')).toContainText('10');
    await page.click('#mbox [data-call="closeModal"]');
    await expect(page.locator('#conx')).toContainText('مجموع الأوزان 90');
  });
});
