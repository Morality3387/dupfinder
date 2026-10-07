"""شبیه‌سازِ تلگرام برای تست‌های سرتاسری — بدونِ شبکه، بدونِ توکن.

`FakeApi` جای `TgApi` و `FakeUser` جای `UserClient` می‌نشیند و همهٔ فراخوانی‌ها را
ثبت می‌کنند تا بتوانیم ادعاهای واقعی بزنیم: «چه چیزی فرستاده شد؟» و «آیا چیزی
از کانال پاک/ویرایش شد؟».
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.tg_api import TgError
from app.user_client import _kind_ok, chunk_plan


class FakeApi:
    """Bot API ساختگیِ درون‌حافظه‌ای."""

    def __init__(self, *, me: Optional[Dict[str, Any]] = None, chats: Optional[Dict[int, Dict[str, Any]]] = None):
        self.me = me or {"id": 999, "username": "dup_test_bot", "first_name": "Dup"}
        self.chats = chats or {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.sent: List[Dict[str, Any]] = []          # پیام‌های ارسالی به چتِ مالک
        self.edits: List[Dict[str, Any]] = []
        self.forwards: List[Dict[str, Any]] = []
        self.deletes: List[Dict[str, Any]] = []
        self._mid = 1000
        self._mid_seq = {}          # message_id ⇒ شمارهٔ ترتیبِ ساخت (برای «آخرین چیزی که کاربر دید»)
        self.fail_forward_ids: set = set()
        self.fail_copy_ids: set = set()
        self.updates: List[Dict[str, Any]] = []
        self.member_status: Dict[Tuple[int, int], str] = {}
        # 🚫 DK-15: چت‌هایی که ربات در آن‌ها «دسترسی ندارد» (برای تستِ هشدارِ قطعِ ارسال)
        self.blocked: set = set()
        # 💾 DK-16: فایل‌های پشتیبانِ «ساخته‌شده» و «آپلودشده» (file_id ⇒ بایت‌ها)
        self.docs: Dict[str, bytes] = {}
        self.media_edits: List[Dict[str, Any]] = []
        self.webhook: str = ""

    # ── ابزار ──
    def _log(self, method: str, **params: Any) -> None:
        self.calls.append((method, params))

    def _resolve(self, chat_id: Any) -> Any:
        """مثلِ تلگرام: «@username» به شناسهٔ عددیِ همان چت تبدیل می‌شود (DK-15: گروهِ چک)."""
        if isinstance(chat_id, str):
            s = chat_id.strip()
            if s.startswith("@"):
                for cid, c in self.chats.items():
                    if ("@" + str(c.get("username") or "")) == s:
                        return int(cid)
                return s
            if s.lstrip("-").isdigit():
                return int(s)
        return chat_id

    def _is_blocked(self, chat_id: Any) -> bool:
        rid = self._resolve(chat_id)
        for b in getattr(self, "blocked", set()):
            if str(b) == str(rid):
                return True
        return False

    def next_mid(self) -> int:
        """شناسهٔ پیامِ بعدی که این fake برمی‌گردانَد (برای آماده‌سازیِ پاسخِ سرور)."""
        return int(self._mid) + 1

    def messages_with(self, text: str) -> List[Dict[str, Any]]:
        return [m for m in self.sent if text in str(m.get("text") or "")]

    def methods(self) -> List[str]:
        return [m for m, _ in self.calls]

    # ── Bot API ──
    async def get_me(self) -> Dict[str, Any]:
        self._log("getMe")
        return self.me

    async def get_updates(self, offset: int = 0, timeout: int = 25) -> List[Dict[str, Any]]:
        self._log("getUpdates", offset=offset)
        out, self.updates = self.updates, []
        await asyncio.sleep(0)
        return out

    async def send_message(self, chat_id: int, text: str, *, kb: Optional[dict] = None,
                           parse_mode: str = "HTML", preview: bool = False, silent: bool = False,
                           reply_to: Optional[int] = None,
                           kb_extra: Optional[dict] = None) -> Dict[str, Any]:
        if self._is_blocked(chat_id):
            raise TgError("sendMessage", 403, "CHAT_WRITE_FORBIDDEN")
        chat_id = self._resolve(chat_id)
        self._mid += 1
        rec = {"message_id": self._mid, "chat_id": int(chat_id), "text": text,
               "kb": kb if kb is not None else kb_extra, "parse_mode": parse_mode}
        self._mid_seq[self._mid] = self._mid
        self.sent.append(rec)
        self._log("sendMessage", chat_id=chat_id, text=text, reply_markup=kb)
        return rec

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, *,
                                kb: Optional[dict] = None, parse_mode: str = "HTML") -> Any:
        self.edits.append({"chat_id": int(chat_id), "message_id": int(message_id), "text": text, "kb": kb})
        self._log("editMessageText", chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb)
        return {"message_id": message_id}

    async def delete_message(self, chat_id: int, message_id: int) -> Any:
        self.deletes.append({"chat_id": int(chat_id), "message_id": int(message_id)})
        self._log("deleteMessage", chat_id=chat_id, message_id=message_id)
        return True

    async def answer_callback(self, cq_id: str, text: str = "", *, alert: bool = False) -> Any:
        self._log("answerCallbackQuery", callback_query_id=cq_id, text=text)
        return True

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> Any:
        self._log("sendChatAction", chat_id=chat_id, action=action)
        return True

    async def forward_message(self, to_chat: int, from_chat: int, message_id: int) -> Dict[str, Any]:
        self._log("forwardMessage", chat_id=to_chat, from_chat_id=from_chat, message_id=message_id)
        if self._is_blocked(to_chat):
            raise TgError("forwardMessage", 403, "CHAT_WRITE_FORBIDDEN")
        to_chat = self._resolve(to_chat)
        if int(message_id) in self.fail_forward_ids:
            raise TgError("forwardMessage", 400, "CHAT_FORWARDS_RESTRICTED")
        self.forwards.append({"to": int(to_chat), "from": int(from_chat), "msg_id": int(message_id)})
        self._mid += 1
        payload: Dict[str, Any] = {"message_id": self._mid}
        # 💾 DK-16: اگر «محتوای کپی‌شده» را از قبل ثبت کرده‌اند، همان را هم می‌دهیم
        if str(self._mid) in getattr(self, "docs", {}):
            payload["document"] = {"file_id": str(self._mid), "file_name": "copy.json.gz"}
            self.updates.append({"message": {"message_id": self._mid, "chat": {"id": to_chat},
                                            "document": payload["document"]}})
        return payload

    async def send_media_group(self, to_chat: int, from_chat: int, message_ids: List[int]) -> List[Dict[str, Any]]:
        """📎 ارسالِ آلبومی (DK-15): همان پیام‌ها یک‌جا ⇒ فایل دوباره آپلود نمی‌شود."""
        ids = [int(x) for x in (message_ids or [])][:10]
        self._log("sendMediaGroup", chat_id=to_chat, from_chat_id=from_chat, message_ids=ids)
        if self._is_blocked(to_chat):
            raise TgError("sendMediaGroup", 403, "CHAT_WRITE_FORBIDDEN")
        to_chat = self._resolve(to_chat)
        if any(i in self.fail_forward_ids for i in ids):
            raise TgError("sendMediaGroup", 400, "CHAT_FORWARDS_RESTRICTED")
        if not ids:
            raise TgError("sendMediaGroup", 400, "MEDIA_GROUP_INVALID")
        self.forwards.append({"to": int(to_chat), "from": int(from_chat), "ids": ids,
                              "msg_id": ids[0], "album": True})
        self._mid += 1
        return [{"message_id": self._mid}]

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, *,
                                        kb: Optional[Dict[str, Any]] = None) -> Any:
        self.edits.append({"chat_id": int(chat_id), "message_id": int(message_id), "kb": kb})
        self._log("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup=kb)
        return True

    async def copy_message(self, to_chat: int, from_chat: int, message_id: int) -> Dict[str, Any]:
        self._log("copyMessage", chat_id=to_chat, from_chat_id=from_chat, message_id=message_id)
        if self._is_blocked(to_chat):
            raise TgError("copyMessage", 403, "CHAT_WRITE_FORBIDDEN")
        to_chat = self._resolve(to_chat)
        if int(message_id) in self.fail_copy_ids:
            raise TgError("copyMessage", 400, "CHAT_FORWARDS_RESTRICTED")
        self._mid += 1
        return {"message_id": self._mid}

    async def get_chat(self, chat_id: Any) -> Dict[str, Any]:
        self._log("getChat", chat_id=chat_id)
        key = chat_id
        if isinstance(chat_id, str) and chat_id.startswith("@"):
            for cid, c in self.chats.items():
                if ("@" + str(c.get("username"))) == chat_id:
                    return c
            raise TgError("getChat", 400, "chat not found")
        if key in self.chats:
            return self.chats[key]
        raise TgError("getChat", 400, "chat not found")

    async def get_chat_member(self, chat_id: Any, user_id: int) -> Dict[str, Any]:
        self._log("getChatMember", chat_id=chat_id, user_id=user_id)
        st = self.member_status.get((int(chat_id), int(user_id)), "administrator")
        return {"status": st}

    async def get_chat_member_count(self, chat_id: Any) -> int:
        self._log("getChatMemberCount", chat_id=chat_id)
        return 0

    async def set_my_commands(self, commands: List[Dict[str, str]]) -> Any:
        self._log("setMyCommands", commands=commands)
        return True

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        # 💾 DK-16: `file_path` لازم است تا ربات بتواند فایلِ پشتیبان را دانلود کند
        if str(file_id) in getattr(self, "docs", {}):
            return {"file_id": str(file_id), "file_path": str(file_id), "file_size": len(self.docs[str(file_id)])}
        return {"file_id": file_id}

    # ── 💾 DK-16: فایلِ پشتیبان ──
    def backup_message(self, data: bytes, *, name: str = "dupfinder-hashes_test_1.json.gz",
                       mid: int = 4242, caption: str = "") -> Dict[str, Any]:
        """پیامی می‌سازد که یک فایلِ پشتیبان دارد (برای تستِ «کاربر فایل را فرستاد»)."""
        self.docs[str(mid)] = bytes(data)
        return {"message_id": int(mid), "chat": {"id": 0}, "from": {"id": 0}, "caption": caption,
                "document": {"file_id": str(mid), "file_name": name,
                             "mime_type": "application/gzip", "file_size": len(data)}}

    async def send_document(self, to_chat: int, filename: str, data: bytes, *,
                            caption: str = "") -> Dict[str, Any]:
        if self._is_blocked(to_chat):
            raise TgError("sendDocument", 403, "CHAT_WRITE_FORBIDDEN")
        to_chat = self._resolve(to_chat)
        self._mid += 1
        mid = self._mid
        self.docs[str(mid)] = bytes(data)
        rec = {"message_id": mid, "chat_id": int(to_chat), "document": {"file_id": str(mid),
               "file_name": str(filename), "file_size": len(data)}, "caption": caption,
               "text": caption}
        self.sent.append(rec)
        self._log("sendDocument", chat_id=to_chat, filename=filename, size=len(data))
        return rec

    async def edit_message_media(self, chat_id: int, message_id: int, filename: str, data: bytes, *,
                                 caption: str = "") -> Any:
        chat_id = self._resolve(chat_id)
        self._mid += 1
        mid = self._mid
        self.docs[str(mid)] = bytes(data)
        self.media_edits.append({"chat_id": int(chat_id), "message_id": int(message_id),
                                 "filename": str(filename), "size": len(data), "new_file_id": str(mid)})
        self._log("editMessageMedia", chat_id=chat_id, message_id=message_id, filename=filename)
        return {"message_id": int(message_id), "document": {"file_id": str(mid)}}

    async def download_file(self, file_path: str, *, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        fid = str(file_path)
        if fid not in self.docs:
            raise TgError("getFile", 400, "file not found")
        data = self.docs[fid]
        if max_bytes and len(data) > int(max_bytes):
            raise TgError("download", 413, "too big")
        self._log("download", file_id=fid, size=len(data))
        return data

    async def set_webhook(self, url: str) -> Any:
        self.webhook = str(url)
        self._log("setWebhook", url=url)
        return True

    async def delete_webhook(self, drop_pending: bool = True) -> Any:
        self.webhook = ""
        self._log("deleteWebhook", drop_pending_updates=drop_pending)
        return True

    async def close(self) -> None:
        return None


def content_hash_of(data: bytes, size: int = 0, *, scope: str = "sample") -> str:
    """همان الگوریتمِ UserClient.hash_file (برای تست‌های قطعیِ «هشِ یکسان»).

    `scope="sample"` ⇒ سه تکهٔ سر/میانه/ته · `scope="full"` ⇒ کلِ محتوا.
    """
    size = int(size or len(data))
    h = hashlib.sha256()
    h.update(str(size).encode())
    if str(scope or "sample").lower() == "full":
        h.update(b"|full")
        data = data[:size]
        h.update(data)
    else:
        for off, ln in chunk_plan(size):
            h.update(str(off).encode())
            h.update(data[off:off + ln])
    return h.hexdigest()[:32]


class FakeUser:
    """کلاینتِ کاربریِ ساختگی: تاریخچهٔ کانال + هشِ محتواییِ درون‌حافظه‌ای."""

    def __init__(self, *, videos: Optional[Dict[int, List[Dict[str, Any]]]] = None,
                 contents: Optional[Dict[Tuple[int, int], bytes]] = None,
                 titles: Optional[Dict[int, Dict[str, Any]]] = None, ready: bool = True,
                 delay: float = 0.0, total_hint: int = 0):
        self.videos = videos or {}
        self.contents = contents or {}
        self.titles = titles or {}
        self._ready = ready
        self.me = {"id": 777, "username": "dupe_user", "name": "Dup User"}
        self.session_string = "FAKE_SESSION" if ready else ""
        self.api_id = 12345
        self.api_hash = "x" * 32
        self.delay = float(delay)
        self.total_hint = int(total_hint)
        self.hints: Dict[int, Dict[str, Any]] = {}
        self.blocked: set = set()                 # 🚫 چت‌هایی که فورواردِ کاربری به آن‌ها ممکن نیست
        self.peer_hashes: Dict[int, int] = {}
        self.entity_misses: List[int] = []
        self.hash_batches: List[int] = []
        self.forwarded: List[Dict[str, Any]] = []
        self.last_error = ""
        self.probed: List[int] = []
        self.qr_times_out: bool = False          # برای تستِ انقضای QR
        self.empty_hint: bool = False            # کانالِ کاملاً خالی (برای تستِ پاک‌سازی)
        self.qr_refresh_limit: int = 99
        self.admin_fails: bool = False
        self._admins: Dict[int, set] = {}
        self.code_requests: List[str] = []      # شماره‌هایی که برایشان کد خواسته شده
        self.sign_in_calls: List[str] = []      # کدهایی که برای ورود تلاش شده
        self.qr_starts: int = 0
        self.qr_recreates: int = 0
        self.admin_calls: List[Dict[str, Any]] = []   # ادمین‌کردن‌های انجام‌شده
        self.admin_rights: Dict[str, Any] = {}

    # ── وضعیت ──
    @property
    def configured(self) -> bool:
        return True

    @property
    def ready(self) -> bool:
        return self._ready

    async def start(self) -> bool:
        return self._ready

    async def stop(self) -> None:
        self._ready = False

    async def send_code(self, phone: str) -> str:
        self.last_code_phone = phone
        self.code_requests.append(str(phone))
        return "hash-%d-%s" % (len(self.code_requests), phone)

    async def sign_in(self, phone: str, code: str, phone_code_hash: str = "") -> Dict[str, Any]:
        """۵۵۵۵۵ ✅ · ۱۱۱۱۱ رمزِ دو مرحله‌ای · ۹۹۹۹۹ کدِ منقضی · ۷۷۷۷۷ کدِ اشتباه."""
        self.sign_in_calls.append(str(code))
        c = str(code).replace(" ", "").replace("-", "")
        if c == "55555":
            self._ready = True
            self.session_string = "FAKE_SESSION"
            return {"ok": True, "need_password": False, "error": "", "kind": "ok"}
        if c == "11111":
            return {"ok": False, "need_password": True, "error": "", "kind": "password"}
        if c == "99999":
            return {"ok": False, "need_password": False, "kind": "expired",
                    "error": "The confirmation code has expired (caused by SignInRequest)"}
        if c == "77777":
            return {"ok": False, "need_password": False, "kind": "invalid", "error": "PHONE_CODE_INVALID"}
        return {"ok": False, "need_password": False, "kind": "invalid", "error": "PHONE_CODE_INVALID"}

    async def sign_in_password(self, password: str) -> Dict[str, Any]:
        if password == "secret":
            self._ready = True
            self.session_string = "FAKE_SESSION"
            return {"ok": True, "error": "", "kind": "ok"}
        return {"ok": False, "error": "PASSWORD_HASH_INVALID", "kind": "password"}

    # ── ورود با QR ──
    async def qr_login_start(self) -> Dict[str, Any]:
        self.qr_starts += 1
        return {"url": "tg://login?token=FAKEQR%d" % self.qr_starts}

    async def qr_login_wait(self, timeout: float = 25.0) -> Dict[str, Any]:
        if getattr(self, "_qr_confirmed", False):
            self._ready = True
            self.session_string = "FAKE_SESSION"
            return {"ok": True, "me": self.me}
        if self.qr_times_out:
            return {"ok": False, "expired": True, "error": "timeout"}
        return {"ok": False, "error": "other"}

    async def qr_login_recreate(self) -> str:
        self.qr_recreates += 1
        if self.qr_recreates >= self.qr_refresh_limit:
            return ""
        return "tg://login?token=FAKEQR%d" % (self.qr_starts + self.qr_recreates)

    # ── ادمینِ کانال ──
    async def add_bot_admin(self, tg_id: int, bot_id: int, *, can_post: bool = True,
                            can_edit: bool = True) -> Dict[str, Any]:
        self.admin_calls.append({"tg_id": int(tg_id), "bot_id": int(bot_id)})
        self.admin_rights = {"post_messages": bool(can_post), "edit_messages": bool(can_edit)}
        if self.admin_fails:
            return {"ok": False, "error": "CHAT_ADMIN_REQUIRED"}
        self._admins.setdefault(int(tg_id), set()).add(int(bot_id))
        return {"ok": True, "error": ""}

    async def is_bot_admin(self, tg_id: int, bot_id: int) -> bool:
        return int(bot_id) in self._admins.get(int(tg_id), set())

    async def resolve(self, ref: Any) -> Optional[Dict[str, Any]]:
        key = int(ref) if str(ref).lstrip("-").isdigit() else ref
        info = self.titles.get(key)
        if info:
            return dict(info)
        return None

    async def probe(self, tg_id: int) -> Dict[str, Any]:
        self.probed.append(int(tg_id))
        rows = self.videos.get(int(tg_id), [])
        last = max([int(r.get("msg_id") or 0) for r in rows] or [0])
        t = (self.titles.get(int(tg_id)) or {})
        return {"total": self.total_hint or len(rows), "last_id": last,
                "title": str(t.get("title") or "")}      # مثلِ کلاینتِ واقعی عنوان هم می‌دهد

    async def iter_videos(self, tg_id: int, *, min_id: int = 0, max_id: int = 0, media_kinds: str = "video",
                          wait_time: float = 0.3, batch: int = 200, stats: Optional[Dict[str, Any]] = None):
        """همان قراردادِ `UserClient.iter_videos` — با آمارِ `visited/matched/completed`."""
        if stats is not None:
            stats.clear()
            stats["visited"] = 0
            stats["matched"] = 0
            stats["completed"] = False
        all_rows = [dict(r) for r in self.videos.get(int(tg_id), []) if int(r.get("msg_id") or 0) > int(min_id or 0)]
        # همان فیلترِ کلاینتِ واقعی (قبلاً حالتِ «video+doc»/«all» در شبیه‌ساز بی‌اثر بود)
        rows = [r for r in all_rows if _kind_ok(r, media_kinds)]
        rows.sort(key=lambda r: int(r.get("msg_id") or 0))
        if stats is not None:
            stats["entity_ok"] = True
            # مثلِ کلاینتِ واقعی: `visited` همهٔ پیام‌های پیمایش‌شده است (نه فقط هم‌نوع‌ها)
            stats["visited"] = len(all_rows)
            stats["matched"] = len(rows)
        for r in rows:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield r
        if stats is not None:
            stats["completed"] = True

    async def channel_is_empty(self, tg_id: int) -> bool:
        """در شبیه‌ساز: کانال وقتی خالی است که هیچ فایلی نداشته باشد (تعدادِ `empty_hint` هم صفر)."""
        return not self.videos.get(int(tg_id), []) and not int(self.total_hint or 0)

    # ── همان API کلاینتِ واقعی برای هینت/هشِ دسترسی (کانالِ خصوصی) ──
    def set_hint(self, tg_id: int, *, username: str = "", access_hash: Optional[int] = None,
                 title: str = "") -> None:
        try:
            key = abs(int(tg_id))
        except Exception:
            return
        h = self.hints.setdefault(key, {})
        if username:
            h["username"] = str(username).lstrip("@")
        if title:
            h["title"] = str(title)
        if access_hash:
            self.peer_hashes[key] = int(access_hash)
            h["access_hash"] = int(access_hash)

    def peer_snapshot(self):
        return {str(k): int(v) for k, v in self.peer_hashes.items() if v}

    async def hash_file(self, tg_id: int, msg_id: int, size: int, *, scope: str = "sample",
                        mode: str = ""):
        sc = scope if scope and scope != "sample" else ("full" if str(mode or "").lower() == "full" else "sample")
        out = await self.hash_batch(tg_id, [(msg_id, size)], scope=sc)
        return out.get(int(msg_id), ("", ""))

    async def hash_batch(self, tg_id: int, items: Sequence[Tuple[int, int]], *, scope: str = "sample",
                         full_max_bytes: int = 0) -> Dict[int, Tuple[str, str]]:
        self.hash_batches.append(len(items))
        want_full = str(scope or "sample").lower() == "full"
        out: Dict[int, Tuple[str, str]] = {}
        for msg_id, size in items:
            data = self.contents.get((int(tg_id), int(msg_id)))
            if data is None:
                out[int(msg_id)] = ("", "")
                continue
            sc = "full" if (want_full and (not full_max_bytes or int(size or 0) <= full_max_bytes)) else "sample"
            out[int(msg_id)] = (content_hash_of(data, size or len(data), scope=sc),
                                "full" if sc == "full" else "fake")
            await asyncio.sleep(0)
        return out

    async def forward(self, to_chat: int, tg_id: int, msg_ids: Sequence[int]) -> bool:
        if any(str(b) == str(to_chat) for b in getattr(self, "blocked", set())):
            return False
        self.forwarded.append({"to": int(to_chat), "from": int(tg_id), "ids": list(msg_ids)})
        return True


# ───────────────────────────── کارخانهٔ دادهٔ ساختگی ─────────────────────────────

MB = 1024 * 1024


def video(msg_id: int, name: str, *, size: int = 50 * MB, duration: int = 60, caption: str = "",
          date: int = 1760000000, grouped_id: int = 0, mime: str = "video/mp4",
          doc_id: int = 0, unique_id: str = "") -> Dict[str, Any]:
    return {"msg_id": msg_id, "grouped_id": grouped_id, "date": date, "doc_id": doc_id or msg_id,
            "file_unique_id": unique_id or ("U%d" % msg_id), "file_identify": str(doc_id or msg_id),
            "file_name": name, "caption": caption, "size": int(size), "duration": int(duration),
            "mime": mime, "width": 1920, "height": 1080, "has_video": 1, "protected": 0}


def doc(msg_id: int, name: str, size: int, caption: str = "", mime: str = "application/pdf",
        doc_id: int = 0) -> Dict[str, Any]:
    """سندِ غیرِ‌ویدیویی (pdf/zip/…) — برای آزمایشِ حالتِ «video+doc» و «all»."""
    return {"msg_id": int(msg_id), "grouped_id": 0, "date": 1760000000 + int(msg_id), "doc_id": int(doc_id or msg_id),
            "file_unique_id": "u%d" % int(msg_id), "file_identify": str(doc_id or msg_id),
            "file_name": name, "caption": caption, "size": int(size), "duration": 0, "mime": mime,
            "width": 0, "height": 0, "kind": "doc"}


def channel_dataset() -> Dict[str, Any]:
    """سناریوی کاملِ تست: هر نوع تکراری که ربات باید پیدا کند."""
    v = [
        # ۱) تکراریِ قطعی با هش (دو آپلودِ جدا، بایت‌های یکسان)
        video(101, "Black.Mirror.S01E01.1080p.WEB-DL.x265.mkv", size=200 * MB, duration=3600,
              caption="قسمت اول فصل یک", doc_id=9001),
        video(102, "Black.Mirror.S01E01.1080p.WEB-DL.x265 (copy).mkv", size=200 * MB, duration=3600,
              caption="قسمت اول فصل یک", doc_id=9002),
        # ۲) نامِ مشابه (کیفیتِ متفاوت) — همان حجم/زمان هم
        video(110, "Inception.2010.1080p.BluRay.x264.mkv", size=180 * MB, duration=8880,
              caption="فیلم اینسپشن دوبله", doc_id=9010),
        video(111, "Inception.2010.720p.BluRay.x264.mkv", size=180 * MB, duration=8880,
              caption="فیلم اینسپشن دوبله", doc_id=9011),
        # ۳) کپشنِ یکسان، نامِ متفاوت، حجم/زمان متفاوت
        video(120, "clip-a401.mp4", size=12 * MB, duration=143,
              caption="برنامهٔ ویژهٔ هفتهٔ اول پاییز با اجرای مهمان", doc_id=9020),
        video(121, "clip-b902.mp4", size=9 * MB, duration=121,
              caption="برنامهٔ ویژهٔ هفتهٔ اول پاییز با اجرای مهمان", doc_id=9021),
        # ۴) حجم و زمانِ یکسان، نام و کپشنِ بی‌ربط ⇒ موردِ ★★★ کارفرما
        video(130, "recording_1402_05_11.mp4", size=50 * MB, duration=60, caption="", doc_id=9030),
        video(131, "zaban-3-final.mp4", size=50 * MB, duration=60, caption="", doc_id=9031),
        video(132, "IMG_8842.mp4", size=50 * MB, duration=61, caption="", doc_id=9032),
        # ۵) قسمت‌های پشت‌سرهم — **نباید** تکراری شمرده شوند
        video(140, "Series.X.S01E01.1080p.mkv", size=100 * MB, duration=2400, caption="قسمت ۱", doc_id=9040),
        video(141, "Series.X.S01E02.1080p.mkv", size=101 * MB, duration=2410, caption="قسمت ۲", doc_id=9041),
        video(142, "Series.X.S01E03.1080p.mkv", size=99 * MB, duration=2395, caption="قسمت ۳", doc_id=9042),
        # ۶) فایلِ تکی (بدونِ هیچ تکرار)
        video(150, "Unique.Lecture.mp4", size=77 * MB, duration=1800, caption="درسِ یگانه", doc_id=9050),
        # ۷) سندِ غیرِ‌ویدیویی — فقط در حالتِ «video+doc» / «all» دیده می‌شود
        doc(160, "کتابِ آموزشِ پایتون.pdf", size=18 * MB, caption="کتاب آموزش پایتون", doc_id=9060),
    ]
    # محتوا: ۱۰۱ و ۱۰۲ بایت‌به‌بایت یکسان. «محتوا» فقط برای پایداریِ هش است؛
    # بایت‌های واقعیِ فایل لازم نیست (تکه‌های بیرون از داده ⇒ خالی حساب می‌شوند)،
    # وگرنه ساختِ گیگابایت داده در تست‌ها کند می‌شود.
    contents: Dict[Tuple[int, int], bytes] = {}
    same = bytes((i * 7) % 251 for i in range(20_000))
    contents[(55, 101)] = same
    contents[(55, 102)] = same
    alphabet = b"abcdefghijklmnopqrstuvwxyz"
    for row in v:
        m = int(row["msg_id"])
        if (55, m) in contents:
            continue
        contents[(55, m)] = bytes(alphabet[(m + i) % 26] for i in range(20_000))
    return {"tg_id": 55, "title": {"tg_id": 55, "title": "کانالِ تست", "username": "testchan", "kind": "channel"},
            "videos": v, "contents": contents}
