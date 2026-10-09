"""مبانيك — حماية البيانات الشخصية والأسرار (0.5.0 — M5/M6).

- تشفير حقول الهوية الحساسة في القاعدة (رقم الهوية، تاريخ الميلاد، هوية المستأجر) بـFernet (AES-128-CBC + HMAC).
- المفتاح من متغير البيئة MABANIQ_PII_KEY (إلزامي في الإنتاج)، أو ملف data/secrets/pii.key يُولَّد تلقائيًا في بيئة العرض.
- الأسرار الأخرى (سر توقيع بوابة الدفع) بالآلية نفسها: بيئة أولًا ثم ملف بصلاحية 600 — ولا تُخزَّن في قاعدة البيانات أبدًا.
- القيم المشفَّرة تُسبق بـ enc:v1: فيبقى الترحيل التدريجي آمنًا: النص القديم يُقرأ كما هو ويُشفَّر عند أول init.
"""
import os
import secrets as _secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .db import data_dir

PREFIX = "enc:v1:"
_cache: dict = {}


def prod() -> bool:
    return os.environ.get("MABANIQ_ENV", "demo") == "prod"


def secrets_dir() -> Path:
    d = data_dir() / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def secret(name: str, env: str, generate=lambda: _secrets.token_hex(32)) -> str:
    """يعيد سرًا باسمه: من البيئة، وإلا من ملف data/secrets/<name> (يُولَّد في العرض فقط)."""
    if env in os.environ and os.environ[env]:
        return os.environ[env]
    if name in _cache:
        return _cache[name]
    f = secrets_dir() / name
    if f.exists():
        v = f.read_text().strip()
    elif prod():
        raise RuntimeError(f"السر {env} مطلوب في بيئة الإنتاج (متغير بيئة أو الملف {f})")
    else:
        v = generate()
        f.write_text(v)
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    _cache[name] = v
    return v


def _fernet() -> Fernet:
    if "fernet" not in _cache:
        _cache["fernet"] = Fernet(secret("pii.key", "MABANIQ_PII_KEY", lambda: Fernet.generate_key().decode()).encode())
    return _cache["fernet"]


def enc(value):
    """يشفّر نصًا؛ None والفارغ والمشفَّر سلفًا تعود كما هي."""
    if value is None or value == "" or (isinstance(value, str) and value.startswith(PREFIX)):
        return value
    return PREFIX + _fernet().encrypt(str(value).encode()).decode()


def dec(value):
    if not value or not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return "⟨تعذّر فك التشفير — مفتاح مختلف⟩"


def mask(value, keep: int = 4) -> str | None:
    """إخفاء جزئي للعرض في القوائم: آخر ٤ خانات فقط."""
    v = dec(value)
    if not v:
        return v
    return "•" * max(2, len(v) - keep) + v[-keep:]


ENCRYPTED_COLUMNS = {"customers": ("id_number", "dob"), "tenants_l": ("id_number",)}


def encrypt_existing(c) -> int:
    """ترحيل: يشفّر أي قيمة نصية ما زالت مكشوفة في الأعمدة الحساسة (آمن للتكرار)."""
    n = 0
    for table, cols in ENCRYPTED_COLUMNS.items():
        have = c.columns(table)
        for col in cols:
            if col not in have:
                continue
            for r in c.execute(f"SELECT id AS rid, {col} AS v FROM {table} WHERE {col} IS NOT NULL AND {col}!='' AND {col} NOT LIKE 'enc:v1:%'").fetchall():
                c.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (enc(r["v"]), r["rid"]))
                n += 1
    return n


def prod_checks() -> None:
    """يُستدعى عند الإقلاع: في الإنتاج لا تشغيل بلا أسرار صريحة."""
    if not prod():
        return
    missing = [e for e in ("MABANIQ_PII_KEY", "MABANIQ_PAY_SECRET") if not os.environ.get(e) and not (secrets_dir() / {"MABANIQ_PII_KEY": "pii.key", "MABANIQ_PAY_SECRET": "pay_secret"}[e]).exists()]
    if missing:
        raise RuntimeError("لا يعمل مبانيك في الإنتاج بلا الأسرار: " + ", ".join(missing))
