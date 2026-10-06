"""تست‌های رگرسیونِ DK-7 — پنج ایرادی که کاربر روی نسخهٔ دیپلوی‌شده پیدا کرد.

۱) اسکنِ ادامه‌ای: پستِ ویرایش‌شده + هشِ کهنه در دیتابیس
۲) سقفِ `duration_pair_cap` و ازقلم‌افتادنِ تکراری در سبدِ پُر
۳) اسکنِ محدود: دامنهٔ تطبیق باید فقط پیام‌های تازه باشد، نه کلِ دیتابیسِ کانال
۴) `_entity`: یوزرنیمِ قدیمی نباید کانالِ اشتباه را برگرداند
۵) مالکیت: بدونِ `OWNER_ID` نباید اولین پیام‌دهنده مالک شود
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import matching as M                       # noqa: E402
from app.db import Db                               # noqa: E402
from app.scanner import Scanner                     # noqa: E402
from dev.fake_telegram import video                 # noqa: E402
from tests.test_bot_flow import Env                 # noqa: E402
from tests.test_scanner import CFG, setup           # noqa: E402

MB = 1024 * 1024


def run(coro):
    return asyncio.run(coro)


# ═══════════════ ۱) هشِ کهنه و پستِ ویرایش‌شده ═══════════════
def test_upsert_files_invalidates_hash_when_content_changes(tmp_path):
    db = Db(str(tmp_path / "u.db"))
    row = video(101, "film.mkv", size=100 * MB, duration=600)
    db.add_files([{**row, "channel_id": 7}])
    fid = db.files_of_channel(7)[0]["id"]
    db.set_hash(fid, "HASH-OLD", "sample")
    # ① همان محتوا ⇒ هش باید دست‌نخورده بماند
    out = db.upsert_files([{**row, "channel_id": 7}])
    assert out == {"n": 1, "changed": [], "cleared": 0}
    assert db.get_file(fid)["content_hash"] == "HASH-OLD"
    # ② پست ویرایش شد و فایلِ تازه حجمِ دیگری دارد ⇒ هشِ کهنه باید پاک و برای هشِ نو علامت‌گذاری شود
    out = db.upsert_files([{**row, "channel_id": 7, "size": 120 * MB, "file_name": "film.new.mkv"}])
    assert out["changed"] == [fid] and out["cleared"] == 1
    f = db.get_file(fid)
    assert f["content_hash"] == "" and f["hash_scope"] == "" and f["size"] == 120 * MB
    db.close()


def test_incremental_scan_rereads_tail_and_rehashes_edited_post(tmp_path):
    """پستِ قدیمی ویرایش شده؛ اسکنِ ادامه‌ای باید بازخوانی، به‌روزرسانی و هشِ نو کند."""
    db, user, chan = setup(tmp_path)
    sc = Scanner(db, user, lambda: dict(CFG, incr_tail=100000))
    run(sc.run(chan, full=True))
    before = {f["msg_id"]: f for f in db.files_of_channel(chan["id"])}
    msg_id = [mid for mid, f in sorted(before.items()) if f["content_hash"] and f["duration"]][0]
    old_hash = before[msg_id]["content_hash"]
    assert old_hash, "پیامِ انتخابی باید در اسکنِ کامل هش شده باشد"
    # کاربر پست را ویرایش می‌کند: حجم/نام عوض می‌شود و بایت‌ها هم تغییر می‌کنند
    rows = user.videos[55]
    for i, r in enumerate(rows):
        if int(r["msg_id"]) == msg_id:
            rows[i] = dict(r, size=int(r["size"]) + 3 * MB, file_name="edited_new_name.mkv")
    user.contents[(55, msg_id)] = b"Z" * (2 * MB)
    # اسکنِ ادامه‌ای: باید از `max_msg_id - incr_tail` بخواند
    sc2 = Scanner(db, user, lambda: dict(CFG, incr_tail=100000))   # کلِ کانال بازخوانی شود
    res = run(sc2.run(chan, full=False))
    f = [x for x in db.files_of_channel(chan["id"]) if int(x["msg_id"]) == msg_id][0]
    assert f["size"] == before[msg_id]["size"] + 3 * MB      # متادیتای تازه ذخیره شد
    assert f["content_hash"] and f["content_hash"] != old_hash   # هشِ کهنه جای خودش را داد
    assert f["file_name"] == "edited_new_name.mkv"
    assert any("تغییر کرده" in n for n in (res.notes or []))  # کاربر خبر می‌شود
    db.close()


def test_incremental_scan_without_tail_skips_old_posts(tmp_path):
    """با `incr_tail=0` رفتارِ قبلی است (فقط پیام‌های تازه‌تر از max_msg_id خوانده می‌شوند)."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: dict(CFG, incr_tail=0)).run(chan, full=True))
    seen = []
    real = user.iter_videos

    def spy(tg_id, **kw):
        seen.append(int(kw.get("min_id") or 0))
        return real(tg_id, **kw)

    user.iter_videos = spy
    run(Scanner(db, user, lambda: dict(CFG, incr_tail=0)).run(chan, full=False))
    assert seen and seen[0] == db.max_msg_id(chan["id"])
    db.close()


# ═══════════════ ۲) سبدِ زمانِ پُر ═══════════════
def test_dense_duration_bucket_keeps_exact_size_duplicate():
    """۳۰۰ کلیپِ هم‌مدت (بیش از سقفِ زنجیره) — جفتِ هم‌حجمِ دقیق نباید از دست برود."""
    rows = [{"id": i, "msg_id": i, "channel_id": 1, "file_name": "c%d.mkv" % i, "name_norm": "c%d" % i,
             "caption": "", "caption_norm": "", "size": 200 * MB + i * 7919, "duration": 900,
             "content_hash": ""} for i in range(300)]
    rows.append({"id": 900, "msg_id": 900, "channel_id": 1, "file_name": "copy.mkv", "name_norm": "copy",
                 "caption": "", "caption_norm": "", "size": rows[17]["size"], "duration": 900,
                 "content_hash": ""})
    cfg = dict(CFG, duration_pair_cap=60, duration_dense_window=4)      # عمداً باریکِ سخت‌گیرانه
    stats = {}
    pairs = set(M._duration_pairs(rows, cfg, stats=stats))
    assert (17, 300) in pairs or (300, 17) in pairs, "هم‌حجمِ دقیق باید همیشه نامزد باشد"
    assert stats.get("duration_pairs_dropped", 0) > 0                  # و شمرده شود
    cfg_all = dict(CFG, exhaustive_pairs=True)
    everything = set(M._duration_pairs(rows, cfg_all))
    assert len(everything) == 301 * 300 // 2                           # «بررسیِ کامل» هیچ‌چیز را جا نمی‌گذارد


# ═══════════════ ۳) دامنهٔ اسکنِ محدود ═══════════════
def test_limited_scan_only_groups_fresh_posts():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        # گروه‌های کهنهٔ داخلِ دیتابیس را دست‌کاری می‌کنیم تا اگر دامنه اشتباه باشد دیده شوند
        old_scan = e.db.last_scan(cid)["id"]
        assert e.db.groups_of_scan(old_scan)
        e.db.add_files([{"channel_id": cid, "msg_id": 999001, "file_name": "old_dup.mkv",
                         "name_norm": "old dup", "caption": "فیلم قدیمی نسخه یک", "caption_norm": "فیلم قدیمی نسخه یک",
                         "size": 700 * MB, "duration": 5000},
                        {"channel_id": cid, "msg_id": 999002, "file_name": "old_dup.mkv",
                         "name_norm": "old dup", "caption": "فیلم قدیمی نسخه یک", "caption_norm": "فیلم قدیمی نسخه یک",
                         "size": 701 * MB, "duration": 5002}])
        def post(mid, cap, dur=0):
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

        html = post(555001, "فيلم تازه 1080p.mkv", 5400) + post(555002, "فيلم تازه 1080p.mkv", 5401)

        async def fake_fetch(uname, before=0, **kw):
            return html if not before else ""

        e.bot.preview_fetch = fake_fetch
        e.tap("scan:limited:%d" % cid)
        e.wait_bg()
        new_scan = e.db.last_scan(cid)["id"]
        cl = e.db.groups_of_scan(new_scan)
        fresh_ids = {f["id"] for f in e.db.files_of_channel(cid) if int(f["msg_id"]) in (555001, 555002)}
        assert cl, "گروهِ تازه ساخته نشد"
        for g in cl:                                     # هر گروه باید حداقل یک پستِ تازه داشته باشد
            members = {m["id"] for m in e.db.group_members(g["id"])}
            assert members & fresh_ids, "گروهی بدونِ پستِ تازه گزارش شد"
        e.close()


# ═══════════════ ۴) یوزرنیمِ قدیمی ⇒ کانالِ اشتباه ═══════════════
def test_entity_rejects_username_pointing_to_another_channel():
    from app.user_client import UserClient
    from tests.test_user_client import FakeTelethon, Msg

    class Mismatch(FakeTelethon):
        async def get_input_entity(self, ref):
            raise ValueError("not cached")

        async def get_entity(self, ref):
            return type("E", (), {"id": 555000111, "title": "کانالِ غریبه", "username": "oldname"})()

        def iter_dialogs(self, limit=None):
            async def gen():
                if False:
                    yield None
            return gen()

    uc = UserClient(api_id=12345, api_hash="x" * 32, session_string="S")
    uc.client = Mismatch([Msg({"msg_id": 1, "size": 10, "file_name": "a.mkv"}, b"x")])
    uc.set_hint(-1001234567890, username="oldname")       # یوزرنیمِ قدیمیِ همین کانال
    try:
        run(uc._entity(-1001234567890))
        raise AssertionError("نباید کانالِ اشتباه برگردانده شود")
    except ValueError as e:
        assert "username:digar" not in str(e)             # پیامِ کاربرپسند است، نه کدِ داخلی
        assert "کانال" in str(e)


# ═══════════════ ۵) مالکیت با کدِ یک‌بارمصرف ═══════════════
def test_owner_bootstrap_requires_claim_code():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.settings.owner_id = 0
        e.bot.owner_id = 0
        e.text("/start")                                   # غریبه
        assert "مالک" in e.last() or "خصوصی" in e.last()
        assert e.bot.owner_id == 0, "هیچ‌کس نباید خودکار مالک شود"
        code = e.bot.claim_code
        assert code, "کدِ مالکیت باید ساخته شود"
        e.text("/claim 000000", uid=99)
        assert e.bot.owner_id == 0 and "نادرست" in e.last()
        e.text("/claim %s" % code, uid=99)
        assert e.bot.owner_id == 99 and e.db.kv_get("owner_id") == 99
        e.text("/start", uid=7)                            # نفرِ بعدی مالک قبلی را نمی‌گیرد
        assert e.bot.owner_id == 99 and "خصوصی" in e.last()
        e.close()


def test_owner_claim_code_from_env():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.settings.owner_id = 0
        e.settings.owner_claim_code = "424242"
        e.bot.owner_id = 0
        e.bot.claim_code = ""
        e.text("/claim 123456", uid=5)
        assert e.bot.owner_id == 0
        e.text("/claim 424242", uid=5)
        assert e.bot.owner_id == 5                          # کدِ متغیرهای محیطی محترم است
        e.close()


# ═══════════════ ۶) پاک‌سازیِ کاملِ کانال (کلیدهای fwd/peerhash هم می‌روند) ═══════════════
def test_delete_channel_removes_all_related_kv_keys(tmp_path):
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        scan_id = e.db.last_scan(cid)["id"]
        gid = e.db.groups_of_scan(scan_id)[0]["id"]
        tg_id = int(e.db.get_channel(cid)["tg_id"])
        e.db.kv_set("fwd:%d:%d" % (scan_id, gid), 1)
        e.db.kv_set("fwd:%d:%d:off" % (scan_id, gid), 3)
        e.db.kv_set("botadmin:%d" % cid, 1)
        e.db.kv_set("peerhash:%s" % tg_id, 987654321)
        out = e.db.delete_channel(cid)
        assert out["channels"] == 1 and out["scans"] == 1 and out["groups"] >= 1
        left = set(e.db.kv_all().keys())
        assert not [k for k in left if str(k).startswith("fwd:%d" % scan_id)]
        assert "fwd:%d:%d" % (scan_id, gid) not in left and "botadmin:%d" % cid not in left
        assert "peerhash:%s" % tg_id not in left
        assert e.db.files_of_channel(cid) == [] and e.db.scans_of(cid) == []
        e.close()
