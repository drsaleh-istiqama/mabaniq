"""Mabaniq 0.29.0 — the invented people of the two full-demo developers (see backend/seed_org.py).

Every name, number, salary and date below is illustrative: no person is real, the figures follow typical Muscat real-estate pay bands so reports look plausible.
Dates are written relative to the day the seed runs (negative = days ago, so a hire "-1500" is about four years before) — the seed never hard-codes a calendar day
that would age. Order matters: a manager precedes the people who report to him (the platform refuses a manager that does not exist yet).

Employee tuple: (key, Arabic name, English name, nationality ('' = Omani), gender, marital, department key, position, manager key | None, hired (days ago), contract,
contract_end (days from today | None), basic, housing, transport, bank)
"""
from __future__ import annotations

# ----------------------------------------------------------------------------------------------------- shared reference lists
BANKS = ("بنك مسقط", "بنك ظفار", "بنك نزوى", "صحار الدولي", "بنك الإسكان العماني")

# department key, name
# position: (title, department key, grade, headcount)
ORGS: dict[str, dict] = {
    "bayan": {
        "departments": [
            ("exec", "الإدارة التنفيذية"), ("sales", "المبيعات والتأجير"), ("proj", "المشاريع والإنشاء"), ("fin", "المالية والمحاسبة"),
            ("hr", "الموارد البشرية والشؤون الإدارية"), ("pm", "إدارة الأملاك والمرافق"), ("cx", "التسويق وخدمة العملاء"),
        ],
        "positions": [
            ("الرئيس التنفيذي", "exec", "A1", 1), ("مدير مكتب الرئيس التنفيذي", "exec", "C1", 1),
            ("مدير المبيعات والتأجير", "sales", "B1", 1), ("مسؤول تأجير", "sales", "C2", 2), ("مسؤول مبيعات", "sales", "C2", 3), ("مندوب تحصيل", "sales", "D1", 1),
            ("مدير المشاريع", "proj", "B1", 1), ("مهندس موقع أول", "proj", "C1", 2), ("مهندس مدني", "proj", "C2", 2), ("مراقب موقع", "proj", "D1", 2),
            ("المدير المالي", "fin", "B1", 1), ("محاسب أول", "fin", "C1", 1), ("محاسب ذمم", "fin", "C2", 1),
            ("مساعد محاسب", "fin", "D1", 1),
            ("مسؤول موارد بشرية", "hr", "C1", 1), ("مسؤول شؤون إدارية وعلاقات حكومية", "hr", "D1", 1), ("سائق ومراسل", "hr", "E1", 1),
            ("مدير الأملاك والمرافق", "pm", "B1", 1), ("مهندس صيانة", "pm", "C2", 2),
            ("مسؤول تسويق وخدمة العملاء", "cx", "C1", 1), ("موظف استقبال وخدمة عملاء", "cx", "D1", 2),
        ],
        # key, name, english, nationality, gender, marital, dept, position, manager, hired days ago, contract, contract end (days ahead), basic, housing, transport, bank
        "employees": [
            ("ceo", "م. سالم بن ناصر الحارثي", "Salim Nasser Al Harthi", "", "male", "married", "exec", "الرئيس التنفيذي", None, 3700, "permanent", None, 3200, 800, 250, 0),
            ("office", "مريم بنت خلفان العبرية", "Maryam Khalfan Al Abri", "", "female", "married", "exec", "مدير مكتب الرئيس التنفيذي", "ceo", 3000, "permanent", None, 1100, 300, 120, 1),
            ("pmgr", "م. هلال بن سعيد المعمري", "Hilal Said Al Maamari", "", "male", "married", "proj", "مدير المشاريع", "ceo", 3500, "permanent", None, 2100, 500, 200, 0),
            ("eng1", "م. أحمد خالد السيد", "Ahmed Khaled El Sayed", "مصري", "male", "married", "proj", "مهندس موقع أول", "pmgr", 2000, "fixed", 95, 1050, 350, 100, 3),
            ("eng2", "م. رشا بنت حمد الكندية", "Rasha Hamad Al Kindi", "", "female", "single", "proj", "مهندس مدني", "pmgr", 1150, "permanent", None, 760, 200, 100, 2),
            ("insp", "فيصل بن سيف الشكيلي", "Faisal Saif Al Shukaili", "", "male", "married", "proj", "مراقب موقع", "pmgr", 1600, "permanent", None, 560, 150, 80, 4),
            ("cfo", "د. يوسف بن علي البلوشي", "Dr. Yousuf Ali Al Balushi", "", "male", "married", "fin", "المدير المالي", "ceo", 3300, "permanent", None, 2000, 450, 150, 0),
            ("acc1", "سلمى بنت ناصر الغافرية", "Salma Nasser Al Ghafri", "", "female", "married", "fin", "محاسب أول", "cfo", 2400, "permanent", None, 820, 220, 90, 1),
            ("acc2", "راجيش كومار نائر", "Rajesh Kumar Nair", "هندي", "male", "married", "fin", "محاسب ذمم", "cfo", 2500, "fixed", 330, 640, 160, 60, 3),
            ("hr", "هدى بنت سعيد الريامية", "Huda Said Al Riyami", "", "female", "married", "hr", "مسؤول موارد بشرية", "ceo", 2700, "permanent", None, 1150, 300, 100, 2),
            ("pro", "ماجد بن عبدالله السعدي", "Majid Abdullah Al Saadi", "", "male", "single", "hr", "مسؤول شؤون إدارية وعلاقات حكومية", "hr", 1700, "permanent", None, 540, 140, 60, 4),
            ("driver", "عمران شاه خان", "Imran Shah Khan", "باكستاني", "male", "married", "hr", "سائق ومراسل", "hr", 1400, "fixed", 40, 330, 80, 0, 3),
            ("smgr", "خالد بن مسعود الرواحي", "Khalid Masoud Al Rawahi", "", "male", "married", "sales", "مدير المبيعات والتأجير", "ceo", 3100, "permanent", None, 1700, 400, 200, 0),
            ("lease1", "عائشة بنت سالم الحجرية", "Aisha Salim Al Hajri", "", "female", "single", "sales", "مسؤول تأجير", "smgr", 1700, "permanent", None, 700, 180, 80, 2),
            ("sale1", "بدر بن محمد الراشدي", "Badr Mohammed Al Rashdi", "", "male", "single", "sales", "مسؤول مبيعات", "smgr", 1000, "permanent", None, 600, 150, 80, 4),
            ("pmg2", "سعود بن حمود الجابري", "Saud Hamoud Al Jabri", "", "male", "married", "pm", "مدير الأملاك والمرافق", "ceo", 2800, "permanent", None, 1500, 350, 150, 1),
            ("mkt", "ريم ماهر الخطيب", "Reem Maher Al Khatib", "أردنية", "female", "single", "cx", "مسؤول تسويق وخدمة العملاء", "smgr", 1500, "fixed", 215, 900, 250, 100, 0),
            ("recep", "ماريا سانتوس", "Maria Santos", "فلبينية", "female", "single", "cx", "موظف استقبال وخدمة عملاء", "mkt", 800, "fixed", 95, 420, 100, 0, 3),
            ("tech", "نواف بن خميس المنذري", "Nawaf Khamis Al Mandhari", "", "male", "single", "pm", "مهندس صيانة", "pmg2", 82, "permanent", None, 620, 150, 80, 1),
            ("leaver", "سانجاي فيرما", "Sanjay Verma", "هندي", "male", "married", "sales", "مندوب تحصيل", "smgr", 2700, "permanent", None, 480, 120, 40, 3),
        ],
        # who signs what in the audit trail and the maker / checker columns: (login name, key of the employee whose name is shown) — the trial logins of the profile
        "actors": {"admin": ("admin", "ceo"), "hr": ("bayan-hr", "hr"), "payroll_a": ("bayan-payroll", "acc2"), "payroll_b": ("admin", "ceo"),
                   "accountant": ("bayan-accountant", "acc1"), "finance": ("finance", "cfo")},
        "leaver": "leaver",       # a person whose service ends with a settlement (key above)
        "newhire": "tech",         # hired recently: probation, partial first month
        "raises": ("acc1", "lease1"),  # a raise effective on the 1st of the last closed month
        "openings": [
            ("مهندس موقع", "proj", 1, "مهندس مدني بخبرة لا تقل عن ثلاث سنوات في المباني التجارية، يجيد قراءة المخططات ومتابعة المقاولين.", "بكالوريوس هندسة مدنية · خبرة 3 سنوات · عضوية نقابة المهندسين · رخصة قيادة"),
            ("مسؤول تأجير تجاري", "sales", 1, "إدارة طلبات استئجار المكاتب والمحلات وتجديد العقود وتحصيل الإيجارات.", "خبرة في التأجير العقاري التجاري · مهارات تفاوض · إتقان Excel"),
            ("مساعد محاسب", "fin", 1, "إدخال القيود وفواتير الموردين ومتابعة التحصيل تحت إشراف المحاسب الأول.", "دبلوم أو بكالوريوس محاسبة · معرفة أساسية بقيمة مضافة"),
        ],
        "candidates": [
            ("وليد بن سهيل الفارسي", "Waleed"), ("نجلاء بنت حمدان الحوسنية", "Najla"), ("عبدالله بن راشد الهاشمي", "Abdullah"), ("إيمان بنت صالح البطاشية", "Eman"),
            ("طارق منصور العلي", "Tariq"), ("سميرة بنت علي المقبالية", "Samira"), ("زياد بن مبارك الفليتي", "Ziyad"), ("لمى بنت يعقوب السيابية", "Lama"),
        ],
        "hire_candidate": ("لمى بنت يعقوب السيابية", "مساعد محاسب", "fin", "female", 540, 130, 60),
    },
    "almukhatat": {
        "departments": [
            ("exec", "الإدارة العامة"), ("sales", "المبيعات والتسويق"), ("proj", "المشاريع والإنشاء"), ("fin", "المالية والمحاسبة"),
            ("hr", "الموارد البشرية والشؤون الإدارية"), ("cx", "خدمة العملاء وما بعد البيع"), ("pm", "إدارة الأملاك والتأجير"),
        ],
        "positions": [
            ("الرئيس التنفيذي", "exec", "A1", 1), ("مدير مكتب الرئيس", "exec", "C1", 1),
            ("مدير المبيعات والتسويق", "sales", "B1", 1), ("مسؤول مبيعات", "sales", "C2", 4), ("مسؤول تسويق رقمي", "sales", "C2", 1), ("منسق حجوزات", "sales", "D1", 2),
            ("مدير المشاريع", "proj", "B1", 1), ("مهندس موقع أول", "proj", "C1", 2), ("مهندس مدني", "proj", "C2", 3), ("مراقب موقع", "proj", "D1", 2), ("مهندس كميات", "proj", "C2", 1),
            ("المدير المالي", "fin", "B1", 1), ("محاسب أول", "fin", "C1", 1), ("أمين صندوق وتحصيل", "fin", "D1", 1),
            ("مسؤول موارد بشرية", "hr", "C1", 1), ("مسؤول مشتريات ولوجستيات", "hr", "D1", 1), ("عامل خدمات", "hr", "E1", 2),
            ("مدير خدمة العملاء", "cx", "B2", 1), ("منسق تسليم وضمان", "cx", "C2", 2),
            ("منسق خدمة عملاء", "cx", "D1", 1),
            ("مدير الأملاك والتأجير", "pm", "B1", 1), ("مسؤول عقود إيجار", "pm", "C2", 2),
        ],
        "employees": [
            ("ceo", "م. حمود بن راشد الفارسي", "Hamoud Rashid Al Farsi", "", "male", "married", "exec", "الرئيس التنفيذي", None, 3900, "permanent", None, 3400, 900, 300, 0),
            ("office", "أسماء بنت مبارك الحبسية", "Asma Mubarak Al Habsi", "", "female", "married", "exec", "مدير مكتب الرئيس", "ceo", 3200, "permanent", None, 1050, 280, 120, 2),
            ("smgr", "عبدالرحمن بن يوسف الصوافي", "Abdulrahman Yousuf Al Sawafi", "", "male", "married", "sales", "مدير المبيعات والتسويق", "ceo", 3400, "permanent", None, 1900, 450, 200, 0),
            ("sale1", "ثريا بنت أحمد الشيزاوية", "Thuraya Ahmed Al Shizawi", "", "female", "married", "sales", "مسؤول مبيعات", "smgr", 2300, "permanent", None, 720, 180, 90, 1),
            ("sale2", "سيف بن عامر الوهيبي", "Saif Amer Al Wahaibi", "", "male", "single", "sales", "مسؤول مبيعات", "smgr", 1400, "permanent", None, 600, 150, 80, 4),
            ("sale3", "محمد نديم أنصاري", "Mohammed Nadeem Ansari", "هندي", "male", "married", "sales", "مسؤول مبيعات", "smgr", 1900, "fixed", 150, 620, 150, 60, 3),
            ("digital", "ليان بنت وليد القاسمي", "Layan Walid Al Qasimi", "أردنية", "female", "single", "sales", "مسؤول تسويق رقمي", "smgr", 900, "fixed", 60, 780, 200, 80, 0),
            ("book", "شيماء بنت حميد البوسعيدية", "Shaima Humaid Al Busaidi", "", "female", "single", "sales", "منسق حجوزات", "smgr", 560, "permanent", None, 480, 120, 60, 2),
            ("pmgr", "م. ناصر بن سليمان البادي", "Nasser Sulaiman Al Badi", "", "male", "married", "proj", "مدير المشاريع", "ceo", 3600, "permanent", None, 2200, 520, 220, 0),
            ("eng1", "م. أنيس الرحمن صديقي", "Anees Ur Rehman Siddiqui", "باكستاني", "male", "married", "proj", "مهندس موقع أول", "pmgr", 2600, "fixed", 120, 1100, 350, 100, 3),
            ("eng2", "م. بدرية بنت سالم الهنائية", "Badriya Salim Al Hinai", "", "female", "married", "proj", "مهندس مدني", "pmgr", 1300, "permanent", None, 780, 200, 100, 1),
            ("eng3", "م. أيمن حسام الدين", "Ayman Hossam El Din", "مصري", "male", "single", "proj", "مهندس كميات", "pmgr", 1000, "fixed", 260, 900, 250, 100, 3),
            ("insp", "يعقوب بن زاهر الكلباني", "Yaqoob Zahir Al Kalbani", "", "male", "married", "proj", "مراقب موقع", "pmgr", 1800, "permanent", None, 570, 150, 80, 4),
            ("cfo", "م. إبراهيم بن عيسى الراجحي", "Ibrahim Issa Al Rajhi", "", "male", "married", "fin", "المدير المالي", "ceo", 3100, "permanent", None, 2050, 460, 160, 0),
            ("acc1", "نادية بنت خالد الجهورية", "Nadia Khalid Al Jahwari", "", "female", "single", "fin", "محاسب أول", "cfo", 1900, "permanent", None, 830, 220, 90, 1),
            ("cash", "ذياب بن سعد الغيلاني", "Dhiyab Saad Al Ghailani", "", "male", "married", "fin", "أمين صندوق وتحصيل", "cfo", 1500, "permanent", None, 520, 130, 60, 4),
            ("hr", "فاطمة بنت عبدالله الرحبية", "Fatma Abdullah Al Rahbi", "", "female", "married", "hr", "مسؤول موارد بشرية", "ceo", 2500, "permanent", None, 1120, 300, 100, 2),
            ("buyer", "أمجد عبدالله القدسي", "Amjad Abdullah Al Qudsi", "أردني", "male", "married", "hr", "مسؤول مشتريات ولوجستيات", "hr", 1250, "fixed", 130, 650, 160, 70, 0),
            ("clean", "ديفيد بيريرا", "David Perera", "سريلانكي", "male", "married", "hr", "عامل خدمات", "hr", 1100, "fixed", 25, 300, 70, 0, 3),
            ("cxm", "منى بنت خميس العامرية", "Muna Khamis Al Amri", "", "female", "married", "cx", "مدير خدمة العملاء", "ceo", 2900, "permanent", None, 1350, 320, 140, 1),
            ("hand1", "عمار بن ماجد المحروقي", "Ammar Majid Al Mahrouqi", "", "male", "single", "cx", "منسق تسليم وضمان", "cxm", 700, "permanent", None, 580, 150, 80, 2),
            ("pmg2", "طلال بن محمد السالمي", "Talal Mohammed Al Salmi", "", "male", "married", "pm", "مدير الأملاك والتأجير", "ceo", 2600, "permanent", None, 1450, 340, 150, 4),
            ("lease1", "رحمة بنت سعيد الزدجالية", "Rahma Said Al Zadjali", "", "female", "single", "pm", "مسؤول عقود إيجار", "pmg2", 75, "permanent", None, 600, 150, 80, 1),
            ("leaver", "غلام مصطفى", "Ghulam Mustafa", "باكستاني", "male", "married", "hr", "عامل خدمات", "hr", 2600, "permanent", None, 310, 70, 0, 3),
        ],
        "actors": {"admin": ("admin", "ceo"), "hr": ("mk-hr", "hr"), "payroll_a": ("mk-payroll", "cash"), "payroll_b": ("admin", "ceo"),
                   "accountant": ("mk-accountant", "acc1"), "finance": ("finance", "cfo")},
        "leaver": "leaver",
        "newhire": "lease1",
        "raises": ("acc1", "sale1"),
        "openings": [
            ("مهندس موقع (فلل)", "proj", 2, "متابعة تنفيذ الفلل السكنية والتنسيق مع المقاولين وفحص الأعمال قبل التسليم.", "بكالوريوس هندسة مدنية · خبرة في المشاريع السكنية · قراءة المخططات"),
            ("مسؤول مبيعات عقارية", "sales", 1, "استقبال العملاء وعرض الوحدات والحجز والمتابعة حتى توقيع العقد.", "خبرة في المبيعات · مهارات تواصل · لغة إنجليزية جيدة"),
            ("منسق خدمة عملاء", "cx", 1, "متابعة طلبات الصيانة وما بعد البيع وتنسيق الزيارات.", "خبرة في خدمة العملاء · إتقان الحاسب"),
        ],
        "candidates": [
            ("حمد بن ناصر الشامسي", "Hamad"), ("آمنة بنت راشد النبهانية", "Amna"), ("بسام فؤاد الحسيني", "Bassam"), ("وفاء بنت عبدالعزيز الفارسية", "Wafaa"),
            ("جابر بن سالم الدرمكي", "Jaber"), ("منال بنت خالد الأغبري", "Manal"), ("حسام الدين محمود", "Hossam"), ("نوال بنت حمد الشبلية", "Nawal"),
        ],
        "hire_candidate": ("نوال بنت حمد الشبلية", "منسق خدمة عملاء", "cx", "female", 520, 120, 60),
    },
}

# policy-neutral working text for the employee file's notes
EMERGENCY = ("أخ", "زوجة", "أب", "أم", "زوج", "أخت")
