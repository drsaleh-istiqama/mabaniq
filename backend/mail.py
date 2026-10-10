"""Mabaniq — outbound e-mail (0.10.0): recovery links, sign-in links, verification.

One transport, configured from the environment only (`MABANIQ_SMTP_*`). Without a configured SMTP host:
  * demo/dev: the message is written to `data/outbox/<stamp>.json` (tests and the Playwright suite read it) and, when
    `MABANIQ_MAIL_ECHO=1`, the link is also returned to the caller so a hosted demo without a mail provider stays usable;
  * prod: sending raises — the API reports the feature as unavailable instead of pretending to send.
Messages are Arabic, RTL, plain text first with a small HTML wrapper; no tracking, no external assets.
"""
from __future__ import annotations

import html
import json
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

from .config import settings
from .db import data_dir
from .observability import log


def configured() -> bool:
    s = settings.smtp
    return bool(s["host"] and s["from_addr"])


def outbox_mode() -> bool:
    return not configured() and not settings.prod


def available() -> bool:
    """Can the API offer e-mail based flows right now?"""
    return configured() or outbox_mode()


def outbox_dir() -> Path:
    d = data_dir() / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _html(subject: str, text: str, link: str | None, label: str | None) -> str:
    body = "".join(f"<p>{html.escape(p)}</p>" for p in text.split("\n\n") if p.strip())
    btn = (f'<p style="margin:24px 0"><a href="{html.escape(link)}" style="background:#D4A64A;color:#1A1405;padding:12px 22px;'
           f'border-radius:10px;text-decoration:none;font-weight:700;display:inline-block">{html.escape(label or "فتح الرابط")}</a></p>'
           f'<p style="color:#6b7280;font-size:12px;direction:ltr;text-align:left;word-break:break-all">{html.escape(link)}</p>') if link else ""
    return (f'<!doctype html><html lang="ar" dir="rtl"><body style="margin:0;background:#f5f6f8;font-family:Tajawal,Segoe UI,Tahoma,sans-serif;color:#111827">'
            f'<div style="max-width:560px;margin:24px auto;background:#fff;border-radius:16px;padding:28px 26px;direction:rtl;text-align:right">'
            f'<div style="font-weight:700;font-size:18px;margin-bottom:6px">مبانيك</div><h2 style="margin:0 0 14px;font-size:20px">{html.escape(subject)}</h2>'
            f'{body}{btn}<p style="color:#6b7280;font-size:12px;margin-top:22px">إن لم تطلب هذه الرسالة فتجاهلها؛ لا يتغيّر شيء في حسابك.</p></div></body></html>')


def send(to: str, subject: str, text: str, link: str | None = None, label: str | None = None, kind: str = "message",
         attachments: list[tuple[str, bytes, str]] | None = None) -> dict:
    """Deliver (SMTP) or record (outbox). Returns {"delivered": bool, "outbox": path?, "echo": link?}."""
    if configured():
        s = settings.smtp
        msg = EmailMessage()
        msg["From"] = f'{s["from_name"]} <{s["from_addr"]}>' if s["from_name"] else s["from_addr"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text + (f"\n\n{link}\n" if link else ""))
        msg.add_alternative(_html(subject, text, link, label), subtype="html")
        for fname, blob, mime in attachments or []:
            maintype, _, subtype = (mime or "application/octet-stream").partition("/")
            msg.add_attachment(blob, maintype=maintype, subtype=subtype or "octet-stream", filename=fname)
        ctx = ssl.create_default_context()
        if s["tls"] == "ssl":
            server = smtplib.SMTP_SSL(s["host"], s["port"], timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(s["host"], s["port"], timeout=20)
        with server:
            if s["tls"] == "starttls":
                server.starttls(context=ctx)
            if s["user"]:
                server.login(s["user"], s["password"])
            server.send_message(msg)
        log.info("mail sent", extra={"event": "mail", "path": kind})
        return {"delivered": True}
    if settings.prod:
        raise RuntimeError("البريد غير مهيّأ في الإنتاج (MABANIQ_SMTP_HOST/FROM)")
    p = outbox_dir() / f"{time.time_ns()}-{secrets.token_hex(3)}.json"  # monotonic name: sorted() = chronological
    p.write_text(json.dumps({"to": to, "subject": subject, "text": text, "link": link, "label": label, "kind": kind,
                             "attachments": [{"name": n, "bytes": len(b), "mime": m} for n, b, m in attachments or []],
                             "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("mail to outbox", extra={"event": "mail_outbox", "path": kind})
    return {"delivered": False, "outbox": str(p), "echo": link if settings.mail_echo else None}
