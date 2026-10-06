"""تست‌های DK-9 — سه خواستهٔ کاربر + باگِ پاک‌سازیِ کانالِ خالی.

① «بتونم برای ربات ادمین اضافه کنم» (دسترسیِ چندکاربره: مالک/ادمین)
② «در فهرستِ کانال‌ها جای شناسه، نامِ کانال دیده شود»
③ پاک‌سازیِ رکوردهای حذف‌شده حتی وقتی کانال **هیچ** فایلِ واجدِ‌شرطی ندارد
   (`if eff_full and seen_ids and …` ⇒ باگِ گزارش‌شده)
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scanner import Scanner                        # noqa: E402
from tests.test_bot_flow import CHAT, Env, OWNER       # noqa: E402
from tests.test_scanner import CFG, setup              # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ═══════════════ ③ پاک‌سازی وقتی کانال خالی می‌شود ═══════════════
def test_prune_runs_when_channel_has_no_files_left(tmp_path):
    """همهٔ ویدیوها در تلگرام حذف شده‌اند ⇒ اسکنِ کامل باید رکوردها را پاک کند (نه اینکه بمانند)."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    n_before = len(db.files_of_channel(chan["id"]))
    assert n_before == 13
    user.videos[55] = []                       # کاربر همهٔ ویدیوها را در تلگرام پاک کرد
    user.contents.clear()
    res = run(Scanner(db, user, lambda: dict(CFG)).run(chan, full=True))
    assert db.files_of_channel(chan["id"]) == [], "رکوردها با کانالِ خالی باقی ماندند"
    assert any("دیگر در کانال نیست" in n for n in (res.notes or []))
    assert res.status == "done" and res.found == 0
    db.close()


def test_prune_skipped_when_empty_state_is_not_confirmed(tmp_path):
    """اگر «خالی‌بودنِ کانال» تأیید نشود (مثلاً خطای دسترسی)، هیچ رکوردی نباید پاک شود."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    n_before = len(db.files_of_channel(chan["id"]))

    async def not_empty(tg_id):                # تلگرام تأیید نمی‌کند که کانال خالی است
        return False

    async def nothing(tg_id, **kw):
        st = kw.get("stats")
        if st is not None:                     # مثلِ کلاینتِ واقعی: پیمایش تمام شد ولی چیزی نبود
            st.update({"visited": 0, "matched": 0, "completed": True, "entity_ok": True})
        if False:
            yield {}

    user.channel_is_empty = not_empty
    user.iter_videos = nothing                 # پیمایش موفق ولی صفر پیام (وضعیتِ مشکوک)
    res = run(Scanner(db, user, lambda: dict(CFG)).run(chan, full=True))
    assert len(db.files_of_channel(chan["id"])) == n_before, "رکوردها بی‌دلیل پاک شدند"
    assert any("تأیید نشد" in n for n in (res.notes or []))
    db.close()


def test_prune_still_works_when_some_videos_removed(tmp_path):
    """حالتِ عادی: چند ویدیو حذف شده و چندتا مانده ⇒ فقط همان‌ها پاک شوند."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    from app.user_client import _kind_ok
    rows = user.videos[55]
    gone = {int(rows[0]["msg_id"]), int(rows[1]["msg_id"])}
    kept = {int(r["msg_id"]) for r in rows[2:] if _kind_ok(r, "video")}   # pdf ایندکس نمی‌شود
    user.videos[55] = [r for r in rows if int(r["msg_id"]) not in gone]
    res = run(Scanner(db, user, lambda: dict(CFG)).run(chan, full=True))
    left = {int(f["msg_id"]) for f in db.files_of_channel(chan["id"])}
    assert left == kept and not (left & gone)
    assert any("دیگر در کانال نیست" in n for n in (res.notes or []))
    db.close()


# ═══════════════ ① ادمین‌ها ═══════════════
def test_owner_adds_admin_by_id_and_admin_can_use_bot():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.text("/addadmin 5001")
        assert 5001 in e.bot.admin_ids and "ادمین" in e.last()
        assert "5001" in str(e.db.kv_get("admins") or "")
        # ادمین: منوی اصلی و اسکن را دارد
        e.text("/start", uid=5001, chat=5001)
        assert "منوی اصلی" in e.last_to(5001)
        assert "خصوصی" not in e.last_to(5001)
        e.tap("scan:full:%d" % cid, uid=5001, chat=5001)
        e.wait_scan()
        assert e.db.last_scan(cid)["status"] == "done"
        # ادمین: دکمهٔ «ادمین‌های ربات» را نمی‌بیند (فقط مالک)
        e.text("/start", uid=5001, chat=5001)
        assert e.kb_btn("ادمین‌های ربات") is None
        # ادمین: «⚙️ تنظیمات» آزاد است (درخواستِ کاربر: با حسابِ ادمین کار می‌کند)
        e.tap("st:menu", uid=5001, chat=5001)
        assert "تنظیماتِ تطبیق" in e.last_to(5001)
        e.tap("st:hash_scope", uid=5001, chat=5001)
        e.text("full", uid=5001, chat=5001)
        assert e.settings.hash_scope == "full", "ادمین تنظیمات را ذخیره نکرد"
        # ولی بخش‌های مالکانه: پیامِ روشن می‌گیرد (نه سکوت)
        e.tap("acc:menu", uid=5001, chat=5001)
        assert "فقط در دستِ <b>مالکِ ربات</b> است" in e.last_to(5001)
        assert "حسابِ کاربری" in e.last_to(5001)
        e.tap("own:menu", uid=5001, chat=5001)
        assert "مدیریتِ ادمین‌ها" in e.last_to(5001)
        # ادمین: نمی‌تواند ادمینِ تازه اضافه کند
        e.tap("own:add:6001", uid=5001, chat=5001)
        assert 6001 not in e.bot.admin_ids
        # مالک: حذفِ ادمین
        e.text("/deladmin 5001")
        assert 5001 not in e.bot.admin_ids
        e.text("/start", uid=5001, chat=5001)
        assert "خصوصی" in e.last_to(5001)
        e.close()


def test_stranger_request_notifies_owner_with_add_button():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.text("سلام", uid=7777, chat=7777)                    # غریبه
        assert "خصوصی" in e.last_to(7777)
        assert e.msg_to(OWNER, "درخواستِ دسترسی")               # مالک خبردار می‌شود
        btn = e.kb_btn("افزودن به‌عنوان ادمین")
        assert btn and btn.get("callback_data") == "own:add:7777"
        e.tap(btn["callback_data"])                            # مالک دکمه را می‌زند
        assert 7777 in e.bot.admin_ids
        e.text("/start", uid=7777, chat=7777)                   # حالا دسترسی دارد
        assert "منوی اصلی" in e.last_to(7777)
        # اسپم نمی‌شود: پیامِ دومِ همان غریبه اعلانِ تازه نمی‌سازد
        e.text("/start", uid=7777, chat=7777)
        e.bot.remove_admin(7777)
        e.text("hi", uid=7777, chat=7777)
        assert not e.msg_to(OWNER, "درخواستِ دسترسی ۲")         # (فقط یک‌بار معرفی می‌شود)
        e.close()


def test_admin_menu_lists_and_removes_via_buttons():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.text("/addadmin 5001")
        e.bot.admin_names["5001"] = "علی (@ali)"                # نام برای نمایش
        e.tap("own:menu")
        v = e.last_view()
        assert "ادمین‌های ربات" in v and "علی" in v
        assert e.kb_btn("حذفِ ادمین") is not None
        e.tap("own:delmenu")
        assert "کدام ادمین حذف شود" in e.last_view()
        btn = e.kb_btn("علی")
        assert btn and btn["callback_data"] == "own:del:5001"
        e.tap(btn["callback_data"])
        assert 5001 not in e.bot.admin_ids
        e.close()


def test_admin_forwarded_message_adds_that_user():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("own:ask")
        assert "شناسهٔ" in e.last()
        m = {"chat": {"id": CHAT}, "from": {"id": OWNER}, "text": "", "message_id": 9,
             "forward_origin": {"type": "user", "sender_user": {"id": 8123, "first_name": "رضا",
                                                                "username": "reza"}}}
        e.run(e.bot.handle_message(m))
        assert 8123 in e.bot.admin_ids
        assert "رضا" in str(e.bot.admin_names.get("8123") or "")
        e.close()


# ═══════════════ ② نامِ کانال به‌جای شناسه ═══════════════
def test_channels_list_shows_name_and_refreshes_placeholder_title():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        c = e.db.get_channel(cid)
        # مثلِ نسخه‌های قبلی: عنوان = خودِ شناسه (و یوزرنیم پاک) ⇒ در فهرست شناسه دیده می‌شد
        e.db.set_channel_title(cid, str(c["tg_id"]), "")
        e.db._exec("UPDATE channels SET username='' WHERE id=?", (cid,))
        e.tap("ch:list")
        v = e.last()
        assert "کانالِ تست" in v, "نامِ کانال از تلگرام تازه نشد"
        assert str(c["tg_id"]) not in v.replace("@testchan", ""), "شناسهٔ عددی در فهرست دیده می‌شود"
        assert "تازه شد" in v
        assert e.kb_btn("کانالِ تست") is not None
        e.close()


def test_channels_list_uses_readable_placeholder_when_name_unknown():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.db.add_channel(-1009999999999, "", "", "channel")     # کانالی که هیچ‌جا حل نمی‌شود
        e.tap("ch:list")
        v = e.last()
        assert "کانالِ بینام" in v
        assert "9999999999" not in v, "به‌جای نام، شناسه نشان داده شد"
        assert e.kb_btn("تلاشِ دوباره") is not None
        e.tap("ch:fix")
        assert e.msg_to(CHAT, "نتوانستم نامِ تازه‌ای پیدا کنم")
        assert "کانالِ بینام" in e.last()          # فهرست دوباره رندر می‌شود
        e.close()


def test_channel_registration_does_not_store_id_as_title():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.db.add_channel(24680, "", "", "channel")        # بدونِ نام شناخته‌شده
        c = e.db.get_channel(cid)
        assert str(c["title"]) in ("", "None") or not str(c["title"]).isdigit()
        e.tap("c:%d" % cid)                                     # کارتِ کانال هم شناسه چاپ نمی‌کند
        v = e.last()
        assert "24680" not in v and "کانالِ بینام" in v
        e.close()


def test_admin_cannot_delete_channel_but_owner_can():
    """«حذف از فهرست» داده‌های ایندکس را پاک می‌کند ⇒ فقط مالک."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.bot.add_admin(5001)
        e.tap("ch:del:%d" % cid, uid=5001, chat=5001)
        assert e.db.get_channel(cid) is not None, "ادمین کانال را حذف کرد"
        e.tap("ch:del:%d" % cid, uid=OWNER)                 # مالک: مجاز
        assert e.db.get_channel(cid) is None
        e.close()


def test_title_refresh_is_rate_limited():
    """تازه‌سازیِ نام نباید هر بار برای همهٔ کانال‌ها به تلگرام درخواست بزند (نه اسپم، نه کندی)."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        for i in range(12):
            e.db.add_channel(-1007000000000 - i, "", "", "channel")
        tried: list = []
        real = e.user.resolve

        async def spy(ref):
            tried.append(ref)
            return await real(ref)

        e.user.resolve = spy
        e.tap("ch:list")
        first = len(tried)
        assert 0 < first <= e.bot.title_refresh_max, "سقفِ هر بازکردن رعایت نشد: %d" % first
        e.tap("ch:list")
        second = len(tried) - first
        assert 0 < second <= e.bot.title_refresh_max
        assert len(set(tried)) == len(tried), "برای یک کانال دو بار تلاش شد (کول‌داون رعایت نشد)"
        e.close()


def test_prune_runs_when_media_kind_disappears_but_channel_has_other_posts(tmp_path):
    """سناریوی گزارش‌شده: ویدیوها پاک شده‌اند و فقط سند مانده ⇒ رکوردهای ویدیو باید بروند."""
    db, user, chan = setup(tmp_path)
    run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    assert db.files_of_channel(chan["id"]), "قبل از تست باید رکوردِ ویدیو داشته باشیم"
    # فقط پیامِ سند (pdf) می‌ماند؛ ویدیوها همه در تلگرام پاک شده‌اند
    docs = [r for r in user.videos[55] if str(r.get("kind") or "") == "doc"]
    assert docs, "دیتاستِ تست باید سند داشته باشد"
    user.videos[55] = docs
    user.contents.clear()
    res = run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    assert db.files_of_channel(chan["id"]) == [], "رکوردِ ویدیوهای حذف‌شده ماند"
    assert any("دیگر در کانال نیست" in n for n in (res.notes or []))
    db.close()


# ═══════════════ DK-10: نامِ کانال و دسترسی‌های لازم ═══════════════
def _env_with_unknown_channel(tmp, **kw):
    """کانالی که نه Bot API می‌شناسدش و نه حسابِ کاربری ⇒ «بدون نام»."""
    e = Env(Path(tmp), **kw)
    cid = e.db.add_channel(-1005550001111, "", "", "channel")
    return e, cid


def test_unknown_channel_offers_manual_name_and_accepts_it():
    with tempfile.TemporaryDirectory() as d:
        e, cid = _env_with_unknown_channel(d)
        e.tap("c:%d" % cid)
        v = e.last_view() if e.api.edits else e.last()
        assert "نامِ این کانال از تلگرام خوانده نشد" in v
        btn = e.kb_btn("نامِ کانال را دستی بگذار")
        assert btn and btn["callback_data"] == "name:%d" % cid
        e.tap(btn["callback_data"])
        assert "نامِ کانال" in e.last()
        e.text("کانالِ بی‌نام من")
        assert "کانالِ بی‌نام من" in e.last()
        assert e.db.get_channel(cid)["title"] == "کانالِ بی‌نام من"
        e.tap("ch:list")
        assert "کانالِ بی‌نام من" in e.last() and "بینام" not in e.last()
        e.close()


def test_forwarded_post_teaches_channel_name():
    """کاربر یک پستِ کانالِ بی‌نام را فوروارد می‌کند ⇒ نام از خودِ پیام برداشته می‌شود."""
    with tempfile.TemporaryDirectory() as d:
        e, cid = _env_with_unknown_channel(d)
        m = {"chat": {"id": CHAT}, "from": {"id": OWNER}, "text": "ادامهٔ متن", "message_id": 8,
             "forward_origin": {"type": "channel", "chat": {"id": -1005550001111,
                                                            "title": "کانالِ ورزشی من",
                                                            "username": "mysport"}}}
        e.run(e.bot.handle_message(m))
        assert "از پستِ فورواردشده خوانده شد" in e.last()
        c = e.db.get_channel(cid)
        assert c["title"] == "کانالِ ورزشی من" and c["username"] == "mysport"
        e.close()


def test_adding_by_forward_then_again_does_not_erase_name():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("ch:add")
        m = {"chat": {"id": CHAT}, "from": {"id": OWNER}, "text": "", "message_id": 11,
             "forward_origin": {"type": "channel", "chat": {"id": -1007770002222,
                                                            "title": "کانالِ فورواردی",
                                                            "username": "fwdchan"}}}
        e.run(e.bot.handle_message(m))
        cid = e.db.list_channels()[-1]["id"]
        assert e.db.get_channel(cid)["title"] == "کانالِ فورواردی"
        # دوباره همان کانال را با شناسهٔ عددی اضافه می‌کنیم (Bot API آن را نمی‌شناسد)
        e.tap("ch:add")
        e.text("-1007770002222")
        c = e.db.get_channel(cid)
        assert c["title"] == "کانالِ فورواردی", "نامِ قبلی با نامِ خالی پاک شد"
        assert c["username"] == "fwdchan"
        assert str(c["id"]) == str(cid)
        e.close()


def test_access_check_says_bot_admin_not_needed_for_scanning():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.api.member_status[(55, 999)] = "left"            # ربات عضو/ادمینِ کانال نیست
        e.tap("chk:%d" % cid)
        v = e.last_view()
        assert "⛔️ عضوِ کانال نیست" in v
        assert "وضعیت خوب است" in v
        assert "لازم نیست ادمین باشد" in v                 # پاسخِ صریح به پرسشِ کاربر
        e.close()


def test_access_check_forbids_full_history_when_account_has_no_access():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()

        async def no_access(tg_id):
            return {"total": 0, "last_id": 0, "title": ""}

        e.user.probe = no_access                           # حسابِ کاربری چیزی نمی‌خواند
        e.tap("chk:%d" % cid)
        v = e.last_view()
        assert "اسکنِ کاملِ تاریخچه کار <b>نمی‌کند</b>" in v
        assert "عضو</b> کنید" in v and "ادمین باشد" in v    # «لازم نیست ادمین باشد؛ فقط عضو»
        assert "کانالِ آرشیو" in v                         # راهِ جایگزینِ بدونِ عضویت
        e.close()


def test_access_check_reports_good_state_when_bot_admin_and_history_readable():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.tap("chk:%d" % cid)
        v = e.last_view()
        assert "✅ ادمینِ کانال است" in v and "تاریخچه خوانده می‌شود" in v
        e.close()


def test_channel_card_shows_name_warning_only_when_unknown():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        cid = e.add_channel()
        e.tap("c:%d" % cid)
        v = e.last_view()
        assert "نامِ این کانال از تلگرام خوانده نشد" not in v, "برای کانالِ نام‌دار هشدارِ بی‌مورد"
        assert e.kb_btn("✏️ نامِ کانال") is None
        assert e.kb_btn("دسترسی‌های لازم") is not None
        e.close()


def test_empty_full_scan_explains_access_and_kind(tmp_path):
    """اسکنِ کاملِ صفرفایل باید راهنمای «دسترسی/نوعِ فایل» بدهد، نه سکوت."""
    db, user, chan = setup(tmp_path)
    user.videos[55] = []
    user.empty_hint = True
    res = run(Scanner(db, user, lambda: CFG).run(chan, full=True))
    assert res.found == 0 and res.status == "done"
    assert any("عضوِ کانال" in n and "دسترسی‌های لازم" in n for n in (res.notes or []))
    db.close()
