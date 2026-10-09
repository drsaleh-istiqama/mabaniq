"""مبانيك — الهوية والصلاحيات.

- كلمات مرور PBKDF2-SHA256 (٢٠٠ ألف دورة) + سياسة قوة + إلزام بالتغيير عند أول دخول
- تحقق ثنائي TOTP (RFC 6238) مع منع إعادة استخدام الرمز، وإلزامي للمدير والمالية في بيئة الإنتاج
- جلسات بكوكي HttpOnly/Secure/SameSite، وحد ٥ جلسات لكل مستخدم
- قفل محاولات الدخول محفوظ في قاعدة البيانات (لا يُمسح بإعادة التشغيل)
- كل مطوّر (Tenant) له مستخدموه وجلساته في قاعدة بياناته المعزولة
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from .db import TENANT, audit_insert, connect, data_dir, init

COOKIE = "mbq_session"
TENANT_COOKIE = "mbq_tenant"
CSRF_COOKIE = "mbq_csrf"  # 0.5.0 — M7: رمز CSRF مزدوج (كوكي + ترويسة X-CSRF-Token)
CSRF_HEADER = "x-csrf-token"
SESSION_HOURS = 12

ROLES = {
    "admin": "مدير عام",
    "sales": "مبيعات",
    "finance": "مالية وتحصيل",
    "engineer": "مهندس موقع",
    "broker": "وسيط عقاري",
    "investor": "مستثمر / ممول",
    "customer": "عميل",
}
ALL_STAFF = {"view", "inventory", "book", "leads", "finance", "confirm", "decide", "construction", "approve_ipc",
             "service", "admin", "audit", "land", "permits", "kyc", "brokers", "invoices", "handover", "oa",
             "leasing", "market", "reports", "notify", "users", "docs"}
PERMS = {
    "admin": ALL_STAFF,
    "sales": {"view", "inventory", "book", "leads", "service", "kyc", "brokers", "market", "notify", "docs"},
    "finance": {"view", "inventory", "finance", "confirm", "decide", "construction", "service", "audit", "kyc",
                "invoices", "oa", "leasing", "reports", "notify", "brokers", "land", "docs"},
    "engineer": {"view", "construction", "permits", "handover", "docs"},
    "broker": {"broker_portal"},
    "investor": {"reports"},
    "customer": {"portal"},
}
TWO_FA_REQUIRED = {"admin", "finance"}

USERS_SQL = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, role TEXT, pw TEXT, customer_id INTEGER, broker_id INTEGER,
  active INTEGER DEFAULT 1, must_change INTEGER DEFAULT 0, totp_secret TEXT, totp_enabled INTEGER DEFAULT 0,
  totp_last INTEGER DEFAULT 0, pw_changed TEXT);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), expires REAL);
CREATE TABLE IF NOT EXISTS auth_failures(k TEXT, at REAL);
CREATE INDEX IF NOT EXISTS ix_auth_failures ON auth_failures(k, at);
"""
USER_MIGR = ["broker_id INTEGER", "must_change INTEGER DEFAULT 0", "totp_secret TEXT", "totp_enabled INTEGER DEFAULT 0",
             "totp_last INTEGER DEFAULT 0", "pw_changed TEXT"]

DEMO = [  # username, name, role
    ("admin", "مدير المنصة", "admin"),
    ("sales", "موظف المبيعات", "sales"),
    ("finance", "المحاسب", "finance"),
    ("engineer", "مهندس الموقع", "engineer"),
    ("investor1", "ممثل البنك الممول", "investor"),
]


def prod() -> bool:
    return os.environ.get("MABANIQ_ENV", "demo") == "prod"


def new_csrf() -> str:
    return secrets.token_urlsafe(32)


def csrf_ok(request: Request) -> bool:
    cookie, header = request.cookies.get(CSRF_COOKIE, ""), request.headers.get(CSRF_HEADER, "")
    return bool(cookie) and len(cookie) >= 32 and hmac.compare_digest(cookie, header)


# ---------------------------------------------------------------- كلمات المرور
def hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        s, h = stored.split("$")
        return hmac.compare_digest(hash_pw(pw, bytes.fromhex(s)).split("$")[1], h)
    except (ValueError, AttributeError):
        return False


COMMON = {"password", "12345678", "123456789", "1234567890", "qwerty123", "mabaniq123", "admin12345", "password123",
          "p@ssw0rd123", "welcome123"}


def policy_errors(pw: str, username: str) -> str | None:
    if len(pw) < 10:
        return "كلمة المرور يجب ألا تقل عن ١٠ أحرف"
    if not re.search(r"[A-Za-z\u0600-\u06FF]", pw) or not re.search(r"\d", pw):
        return "كلمة المرور يجب أن تجمع بين الحروف والأرقام"
    if username.lower() in pw.lower() or pw.lower() in COMMON:
        return "كلمة المرور ضعيفة أو قريبة من اسم المستخدم"
    return None


def temp_password() -> str:
    return secrets.token_urlsafe(10) + str(secrets.randbelow(10))


# ---------------------------------------------------------------- TOTP
def totp_at(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def totp_verify(secret: str, code: str, last: int = 0) -> int | None:
    """يعيد رقم العدّاد إن صح الرمز (نافذة ±٣٠ ثانية)، ويرفض الرمز المستخدم سابقًا."""
    if not secret or not re.fullmatch(r"\d{6}", code or ""):
        return None
    now = int(time.time() // 30)
    for ctr in (now - 1, now, now + 1):
        if ctr > (last or 0) and hmac.compare_digest(totp_at(secret, ctr), code):
            return ctr
    return None


def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


# ---------------------------------------------------------------- الحسابات التجريبية
def creds_file() -> Path:
    t = TENANT.get()
    return data_dir() / ("credentials.json" if t == "jadwa" else f"credentials_{t}.json")


def ensure_schema(c) -> None:
    if getattr(c, "dialect", "sqlite") == "postgres":
        return
    have = c.columns("users")
    if have:
        for col in USER_MIGR:
            if col.split()[0] not in have:
                c.execute(f"ALTER TABLE users ADD COLUMN {col}")
    c.executescript(USERS_SQL)


def ensure_users(c, customers: list[tuple[int, str]], brokers: list[tuple[int, str]] = ()) -> None:
    """ينشئ حسابات العرض بكلمات مرور عشوائية في data/credentials*.json (صلاحية 600)،
    ويُلزم كل حساب بتغيير كلمة المرور عند أول دخول (MABANIQ_FORCE_PW_CHANGE=1 افتراضيًا)."""
    ensure_schema(c)
    f = creds_file()
    if prod():
        # 0.5.0 — M6: في الإنتاج لا حسابات عرض ولا ملف كلمات مرور؛ حساب مدير واحد بكلمة مؤقتة في ملف يُحذف عند أول تغيير
        if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            pw = temp_password()
            c.execute("INSERT INTO users(username,name,role,pw,must_change) VALUES(?,?,?,?,1)", ("admin", "مدير المنصة", "admin", hash_pw(pw)))
            c.commit()
            fa = data_dir() / "first-admin-password.txt"
            fa.write_text(f"admin: {pw}" + chr(10) + "(يُحذف هذا الملف تلقائيًا عند أول تغيير لكلمة المرور)" + chr(10))
            os.chmod(fa, 0o600)
        return
    creds = json.loads(f.read_text()) if f.exists() else {}
    rotate = not f.exists()  # الملف مفقود (قاعدة PostgreSQL قائمة من تشغيل سابق مثلًا) ⟵ تُدوَّر كلمات مرور العرض وتُكتب من جديد
    force = 1 if os.environ.get("MABANIQ_FORCE_PW_CHANGE", "1") == "1" else 0
    wanted = [(u, n, r, None, None) for u, n, r in DEMO]
    wanted += [(f"client{i + 1}", n, "customer", cid, None) for i, (cid, n) in enumerate(customers)]
    wanted += [(f"broker{i + 1}", n, "broker", None, bid) for i, (bid, n) in enumerate(brokers)]
    changed = False
    for un, name, role, cust, brk in wanted:
        if not c.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone():
            pw = creds.get(un) or temp_password()
            c.execute("INSERT INTO users(username,name,role,pw,customer_id,broker_id,must_change) VALUES(?,?,?,?,?,?,?)",
                      (un, name, role, hash_pw(pw), cust, brk, force))
            creds[un] = pw
            changed = True
        else:
            c.execute("UPDATE users SET customer_id=?, broker_id=?, name=? WHERE username=?", (cust, brk, name, un))
            if rotate:
                pw = temp_password()
                c.execute("UPDATE users SET pw=?, must_change=? WHERE username=?", (hash_pw(pw), force, un))
                creds[un] = pw
                changed = True
    c.commit()
    if changed:
        f.write_text(json.dumps(creds, ensure_ascii=False, indent=1))
        os.chmod(f, 0o600)


# ---------------------------------------------------------------- قفل المحاولات (دائم)
def _fail_count(c, k: str, window: int) -> int:
    return c.execute("SELECT COUNT(*) FROM auth_failures WHERE k=? AND at>?", (k, time.time() - window)).fetchone()[0]


def _fail(c, *keys):
    for k in keys:
        c.execute("INSERT INTO auth_failures VALUES(?,?)", (k, time.time()))
    c.execute("DELETE FROM auth_failures WHERE at<?", (time.time() - 86400,))
    c.commit()


DUMMY = hash_pw("dummy-password-x1")
TRUST_PROXY = os.environ.get("MABANIQ_TRUST_PROXY", "1") == "1"


def client_ip(request: Request) -> str:
    """لا نثق برأس cf-connecting-ip إلا إذا جاء الطلب من الوكيل المحلي (النفق)."""
    peer = request.client.host if request.client else "?"
    if TRUST_PROXY and peer in ("127.0.0.1", "::1"):
        return request.headers.get("cf-connecting-ip") or peer
    return peer


_schema_ok: set = set()


def conn():
    c = connect()
    t = TENANT.get()
    if t not in _schema_ok:
        init(c)
        ensure_schema(c)
        c.commit()
        _schema_ok.add(t)
    return c


def login(username: str, pw: str, ip: str, otp: str | None = None) -> tuple[str, dict]:
    username = username.strip().lower()
    c = conn()
    try:
        key, acct = f"{ip}:{username}", f"*:{username}"
        if _fail_count(c, key, 300) >= 5:
            raise HTTPException(429, "محاولات كثيرة. حاول بعد ٥ دقائق.")
        if _fail_count(c, acct, 900) >= 20:
            raise HTTPException(429, "الحساب مقفل مؤقتًا بسبب محاولات كثيرة. حاول بعد ١٥ دقيقة.")
        u = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if not u:
            check_pw(pw, DUMMY)  # توقيت متقارب لمنع كشف وجود الحساب
        if not u or not check_pw(pw, u["pw"]):
            _fail(c, key, acct)
            raise HTTPException(401, "اسم المستخدم أو كلمة المرور غير صحيحة")
        if u["totp_enabled"]:
            if not otp:
                raise HTTPException(401, "OTP_REQUIRED")
            ctr = totp_verify(u["totp_secret"], otp, u["totp_last"])
            if ctr is None:
                _fail(c, key, acct)
                raise HTTPException(401, "رمز التحقق غير صحيح أو مستخدم سابقًا")
            c.execute("UPDATE users SET totp_last=? WHERE id=?", (ctr, u["id"]))
        c.execute("DELETE FROM auth_failures WHERE k=?", (key,))
        token = secrets.token_urlsafe(32)
        c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        c.execute("""DELETE FROM sessions WHERE user_id=? AND token_hash NOT IN
                     (SELECT token_hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT 4)""", (u["id"], u["id"]))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), u["id"], time.time() + SESSION_HOURS * 3600))
        audit_insert(c, u["name"], "تسجيل دخول", f"{u['username']} من {ip}{' · بتحقق ثنائي' if u['totp_enabled'] else ''}")
        c.commit()
        return token, public(u)
    finally:
        c.close()


def issue_session(username: str) -> str:
    """للاختبارات والإدارة المحلية فقط (غير معروضة عبر الـ API)."""
    c = conn()
    try:
        u = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), u["id"], time.time() + SESSION_HOURS * 3600))
        c.commit()
        return token
    finally:
        c.close()


def logout(token: str | None) -> None:
    if token:
        c = conn()
        c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        c.commit()
        c.close()


def kill_sessions(c, user_id: int, keep_hash: str | None = None) -> None:
    c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (user_id, keep_hash or ""))


def public(u) -> dict:
    needs_2fa = prod() and u["role"] in TWO_FA_REQUIRED and not u["totp_enabled"]
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"],
            "role_label": ROLES[u["role"]], "perms": sorted(PERMS[u["role"]]), "customer_id": u["customer_id"],
            "broker_id": u["broker_id"], "must_change": bool(u["must_change"]), "totp_enabled": bool(u["totp_enabled"]),
            "needs_2fa": needs_2fa, "tenant": TENANT.get()}


def token_hash(request: Request) -> str | None:
    t = request.cookies.get(COOKIE)
    return hashlib.sha256(t.encode()).hexdigest() if t else None


def session_user(request: Request) -> dict | None:
    th = token_hash(request)
    if not th:
        return None
    c = conn()
    try:
        row = c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                           WHERE s.token_hash=? AND s.expires>? AND u.active=1""", (th, time.time())).fetchone()
        return public(row) if row else None
    finally:
        c.close()


GATE_EXEMPT = {"/api/me", "/api/auth/password", "/api/auth/logout", "/api/auth/2fa/setup", "/api/auth/2fa/enable"}


def current(request: Request) -> dict:
    u = session_user(request)
    if not u:
        raise HTTPException(401, "يلزم تسجيل الدخول")
    if request.url.path not in GATE_EXEMPT:
        if u["must_change"]:
            raise HTTPException(403, "MUST_CHANGE_PASSWORD")
        if u["needs_2fa"]:
            raise HTTPException(403, "MUST_ENABLE_2FA")
    request.state.user = u
    return u


def need(perm: str):
    def dep(u: dict = Depends(current)) -> dict:
        if perm not in u["perms"]:
            raise HTTPException(403, "ليست لديك صلاحية لهذا الإجراء")
        return u
    return dep


def need_any(*perms: str):
    def dep(u: dict = Depends(current)) -> dict:
        if not set(perms) & set(u["perms"]):
            raise HTTPException(403, "ليست لديك صلاحية لهذا الإجراء")
        return u
    return dep
