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
    "min_caption_len": "حداقلِ طولِ کپشن برای مقایسه (نویسه؛ پیش‌فرض ۱۲)",
    "size_tol_pct": "تلورانسِ حجم (٪)",
    "size_tol_min": "تلورانسِ حجم (حداقل بایت)",
    "dur_tol_s": "تلورانسِ زمانِ ویدیو (ثانیه)",
    "min_size_for_match": "حداقل حجم برای مقایسه (بایت)",
    "max_forward_per_group": "حداکثر فوروارد در هر گروه",
    "check_target": "گروهِ چک: مقصدِ ارسالِ تکراری‌ها (گروه/کانال)",
    "check_albums": "در گروهِ چک، تکراری‌های هر گروه کنارِ هم (آلبوم) فرستاده شوند",
    "media_kinds": "نوعِ فایل‌های اسکن‌شده",
    "min_duration_s": "حداقل زمانِ ویدیو برای مقایسه (ثانیه)",
    "size_time_require_one_exact": "حالتِ حجم/زمان: یکی دقیقاً برابر باشد",
    "hash_scope": "دامنهٔ هش: sample (سر+میانه+ته) یا full (کلِ فایل)",
    "size_pair_cap": "سقفِ جفت‌های حجمِ نزدیک برای هر فایل",
    "duration_pair_cap": "سقفِ جفت‌های «زمانِ یکسان» در هر زنجیره (سبدِ پُر)",
    "duration_dense_window": "پنجرهٔ حجمی داخل سبدِ زمانِ پُر (تعدادِ همسایه)",
    "exhaustive_pairs": "بررسیِ کاملِ جفت‌ها (بدونِ سقف — کندتر ولی هیچ جفتی جا نمی‌ماند)",
    "incr_tail": "بازخوانیِ چند پیامِ آخر در اسکنِ ادامه‌ای (برای پست‌های ویرایش‌شده)",
    "cluster_mode": "حالتِ گروه‌بندی: loose (زنجیره‌ای) یا strict (هر عضو با همهٔ اعضا شبیه باشد)",
    "prune_missing": "در اسکنِ کامل، رکوردِ فایل‌های حذف‌شده از کانال از ایندکس پاک شود",
    "hash_full_max_mb": "سقفِ حجم برای هشِ کامل (مگابایت)",
    "preview_pages": "تعدادِ صفحه در اسکنِ محدود (هر صفحه ~۲۰ پست)",
    "preview_delay": "مکثِ بین صفحه‌های اسکنِ محدود (ثانیه)",
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
    min_caption_len: int = field(default_factory=lambda: _env_int("MIN_CAPTION_LEN", 12))
    size_tol_pct: float = field(default_factory=lambda: _env_float("SIZE_TOL_PCT", 0.5))
    size_tol_min: int = field(default_factory=lambda: _env_int("SIZE_TOL_MIN", 2048))
    dur_tol_s: float = field(default_factory=lambda: _env_float("DUR_TOL_S", 2.0))
    min_duration_s: int = field(default_factory=lambda: _env_int("MIN_DURATION_S", 3))
    min_size_for_match: int = field(default_factory=lambda: _env_int("MIN_SIZE_FOR_MATCH", 102400))
    size_time_require_one_exact: bool = field(default_factory=lambda: _env_bool("SIZE_TIME_REQUIRE_ONE_EXACT", True))
    # ── رفتارِ اسکن/گزارش ──
    hash_mode: str = field(default_factory=lambda: _env("HASH_MODE", "candidates") or "candidates")  # off|candidates|all
    hash_scope: str = field(default_factory=lambda: _env("HASH_SCOPE", "sample") or "sample")         # sample|full
    hash_full_max_mb: int = field(default_factory=lambda: _env_int("HASH_FULL_MAX_MB", 200))
    size_pair_cap: int = field(default_factory=lambda: _env_int("SIZE_PAIR_CAP", 240))
    duration_pair_cap: int = field(default_factory=lambda: _env_int("DURATION_PAIR_CAP", 600))
    duration_dense_window: int = field(default_factory=lambda: _env_int("DURATION_DENSE_WINDOW", 40))
    exhaustive_pairs: bool = field(default_factory=lambda: _env_bool("EXHAUSTIVE_PAIRS", False))
    # اسکنِ ادامه‌ای از `max_msg_id - incr_tail` می‌خواند تا پست‌های **ویرایش‌شده** هم دیده شوند
    incr_tail: int = field(default_factory=lambda: _env_int("INCR_TAIL", 200))
    # گروه‌بندی: `loose` (پیش‌فرض؛ Union-Find گذرا + نشانهٔ زنجیره‌ای) یا `strict` (هر عضو با همه)
    cluster_mode: str = field(default_factory=lambda: (_env("CLUSTER_MODE", "loose") or "loose").lower())
    # در اسکنِ کامل، رکوردِ فایل‌هایی که کاربر در تلگرام پاک کرده از ایندکسِ ربات حذف شود
    prune_missing: bool = field(default_factory=lambda: _env_bool("PRUNE_MISSING", True))
    keep_webhook: bool = field(default_factory=lambda: _env_bool("KEEP_WEBHOOK", False))
    # ↑ 💾 DK-16: پیشفرض، وبهوکِ احتمالیِ قدیمی برداشته میشود تا `getUpdates` کار کند؛
    #   اگر روی این سرور وبهوک لازم دارید، KEEP_WEBHOOK=1 بگذارید.
    # ── اسکنِ محدود (بدونِ حسابِ کاربری، از پیش‌نمایشِ عمومیِ t.me/s) ──
    preview_pages: int = field(default_factory=lambda: _env_int("PREVIEW_PAGES", 6))
    owner_claim_code: str = field(default_factory=lambda: _env("OWNER_CLAIM_CODE"))
    preview_delay: float = field(default_factory=lambda: _env_float("PREVIEW_DELAY", 1.2))
    media_kinds: str = field(default_factory=lambda: _env("MEDIA_KINDS", "video") or "video")        # video|video+doc|all
    max_forward_per_group: int = field(default_factory=lambda: _env_int("MAX_FORWARD_PER_GROUP", 12))
    # ── 📤 DK-15: «گروهِ چک» — مقصدِ ارسالِ تکراری‌ها برای بازبینیِ کاربر ──
    # خالی = مقصدی تعیین نشده (بخشِ گروهِ چک خاموش است). می‌تواند `@username` یا `-100…` باشد.
    check_target: str = field(default_factory=lambda: _env("CHECK_TARGET"))
    check_albums: bool = field(default_factory=lambda: _env_bool("CHECK_ALBUMS", True))
    # 🗄 DK-17: پشتیبانِ گیتهاب — «منبعِ یکتا» برای هش‌ها/کانال‌ها/تنظیمات روی همان مخزنِ سورس
    gh_backup_repo: str = field(default_factory=lambda: _env("GH_BACKUP_REPO", "baddarksss/dupfinder"))
    gh_backup_path: str = field(default_factory=lambda: _env("GH_BACKUP_PATH", "backup") or "backup")
    gh_backup_token: str = field(default_factory=lambda: _env("GH_BACKUP_TOKEN") or _env("GH_TOKEN"))
    backup_key: str = field(default_factory=lambda: _env("BACKUP_KEY"))     # رمزِ قفلِ فایلِ پشتیبان
    gh_backup_auto: bool = field(default_factory=lambda: _env_bool("GH_BACKUP_AUTO", True))
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
