"""Mabaniq — external identity (0.10.0): sign in with username *or* e-mail, one-time e-mail sign-in links, password
recovery by e-mail, and Google sign-in (OpenID Connect, authorization code).

Rules that do not bend:
* **No account is ever created by these flows.** Admins create staff accounts; customer accounts come from the customer
  file. An external identity only *matches* an existing active account — Google by its `sub`, or by a Google-verified
  e-mail equal to the account's e-mail (the match then links the `sub`).
* Every link is a random token stored **hashed**, single-use, short-lived (reset 30 min, sign-in 15 min).
* Requests for a recovery or sign-in link answer identically whether the identifier exists or not (no enumeration).
* Accounts protected by TOTP cannot be entered by a link or by Google alone (the second factor would be bypassed).
* Google `state` is an HMAC-signed blob bound to the starting browser through an HttpOnly cookie scoped to the OAuth path;
  the `id_token` is verified by Google's tokeninfo endpoint and then checked for aud · iss · exp · nonce · email_verified.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import auth as A
from . import mail, pii
from .config import settings
from .db import TENANT, audit_insert, valid_tenant

router = APIRouter()
RESET_MINUTES = 30
MAGIC_MINUTES = 15
OAUTH_MINUTES = 10
OAUTH_COOKIE = "mbq_oauth"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
TENANT_RE = r"^[a-z][a-z0-9-]{1,30}$"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


# ---------------------------------------------------------------- helpers
def norm_email(e: str | None) -> str:
    return (e or "").strip().lower()


def _secret() -> bytes:
    return pii.secret("auth.key", "MABANIQ_AUTH_SECRET").encode()


def sign(kind: str, payload: dict, ttl: int) -> str:
    body = json.dumps({**payload, "k": kind, "exp": int(time.time()) + ttl}, separators=(",", ":"), ensure_ascii=False).encode()
    b = base64.urlsafe_b64encode(body).decode().rstrip("=")
    return b + "." + hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]


def verify(kind: str, blob: str | None) -> dict | None:
    if not blob or "." not in blob or len(blob) > 2000:
        return None
    b, mac = blob.rsplit(".", 1)
    if not hmac.compare_digest(mac, hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]):
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    except Exception:  # noqa: BLE001
        return None
    if d.get("k") != kind or d.get("exp", 0) < time.time():
        return None
    return d


def issue_token(c, user_id: int, kind: str, minutes: int, ip: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    c.execute("DELETE FROM auth_tokens WHERE expires<? OR used=1", (now - 86400,))
    c.execute("INSERT INTO auth_tokens(token_hash,user_id,kind,expires,created,ip) VALUES(?,?,?,?,?,?)",
              (hashlib.sha256(token.encode()).hexdigest(), user_id, kind, now + minutes * 60, now, (ip or "")[:64]))
    return token


def consume_token(c, token: str, kind: str):
    """Single use: returns the row and marks it used, or None."""
    if not token or len(token) > 200:
        return None
    h = hashlib.sha256(token.encode()).hexdigest()
    row = c.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND kind=? AND used=0 AND expires>?", (h, kind, time.time())).fetchone()
    if not row:
        return None
    c.execute("UPDATE auth_tokens SET used=1 WHERE token_hash=?", (h,))
    return row


def find_user(c, identifier: str):
    ident = (identifier or "").strip().lower()
    return c.execute("SELECT * FROM users WHERE active=1 AND (username=? OR lower(email)=?)", (ident, ident)).fetchone()


def public_url(request: Request) -> str:
    if settings.public_url:
        return settings.public_url.rstrip("/")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    scheme = "https" if (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https") else "http"
    return f"{scheme}://{host}"


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def set_session_cookies(response: Response, request: Request, token: str, tenant: str) -> None:
    sec = _secure(request)
    age = A.SESSION_HOURS * 3600
    response.set_cookie(A.COOKIE, token, httponly=True, samesite="lax", secure=sec, max_age=age, path="/")
    response.set_cookie(A.TENANT_COOKIE, tenant, httponly=True, samesite="lax", secure=sec, max_age=age, path="/")
    response.set_cookie(A.CSRF_COOKIE, A.new_csrf(), httponly=False, samesite="lax", secure=sec, max_age=age, path="/")


def home(role: str) -> str:
    return "/app" if role == "customer" else "/broker" if role == "broker" else "/"


def google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def methods() -> dict:
    return {"password": True, "email_login": True, "email_link": mail.available(), "forgot": mail.available(), "google": google_enabled(),
            "mail_mode": "smtp" if mail.configured() else ("outbox" if mail.outbox_mode() else "off")}


def _mail_or_503():
    if not mail.available():
        raise HTTPException(503, "خدمة البريد غير مهيّأة على هذا الخادم — تواصل مع مدير المنصة")


def _tenant(t: str) -> None:
    if not valid_tenant(t):
        raise HTTPException(404, "المطوّر غير معروف")
    TENANT.set(t)


# ---------------------------------------------------------------- public: methods
@router.get("/api/auth/methods")
def auth_methods():
    return methods()


# ---------------------------------------------------------------- password recovery
class ForgotIn(BaseModel):
    identifier: str = Field(min_length=2, max_length=120)  # username or e-mail
    tenant: str = Field(default="jadwa", max_length=32, pattern=TENANT_RE)


SENT = {"sent": True, "message": "إن كان الحساب موجودًا وله بريد مسجَّل، فقد وصلته رسالة برابط صالح لمدة محدودة."}


@router.post("/api/auth/password/forgot")
def password_forgot(body: ForgotIn, request: Request):
    _tenant(body.tenant)
    _mail_or_503()
    c = A.conn()
    try:
        u = find_user(c, body.identifier)
        out = dict(SENT)
        if u and u["email"]:
            ip = A.client_ip(request)
            token = issue_token(c, u["id"], "reset", RESET_MINUTES, ip)
            link = f"{public_url(request)}/login?reset={token}&t={body.tenant}"
            res = mail.send(u["email"], "استعادة كلمة المرور — مبانيك",
                            f"مرحبًا {u['name']}،\n\nطُلب تعيين كلمة مرور جديدة لحسابك ({u['username']}). افتح الرابط التالي خلال {RESET_MINUTES} دقيقة لاختيار كلمة مرور جديدة. الرابط يعمل مرة واحدة.",
                            link, "تعيين كلمة مرور جديدة", kind="reset")
            audit_insert(c, u["name"], "طلب استعادة كلمة المرور", f"{u['username']} من {ip}")
            if res.get("echo"):
                out["demo_link"] = res["echo"]
        else:
            A.check_pw("x", A.DUMMY)  # comparable timing whether or not the account exists
        c.commit()
        return out
    finally:
        c.close()


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new: str = Field(min_length=10, max_length=200)
    tenant: str = Field(default="jadwa", max_length=32, pattern=TENANT_RE)


@router.post("/api/auth/password/reset")
def password_reset(body: ResetIn, request: Request):
    _tenant(body.tenant)
    c = A.conn()
    try:
        row = consume_token(c, body.token, "reset")
        u = c.execute("SELECT * FROM users WHERE id=? AND active=1", (row["user_id"],)).fetchone() if row else None
        if not u:
            c.commit()
            raise HTTPException(400, "الرابط غير صالح أو منتهٍ — اطلب رابطًا جديدًا")
        err = A.policy_errors(body.new, u["username"])
        if err:
            c.rollback()
            raise HTTPException(400, err)
        c.execute("UPDATE users SET pw=?, must_change=0, pw_changed=? WHERE id=?", (A.hash_pw(body.new), time.strftime("%Y-%m-%dT%H:%M:%S"), u["id"]))
        A.kill_sessions(c, u["id"])
        audit_insert(c, u["name"], "تعيين كلمة مرور عبر رابط الاستعادة", f"{u['username']} من {A.client_ip(request)} · أُنهيت كل الجلسات")
        c.commit()
        return {"ok": True, "username": u["username"]}
    finally:
        c.close()


# ---------------------------------------------------------------- e-mail sign-in link
class MagicIn(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    tenant: str = Field(default="jadwa", max_length=32, pattern=TENANT_RE)


@router.post("/api/auth/email/request")
def email_link_request(body: MagicIn, request: Request):
    _tenant(body.tenant)
    _mail_or_503()
    email = norm_email(body.email)
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "صيغة البريد غير صحيحة")
    c = A.conn()
    try:
        u = c.execute("SELECT * FROM users WHERE active=1 AND lower(email)=?", (email,)).fetchone()
        out = dict(SENT)
        if u and not u["totp_enabled"]:
            ip = A.client_ip(request)
            token = issue_token(c, u["id"], "magic", MAGIC_MINUTES, ip)
            link = f"{public_url(request)}/auth/email/{token}?t={body.tenant}"
            res = mail.send(u["email"], "رابط الدخول — مبانيك",
                            f"مرحبًا {u['name']}،\n\nهذا رابط دخول لمرة واحدة إلى حسابك ({u['username']}) صالح لمدة {MAGIC_MINUTES} دقيقة. إن لم تطلبه فتجاهل الرسالة.",
                            link, "الدخول إلى مبانيك", kind="magic")
            audit_insert(c, u["name"], "طلب رابط دخول بريدي", f"{u['username']} من {ip}")
            if res.get("echo"):
                out["demo_link"] = res["echo"]
        else:
            A.check_pw("x", A.DUMMY)
        c.commit()
        return out
    finally:
        c.close()


@router.get("/auth/email/{token}", include_in_schema=False)
def email_link_login(token: str, request: Request, t: str = "jadwa"):
    if not valid_tenant(t):
        return RedirectResponse("/login?err=link", 303)
    TENANT.set(t)
    c = A.conn()
    try:
        row = consume_token(c, token, "magic")
        u = c.execute("SELECT * FROM users WHERE id=? AND active=1", (row["user_id"],)).fetchone() if row else None
        if not u:
            c.commit()
            return RedirectResponse("/login?err=link", 303)
        if u["totp_enabled"]:
            c.commit()
            return RedirectResponse("/login?err=link-2fa", 303)
        ip, ua = A.client_ip(request), request.headers.get("user-agent", "")
        session = A._new_session(c, u["id"], ip, ua)
        c.execute("UPDATE users SET email_verified=1 WHERE id=?", (u["id"],))
        audit_insert(c, u["name"], "تسجيل دخول برابط بريدي", f"{u['username']} من {ip} · {A._ua_label(ua)}")
        c.commit()
        resp = RedirectResponse(home(u["role"]), 303)
        set_session_cookies(resp, request, session, t)
        return resp
    finally:
        c.close()


# ---------------------------------------------------------------- Google (OpenID Connect)
def google_exchange(code: str, redirect_uri: str) -> dict:
    """Authorization code → id_token → Google-verified claims. Replaced in tests."""
    import httpx
    with httpx.Client(timeout=15) as h:
        tok = h.post(GOOGLE_TOKEN, data={"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                                         "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        tok.raise_for_status()
        idt = tok.json().get("id_token", "")
        if not idt:
            raise RuntimeError("no id_token")
        info = h.get(GOOGLE_TOKENINFO, params={"id_token": idt})
        info.raise_for_status()
        return info.json()


def _oauth_cookie(resp: Response, request: Request, value: str, clear: bool = False) -> None:
    resp.set_cookie(OAUTH_COOKIE, value, httponly=True, samesite="lax", secure=_secure(request), max_age=0 if clear else OAUTH_MINUTES * 60, path="/auth/google")


@router.get("/auth/google/start", include_in_schema=False)
def google_start(request: Request, t: str = "jadwa", link: str = "0"):
    if not google_enabled():
        return JSONResponse({"detail": "الدخول عبر Google غير مفعّل على هذا الخادم"}, status_code=404)
    if not valid_tenant(t):
        return RedirectResponse("/login?err=google", 303)
    TENANT.set(t)
    link_uid = 0
    if link == "1":
        me = A.session_user(request)
        if not me:
            return RedirectResponse("/login?err=link-session", 303)
        link_uid = me["id"]
    nonce, bind = secrets.token_urlsafe(16), secrets.token_urlsafe(24)
    state = sign("oauth", {"n": nonce, "t": t, "b": hashlib.sha256(bind.encode()).hexdigest(), "link": link_uid}, OAUTH_MINUTES * 60)
    params = {"client_id": settings.google_client_id, "redirect_uri": f"{public_url(request)}/auth/google/callback", "response_type": "code",
              "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account", "access_type": "online"}
    resp = RedirectResponse(GOOGLE_AUTH + "?" + urlencode(params), 303)
    _oauth_cookie(resp, request, bind)
    return resp


def _fail(request: Request, code: str) -> Response:
    resp = RedirectResponse(f"/login?err={code}", 303)
    _oauth_cookie(resp, request, "", clear=True)
    return resp


@router.get("/auth/google/callback", include_in_schema=False)
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    if not google_enabled():
        return _fail(request, "google")
    if error:
        return _fail(request, "google-denied")
    st = verify("oauth", state)
    bind = request.cookies.get(OAUTH_COOKIE, "")
    if not st or not code or not bind or not hmac.compare_digest(st.get("b", ""), hashlib.sha256(bind.encode()).hexdigest()):
        return _fail(request, "state")  # wrong browser or stale state — before any call to Google
    t = st.get("t", "")
    if not valid_tenant(t):
        return _fail(request, "state")
    TENANT.set(t)
    try:
        info = google_exchange(code, f"{public_url(request)}/auth/google/callback")
    except Exception as e:  # noqa: BLE001
        A.log.warning("google exchange failed", extra={"event": "google_error", "path": type(e).__name__}) if hasattr(A, "log") else None
        return _fail(request, "google")
    if info.get("aud") != settings.google_client_id or info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        return _fail(request, "aud")
    if int(info.get("exp", 0)) < time.time() or info.get("nonce") != st.get("n"):
        return _fail(request, "nonce")
    if str(info.get("email_verified", "")).lower() != "true" or not info.get("email"):
        return _fail(request, "unverified")
    email, sub = norm_email(info["email"]), str(info.get("sub", ""))[:64]
    if not sub:
        return _fail(request, "google")
    c = A.conn()
    try:
        ip, ua = A.client_ip(request), request.headers.get("user-agent", "")
        if st.get("link"):
            me = A.session_user(request)
            if not me or me["id"] != st["link"]:
                return _fail(request, "link-session")
            if c.execute("SELECT 1 FROM users WHERE google_sub=? AND id!=?", (sub, me["id"])).fetchone():
                return _fail(request, "google-taken")
            c.execute("UPDATE users SET google_sub=?, email=COALESCE(email, ?), email_verified=CASE WHEN lower(COALESCE(email, ?))=? THEN 1 ELSE email_verified END WHERE id=?",
                      (sub, email, email, email, me["id"]))
            audit_insert(c, me["name"], "ربط حساب Google", f"{me['username']} · {email}")
            c.commit()
            resp = RedirectResponse("/#adm", 303)
            _oauth_cookie(resp, request, "", clear=True)
            return resp
        u = c.execute("SELECT * FROM users WHERE active=1 AND google_sub=?", (sub,)).fetchone()
        linked_now = False
        if not u:
            u = c.execute("SELECT * FROM users WHERE active=1 AND lower(email)=? AND google_sub IS NULL", (email,)).fetchone()
            linked_now = bool(u)
        if not u:
            audit_insert(c, "النظام", "محاولة دخول Google لهوية غير معروفة", f"{email} من {ip}")
            c.commit()
            return _fail(request, "google-unknown")
        if u["totp_enabled"]:
            c.commit()
            return _fail(request, "link-2fa")
        if linked_now:
            c.execute("UPDATE users SET google_sub=?, email_verified=1 WHERE id=?", (sub, u["id"]))
        session = A._new_session(c, u["id"], ip, ua)
        audit_insert(c, u["name"], "تسجيل دخول عبر Google", f"{u['username']} ({email}) من {ip}{' · رُبط الحساب' if linked_now else ''} · {A._ua_label(ua)}")
        c.commit()
        resp = RedirectResponse(home(u["role"]), 303)
        set_session_cookies(resp, request, session, t)
        _oauth_cookie(resp, request, "", clear=True)
        return resp
    finally:
        c.close()


# ---------------------------------------------------------------- my identity (any signed-in user) and admin
class EmailIn(BaseModel):
    email: str = Field(max_length=120)


@router.get("/api/me/identity")
def my_identity(u=Depends(A.current)):
    c = A.conn()
    try:
        row = c.execute("SELECT email, email_verified, google_sub FROM users WHERE id=?", (u["id"],)).fetchone()
        return {"email": row["email"], "email_verified": bool(row["email_verified"]), "google_linked": bool(row["google_sub"]), "methods": methods(),
                "totp_enabled": u["totp_enabled"]}
    finally:
        c.close()


def _set_email(c, uid: int, email: str, actor: str, who: str) -> dict:
    email = norm_email(email)
    if email and not EMAIL_RE.match(email):
        raise HTTPException(400, "صيغة البريد غير صحيحة")
    if email and c.execute("SELECT 1 FROM users WHERE lower(email)=? AND id!=?", (email, uid)).fetchone():
        raise HTTPException(409, "هذا البريد مسجَّل لحساب آخر")
    c.execute("UPDATE users SET email=?, email_verified=0 WHERE id=?", (email or None, uid))
    audit_insert(c, actor, "تحديث البريد الإلكتروني", f"{who} ⟵ {email or '—'}")
    c.commit()
    return {"email": email or None, "email_verified": False}


@router.post("/api/me/email")
def my_email(body: EmailIn, u=Depends(A.current)):
    c = A.conn()
    try:
        return _set_email(c, u["id"], body.email, u["name"], u["username"])
    finally:
        c.close()


@router.post("/api/me/google/unlink")
def my_google_unlink(u=Depends(A.current)):
    c = A.conn()
    try:
        c.execute("UPDATE users SET google_sub=NULL WHERE id=?", (u["id"],))
        audit_insert(c, u["name"], "فصل حساب Google", u["username"])
        c.commit()
        return {"google_linked": False}
    finally:
        c.close()


@router.post("/api/users/{uid}/email")
def admin_set_email(uid: int, body: EmailIn, u=Depends(A.need("users"))):
    c = A.conn()
    try:
        t = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if not t:
            raise HTTPException(404, "المستخدم غير موجود")
        return _set_email(c, uid, body.email, u["name"], t["username"])
    finally:
        c.close()
