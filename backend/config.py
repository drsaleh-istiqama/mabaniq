"""Mabaniq — configuration from the environment (Unit 0).

One place reads the environment; everything else imports `settings`. In production (`MABANIQ_ENV=prod`)
`validate()` must return no errors or the process refuses to start — the same fail-fast rule as
`istiqama-map` (no secret or debug flag may be left to a default).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.7.0"
ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _rate(name: str, default: str) -> tuple[int, int]:
    """'N/SECONDS' → (N, SECONDS)."""
    raw = os.environ.get(name, default)
    try:
        n, s = raw.split("/")
        return max(1, int(n)), max(1, int(s))
    except ValueError:
        n, s = default.split("/")
        return int(n), int(s)


@dataclass(frozen=True)
class Settings:
    env: str = "demo"
    version: str = VERSION
    git_sha: str = ""
    app_name: str = "مبانيك | Mabaniq"
    app_domain: str = "mabaniq.example.org"
    database_url: str = ""                       # postgresql://… (Unit 1); empty = SQLite files under data/
    sqlite_path: str = str(ROOT / "data" / "mabaniq.db")
    host: str = "127.0.0.1"
    port: int = 8800
    trust_proxy: bool = True
    force_pw_change: bool = True
    log_json: bool = True
    log_level: str = "INFO"
    rate_login: tuple[int, int] = (10, 60)       # per IP
    rate_api: tuple[int, int] = (600, 60)        # per IP, all /api/*
    rate_webhook: tuple[int, int] = (60, 60)
    pii_key_set: bool = False
    pay_secret_set: bool = False
    sentry_dsn: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def prod(self) -> bool:
        return self.env == "prod"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            env=os.environ.get("MABANIQ_ENV", "demo"),
            version=os.environ.get("MABANIQ_VERSION", VERSION),
            git_sha=os.environ.get("MABANIQ_GIT_SHA", ""),
            app_name=os.environ.get("MABANIQ_APP_NAME", "مبانيك | Mabaniq"),
            app_domain=os.environ.get("MABANIQ_APP_DOMAIN", "mabaniq.example.org"),
            database_url=os.environ.get("MABANIQ_DATABASE_URL", ""),
            sqlite_path=os.environ.get("MABANIQ_DB", str(ROOT / "data" / "mabaniq.db")),
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8800")),
            trust_proxy=_bool("MABANIQ_TRUST_PROXY", True),
            force_pw_change=_bool("MABANIQ_FORCE_PW_CHANGE", True),
            log_json=_bool("MABANIQ_LOG_JSON", True),
            log_level=os.environ.get("MABANIQ_LOG_LEVEL", "INFO").upper(),
            rate_login=_rate("MABANIQ_RATE_LOGIN", "10/60"),
            rate_api=_rate("MABANIQ_RATE_API", "600/60"),
            rate_webhook=_rate("MABANIQ_RATE_WEBHOOK", "60/60"),
            pii_key_set=bool(os.environ.get("MABANIQ_PII_KEY")),
            pay_secret_set=bool(os.environ.get("MABANIQ_PAY_SECRET")),
            sentry_dsn=os.environ.get("MABANIQ_SENTRY_DSN", ""),
        )

    def validate(self) -> list[str]:
        """Errors that must block a production start. Empty list = OK."""
        errs: list[str] = []
        if not self.prod:
            return errs
        if not self.pii_key_set:
            errs.append("MABANIQ_PII_KEY غير معيَّن (مفتاح تشفير بيانات الهوية)")
        if not self.pay_secret_set:
            errs.append("MABANIQ_PAY_SECRET غير معيَّن (سر توقيع إشعارات بوابة الدفع)")
        if not self.force_pw_change:
            errs.append("MABANIQ_FORCE_PW_CHANGE يجب أن يبقى مفعّلًا في الإنتاج")
        if not self.database_url:
            errs.append("MABANIQ_DATABASE_URL (PostgreSQL) مطلوب في الإنتاج — SQLite للتطوير فقط (الوحدة 1)")
        if self.app_domain.endswith("example.org"):
            errs.append("MABANIQ_APP_DOMAIN ما زال القيمة المؤقتة example.org (قرار المالك 4)")
        if self.log_level == "DEBUG":
            errs.append("MABANIQ_LOG_LEVEL=DEBUG يسرّب تفاصيل في سجلات الإنتاج")
        return errs

    def public(self) -> dict:
        """Safe to show on /version and in logs (no secrets)."""
        return {"version": self.version, "env": self.env, "git_sha": self.git_sha or None, "app": self.app_name,
                "database": "postgresql" if self.database_url.startswith("postgres") else "sqlite",
                "rate_limits": {"login": "%d/%ds" % self.rate_login, "api": "%d/%ds" % self.rate_api}}


settings = Settings.from_env()
