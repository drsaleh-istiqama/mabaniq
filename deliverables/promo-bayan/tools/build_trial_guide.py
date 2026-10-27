# -*- coding: utf-8 -*-
"""دليل تجربة منصة مبانيك لبيان عمان (صفحتان A4) + نص رسالة الدعوة. لا كلمات مرور في أي مخرَج:
كلمة الدخول المؤقتة تُرسل بقناة منفصلة عن الدليل.   python deliverables/promo-bayan/tools/build_trial_guide.py"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from fpdf.enums import XPos, YPos
from hijridate import Gregorian

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")
import build_guide as G  # noqa: E402

PKG = HERE.parent
URL = "https://mabaneek.com"
TODAY = dt.date(2026, 10, 26)
_h = Gregorian(TODAY.year, TODAY.month, TODAY.day).to_hijri()
DATE_LINE = f"{_h.day} {_h.month_name('ar')} {_h.year}هـ الموافق {TODAY.day} أكتوبر {TODAY.year}م"

ACCOUNTS = [
    ("bayan-ceo", "مدير عام", "كل شيء: القرارات، المخزون، التأجير، التسويق، المالية، التقارير، المستخدمون والأمان"),
    ("bayan-sales", "مبيعات", "المخزون، العملاء المحتملون، عروض الأسعار والحجز والعقود، الوسطاء والعمولات، تسويق المشاريع"),
    ("bayan-finance", "مالية وتحصيل", "السيولة والتعثر، الفواتير والضمان، المطابقة البنكية، المستخلصات، التقارير، محفظة التأجير (العقود والإيجارات)"),
    ("bayan-engineer", "مهندس مشاريع", "الإنشاء والمستخلصات، التراخيص، التسليم والعيوب"),
    ("bayan-client", "عميل", "تطبيق العميل على الهاتف: وحدتي، الدفعات، الصيانة، المستندات (يُفتح تلقائيًا بعد الدخول)"),
]

STEPS = [
    ("bayan-ceo", "لوحة القيادة: صندوق القرارات مرتّبًا بالأولوية والأثر المالي، ثم اضغطوا على أي قرار لتروا سببه."),
    ("bayan-ceo", "المخزون والتسعير ⟵ اختاروا «مساحات الخوض» ⟵ زر «المخططات»: الطابق الأرضي بعلامات المحلات ومخططات كتيّبكم."),
    ("bayan-finance", "التسليم والأملاك ⟵ «التأجير» (صلاحية المالية والمدير العام): عقود الوحدات المحتفظ بها، دفعاتها الربعية، المتأخر، وتنبيه التجديد؛ جرّبوا «+ عقد إيجار» على الوحدة الشاغرة."),
    ("bayan-sales", "العقود والوسطاء ⟵ «عروض الأسعار» ⟵ «+ عرض سعر»: أصدروا عرضًا لمكتب متاح بخطة مرابحة، ثم افتحوا PDF بترويستكم، وحوّلوه إلى حجز."),
    ("bayan-client", "تطبيق العميل: وحدتي (تقدم البناء)، الدفعات (جدول الأقساط)، المزيد (العقد والمخططات وموقع وحدته)."),
    ("bayan-finance", "السيولة والتعثر ثم الفواتير والضمان: رادار السيولة، المتأخرات، وتبرعات التأخير بدل الغرامة."),
    ("bayan-ceo", "تسويق المشاريع: لوحة تصنّف مشاريعكم (آلاء بطيء البيع)، ثم «استوديو الإعلانات» لتصميم إعلان على تصوّر مساحات الخوض."),
    ("bayan-ceo", "التقارير والتحليلات: افتحوا «لوحة المحفظة» وصدّروها PDF أو CSV."),
]

NOTES = [
    "كل الأسعار والإيجارات ونِسب البيع والمستأجرين والعملاء والدفعات في هذه البيئة افتراضية، مبنية على مساحات كتيّباتكم المنشورة (لا تنشرون أسعاركم). لا تُدخلوا بيانات عملاء حقيقيين.",
    "قائمة «المطوّر» في شاشة الدخول تعرض مطوّرين آخرين لا علاقة لكم بهم؛ بياناتكم معزولة عنهم على مستوى قاعدة البيانات — وهو ما يسمح بكيان مستقل لبيت بيان للاستثمار إن أردتم.",
    "البريد في وضع «صندوق صادر» (لا يصل بريد فعلي بعد)، وواتساب بروابط wa.me تُفتح من جهازكم، والملفات التي ترفعونها مؤقتة وقد تُمحى عند تحديث المنصة.",
    "المنصة بالتمويل الإسلامي: لا فوائد في أي خطة؛ التأخير تبرع بشرط العقد لا غرامة إيرادًا.",
    "بعد دخولكم الأول تختارون كلمة مرور خاصة بكم لا يعرفها غيركم، ويمكنكم تفعيل التحقق الثنائي من «الإدارة والأمان ⟵ أماني».",
]


class TG(G.Guide):
    def footer(self):
        self.set_y(-12)
        self.set_font("Tajawal", "", 8)
        self.set_text_color(*G.MUTED)
        self.cell(self.cw, 5, f"صفحة {self.page_no()} من {{nb}} · {DATE_LINE} · بيانات التجربة افتراضية", align="R")
        self.set_y(-12)
        self.cell(self.cw, 5, "جدوى للدراسات والتطوير · مبانيك", align="L")


def build(out: Path):
    p = TG()
    p.set_auto_page_break(auto=True, margin=16)
    p.live = URL
    p.cover = False
    p.sec = "دليل التجربة"
    p.add_page()
    p.h1("دليل تجربة منصة مبانيك — بيان عمان", 18)
    p.set_font("Tajawal", "", 9.5)
    p.set_text_color(*G.MUTED)
    p.cell(p.cw, 6, DATE_LINE + " · بيئة تجربة خاصة بكم", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.ln(3)
    p.lead("هذه بيئة تجربة جُهّزت لكم باسم الشركة: مشاريعكم (مساحات الخوض، مركز الشباب للأعمال، آلاء بيزنس أفنيو، إم كيو ريزيدنسز، بوابة المعبيلة، ساحة الخوير) ومخططات كتيّباتكم وترويستكم، لتجربوا بأنفسكم كيف تُدار محفظة التأجير والمبيعات والحجوزات والتحصيل والتسليم والتسويق.", 10.3)

    # الدخول
    p.set_font("Tajawal", "B", 12); p.set_text_color(*G.GOLD)
    p.cell(p.cw, 8, "أولًا: كيف تدخلون", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.bullets([f"افتحوا {URL} ثم «دخول» (أو {URL}/login مباشرة).",
               "من قائمة «المطوّر» اختاروا «بيان عمان».",
               "اكتبوا اسم المستخدم من الجدول أدناه وكلمة المرور المؤقتة (تصلكم برسالة منفصلة عن هذا الدليل).",
               "ستُطلب منكم كلمة مرور جديدة خاصة بكم (10 أحرف فأكثر بحروف وأرقام) قبل المتابعة."], 10)

    # جدول الحسابات
    ws = [p.cw * x for x in (0.17, 0.15, 0.68)]
    y = p.get_y() + 1
    xr = p.w - p.r_margin
    p.set_fill_color(*G.INK); p.set_text_color(255, 255, 255); p.set_font("Tajawal", "B", 9.5)
    for h, wd in zip(("اسم المستخدم", "الدور", "ماذا يرى"), ws):
        p.set_xy(xr - wd, y); p.cell(wd, 8, h, align="C", fill=True); xr -= wd
    y += 8
    for i, row in enumerate(ACCOUNTS):
        p.set_font("Tajawal", "", 9)
        rh = max(p.multi_cell(ws[2] - 3, 4.8, row[2], align="R", dry_run=True, output="HEIGHT") + 4, 9)
        p.set_fill_color(*(G.PALE if i % 2 == 0 else (255, 255, 255)))
        p.rect(p.l_margin, y, p.cw, rh, style="F")
        xr = p.w - p.r_margin
        for ci, (cell, wd) in enumerate(zip(row, ws)):
            p.set_xy(xr - wd + 1.5, y + 2)
            p.set_text_color(*G.INK)
            p.set_font("Tajawal", "B" if ci == 0 else "", 9)
            if ci == 0:
                p.set_text_color(*G.GREEN)
            p.multi_cell(wd - 3, 4.8, cell, align="R" if ci == 2 else "C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            xr -= wd
        y += rh
    p.set_y(y + 4)

    # الجولة
    p.set_font("Tajawal", "B", 12); p.set_text_color(*G.GOLD)
    p.cell(p.cw, 8, "ثانيًا: جولة مقترحة من 15 دقيقة", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for i, (who, what) in enumerate(STEPS, 1):
        y = p.get_y()
        p.set_fill_color(*G.GOLD); p.set_text_color(255, 255, 255); p.set_font("Tajawal", "B", 9)
        p.set_xy(p.w - p.r_margin - 7, y); p.cell(7, 6.5, str(i), align="C", fill=True)
        p.set_fill_color(*G.INK); p.set_font("Tajawal", "B", 8)
        tw = p.get_string_width(who) + 5
        p.set_xy(p.w - p.r_margin - 9 - tw, y); p.cell(tw, 6.5, who, align="C", fill=True)
        p.set_text_color(*G.INK); p.set_font("Tajawal", "", 9.8)
        p.set_xy(p.l_margin, y)
        p.multi_cell(p.cw - 11 - tw, 5.3, what, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        p.ln(0.8)
    p.ln(0.5)

    # ملاحظات
    p.set_font("Tajawal", "B", 12); p.set_text_color(*G.GOLD)
    p.cell(p.cw, 8, "ثالثًا: اعلموا قبل التجربة", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.bullets(NOTES, 9.2)
    p.set_font("Tajawal", "B", 10.3); p.set_text_color(*G.GREEN)
    p.multi_cell(p.cw, 6, "ملاحظاتكم هي أثمن ما نحتاجه: ما أعجبكم، وما ينقص، وما تريدونه مختلفًا — أرسلوها لنا بأي وقت.", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    p.output(str(out))
    print("PDF", out.name, p.page_no(), "صفحة")


MESSAGE = f"""# رسالة دعوة التجربة — بيان عمان (مؤسسة بيان العقارية)

> للإرسال إلى إدارة بيان عمان — المؤسس والرئيس التنفيذي (واتساب/بريد). **كلمة المرور المؤقتة تُرسل برسالة منفصلة وليست في هذا الملف.**

السلام عليكم ورحمة الله وبركاته،

الإخوة الأفاضل في إدارة بيان عمان، جهّزنا لكم بيئة تجربة لمنصة «مبانيك» (منصة التطوير العقاري من جدوى) باسم شركتكم: مشاريعكم (مساحات الخوض، مركز الشباب للأعمال، آلاء بيزنس أفنيو، إم كيو ريزيدنسز، بوابة المعبيلة، ساحة الخوير) ومخططات كتيّباتكم وترويستكم، لتجربوا بأنفسكم دورة محفظتكم التجارية كاملة: التأجير (العقود والدفعات الربعية والتجديد) والبيع من عرض السعر إلى التسليم.

• الرابط: {URL}
• من شاشة الدخول اختاروا المطوّر «بيان عمان»
• اسم المستخدم للإدارة: bayan-ceo (مدير عام: يرى كل شيء) — وحسابات أخرى لفريقكم في «دليل التجربة» المرفق (مبيعات، مالية، مهندس، وعميل لتجربة تطبيق العميل)
• كلمة المرور المؤقتة سأرسلها في رسالة منفصلة، وستختارون كلمة خاصة بكم عند أول دخول

مرفق: «دليل التجربة» (صفحتان: الدخول، جولة 15 دقيقة، وملاحظات) و«الدليل المختصر» بلقطات من المنصة، وإنفوجرافيك المنصة في صفحة واحدة.

للعلم: الأسعار والإيجارات ونسب البيع والمستأجرون والعملاء في هذه البيئة افتراضية مبنية على مساحات كتيّباتكم المنشورة، فنرجو ألا تُدخلوا بيانات عملاء أو مستأجرين حقيقيين. وننتظر ملاحظاتكم، ثم نرتب اجتماعًا لعرض حي ومناقشة صيغة التعاون — وإن رغبتم في كيان مستقل لبيت بيان للاستثمار على المنصة نفسها فذلك متاح.

جزاكم الله خيرًا
"""

if __name__ == "__main__":
    build(PKG / "mabaniq-bayan-trial-guide.pdf")
    (PKG / "trial-invitation-message.md").write_text(MESSAGE, encoding="utf-8", newline="\n")
    print("message ok")
