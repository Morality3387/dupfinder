"""تست‌های DK-15 — چهار خواستهٔ کاربر روی رباتِ «پیدا کردنِ تکراری‌ها».

خواسته‌ها (همان‌طور که کاربر گفت):
 ① «وقتی یک اسکن جدید زدم، تاریخچهٔ اسکنِ قبلی پاک شود — انگار از نو اسکن زده»
 ② «وقتی رفتم تو لیست، تیکِ رسیدگی در قسمتِ لیست هم بخورد»
 ③ «تو یک دکمه فوروارد، همهٔ تکراری‌های همان گروه را بی‌سقف و خودش تا آخر بفرستد»
 ④ «هر تکراری را کنارِ خودش به یک گروه/کانال بفرست تا چک کنم — بدونِ محدودیتِ تعداد»

قراردادِ پیاده‌سازی: ریستِ اسکن = «فقط نتایج» (ایندکس/هش دست‌نخورده) · گروهِ چک = **دستی،
فقط با دکمه، بدونِ سقف** · مقصد هم با فورواردِ پیام و هم با تایپِ یوزرنیم/شناسه.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings                    # noqa: E402
from tests.test_bot_flow import CHAT, Env          # noqa: E402

TGT = -100999            # شناسهٔ گروهِ چکِ ساختگی (مقصد)


# ───────────────────────────── ابزار ─────────────────────────────

def _scan_env(d, **kw):
    """محیطِ آماده: کانال اضافه‌شده + یک اسکنِ کاملِ تمام‌شده."""
    e = Env(Path(d), **kw)
    e.text("/start")
    cid = e.add_channel()
    e.tap("scan:full:%d" % cid)
    e.wait_scan()
    return e, cid, e.db.last_scan(cid)["id"]


def _groups(e, scan_id):
    return e.db.groups_of_scan(scan_id)


def _to_target(e):
    """هر چه به گروهِ چک (مقصد) فرستاده شده — برای ادعاهای «چه چیزی رفت؟»"""
    return [m for m in e.api.sent if int(m.get("chat_id") or 0) == TGT]


def _files_to_target(e):
    """شمارشِ فایل‌هایی که به مقصد رفت (آلبوم‌ها هم به‌اندازهٔ اعضایشان حساب می‌شوند)."""
    return sum(len(f.get("ids") or []) for f in e.api.forwards if int(f.get("to") or 0) == TGT)


def _register_target(e, cid=TGT, title="گروهِ چکِ من", username="mychan"):
    """گروهِ چکِ ساختگی را در شبیه‌سازِ تلگرام ثبت می‌کند (مثلِ گروهِ واقعیِ کاربر)."""
    e.api.chats[cid] = {"id": cid, "title": title, "username": username}


def _set_target_by_text(e, value="@mychan", *, register=True):
    if register:
        _register_target(e, username=str(value).lstrip("@"))
    e.text("/check")
    e.tap("ck:set:id")
    e.text(value)


class _NoLinkApi:
    """پوششِ ساختگی: هر ارسالِ پیامِ لینکِ پست شکست می‌خورد (شبیه‌سازیِ «ربات دسترسی ندارد»)."""

    def __init__(self, api):
        self._api = api

    def __getattr__(self, name):
        return getattr(self._api, name)

    async def send_message(self, chat_id, text, **kw):
        if str(text).startswith("🔗"):
            from app.tg_api import TgError
            raise TgError("sendMessage", 403, "CHAT_WRITE_FORBIDDEN")
        return await self._api.send_message(chat_id, text, **kw)


def _type_value(e, key, value):
    e.tap("st:%s" % key)
    e.tap("sta:%s" % key)
    e.text(value)


# ───────────────── ① ریستِ نتایجِ اسکنِ قبلی ─────────────────

def test_new_scan_wipes_previous_results_but_keeps_the_index():
    """خواستهٔ ①: با اسکنِ تازه، لیست/گروه‌های اسکنِ قبلی پاک شود ولی ایندکس بماند."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, old_scan = _scan_env(d)
        old_groups = [g["id"] for g in _groups(e, old_scan)]
        old_files = e.db.count_files(cid)
        old_hashed = e.db.stats()["hashed"]
        assert old_groups and old_files and old_hashed > 0
        # آثاری که باید پاک شوند: تیکِ رسیدگی، «قبلاً فرستاده شد»، «به گروهِ چک رفت»
        e.db.set_group_state(old_groups[0], "done")
        e.db.kv_set("fwd:%d:%d" % (old_scan, old_groups[0]), 1)
        e.db.kv_set("mir:%d:%d" % (old_scan, old_groups[0]), 1)
        # اسکنِ دوم
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        new_scan = e.db.last_scan(cid)["id"]
        assert new_scan != old_scan
        assert e.db.get_scan(old_scan) is None                       # ردیفِ اسکنِ قبلی رفت
        assert [s["id"] for s in e.db.scans_of(cid)] == [new_scan]   # فقط اسکنِ تازه مانده
        assert e.db.group_members(old_groups[0]) == []               # اعضای گروه‌های قبلی رفت
        assert e.db.kv_get("fwd:%d:%d" % (old_scan, old_groups[0])) is None
        assert e.db.kv_get("mir:%d:%d" % (old_scan, old_groups[0])) is None
        # ایندکس دست‌نخورده (اسکنِ تازه لازم نیست از صفر هش کند)
        assert e.db.count_files(cid) == old_files
        assert e.db.stats()["hashed"] == old_hashed
        # و کاربر این را در گزارش می‌بیند
        assert "نتایجِ اسکنِ قبلی پاک شد" in e.last_view()
        e.close()


def test_report_and_list_show_only_the_fresh_scan():
    """بعد از اسکنِ تازه، شمارندهٔ فهرست از صفرِ همان اسکن است (نه جمعِ اسکن‌های قبلی)."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, old_scan = _scan_env(d)
        n_first = len(_groups(e, old_scan))
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        new_scan = e.db.last_scan(cid)["id"]
        e.tap("l:%d:%d:all:0" % (new_scan, cid))
        assert "کلِ گروه‌ها: <b>%d</b>" % len(_groups(e, new_scan)) in e.last_view()
        assert len(_groups(e, new_scan)) == n_first                  # همان کانال، همان نتیجه
        e.close()


# ───────────────── ② تیکِ رسیدگی در فهرست ─────────────────

def test_done_and_ignored_marks_show_inside_the_groups_list():
    """خواستهٔ ②: متنِ ردیف‌های **لیست** باید وضعیت را نشان دهد، نه فقط صفحهٔ گروه."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        gs = _groups(e, scan_id)
        assert len(gs) >= 2, "برای این تست دست‌کم دو گروه لازم است"
        g1, g2 = int(gs[0]["id"]), int(gs[1]["id"])
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        txt = e.last_view()
        shown = min(len(gs), int(e.settings.page_size or 8))
        assert txt.count("   —") == shown                            # پیش از رسیدگی: بدونِ تیک
        e.tap("m:%d:%d:%d:done" % (scan_id, cid, g1))
        e.tap("m:%d:%d:%d:ign" % (scan_id, cid, g2))
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        txt = e.last_view()
        assert "✔ رسیدگی‌شده" in txt and "🔒 نادیده" in txt
        # ولی گروهِ نادیده‌گرفته‌شده هم در فهرستِ «همه» دیده می‌شود
        assert "#%d" % g2 in txt
        # فیلترِ «فقط رسیدگی‌نشده» گروه‌های تیک‌خورده را بیرون می‌گذارد
        e.tap("l:%d:%d:open:0" % (scan_id, cid))
        assert "#%d" % g1 not in e.last_view()
        e.close()


def test_list_buttons_carry_the_tick_mark():
    """تیک باید روی خودِ دکمهٔ گروه هم باشد تا در فهرستِ دکمه‌ها فوری دیده شود."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        gid = int(_groups(e, scan_id)[0]["id"])
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        labels = [b["text"] for row in e.last_view_kb() for b in row if b["callback_data"].startswith("g:")]
        assert labels and any(l.startswith("★") for l in labels)
        assert not any(l.startswith("✔ ") for l in labels)            # هنوز هیچ‌کدام رسیدگی نشده
        e.tap("m:%d:%d:%d:done" % (scan_id, cid, gid))
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        labels = [b["text"] for row in e.last_view_kb() for b in row if b["callback_data"].startswith("g:")]
        assert sum(1 for l in labels if l.startswith("✔ ")) == 1
        e.close()


# ───────────────── ③ فورواردِ گروه: بدونِ سقف، بدونِ «ادامه» ─────────────────

def test_group_forward_sends_every_file_without_cap_and_without_continue():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d, max_forward_per_group=1)      # سقفِ عمداً کوچک
        gid = 0
        for g in _groups(e, scan_id):
            if len(e.db.group_members(int(g["id"]))) >= 3:
                gid = int(g["id"])
                break
        assert gid, "گروهِ سه‌عضوی لازم است"
        n = len(e.db.group_members(gid))
        e.tap("f:%d:%d:all:0:%d" % (scan_id, cid, gid))
        assert len(e.api.forwards) == n                              # همه رفت، سقف بی‌اثر است
        assert "بدونِ سقف" in e.last()
        assert not [b for row in e.last_kb() for b in row if "ادامه" in b["text"]]
        e.close()


def test_group_forward_warns_loudly_when_nothing_can_be_sent():
    """اگر هیچ‌کدام نرفت، پیامِ روشن بیاید (نه شکستِ خاموش)."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        gid = int(_groups(e, scan_id)[0]["id"])
        members = e.db.group_members(gid)
        e.api.fail_forward_ids |= {int(m["msg_id"]) for m in members}   # فورواردِ ربات ممنوع
        e.api.fail_copy_ids |= {int(m["msg_id"]) for m in members}      # کپی هم ممنوع
        e.user._ready = False                                          # حسابِ کاربری هم نیست
        e.bot.reporter.api = _NoLinkApi(e.api)                        # حتی لینک هم نمی‌رسد
        e.tap("f:%d:%d:all:0:%d" % (scan_id, cid, gid))
        assert "فرستاده‌شده: <b>0</b>" in e.last()
        assert "هیچ‌کدام از فایل‌های این گروه فرستاده نشد" in e.last()
        assert "حسابِ کاربری" in e.last()                             # راهِ‌حل هم گفته می‌شود
        e.close()


def test_group_forward_says_loudly_when_only_links_could_be_sent():
    """ربات اجازهٔ فوروارد ندارد ⇒ لینک می‌رود، ولی پیام **روشن** می‌گوید فایل نرفته."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        gid = int(_groups(e, scan_id)[0]["id"])
        members = e.db.group_members(gid)
        e.api.fail_forward_ids |= {int(m["msg_id"]) for m in members}
        e.api.fail_copy_ids |= {int(m["msg_id"]) for m in members}
        e.user._ready = False
        e.tap("f:%d:%d:all:0:%d" % (scan_id, cid, gid))
        assert "فقط لینک" in e.last()
        assert "اجازهٔ فورواردِ خودِ فایل را نداشت" in e.last()
        e.close()


# ───────────────── ④ گروهِ چک ─────────────────

def test_check_group_is_manual_only_and_asks_for_a_destination_first():
    """خواستهٔ ④: بدونِ مقصد هیچ‌چیز نمی‌رود و دکمه‌های تعیینِ مقصد نشان داده می‌شود."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        e.tap("cs:%d:%d" % (scan_id, cid))
        assert "مقصد" in e.last() and "تعیین" in e.last()
        assert not _files_to_target(e)                                # هیچ فایلی نرفت
        kb = e.last_kb()
        assert any(b["callback_data"] == "ck:set:forward" for row in kb for b in row)
        assert any(b["callback_data"] == "ck:set:id" for row in kb for b in row)
        e.close()


def test_destination_can_be_set_by_forwarding_a_message_from_it():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        e.text("/check")
        e.tap("ck:set:forward")
        assert "فوروارد" in e.last()
        e.text("", fwd={"type": "channel", "chat": {"id": TGT, "title": "گروهِ چکِ من",
                                                    "username": "my_check"}})
        assert e.settings.check_target == "@my_check"                 # یوزرنیم ترجیح دارد
        assert e.db.kv_get("setting:check_target") == "@my_check"
        assert e.db.kv_get("check:title") == "گروهِ چکِ من"
        assert "ذخیره شد" in e.last()
        e.close()


def test_destination_can_be_typed_in_several_formats():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        e.text("/check")
        e.tap("ck:set:id")
        e.text("@my_check")
        assert e.settings.check_target == "@my_check"
        e.text("/check")
        e.tap("ck:set:id")
        e.text("-1001234567890")
        assert e.settings.check_target == "-1001234567890"            # شناسهٔ عددی هم قبول است
        e.tap("ck:set:id")
        e.text("t.me/my_other")
        assert e.settings.check_target == "@my_other"                 # لینک هم قبول است
        e.close()


def test_bad_destination_is_rejected_with_a_clear_hint():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        e.text("/check")
        e.tap("ck:set:id")
        e.text("سلام")                                                # بی‌معنی
        assert "خوانده نشد" in e.last()
        assert e.settings.check_target == ""                          # چیزی ذخیره نشد
        e.text("خاموش")                                              # برداشتنِ مقصد
        assert e.settings.check_target == ""
        e.close()


def test_check_send_never_happens_automatically_after_a_scan():
    """مهم‌ترین شرطِ کاربر: بخشِ گروهِ چک **خودکار** نمی‌فرستد؛ فقط با دکمه."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        before = len(_to_target(e))
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        new_scan = e.db.last_scan(cid)["id"]
        assert len(_to_target(e)) == before                           # بعد از اسکنِ تازه هم صفر
        assert not e.api.methods().count("sendMediaGroup")
        # دکمه اما در گزارشِ اسکن هست و متن می‌گوید دستی است
        btn = e.kb_btn("به گروهِ چک")
        assert btn and btn["callback_data"] == "cs:%d:%d" % (new_scan, cid)
        assert "خودکار" in e.last_view()
        e.close()


def test_check_send_delivers_every_group_with_header_and_album():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d, max_forward_per_group=1)        # سقفِ کوچک ⇒ نباید اثر کند
        _set_target_by_text(e, "@mychan")
        groups = [g for g in _groups(e, scan_id) if str(g.get("state") or "open") != "ignored"]
        want = sum(len(e.db.group_members(int(g["id"]))) for g in groups)
        e.tap("cs:%d:%d" % (scan_id, cid))
        assert _files_to_target(e) == want                             # همهٔ فایل‌ها، بی‌سقف
        heads = [m for m in _to_target(e) if "🔸 <b>#" in str(m.get("text") or "")]
        assert len(heads) == len(groups)                               # هر گروه یک سرتیتر
        assert any("تکراری‌ها (کنارِ هم)" in str(m.get("text") or "") for m in heads)
        assert any(f.get("album") for f in e.api.forwards if int(f.get("to") or 0) == TGT)
        assert all(e.db.kv_get("mir:%d:%d" % (scan_id, int(g["id"]))) for g in groups)
        e.close()


def test_check_send_with_albums_off_goes_one_by_one():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        e.settings.check_albums = False
        e.tap("cs:%d:%d" % (scan_id, cid))
        assert not any(f.get("album") for f in e.api.forwards if int(f.get("to") or 0) == TGT)
        assert "sendMediaGroup" not in e.api.methods()                 # فقط تک‌به‌تک
        e.close()


def test_check_send_skips_ignored_groups_and_skipped_ones():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        gs = _groups(e, scan_id)
        ignored, skipped = int(gs[0]["id"]), int(gs[1]["id"])
        e.tap("m:%d:%d:%d:ign" % (scan_id, cid, ignored))              # کاربر: این را نادیده بگیر
        e.db.kv_set("checkq:skip:%d:%d" % (scan_id, skipped), 1)       # و این یکی با «🗑 حذفِ جهش»
        e.tap("cs:%d:%d" % (scan_id, cid))
        tgt_msgs = [str(m.get("text") or "") for m in _to_target(e)]
        assert "#%d" % ignored not in " ".join(tgt_msgs)
        assert "#%d" % skipped not in " ".join(tgt_msgs)
        assert "نادیده‌گرفته‌شده‌ها" in e.all_view_text()      # سرتیترِ شروع هم چیزی که کاربر می‌بیند
        e.close()


def test_check_send_warns_loudly_when_nothing_reaches_the_target():
    """قراردادِ کاربر: اگر ربات اجازهٔ ارسال نداشت، هشدارِ روشن بدهد — نه شکستِ خاموش."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        e.user._ready = False                                          # حسابِ کاربری هم وصل نیست
        e.api.blocked.add(TGT)
        e.user.blocked.add(TGT)
        e.tap("cs:%d:%d" % (scan_id, cid))
        view = e.all_view_text()
        assert "هیچ فایلی به مقصد نرسید" in view
        assert "ادمین" in view
        assert e.kb_btn("تستِ دسترسی") is not None
        e.close()


def test_again_and_resume_buttons_work():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        e.tap("cs:%d:%d" % (scan_id, cid))
        first = _files_to_target(e)
        e.tap("cs:%d:%d" % (scan_id, cid))                             # دوباره ⇒ هیچ (قبلاً رفته)
        assert _files_to_target(e) == first
        assert "چیزی برای فرستادن نمانده" in e.last()
        e.tap("qs:again:%d:%d" % (scan_id, cid))                       # «🔁 همه را از نو»
        assert _files_to_target(e) == first * 2
        e.close()


def test_state_and_all_done_buttons():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        e.tap("cs:%d:%d" % (scan_id, cid))
        e.tap("qs:state:%d" % scan_id)
        assert "وضعیتِ فرستادن به گروهِ چک" in e.last_view()
        assert "باقی‌مانده: <b>0</b> گروه" in e.last_view()
        e.tap("qs:alldone:%d" % scan_id)
        assert all(str(g.get("state")) == "done" for g in _groups(e, scan_id))
        e.tap("l:%d:%d:all:0" % (scan_id, cid))
        shown = min(len(_groups(e, scan_id)), int(e.settings.page_size or 8))
        assert e.last_view().count("✔ رسیدگی‌شده") == shown
        e.close()


def test_per_group_check_button_sends_only_that_group():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        gid = int(_groups(e, scan_id)[0]["id"])
        n = len(e.db.group_members(gid))
        e.tap("csrf:%d:%d:%d" % (scan_id, cid, gid))
        assert _files_to_target(e) == n
        assert e.db.kv_get("mir:%d:%d" % (scan_id, gid)) == 1
        assert not e.db.kv_get("mir:%d:%d" % (scan_id, int(_groups(e, scan_id)[1]["id"])))
        # دکمهٔ «🗑 حذفِ جهش» روی سرتیتر هم در دسترس است
        heads = [m for m in _to_target(e) if "🔸 <b>#" in str(m.get("text") or "")]
        assert heads and "qs:skip:%d:%d" % (scan_id, gid) in str((heads[0].get("kb") or {}))
        e.close()


def test_check_access_test_explains_when_bot_cannot_reach_target():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@unknown_channel", register=False)      # در FakeApi وجود ندارد
        e.tap("ck:test")
        assert "دسترسی ندارد" in e.last() and "ادمین" in e.last()
        _register_target(e, username="unknown_channel")
        e.tap("ck:test")
        assert "دسترسی به مقصد برقرار است" in e.last() and "گروهِ چکِ من" in e.last()
        e.close()


def test_check_settings_page_has_explanation_and_presets():
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        e.text("/settings")
        view = e.all_view_text()
        assert "گروهِ چک" in view
        assert e.kb_btn("مقصدِ گروهِ چک") is not None
        e.tap("st:check_target")
        assert "مقصدِ ارسال" in e.last_view()
        assert "خودکار" in e.last_view()                                # توضیحِ «دستی بودن»
        assert e.kb_btn("یوزرنیم", sent=False) is not None or e.kb_btn("یوزرنیم") is not None
        e.tap("st:check_albums")
        assert "کنارِ هم" in e.last_view()
        e.close()


def test_check_target_survives_restart_via_settings_overrides():
    """مقصد در kv ذخیره می‌شود ⇒ بعد از ری‌استارت هم می‌ماند."""
    with tempfile.TemporaryDirectory() as d:
        e, cid, scan_id = _scan_env(d)
        _set_target_by_text(e, "@mychan")
        st = Settings()
        st.apply_overrides(dict(e.db.kv_all()).get("setting:check_target") and
                           {"check_target": "@mychan"} or {})
        assert st.check_target == "@mychan"
        assert "check_target" in [k for k in Settings().__dataclass_fields__]
        e.close()
