"""تست‌های DK-11 — «تنظیمات کار نمی‌کند».

ریشه‌های واقعی: ① مقدارِ نامعتبر حالتِ انتظار را پاک می‌کرد و مقدارِ درستِ بعدی گم می‌شد
② فقط انگلیسیِ دقیق قبول می‌شد («کامل»، «همه»، «۰.۶» رد می‌شدند) ③ کلیدهای تازهٔ DK-8 در منو
نبودند ④ غیرِمالک فقط alertِ گذرا می‌گرفت (سکوت) ⑤ برچسبِ دکمه‌ها بیش از حد بلند بود.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_bot_flow import CHAT, Env            # noqa: E402


def test_persian_words_and_digits_are_accepted():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("sta:hash_scope")
        e.text("کامل")                                   # مترادفِ فارسیِ full
        assert e.settings.hash_scope == "full"
        e.tap("sta:hash_mode")
        e.text("خاموش")
        assert e.settings.hash_mode == "off"
        e.tap("sta:media_kinds")
        e.text("ویدیو و سند")
        assert e.settings.media_kinds == "video+doc"
        e.tap("sta:cluster_mode")
        e.text("سخت‌گیرانه")
        assert e.settings.cluster_mode == "strict"
        e.tap("sta:th_name_ratio")
        e.text("۰.۷")                                    # ارقامِ فارسی
        assert abs(e.settings.th_name_ratio - 0.7) < 1e-9
        e.tap("sta:prune_missing")
        e.text("خاموش")
        assert e.settings.prune_missing is False
        e.close()


def test_invalid_value_keeps_state_and_next_value_applies():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("sta:min_caption_len")
        e.text("سلام")                                   # عدد نیست
        assert "مقدارِ نامعتبر" in e.last() and "مقدارهای مجاز" in e.last()
        assert e.bot.pending.get(CHAT, {}).get("key") == "min_caption_len"
        e.text("8")                                      # همان حالتِ انتظار، مقدارِ درست
        assert e.settings.min_caption_len == 8
        assert "ذخیره شد" in e.last()
        e.close()


def test_threshold_out_of_range_is_rejected_with_hint():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("sta:th_cap_ratio")
        e.text("60")                                     # به‌جای 0.6
        assert "بین ۰ و ۱" in e.last()
        assert e.settings.th_cap_ratio == 0.8            # دست‌نخورده
        e.text("0.6")
        assert e.settings.th_cap_ratio == 0.6
        e.close()


def test_new_settings_are_reachable_from_the_menu():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:menu")
        kb = e.last_kb()
        keys = {b["callback_data"] for row in kb for b in row if b.get("callback_data")}
        for k in ("st:cluster_mode", "st:min_caption_len", "st:prune_missing", "st:incr_tail"):
            assert k in keys, "کلیدِ %s در منو نیست" % k
        assert "st:guide" in keys, "دکمهٔ راهنمای تنظیمات نیست"
        labels = [b["text"] for row in kb for b in row if b.get("callback_data")]
        assert max(len(x) for x in labels) <= 44, "برچسبِ خیلی بلند"
        # سرگروه‌ها هم آمده‌اند (دسته‌بندی ⇒ پیدا کردنِ گزینه آسان)
        headers = [b["text"] for row in kb for b in row if b.get("callback_data") == "nop:"]
        assert any("تشخیص و هش" in h for h in headers) and any("حساسیت" in h for h in headers)
        # دستهٔ «گروه‌بندی» سرگروه دارد ولی چون یک عضو است سرگروهِ تکراری نمی‌سازد
        e.tap("st:cluster_mode")
        assert "سختگیریِ گروه‌بندی" in e.last_view()
        e.close()


def test_set_command_works_as_text_alternative():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.text("/set hash_scope full")
        assert e.settings.hash_scope == "full" and "ذخیره شد" in e.last()
        e.text("/set کلید_غلط 5")
        assert "کلیدِ نامعتبر" in e.last()
        e.text("/set 5")                                  # راهنمای استفاده
        assert "مثال" in e.last()
        e.text("/settings")                               # ورودِ متنی به تنظیمات
        assert "تنظیماتِ تطبیق" in e.last()
        e.close()


def test_admin_can_use_settings_and_is_blocked_only_from_owner_parts():
    """ادمین (که کاربر با آن کار می‌کند) باید تنظیمات را ببیند و ذخیره کند."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.bot.add_admin(5001)
        e.tap("st:menu", uid=5001, chat=5001)
        assert "تنظیماتِ تطبیق" in e.last_to(5001)
        e.text("/set دامنه هش کامل", uid=5001, chat=5001)
        assert e.settings.hash_scope == "full" and "ذخیره شد" in e.last_to(5001)
        # بخش‌های مالکانه: پیامِ روشن (نه سکوت)
        e.tap("acc:menu", uid=5001, chat=5001)
        assert "فقط در دستِ <b>مالکِ ربات</b> است" in e.last_to(5001)
        assert "حسابِ کاربری" in e.last_to(5001)
        e.close()


def test_settings_menu_still_renders_when_keyboard_fails():
    """اگر تلگرام کیبورد را رد کند، متنِ تنظیمات می‌رود و راهِ /set هم گفته می‌شود."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))

        async def broken_send(chat_id, text, *, kb=None, **kw):
            if kb:
                raise RuntimeError("BUTTON_TEXT_INVALID")
            return await real_send(chat_id, text, kb=None, **kw)

        real_send = e.api.send_message
        e.api.send_message = broken_send
        e.run(e.bot._settings_menu(CHAT))
        assert "تنظیماتِ تطبیق" in e.api.sent[-1]["text"]
        assert "BUTTON_TEXT_INVALID" in e.api.sent[-1]["text"] or "/set" in e.api.sent[-1]["text"]
        e.close()
