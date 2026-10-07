"""تست‌های DK-13 — «توضیح بذار، نمی‌دانم دکمه‌های تنظیمات چه کار می‌کنند».

راه‌حل: ① منوی دسته‌بندی‌شده با برچسبِ فارسی ② صفحهٔ توضیح برای هر گزینه (چیست + گزینه‌ها با
نتیجه‌شان) ③ دکمه‌های «مقدار» که با یک کلیک اعمال می‌شوند ④ راهنمای کاملِ همهٔ تنظیم‌ها
⑤ بازگشتِ تک‌گزینه به پیش‌فرض.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bot_app import SETTING_GROUPS, SETTING_INFO     # noqa: E402
from tests.test_bot_flow import CHAT, Env                # noqa: E402

ALL_KEYS = [k for _g, ks in SETTING_GROUPS for k in ks]


def test_every_button_has_a_plain_persian_title_and_explanation():
    """هیچ گزینه‌ای نباید بی‌توضیح باشد و همه باید برچسبِ فارسی داشته باشند."""
    # DK-15: دو تنظیمِ تازهٔ «گروهِ چک» (مقصد + آلبوم) ⇒ ۱۹
    # DK-18: «🔔 نوتیفِ پایانِ اسکن» ⇒ ۲۰
    assert len(SETTING_INFO) == len(ALL_KEYS) == 20
    for k in ALL_KEYS:
        info = SETTING_INFO[k]
        assert info.get("title") and len(info["title"]) <= 26, k
        assert info.get("what") and len(info["what"]) > 25, k          # توضیحِ واقعی، نه یک کلمه
        assert info.get("options") or info.get("presets"), k            # گزینه/مقدارِ پیشنهادی
        for value, label, _desc in (info.get("options") or info.get("presets")):
            assert str(value) and str(label), (k, value)


def test_menu_is_grouped_and_shows_current_values():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:menu")
        v = e.last()
        assert "هر گزینه یک تنظیم است" in v.replace("\n", " ") or "هر دکمه یک تنظیم" in v
        assert "نامِ فایل" in v and "کپشن" in v       # توضیحِ کارِ ربات در سرصفحه
        kb = e.last_kb()
        flat = [b for row in kb for b in row]
        headers = [b["text"] for b in flat if b["callback_data"] == "nop:"]
        for needle in ("تشخیص و هش", "حساسیت", "حجم و زمان", "گروه‌بندی", "اسکن", "فوروارد"):
            assert any(needle in h for h in headers), needle
        labels = [b["text"] for b in flat if b["callback_data"].startswith("st:")]
        assert any("حالتِ هش: candidates" == x.split("⚙️ ")[-1].replace("🔑 ", "") for x in labels) \
            or any("candidates" in x for x in labels)                  # مقدارِ فعلی روی دکمه
        e.close()


def test_tapping_a_setting_shows_explanation_and_choices():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:hash_scope")
        v = e.last_view()
        assert "دامنهٔ هش" in v
        assert "چه چیزی هش شود" in v                       # «این گزینه چیست»
        assert "مقدارِ فعلی: <b>sample</b>" in v and "پیش‌فرض" in v
        assert "گزینه‌ها (روی دکمه بزنید" in v
        assert "نمونه (سریع)" in v and "کامل (قطعی)" in v   # گزینه‌ها با نتیجه‌شان
        datas = e.view_datas()
        assert "stv:hash_scope:full" in datas               # دکمهٔ مقدارِ دیگر
        assert "sta:hash_scope" in datas                    # تایپِ مقدارِ دلخواه
        assert "st:guide" in datas and "st:menu" in datas
        e.close()


def test_clicking_a_value_button_applies_it_immediately():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:hash_scope")
        e.tap("stv:hash_scope:full")                        # یک کلیک = همان لحظه اعمال
        assert e.settings.hash_scope == "full"
        assert e.db.kv_get("setting:hash_scope") == "full"
        v = e.last_view()
        assert "✅ ذخیره شد" in v
        assert "✅ <b>کامل (قطعی)</b> (فعلی)" in v           # صفحه با مقدارِ تازه تازه‌سازی شد
        e.tap("stv:hash_mode:candidates")                   # از همین صفحه به گزینهٔ بعدی
        assert e.settings.hash_mode == "candidates"
        e.close()


def test_reset_single_setting_button():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.settings.th_name_ratio = 0.5
        e.db.kv_set("setting:th_name_ratio", 0.5)
        e.tap("st:th_name_ratio")
        texts = [b["text"] for row in e.last_view_kb() for b in row]
        assert any("پیش‌فرضِ همین گزینه (0.82)" in t for t in texts)
        e.tap("std:th_name_ratio")
        assert abs(e.settings.th_name_ratio - 0.82) < 1e-9
        assert "به پیش‌فرض برگشت" in e.last_view()
        e.close()


def test_guide_explains_every_setting_with_values():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:guide")
        joined = e.all_view_text()
        assert "راهنمای تنظیمات" in joined
        for k in ALL_KEYS:
            assert SETTING_INFO[k]["title"] in joined, k
        assert "الان:" in joined and "پیش‌فرض:" in joined
        assert "کامل (قطعی)" in joined or "کلِ فایل" in joined       # توضیحِ گزینه‌ها هم آمده
        e.close()


def test_guide_command_and_menu_button_paths():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.text("/settings راهنما")
        assert "راهنمای تنظیمات" in e.all_view_text()      # راهنما چند پیام است
        assert "حالتِ هش" in e.all_view_text() and "پیش‌فرض:" in e.all_view_text()
        e.text("/settings")
        assert "تنظیماتِ تطبیق" in e.last()
        assert "st:guide" in e.view_datas()
        e.close()


def test_typing_a_value_still_works_and_returns_to_the_same_setting():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:min_caption_len")
        e.tap("sta:min_caption_len")                        # «✏️ تایپ می‌کنم»
        assert "مقدارِ تازهٔ" in e.last()
        e.text("۹")                                          # ارقامِ فارسی
        assert e.settings.min_caption_len == 9
        assert "st:min_caption_len" in e.view_datas(), "بعد از ذخیره باید راهِ برگشت به همان گزینه باشد"
        e.close()


def test_invalid_typed_value_keeps_waiting_with_hint():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("sta:th_name_ratio")
        e.text("۵")                                          # آستانه باید ۰..۱ باشد
        assert "بین ۰ و ۱" in e.last()
        assert e.bot.pending.get(CHAT, {}).get("key") == "th_name_ratio"
        assert "st:th_name_ratio" in e.view_datas()
        e.text("۰.۷")
        assert abs(e.settings.th_name_ratio - 0.7) < 1e-9
        e.close()


def test_bool_settings_offer_on_off_buttons():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:prune_missing")
        v = e.last_view()
        assert "روشن (پیش‌فرض)" in v and "خاموش" in v
        assert "دیتابیسِ خودِ ربات" in v                     # نکتهٔ امنیتی: چیزی در تلگرام پاک نمی‌شود
        e.tap("stv:prune_missing:0")
        assert e.settings.prune_missing is False
        e.close()


def test_boolean_settings_are_shown_in_persian():
    """در منو و صفحهٔ توضیح، به‌جای True/False باید «روشن/خاموش» دیده شود."""
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:menu")
        labels = [b["text"] for row in e.last_view_kb() for b in row]
        assert any("رکوردهای حذف‌شده: روشن" in t for t in labels), labels
        assert not any("True" in t or "False" in t for t in labels), labels
        e.tap("st:prune_missing")
        v = e.last_view()
        assert "مقدارِ فعلی: <b>روشن</b>" in v and "True" not in v
        e.tap("stv:prune_missing:0")
        assert "مقدارِ فعلی: <b>خاموش</b>" in e.last_view()
        assert "✅ ذخیره شد" in e.last_view() and "خاموش" in e.last_view()
        e.close()


def test_guide_shows_persian_values_for_booleans():
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.tap("st:guide")
        joined = e.all_view_text()
        assert "حجم یا زمانِ دقیق" in joined and "روشن" in joined
        assert "True" not in joined and "False" not in joined
        e.close()
