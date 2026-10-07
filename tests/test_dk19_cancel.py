"""تست‌های DK-19 — «⏹ توقف» باید واقعاً بایستد و اسکنِ گیرکرده ربات را قفل نکند.

گزارشِ کاربر: «اومدم اسکن کنم گفت: ⏳ یک اسکن در جریان است … بعد از صفحهٔ اصلی توقف زدم:
⏹ درخواستِ توقف فرستاده شد… و کنسل نشد.»

ریشهٔ باگ (از لاگِ سرور): اسکن در فازِ هش‌گذاریِ نامزدها بود، اتصالِ تلگرام قطع شد و
`asyncio.gather` داخلِ `hash_batch` تا ابد منتظرِ دانلودِ گم‌شده ماند. چکِ لغو فقط **بینِ
دسته‌های ۱۰۰تایی** بود، پس هرگز اجرا نشد ⇒ نه توقف کار کرد، نه گزارشِ پایانی آمد.

سه لایهٔ محافظت که این فایل تست می‌کند:
 ① `guarded_gather` — لغوِ کاربر هر نیم‌ثانیه چک می‌شود و تسک‌های معلق قطع می‌شوند.
 ② `item_timeout` — هیچ فایلی بیش از ۴ دقیقه منتظر نمی‌مانَد؛ فایلِ گیرکرده رد می‌شود.
 ③ نگهبانِ ربات — اگر اسکن در مهلت نایستاد، تسک اجباری قطع و «کنسل‌شده» ثبت می‌شود؛
    و پرچمِ کهنه («در جریان» بدونِ تسکِ زنده) دیگر کاربر را از اسکن‌کردن محروم نمی‌کند.
"""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bot_app import BotApp                            # noqa: E402
from app.user_client import HashCanceled, guarded_gather  # noqa: E402
from dev.fake_telegram import channel_dataset             # noqa: E402
from tests.test_bot_flow import CHAT, Env                 # noqa: E402
from tests.test_user_client import build                  # noqa: E402

MB = 1024 * 1024


# ───────────────── ① نگهبانِ گروهی: لغو و مهلت ─────────────────

def test_guarded_gather_keeps_order_and_results():
    async def ok(v, delay=0.0):
        if delay:
            await asyncio.sleep(delay)
        return v

    async def go():
        return await guarded_gather([ok("a"), ok("b", 0.05), ok("c")])

    g = asyncio.run(go())
    assert g["results"] == ["a", "b", "c"]
    assert g["canceled"] is False and g["timeouts"] == 0


def test_guarded_gather_cancels_hanging_work_fast():
    """قلبِ باگِ گزارش‌شده: کارِ گیرکرده باید با فشردنِ توقف سریع رها شود، نه هرگز."""
    flag = {"v": False}

    async def stuck():
        await asyncio.sleep(30)

    async def flip():
        await asyncio.sleep(0.1)
        flag["v"] = True

    async def go():
        asyncio.ensure_future(flip())
        t0 = time.monotonic()
        g = await guarded_gather([stuck(), stuck(), stuck()],
                                 cancel=lambda: flag["v"], poll=0.05)
        return g, time.monotonic() - t0

    g, dt = asyncio.run(go())
    assert g["canceled"] is True and g["results"] == [None, None, None]
    assert dt < 2.0, "لغو باید فوری باشد، نه بعد از ۳۰ ثانیه: %.2fs" % dt


def test_guarded_gather_item_timeout_does_not_stop_the_rest():
    async def quick():
        return 1

    async def stuck():
        await asyncio.sleep(5)
        return 2

    async def go():
        t0 = time.monotonic()
        g = await guarded_gather([quick(), stuck()], poll=0.05, item_timeout=0.2)
        return g, time.monotonic() - t0

    g, dt = asyncio.run(go())
    assert g["results"] == [1, None] and g["timeouts"] == 1
    assert dt < 2.0, "مهلتِ هر کار باید مستقل باشد: %.2fs" % dt


# ───────────────── ② hash_batch روی دانلودِ گیرکرده ─────────────────

def _client_with_hang(msgs, contents, hang_ids):
    """کلاینتِ ساختگی که دانلودِ پیام‌های `hang_ids` را «گیر» می‌کند (شبیه‌سازیِ قطعِ اتصال)."""
    uc, tg = build(msgs, contents)
    orig = tg._download

    def patched(media, off, ln):
        msg = tg._by_media.get(id(media))

        async def gen():
            if msg is not None and int(msg.id) in set(hang_ids):
                await asyncio.sleep(30)          # هرگز برنمی‌گردد
                return
            async for x in orig(media, off, ln):
                yield x

        return gen()

    tg._download = patched
    uc.chunk_delay = 0.0          # بدونِ تأخیرِ ساختگی تا سنجشِ زمان دقیق باشد
    return uc, tg


def test_hash_batch_stops_quickly_when_user_cancels():
    ds = channel_dataset()
    uc, _ = _client_with_hang(ds["videos"], ds["contents"], hang_ids={101})
    flag = {"v": False}

    async def go():
        async def flip():
            await asyncio.sleep(0.15)
            flag["v"] = True

        asyncio.ensure_future(flip())
        t0 = time.monotonic()
        try:
            await uc.hash_batch(55, [(101, 200 * MB), (102, 200 * MB)],
                                cancel=lambda: flag["v"])
            return "returned", time.monotonic() - t0
        except HashCanceled:
            return "canceled", time.monotonic() - t0

    kind, dt = asyncio.run(go())
    assert kind == "canceled", "توقف باید HashCanceled بدهد تا اسکنر «کنسل» را ثبت کند"
    assert dt < 2.0, "لغوِ هش باید فوری باشد: %.2fs" % dt


def test_hash_batch_skips_stuck_file_and_keeps_the_rest():
    ds = channel_dataset()
    uc, _ = _client_with_hang(ds["videos"], ds["contents"], hang_ids={101})
    stats = {}

    async def go():
        t0 = time.monotonic()
        out = await uc.hash_batch(55, [(101, 200 * MB), (102, 200 * MB)],
                                  item_timeout=0.3, stats=stats)
        return out, time.monotonic() - t0

    out, dt = asyncio.run(go())
    assert out[101] == ("", ""), "فایلِ گیرکرده باید رد شود، نه این‌که اسکن را بخواباند"
    assert out[102][0], "بقیهٔ فایل‌های سالم باید هش شوند"
    assert stats.get("timeouts") == 1
    assert dt < 3.0, dt


# ───────────────── ③ حالتِ اسکن در ربات ─────────────────

def test_scan_alive_only_when_a_task_is_really_running():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        assert e.bot._scan_alive() is False, "بدونِ اسکن ⇒ زنده نیست"

        e.bot.scan = {"done": True, "started": time.time(), "task": None}
        assert e.bot._scan_alive() is False

        async def hang():
            await asyncio.sleep(5)

        t = e.loop.create_task(hang())
        e.bot.scan = {"done": False, "started": time.time(), "task": t}
        assert e.bot._scan_alive() is True

        t.cancel()
        e.run(asyncio.gather(t, return_exceptions=True))
        assert e.bot._scan_alive() is False, "تسکِ مرده ⇒ اسکنِ کهنه، نه «در جریان»"

        e.bot.scan = {"done": False, "started": time.time() - 600, "task": None}
        assert e.bot._scan_alive() is False, "پرچمِ جامانده (بدونِ تسک) کهنه است"
        e.bot.scan = {"done": False, "started": time.time(), "task": None}
        assert e.bot._scan_alive() is True, "فاصلهٔ ساختِ تسک باید محترم شمرده شود"


def test_scan_snapshot_reports_stale_instead_of_running():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        assert e.bot.scan_snapshot()["state"] == "idle"
        e.bot.scan = {"done": False, "started": time.time() - 500, "task": None, "cid": 3, "channel": {}}
        snap = e.bot.scan_snapshot()
        assert snap["state"] == "stale", snap
        assert "کهنه" in str(snap.get("note") or "")


def test_cancel_on_ghost_scan_frees_the_user():
    """اگر «یک اسکن در جریان است» دروغ باشد، زدنِ توقف باید آزاد کند (نه پیامِ بی‌اثر)."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        sid = e.db.create_scan(cid, {"full": False})       # ردیفِ جامانده مثلِ ری‌استارتِ سرور
        e.db.update_scan(sid, status="running")
        e.bot.scan = {"done": False, "started": time.time() - 900, "task": None,
                      "cid": cid, "channel": {}}
        e.api.sent.clear()
        e.tap("scan:cancel")
        assert e.bot.scan is None, "پرچمِ کهنه باید پاک شود تا کاربر گیر نکند"
        assert "اسکنی در جریان نیست" in e.last()
        assert (e.db.get_scan(sid) or {}).get("status") == "canceled"


def test_hung_scan_is_force_stopped_by_watchdog():
    """باگِ گزارش‌شده: «درخواستِ توقف فرستاده شد» و بعد سکوت — حالا نگهبان قطعش می‌کند."""
    grace = BotApp.CANCEL_GRACE
    BotApp.CANCEL_GRACE = 0.3
    try:
        with tempfile.TemporaryDirectory() as d:
            e = Env(Path(d))
            cid = e.add_channel()
            sid = e.db.create_scan(cid, {"full": True})
            e.db.update_scan(sid, status="running")

            class FakeScanner:
                def __init__(self):
                    self.scan_id = sid
                    self.progress = type("P", (), {"pct": 70.0, "hashed": 114,
                                                   "hash_total": 1746})()

                def cancel(self):
                    FakeScanner.called = True

            FakeScanner.called = False

            async def hang():
                await asyncio.sleep(60)

            t = e.loop.create_task(hang())
            e.bot.scan = {"chat_id": CHAT, "msg_id": 9, "done": False, "started": time.time(),
                          "cid": cid, "channel": {"id": cid, "title": "Top irani"},
                          "scanner": FakeScanner(), "task": t}
            e.api.sent.clear()
            e.run(e.bot._cancel_scan(CHAT))
            assert FakeScanner.called, "اول باید سیگنالِ مؤدبانه برود"
            assert any("درخواستِ توقف" in m["text"] for m in e.api.sent)

            # نگهبان: تا مهلت صبر، بعد قطعِ اجباری
            e.run(asyncio.sleep(1.2))
            assert t.done(), "اسکنِ گیرکرده باید اجباری قطع شود"
            assert (e.bot.scan or {}).get("done") is True
            assert (e.db.get_scan(sid) or {}).get("status") == "canceled", \
                "وضعیت باید در دیتابیس «کنسل‌شده» ثبت شود (نه running)"
            assert any("متوقف شد" in m["text"] for m in e.api.sent)
            assert e.bot._scan_alive() is False, "بعد از قطع، اسکنِ تازه باید آزاد باشد"
    finally:
        BotApp.CANCEL_GRACE = grace


def test_start_scan_blocked_only_by_a_live_scan():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()

        async def hang():
            await asyncio.sleep(5)

        # (الف) اسکنِ واقعاً در جریان ⇒ پیامِ «در جریان است»
        t = e.loop.create_task(hang())
        e.bot.scan = {"done": False, "started": time.time(), "task": t,
                      "cid": cid, "channel": {}}
        e.api.sent.clear()
        e.run(e.bot._start_scan(CHAT, cid, full=False))
        assert any("در جریان است" in m["text"] for m in e.api.sent), "اسکنِ زنده باید بلاک کند"
        t.cancel()
        e.run(asyncio.gather(t, return_exceptions=True))

        # (ب) پرچمِ کهنه (بدونِ تسک) ⇒ نباید بلاک کند؛ خودش پاک می‌شود و اسکن شروع می‌شود
        e.bot.scan = {"done": False, "started": time.time() - 900, "task": None,
                      "cid": cid, "channel": {}}
        e.api.sent.clear()
        e.run(e.bot._start_scan(CHAT, cid, full=False))
        assert not any("در جریان است" in m["text"] for m in e.api.sent), \
            "پرچمِ کهنه نباید جلوی اسکنِ تازه را بگیرد"
        assert e.bot.scan is not None and e.bot._scan_alive(), "اسکنِ تازه باید واقعاً شروع شود"
        e.wait_scan()
