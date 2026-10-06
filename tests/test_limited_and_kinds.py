"""تست‌های تکمیلیِ باگ‌های کاربر: media_kinds در اسکن، هشِ کامل، و اسکنِ محدود."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Db                                  # noqa: E402
from app.scanner import Scanner                        # noqa: E402
from dev.fake_telegram import channel_dataset          # noqa: E402
from tests.test_scanner import CFG                     # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _mk(tmp, **over):
    db = Db(str(Path(tmp) / "m.db"))
    ds = channel_dataset()
    from dev.fake_telegram import FakeUser
    user = FakeUser(videos={55: ds["videos"]}, contents=ds["contents"], titles={55: ds["title"]})
    cfg = dict(CFG)
    cfg.update(over)
    return db, user, ds, cfg


def test_scan_with_video_doc_indexes_documents(tmp_path):
    """حالتِ «video+doc» باید سندِ غیرِویدیویی هم ایندکس کند (باگِ msg_to_file)."""
    with tempfile.TemporaryDirectory() as d:
        db, user, ds, cfg = _mk(d, media_kinds="video+doc")
        cid = db.add_channel(55, "کانالِ تست", "testchan")
        chan = db.get_channel(cid)
        res = run(Scanner(db, user, lambda: cfg).run(chan, full=True))
        files = db.files_of_channel(chan["id"])
        mimes = {f["mime"] for f in files}
        assert res.status == "done"
        assert any(m == "application/pdf" for m in mimes), mimes      # سندِ ۱۶۰ ایندکس شد
        assert len(files) == 14                                      # ۱۳ ویدیو + ۱ pdf
        assert res.found == 14
        db.close()


def test_scan_with_video_only_skips_documents(tmp_path):
    with tempfile.TemporaryDirectory() as d:
        db, user, ds, cfg = _mk(d, media_kinds="video")
        cid = db.add_channel(55, "کانالِ تست", "testchan")
        chan = db.get_channel(cid)
        res = run(Scanner(db, user, lambda: cfg).run(chan, full=True))
        files = db.files_of_channel(chan["id"])
        assert len(files) == 13 and all(f["mime"].startswith("video/") for f in files)
        assert res.status == "done"
        db.close()


def test_full_hash_scope_marks_group_exact(tmp_path):
    """`hash_scope=full` ⇒ هشِ کلِ محتوا ⇒ گروه «قطعی» (★★★★) — روی مسیرِ کاملِ اسکن."""
    with tempfile.TemporaryDirectory() as d:
        db, user, ds, cfg = _mk(d, hash_mode="candidates", hash_scope="full")
        cid = db.add_channel(55, "کانالِ تست", "testchan")
        chan = db.get_channel(cid)
        res = run(Scanner(db, user, lambda: cfg).run(chan, full=True))
        groups = db.groups_of_scan(res.scan_id)
        exact = [g for g in groups if g["exact"]]
        assert exact, "گروهِ قطعی ساخته نشد"
        members = sorted(m["msg_id"] for m in db.group_members(exact[0]["id"]))
        assert members == [101, 102]
        assert "هشِ کامل" in exact[0]["reason"]
        # دامنهٔ هش در دیتابیس هم «full» ثبت شده باشد
        h = {f["msg_id"]: f.get("hash_scope") for f in db.files_of_channel(chan["id"])}
        assert h.get(101) == "full" and h.get(102) == "full"
        db.close()


PREVIEW_HTML = """
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="testchan/101">
 <div class="tgme_widget_message_bubble">
  <div class="tgme_widget_message_text js-message_text" dir="auto">فیلم تست دوبله فارسی.mp4</div>
  <i class="message_video_duration js-message_video_duration">1:32:00</i>
  <time datetime="2026-02-01T10:00:00+00:00"></time>
 </div></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="testchan/102">
 <div class="tgme_widget_message_bubble">
  <div class="tgme_widget_message_text js-message_text" dir="auto">فیلم تست دوبله فارسی.mp4</div>
  <i class="message_video_duration js-message_video_duration">1:32:00</i>
  <time datetime="2026-02-02T10:00:00+00:00"></time>
 </div></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="testchan/103">
 <div class="tgme_widget_message_bubble">
  <div class="tgme_widget_message_text js-message_text" dir="auto">خبرِ کاملاً متفاوت ورزشی</div>
  <time datetime="2026-02-03T10:00:00+00:00"></time>
 </div></div></div>
"""


def test_limited_scan_groups_public_channel_by_caption(tmp_path):
    """«⚠️ اسکنِ محدود» باید واقعاً کار کند (قبلاً پیامِ «پیاده‌سازی نشده» می‌داد)."""
    from tests.test_bot_flow import Env
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)
        cid = e.add_channel()
        calls = []

        async def fake_fetch(username, before=0, **kw):
            calls.append((username, int(before)))
            return "" if before == 101 else PREVIEW_HTML       # صفحهٔ بعدی خالی ⇒ توقف

        e.bot.preview_fetch = fake_fetch
        e.tap("scan:limited:%d" % cid)
        assert calls and calls[0][0] == "testchan"
        scan = e.db.last_scan(cid)
        assert scan and scan["status"] == "done"
        groups = e.db.groups_of_scan(scan["id"])
        assert len(groups) == 1
        assert sorted(m["msg_id"] for m in e.db.group_members(groups[0]["id"])) == [101, 102]
        # پستِ متنیِ بی‌مدیا وارد ایندکس نشده
        assert sorted(f["msg_id"] for f in e.db.files_of_channel(cid)) == [101, 102]
        # صداقتِ گزارش: هشدارِ محدودبودن باید در متن باشد
        summary = e.db.get_scan(scan["id"])["params"]
        assert "preview" in summary and "محدود" in summary
        e.close()


def test_limited_scan_private_channel_explains_alternative(tmp_path):
    from tests.test_bot_flow import Env
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d), ready=False)
        cid = e.add_channel()
        e.db._exec("UPDATE channels SET username='' WHERE id=?", (cid,))
        e.db.conn.commit()
        e.tap("scan:limited:%d" % cid)
        txt = e.last_view()
        assert "عمومی" in txt and "حسابِ کاربری" in txt
        assert e.db.last_scan(cid) is None            # اسکنی شروع نشده
        e.close()
