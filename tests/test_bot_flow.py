"""تستِ سرتاسریِ ربات — همان مسیری که کاربرِ واقعی در تلگرام طی می‌کند.

هیچ شبکه‌ای در کار نیست: `FakeApi` جای Bot API و `FakeUser` جای کلاینتِ کاربری
می‌نشیند، ولی خودِ منطقِ ربات/اسکن/گزارش واقعی اجرا می‌شود. برای اینکه تسکِ اسکن
بینِ فراخوانی‌ها زنده بماند، همه‌چیز روی **یک** حلقهٔ asyncio اجرا می‌شود.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bot_app import BotApp                     # noqa: E402
from app.config import Settings                    # noqa: E402
from app.db import Db                              # noqa: E402
from dev.fake_telegram import FakeApi, FakeUser, channel_dataset  # noqa: E402

CHAT = 111
OWNER = 1
BOT_ID = 999


class Env:
    """محیطِ تست با حلقهٔ asyncioِ پایدار."""

    def __init__(self, tmp: Path, *, ready=True, delay=0.0, total_hint=0, **setting_kw):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.db = Db(str(tmp / "bot.db"))
        ds = channel_dataset()
        self.user = FakeUser(videos={55: ds["videos"]}, contents=ds["contents"],
                             titles={55: ds["title"],
                                     77: {"tg_id": 77, "title": "کانال دو", "username": "chan2", "kind": "channel"}},
                             ready=ready, delay=delay, total_hint=total_hint)
        self.api = FakeApi(chats={55: {"id": 55, "title": "کانالِ تست", "username": "testchan"},
                                  77: {"id": 77, "title": "کانال دو", "username": "chan2"}})
        self.settings = Settings(bot_token="test", owner_id=OWNER, db_path=str(tmp / "x.db"),
                                 page_size=3, progress_interval=0.0, max_forward_per_group=2)
        for k, v in setting_kw.items():
            setattr(self.settings, k, v)
        self.bot = BotApp(self.api, self.db, self.settings, self.user)
        self.ds = ds

    # ── محرک‌ها ──
    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def text(self, t, *, uid=OWNER, chat=CHAT, mid=1, fwd=None):
        m = {"chat": {"id": chat}, "from": {"id": uid}, "text": t, "message_id": mid}
        if fwd:
            m["forward_origin"] = fwd
        return self.run(self.bot.handle_message(m))

    def tap(self, data, *, mid=5, uid=OWNER, chat=CHAT):
        return self.run(self.bot.handle_callback({"id": "cq", "data": data, "from": {"id": uid},
                                                 "message": {"chat": {"id": chat}, "message_id": mid}}))

    def wait_scan(self):
        sc = self.bot.scan or {}
        t = sc.get("task")
        if t is not None and not t.done():
            self.run(t)

    def add_channel(self, username="@testchan"):
        self.tap("ch:add")
        self.text(username)
        return self.db.list_channels()[-1]["id"]

    def last(self):
        return self.api.sent[-1]["text"] if self.api.sent else ""

    def last_view(self):
        """آخرین چیزی که کاربر می‌بیند: بر اساسِ ترتیبِ واقعیِ فراخوانی‌ها."""
        for method, params in reversed(self.api.calls):
            if method in ("sendMessage", "editMessageText"):
                return str(params.get("text") or "")
        return ""

    def kb_btn(self, contains, *, sent=True):
        pool = self.api.sent if sent else []
        for m in reversed(pool):
            for row in ((m.get("kb") or {}).get("inline_keyboard") or []):
                for b in row:
                    if contains in str(b.get("text", "")):
                        return b
        for e in reversed(self.api.edits):
            for row in ((e.get("kb") or {}).get("inline_keyboard") or []):
                for b in row:
                    if contains in str(b.get("text", "")):
                        return b
        return None

    def close(self):
        try:
            self.loop.close()
        except Exception:
            pass
        self.db.close()
        asyncio.set_event_loop(None)


def test_start_menu_help_and_owner_only():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.text("/start")
        assert "منوی اصلی" in e.last()
        assert "setMyCommands" in e.api.methods()
        e.text("/help")
        h = e.last()
        for needle in ("نامِ فایل", "کپشن", "حجم + زمان", "هشِ محتوا", "تاریخچهٔ کامل",
                       "حسابِ کاربری", "پاک/ویرایش نمی‌کند", "نوارِ درصد", "توقف و کنسل"):
            assert needle in h, needle
        e.text("/history")
        assert "تاریخچهٔ کامل" in e.last()
        e.text("/status")
        assert "وضعیت" in e.last() and "حسابِ کاربری" in e.last()
        # غیرمالک هیچ داده‌ای نمی‌بیند
        before = len(e.api.sent)
        e.text("/start", uid=4242)
        assert "خصوصی" in e.last() and len(e.api.sent) == before + 1
        e.tap("ch:list", uid=4242)
        assert "خصوصی" in e.last()
        e.close()


def test_add_channel_three_ways_and_dedup():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel("@testchan")
        assert "کانال ذخیره شد" in e.last()
        c = e.db.get_channel(cid)
        assert c["tg_id"] == 55 and c["username"] == "testchan"
        # ۲) پستِ فورواردشده
        e.text("", fwd={"type": "channel", "chat": {"id": 77, "title": "کانال دو", "username": "chan2"}})
        assert "کانال ذخیره شد" in e.last()
        assert len(e.db.list_channels()) == 2
        # ۳) لینک و شناسهٔ عددی ⇒ بدونِ ردیفِ تکراری
        e.tap("ch:add")
        e.text("https://t.me/chan2")
        assert len(e.db.list_channels()) == 2
        e.tap("ch:add")
        e.text("-1001234567890")
        assert len(e.db.list_channels()) == 3
        # لینکِ دعوتِ خصوصی پشتیبانی نمی‌شود
        e.tap("ch:add")
        e.text("https://t.me/+AbCdEf")
        assert "+" in e.last() and "پشتیبانی نمی‌شود" in e.last()
        # فهرستِ کانال‌ها با دکمهٔ هر کانال
        e.tap("ch:list")
        assert "کانال‌های شما" in e.last()
        assert e.kb_btn("کانالِ تست") is not None
        # حذفِ کانال از فهرست (فقط از دیتابیسِ ربات)
        cid2 = e.db.list_channels()[-1]["id"]
        e.tap("ch:del:%d" % cid2)
        assert "هیچ فایلی در تلگرام پاک نشد" in e.last()
        assert e.db.get_channel(cid2) is None
        e.close()


def test_full_scan_report_forward_and_actions():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), total_hint=40)
        e.text("/start")
        cid = e.add_channel()
        # صفحهٔ کانال و شروعِ اسکن از دکمهٔ اسمِ کانال
        e.tap("c:%d" % cid)
        assert "کانالِ تست" in e.last() and "فایل" in e.last()
        btn = e.kb_btn("اسکن کامل")
        assert btn["callback_data"] == "scan:full:%d" % cid
        e.tap(btn["callback_data"])
        e.wait_scan()
        # نوارِ درصد: چند ویرایش با درصدِ یکنوا
        progs = [x["text"] for x in e.api.edits if "%" in x["text"]]
        assert len(progs) >= 3, progs
        pcts = [float(p.split("%")[0].split()[-1]) for p in progs]
        assert pcts == sorted(pcts) and pcts[-1] == 100.0
        assert "کنسل" in str(e.api.edits[0].get("kb")) or "توقف" in str(e.api.edits[0].get("kb"))
        final = e.api.edits[-1]["text"]
        assert "اسکن تمام شد" in final and "گروه‌های تکراری" in final
        assert "قطعی" in final and "حجم و زمان یکسان" in final and "نامِ مشابه" in final
        scan_id = e.db.last_scan(cid)["id"]
        assert e.db.get_scan(scan_id)["status"] == "done"
        assert e.db.count_files(cid) == 13
        # فهرستِ گروه‌ها + فیلترها
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        assert "گروه‌های تکراری" in e.last_view() and "دلیل:" in e.last_view()
        e.tap("l:%d:%d:sizetime:0" % (scan_id, cid))
        assert "حجم+زمان" in e.last_view()
        e.tap("l:%d:%d:exact:0" % (scan_id, cid))
        assert "قطعی" in e.last_view()
        e.tap("l:%d:%d:caption:0" % (scan_id, cid))
        assert "کپشن" in e.last_view()
        # باز کردنِ گروهِ «حجم و زمان»
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        g_btn = e.kb_btn("#")
        assert g_btn and g_btn["callback_data"].startswith("g:")
        gid = int(g_btn["callback_data"].split(":")[-1])
        e.tap(g_btn["callback_data"])
        detail = e.last_view()
        assert "دلیلِ تشخیص" in detail and "t.me/testchan/" in detail and "پیام" in detail
        members = e.db.group_members(gid)
        assert len(members) >= 2
        # فوروارد
        e.tap("f:%d:%d:all:0:%d" % (scan_id, cid, gid))
        assert len(e.api.forwards) == 2                      # سقفِ max_forward_per_group=2
        assert e.api.forwards[0]["from"] == 55 and e.api.forwards[0]["to"] == CHAT
        assert "فورواردِ گروه" in e.last()
        if len(members) > 2:
            cont = e.kb_btn("ادامه")
            assert cont is not None
            off = int(cont["callback_data"].split(":")[-1])
            e.tap(cont["callback_data"])
            assert len(e.api.forwards) == min(len(members), 4)
            assert off == 2
        # لینک‌ها، علامت‌زدن، خلاصه
        e.tap("u:%d:%d:%d" % (scan_id, cid, gid))
        assert e.last_view().count("https://t.me/testchan/") >= len(members)
        e.tap("m:%d:%d:%d:done" % (scan_id, cid, gid))
        assert e.db.get_group(gid)["state"] == "done" and "رسیدگی‌شده" in e.last_view()
        e.tap("m:%d:%d:%d:ign" % (scan_id, cid, gid))
        assert e.db.get_group(gid)["state"] == "ignored"
        e.tap("s:%d:%d" % (scan_id, cid))
        assert "گزارشِ اسکن" in e.last_view()
        # 🛡 هیچ پیام/فایلی در کانال پاک یا ویرایش نشده
        assert all(c[1].get("chat_id") == CHAT for c in e.api.calls if c[0] == "deleteMessage")
        assert not any(c[0] == "editMessageText" and c[1].get("chat_id") == 55 for c in e.api.calls)
        assert not any(c[0] in ("deleteMessage", "editMessageText") and c[1].get("from_chat_id") == 55
                       for c in e.api.calls)
        e.close()


def test_scan_without_user_account_shows_history_guidance():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        txt = e.last()
        assert "تاریخچهٔ کانال" in txt and "اتصالِ حساب" in txt and "۳۰ ثانیه" in txt
        assert e.bot.scan is None
        e.tap("scan:limited:%d" % cid)
        assert "حسابِ کاربری" in e.last()
        e.close()


def test_cancel_scan_by_button():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), delay=0.02, total_hint=13)
        cid = e.add_channel()
        e.text("/start")
        e.run(e.bot._start_scan(CHAT, cid, full=True))
        assert e.bot.scan and not e.bot.scan["done"]

        async def cancel_soon():
            for _ in range(400):
                sc = e.bot.scan.get("scanner")
                if sc and sc.progress.files >= 3:
                    break
                await asyncio.sleep(0.005)
            await e.bot._cancel_scan(CHAT)
            await e.bot.scan["task"]
        e.run(cancel_soon())
        res = e.bot.scan["result"]
        assert res.status == "canceled"
        assert e.db.get_scan(res.scan_id)["status"] == "canceled"
        assert 0 < e.db.count_files(cid) < 13
        assert "کنسل" in "".join(x["text"] for x in e.api.edits[-3:])
        e.close()


def test_rescan_finds_new_duplicates_and_continues():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        first = e.db.last_scan(cid)
        assert first["files_found"] == 13
        # دو نسخهٔ تازه از یک فیلم به کانال اضافه می‌شود
        e.user.videos[55] = list(e.user.videos[55]) + [
            {"msg_id": 170, "grouped_id": 0, "date": 1760000000, "doc_id": 9070, "file_unique_id": "U170",
             "file_identify": "9070", "file_name": "Documentary.Ocean.1080p.mkv", "caption": "مستند اقیانوس",
             "size": 90 * 1024 * 1024, "duration": 900, "mime": "video/mp4", "width": 1920, "height": 1080,
             "has_video": 1, "protected": 0},
            {"msg_id": 171, "grouped_id": 0, "date": 1760000000, "doc_id": 9071, "file_unique_id": "U171",
             "file_identify": "9071", "file_name": "Documentary.Ocean.720p.mkv", "caption": "مستند اقیانوس",
             "size": 90 * 1024 * 1024, "duration": 900, "mime": "video/mp4", "width": 1280, "height": 720,
             "has_video": 1, "protected": 0},
        ]
        e.tap("scan:cont:%d" % cid)          # ادامهٔ اسکن: فقط جدیدها
        e.wait_scan()
        last = e.db.last_scan(cid)
        assert last["min_id"] == 150
        assert e.db.count_files(cid) == 15
        groups = e.db.groups_of_scan(last["id"])
        assert any(170 in [m["msg_id"] for m in e.db.group_members(g["id"])] for g in groups)
        e.close()


def test_settings_change_validation_and_reset():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:menu")
        assert "تنظیماتِ تطبیق" in e.last()      # ارسالِ تازه، نه ویرایش
        e.tap("st:size_tol_pct")
        e.text("1.5")
        assert e.settings.size_tol_pct == 1.5 and e.db.kv_get("setting:size_tol_pct") == 1.5
        e.tap("st:hash_mode")
        e.text("all")
        assert e.settings.hash_mode == "all"
        e.tap("st:hash_mode")
        e.text("چیزِ بی‌ربط")
        assert e.settings.hash_mode == "all" and "فقط off" in e.last()
        e.tap("st:size_time_require_one_exact")
        e.text("0")
        assert e.settings.size_time_require_one_exact is False
        e.tap("st:reset")
        assert e.settings.size_tol_pct == 0.5 and e.settings.hash_mode == "candidates"
        e.close()


def test_login_wizard_code_and_2fa_and_session_management():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)
        e.tap("acc:menu")
        assert "حسابِ کاربری" in e.last() and "وصل نیست" in e.last()
        e.tap("acc:login")
        e.text("12345", mid=11)                 # api_id
        assert "api_hash" in e.last()
        e.text("y" * 32, mid=12)                # api_hash
        assert "شماره" in e.last()
        e.text("+989120000000", mid=13)         # phone
        assert "کدِ پیامک" in e.last()
        e.text("1 1 1 1 1", mid=14)             # نیاز به رمزِ دو مرحله‌ای
        assert "رمزِ دو مرحله‌ای" in e.last()
        e.text("secret", mid=15)
        assert "وصل است" in e.last()
        assert e.db.kv_get("session_string") == "FAKE_SESSION"
        assert e.db.kv_get("api_id") == 12345 and e.db.kv_get("api_hash") == "y" * 32
        # پیام‌های حساسِ کاربر از چتِ ربات پاک شده‌اند
        deleted = {c[1]["message_id"] for c in e.api.calls if c[0] == "deleteMessage"}
        assert {11, 12, 13, 14, 15} <= deleted
        e.tap("acc:session")
        assert "رشتهٔ سشن" in e.last() and "FAKE_SESSION" in e.last()
        e.tap("acc:test")
        assert "برقرار" in e.last()
        e.tap("acc:logout")
        assert e.db.kv_get("session_string") == "" and "قطع" in e.last()
        e.close()


def test_login_wrong_code_offers_fresh_code():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)
        e.tap("acc:login")
        e.text("12345", mid=11)
        e.text("z" * 32, mid=12)
        e.text("+989120000000", mid=13)
        e.text("77777", mid=14)                 # کدِ اشتباه
        assert "کد اشتباه" in e.last()
        assert e.bot.pending.get(CHAT) is not None          # وضعیت حفظ می‌شود
        assert e.kb_btn("کدِ تازه")                          # دکمهٔ «کدِ تازه» هست
        n = len(e.user.code_requests)
        e.tap("acc:resend")                                 # درخواستِ کدِ تازه
        assert len(e.user.code_requests) == n + 1 and "کدِ تازه" in e.last()
        e.text("55555", mid=15)                             # کدِ درست
        assert "وصل شد" in e.last() and e.db.kv_get("session_string") == "FAKE_SESSION"
        e.close()


def test_login_expired_code_then_resend_succeeds():
    """همان چیزی که کاربر دید: کدِ منقضی ⇒ پیامِ روشن + دکمهٔ کدِ تازه (نه شروع از صفر)."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)
        e.tap("acc:login")
        e.text("12345", mid=11)
        e.text("z" * 32, mid=12)
        e.text("+989120000000", mid=13)
        e.text("99999", mid=14)                 # کدِ پیامِ قبلی ⇒ منقضی
        assert "باطل/منقضی" in e.last() and "کدِ تازه" in e.last()
        assert e.bot.pending.get(CHAT)["kind"] == "login_code"
        e.tap("acc:resend")
        assert "کدِ تازه فرستاده شد" in e.last()
        e.text("55555", mid=15)
        assert "وصل شد" in e.last()
        e.close()


def test_login_skips_api_steps_when_variables_set():
    """api_id/api_hash از Variables آمده‌اند ⇒ فقط شماره و کد پرسیده می‌شود."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.tap("acc:menu")
        assert "تنظیم شده" in e.last()
        e.tap("acc:login")
        assert "api_id" not in e.last() and "شمارهٔ همان حساب" in e.last()
        assert "گام ۱ از ۲" in e.last()
        kb = e.api.sent[-1]["kb"]                                # دکمهٔ اشتراکِ شماره
        assert kb["keyboard"][0][0].get("request_contact") is True
        e.close()


def test_login_phone_by_contact_button():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.tap("acc:login")
        e.run(e.bot.handle_message({"chat": {"id": CHAT}, "from": {"id": OWNER}, "message_id": 21,
                                    "contact": {"phone_number": "989123456789", "user_id": OWNER}}))
        assert e.user.code_requests == ["+989123456789"]          # نرمال‌سازیِ شماره
        assert "کدِ پیامک/تلگرام" in e.last()
        e.text("55555", mid=22)
        assert "وصل شد" in e.last() and e.db.kv_get("session_string") == "FAKE_SESSION"
        e.close()


def test_login_contact_cannot_be_someone_elses():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.tap("acc:login")
        e.run(e.bot.handle_message({"chat": {"id": CHAT}, "from": {"id": OWNER}, "message_id": 21,
                                    "contact": {"phone_number": "989120000000", "user_id": 987654}}))
        assert "خودتان" in e.last() and e.user.code_requests == []
        e.close()


def test_login_password_retry():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.tap("acc:login")
        e.text("+989120000000", mid=13)
        e.text("11111", mid=14)                    # نیاز به رمزِ دو مرحله‌ای
        assert "رمزِ دو مرحله‌ای" in e.last()
        e.text("nope", mid=15)
        assert "تلاشِ ۱ از ۳" in e.last()
        e.text("secret", mid=16)                   # رمزِ درست
        assert "رمز پذیرفته شد" in e.last() and e.db.kv_get("session_string") == "FAKE_SESSION"
        e.close()


def test_login_password_three_wrong_locks_out():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.tap("acc:login")
        e.text("+989120000000", mid=13)
        e.text("11111", mid=14)
        for i in range(3):
            e.text("bad%d" % i, mid=20 + i)
        assert "سه بار" in e.last() and e.bot.pending.get(CHAT) is None
        e.close()


def test_login_reset_clears_stored_api_keys():
    """اگر api_id اشتباه ذخیره شده باشد، باید راهِ بیرون وجود داشته باشد."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.db.kv_set("api_id", 424242)
        e.db.kv_set("api_hash", "h" * 32)
        e.tap("acc:login")
        e.tap("acc:reset")
        assert "پاک شد" in e.last() and e.settings.api_id == 0 and e.settings.api_hash == ""
        assert e.db.kv_get("api_id") in (0, "0") and e.db.kv_get("api_hash") == ""
        e.tap("acc:login")                       # حالا از گامِ اول شروع می‌شود
        assert "api_id" in e.last()
        e.close()


def test_login_send_code_failure_shows_fix_buttons():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)

        async def boom(phone):
            raise RuntimeError("ApiIdInvalidError: api_id is invalid")
        e.user.send_code = boom
        e.tap("acc:login")
        e.text("+989120000000", mid=13)
        assert "ارسالِ کد ناموفق" in e.last() and "api_id" in e.last()
        assert e.kb_btn("کلیدها")
        e.close()


def test_login_cancel_clears_state():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False, api_id=424242, api_hash="h" * 32)
        e.tap("acc:login")
        e.tap("acc:cancel")
        assert "ورود لغو شد" in e.last() and e.bot.pending.get(CHAT) is None
        e.close()


def test_scan_all_channels_sequentially():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.add_channel("@testchan")
        e.text("", fwd={"type": "channel", "chat": {"id": 77, "title": "کانال دو", "username": "chan2"}})
        e.user.videos[77] = list(e.ds["videos"][:3])
        cid1, cid2 = [c["id"] for c in e.db.list_channels()]
        e.tap("scan:all")                       # پشتِ‌سرهم و کامل اجرا می‌شود
        assert e.db.count_files(cid1) == 13      # کانالِ اول
        assert e.db.count_files(cid2) == 3       # کانالِ دوم
        assert e.db.last_scan(cid1)["status"] == "done"
        assert e.db.last_scan(cid2)["status"] == "done"
        e.close()


def test_forward_falls_back_when_content_is_protected():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        scan_id = e.db.last_scan(cid)["id"]
        gid = e.db.groups_of_scan(scan_id)[0]["id"]
        members = e.db.group_members(gid)
        e.api.fail_forward_ids = {m["msg_id"] for m in members}      # محتوای محافظت‌شده
        e.tap("f:%d:%d:all:0:%d" % (scan_id, cid, gid))
        assert e.user.forwarded, "وقتی فورواردِ ربات رد شود، باید حسابِ کاربری استفاده شود"
        assert "فرستاده‌شده" in e.last()
        e.close()


def test_forward_uses_link_when_everything_blocked():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)          # حسابِ کاربری وصل نیست
        cid = e.add_channel()
        e.user._ready = True                   # فقط برای اجازهٔ اسکن
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        e.user._ready = False
        scan_id = e.db.last_scan(cid)["id"]
        gid = e.db.groups_of_scan(scan_id)[0]["id"]
        members = e.db.group_members(gid)
        e.api.fail_forward_ids = {m["msg_id"] for m in members}
        e.api.fail_copy_ids = {m["msg_id"] for m in members}
        e.tap("f:%d:%d:all:0:%d" % (scan_id, cid, gid))
        assert "https://t.me/testchan/" in e.last() or "t.me/testchan" in "".join(
            x["text"] for x in e.api.sent[-3:])
        e.close()
