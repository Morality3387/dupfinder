"""کلاینتِ کاربری (Telethon) — لازم برای دیدنِ **تاریخچهٔ کامل** کانال و هش‌گذاری.

رباتِ معمولی (Bot API) از یک نقطه به بعد تاریخچهٔ کانال را نمی‌بیند؛ با حسابِ
کاربری (این کلاس) `messages.getHistory` کامل خوانده می‌شود و دانلودِ جزئی هم ممکن است.
همهٔ تعامل‌ها فقط **خواندن** است؛ هیچ‌جا پیام/فایلی پاک نمی‌شود.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("dup.user")

CHUNK = 131072  # ۱۲۸KB — مضربِ ۴۰۹۶ (شرطِ MTProto برای offset/limit)


def _is_video_kind(mime: str, kind: str) -> bool:
    mime = str(mime or "").lower()
    kind = str(kind or "video")
    if kind == "all":
        return True
    if kind in ("video", "video+doc"):
        if mime.startswith("video/"):
            return True
        if kind == "video+doc" and mime and not mime.startswith(("image/", "audio/")):
            return True
        return False
    return mime.startswith("video/")


class UserClient:
    """پوششِ Telethon. اگر وارد نشده باشد `ready=False` و ربات در حالتِ محدود کار می‌کند."""

    def __init__(self, api_id: int = 0, api_hash: str = "", session_string: str = "", *,
                 session_factory=None):
        self.api_id = int(api_id or 0)
        self.api_hash = api_hash or ""
        self.session_string = session_string or ""
        self.client = None
        self.me: Dict[str, Any] = {}
        self._session_factory = session_factory
        self.last_error = ""
        self.chunk_delay = 0.12        # مکثِ کوتاه بین تکه‌های دانلود (مراعاتِ محدودیتِ تلگرام)
        # شمارنده‌ها — برای گزارش/دیباگ و هم‌نامی با شبیه‌سازِ تست‌ها
        self.probed: List[int] = []
        self.hash_batches: List[int] = []
        self.forwarded: List[Dict[str, Any]] = []

    # ── چرخهٔ عمر ──
    @property
    def configured(self) -> bool:
        return bool(self.api_id and self.api_hash)

    @property
    def ready(self) -> bool:
        try:
            return bool(self.client and self.client.is_connected() and self.session_string)
        except Exception:
            return False

    async def start(self) -> bool:
        """اتصال با سشنِ ذخیره‌شده (اگر هست). خروجی: آماده یا نه."""
        if not self.configured or not self.session_string:
            return False
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            if self.client is None:
                self.client = TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash,
                                             device_model="DupFinder", system_version="Railway",
                                             app_version="1.0")
            await self.client.connect()
            if not await self.client.is_user_authorized():
                self.last_error = "سشن معتبر نیست"
                return False
            me = await self.client.get_me()
            self.me = {"id": getattr(me, "id", 0), "username": getattr(me, "username", "") or "",
                       "name": " ".join(x for x in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if x)}
            self.session_string = self.client.session.save()
            return True
        except Exception as e:  # pragma: no cover - وابسته به شبکه
            self.last_error = str(e)
            log.warning("اتصالِ کلاینتِ کاربری ناموفق: %s", e)
            return False

    async def stop(self) -> None:
        try:
            if self.client:
                await self.client.disconnect()
        except Exception:
            pass

    # ── ورود ──
    async def connect_only(self) -> bool:
        if not self.configured:
            return False
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        if self.client is None:
            self.client = TelegramClient(StringSession(self.session_string), self.api_id, self.api_hash,
                                         device_model="DupFinder", system_version="Railway", app_version="1.0")
        if not self.client.is_connected():
            await self.client.connect()
        return True

    async def send_code(self, phone: str) -> str:
        """درخواستِ کدِ ورود. هر بار صدا زده شود، **کدِ قبلی باطل می‌شود**.

        شماره نرمال می‌شود (ارقام + پیشوندِ «+») تا هم شمارهٔ تایپ‌شده و هم
        شمارهٔ دکمهٔ «ارسالِ شمارهٔ من» درست کار کند.
        """
        phone = norm_phone(phone)
        await self.connect_only()
        sent = await self.client.send_code_request(phone)
        self.last_code_phone = phone
        log.info("کدِ ورود برای %s…%s فرستاده شد", phone[:4], phone[-3:])
        return str(getattr(sent, "phone_code_hash", "") or "")

    async def sign_in(self, phone: str, code: str, phone_code_hash: str = "") -> Dict[str, Any]:
        """خروجی: {ok, need_password, error, kind}

        kind ∈ ok | password | expired | invalid | flood | other — ربات با آن پیامِ
        درست به کاربر می‌دهد (مثلاً «کدِ تازه بفرست» به‌جای برگشتن به گامِ اول).
        """
        from telethon.errors import (SessionPasswordNeededError, PhoneCodeExpiredError,
                                     PhoneCodeInvalidError, PhoneCodeEmptyError, FloodWaitError)
        code = str(code).replace(" ", "").replace("-", "").strip()
        phone = norm_phone(phone)
        try:
            await self.connect_only()
            kwargs: Dict[str, Any] = {}
            if phone_code_hash:
                kwargs["phone_code_hash"] = phone_code_hash
            await self.client.sign_in(phone=phone, code=code, **kwargs)
        except SessionPasswordNeededError:
            log.info("کد درست بود؛ حساب رمزِ دو مرحله‌ای دارد")
            return {"ok": False, "need_password": True, "error": "", "kind": "password"}
        except (PhoneCodeExpiredError, PhoneCodeEmptyError) as e:
            log.warning("sign_in: کدِ منقضی/خالی (%s)", e)
            return {"ok": False, "need_password": False, "error": str(e), "kind": "expired"}
        except PhoneCodeInvalidError as e:
            log.warning("sign_in: کدِ اشتباه (%s)", e)
            return {"ok": False, "need_password": False, "error": str(e), "kind": "invalid"}
        except FloodWaitError as e:
            log.warning("sign_in: FloodWait %s ثانیه", getattr(e, "seconds", "?"))
            return {"ok": False, "need_password": False,
                    "error": "FLOOD_WAIT_%s" % getattr(e, "seconds", ""), "kind": "flood"}
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            kind = ("expired" if "expired" in low else
                    "invalid" if "invalid" in low else
                    "flood" if "flood" in low or "too many" in low else "other")
            log.warning("sign_in ناموفق (%s): %s", kind, msg)
            return {"ok": False, "need_password": False, "error": msg, "kind": kind}
        self.session_string = self.client.session.save()
        me = await self.client.get_me()
        self.me = {"id": getattr(me, "id", 0), "username": getattr(me, "username", "") or "",
                   "name": " ".join(x for x in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if x)}
        return {"ok": True, "need_password": False, "error": ""}

    async def sign_in_password(self, password: str) -> Dict[str, Any]:
        try:
            await self.connect_only()
            await self.client.sign_in(password=str(password))
        except Exception as e:
            low = str(e).lower()
            kind = "flood" if "flood" in low else ("password" if "password" in low else "other")
            log.warning("sign_in_password ناموفق (%s): %s", kind, e)
            return {"ok": False, "error": str(e), "kind": kind}
        self.session_string = self.client.session.save()
        me = await self.client.get_me()
        self.me = {"id": getattr(me, "id", 0), "username": getattr(me, "username", "") or "",
                   "name": " ".join(x for x in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if x)}
        return {"ok": True, "error": ""}

    # ── ورود با QR (بدونِ کدِ ورود ⇒ بدونِ ریسکِ «code previously shared») ──
    async def qr_login_start(self) -> Optional[Dict[str, Any]]:
        """شروعِ ورودِ QR. خروجی: {url, token} یا None."""
        try:
            await self.connect_only()
            self._qr = await self.client.qr_login()
            return {"url": str(getattr(self._qr, "url", "") or "")}
        except Exception as e:
            self.last_error = str(e)
            log.warning("qr_login_start ناموفق: %s", e)
            return None

    async def qr_login_wait(self, timeout: float = 25.0) -> Dict[str, Any]:
        """انتظار برای تأییدِ کاربر در تلگرام. خروجی: {ok|expired|error}"""
        qr = getattr(self, "_qr", None)
        if qr is None:
            return {"ok": False, "error": "no_qr"}
        try:
            user = await qr.wait(timeout=float(timeout))
            self.session_string = self.client.session.save()
            self.me = {"id": getattr(user, "id", 0), "username": getattr(user, "username", "") or "",
                       "name": " ".join(x for x in [getattr(user, "first_name", ""),
                                                    getattr(user, "last_name", "")] if x)}
            log.info("ورودِ QR تأیید شد (id=%s)", self.me.get("id"))
            return {"ok": True, "me": self.me}
        except asyncio.TimeoutError:
            return {"ok": False, "expired": True, "error": "timeout"}
        except Exception as e:
            low = str(e).lower()
            if "timeout" in low or "expired" in low:
                return {"ok": False, "expired": True, "error": str(e)}
            log.warning("qr_login_wait ناموفق: %s", e)
            return {"ok": False, "error": str(e)}

    async def qr_login_recreate(self) -> str:
        """توکنِ تازه برای QR (کدِ قبلی باطل می‌شود). خروجی: url تازه."""
        qr = getattr(self, "_qr", None)
        if qr is None:
            return ""
        try:
            await qr.recreate()
            return str(getattr(qr, "url", "") or "")
        except Exception as e:
            log.warning("qr_login_recreate ناموفق: %s", e)
            return ""

    # ── ادمین‌کردنِ ربات در کانال (با حسابِ کاربری) ──
    async def add_bot_admin(self, tg_id: int, bot_id: int, *, can_post: bool = True,
                            can_edit: bool = True) -> Dict[str, Any]:
        """ربات را ادمینِ کانال/گروه می‌کند.

        ⚠️ عمداً **هیچ‌وقت** مجوزِ حذفِ پیام (`delete_messages`) داده نمی‌شود؛
        ربات فقط می‌خواند/فوروارد می‌کند.
        """
        try:
            from telethon.tl.functions.channels import EditAdminRequest
            from telethon.tl.types import ChannelAdminRights
            rights = ChannelAdminRights(post_messages=bool(can_post), edit_messages=bool(can_edit))
            ent = await self.client.get_input_entity(int(tg_id))
            await self.client(EditAdminRequest(channel=ent, user_id=int(bot_id), admin_rights=rights))
            log.info("ربات (id=%s) ادمینِ %s شد (بدونِ مجوزِ حذف)", bot_id, tg_id)
            return {"ok": True, "error": ""}
        except Exception as e:
            log.warning("add_bot_admin ناموفق: %s", e)
            return {"ok": False, "error": str(e)}

    async def is_bot_admin(self, tg_id: int, bot_id: int) -> bool:
        """آیا ربات ادمینِ این کانال/گروه است؟"""
        try:
            from telethon.tl.functions.channels import GetParticipantRequest
            from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator
            ent = await self.client.get_input_entity(int(tg_id))
            res = await self.client(GetParticipantRequest(channel=ent, participant=int(bot_id)))
            p = getattr(res, "participant", None)
            return isinstance(p, (ChannelParticipantAdmin, ChannelParticipantCreator))
        except Exception as e:
            log.debug("is_bot_admin: %s", e)
            return False

    # ── خواندنِ کانال ──
    async def resolve(self, ref: Any) -> Optional[Dict[str, Any]]:
        """شناسه/یوزرنیم/لینک ⇒ {tg_id,title,username,kind}"""
        ent = await self.client.get_entity(ref)
        if ent is None:
            return None
        # چتِ کامل ⇒ برای private access_hash لازم است
        try:
            full = await self.client.get_entity(getattr(ent, "id", ent))
        except Exception:
            full = ent
        ent = full if full is not None else ent
        return {
            "tg_id": int(getattr(ent, "id", 0) or 0),
            "title": getattr(ent, "title", "") or "",
            "username": getattr(ent, "username", "") or "",
            "kind": "channel" if getattr(ent, "broadcast", False) else "group",
        }

    @staticmethod
    def msg_to_file(msg: Any) -> Optional[Dict[str, Any]]:
        """تبدیلِ پیامِ Telethon به ردیفِ فایل (فقط ویدیو/سندِ ویدیویی)."""
        try:
            doc = getattr(msg, "document", None)
            video = getattr(msg, "video", None)
            if doc is None and video is None:
                return None
            mime = str(getattr(doc, "mime_type", "") or "")
            if video is None and not mime.startswith("video/"):
                return None
            size = 0
            duration = 0
            width = height = 0
            fname = ""
            try:
                f = getattr(msg, "file", None)
                if f is not None:
                    size = int(getattr(f, "size", 0) or 0)
                    fname = str(getattr(f, "name", "") or "")
                    duration = int(getattr(f, "duration", 0) or 0)
                    width = int(getattr(f, "width", 0) or 0)
                    height = int(getattr(f, "height", 0) or 0)
            except Exception:
                pass
            if not size and doc is not None:
                size = int(getattr(doc, "size", 0) or 0)
            for attr in (getattr(doc, "attributes", None) or []):
                cn = type(attr).__name__
                if cn == "DocumentAttributeFilename" and not fname:
                    fname = str(getattr(attr, "file_name", "") or "")
                if cn == "DocumentAttributeVideo":
                    duration = duration or int(getattr(attr, "duration", 0) or 0)
                    width = width or int(getattr(attr, "w", 0) or 0)
                    height = height or int(getattr(attr, "h", 0) or 0)
            protected = 1 if (getattr(msg, "noforwards", False) or
                              getattr(getattr(msg, "chat", None), "noforwards", False)) else 0
            return {
                "msg_id": int(getattr(msg, "id", 0) or 0),
                "grouped_id": int(getattr(msg, "grouped_id", 0) or 0),
                "date": int(getattr(getattr(msg, "date", None), "timestamp", lambda: 0)() or 0),
                "doc_id": int(getattr(doc, "id", 0) or 0),
                "file_unique_id": str(getattr(getattr(msg, "file", None), "unique_id", "") or ""),
                "file_identify": str(getattr(doc, "id", "") or ""),
                "file_name": fname,
                "caption": str(getattr(msg, "message", "") or ""),
                "size": int(size or 0),
                "duration": int(duration or 0),
                "mime": mime,
                "width": int(width or 0),
                "height": int(height or 0),
                "has_video": 1 if (video is not None or mime.startswith("video/")) else 0,
                "protected": protected,
            }
        except Exception as e:  # pragma: no cover
            log.debug("msg_to_file خطا: %s", e)
            return None

    async def iter_videos(self, tg_id: int, *, min_id: int = 0, max_id: int = 0,
                          media_kinds: str = "video", wait_time: float = 0.3,
                          batch: int = 200) -> AsyncIterator[Dict[str, Any]]:
        """پیمایشِ **کاملِ** تاریخچه (قدیم → جدید) و بازگرداندنِ فایل‌های ویدیویی."""
        ent = await self.client.get_input_entity(tg_id)
        buf: List[Dict[str, Any]] = []
        kwargs: Dict[str, Any] = {"min_id": int(min_id or 0), "reverse": True, "wait_time": float(wait_time or 0)}
        if max_id:
            kwargs["max_id"] = int(max_id)
        async for msg in self.client.iter_messages(ent, **kwargs):
            if getattr(msg, "action", None) is not None and getattr(msg, "media", None) is None:
                continue
            row = self.msg_to_file(msg)
            if not row:
                continue
            if not _is_video_kind(row["mime"], media_kinds) and not row.get("has_video"):
                continue
            buf.append(row)
            if len(buf) >= batch:
                for r in buf:
                    yield r
                buf = []
        for r in buf:
            yield r

    async def probe(self, tg_id: int) -> Dict[str, Any]:
        """{total, last_id, title} — برای نوارِ درصدِ اسکن.

        `total` تعدادِ کلِ پیام‌های تاریخچهٔ کانال است (GetHistory.count) و
        `last_id` شناسهٔ تازه‌ترین پیام؛ هیچ‌کدام محتوایی دانلود نمی‌کنند.
        ⚠️ این متد را داخلِ حلقهٔ پیام‌ها صدا نزنید (یک‌بار قبل از اسکن کافی است).
        """
        out: Dict[str, Any] = {"total": 0, "last_id": 0, "title": ""}
        try:
            ent = await self.client.get_input_entity(tg_id)
            self.probed.append(int(tg_id))
            try:
                from telethon.tl.functions.messages import GetHistoryRequest
                res = await self.client(GetHistoryRequest(peer=ent, offset_id=0, offset_date=None,
                                                          add_offset=0, limit=1, max_id=0, min_id=0, hash=0))
                out["total"] = int(getattr(res, "count", 0) or 0)
                msgs = [m for m in (getattr(res, "messages", None) or []) if getattr(m, "id", None)]
                if msgs:
                    out["last_id"] = int(getattr(msgs[0], "id", 0) or 0)
            except Exception as e:
                log.debug("probe/GetHistory خطا: %s", e)
            if not out["last_id"]:                      # فال‌بکِ سبک
                latest = await self.client.get_messages(ent, limit=1)
                if latest:
                    out["last_id"] = int(getattr(latest[0], "id", 0) or 0)
            try:
                full = await self.client.get_entity(tg_id)
                out["title"] = getattr(full, "title", "") or ""
            except Exception:
                pass
        except Exception as e:
            log.info("probe(%s) خطا: %s", tg_id, e)
        return out

    async def hash_file(self, tg_id: int, msg_id: int, size: int = 0, *,
                        mode: str = "head+mid+tail") -> Tuple[str, str]:
        """هشِ محتوایی از چند تکهٔ فایل (بدونِ دانلودِ کامل). خروجی: (هش، دامنه)"""
        try:
            ent = await self.client.get_input_entity(tg_id)
            msg = await self.client.get_messages(ent, ids=int(msg_id))
            if msg is None or getattr(msg, "media", None) is None:
                return "", ""
            return await self._hash_msg(msg, size)
        except Exception as e:
            log.debug("hash_file(%s/%s) خطا: %s", tg_id, msg_id, e)
            return "", ""

    async def hash_batch(self, tg_id: int, items: Sequence[Tuple[int, int]],
                         *, concurrency: int = 3) -> Dict[int, Tuple[str, str]]:
        """هشِ گروهی: پیام‌ها را یک‌جا می‌گیرد و تکه‌های هر فایل را با محدودیتِ هم‌زمانی می‌خواند.

        ورودی: [(msg_id, size), …]   خروجی: {msg_id: (هش، دامنه)}
        هیچ فایلی دانلودِ کامل یا پاک نمی‌شود — فقط سر/میانه/دُم (۱۲۸KB هر تکه).
        """
        out: Dict[int, Tuple[str, str]] = {}
        todo = [(int(m), int(s or 0)) for m, s in (items or [])]
        if not todo:
            return out
        ent = await self.client.get_input_entity(tg_id)
        try:
            msgs = await self.client.get_messages(ent, ids=[m for m, _ in todo])
        except Exception as e:
            log.info("hash_batch/گرفتنِ پیام‌ها ناموفق (%s) — تک‌تک ادامه می‌دهیم", e)
            msgs = []
        by_id: Dict[int, Any] = {}
        for m in (msgs or []):
            if m is not None:
                by_id[int(getattr(m, "id", 0) or 0)] = m
        sem = asyncio.Semaphore(max(1, int(concurrency)))

        async def work(msg_id: int, size: int) -> Tuple[str, str]:
            async with sem:
                msg = by_id.get(msg_id)
                if msg is None:
                    try:
                        msg = await self.client.get_messages(ent, ids=msg_id)
                    except Exception:
                        msg = None
                if msg is None or getattr(msg, "media", None) is None:
                    return "", ""
                return await self._hash_msg(msg, size)

        results = await asyncio.gather(*[work(m, s) for m, s in todo], return_exceptions=True)
        for (msg_id, _size), r in zip(todo, results):
            out[msg_id] = r if isinstance(r, tuple) else ("", "")
        self.hash_batches.append(len(todo))
        return out

    async def _hash_msg(self, msg: Any, size: int = 0) -> Tuple[str, str]:
        """هشِ چندتکه‌ایِ یک پیامِ ازپیش‌گرفته‌شده (هستهٔ مشترکِ hash_file/hash_batch)."""
        try:
            doc = getattr(msg, "document", None)
            size = int(size or 0) or int(getattr(getattr(msg, "file", None), "size", 0) or 0) \
                or int(getattr(doc, "size", 0) or 0)
            if size <= 0:
                return "", ""
            h = hashlib.sha256()
            h.update(str(size).encode())
            got: List[str] = []
            for off, ln in chunk_plan(size, CHUNK):
                buf = await self._download_chunk(msg, off, ln)
                if not buf:
                    return "", ""
                h.update(str(off).encode())
                h.update(buf)
                got.append("%d+%d" % (off, len(buf)))
                if self.chunk_delay:
                    await asyncio.sleep(float(self.chunk_delay))
            return h.hexdigest()[:32], ",".join(got)
        except Exception as e:
            log.debug("_hash_msg خطا: %s", e)
            return "", ""

    async def _download_chunk(self, msg: Any, offset: int, length: int) -> bytes:
        media = getattr(msg, "media", None) or msg
        buf = bytearray()
        async for part in self.client.iter_download(media, offset=int(offset), limit=int(length),
                                                   request_size=int(length), chunk_size=int(length)):
            buf += part
            if len(buf) >= length:
                break
        return bytes(buf[:length])

    async def forward(self, to_chat: int, tg_id: int, msg_ids: Sequence[int]) -> bool:
        """فوروارد با **حسابِ کاربری** (فال‌بکِ دوم وقتی ربات اجازه ندارد)."""
        try:
            ent = await self.client.get_input_entity(tg_id)
            await self.client.forward_messages(int(to_chat), list(msg_ids), ent)
            self.forwarded.append({"to": int(to_chat), "from": int(tg_id), "ids": [int(x) for x in msg_ids]})
            return True
        except Exception as e:
            log.info("فورواردِ کاربری ناموفق: %s", e)
            return False


def chunk_plan(size: int, chunk: int = CHUNK) -> List[Tuple[int, int]]:
    """تکه‌های دانلود: سر + میانه + دُم (offset/limit مضربِ ۴۰۹۶)."""
    size = int(size or 0)
    if size <= 0:
        return []
    if size <= chunk:
        return [(0, size)]
    def down(x: int) -> int:
        return max(0, (int(x) // 4096) * 4096)
    plan: List[Tuple[int, int]] = []
    offs = [0, down(max(0, size // 2 - chunk // 2)), down(max(0, size - chunk))]
    for off in offs:
        ln = min(chunk, size - off)
        ln = int(ln) if ln < chunk else int(chunk)
        if ln <= 0:
            continue
        if all(off != o for o, _ in plan):
            plan.append((off, ln))
    return plan


_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def norm_digits(s: Any) -> str:
    """ارقامِ فارسی/عربی ⇒ لاتین («۲۸۷۳۴» ⇒ «28734»)."""
    return str(s or "").translate(_DIGIT_MAP)


def norm_phone(s: Any) -> str:
    """شماره را به شکلِ «+ارقام» درمی‌آورد (هم برای تایپ، هم برای دکمهٔ تماس).

    «۰۰۹۸۹۱۲…» (پیشوندِ بین‌المللیِ رایج) و ارقامِ فارسی هم پذیرفته می‌شوند.
    """
    digits = re.sub(r"[^\d]", "", norm_digits(s))
    if digits.startswith("00"):
        digits = digits[2:]
    return ("+" + digits) if digits else ""


_PHONE_RE = re.compile(r"^\+?\d{6,15}$")


def looks_like_phone(s: str) -> bool:
    return bool(_PHONE_RE.match(str(s or "").strip().replace(" ", "")))
