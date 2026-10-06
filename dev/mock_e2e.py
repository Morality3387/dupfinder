#!/usr/bin/env python3
"""✨ اجرای نمایشیِ کاملِ ربات بدونِ تلگرام — همان مسیری که کاربر می‌رود.

اجرا:  python3 dev/mock_e2e.py            (بدونِ توکن، بدونِ شبکه)
خروجی: متنِ دقیقِ همان پیام‌هایی که ربات در تلگرام می‌فرستد + جمع‌بندیِ تست.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bot_app import BotApp                     # noqa: E402
from app.config import Settings                    # noqa: E402
from app.db import Db                              # noqa: E402
from dev.fake_telegram import FakeApi, FakeUser, channel_dataset  # noqa: E402

CHAT, OWNER = 111, 1


def plain(html_text: str) -> str:
    """تبدیلِ متنِ HTMLِ تلگرام به متنِ خوانا برای ترمینال."""
    t = re.sub(r"<a href=\"[^\"]+\">([^<]*)</a>", r"\1", html_text)
    t = re.sub(r"</?(b|i|u|s|code|pre)>", "", t)
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return t


class Show:
    """پیام‌ها را با ترتیبِ واقعی چاپ می‌کند (ارسال یا ویرایش)."""

    def __init__(self, api: FakeApi, *, only_last_edit_per_msg: bool = False):
        self.api = api
        self.pos = 0
        self.last_edit_seen: dict = {}
        self.only_last = only_last_edit_per_msg

    def flush(self) -> None:
        calls = self.api.calls
        while self.pos < len(calls):
            method, params = calls[self.pos]
            self.pos += 1
            if method == "sendMessage":
                print("\n🤖 %s" % plain(str(params.get("text") or "")))
                self._kb(params.get("reply_markup"))
            elif method == "editMessageText":
                self.last_edit_seen[params.get("message_id")] = params.get("text")
            elif method == "forwardMessage":
                print("   📎 فوروارد پیام %s از کانال %s به چت" % (params.get("message_id"), params.get("from_chat_id")))
            elif method == "copyMessage":
                print("   📄 کپی پیام %s (فوروارد ممکن نبود)" % params.get("message_id"))
            elif method == "deleteMessage":
                print("   🗑 حذف پیام %s (فقط پیامِ خودِ کاربر/ربات در چتِ ربات)" % params.get("message_id"))
        # آخرین ویرایش‌های معلقِ اسکن را نشان بده
        for mid, text in list(self.last_edit_seen.items()):
            if self.only_last:
                print("\n♻️ [ویرایشِ پیامِ پیشرفت] %s" % plain(str(text)))
                del self.last_edit_seen[mid]

    def _kb(self, kb) -> None:
        if not kb:
            return
        rows = (kb or {}).get("inline_keyboard") or []
        for row in rows:
            print("      [ " + " ] [ ".join(b["text"] for b in row) + " ]")


def main() -> int:
    tmp = tempfile.mkdtemp()
    db = Db(os.path.join(tmp, "demo.db"))
    ds = channel_dataset()
    user = FakeUser(videos={55: ds["videos"]}, contents=ds["contents"], titles={55: ds["title"]}, delay=0.01)
    api = FakeApi(chats={55: {"id": 55, "title": "کانالِ تست", "username": "testchan"}})
    settings = Settings(bot_token="demo", owner_id=OWNER, db_path=os.path.join(tmp, "x.db"),
                        page_size=3, progress_interval=0.0, max_forward_per_group=3)
    bot = BotApp(api, db, settings, user)
    show = Show(api)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def run(coro):
        return loop.run_until_complete(coro)

    def text(t):
        run(bot.handle_message({"chat": {"id": CHAT}, "from": {"id": OWNER}, "text": t, "message_id": 1}))
        show.flush()

    def tap(data, mid=5):
        run(bot.handle_callback({"id": "cq", "data": data, "from": {"id": OWNER},
                                "message": {"chat": {"id": CHAT}, "message_id": mid}}))
        show.flush()

    print("═" * 78)
    print("  DupFinder — اجرای نمایشیِ کامل (همان پیام‌هایی که در تلگرام می‌بینید)")
    print("═" * 78)
    text("/start")
    text("/help")
    print("\n" + "─" * 78 + "\n➊ افزودنِ کانال با یوزرنیم")
    tap("ch:add")
    text("@testchan")
    cid = db.list_channels()[-1]["id"]

    print("\n" + "─" * 78 + "\n➋ اسکنِ کاملِ کانال (۱۳ ویدیو، شاملِ ۴ نوع تکرار)")
    tap("scan:full:%d" % cid)
    task = bot.scan["task"]
    if task and not task.done():
        run(task)
    show.only_last = True
    show.flush()
    scan_id = db.last_scan(cid)["id"]
    print("\n   ℹ️ پیشرفتِ اسکن در %d ویرایشِ پیام گزارش شد." % len([e for e in api.edits if "%" in e["text"]]))

    print("\n" + "─" * 78 + "\n➌ فهرستِ گروه‌های تکراری (صفحهٔ ۱)")
    tap("l:%d:%d:all:0" % (scan_id, cid))
    print("\n" + "─" * 78 + "\n➍ فقط گروهِ ★★★ «حجم و زمان یکسان» (تمرکزِ اصلی)")
    tap("l:%d:%d:sizetime:0" % (scan_id, cid))

    groups = db.groups_of_scan(scan_id, signal="sizetime")
    gid = groups[0]["id"]
    print("\n" + "─" * 78 + "\n➎ داخلِ گروهِ ★★★")
    tap("g:%d:%d:sizetime:0:%d" % (scan_id, cid, gid))
    print("\n" + "─" * 78 + "\n➏ فورواردِ فایل‌های گروه به چت (برای پریدن روی پستِ کانال)")
    tap("f:%d:%d:sizetime:0:%d" % (scan_id, cid, gid))
    print("\n" + "─" * 78 + "\n➐ لینکِ پیام‌ها (اگر فوروارد ممکن نباشد)")
    tap("u:%d:%d:%d" % (scan_id, cid, gid))
    print("\n" + "─" * 78 + "\n➑ کنسل کردنِ اسکنِ در جریان (دکمهٔ «⏹ توقف و کنسل»)")
    run(bot._start_scan(CHAT, cid, full=True))

    async def cancel_when_started():
        for _ in range(500):
            sc = bot.scan.get("scanner") if bot.scan else None
            if sc and sc.progress.files >= 4:
                break
            await asyncio.sleep(0.005)
        await bot._cancel_scan(CHAT)
        await bot.scan["task"]
    run(cancel_when_started())
    show.only_last = True
    show.flush()
    print("   ℹ️ نتیجه: %s · فایل‌های حفظ‌شده: %d" % (bot.scan["result"].status, db.count_files(cid)))

    print("\n" + "═" * 78)
    print("  جمع‌بندیِ آنچه ربات پیدا کرد")
    print("═" * 78)
    for g in db.groups_of_scan(scan_id):
        members = db.group_members(g["id"])
        msgs = ", ".join(str(m["msg_id"]) for m in members)
        stars = {4: "★★★★", 3: "★★★", 2: "★★", 1: "★"}.get(int(g["strength"]), "★")
        print("  %-4s #%-3s  %-42s  %d فایل  (پیام‌ها: %s)" % (stars, g["id"], g["reason"], len(members), msgs))
    print("\n  فایل‌های ایندکس‌شده: %d · هش‌شده: %d · گروه‌ها: %d" % (
        db.count_files(cid),
        len([f for f in db.files_of_channel(cid) if f["content_hash"]]),
        len(db.groups_of_scan(scan_id))))
    print("  🛡 حذف‌شده از کانال: %d   (ربات هیچ فایلی حذف نمی‌کند)" % len(
        [c for c in api.calls if c[0] == "deleteMessage" and c[1].get("chat_id") == 55]))
    print("  📎 فورواردهای انجام‌شده: %d" % len(api.forwards))
    print("═" * 78)
    db.close()
    loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
