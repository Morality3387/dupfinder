"""توابعِ خالصِ تطبیق (بدونِ I/O) — قلبِ تشخیصِ تکراری‌ها.

سه سیگنال به‌ترتیبِ اولویتِ کارفرما:
  ۱) نامِ فایل   → `name_similar()`
  ۲) کپشن       → `caption_similar()`
  ۳) حجم + زمان → `size_time_same()`
به‌علاوهٔ یک سیگنالِ قطعی: هشِ محتوایی (`hash_equal`) که «قطعاً همان فایل» است.
همهٔ توابع بدونِ شبکه/db ⇒ کاملاً قابلِ تستِ واحد.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Optional, Sequence, Set, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# ۱) نرمال‌سازی
# ─────────────────────────────────────────────────────────────────────────────

# نگاشتِ حرف‌های عربی/فارسی به شکلِ یکسان
_CHAR_MAP = {
    "ي": "ی", "ى": "ی", "ﻯ": "ی", "ﻰ": "ی", "ئ": "ی",
    "ك": "ک", "ﻙ": "ک", "ﻚ": "ک",
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ﻻ": "لا",
    "ة": "ه", "ۀ": "ه", "ؤ": "و",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "…": " ", "—": " ", "–": " ", "ـ": "", "«": " ", "»": " ", "\u200f": "", "\u200e": "",
}
_DIACRITICS = re.compile(r"[\u064b-\u0655\u0670\u0640]")
_ZWNJ = "\u200c"

# بازهٔ اموجی/پیکتوگرام‌ها (برای مقایسهٔ متنی حذف می‌شوند)
_EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U0001F000-\U0001F2FF" "\u2600-\u27BF"
    "\u2B00-\u2BFF" "\uFE0F" "\u2190-\u21FF" "\u2300-\u23FF" "\U0001F1E6-\U0001F1FF" "]"
)
_URL = re.compile(r"(?:https?://|tg://|www\.)\S+", re.I)
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}")
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s\u0600-\u06FF]+", re.UNICODE)

# توکن‌های «کیفیت/فرمت» که نباید نام‌ها را متفاوت کنند
_QUALITY_TOKENS = {
    "1080p", "1080", "720p", "720", "480p", "480", "360p", "2160p", "2160", "1440p", "4k", "8k", "2k",
    "fhd", "uhd", "fullhd", "hd", "sd", "hq", "lq", "hdrip", "webrip", "webdl", "web", "dl", "bluray",
    "brrip", "bdrip", "dvdrip", "dvd", "hdrip", "hdtv", "hdcam", "cam", "ts", "tc", "remux", "proper",
    "repack", "x264", "x265", "h264", "h265", "hevc", "avc", "xvid", "divx", "aac", "ac3", "eac3", "ddp",
    "dd", "dd5", "dts", "mp3", "opus", "10bit", "8bit", "hdr", "hdr10", "sdr", "dv", "dolby", "atmos",
    "dual", "dubbed", "dub", "subbed", "sub", "softsub", "hardsub", "multi", "persian", "farsi", "dubbed",
    "zabane", "zaban", "dubbing", "voa", "ir", "iran", "imax", "uncut", "extended", "directors", "cut",
    "mp4", "mkv", "avi", "mov", "m4v", "webm", "flv", "wmv", "mpg", "mpeg", "vob", "m2ts", "part", "vol",
    "yts", "yify", "rarbg", "galaxyrg", "psa", "evo", "f2m", "encode", "encoded", "encodegah",
    "film2movie", "digimoviez", "valamovie", "avamovie", "bia2movies", "zar", "zardfilm", "nimadl",
    "dlfilm", "download", "زبان", "zaban", "zabane",
    "دوبله", "زیرنویس", "چسبیده", "نسخه", "کیفیت", "سانسور", "کامل", "fullhd", "دو", "دو‌زبانه",
}
# ⚠️ واژه‌های عمومی («فیلم/سریال/movie») عمداً حذف **نمی‌شوند**؛ حذف‌شان
#    نام‌های کوتاه را بی‌محتوا می‌کند و ریسکِ تطبیقِ اشتباه بالا می‌رود.
# توکن‌های شمارشیِ «قسمت/فصل»
_EP_WORDS = {"قسمت", "بخش", "پارت", "اپیزود", "ep", "episode", "epi", "epis", "e", "part", "pt"}
_SEASON_WORDS = {"فصل", "س", "season", "s", "sezon"}


def _strip_quality(tokens: Sequence[str]) -> List[str]:
    out = []
    for t in tokens:
        if t in _QUALITY_TOKENS:
            continue
        # 1080px / x265-psa / 720p60
        if re.fullmatch(r"\d{3,4}p(?:\d{1,2})?", t):
            continue
        if re.fullmatch(r"x?26[45]", t):
            continue
        if re.fullmatch(r"(?:h|hevc)?d?(?:rip|cam|ts|tc)", t):
            continue
        out.append(t)
    return out


def normalize(text: Optional[str], *, drop_quality: bool = False, drop_urls: bool = True) -> str:
    """نرمال‌سازیِ متن برای مقایسه: حروفِ یکسان، ارقامِ لاتین، بی‌اموجی، بی‌نقطه‌گذاری."""
    s = str(text or "")
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(_CHAR_MAP.get(ch, ch) for ch in s)
    s = _DIACRITICS.sub("", s)
    s = s.replace(_ZWNJ, "")
    s = s.lower()
    s = _EMOJI.sub(" ", s)
    if drop_urls:
        s = _URL.sub(" ", s)
        s = _HANDLE.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    if drop_quality:
        s = " ".join(_strip_quality(s.split()))
    return s.strip()


def name_norm(name: Optional[str]) -> str:
    """نامِ فایلِ نرمال‌شده **با** حذفِ توکن‌های کیفیت/فرمت (برای مقایسه)."""
    return normalize(name, drop_quality=True, drop_urls=True)


def caption_norm(caption: Optional[str]) -> str:
    """کپشنِ نرمال‌شده (کیفیت‌ها این‌جا حذف نمی‌شوند؛ متنِ تبلیغاتی/لینک حذف می‌شود)."""
    return normalize(caption, drop_quality=False, drop_urls=True)


# ─────────────────────────────────────────────────────────────────────────────
# ۲) امضای قسمت/فصل (تا S01E01 با S01E02 قاطی نشود)
# ─────────────────────────────────────────────────────────────────────────────

_RE_SXXEYY = re.compile(r"\bs\s*(\d{1,2})\s*[\s._\-]*e\s*(\d{1,3})\b")
_RE_XFORMAT = re.compile(r"\b(\d{1,2})\s*x\s*(\d{1,3})\b")
_RE_FA_SEASON = re.compile(r"\b(?:فصل|season|sezon)\s*(\d{1,2})\b[^\d]{0,14}?(\d{1,3})\b")
_RE_FA_EP = re.compile(r"\b(?:قسمت|بخش|پارت|اپیزود|episode|epi|ep|part|pt)\s*[._\-]?\s*(\d{1,3})\b")
_RE_EP_DOT = re.compile(r"(?:^|[\s._\-])(?:e|ep)[._\-](\d{1,3})(?:\b|$)")
_RE_E_ONLY = re.compile(r"\be[._\-]?(\d{1,3})\b")


def episode_signature(text: Optional[str]) -> str:
    """امضای «فصل/قسمت» — مثل `s01e02` یا `p12` یا `''` اگر تشخیص داده نشد."""
    s = normalize(text, drop_quality=False, drop_urls=True)
    if not s:
        return ""
    m = _RE_SXXEYY.search(s)
    if m:
        return "s%02de%03d" % (int(m.group(1)), int(m.group(2)))
    m = _RE_XFORMAT.search(s)
    if m:
        return "s%02de%03d" % (int(m.group(1)), int(m.group(2)))
    m = _RE_FA_SEASON.search(s)
    if m:
        return "s%02de%03d" % (int(m.group(1)), int(m.group(2)))
    m = _RE_FA_EP.search(s)
    if m:
        return "p%03d" % int(m.group(1))
    m = _RE_EP_DOT.search(s)
    if m:
        return "p%03d" % int(m.group(1))
    m = _RE_E_ONLY.search(s)
    if m:
        return "p%03d" % int(m.group(1))
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# ۳) سنجه‌های شباهت
# ─────────────────────────────────────────────────────────────────────────────

def tokens(s: str) -> List[str]:
    return [t for t in (s or "").split() if t]


def token_set(s: str) -> Set[str]:
    return set(tokens(s))


def jaccard(a: str, b: str) -> float:
    """شباهتِ توکنی (Jaccard).

    حروفِ تک‌حرفی («و»، «a») نویز حساب می‌شوند و حذف می‌شوند، ولی **ارقامِ تک‌رقمی
    حذف نمی‌شوند** — وگرنه «فیلم ۱» و «فیلم ۲» شبیهِ هم می‌شدند (باگِ واقعی)."""
    ta, tb = token_set(a), token_set(b)
    if not ta or not tb:
        return 0.0

    def clean(ts: set) -> set:
        return {t for t in ts if len(t) > 1 or t.isdigit()} or ts

    sa, sb = clean(ta), clean(tb)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def ratio(a: str, b: str) -> float:
    """شباهتِ رشته‌ایِ ترتیبی (۰..۱)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def shared_token_count(a: str, b: str) -> int:
    return len(token_set(a) & token_set(b))


# ─────────────────────────────────────────────────────────────────────────────
# ۴) سیگنالِ ۱ — نامِ فایل
# ─────────────────────────────────────────────────────────────────────────────

MIN_NAME_LEN = 3


def name_similar(a: Optional[str], b: Optional[str], *, th_ratio: float = 0.82,
                 th_jaccard: float = 0.60, with_episode_guard: bool = True) -> Tuple[bool, float]:
    """آیا دو **نامِ فایل** به‌قدرِ کافی شبیه‌اند؟ (خروجی: (بله/نه، امتیاز))"""
    # همیشه نرمال‌سازی می‌کنیم؛ نرمال‌سازیِ دوباره بی‌اثر است (idempotent).
    na, nb = name_norm(a), name_norm(b)
    if not na or not nb:
        return False, 0.0
    if with_episode_guard:
        # ⚠️ امضا از متنِ خام گرفته می‌شود: توکن‌هایی مثلِ «part»/«قسمت» در
        #    نرمال‌سازیِ نام حذف می‌شوند و اگر بعد از آن امضا بگیریم، گارد از کار می‌افتد.
        ea, eb = episode_signature(a), episode_signature(b)
        if ea and eb and ea != eb:
            return False, 0.0
    if len(na) < MIN_NAME_LEN or len(nb) < MIN_NAME_LEN:
        same = na == nb
        return same, 1.0 if same else 0.0
    if na == nb:
        return True, 1.0
    j = jaccard(na, nb)
    r = ratio(na, nb)
    score = round(0.6 * r + 0.4 * j, 4)
    # پوششِ توکنی: همهٔ توکن‌های نامِ کوتاه‌تر در نامِ بلندتر باشند و طول‌ها نزدیک.
    # ⚠️ مقایسهٔ زیررشته‌ای خام این‌جا **ممنوع** است: «video 3» زیررشتهٔ «video 30»
    #    است ولی دو فایلِ کاملاً متفاوت‌اند (باگِ واقعیِ کشف‌شده در تست).
    ta, tb2 = token_set(na), token_set(nb)
    shorter, longer = (ta, tb2) if len(na) <= len(nb) else (tb2, ta)
    contains = (len(shorter) >= 2 and shorter.issubset(longer)
                and len(ta) != len(tb2)
                and (min(len(na), len(nb)) / max(len(na), len(nb)) >= 0.5))
    # 🚪 درِ فرارِ «نسبتِ بالا» فقط با پوششِ توکنیِ کافی باز می‌شود؛ وگرنه
    #    «video 3» و «video 30» (نسبتِ ۰٫۹۳) اشتباهاً یکی می‌شوند.
    ok = ((r >= th_ratio and j >= th_jaccard) or contains
          or (r >= th_ratio + 0.06 and j >= max(0.45, th_jaccard - 0.15))
          or (j >= min(0.98, th_jaccard + 0.25) and r >= 0.60))
    return bool(ok), (max(score, 0.99) if (ok and contains and r >= 0.95) else score)


# ─────────────────────────────────────────────────────────────────────────────
# ۵) سیگنالِ ۲ — کپشن
# ─────────────────────────────────────────────────────────────────────────────

MIN_CAPTION_LEN = 12


def caption_similar(a: Optional[str], b: Optional[str], *, th_ratio: float = 0.80,
                    th_jaccard: float = 0.60) -> Tuple[bool, float]:
    """آیا دو **کپشن** تکراری/شبیه‌اند؟ کپشنِ خالی هرگز تطبیق نمی‌شود."""
    ca, cb = caption_norm(a), caption_norm(b)
    if not ca or not cb:
        return False, 0.0
    if len(ca) < MIN_CAPTION_LEN or len(cb) < MIN_CAPTION_LEN:
        return False, 0.0
    if ca == cb:
        return True, 1.0
    j = jaccard(ca, cb)
    r = ratio(ca, cb)
    shared = shared_token_count(ca, cb)
    small = min(len(tokens(ca)), len(tokens(cb))) or 1
    enough_shared = shared >= 6 or (shared / small) >= 0.6
    # کپشنِ فارسیِ پرتکرار («دانلود فیلم…») نباید تنها سیگنالِ تطبیق باشد؛
    # پس برای کپشنِ کوتاه‌تر از ۲۵ نویسه سخت‌گیرتر می‌شویم.
    if min(len(ca), len(cb)) < 25:
        th_ratio, th_jaccard = max(th_ratio, 0.90), max(th_jaccard, 0.75)
    ok = (r >= th_ratio and j >= th_jaccard and enough_shared)
    return bool(ok), round(0.6 * r + 0.4 * j, 4)


# ─────────────────────────────────────────────────────────────────────────────
# ۶) سیگنالِ ۳ — حجم + زمان (تمرکزِ اصلیِ کارفرما)
# ─────────────────────────────────────────────────────────────────────────────

def size_close(a: Optional[int], b: Optional[int], *, tol_pct: float = 0.5,
               tol_min: int = 2048) -> bool:
    if not a or not b:
        return False
    a, b = int(a), int(b)
    tol = max(int(tol_min), int(round(max(a, b) * max(0.0, tol_pct) / 100.0)))
    return abs(a - b) <= tol


def size_time_same(fa: dict, fb: dict, *, size_tol_pct: float = 0.5, size_tol_min: int = 2048,
                   dur_tol_s: float = 2.0, min_size: int = 102400,
                   min_duration_s: int = 3, require_one_exact: bool = True) -> Tuple[bool, float]:
    """«۲ تا فیلم با حجمِ ۵۰ مگ و زمانِ ۱ دقیقه» ⇒ همان فایل.

    خروجی: (تطبیق، امتیاز). اگر زمانِ یکی نامعلوم باشد (۰) تطبیق رخ نمی‌دهد؛
    فقط حجمِ خالی/کوچک کافی نیست.

    `require_one_exact` (پیش‌فرض روشن): **یکی از دو مشخصه باید دقیقاً برابر باشد**
    (یا حجمِ بایت‌به‌بایت یکسان، یا زمانِ ثانیه‌به‌ثانیه). بدونِ این شرط، در کانال‌هایی
    که صدها کلیپِ هم‌اندازه با اختلافِ ۱ ثانیه دارند، همه در یک گروهِ غول‌آسا جمع
    می‌شدند (زنجیره‌شدنِ نامزدها) — باگِ واقعیِ کشف‌شده در تست.

    ⚠️ امتیاز **فقط برای رتبه‌بندی** است؛ برای «آیا حجم/زمان دقیقاً برابرند» هیچ‌وقت
    به امتیاز تکیه نکنید — `matching` از خودِ بایت‌ها/ثانیه‌ها استفاده می‌کند.
    """
    sa, sb = int(fa.get("size") or 0), int(fb.get("size") or 0)
    da, db = int(fa.get("duration") or 0), int(fb.get("duration") or 0)
    if min(sa, sb) < int(min_size):
        return False, 0.0
    if not size_close(sa, sb, tol_pct=size_tol_pct, tol_min=size_tol_min):
        return False, 0.0
    if da < min_duration_s or db < min_duration_s:
        return False, 0.0
    if abs(da - db) > float(dur_tol_s):
        return False, 0.0
    if require_one_exact and (sa != sb) and (da != db):
        return False, 0.0
    # امتیاز بر پایهٔ **تلورانس** نرمال می‌شود: ۱ ⇒ هر دو دقیقاً برابر، ۰ ⇒ روی لبهٔ تلورانس.
    # (باگِ قبلی: `sd * 100` امتیازِ حجم را همیشه ۱ می‌کرد و باعث می‌شد پرچمِ
    #  «حجم و زمان یکسان» حتی وقتی حجم‌ها فقط نزدیک بودند روشن شود.)
    tol = max(int(size_tol_min), int(round(max(sa, sb) * max(0.0, size_tol_pct) / 100.0)))
    size_score = 1.0 - min(1.0, abs(sa - sb) / float(max(1, tol)))
    dur_score = 1.0 - min(1.0, abs(da - db) / float(max(1e-9, float(dur_tol_s))))
    return True, round(0.6 * size_score + 0.4 * dur_score, 4)


def hash_equal(fa: dict, fb: dict) -> bool:
    """دو فایل با هشِ محتواییِ یکسان ⇒ قطعاً همان فایل (قوی‌ترین سیگنال)."""
    ha, hb = fa.get("content_hash"), fb.get("content_hash")
    if not ha or not hb or ha == "ERR":
        return False
    return ha == hb and str(fa.get("hash_scope") or "") == str(fb.get("hash_scope") or "")


def same_telegram_file(fa: dict, fb: dict) -> bool:
    """قطعاً همان آپلودِ تلگرام (بدونِ دانلودِ بایت) — با identify/filename/امضای سایز."""
    for key in ("file_unique_id", "file_identify", "doc_id"):
        a, b = fa.get(key), fb.get(key)
        if a and b and str(a) == str(b):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ۷) امتیازِ نهاییِ یک جفت
# ─────────────────────────────────────────────────────────────────────────────

SIGNALS = ("hash", "telegram_file", "name", "caption", "size_time")


def pair_signals(fa: dict, fb: dict, *, cfg: dict) -> dict:
    """همهٔ سیگنال‌های فعالِ میانِ دو فایل را برمی‌گرداند (برای تست و گزارش)."""
    out: dict = {}
    if hash_equal(fa, fb):
        out["hash"] = 1.0
    elif same_telegram_file(fa, fb):
        out["telegram_file"] = 1.0
    ok, sc = name_similar(fa.get("name_norm") or fa.get("name"), fb.get("name_norm") or fb.get("name"),
                          th_ratio=cfg.get("th_name_ratio", 0.82), th_jaccard=cfg.get("th_name_jaccard", 0.6))
    if ok:
        out["name"] = sc
    ok, sc = caption_similar(fa.get("caption_norm") or fa.get("caption"),
                             fb.get("caption_norm") or fb.get("caption"),
                             th_ratio=cfg.get("th_cap_ratio", 0.8), th_jaccard=cfg.get("th_cap_jaccard", 0.6))
    if ok:
        out["caption"] = sc
    ok, sc = size_time_same(fa, fb, size_tol_pct=cfg.get("size_tol_pct", 0.5),
                            size_tol_min=cfg.get("size_tol_min", 2048),
                            dur_tol_s=cfg.get("dur_tol_s", 2.0),
                            min_size=cfg.get("min_size_for_match", 102400),
                            min_duration_s=cfg.get("min_duration_s", 3))
    if ok:
        out["size_time"] = sc
    return out


def human_bytes(n: Optional[int]) -> str:
    n = int(n or 0)
    if n <= 0:
        return "؟"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    x = float(n)
    while x >= 1024 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    return ("%.2f" % x).rstrip("0").rstrip(".") + " " + units[i]


def human_duration(seconds: Optional[int]) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return "؟"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, sec)
    return "%d:%02d" % (m, sec)


def percent(a: int, b: int) -> float:
    b = int(b or 0)
    if b <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * float(a) / float(b)))
