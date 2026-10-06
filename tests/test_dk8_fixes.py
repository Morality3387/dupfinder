"""تست‌های رگرسیونِ DK-8 — چهار ایرادِ بازبینیِ آخر + محدودیتِ عمدیِ الگوریتم.

۱) عوض‌کردنِ `hash_scope` (sample ⇒ full) باید فایل‌های قبلی را از نو هش کند.
۲) فایل‌هایی که کاربر در تلگرام پاک کرده، در اسکنِ کامل از ایندکس بیرون بروند
   (بدونِ آسیب به رکوردهای سند/عکس در اسکنِ «فقط ویدیو»).
۳) عوض‌کردنِ `media_kinds` باید خودکار اسکنِ کامل شود (وگرنه فایل‌های قدیمیِ نوعِ تازه ایندکس نمی‌شوند).
۴) اسکنِ محدود (پیش‌نمایشِ عمومی) واقعاً کار کند و فورواردِ بی‌معنی را توضیح دهد.
۵) گروه‌بندیِ زنجیره‌ای (A~B و B~C ولی A!~C): نشانه‌دار شود و حالتِ سختگیرانه آن را نشکند.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import matching as M                          # noqa: E402
from app.scanner import Scanner                        # noqa: E402
from tests.test_bot_flow import Env                    # noqa: E402
from tests.test_scanner import CFG, setup              # noqa: E402

MB = 1024 * 1024


def run(coro):
    return asyncio.run(coro)


# ═══════════════ ۱) دامنهٔ هش ═══════════════
def test_hash_scope_change_rehashes_previous_sample_hashes(tmp_path):
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: dict(CFG, hash_scope="sample")).run(chan, full=True))
    files = [f for f in db.files_of_channel(chan["id"]) if f["content_hash"]]
    assert files, "بدونِ هش، تست بی‌معنی است"
    old = {f["id"]: (f["content_hash"], f["hash_scope"]) for f in files}
    assert all(str(f["hash_scope"]).lower() != "full" for f in files)
    res = run(Scanner(db, user, lambda: dict(CFG, hash_scope="full", hash_full_max_mb=500)).run(chan, full=True))
    changed = 0
    for fid, (h_old, sc_old) in old.items():
        f = db.get_file(fid)
        assert str(f["hash_scope"]).lower() == "full", "دامنهٔ هش ارتقا پیدا نکرد: %s" % f["hash_scope"]
        assert f["content_hash"] != h_old
        changed += 1
    assert changed and any("دامنهٔ قدیمی" in n or "full" in n for n in (res.notes or []))
    db.close()


def test_hash_scope_downswitch_does_not_rehash(tmp_path):
    """برگشتنِ تنظیم از full به sample نباید هشِ کاملِ موجود را باطل کند (بی‌دلیل دانلود نکند)."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: dict(CFG, hash_scope="full", hash_full_max_mb=500)).run(chan, full=True))
    before = {f["id"]: f["content_hash"] for f in db.files_of_channel(chan["id"]) if f["content_hash"]}
    run(Scanner(db, user, lambda: dict(CFG, hash_scope="sample")).run(chan, full=True))
    after = {f["id"]: f["content_hash"] for f in db.files_of_channel(chan["id"]) if f["content_hash"]}
    for fid, h in before.items():
        assert after.get(fid) == h, "هشِ کاملِ معتبر بی‌دلیل دوباره حساب شد"
    db.close()


# ═══════════════ ۲) رکوردهای حذف‌شده ═══════════════
def test_full_scan_prunes_records_deleted_from_channel(tmp_path):
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    rows = user.videos[55]
    victim = int(rows[3]["msg_id"])
    assert db.get_file_by_msg(chan["id"], victim) is not None
    user.videos[55] = [r for r in rows if int(r["msg_id"]) != victim]      # کاربر پست را در تلگرام پاک کرد
    user.contents.pop((55, victim), None)
    res = run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    assert db.get_file_by_msg(chan["id"], victim) is None, "رکوردِ حذف‌شده در ایندکس ماند"
    assert any("دیگر در کانال نیست" in n for n in (res.notes or []))
    # اعضای گروه‌ها هم نباید به فایلِ حذف‌شده اشاره کنند
    for sc in db.scans_of(chan["id"]):
        for g in db.groups_of_scan(sc["id"]):
            assert all(int(m["msg_id"]) != victim for m in db.group_members(g["id"]))
    db.close()


def test_prune_keeps_other_media_kinds_intact(tmp_path):
    """اسکنِ «فقط ویدیو» نباید رکوردِ سند/عکس را پاک کند (آن‌ها در این اسکن خوانده نمی‌شوند)."""
    db, user, chan = setup(tmp_path)
    db.add_files([{"channel_id": chan["id"], "msg_id": 999777, "file_name": "book.pdf",
                   "name_norm": "book", "caption": "", "caption_norm": "", "size": 5 * MB,
                   "duration": 0, "mime": "application/pdf", "has_video": 0}])
    run(Scanner(db, user, lambda: dict(CFG, media_kinds="video")).run(chan, full=True))
    assert db.get_file_by_msg(chan["id"], 999777) is not None, "سندِ دست‌نخورده پاک شد"
    db.close()


# ═══════════════ ۳) تغییرِ media_kinds ═══════════════
def test_media_kinds_change_auto_upgrades_to_full_scan(tmp_path):
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: dict(CFG, media_kinds="video")).run(chan, full=True))
    pdf_msg = max(int(r["msg_id"]) for r in user.videos[55] if str(r.get("kind") or "") == "doc")
    assert db.get_file_by_msg(chan["id"], pdf_msg) is None       # در حالتِ «فقط ویدیو» ایندکس نشده
    res = run(Scanner(db, user, lambda: dict(CFG, media_kinds="video+doc")).run(chan, full=False))
    assert db.get_file_by_msg(chan["id"], pdf_msg) is not None, "با تغییرِ نوع، فایلِ قدیمیِ سند ایندکس نشد"
    assert any("خودکار کامل" in n for n in (res.notes or []))
    sc = db.get_scan(res.scan_id)
    assert '"auto_full_kinds": true' in str(sc["params"]).lower()
    db.close()


# ═══════════════ ۴) اسکنِ محدود (پیش‌نمایشِ عمومی) ═══════════════
def _post_html(mid: int, cap: str, dur: int = 0) -> str:
    dur_html = ("<i class=\"tgme_widget_message_video_duration js-message_video_duration\">%d:%02d</i>"
                % (dur // 60, dur % 60)) if dur else ""
    return ("<div class=\"tgme_widget_message_wrap\">"
            "<a href=\"https://t.me/testchan/%d\" data-post=\"testchan/%d\"></a>"
            "<div class=\"tgme_widget_message_bubble\">"
            "<a class=\"tgme_widget_message_photo_wrap\" href=\"https://t.me/testchan/%d\"></a>"
            "%s<div class=\"tgme_widget_message_text js-message_text\">%s</div>"
            "<div class=\"tgme_widget_message_footer\">"
            "<time datetime=\"2026-10-06T10:00:00+00:00\"></time></div></div></div>"
            % (mid, mid, mid, dur_html, cap))


def test_limited_scan_public_preview_creates_groups_and_blocks_forward():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()

        async def fake_fetch(uname, before=0, **kw):
            if before:
                return ""
            return _post_html(5001, "فيلم نمونه 1080p.mkv", 5400) + _post_html(5002, "فيلم نمونه 1080p.mkv", 5401)

        e.bot.preview_fetch = fake_fetch
        e.tap("scan:limited:%d" % cid)
        e.wait_bg()
        scan = e.db.last_scan(cid)
        groups = e.db.groups_of_scan(scan["id"])
        members = [m for g in groups for m in e.db.group_members(g["id"])]
        assert groups and {int(m["msg_id"]) for m in members} == {5001, 5002}
        assert "اسکنِ محدود" in e.last_view()
        # فوروارد در این حالت معنا ندارد ⇒ پیامِ راهنما، نه خطا
        e.tap("f:%d:%d:all:0:%d" % (scan["id"], cid, groups[0]["id"]))
        assert "فوروارد ممکن نیست" in e.last_view()
        assert not e.user.forwarded
        # دکمهٔ فوروارد در کارتِ گروه هم پنهان است
        e.tap("g:%d:%d:all:0:%d" % (scan["id"], cid, groups[0]["id"]))
        assert e.kb_btn("فایل‌های این گروه") is None
        e.close()


def test_limited_scan_private_channel_explains_and_offers_solution():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.db.set_channel_username(cid, "")                              # کانالِ خصوصی (بی‌یوزرنیم)
        e.tap("scan:limited:%d" % cid)
        txt = e.last_view()
        assert "عمومی" in txt and "یوزرنیم" in txt          # توضیحِ صریحِ محدودیت
        assert "حسابِ کاربری" in txt and "ادمین" in txt      # دو راهِ جایگزینِ عملی
        assert e.kb_btn("اسکنِ محدود") is None               # دکمهٔ بی‌اثر نشان داده نمی‌شود
        e.close()


# ═══════════════ ۵) گروه‌بندیِ زنجیره‌ای و حالتِ سختگیرانه ═══════════════
def _rows_chain():
    """A~B با **نام** · A~C با **کپشن** · B!~C (هیچ سیگنالی بین‌شان نیست) ⇒ گرافِ ستاره‌ای."""
    cap = "دانلود فیلم اول با کیفیت بالا"            # ≥ ۱۲ نویسه تا سیگنالِ کپشن فعال شود
    base = {"channel_id": 1, "msg_id": 0, "caption": "", "size": 0, "duration": 0,
            "content_hash": "", "file_name": "", "caption_norm": ""}
    return [
        {**base, "id": 1, "msg_id": 1, "file_name": "Inception 2010.mkv", "name_norm": "inception 2010",
         "caption": cap, "caption_norm": cap},
        {**base, "id": 2, "msg_id": 2, "file_name": "Inception.2010.mkv", "name_norm": "inception 2010",
         "caption": "فیلم دوم با کیفیت متوسط", "caption_norm": "فیلم دوم با کیفیت متوسط"},
        {**base, "id": 3, "msg_id": 3, "file_name": "فیلم سوم.mkv", "name_norm": "فیلم سوم",
         "caption": cap, "caption_norm": cap},
    ]


def test_full_scan_rereads_from_zero(tmp_path):
    """رگرسیونِ DK-8: در «اسکنِ کاملِ دوم» روی همان کانال، باید از صفر خوانده شود (نه از max_msg_id)."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    seen = []
    real = user.iter_videos

    def spy(tg_id, **kw):
        seen.append(int(kw.get("min_id") or 0))
        return real(tg_id, **kw)

    user.iter_videos = spy
    res = run(Scanner(db, user, lambda: dict(CFG)).run(chan, full=True))
    assert seen == [0], "اسکنِ کامل باید از شناسهٔ صفر بخواند، نه از %s" % seen
    from app.user_client import _kind_ok
    expected = len([r for r in user.videos[55] if _kind_ok(r, "video")])   # فقط ویدیوها (pdf نه)
    assert res.found == expected and res.files == expected
    db.close()


def test_chain_cluster_is_flagged_loose_and_split_strict():
    rows = _rows_chain()
    loose = M.find_clusters(rows, dict(CFG, cluster_mode="loose"))
    assert len(loose) == 1 and loose[0]["count"] == 3
    assert loose[0]["chain"] is True and "زنجیره" in loose[0]["reason"]
    assert loose[0]["links"] == 2 and loose[0]["density"] < 1.0
    stats = {}
    strict = M.find_clusters(rows, dict(CFG, cluster_mode="strict"), stats=stats)
    assert len(strict) == 1 and strict[0]["count"] == 2      # فقط جفتِ واقعاً شبیه
    assert strict[0]["chain"] is False and strict[0]["density"] == 1.0
    assert stats.get("strict_leftovers") == 1                 # فایلِ سوم فقط زنجیره‌ای بود
    assert len(M.find_clusters(rows, dict(CFG, cluster_mode="strict"))) == 1


def test_fully_connected_group_of_four_is_not_flagged_as_chain():
    rows = [{"id": i, "channel_id": 1, "msg_id": i, "file_name": "same.mkv", "name_norm": "same name",
             "caption": "یک کپشن واحد برای همه", "caption_norm": "یک کپشن واحد", "size": 100 * MB + i,
             "duration": 600, "content_hash": ""} for i in range(1, 5)]
    cl = M.find_clusters(rows, CFG)
    assert len(cl) == 1 and cl[0]["count"] == 4
    assert cl[0]["chain"] is False and cl[0]["density"] == 1.0


# ═══════════════ ۶) کپشنِ کوتاه: پیش‌فرض نادیده، با تنظیم قابلِ استفاده ═══════════════
def test_short_caption_ignored_by_default_but_configurable():
    cap = "فیلم اول"                                       # ۸ نویسه ⇒ کمتر از حدِ پیش‌فرض (۱۲)
    rows = [
        {"id": 1, "channel_id": 1, "msg_id": 1, "file_name": "a-1080p.mkv", "name_norm": "a",
         "caption": cap, "caption_norm": cap, "size": 500 * MB, "duration": 3600, "content_hash": ""},
        {"id": 2, "channel_id": 1, "msg_id": 2, "file_name": "b-720p.mkv", "name_norm": "b",
         "caption": cap, "caption_norm": cap, "size": 900 * MB, "duration": 7200, "content_hash": ""},
    ]
    assert M.find_clusters(rows, CFG) == []                # پیش‌فرض: کپشنِ کوتاه سیگنال نیست
    cl = M.find_clusters(rows, dict(CFG, min_caption_len=6))
    assert len(cl) == 1 and cl[0]["signals"] == ["caption"]  # با تنظیمِ صریح: کار می‌کند
