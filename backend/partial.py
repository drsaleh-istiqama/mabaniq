"""مبانيك 0.30.0 — التحديث الجزئي بدلالة PATCH صريحة: دالة واحدة لكل شاشة تعديل.

القواعد (الجرد والتصميم في docs/DESIGN-partial-update.md):
  • الحقل الذي لم يُرسَل (ليس في `model_fields_set`) لا يُمس أبدًا — لا يعني «فارغ» أنه «لا تغيير».
  • الحقل المُرسَل فارغًا أو null يُفرَّغ (NULL) إن كان اختياريًا، ويُرفض بـ400 ورسالة عربية تسمّيه إن كان إلزاميًا.
  • الحقل المُرسَل بقيمته الحالية ليس تغييرًا؛ فإن لم يتغيّر شيء فلا UPDATE ولا سطر تدقيق ولا commit، والرد `changed: []`.
  • سطر التدقيق يذكر الحقول ومن ⟵ إلى. البيانات الشخصية (`personal`) والمشفّرة (`secret`) تُذكر بالاسم وحده: لا قيمة قديمة ولا جديدة
    في التدقيق ولا في الرد.

الاستعمال:
    PERMIT = {"status": Col("الحالة", required=True), "ref": Col("الرقم المرجعي"), "expires": Col("تاريخ الانتهاء", kind="date")}
    p = diff(cur, body, PERMIT, extra={...})        # نقيّة: لا كتابة ولا قراءة من القاعدة؛ ترفض تفريغ الإلزامي
    ...                                              # قواعد العمل الخاصة بالنقطة على p.value("status") ونحوه
    return p.commit(c, "permits", pid, "تحديث ترخيص", subject)   # UPDATE + تدقيق + commit — فقط إن تغيّر شيء
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException

from . import pii
from .common import audit

EMPTY = "بلا"
_MAX_SHOWN = 80


@dataclass(frozen=True)
class Col:
    """ما تعرفه الدالة عن عمود قابل للتعديل."""
    label: str                                    # الاسم العربي في رسالة الواجهة وسطر التدقيق
    required: bool = False                        # لا يُفرَّغ: 400 بالعربية يسمّي الحقل
    personal: bool = False                        # بيانات شخصية: لا قيمة في التدقيق ولا في الرد
    secret: bool = False                          # مشفّر في القاعدة (pii.py): يُقارَن مفتوحًا ويُكتب مشفّرًا؛ يعني personal
    quiet: bool = False                           # نص طويل (مواد سياسة…): يُذكر أنه عُدِّل دون قيمه، في التدقيق وفي الرد
    kind: str = "text"                            # text | num | date | bool — طريقة المقارنة والعرض
    check: Callable[[Any], str | None] | None = None   # يُستدعى للقيمة غير الفارغة؛ يعيد رسالة خطأ عربية أو None
    to_db: Callable[[Any], Any] | None = None     # تحويل القيمة المُرسَلة إلى ما يُخزَّن (مثل 'none' ⟵ NULL)

    @property
    def hidden(self) -> str:
        """'' يُظهر القديم والجديد · 'personal' قيمة شخصية/مشفّرة لا تُذكر أبدًا · 'quiet' عُدِّل بلا قيم."""
        return "personal" if self.personal or self.secret else "quiet" if self.quiet else ""


@dataclass
class Change:
    field: str
    label: str
    old: Any
    new: Any
    hidden: str
    kind: str
    db: Any                                       # ما يُكتب فعلًا في العمود (مشفّرًا للسرّي)


def _is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _clean(v):
    """القيمة المُرسَلة ⟵ شكل التخزين: النص مُقصّص والفارغ NULL، والتاريخ ISO، والمنطقي 0/1."""
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dt.datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, bool):
        return int(v)
    return v


def _key(kind: str, v):
    """مفتاح المقارنة: لا يفرّق بين NULL والفارغ، ولا بين 5 و5.0، ولا بين التاريخ والتاريخ مع الوقت."""
    if kind == "bool":
        return 0 if _is_empty(v) or str(v).lower() in ("0", "false") else 1   # عمود منطقي: NULL يعني 0
    if _is_empty(v):
        return None
    if kind == "num":
        try:
            return round(float(v), 6)
        except (TypeError, ValueError):
            return str(v)
    if kind == "date":
        return str(v)[:10]
    return v.strip() if isinstance(v, str) else v


def _show(kind: str, v) -> str:
    if _is_empty(v):
        return EMPTY
    if kind == "bool":
        return "نعم" if _key("bool", v) else "لا"
    if kind == "num":
        try:
            f = float(v)
            return str(int(f)) if f.is_integer() else str(f)     # 7.0 ⟵ 7
        except (TypeError, ValueError):
            pass
    s = str(v)
    return s if len(s) <= _MAX_SHOWN else s[:_MAX_SHOWN - 1] + "…"


class Patch:
    """ما سيتغيّر في صف واحد — يُبنى بـ`diff()` ويُنفَّذ بـ`commit()`."""

    def __init__(self, cur: dict, changes: list[Change]):
        self.cur = cur
        self.changes = changes

    @property
    def changed(self) -> list[str]:
        return [x.field for x in self.changes]

    def __bool__(self) -> bool:
        return bool(self.changes)

    def value(self, field: str, default=None):
        """القيمة الفعّالة بعد التعديل (المُرسَلة إن تغيّرت، وإلا الحالية) — لفحوص تجمع أكثر من حقل. السرّي يعود مفتوحًا."""
        for x in self.changes:
            if x.field == field:
                return x.new
        return self.cur.get(field, default)

    def public(self) -> list[dict]:
        out = []
        for x in self.changes:
            if x.hidden:
                out.append({"field": x.field, "label": x.label, x.hidden: True})
            else:
                out.append({"field": x.field, "label": x.label, "old": x.old, "new": x.new})
        return out

    def detail(self) -> str:
        parts = []
        for x in self.changes:
            if x.hidden == "personal":
                parts.append(f"{x.label} (قيمة محجوبة)")
            elif x.hidden == "quiet":
                parts.append(f"{x.label} (عُدِّل)")
            else:
                parts.append(f"{x.label}: «{_show(x.kind, x.old)}» ⟵ «{_show(x.kind, x.new)}»")
        return "؛ ".join(parts)

    def response(self, **extra) -> dict:
        return {"ok": True, "changed": self.changed, "changes": self.public(), **extra}

    def commit(self, c, table: str, row_id, action: str, subject: str, *, key: str = "id", **extra) -> dict:
        """UPDATE + سطر تدقيق واحد + commit واحد — فقط إن تغيّر شيء؛ وإلا يعود الرد `changed: []` ولا يُكتب شيء."""
        if self.changes:
            sets = ", ".join(f"{x.field}=?" for x in self.changes)
            c.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", (*[x.db for x in self.changes], row_id))
            self.audited(c, action, subject)
        return self.response(**extra)

    def audited(self, c, action: str, subject: str) -> None:
        """سطر التدقيق + commit — للنقاط التي تكتب في غير جدول بمفتاح (إعدادات المؤسسة): تكتب هي القيم ثم تستدعي هذه."""
        audit(c, action, f"{subject} · {self.detail()}" if subject else self.detail())
        c.commit()


def _sent(body) -> set[str]:
    return set(body.model_fields_set) if hasattr(body, "model_fields_set") else set(body or {})


def _get(body, name):
    return getattr(body, name) if hasattr(body, "model_fields_set") else body[name]


def diff(cur, body, spec: dict[str, Col], *, extra: dict | None = None) -> Patch:
    """يبني التغيير من الصف الحالي `cur` وما أرسله العميل `body` (نموذج Pydantic أو قاموس) وفق `spec`.

    `extra`: قيم يشتقها الخادم نفسه (مثل تاريخ الصدور عند الانتقال إلى «صادر») بشكل التخزين؛ تُقارَن وتُكتب وتظهر في `changes` بتسميتها،
    وتغلب ما أرسله العميل لنفس الحقل.
    ترفض (400) تفريغ حقل إلزامي، وأي قيمة لا يقبلها `check`."""
    cur = dict(cur)
    extra = extra or {}
    sent = _sent(body)
    changes: list[Change] = []
    todo: list[tuple[str, Col, Any]] = [(k, col, _get(body, k)) for k, col in spec.items() if k in sent and k not in extra]
    for k, v in extra.items():      # ما يشتقه الخادم يغلب ما أرسله العميل لنفس الحقل (مثل المالك الافتراضي لوحدة دخلت المحفظة)
        todo.append((k, spec.get(k) or Col(k), v))
    for k, col, raw in todo:
        new = _clean(raw)
        if new is None and col.required:
            raise HTTPException(400, f"«{col.label}» حقل إلزامي ولا يُفرَّغ")
        if new is not None and col.check:
            err = col.check(new)
            if err:
                raise HTTPException(400, err)
        if new is not None and col.to_db:
            new = col.to_db(new)
        if col.secret:
            old = pii.dec(cur.get(k)) or None
            db = pii.enc(new) if new is not None else None
        else:
            old = cur.get(k)
            db = new
        if _key(col.kind, old) == _key(col.kind, new):
            continue
        changes.append(Change(k, col.label, old, new, col.hidden, col.kind, db))
    return Patch(cur, changes)


def partial_update(c, table: str, row_id, cur, body, spec: dict[str, Col], *, action: str, subject: str, extra: dict | None = None, key: str = "id") -> dict:
    """الحالة البسيطة كلها في استدعاء: خطّط ثم نفّذ. النقاط ذات القواعد الإضافية تستعمل `diff()` ثم `commit()` بنفسها."""
    return diff(cur, body, spec, extra=extra).commit(c, table, row_id, action, subject, key=key)
