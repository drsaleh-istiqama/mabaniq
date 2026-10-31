"""Mabaniq 0.29.0 — the policy and regulation register (governance).

A policy is a numbered set of articles with an owner, an effective date and a review period. Every change is a new *version* (a new row, `supersedes_id` pointing at the one it
replaces): a draft is prepared by one person and approved by a different one, and approving it retires the version that was in force. Staff read the approved text and acknowledge it
once per version; the administrator sees who has and has not. Nothing is deleted — a dropped draft is retired, an old version stays as history.

Two permissions, both core (never switched off with a module): `policies` — read the approved policies and acknowledge them (every staff role and the employee portal); `policies_admin` —
prepare, approve and retire (the general manager and the HR officer). A user without `policies_admin` never sees a draft or a retired version.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import PERMS, need
from .common import act_as, audit, db, now_s, rows, today
from .modules import one

router = APIRouter()
CATEGORIES = {"hr": "الموارد البشرية", "governance": "الحوكمة", "finance": "المالية", "leasing": "التأجير", "sales": "المبيعات", "operations": "التشغيل والصيانة", "compliance": "الامتثال"}
STATUS_AR = {"draft": "مسودة", "approved": "معتمدة", "retired": "موقوفة"}
CODE_RE = r"^[A-Za-z][A-Za-z0-9_-]{1,29}$"
Cat = Literal["hr", "governance", "finance", "leasing", "sales", "operations", "compliance"]


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid")
    no: str = Field(default="", max_length=12)
    title: str = Field(default="", max_length=120)
    text: str = Field(min_length=2, max_length=4000)


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=CODE_RE)
    title: str = Field(min_length=3, max_length=160)
    category: Cat
    owner_role: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=600)
    articles: list[Article] = Field(min_length=1, max_length=40)
    basis: str = Field(default="", max_length=400)
    review_months: int = Field(default=12, ge=1, le=60)
    ack_required: bool = True


class PolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=3, max_length=160)
    category: Cat | None = None
    owner_role: str | None = Field(default=None, max_length=80)
    summary: str | None = Field(default=None, max_length=600)
    articles: list[Article] | None = Field(default=None, min_length=1, max_length=40)
    basis: str | None = Field(default=None, max_length=400)
    review_months: int | None = Field(default=None, ge=1, le=60)
    ack_required: bool | None = None


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_from: str


def _articles(items) -> str:
    out = []
    for i, a in enumerate(items, 1):
        out.append({"no": (a.no.strip() if hasattr(a, "no") else a["no"]) or str(i), "title": (a.title if hasattr(a, "title") else a["title"]).strip(),
                    "text": (a.text if hasattr(a, "text") else a["text"]).strip()})
    return json.dumps(out, ensure_ascii=False)


def _is_admin(u: dict) -> bool:
    return "policies_admin" in u["perms"]


def _review_due(effective_from: str | None, months: int) -> str | None:
    """The date the policy is due for review: its effective date plus its review period."""
    if not effective_from:
        return None
    y, m = divmod(int(effective_from[5:7]) - 1 + months, 12)
    return f"{int(effective_from[:4]) + y:04d}-{m + 1:02d}-{min(int(effective_from[8:10]), 28):02d}"


def _view(r, full: bool = False) -> dict:
    d = dict(r)
    d["category_label"] = CATEGORIES.get(d["category"], d["category"])
    d["status_label"] = STATUS_AR[d["status"]]
    d["ack_required"] = bool(d["ack_required"])
    if full:
        try:
            d["articles"] = json.loads(d.pop("body") or "[]")
        except ValueError:
            d["articles"] = []
    else:
        d.pop("body", None)
    d["review_due"] = _review_due(d.get("effective_from"), d["review_months"]) if d["status"] == "approved" else None
    d["review_overdue"] = bool(d["review_due"] and d["review_due"] < today().isoformat())
    return d


LIST_SQL = """SELECT p.id, p.code, p.title, p.category, p.owner_role, p.summary, p.version, p.status, p.effective_from, p.review_months, p.ack_required, p.basis, p.supersedes_id,
              p.created_by, p.approved_by, p.approved_at, p.body,
              (SELECT COUNT(*) FROM policy_acks a WHERE a.policy_id=p.id) ack_count,
              (SELECT COUNT(*) FROM policy_acks a WHERE a.policy_id=p.id AND a.username=?) acked
              FROM policies p"""


def _staff_targets(c) -> list[dict]:
    """Active logins whose role carries `policies`: who is expected to read an acknowledged policy."""
    roles = sorted(r for r, perms in PERMS.items() if "policies" in perms)
    ph = ",".join("?" for _ in roles)
    return rows(c.execute(f"SELECT username, name, role FROM users WHERE active=1 AND role IN ({ph}) ORDER BY name", tuple(roles)))


@router.get("/api/policies/summary")
def api_summary(u=Depends(need("policies"))):
    c = db()
    admin = _is_admin(u)
    where = "" if admin else " WHERE status='approved'"
    rs = rows(c.execute("SELECT id, code, category, status, effective_from, review_months, ack_required FROM policies" + where))
    out = {"total": len(rs), "approved": sum(r["status"] == "approved" for r in rs), "draft": sum(r["status"] == "draft" for r in rs), "retired": sum(r["status"] == "retired" for r in rs),
           "by_category": {k: sum(1 for r in rs if r["category"] == k and r["status"] != "retired") for k in CATEGORIES}}
    appr = [r for r in rs if r["status"] == "approved"]
    out["review_overdue"] = sum(1 for r in appr if (_review_due(r["effective_from"], r["review_months"]) or "9") < today().isoformat())
    mine = {r["policy_id"] for r in c.execute("SELECT policy_id FROM policy_acks WHERE username=?", (u["username"],)).fetchall()}
    out["my_pending"] = sum(1 for r in appr if r["ack_required"] and r["id"] not in mine)
    return out


@router.get("/api/policies")
def api_list(category: str | None = Query(None, pattern="^(hr|governance|finance|leasing|sales|operations|compliance)$"),
             status: str | None = Query(None, pattern="^(draft|approved|retired)$"), q: str | None = Query(None, max_length=60), u=Depends(need("policies"))):
    c = db()
    admin = _is_admin(u)
    where, args = [], [u["username"]]
    if not admin:
        where.append("p.status='approved'")
    elif status:
        where.append("p.status=?")
        args.append(status)
    if category:
        where.append("p.category=?")
        args.append(category)
    if q and q.strip():
        where.append("(p.title LIKE ? OR p.code LIKE ? OR p.summary LIKE ?)")
        args += [f"%{q.strip()}%"] * 3
    sql = LIST_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY p.category, p.code, p.version DESC"
    return [_view(r) for r in c.execute(sql, tuple(args)).fetchall()]


@router.get("/api/policies/{pid}")
def api_get(pid: int, u=Depends(need("policies"))):
    c = db()
    r = one(c, LIST_SQL + " WHERE p.id=?", (u["username"], pid), "السياسة غير موجودة")
    if r["status"] != "approved" and not _is_admin(u):
        raise HTTPException(404, "السياسة غير موجودة")
    out = _view(r, full=True)
    vs = rows(c.execute("SELECT id, version, status, effective_from, approved_by, approved_at, created_by FROM policies WHERE code=? ORDER BY version DESC", (r["code"],)))
    out["versions"] = [v for v in vs if _is_admin(u) or v["status"] == "approved"]
    return out


def _clean(b: PolicyIn) -> tuple:
    return b.title.strip(), b.category, b.owner_role.strip() or None, b.summary.strip() or None, _articles(b.articles), b.basis.strip() or None, b.review_months, int(b.ack_required)


@router.post("/api/policies")
def api_create(b: PolicyIn, u=Depends(act_as("policies_admin"))):
    """A first version, as a draft. The code is the policy's permanent identity across versions."""
    c = db()
    if c.execute("SELECT 1 FROM policies WHERE code=?", (b.code.upper(),)).fetchone():
        raise HTTPException(409, "الرمز مستخدم — لتعديل سياسة قائمة أنشئ لها نسخة جديدة")
    title, cat, owner, summary, body, basis, months, ack = _clean(b)
    pid = c.execute("INSERT INTO policies(code,title,category,owner_role,summary,body,version,status,review_months,ack_required,basis,created_by) VALUES(?,?,?,?,?,?,1,'draft',?,?,?,?)",
                    (b.code.upper(), title, cat, owner, summary, body, months, ack, basis, u["username"])).lastrowid
    audit(c, "سياسة جديدة (مسودة)", f"{b.code.upper()} · {title}")
    c.commit()
    return {"id": pid}


@router.patch("/api/policies/{pid}")
def api_edit(pid: int, b: PolicyPatch, u=Depends(act_as("policies_admin"))):
    c = db()
    r = one(c, "SELECT * FROM policies WHERE id=?", (pid,), "السياسة غير موجودة")
    if r["status"] != "draft":
        raise HTTPException(409, "المعتمدة لا تُعدَّل — أنشئ نسخة جديدة منها")
    sent = b.model_fields_set
    new: dict = {}
    for k in ("title", "category", "owner_role", "summary", "basis"):
        if k in sent:
            v = getattr(b, k)
            new[k] = (v.strip() or None) if isinstance(v, str) else v
    if "title" in new and not new["title"]:
        raise HTTPException(400, "العنوان مطلوب")
    if "category" in new and new["category"] is None:
        raise HTTPException(400, "التصنيف مطلوب")
    if "articles" in sent and b.articles is not None:
        new["body"] = _articles(b.articles)
    if "review_months" in sent and b.review_months is not None:
        new["review_months"] = b.review_months
    if "ack_required" in sent and b.ack_required is not None:
        new["ack_required"] = int(b.ack_required)
    if new:
        c.execute("UPDATE policies SET " + ", ".join(f"{k}=?" for k in new) + " WHERE id=?", (*new.values(), pid))
        audit(c, "تعديل مسودة سياسة", f"{r['code']} v{r['version']} · الحقول: {', '.join(new)}")
        c.commit()
    return {"ok": True}


@router.post("/api/policies/{pid}/new-version")
def api_new_version(pid: int, u=Depends(act_as("policies_admin"))):
    """A draft copy (version + 1) of an approved policy — the approved text keeps governing until the new one is approved."""
    c = db()
    r = one(c, "SELECT * FROM policies WHERE id=?", (pid,), "السياسة غير موجودة")
    if r["status"] != "approved":
        raise HTTPException(409, "تُنشأ النسخة الجديدة من النسخة المعتمدة السارية")
    if c.execute("SELECT 1 FROM policies WHERE code=? AND status='draft'", (r["code"],)).fetchone():
        raise HTTPException(409, "لهذه السياسة مسودة قائمة — أكملها أو أوقفها أولًا")
    nv = c.execute("SELECT MAX(version) m FROM policies WHERE code=?", (r["code"],)).fetchone()["m"] + 1
    nid = c.execute("""INSERT INTO policies(code,title,category,owner_role,summary,body,version,status,review_months,ack_required,basis,supersedes_id,created_by)
                       VALUES(?,?,?,?,?,?,?,'draft',?,?,?,?,?)""", (r["code"], r["title"], r["category"], r["owner_role"], r["summary"], r["body"], nv, r["review_months"], r["ack_required"], r["basis"], pid, u["username"])).lastrowid
    audit(c, "نسخة جديدة من سياسة", f"{r['code']} v{nv} (مسودة)")
    c.commit()
    return {"id": nid, "version": nv}


@router.post("/api/policies/{pid}/approve")
def api_approve(pid: int, b: ApproveIn, u=Depends(act_as("policies_admin"))):
    """A different person from the one who prepared it approves, and states the date from which it governs; the version in force until then is retired."""
    c = db()
    r = one(c, "SELECT * FROM policies WHERE id=?", (pid,), "السياسة غير موجودة")
    if r["status"] != "draft":
        raise HTTPException(409, "المسودات وحدها تُعتمد")
    if r["created_by"] == u["username"]:
        raise HTTPException(403, "لا تعتمد سياسة أعددتها بنفسك — يعتمدها شخص آخر")
    try:
        ef = dt.date.fromisoformat(b.effective_from)
    except ValueError:
        raise HTTPException(400, "تاريخ السريان غير صالح") from None
    if ef > today() + dt.timedelta(days=366):
        raise HTTPException(400, "تاريخ السريان بعيد في المستقبل")
    c.execute("UPDATE policies SET status='retired', retired_by=?, retired_at=? WHERE code=? AND status='approved' AND id!=?", (u["username"], now_s(), r["code"], pid))
    c.execute("UPDATE policies SET status='approved', effective_from=?, approved_by=?, approved_at=? WHERE id=?", (ef.isoformat(), u["username"], now_s(), pid))
    audit(c, "اعتماد سياسة", f"{r['code']} v{r['version']} · تسري من {ef.isoformat()}")
    c.commit()
    return {"ok": True}


@router.post("/api/policies/{pid}/retire")
def api_retire(pid: int, u=Depends(act_as("policies_admin"))):
    c = db()
    r = one(c, "SELECT * FROM policies WHERE id=?", (pid,), "السياسة غير موجودة")
    if r["status"] == "retired":
        raise HTTPException(409, "السياسة موقوفة بالفعل")
    c.execute("UPDATE policies SET status='retired', retired_by=?, retired_at=? WHERE id=?", (u["username"], now_s(), pid))
    audit(c, "إيقاف سياسة", f"{r['code']} v{r['version']} ({STATUS_AR[r['status']]} ← موقوفة)")
    c.commit()
    return {"ok": True}


@router.post("/api/policies/{pid}/ack")
def api_ack(pid: int, u=Depends(act_as("policies"))):
    """'I have read this version.' Once per person per version; a draft or retired version cannot be acknowledged."""
    c = db()
    r = one(c, "SELECT * FROM policies WHERE id=?", (pid,), "السياسة غير موجودة")
    if r["status"] != "approved":
        raise HTTPException(404, "السياسة غير موجودة")
    if not r["ack_required"]:
        raise HTTPException(409, "هذه السياسة لا تتطلب إقرارًا")
    if c.execute("SELECT 1 FROM policy_acks WHERE policy_id=? AND username=?", (pid, u["username"])).fetchone():
        raise HTTPException(409, "أقررت بالاطلاع على هذه النسخة من قبل")
    c.execute("INSERT INTO policy_acks(policy_id,version,username,name,employee_id,acked_at) VALUES(?,?,?,?,?,?)", (pid, r["version"], u["username"], u["name"], u.get("employee_id"), now_s()))
    audit(c, "إقرار بالاطلاع على سياسة", f"{r['code']} v{r['version']}")
    c.commit()
    return {"ok": True}


@router.get("/api/policies/{pid}/acks")
def api_acks(pid: int, u=Depends(act_as("policies_admin"))):
    """Who has acknowledged this version and who has not yet (among the active logins whose role is expected to read it)."""
    c = db()
    r = one(c, "SELECT id, code, version, status, ack_required FROM policies WHERE id=?", (pid,), "السياسة غير موجودة")
    done = rows(c.execute("SELECT username, name, acked_at FROM policy_acks WHERE policy_id=? ORDER BY acked_at", (pid,)))
    got = {d["username"] for d in done}
    pend = [t for t in _staff_targets(c) if t["username"] not in got] if r["status"] == "approved" and r["ack_required"] else []
    return {"policy": dict(r), "acknowledged": done, "pending": pend}
