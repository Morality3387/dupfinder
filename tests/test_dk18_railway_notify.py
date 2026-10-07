"""تست‌های DK-18 — 🚂 اعتبار/روزِ ماندهٔ Railway در صفحهٔ اصلی · 🔐 توکن از محیط/ربات · 🔔 نوتیفِ پایانِ اسکن.

خواسته‌های کاربر:
 ① «یه فیچر دیگه هم اضافه کن که توکنِ ریلوی رو استفاده کنه و تو صفحهٔ اصلی کردیت و روزِ
    باقی‌ماندهٔ ریلوی رو نشون بده.»
 ② «موقعِ نصبِ ربات هم وریبل بذار برای توکنِ ریلوی.» ⇒ `RAILWAY_TOKEN` در `.env.example` و در
    متغیرهای سرور، و از خودِ ربات هم قابلِ تنظیم (پیامِ توکن بعدش پاک می‌شود).
 ③ «یه اپشن بذار وقتی اسکن تموم شد ی ناتیف بفرسته، بدونم که هی چک نکنم تمام شده یا نه.»
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import railway as RW                        # noqa: E402
from app.config import Settings                      # noqa: E402
from tests.test_bot_flow import CHAT, OWNER, Env     # noqa: E402

RAW_OK = {"me": {"email": "elf-smitten-catnip@duck.com", "workspaces": [
    {"id": "e5c6b095-6ef4-46a8-99c1-fce2b653f306", "name": "morality3387's Projects", "plan": "HOBBY",
     "customer": {"id": "c1", "creditBalance": 5, "currentUsage": 0.1,
                  "remainingUsageCreditBalance": 4.9, "trialDaysRemaining": 29,
                  "isTrialing": True, "state": "INACTIVE",
                  "billingPeriod": {"start": "2026-10-06T10:49:26.664Z", "end": "2026-10-07T23:59:59.999Z"}}}]}}


class FakeRailway:
    """transport ساختگی برای `RW.Railway` — پاسخِ GraphQL را شبیه‌سازی می‌کند."""

    def __init__(self, data=None, error=None):
        self.data = data if data is not None else RAW_OK
        self.error = error
        self.calls = []

    def __call__(self, url, body):
        self.calls.append(body)
        if self.error:
            return {"errors": [{"message": self.error}]}
        return {"data": self.data}


def _env(d, transport=None, **kw):
    e = Env(Path(d), **kw)
    e.text("/start")
    e.bot.rw_transport = transport
    return e


def _scan(e):
    cid = e.add_channel()
    e.tap("scan:full:%d" % cid)
    e.wait_scan()
    return cid


# ───────────────────────── ① ماژولِ Railway ─────────────────────────

def test_summarise_extracts_plan_credit_and_days():
    info = RW.summarise({"me": RAW_OK["me"]})
    assert info["plan"] == "HOBBY" and info["credit"] == 5.0 and info["usage"] == 0.1
    assert info["is_trial"] is True and info["days_left"] == 29
    assert info["workspace"].startswith("morality3387")
    # 💳 «باقی‌مانده» = همان عددی که پنلِ ریلوی نشان می‌دهد (کل − مصرف)
    assert info["credit_left"] == 4.9, info


def test_summarise_prefers_matching_project_and_falls_back():
    two = {"me": {"email": "x@y.z", "workspaces": [
        {"id": "w1", "name": "A", "plan": "FREE", "customer": {"creditBalance": 1, "trialDaysRemaining": 3, "isTrialing": True}},
        {"id": "w2", "name": "B", "plan": "PRO", "customer": {"creditBalance": 9, "trialDaysRemaining": 11, "isTrialing": True}}]}}
    assert RW.summarise(two, project_id="w2")["workspace"] == "B"
    assert RW.summarise(two)["workspace"] == "A", "بی‌شناسه ⇒ اولین ورک‌اسپیس"
    # بی‌trial: روزهای مانده از پایانِ دوره حساب می‌شود
    plain = RW.summarise({"me": {"workspaces": [{"id": "w", "customer": {
        "creditBalance": 2, "isTrialing": False,
        "billingPeriod": {"end": "2026-10-20T00:00:00.000Z"}}}]}}, now=1760000000)
    assert plain["is_trial"] is False and plain["days_left"] >= 0


def test_credit_left_uses_panel_number_and_never_goes_negative():
    """باقی‌مانده یا از خودِ Railway می‌آید یا مثلِ پنل حساب می‌شود؛ هرگز منفی نمی‌شود."""
    with_panel = {"me": {"workspaces": [{"id": "w", "plan": "HOBBY", "customer": {
        "creditBalance": 5, "currentUsage": 1.25, "remainingUsageCreditBalance": 3.75}}]}}
    assert RW.summarise(with_panel)["credit_left"] == 3.75
    no_field = {"me": {"workspaces": [{"id": "w", "plan": "HOBBY", "customer": {
        "creditBalance": 5, "currentUsage": 1.25}}]}}
    assert RW.summarise(no_field)["credit_left"] == 3.75, "بی‌فیلدِ Railway ⇒ کل − مصرف"
    over = {"me": {"workspaces": [{"id": "w", "customer": {
        "creditBalance": 5, "currentUsage": 6.5}}]}}
    assert RW.summarise(over)["credit_left"] == 0.0, "زیرِ صفر نمی‌رود"
    # درصد و نوارِ مصرف (مثلِ پنل)
    info = RW.summarise(with_panel)
    assert 24.0 < RW.used_pct(info) < 26.0
    bar = RW.bar_text(RW.used_pct(info))
    assert len(bar) == 10 and bar.count("▰") == 2
    assert RW.bar_text(2.3).count("▰") == 1, "مصرفِ کم هم باید دیده شود، نه نوارِ خالی"
    assert RW.bar_text(0).count("▰") == 0 and RW.bar_text(100).count("▱") == 0


def test_warn_text_flags_low_days_and_low_credit():
    assert "روز" in RW.warn_text({"days_left": 3, "credit": 4.0})
    assert "اعتبار" in RW.warn_text({"days_left": 20, "credit": 0.2})
    assert RW.warn_text({"days_left": 20, "credit": 4.0}) == ""
    # هشدار بر پایهٔ «باقی‌مانده» است، نه اعتبارِ کل
    assert "اعتبار" in RW.warn_text({"days_left": 20, "credit": 5.0, "credit_left": 0.2})
    assert RW.warn_text({"days_left": 20, "credit": 5.0, "credit_left": 4.8}) == ""


# ───────────────────────── ② توکن و صفحهٔ اصلی ─────────────────────────

def test_main_menu_shows_railway_line_from_env_token():
    """توکن از متغیرِ محیطی ⇒ صفحهٔ اصلی اعتبار و روزِ مانده را نشان می‌دهد."""
    fake = FakeRailway()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        e.settings.railway_token = "rw-token-abcdef123456"
        asyncio.new_event_loop().run_until_complete(e.bot.rw_startup())
        e.text("/start")
        txt = e.last_view()
        assert "🚂" in txt and "5.00" in txt, txt
        assert "$4.90" in txt, "باقی‌مانده (نه اعتبارِ کل) باید نشان داده شود: " + txt
        assert ("۲۹" in txt or "29" in txt), txt          # شمارنده‌ها فارسی نمایش داده می‌شوند
        assert "HOBBY" in txt and "آزمایشی" in txt
        assert fake.calls and "me" in fake.calls[0]["query"]
        # هم کش شده و هم قابلِ دیدن از /health
        assert e.bot._rw_cached().get("fetched_at")


def test_main_menu_without_token_says_how_to_set_it():
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, FakeRailway())
        e.text("/start")
        assert "توکن تنظیم نشده" in e.last_view()
        assert "rw:menu" in json.dumps(e.api.sent[-1].get("kb") or {}, ensure_ascii=False)


def test_railway_panel_and_token_set_from_bot_deletes_message():
    """روی صفحهٔ «🚂 ریلوی» توکن فرستاده می‌شود؛ پیام پاک و اطلاعات خوانده می‌شود."""
    fake = FakeRailway()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        e.tap("rw:menu")
        assert "حسابِ Railway" in e.last_view() and "توکنِ Railway تنظیم نشده" in e.last_view()
        e.tap("rw:tok")
        e.text("f0f0f0f0-1111-2222-3333-444455556666", mid=77)
        assert e.db.kv_get("railway:token").startswith("f0f0f0f0")
        assert any(x["message_id"] == 77 for x in e.api.deletes), "پیامِ توکن باید پاک شود"
        assert "5.00" in e.last_view(), "بعد از ثبتِ توکن، اطلاعات باید خوانده شود"
        # بروزرسانی و پاک‌کردن
        e.tap("rw:refresh")
        view = e.last_view()
        assert "اعتبارِ باقی‌مانده" in view and "$4.90" in view and "از $5.00" in view
        assert "٪" in view, "درصدِ مصرف (مثل پنلِ ریلوی) باید بیاید"
        e.tap("rw:clr")
        assert not e.db.kv_get("railway:token")
        assert "توکنِ ربات پاک شد" in e.last_view()


def test_railway_token_env_fallback_and_project_id_override():
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, FakeRailway())
        e.settings.railway_token = "env-token-1234567890"
        e.settings.railway_project_id = "e5c6b095-6ef4-46a8-99c1-fce2b653f306"
        asyncio.new_event_loop().run_until_complete(e.bot.rw_startup())
        assert e.bot._rw_cached()["plan"] == "HOBBY"
        e.db.kv_set("railway:token", "kv-token-abcdefghij")     # مقدارِ ربات اولویت دارد
        assert e.bot._rw_token() == "kv-token-abcdefghij"


def test_railway_errors_never_break_the_menu():
    """توکنِ خراب/شبکهٔ قطع ⇒ پیامِ روشن در پنل، بدونِ کرش."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, FakeRailway(error="Not Authorized"))
        e.settings.railway_token = "bad-token-1234567890"
        asyncio.new_event_loop().run_until_complete(e.bot.rw_startup())
        e.text("/start")
        assert "🚂" in e.last_view()                     # صفحهٔ اصلی سالم است
        e.tap("rw:menu")
        assert "Not Authorized" in e.last_view()
        # حالا خطای شبکه
        class Boom:
            def __call__(self, url, body):
                raise RW.RailwayError("ارتباط با Railway نشد")
        e.bot.rw_transport = Boom()
        e.tap("rw:refresh")
        assert "ارتباط با Railway نشد" in e.last_view()


def test_env_example_documents_the_new_variables():
    """② بخشِ «وریبل موقع نصب»: نام‌های محیطی باید مستند باشند."""
    txt = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text(encoding="utf-8")
    for key in ("RAILWAY_TOKEN=", "RAILWAY_PROJECT_ID=", "NOTIFY_SCAN_DONE=",
                "GH_BACKUP_REPO=", "BACKUP_KEY="):
        assert key in txt, "کلیدِ %s در .env.example نیست" % key
    # و در Settings هم خوانده می‌شوند
    s = Settings(bot_token="t", owner_id=1)
    assert hasattr(s, "railway_token") and hasattr(s, "railway_project_id")
    assert isinstance(s.notify_scan_done, bool)


# ───────────────────────── ③ نوتیفِ پایانِ اسکن ─────────────────────────

def test_scan_done_notification_is_sent_by_default():
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, FakeRailway())
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.api.sent.clear()
        cid = _scan(e)
        notes = [m for m in e.api.sent if "🔔" in str(m.get("text") or "")]
        assert notes, "باید پیامِ نوتیفِ پایانِ اسکن بیاید"
        txt = notes[0]["text"]
        assert "اسکن تمام شد" in txt and "مدت" in txt and "گروه‌های تکراری" in txt
        assert "کانالِ تست" in txt
        # دکمهٔ «دیدنِ گروه‌ها» فقط وقتی گروهی هست
        datas = {b.get("callback_data") for row in (notes[0].get("kb") or {}).get("inline_keyboard", [])
                 for b in row}
        assert any(str(d).startswith("l:") for d in datas) or not e.db.groups_of_scan(
            e.db.last_scan(cid)["id"])
        # گزارشِ نهایی همچنان «آخرین چیزی» است که کاربر می‌بیند
        assert "اسکن تمام شد" in e.last_view() and "🔔" not in e.last_view()


def test_scan_done_notification_can_be_turned_off_in_settings():
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, FakeRailway())
        e.tap("st:notify_scan_done")
        e.tap("stv:notify_scan_done:0")                 # خاموش از روی صفحهٔ تنظیم
        assert str(e.bot._setting_display("notify_scan_done")).lower() in ("0", "خاموش")
        e.api.sent.clear()
        _scan(e)
        assert not [m for m in e.api.sent if "🔔" in str(m.get("text") or "")], \
            "با خاموش‌بودنِ گزینه نباید نوتیف بیاید"


def test_canceled_scan_also_notifies_with_its_own_icon():
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, FakeRailway())
        e.api.sent.clear()
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        e.tap("scan:cancel")                            # توقفِ وسطِ کار
        e.wait_scan()
        notes = [m for m in e.api.sent if "⏹" in str(m.get("text") or "") and "اسکن کنسل شد" in str(m.get("text") or "")]
        assert notes, "کنسل هم باید نوتیف بدهد: %s" % [m.get("text", "")[:40] for m in e.api.sent]


def test_startup_refresh_and_health_keys():
    """/health هم خلاصهٔ Railway را نشان می‌دهد (بی‌توکن/بی‌رمز)."""
    import socket
    from app.bot_app import BotApp                    # noqa: E402
    from app.db import Db                             # noqa: E402
    from app.user_client import UserClient            # noqa: E402
    import main as M                                  # noqa: E402
    from dev.fake_telegram import FakeApi             # noqa: E402

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()

    async def go():
        with tempfile.TemporaryDirectory() as d:
            db = Db(str(Path(d) / "h.db"))
            st = Settings(bot_token="t", owner_id=OWNER, db_path=str(Path(d) / "x.db"),
                          railway_token="tok-123456789")
            api = FakeApi()
            bot = BotApp(api, db, st, UserClient(0, "", ""))
            bot.rw_transport = FakeRailway()
            await bot.rw_startup()
            import aiohttp
            runner = await M.health_server(db, bot, port)
            try:
                async with aiohttp.ClientSession() as cl:
                    async with cl.get("http://127.0.0.1:%d/health" % port) as r:
                        return await r.json()
            finally:
                await runner.cleanup()
                db.close()

    body = asyncio.new_event_loop().run_until_complete(go())
    for k in ("railway_token", "railway_plan", "railway_days_left", "railway_credit",
              "railway_credit_left", "railway_usage", "railway_error"):
        assert k in body, sorted(body)
    assert body["railway_token"] is True and body["railway_plan"] == "HOBBY"
    assert body["railway_days_left"] == 29 and body["railway_credit"] == 5.0
    assert body["railway_credit_left"] == 4.9 and body["railway_usage"] == 0.1
    assert body["rev"] == "2026-10-07-dk18"
