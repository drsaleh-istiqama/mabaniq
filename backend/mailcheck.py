"""`python -m backend.mailcheck [--send]` — فحص إعدادات SMTP كما تراها المنصة، بلا كشف كلمة المرور (0.14.1).

يُشغَّل محليًا أو من تبويب Console في Railway. يطبع المضيف والمنفذ ونوع التشفير والمستخدم (مقنَّعًا) وطول كلمة المرور وهل فيها مسافات،
ثم يحاول الاتصال وSTARTTLS وتسجيل الدخول ويطبع ردّ الخادم الحرفي عند الفشل. مع `--send` يرسل رسالة اختبار إلى MABANIQ_SALES_EMAIL (أو المرسِل).
"""
from __future__ import annotations

import smtplib
import ssl
import sys

from .config import settings


def mask(addr: str) -> str:
    if "@" not in addr:
        return addr[:2] + "…" if addr else "(فارغ)"
    u, d = addr.split("@", 1)
    return f"{u[:2]}***@{d}"


def main() -> int:
    s = settings.smtp
    pw = s["password"] or ""
    print(f"host={s['host'] or '(فارغ)'} port={s['port']} tls={s['tls']} user={mask(s['user'])} from={mask(s['from_addr'])} from_name={s['from_name']}")
    print(f"password: {'(فارغ)' if not pw else f'{len(pw)} حرفًا'}{' — تحوي مسافات!' if ' ' in pw else ''} · sales_email={mask(settings.sales_email) or '(فارغ)'} · env={settings.env}")
    if not s["host"] or not s["from_addr"]:
        print("✗ SMTP غير مهيّأ: يلزم MABANIQ_SMTP_HOST وMABANIQ_SMTP_FROM على الأقل (البريد في وضع صندوق الصادر).")
        return 2
    if s["user"] and "@" not in s["user"]:
        print("⚠ MABANIQ_SMTP_USER بلا @ — Gmail وWorkspace يطلبان العنوان الكامل.")
    try:
        ctx = ssl.create_default_context()
        if s["tls"] == "ssl":
            server = smtplib.SMTP_SSL(s["host"], s["port"], timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(s["host"], s["port"], timeout=20)
        with server:
            code, msg = server.ehlo()
            print(f"EHLO → {code} {msg.decode(errors='replace').splitlines()[0]}")
            if s["tls"] == "starttls":
                code, msg = server.starttls(context=ctx)
                print(f"STARTTLS → {code}")
                server.ehlo()
            print("AUTH mechanisms:", server.esmtp_features.get("auth", "(none)"))
            if s["user"]:
                try:
                    server.login(s["user"], pw.replace(" ", ""))
                    print("✓ تسجيل الدخول نجح")
                except smtplib.SMTPAuthenticationError as e:
                    print(f"✗ رفض الخادم بيانات الدخول: {e.smtp_code} {e.smtp_error.decode(errors='replace')[:300]}")
                    return 1
                except smtplib.SMTPServerDisconnected:
                    print("✗ أغلق الخادم الاتصال أثناء AUTH — هكذا يتصرف Gmail حين يكون المستخدم أو كلمة مرور التطبيق غير صحيحين، أو حين تكون كلمة المرور لحساب Google آخر غير MABANIQ_SMTP_USER.")
                    return 1
            if "--send" in sys.argv:
                from . import mail
                to = settings.sales_email or s["from_addr"]
                res = mail.send(to, "اختبار بريد مبانيك", "رسالة اختبار من python -m backend.mailcheck — إن وصلتك فالإرسال يعمل.", kind="mailcheck")
                print("✓ أُرسلت رسالة اختبار إلى", mask(to), res)
        return 0
    except Exception as e:  # noqa: BLE001 — a diagnostic prints whatever happened
        print(f"✗ {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
