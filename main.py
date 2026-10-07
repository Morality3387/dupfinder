#!/usr/bin/env python3
"""نقطهٔ ورود — DupFinder: رباتِ پیدا کردنِ فیلم‌های تکراریِ کانال‌های تلگرام.

اجرا:  BOT_TOKEN=... python3 main.py
سرویسِ سلامت (برای Railway):  GET /  و  GET /health  روی $PORT
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time

# امکانِ اجرا از هر پوشه‌ای
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.bot_app import BotApp          # noqa: E402
from app.config import Settings         # noqa: E402
from app.db import Db                   # noqa: E402
from app.tg_api import TgApi            # noqa: E402
from app.user_client import UserClient  # noqa: E402

log = logging.getLogger("dup")
_STARTED_AT = time.time()          # برای uptime_s در /health (قبلاً اشتباهاً از ساعتِ monotonic خوانده می‌شد)
REV = "2026-10-07-dk16"             # برچسبِ نسخه (در /health دیده می‌شود)


def uptime_seconds() -> int:
    """ثانیه‌های سپری‌شده از شروعِ برنامه (نه ساعتِ monotonic — باگی که کاربر گرفت)."""
    return int(max(0.0, time.time() - _STARTED_AT))


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, str(level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def pick_db_path(preferred: str) -> str:
    d = os.path.dirname(os.path.abspath(preferred)) or "."
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".w")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return preferred
    except Exception:
        alt = os.path.join(os.getcwd(), "data", "dup.db")
        os.makedirs(os.path.dirname(alt), exist_ok=True)
        log.warning("مسیرِ %s قابلِ نوشتن نیست ⇒ %s", preferred, alt)
        return alt


async def health_server(db: Db, bot_app: BotApp, port: int) -> None:
    """سرورِ کوچکِ سلامت (برای Railway). هیچ دادهٔ حساسی برنمی‌گرداند."""
    from aiohttp import web

    async def handle(_req):
        st = db.stats()
        scan = bot_app.scan or {}
        body = {
            "ok": True,
            "app": "dupfinder",
            "rev": REV,                       # برای تأییدِ سریعِ این‌که کدام نسخه روی سرور است

            "uptime_s": uptime_seconds(),
            "started_at": int(_STARTED_AT),
            "channels": st["channels"],
            "files": st["files"],
            "scans": st["scans"],
            "groups": st["groups"],
            "hashed": int(st.get("hashed") or 0),                 # 💾 DK-16: هش‌ها
            "hash_full": db.count_hashed_scope("full"),
            "hash_sample": db.count_hashed_scope("sample"),
            "stale_scans": int(getattr(bot_app, "_stale_marked", 0) or 0),   # اسکن‌های نیمه‌کارهٔ استارت
            "user_account": bool(getattr(bot_app.user, "ready", False)),
            "scan_running": bool(scan and not scan.get("done")),
            "hash_mode": str(getattr(bot_app.settings, "hash_mode", "") or ""),
            "hash_scope": str(getattr(bot_app.settings, "hash_scope", "") or ""),
            "hash_full_max_mb": int(getattr(bot_app.settings, "hash_full_max_mb", 0) or 0),
            **{("scan_" + k): v for k, v in (bot_app.scan_snapshot() or {}).items()
               if k in ("state", "phase", "pct", "hashed", "hash_total", "note", "channel", "age_s")},
        }
        return web.json_response(body)

    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/health", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("سرورِ سلامت روی 0.0.0.0:%d", port)
    return runner


async def amain() -> int:
    settings = Settings()
    setup_logging(settings.log_level)
    if not settings.bot_token:
        log.error("BOT_TOKEN تنظیم نشده است. متغیرهای محیطی را از .env.example پر کنید.")
        return 2
    settings.db_path = pick_db_path(settings.db_path)
    db = Db(settings.db_path)
    # بازنویسی از دیتابیس (تنظیماتِ ذخیره‌شده در ربات)
    kv = db.kv_all()
    settings.apply_overrides({k[len("setting:"):]: v for k, v in kv.items() if k.startswith("setting:")})
    settings.api_id = int(kv.get("api_id") or settings.api_id or 0)
    settings.api_hash = str(kv.get("api_hash") or settings.api_hash or "")
    if kv.get("session_string"):
        settings.session_string = str(kv["session_string"])
    if kv.get("owner_id"):
        settings.owner_id = int(kv["owner_id"])
    log.info("دیتابیس: %s", settings.db_path)

    api = TgApi(settings.bot_token)
    me = {}
    for attempt in range(5):
        try:
            me = await api.get_me()
            break
        except Exception as e:
            log.warning("getMe ناموفق (%s) — تلاشِ %d", e, attempt + 1)
            await asyncio.sleep(2 + attempt)
    if not me:
        log.error("توکنِ ربات نامعتبر است یا شبکه در دسترس نیست.")
        return 3
    log.info("ربات: @%s (%s)", me.get("username"), me.get("id"))

    user = UserClient(settings.api_id, settings.api_hash, settings.session_string)
    if user.configured and user.session_string:
        ok = await user.start()
        log.info("حسابِ کاربری: %s", "وصل ✅" if ok else "وصل نشد — با دکمهٔ 🔑 از ربات وارد شوید")

    # 💾 DK-16: در حالتِ polling با `getUpdates`، وبهوکِ قدیمی جلوی دریافتِ آپدیت‌ها را می‌گیرد
    # (باگِ واقعیِ گزارش‌شده در سرویسِ خواهر). در حالتِ dev/testing دست نمی‌زنیم.
    if not settings.keep_webhook:
        try:
            await api.delete_webhook(drop_pending=False)
            log.info("وبهوک (اگر بود) برداشته شد؛ ربات با getUpdates کار می‌کند.")
        except Exception as e:
            log.info("برداشتنِ وبهوک ناموفق (بی‌خطر): %s", e)

    bot_app = BotApp(api, db, settings, user)
    runner = None
    port = int(os.environ.get("PORT") or 0)
    if port:
        try:
            runner = await health_server(db, bot_app, port)
        except Exception as e:
            log.warning("سرورِ سلامت بالا نیامد: %s", e)

    stop = asyncio.Event()

    def _sig(*_a):
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for s in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(s, _sig)
            except NotImplementedError:
                pass
    except Exception:
        pass

    # ⏹ DK-16: اسکن‌هایی که با ری‌استارت نیمه‌کاره مانده‌اند را علامت می‌زنیم و به مالک خبر می‌دهیم
    bot_task = asyncio.create_task(bot_app.mark_stale_scans())
    task = asyncio.create_task(bot_app.run())
    log.info("ربات شروع به کار کرد. Ctrl+C برای خروج.")
    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass
    log.info("خروج…")
    bot_task.cancel()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await user.stop()
    await api.close()
    if runner:
        await runner.cleanup()
    db.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(amain()))
    except KeyboardInterrupt:
        raise SystemExit(0)
