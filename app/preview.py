"""اسکنِ محدود — بدونِ حسابِ کاربری، از **پیش‌نمایشِ عمومیِ** تلگرام (`t.me/s/<username>`).

تلگرام برای کانال‌های عمومی یک نسخهٔ وبِ سبک می‌دهد که آخرین پست‌ها را نشان می‌دهد.
از آن‌جا می‌توانیم: شمارهٔ پیام، تاریخ، **کپشن**، **زمانِ ویدیو** و نوعِ مدیا را بخوانیم.
آن‌چه **در دسترس نیست**: حجمِ فایل و کلِ تاریخچه (فقط چند صفحهٔ آخر).

پس این حالت صادقانه «محدود» نامیده می‌شود:
  • تشخیص بر پایهٔ کپشن/نام است (حجم و هش ممکن نیست)
  • فقط چند صفحهٔ آخرِ کانال پیمایش می‌شود
  • فورواردِ فایل ممکن نیست (ربات دسترسی ندارد) ⇒ «🔗 لینکِ پیام‌ها» جایگزین است

همهٔ توابعِ تجزیه **خالص** هستند تا بدونِ شبکه هم تست شوند (`fetch_page` تنها بخشِ شبکه‌ای است).
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

_URL = "https://t.me/s/%s"
_EXT = re.compile(r"\.(?:mkv|mp4|avi|mov|m4v|webm|ts|mpg|mpeg|flv|wmv|zip|rar|pdf)\b", re.I)
_QUALITY = re.compile(r"(?:\d{3,4}p|4k|8k|2160p|x26[45]|hevc|web-?dl|web-?rip|bluray|blu-?ray|hdtv|dubbed|دوبله)", re.I)
_MSG_SPLIT = re.compile(r'<div class="tgme_widget_message_wrap')
_POST = re.compile(r'data-post="([^"/]+)/(\d+)"')
_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>\s*(?:<div|</div>)', re.S)
_DUR = re.compile(r'js-message_video_duration"[^>]*>\s*([0-9:]{2,12})\s*<')
_TAGS = re.compile(r"<[^>]+>")


def duration_seconds(txt: str) -> int:
    """«0:27» ⇒ ۲۷ · «1:02:03» ⇒ ۳۷۲۳"""
    parts = [p for p in str(txt or "").strip().split(":") if p != ""]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if not nums:
        return 0
    sec = 0
    for n in nums:
        sec = sec * 60 + n
    return sec


def to_epoch(iso: str) -> int:
    """«2026-10-05T18:32:11+00:00» ⇒ زمانِ یونیکس (۰ اگر نامفهوم بود)."""
    s = str(iso or "").strip().replace("Z", "+00:00")
    if not s:
        return 0
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        return 0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def strip_html(fragment: str) -> str:
    """تگ‌ها/`<br>` را تبدیل به متنِ ساده می‌کند (برای کپشنِ چندخطی)."""
    s = str(fragment or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAGS.sub("", s)
    return _html.unescape(s).strip()


def name_from_caption(caption: str) -> str:
    """اگر کپشن شبیهِ نامِ فایل بود، همان را به‌عنوانِ نام می‌گیریم؛ وگرنه خالی."""
    text = str(caption or "").strip()
    if not text:
        return ""
    first = ""
    for line in text.splitlines():
        if line.strip():
            first = line.strip()
            break
    if not first or len(first) < 6:
        return ""
    if _EXT.search(first) or _QUALITY.search(first):
        return first[:150]
    return ""


def parse_messages(page: str, username: str = "") -> List[Dict[str, Any]]:
    """HTMLِ پیش‌نمایش ⇒ ردیف‌های فایل (فقط پست‌های دارای مدیا).

    هر ردیف: {msg_id, date, caption, file_name, duration, mime, has_video, size=0}
    (`size` صفر است چون تلگرام در پیش‌نمایشِ وب حجم نمی‌دهد.)
    """
    out: List[Dict[str, Any]] = []
    if not page:
        return out
    for block in _MSG_SPLIT.split(page)[1:]:
        m = _POST.search(block)
        if not m:
            continue
        who, mid = m.group(1), int(m.group(2))
        is_video = ("js-message_video_duration" in block) or ("message_video_play" in block)
        is_photo = "tgme_widget_message_photo_wrap" in block
        if not (is_video or is_photo):
            continue                                   # متن/صدا/سندِ دیگر را کاری نداریم
        cap = ""
        tm = _TEXT.search(block)
        if tm:
            cap = strip_html(tm.group(1))
        dur = 0
        dm = _DUR.search(block)
        if dm:
            dur = duration_seconds(dm.group(1))
        t = _TIME.search(block)
        out.append({
            "msg_id": int(mid),
            "date": to_epoch(t.group(1) if t else ""),
            "caption": cap,
            "file_name": name_from_caption(cap),
            "duration": int(dur),
            "mime": "video/mp4" if is_video else "",
            "has_video": 1 if is_video else 0,
            "has_photo": 1 if is_photo and not is_video else 0,
            "size": 0,
            "channel_username": who or username,
        })
    # قدیم ⇒ جدید (مثلِ اسکنِ عادی)
    out.sort(key=lambda r: int(r.get("msg_id") or 0))
    return out


async def fetch_page(username: str, before: int = 0, *, timeout: float = 25.0) -> str:
    """یک صفحهٔ پیش‌نمایش را می‌خواند (`before` = فقط پیام‌های قدیمی‌تر از این شناسه)."""
    import aiohttp
    uname = str(username or "").lstrip("@").strip()
    if not uname:
        return ""
    url = _URL % uname
    if before:
        url += "?before=%d" % int(before)
    headers = {"User-Agent": UA, "Accept-Language": "fa,en;q=0.8"}
    tmo = aiohttp.ClientTimeout(total=float(timeout))
    async with aiohttp.ClientSession(timeout=tmo, headers=headers) as ses:
        async with ses.get(url) as resp:
            if resp.status != 200:
                return ""
            return await resp.text()


def oldest_id(rows: List[Dict[str, Any]]) -> int:
    ids = [int(r.get("msg_id") or 0) for r in (rows or [])]
    return min(ids) if ids else 0
