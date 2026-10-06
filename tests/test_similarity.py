"""تستِ توابعِ تطبیق — حالت‌های مثبت و منفیِ واقعی (فارسی/انگلیسی/کیفیت/قسمت)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import similarity as S  # noqa: E402


def test_normalization_persian_variants():
    assert S.normalize("سلام دنياي كوچك") == S.normalize("سلام دنیای کوچک")
    assert S.normalize("برنامهٔ ویژهٔ نوروز") == "برنامه ویژه نوروز"
    assert S.normalize("فصل ۲ قسمت ۱۲") == "فصل 2 قسمت 12"
    assert S.normalize("ارقام ٣ ٤") == "ارقام 3 4"
    assert S.normalize("🎬 فیلم 🍿") == "فیلم"


def test_normalization_strips_urls_and_handles():
    got = S.caption_norm("دانلود از https://t.me/foo_bar و @channel_name")
    assert "https" not in got and "foo_bar" not in got and "channel_name" not in got
    assert got.startswith("دانلود از")


def test_normalization_keeps_generic_words():
    # «فیلم» و «سریال» نباید حذف شوند (وگرنه نام‌های کوتاه بی‌محتوا می‌شوند)
    assert "فیلم" in S.name_norm("فیلم بدون سانسور")
    assert "movie" in S.name_norm("Movie 2024 1080p.mkv")


def test_normalization_drops_quality_tokens():
    assert S.name_norm("Inception.2010.1080p.BluRay.x265.mkv") == "inception 2010"
    assert S.name_norm("Inception.2010.720p.BluRay.x264.mkv") == "inception 2010"
    assert S.name_norm("Show.S01E01.WEB-DL.1080p.AAC.mp4") == "show s01e01"


def test_episode_signatures():
    assert S.episode_signature("Show.S01E01.1080p.mkv") == "s01e001"
    assert S.episode_signature("show s01 e01.mkv") == "s01e001"
    assert S.episode_signature("Show.1x05.mkv") == "s01e005"
    assert S.episode_signature("سریال فصل ۲ قسمت ۱۲.mkv") == "s02e012"
    assert S.episode_signature("قسمت 3 پارت دوم.mp4") == "p003"
    assert S.episode_signature("E04 final.mp4") == "p004"
    assert S.episode_signature("ep.12.mkv") == "p012"
    assert S.episode_signature("فیلمِ بدون قسمت.mkv") == ""
    assert S.episode_signature("The.Film.2019.1080p.mkv") == ""


def test_name_similar_positive_cases():
    ok, sc = S.name_similar("Inception.2010.1080p.BluRay.x264.mkv", "Inception.2010.720p.BluRay.x264.mkv")
    assert ok and sc > 0.9
    ok, _ = S.name_similar("Black.Mirror.S01E01.1080p.WEB-DL.x265.mkv",
                           "Black.Mirror.S01E01.1080p.WEB-DL.x265 (copy).mkv")
    assert ok
    ok, _ = S.name_similar("film-2024-final.mp4", "film.2024.final.mp4")
    assert ok
    # کوتاه‌شدنِ نام با «دوبله/زیرنویس» فرقی نمی‌کند
    ok, _ = S.name_similar("Serial.Episode.05.دوبله.فارسی.mkv", "Serial.Episode.05.زیرنویس.فارسی.mkv")
    assert ok


def test_name_similar_negative_cases():
    # قسمت‌های پشت‌سرهم هرگز تکراری نیستند
    assert not S.name_similar("Series.X.S01E01.1080p.mkv", "Series.X.S01E02.1080p.mkv")[0]
    assert not S.name_similar("Film.Part.1.1080p.mkv", "Film.Part.2.1080p.mkv")[0]
    assert not S.name_similar("clip-a401.mp4", "clip-b902.mp4")[0]
    assert not S.name_similar("1.mp4", "2.mp4")[0]
    assert not S.name_similar("", "anything.mp4")[0]
    assert not S.name_similar(None, None)[0]
    assert not S.name_similar("lecture-physics.mp4", "cooking-show.mp4")[0]


def test_name_similar_different_seasons_blocked():
    assert not S.name_similar("Show.S01E05.mkv", "Show.S02E05.mkv")[0]


def test_caption_similar():
    a = "برنامهٔ ویژهٔ هفتهٔ اول پاییز با اجرای مهمان"
    b = "برنامه ویژه هفته اول پاییز با اجرای مهمان"
    ok, sc = S.caption_similar(a, b)
    assert ok and sc > 0.9
    long_a = "دانلود فیلم سینمایی امشب از شبکه سه با کیفیت بالا و دوبله فارسی"
    long_b = "دانلود فیلم سینمایی امشب از شبکه چهار با کیفیت بالا و دوبله فارسی"
    assert S.caption_similar(long_a, long_b)[0]
    # خالی/کوتاه هیچ‌وقت تطبیق نمی‌شود
    assert not S.caption_similar("", "")[0]
    assert not S.caption_similar("قسمت ۱", "قسمت ۲")[0]
    assert not S.caption_similar(None, "متن طولانی برای تست کپشن")[0]
    assert not S.caption_similar("برنامهٔ ورزشی امروز ساعت ۱۸", "مستند حیات وحش آفریقا امشب")[0]


def test_caption_similar_needs_enough_shared_tokens():
    a = "اشتراک ویژه کانال ما با تخفیف است"
    b = "اشتراک ویژه کانال شما همیشه رایگان است"
    # توکن‌های مشترک کم است ⇒ نباید تطبیق شود
    assert not S.caption_similar(a, b)[0]


def test_size_time_same():
    base = {"size": 50 * 1024 * 1024, "duration": 60}
    same = {"size": 50 * 1024 * 1024, "duration": 60}
    near = {"size": 50 * 1024 * 1024 + 1000, "duration": 60}   # زمان دقیقاً برابر
    diff_dur = {"size": 50 * 1024 * 1024, "duration": 90}
    diff_size = {"size": 60 * 1024 * 1024, "duration": 60}
    zero_dur = {"size": 50 * 1024 * 1024, "duration": 0}
    tiny = {"size": 1024, "duration": 60}
    assert S.size_time_same(base, same)[0]
    assert S.size_time_same(base, near)[0]
    assert not S.size_time_same(base, diff_dur)[0]
    assert not S.size_time_same(base, diff_size)[0]
    assert not S.size_time_same(base, zero_dur)[0]      # زمان نامعلوم ⇒ بدونِ تطبیق
    assert not S.size_time_same(tiny, {"size": 1024, "duration": 60})[0]   # خیلی کوچک


def test_size_time_tolerance_boundaries():
    a = {"size": 100 * 1024 * 1024, "duration": 120}     # 104,857,600
    tol = max(2048, int(a["size"] * 0.005))              # ≈ 524,288
    # حجم کمی متفاوت ولی **زمان دقیقاً برابر** ⇒ تطبیق (شرطِ «یکی دقیقاً برابر»)
    ok_edge = {"size": a["size"] + tol, "duration": 120}
    bad_edge = {"size": a["size"] + tol + 8192, "duration": 120}
    assert S.size_time_same(a, ok_edge)[0]
    assert not S.size_time_same(a, bad_edge)[0]
    assert not S.size_time_same(a, {"size": a["size"], "duration": 123})[0]


def test_size_time_requires_one_field_exactly_equal():
    """باگِ واقعی: بدونِ این شرط، کلیپ‌های هم‌اندازه با اختلافِ ۱ ثانیه همه یک گروه می‌شدند."""
    a = {"size": 60 * 1024 * 1024, "duration": 100}
    drift = {"size": 60 * 1024 * 1024 + 40_000, "duration": 101}   # هم حجم هم زمان کمی متفاوت
    assert not S.size_time_same(a, drift)[0]
    assert S.size_time_same(a, drift, require_one_exact=False)[0]  # با خاموش‌کردنِ شرط، تطبیق می‌شود
    assert S.size_time_same(a, {"size": 60 * 1024 * 1024 + 40_000, "duration": 100})[0]  # زمانِ دقیق
    assert S.size_time_same(a, {"size": 60 * 1024 * 1024, "duration": 101})[0]           # حجمِ دقیق
    # امتیازِ حالتِ «هر دو دقیقاً برابر» باید کامل باشد
    assert S.size_time_same(a, dict(a))[1] >= 0.999


def test_hash_and_telegram_file_identity():
    a = {"content_hash": "abc123", "hash_scope": "0+128"}
    b = {"content_hash": "abc123", "hash_scope": "0+128"}
    c = {"content_hash": "abc123", "hash_scope": "0+64"}
    d = {"content_hash": "", "hash_scope": ""}
    assert S.hash_equal(a, b)
    assert not S.hash_equal(a, c)      # دامنهٔ هش متفاوت ⇒ قابلِ مقایسه نیست
    assert not S.hash_equal(a, d)
    assert S.same_telegram_file({"file_unique_id": "U1"}, {"file_unique_id": "U1"})
    assert not S.same_telegram_file({"file_unique_id": ""}, {"file_unique_id": ""})
    assert S.same_telegram_file({"doc_id": 42}, {"doc_id": 42})


def test_jaccard_and_ratio_edges():
    assert S.jaccard("", "x") == 0.0
    assert S.jaccard("a b", "a b") == 1.0
    assert 0 < S.jaccard("a b c", "a b d") < 1
    assert S.ratio("", "x") == 0.0
    assert S.ratio("abc", "abc") == 1.0


def test_humanizers():
    assert S.human_bytes(0) == "؟"
    assert S.human_bytes(1024) == "1 KB"
    assert S.human_bytes(50 * 1024 * 1024) == "50 MB"
    assert S.human_duration(0) == "؟"
    assert S.human_duration(60) == "1:00"
    assert S.human_duration(3661) == "1:01:01"
    assert S.percent(1, 0) == 0.0
    assert S.percent(1, 4) == 25.0
    assert S.percent(9, 4) == 100.0
