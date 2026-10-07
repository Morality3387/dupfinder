"""تست‌های DK-16 — پشتیبانِ هش‌ها + استارتِ تازه + /health.

خواسته‌های کاربر:
 ① «ریلوی ۳۰ روزه است و بعد باید ربات را روی اکانتِ جدید ببرم؛ بشود اطلاعاتِ هش را جایی آپلود
    کند؟ مثلاً برای هر کانال یک پوشه، تا با اکانتِ جدید از صفر اسکن نکند و هش‌ها را از آنجا بخواند»
 ② «دو ساعت گذشته و اسکن تمام نشده — طبیعی است؟» (اسکن با ری‌استارت قطع شده بود و هیچ‌کس خبر
    نداشت) ⇒ در استارت، اسکنِ نیمه‌کاره «متوقف‌شده» علامت می‌خورد و به مالک اطلاع می‌رسد
 ③ «/health جزئیاتِ اسکن را نشان بدهد» ⇒ فاز/درصد/هش‌شده از کل + شمارشِ هش‌ها
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import backup as B                          # noqa: E402
from app.config import Settings                      # noqa: E402
from tests.test_bot_flow import CHAT, OWNER, Env     # noqa: E402


def _env(d, **kw):
    e = Env(Path(d), **kw)
    e.text("/start")
    return e


def _doc_msg(e, data, *, name="dupfinder-hashes_x_1.json.gz", mid=4242, caption="", fwd=False):
    """پیامی که یک فایلِ پشتیبان دارد (کاربر فرستاده یا فوروارد کرده)."""
    if fwd:
        # مثلِ تلگرامِ واقعی: پیامِ فورواردشده هم `document` دارد، ولی فایلش در دسترسِ ربات نیست
        m = {"chat": {"id": CHAT}, "from": {"id": OWNER}, "caption": caption, "message_id": mid,
             "document": {"file_id": str(mid), "file_name": name, "mime_type": "application/gzip",
                          "file_size": len(data)},
             "forward_origin": {"type": "channel", "chat": {"id": -100777, "title": "آرشیو"}}}
    else:
        m = dict(e.api.backup_message(bytes(data), name=name, mid=mid, caption=caption))
        m["chat"] = {"id": CHAT}
        m["from"] = {"id": OWNER}
    return e.run(e.bot.handle_message(m))


# ───────────────── ① ساخت و بازگرداندنِ پشتیبان ─────────────────

def test_export_then_import_restores_hashes_without_rescanning():
    """قلبِ خواسته: هش‌ها در فایل می‌روند و روی رباتِ تازه **بدونِ اسکن** برمی‌گردند."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.setting_hash_scope = None
        e.settings.hash_scope = "full"
        e.settings.hash_mode = "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        n_hashed = e.db.count_hashed_scope()
        assert n_hashed > 0, "اسکنِ اول باید هش بسازد"

        data, rep, name = B.export_channel(e.db, cid, rev="test")
        assert rep["count"] == e.db.count_files(cid) and rep["hashed"] == n_hashed
        assert name.startswith("dupfinder-hashes_") and data[:2] == b"\x1f\x8b"     # gzip

        # رباتِ تازه: همان کانال، ولی بدونِ هش (شبیه اکانتِ جدید که ایندکس ندارد)
        with tempfile.TemporaryDirectory() as d2:
            e2 = _env(d2)
            cid2 = e2.add_channel()                      # همان @testchan ⇒ همان tg_id
            e2.db.conn.execute("DELETE FROM files WHERE channel_id=?", (cid2,))
            e2.db.conn.commit()
            assert e2.db.count_hashed_scope() == 0

            payload = B.load(data)
            plan = B.import_plan(e2.db, payload)
            st = B.apply_import(e2.db, plan)
            assert st["hashes"] == n_hashed, "همهٔ هش‌ها باید برگردند (%s)" % st
            assert e2.db.count_hashed_scope("full") == n_hashed
            assert e2.db.count_files(cid2) == rep["count"]
            # نام/کپشن/حجم هم برگشته ⇒ مقایسه بدونِ دانلود کار می‌کند
            f = e2.db.files_of_channel(cid2)[0]
            assert f["file_name"] and f["size"] > 0


def test_import_does_not_lose_hash_when_scan_runs_again():
    """بعد از بازگرداندن، اسکنِ «ادامه» نباید هش‌های برگشته را از نو دانلود کند."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        data, rep, _ = B.export_channel(e.db, cid)
        hashes_before = {f["msg_id"]: f["content_hash"] for f in e.db.files_of_channel(cid)
                         if f["content_hash"]}

        e.db.conn.execute("UPDATE files SET content_hash='', hash_scope='' WHERE channel_id=?", (cid,))
        e.db.conn.commit()
        B.apply_import(e.db, B.import_plan(e.db, B.load(data)))
        after = {f["msg_id"]: f["content_hash"] for f in e.db.files_of_channel(cid) if f["content_hash"]}
        assert after == hashes_before

        e.user.hash_batches.clear()
        e.tap("scan:cont:%d" % cid)                  # اسکنِ ادامه: نامزدها همان‌ها هستند
        e.wait_scan()
        # هیچ دانلودی برای هش لازم نیست: بچ‌ها یا خالی‌اند یا فقط برای فایل‌های بدونِ هش
        assert not e.user.hash_batches, "با هش‌های موجود، hash_batch نباید صدا زده شود"


def test_restore_from_sent_document_flow():
    """کاربر فایل را برای ربات می‌فرستد ⇒ خلاصه + «✅ بازگردان» ⇒ بازگرداندن."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        data, rep, name = B.export_channel(e.db, cid)
        e.db.conn.execute("UPDATE files SET content_hash='', hash_scope=''")
        e.db.conn.commit()

        _doc_msg(e, data, name=name)
        assert "فایلِ پشتیبان شناخته شد" in e.last_view()
        assert "کانال پیدا شد" in e.last_view()
        e.tap("bk:yes")
        assert "بازگرداندن تمام شد" in e.last_view(), e.last_view()
        assert e.db.count_hashed_scope() == rep["hashed"]


def test_restore_from_forwarded_document_uses_a_copy_in_our_chat():
    """اگر کاربر پشتیبان را **فوروارد** کند (فایلش در دسترسِ ربات نیست)، ربات کپی می‌گیرد."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        data, rep, _ = B.export_channel(e.db, cid)
        e.db.conn.execute("UPDATE files SET content_hash='', hash_scope=''")
        e.db.conn.commit()
        # فوروارد: پیام `document` ندارد، فقط forward_origin
        nmid = e.api.next_mid()          # همان شناسه‌ای که fake برای «کپیِ فایل» برمی‌گردانَد
        e.api.docs[str(nmid)] = data     # محتوای کپیِ فایل در چتِ خودمان
        _doc_msg(e, data, name="dupfinder-hashes_آرشیو_1.json.gz", mid=777, fwd=True)
        assert "فایلِ پشتیبان شناخته شد" in e.last_view(), e.last_view()
        e.tap("bk:yes")
        assert e.db.count_hashed_scope() == rep["hashed"]
        fwd = [c for c in e.api.calls if c[0] == "forwardMessage"]
        assert fwd, "باید یک کپی از فایل در چتِ خودمان گرفته شود"


def test_snapshot_backup_has_all_channels_and_settings_but_no_secrets():
    """پشتیبانِ کامل: همهٔ کانال‌ها + تنظیمات، ولی بدونِ توکن/سشن/api_hash."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.db.kv_set("setting:th_name_ratio", "0.91")
        e.db.kv_set("session_string", "SECRET-SESSION")
        e.db.kv_set("api_hash", "SECRET-HASH")
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        data, rep, name = B.export_snapshot(e.db, rev="test")
        assert name.startswith("dupfinder-backup_") and rep["channels"] >= 1
        payload = B.load(data)
        assert payload["scope"] == "snapshot"
        assert payload["settings"].get("setting:th_name_ratio") == "0.91"
        raw = json.dumps(payload, ensure_ascii=False)
        for secret in ("SECRET-SESSION", "SECRET-HASH", "bot_token"):
            assert secret not in raw, secret


def test_menu_buttons_and_auto_toggle():
    """منو: دکمه‌های پشتیبان + روشن/خاموش‌کردنِ خودکار."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        e.tap("bk:menu")
        txt = e.last_view()
        assert "پشتیبانِ هش‌ها" in txt and "خودکار" in txt
        flat = [b.get("text", "") for row in e.last_view_kb() for b in row]
        assert any("پشتیبانِ همه" in t for t in flat)
        assert any("بازگرداندن" in t for t in flat)
        assert e.bot._backup_auto() is True
        e.tap("bk:auto")
        assert e.bot._backup_auto() is False
        e.tap("bk:auto")
        assert e.bot._backup_auto() is True

        e.tap("bk:one:%d" % cid)
        assert [c for c in e.api.calls if c[0] == "sendDocument"], "فایلِ پشتیبان باید فرستاده شود"
        assert "فرستاده شد" in e.last_view()


def test_auto_backup_after_scan_sends_document_and_edits_next_time():
    """خودکار: پس از اسکنی که هش بسازد، فایل می‌رود؛ بارِ بعد همان پیام به‌روز می‌شود."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        docs = [c for c in e.api.calls if c[0] == "sendDocument"]
        assert docs, "پایانِ اسکن باید پشتیبان بفرستد"
        assert e.api.media_edits == [], "بارِ اول پیامِ قبلی وجود ندارد"
        # پشتیبانِ ذخیره‌شده قدیمی/ناقص است (۵ از ۱۳) و بارِ بعد باید به‌روز شود
        e.db.kv_set("backup:hashes:%d" % cid, 5)
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        assert e.api.media_edits, "بارِ دوم باید همان پیامِ پشتیبان را به‌روز کند"


def test_pending_restore_suggests_backup_before_scan():
    """اگر فایل را فرستاده و بعد «اسکن» بزند، ربات اول یادآوری می‌کند (ترتیبِ درست)."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        data, _rep, name = B.export_channel(e.db, cid)
        _doc_msg(e, data, name=name)                  # فایل آماده است (بدونِ بازگرداندن)
        e.tap("scan:full:%d" % cid)
        assert "فایلِ پشتیبان" in e.last_view() and "بازگردان و بعد اسکن" in e.last_view()
        assert e.bot.scan in ({}, None) or not e.bot.scan.get("task"), "اسکن نباید شروع شود"
        assert "bk:yes" in e.view_datas()


# ───────────────── ② اسکنِ نیمه‌کاره در استارت ─────────────────

def test_stale_running_scan_is_marked_and_owner_is_told():
    """اسکنِ «در جریان»ِ مانده از ری‌استارت ⇒ «متوقف‌شده» + پیام به مالک + دکمهٔ ادامه."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        cid = e.add_channel()
        sid = e.db.create_scan(cid, {"full": True})
        assert e.db.stale_running_scans() and e.db.stale_running_scans()[0]["id"] == sid
        n = e.run(e.bot.mark_stale_scans())
        assert n == 1
        row = e.db.get_scan(sid)
        assert row["status"] == "canceled" and row["phase"] == "canceled" and row["finished_at"] > 0
        assert e.db.stale_running_scans() == []            # دیگر تکرار نمی‌شود
        txt = e.api.sent[-1]["text"] if e.api.sent else ""
        assert "اسکنِ قبلی قطع شد" in txt
        assert "scan:cont:%d" % cid in json.dumps(e.api.sent[-1].get("kb") or {}, ensure_ascii=False)


def test_health_snapshot_exposes_scan_details():
    """③ /health: فاز/درصد/هش‌شده از کل + شمارشِ هش‌های کامل و نمونه‌ای."""
    with tempfile.TemporaryDirectory() as d:
        e = _env(d)
        assert e.bot.scan_snapshot()["state"] == "idle"
        cid = e.add_channel()
        e.settings.hash_scope, e.settings.hash_mode = "full", "all"
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        snap = e.bot.scan_snapshot()
        assert snap["state"] == "finished" and snap["status"] == "done"
        assert snap["files"] > 0 and snap["groups"] >= 0
        assert e.db.count_hashed_scope("full") > 0 and e.db.count_hashed_scope("sample") == 0
        assert e.db.stats()["hashed"] == e.db.count_hashed_scope()
        assert getattr(e.bot, "_stale_marked", 0) == 0     # اسکنِ سالم ⇒ چیزی علامت نمی‌خورد


def test_health_endpoint_reports_scan_and_hash_details():
    """③ خودِ `/health`: همان کلیدهایی که برای عیب‌یابی از بیرون لازم است."""
    import socket
    from app.bot_app import BotApp                    # noqa: E402
    from app.db import Db                             # noqa: E402
    from app.user_client import UserClient            # noqa: E402
    import main as M                                  # noqa: E402
    from dev.fake_telegram import FakeApi, FakeUser   # noqa: E402

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()

    async def go():
        with tempfile.TemporaryDirectory() as d:
            db = Db(str(Path(d) / "h.db"))
            settings = Settings(bot_token="t", owner_id=OWNER, db_path=str(Path(d) / "x.db"),
                                hash_scope="full", hash_mode="all")
            bot = BotApp(FakeApi(), db, settings, UserClient(0, "", ""))
            runner = await M.health_server(db, bot, port)
            try:
                import aiohttp
                async with aiohttp.ClientSession() as cl:
                    async with cl.get("http://127.0.0.1:%d/health" % port) as r:
                        assert r.status == 200
                        return await r.json()
            finally:
                await runner.cleanup()
                db.close()

    body = asyncio.new_event_loop().run_until_complete(go())
    for k in ("ok", "rev", "files", "hashed", "hash_full", "hash_sample", "hash_mode", "hash_scope",
              "hash_full_max_mb", "stale_scans", "scan_running", "scan_state"):
        assert k in body, "کلیدِ «%s» در /health نیست: %s" % (k, sorted(body))
    assert body["rev"] == "2026-10-07-dk18"
    assert body["hash_mode"] == "all" and body["hash_scope"] == "full"
    assert body["scan_state"] == "idle" and body["stale_scans"] == 0
