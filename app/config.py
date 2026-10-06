"""تنظیماتِ برنامه — از متغیرهای محیطی + بازنویسیِ زمانِ اجرا از دیتابیس."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except Exception:
        return default

def _env_bool(name: str, default: bool) -> bool:
    v = _env(name, "").lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on", "بله")


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except Exception:
        return default

# ── نامِ فارسی برای هر پارامتر (برای نمایش در تنظیماتِ ربات) ─────────────────
LABELS: Dict[str, str] = {
    "hash_mode": "حالتِ هش (تأییدِ فایلِ یکسان)",
    "th_name_ratio": "آستانهٔ شباهتِ نام (نسبت)",
    "th_name_jaccard": "آستانهٔ شباهتِ نام (توکن)",
    "th_cap_ratio": "آستانهٔ شباهتِ کپشن (نسبت)",
    "th_cap_jaccard": "آستانهٔ شباهتِ کپشن (توکن)",
    "size_tol_pct": "تلورانسِ حجم (٪)",
    "size_tol_min": "تلورانسِ حجم (حداقل بایت)",
    "dur_tol_s": "تلورانسِ زمانِ ویدیو (ثانیه)",
    "min_size_for_match": "حداقل حجم برای مقایسه (بایت)",
    "max_forward_per_group": "حداکثر فوروارد در هر گروه",
    "media_kinds": "نوعِ فایل‌های اسکن‌شده",
    "min_duration_s": "حداقل زمانِ ویدیو برای مقایسه (ثانیه)",
    "size_time_require_one_exact": "حالتِ حجم/زمان: یکی دقیقاً برابر باشد",
}


@dataclass
class Settings:
    # ── زیرساخت ──
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN"))
    owner_id: int = field(default_factory=lambda: _env_int("OWNER_ID", 0))
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "/data/dup.db"))
    lang: str = field(default_factory=lambda: _env("LANG", "fa") or "fa")
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO") or "INFO")
    # ── حسابِ کاربری (Telethon) برای خواندنِ تاریخچهٔ کامل ──
    api_id: int = field(default_factory=lambda: _env_int("TG_API_ID", 0))
    api_hash: str = field(default_factory=lambda: _env("TG_API_HASH"))
    session_string: str = field(default_factory=lambda: _env("TG_SESSION_STRING"))
    # ── آستانه‌های تطبیق (قابلِ تغییر از خودِ ربات) ──
    th_name_ratio: float = field(default_factory=lambda: _env_float("TH_NAME_RATIO", 0.82))
    th_name_jaccard: float = field(default_factory=lambda: _env_float("TH_NAME_JACCARD", 0.60))
    th_cap_ratio: float = field(default_factory=lambda: _env_float("TH_CAP_RATIO", 0.80))
    th_cap_jaccard: float = field(default_factory=lambda: _env_float("TH_CAP_JACCARD", 0.60))
    size_tol_pct: float = field(default_factory=lambda: _env_float("SIZE_TOL_PCT", 0.5))
    size_tol_min: int = field(default_factory=lambda: _env_int("SIZE_TOL_MIN", 2048))
    dur_tol_s: float = field(default_factory=lambda: _env_float("DUR_TOL_S", 2.0))
    min_duration_s: int = field(default_factory=lambda: _env_int("MIN_DURATION_S", 3))
    min_size_for_match: int = field(default_factory=lambda: _env_int("MIN_SIZE_FOR_MATCH", 102400))
    size_time_require_one_exact: bool = field(default_factory=lambda: _env_bool("SIZE_TIME_REQUIRE_ONE_EXACT", True))
    # ── رفتارِ اسکن/گزارش ──
    hash_mode: str = field(default_factory=lambda: _env("HASH_MODE", "candidates") or "candidates")  # off|candidates|all
    media_kinds: str = field(default_factory=lambda: _env("MEDIA_KINDS", "video") or "video")        # video|video+doc|all
    max_forward_per_group: int = field(default_factory=lambda: _env_int("MAX_FORWARD_PER_GROUP", 12))
    progress_interval: float = field(default_factory=lambda: _env_float("PROGRESS_INTERVAL", 2.0))
    scan_wait_time: float = field(default_factory=lambda: _env_float("SCAN_WAIT_TIME", 0.35))
    page_size: int = field(default_factory=lambda: _env_int("PAGE_SIZE", 8))

    def as_public(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("bot_token", "api_hash", "session_string"):
            d.pop(k, None)
        return d

    def apply_overrides(self, kv: Dict[str, Any]) -> "Settings":
        """پارامترهای عددی/رشته‌ای را از دیتابیس روی خود اعمال می‌کند."""
        for k in LABELS:
            if k in kv and kv[k] is not None and kv[k] != "":
                cur = getattr(self, k)
                try:
                    if isinstance(cur, bool):
                        setattr(self, k, bool(kv[k]))
                    elif isinstance(cur, int):
                        setattr(self, k, int(float(kv[k])))
                    elif isinstance(cur, float):
                        setattr(self, k, float(kv[k]))
                    else:
                        setattr(self, k, str(kv[k]))
                except Exception:
                    pass
        return self
