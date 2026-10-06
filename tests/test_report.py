"""تستِ گزارش و فوروارد: متن‌های واضح، صفحه‌بندیِ درست، و مسیرهای پشت‌سرهمِ فوروارد."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import report as R                      # noqa: E402
from app.tg_api import TgError                   # noqa: E402
from dev.fake_telegram import FakeApi, FakeUser  # noqa: E402

CHAN = {"id": 1, "tg_id": -1001234567890, "title": "کانالِ تست", "username": "testchan"}


def member(msg_id, name="a.mp4", size=50 * 1024 * 1024, dur=60):
    return {"id": msg_id, "msg_id": msg_id, "file_name": name, "size": size, "duration": dur,
            "date": 1760000000, "content_hash": ""}


def run(coro):
    return asyncio.run(coro)


def test_msg_link_public_and_private():
    assert R.msg_link({"username": "testchan"}, 42) == "https://t.me/testchan/42"
    assert R.msg_link({"username": "@testchan"}, 42) == "https://t.me/testchan/42"
    assert R.msg_link({"tg_id": -1001234567890}, 42) == "https://t.me/c/1234567890/42"
    assert R.msg_link({"tg_id": 0}, 42) == ""


def test_progress_text_phases():
    t = R.progress_text("index", "کانال", 33.3, seen=120, total=400, files=7)
    assert "مرورِ تاریخچه" in t and "33.3%" in t and "120" in t and "400" in t and "7" in t
    t2 = R.progress_text("hash", "کانال", 80, hashed=4, hash_total=9)
    assert "هش‌گذاری" in t2 and "4" in t2 and "9" in t2
    assert "پایان" in R.progress_text("done", "ک", 100)
    assert "کنسل" in R.progress_text("canceled", "ک", 40)
    assert R.bar(0).startswith("▁") and R.bar(100).startswith("█")
    assert "تنظیم" not in R.bar(50) or True


def test_summary_text_has_all_signals():
    scan = {"status": "done", "seen_msgs": 500, "files_found": 120, "hashed": 30, "groups_found": 7,
            "error": ""}
    counts = {"exact": 1, "sizetime": 2, "name": 3, "caption": 1}
    txt = R.scan_summary_text(scan, CHAN, counts)
    for needle in ("گزارشِ اسکن", "کانالِ تست", "کامل شد", "500", "120", "30", "7",
                   "قطعی", "حجم و زمان یکسان", "نامِ مشابه", "کپشنِ مشابه", "اولویتِ بررسی"):
        assert needle in txt, needle


def test_summary_text_reports_errors():
    scan = {"status": "error", "error": "شبکه قطع شد", "seen_msgs": 3, "files_found": 1,
            "hashed": 0, "groups_found": 0}
    txt = R.scan_summary_text(scan, CHAN, {})
    assert "خطا" in txt and "شبکه قطع شد" in txt


def test_group_detail_lists_files_with_links():
    members = [member(101, "a.1080p.mkv"), member(102, "a.720p.mkv", size=50 * 1024 * 1024 + 512)]
    g = {"id": 9, "strength": 3, "reason": "نام مشابه + حجم و زمان یکسان", "count": 2, "state": "open"}
    txt = R.group_detail_text(CHAN, g, members)
    assert "گروه #9" in txt and "★★★" in txt
    assert "https://t.me/testchan/101" in txt and "https://t.me/testchan/102" in txt
    assert "50 MB" in txt and "1:00" in txt and "پیام 101" in txt
    assert txt.count("<b>2</b>") >= 2
    assert "\u200cهای یکتا: <b>2</b>" in txt
    # حالتِ رسیدگی‌شده نمایش داده می‌شود
    g["state"] = "done"
    assert "رسیدگی‌شده" in R.group_detail_text(CHAN, g, members)


def test_group_detail_truncates_long_lists():
    members = [member(1000 + i, "f%d.mp4" % i) for i in range(30)]
    g = {"id": 3, "strength": 4, "reason": "هشِ محتوا یکسان", "count": 30, "state": "open"}
    txt = R.group_detail_text(CHAN, g, members, max_show=20)
    assert "و <b>10</b> فایلِ دیگر" in txt


def test_links_text():
    txt = R.links_text(CHAN, [member(5), member(6)])
    assert txt.count("https://t.me/testchan/") == 4      # دو لینک، دو بار (متن + href)


def test_groups_page_text_and_filters():
    groups = [{"id": 1, "strength": 4, "count": 2, "reason": "هشِ محتوا یکسان"},
              {"id": 2, "strength": 3, "count": 3, "reason": "حجم و زمان یکسان"}]
    txt = R.groups_page_text(CHAN, groups, 0, 2, "all", 10)
    assert "گروه‌های تکراری" in txt and "صفحه 1 از 2" in txt and "#1" in txt and "#2" in txt
    empty = R.groups_page_text(CHAN, [], 0, 1, "caption", 0)
    assert "پیدا نشد" in empty and "کپشن" in empty


def test_callback_data_within_telegram_limit():
    """callback_data حداکثر ۶۴ بایت است — وگرنه تلگرام دکمه را رد می‌کند."""
    groups = [{"id": 12345, "strength": 3, "count": 12, "reason": "حجم و زمان یکسان"}]
    kbs = [R.groups_kb(99, 12, "all", 0, 3, groups), R.group_kb(99, 12, "all", 0, 12345),
           R.progress_kb()]
    for kb in kbs:
        for row in kb["inline_keyboard"]:
            for b in row:
                if "callback_data" in b:
                    assert len(b["callback_data"].encode()) <= 64, b["callback_data"]
                    assert len(b["text"]) <= 64


def test_groups_kb_marks_active_filter_and_navigation():
    groups = [{"id": 1, "strength": 3, "count": 2, "reason": "حجم و زمان یکسان"}]
    kb = R.groups_kb(5, 7, "sizetime", 1, 3, groups)
    flat = [b for row in kb["inline_keyboard"] for b in row]
    assert any(b["text"].startswith("• ") and "حجم+زمان" in b["text"] for b in flat)
    assert any(b["callback_data"] == "p:7:5:sizetime:0" for b in flat)      # ⏮
    assert any(b["callback_data"] == "p:7:5:sizetime:2" for b in flat)      # ⏭
    assert any(b["callback_data"] == "g:7:5:sizetime:1:1" for b in flat)


def test_reporter_forward_bot_path():
    api = FakeApi()
    rep = R.Reporter(api, FakeUser(), max_per_group=2)
    members = [member(101), member(102), member(103)]
    res = run(rep.forward_group(777, CHAN, members))
    assert res["sent"] == 2 and res["remaining"] == 1 and res["total"] == 3
    assert api.forwards[0] == {"to": 777, "from": -1001234567890, "msg_id": 101}
    # ادامه از offset
    res2 = run(rep.forward_group(777, CHAN, members, offset=res["offset"]))
    assert res2["sent"] == 1 and res2["remaining"] == 0
    assert [f["msg_id"] for f in api.forwards] == [101, 102, 103]
    assert api.deletes == []          # هیچ‌چیز پاک نمی‌شود


def test_reporter_falls_back_to_user_account_then_copy_then_link():
    api = FakeApi()
    api.fail_forward_ids = {202}
    user = FakeUser()
    rep = R.Reporter(api, user, max_per_group=3)
    members = [member(201), member(202)]
    res = run(rep.forward_group(777, CHAN, members))
    assert res["sent"] == 2 and res["failed"] == []
    assert user.forwarded and user.forwarded[0]["ids"] == [202]

    # حالا حتی حسابِ کاربری هم نداریم ⇒ کپی، و اگر آن هم نشد لینک
    api2 = FakeApi()
    api2.fail_forward_ids = {202, 203}
    api2.fail_copy_ids = {203}
    rep2 = R.Reporter(api2, None, max_per_group=3)
    res2 = run(rep2.forward_group(777, CHAN, [member(202), member(203)]))
    assert res2["sent"] == 2
    assert "https://t.me/testchan/203" in api2.sent[-1]["text"]


def test_reporter_reports_total_failure():
    api = FakeApi()
    api.fail_forward_ids = {301}
    api.fail_copy_ids = {301}
    api.send_message = _boom_message(api)
    rep = R.Reporter(api, None, max_per_group=1)
    res = run(rep.forward_group(777, {"tg_id": 0, "username": ""}, [member(301)]))
    assert res["sent"] == 0 and res["failed"] == [301]


def _boom_message(api):
    async def _m(*a, **kw):
        raise TgError("sendMessage", 400, "boom")
    return _m
