"""گزارش‌گیری: متن‌های واضحِ فارسی، صفحه‌بندی، فورواردِ گروه‌ها (با لینکِ بازگشت به کانال)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from . import similarity as S
from .tg_api import esc

log = logging.getLogger("dup.report")

STARS = {4: "★★★★", 3: "★★★", 2: "★★", 1: "★"}
SIGNAL_FA = {"hash": "هشِ محتوا", "telegram_file": "شناسهٔ فایل", "size_time": "حجم+زمان",
             "name": "نام", "caption": "کپشن"}


def bar(pct: float, width: int = 12) -> str:
    pct = max(0.0, min(100.0, float(pct or 0)))
    full = int(round(width * pct / 100.0))
    return "█" * full + "▁" * (width - full) + " %5.1f%%" % pct


def msg_link(channel: Dict[str, Any], msg_id: int) -> str:
    u = str(channel.get("username") or "").lstrip("@")
    if u:
        return "https://t.me/%s/%d" % (u, int(msg_id))
    tg = str(channel.get("tg_id") or "")
    if tg.startswith("-100"):
        return "https://t.me/c/%s/%d" % (tg[4:], int(msg_id))
    if tg.startswith("-"):
        return "https://t.me/c/%s/%d" % (tg.lstrip("-"), int(msg_id))
    return ""


def date_fa(ts: int) -> str:
    """تاریخِ پست به وقتِ ایران (UTC+3:30) — بدونِ هشدارِ منسوخِ پایتون."""
    import datetime
    if not ts or int(ts) < 0:
        return "—"                       # پست بدونِ تاریخ (نادر) — نه ۱۹۷۰!
    try:
        d = datetime.datetime.fromtimestamp(int(ts or 0), tz=datetime.timezone.utc)
        d = d.astimezone(datetime.timezone(datetime.timedelta(hours=3, minutes=30)))
        return d.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "؟"


def file_line(f: Dict[str, Any], channel: Dict[str, Any], idx: Optional[int] = None) -> str:
    link = msg_link(channel, int(f.get("msg_id") or 0))
    num = ("%d) " % idx) if idx else ""
    name = esc(f.get("file_name") or "(بدون نام)")
    if link:
        head = '<a href="%s">%s%s</a>' % (link, num, name)
    else:
        head = "%s<b>%s</b>" % (num, name)
    meta = " · ".join([
        S.human_bytes(f.get("size")),
        S.human_duration(f.get("duration")),
        date_fa(f.get("date")),
        "پیام %s" % f.get("msg_id"),
    ])
    tail = ""
    if f.get("content_hash"):
        tail = " · 🧬 %s" % esc(str(f.get("content_hash"))[:8])
    return "• %s\n   <code>%s</code>%s" % (head, esc(meta), tail)


# ───────────────────────────── متن‌ها ─────────────────────────────

def scan_summary_text(scan: Dict[str, Any], channel: Dict[str, Any], counts: Dict[str, int],
                      *, total_indexed: int = 0, notes: Optional[List[str]] = None) -> str:
    st = {"done": "✅ کامل شد", "canceled": "⏹ کنسل شد", "error": "⚠️ خطا", "running": "⏳ در حال اجرا"}.get(
        str(scan.get("status")), str(scan.get("status")))
    lines = [
        "📊 <b>گزارشِ اسکن</b> — <b>%s</b>" % esc(channel_title(channel)),
        "وضعیت: %s" % st,
    ]
    if int(scan.get("min_id") or 0) > 0:
        lines.append("<i>🔄 ادامهٔ اسکن: فقط پیام‌های تازه‌تر از %s خوانده شد؛ گروه‌بندی روی کلِ ایندکس انجام می‌شود.</i>"
                     % _num(scan.get("min_id")))
    lines += [
        "فایل‌های دیده‌شده در این اسکن: <b>%s</b>" % _num(scan.get("files_found")),
        "پیام‌های پیمایش‌شده (تقریبی، از روی شناسه‌ها): <b>%s</b>" % _num(scan.get("seen_msgs")),
        "هشِ گرفته‌شده: <b>%s</b>" % _num(scan.get("hashed")),
    ]
    if total_indexed:
        lines.append("کلِ ویدیوهای ایندکس‌شدهٔ این کانال: <b>%s</b>" % _num(total_indexed))
    lines += [
        "",
        "🔁 <b>گروه‌های تکراری: %s</b>" % _num(scan.get("groups_found")),
        "   ★★★★ قطعی — کلِ محتوا یکی است (هشِ کامل یا شناسهٔ خودِ تلگرام): %s" % counts.get("exact", 0),
        "   🧬 نمونهٔ محتوا یکسان (سر+میانه+ته — قوی ولی نه قطعی): %s" % counts.get("content", 0),
        "   ★★★ حجم و زمان یکسان: %s" % counts.get("sizetime", 0),
        "   ★★ نامِ مشابه: %s" % counts.get("name", 0),
        "   ★ کپشنِ مشابه: %s" % counts.get("caption", 0),
    ]
    if scan.get("error"):
        lines += ["", "⚠️ خطا: <code>%s</code>" % esc(str(scan.get("error"))[:200])]
    for nt in (notes or []):
        lines += ["", "⚠️ %s" % esc(str(nt))]
    lines += ["", "<i>اولویتِ بررسی: ۱) نام ۲) کپشن ۳) حجم+زمان — هشِ <b>کامل</b> تأییدِ قطعی است "
                   "و هشِ نمونه‌ای (سه‌تکه) فقط نشانهٔ قوی است.</i>",
              "<i>ℹ️ یک گروه می‌تواند چند دلیل داشته باشد، پس جمعِ ردیف‌های بالا از تعدادِ گروه‌ها بیشتر است.</i>"]
    return "\n".join(lines)


def groups_page_text(channel: Dict[str, Any], groups: Sequence[Dict[str, Any]], page: int, pages: int,
                     filt: str, total: int) -> str:
    fname = FILTER_FA.get(filt, "همه")
    if not groups:
        return ("🔁 <b>گروه‌های تکراری</b> — %s\n\nفیلتر: %s\n\n"
                "چیزی با این فیلتر پیدا نشد." % (esc(channel.get("title") or ""), fname))
    lines = ["🔁 <b>گروه‌های تکراری</b> — %s" % esc(channel.get("title") or ""),
             "فیلتر: <b>%s</b> · کلِ گروه‌ها: <b>%d</b> · صفحه %d از %d" % (fname, total, page + 1, max(1, pages)), ""]
    for g in groups:
        stars = STARS.get(int(g.get("strength") or 0), "★")
        reason = esc(g.get("reason") or "")
        lines.append("🔸 <b>#%s</b> · %s · <b>%s فایل</b>\n    دلیل: %s" % (
            g.get("id"), stars, _num(g.get("count")), reason))
    lines.append("")
    lines.append("<i>روی هر گروه بزنید تا فایل‌ها را ببینید و با فوروارد به چت خودتان بفرستید.</i>")
    lines.append("<i>فیلترها هم‌پوشانی دارند: گروهِ ★★★★ در «حجم+زمان» و «نام» هم دیده می‌شود.</i>")
    return "\n".join(lines)


def group_detail_text(channel: Dict[str, Any], g: Dict[str, Any], members: Sequence[Dict[str, Any]],
                      *, max_show: int = 20) -> str:
    stars = STARS.get(int(g.get("strength") or 0), "★")
    uniq_sizes = len({int(m.get("size") or 0) for m in members})
    uniq_dur = len({int(m.get("duration") or 0) for m in members})
    lines = [
        "%s <b>گروه #%s</b> — %s" % (stars, g.get("id"), esc(channel.get("title") or "")),
        "دلیلِ تشخیص: <b>%s</b>" % esc(g.get("reason") or ""),
        "تعدادِ فایل‌ها: <b>%d</b> · حجم‌های یکتا: <b>%d</b> · زمان‌های یکتا: <b>%d</b>" % (
            len(members), uniq_sizes, uniq_dur),
        "",
    ]
    m0 = members[0]
    lines.append("📐 نمونه: <b>%s</b> · <b>%s</b>" % (S.human_bytes(m0.get("size")), S.human_duration(m0.get("duration"))))
    if str(g.get("state") or "open") != "open":
        lines.append("وضعیت: %s" % ("✔ رسیدگی‌شده" if g.get("state") == "done" else "🔒 نادیده‌گرفته‌شده"))
    lines.append("")
    for i, m in enumerate(list(members)[:max_show], 1):
        lines.append(file_line(m, channel, i))
    if len(members) > max_show:
        lines.append("… و <b>%d</b> فایلِ دیگر (با دکمهٔ فوروارد همه فرستاده می‌شوند)." % (len(members) - max_show))
    return "\n".join(lines)


def links_text(channel: Dict[str, Any], members: Sequence[Dict[str, Any]]) -> str:
    lines = ["🔗 <b>لینکِ پیام‌ها</b> — %s" % esc(channel.get("title") or ""), ""]
    for i, m in enumerate(members, 1):
        link = msg_link(channel, int(m.get("msg_id") or 0))
        nm = esc((m.get("file_name") or "(بدون نام)")[:60])
        lines.append("%d) %s\n   <a href=\"%s\">%s</a>" % (i, nm, link, link or "—"))
    return "\n".join(lines)


FILTER_FA = {"all": "همه", "exact": "★★★★ قطعی", "content": "🧬 نمونهٔ محتوا",
             "sizetime": "★★★ حجم+زمان", "name": "★★ نام", "caption": "★ کپشن",
             "open": "فقط رسیدگی‌نشده"}
FILTERS = ["all", "exact", "content", "sizetime", "name", "caption", "open"]


# راهنمای ثابتِ فرمتِ کدِ ورود: تلگرام کدِ یک‌پارچه را «قبلاً به‌اشتراک‌گذاشته» می‌شمارد
# و ورود را بلاک می‌کند (پیامِ «Incomplete login attempt» در تلگرام).
CODE_FORMAT_HELP = ("⛔️ کد را <b>به‌هم‌چسبیده</b> نفرستید (<code>12345</code> ممنوع!) — تلگرام آن را "
                    "«قبلاً به‌اشتراک‌گذاشته» می‌داند و ورود را بلاک می‌کند.\n"
                    "✅ کد را <b>رقم‌رقم</b> بفرستید: <code>1 2 3 4 5</code>")


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(x: Any) -> str:
    """ارقامِ لاتین ⇒ فارسی (برای شمارهٔ گام‌ها و شمارنده‌های کوتاه)."""
    return str(x).translate(_FA_DIGITS)


def _num(x: Any) -> str:
    try:
        return "{:,}".format(int(x or 0))
    except Exception:
        return str(x)


# ───────────────────────────── کیبوردها ─────────────────────────────

def reply_kb(rows: List[List[Dict[str, Any]]], *, placeholder: str = "") -> Dict[str, Any]:
    """کیبوردِ زیرِ کادرِ تایپ (ReplyKeyboard) — برای دکمهٔ «ارسالِ شمارهٔ من».

    با one_time_keyboard بعد از یک‌بار استفاده خودش جمع می‌شود.
    """
    out: Dict[str, Any] = {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}
    if placeholder:
        out["input_field_placeholder"] = placeholder[:64]
    return out


def contact_btn(text: str = "📱 ارسالِ شمارهٔ من") -> Dict[str, Any]:
    """دکمهٔ اشتراکِ شمارهٔ تماس (کاربر فقط یک‌بار می‌زند)."""
    return {"text": text, "request_contact": True}


def text_btn(text: str) -> Dict[str, Any]:
    return {"text": text}


def remove_kb() -> Dict[str, Any]:
    return {"remove_keyboard": True}


def channel_title(c: Dict[str, Any]) -> str:
    """نامِ نمایشیِ کانال: عنوان، بعد یوزرنیم، و در آخر شناسه (هیچ‌وقت شناسه اول نمی‌آید)."""
    return str(c.get("title") or "").strip() or ("@" + str(c.get("username") or "").strip() if c.get("username") else "") \
        or ("کانال " + str(c.get("tg_id") or ""))


def kb(rows: List[List[Dict[str, str]]]) -> Dict[str, Any]:
    return {"inline_keyboard": rows}


def btn(text: str, cb: str = "") -> Dict[str, str]:
    return {"text": text} if not cb else {"text": text, "callback_data": cb}


def groups_kb(channel_id: int, scan_id: int, filt: str, page: int, pages: int,
              page_groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[List[Dict[str, str]]] = []
    for g in page_groups:
        stars = STARS.get(int(g.get("strength") or 0), "★")
        rows.append([btn("%s #%s · %s فایل · %s" % (stars, g.get("id"), g.get("count"),
                                                  (g.get("reason") or "")[:28]),
                         "g:%d:%d:%s:%d:%d" % (scan_id, channel_id, filt, page, int(g.get("id"))))])
    frow = []
    for f in FILTERS:
        mark = "• " if f == filt else ""
        frow.append(btn(mark + FILTER_FA[f], "l:%d:%d:%s:0" % (scan_id, channel_id, f)))
        if len(frow) == 3:
            rows.append(frow); frow = []
    if frow:
        rows.append(frow)
    if pages > 1:
        nav = [btn("⏮", "p:%d:%d:%s:0" % (scan_id, channel_id, filt)),
               btn("◀", "p:%d:%d:%s:%d" % (scan_id, channel_id, filt, max(0, page - 1))),
               btn("%d/%d" % (page + 1, pages), "nop"),
               btn("▶", "p:%d:%d:%s:%d" % (scan_id, channel_id, filt, min(pages - 1, page + 1))),
               btn("⏭", "p:%d:%d:%s:%d" % (scan_id, channel_id, filt, pages - 1))]
        rows.append(nav)
    rows.append([btn("🔄 به‌روزرسانی", "p:%d:%d:%s:%d" % (scan_id, channel_id, filt, page)),
                 btn("📊 خلاصهٔ اسکن", "s:%d:%d" % (scan_id, channel_id))])
    rows.append([btn("🏠 کانال‌ها", "ch:list")])
    return kb(rows)


def group_kb(channel_id: int, scan_id: int, filt: str, page: int, gid: int, *,
             can_forward: bool = True) -> Dict[str, Any]:
    head = [[btn("📎 فوروارد فایل‌های این گروه",
                 "f:%d:%d:%s:%d:%d" % (scan_id, channel_id, filt, page, gid))]] if can_forward else []
    return kb(head + [
        [btn("🔗 لینکِ پیام‌ها", "u:%d:%d:%d" % (scan_id, channel_id, gid))],
        [btn("✔ رسیدگی شد", "m:%d:%d:%d:done" % (scan_id, channel_id, gid)),
         btn("🔒 نادیده بگیر", "m:%d:%d:%d:ign" % (scan_id, channel_id, gid))],
        [btn("◀ بازگشت به فهرست", "p:%d:%d:%s:%d" % (scan_id, channel_id, filt, page))],
    ])


def progress_text(phase: str, ch_title: str, pct: float, *, seen: int = 0, total: int = 0,
                  files: int = 0, hashed: int = 0, hash_total: int = 0, note: str = "",
                  cur_id: int = 0, top_id: int = 0) -> str:
    head = {"index": "📥 مرورِ تاریخچه", "hash": "🧬 هش‌گذاری", "match": "🧠 تحلیل و گروه‌بندی",
            "done": "✅ پایان", "canceled": "⏹ کنسل شد", "error": "⚠️ خطا"}.get(phase, phase)
    lines = ["<b>%s</b> — %s" % (head, esc(ch_title or "")),
             "<code>%s</code>" % bar(pct)]
    if phase in ("index", "hash"):
        if top_id and cur_id:
            lines.append("پیشرفت بر اساسِ شمارهٔ پیام: <b>#%s</b> از <b>#%s</b>"
                         % (_num(cur_id), _num(top_id)))
        tot = (" از %s پیامِ کانال" % _num(total)) if total else ""
        lines.append("ویدیوهای پیداشده تا حالا: <b>%s</b>%s" % (_num(seen), tot))
    lines.append("ویدیوهای پیداشده: <b>%s</b>" % _num(files))
    if hash_total:
        lines.append("هش‌گذاری: <b>%s</b> از %s" % (_num(hashed), _num(hash_total)))
    if note:
        lines.append("<i>%s</i>" % esc(note))
    return "\n".join(lines)


def progress_kb() -> Dict[str, Any]:
    return kb([[btn("⏹ توقف و کنسل", "scan:cancel")]])


# ───────────────────────────── فوروارد ─────────────────────────────

class Reporter:
    """فورواردِ فایل‌های یک گروه به چتِ مالک — با سه مسیرِ پشت‌سرهم و **بدونِ حذفِ چیزی**."""

    def __init__(self, api, user=None, *, max_per_group: int = 12):
        self.api = api
        self.user = user                      # کلاینتِ کاربری (فال‌بک دوم)؛ می‌تواند None باشد
        self.max_per_group = int(max_per_group)

    async def forward_group(self, owner_chat: int, channel: Dict[str, Any], members: Sequence[Dict[str, Any]],
                            *, offset: int = 0) -> Dict[str, Any]:
        members = list(members)
        chunk = members[offset: offset + self.max_per_group]
        sent, failed = 0, []
        for m in chunk:
            ok = await self._forward_one(owner_chat, channel, int(m.get("msg_id") or 0), m)
            if ok:
                sent += 1
            else:
                failed.append(int(m.get("msg_id") or 0))
        return {"sent": sent, "failed": failed, "offset": offset + len(chunk),
                "remaining": max(0, len(members) - (offset + len(chunk))), "total": len(members)}

    async def _forward_one(self, owner_chat: int, channel: Dict[str, Any], msg_id: int, member: Dict[str, Any]) -> bool:
        tg_id = int(channel.get("tg_id") or 0)
        # ۱) فوروارد با ربات (خروجیِ «برو تو کانال ببین» همین است)
        try:
            await self.api.forward_message(owner_chat, tg_id, msg_id)
            return True
        except Exception as e:
            log.info("forward ربات ناموفق (msg=%s): %s", msg_id, e)
        # ۲) فوروارد با حسابِ کاربری
        if self.user is not None and getattr(self.user, "ready", False):
            try:
                if await self.user.forward(owner_chat, tg_id, [msg_id]):
                    return True
            except Exception as e:
                log.info("forward کاربری ناموفق: %s", e)
        # ۳) کپی + لینک (اگر محتوا محافظت‌شده باشد، فقط لینک)
        try:
            await self.api.copy_message(owner_chat, tg_id, msg_id)
            return True
        except Exception:
            pass
        link = msg_link(channel, msg_id)
        if link:
            try:
                await self.api.send_message(owner_chat, "🔗 %s\n%s" % (esc((member.get("file_name") or "")[:60]), link))
                return True
            except Exception:
                pass
        return False
