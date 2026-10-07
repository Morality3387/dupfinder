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

CHUNK = 131072        # ۱۲۸KB — تکهٔ «نمونه‌ای» (سر/میانه/ته)
FULL_CHUNK = 524288   # ۵۱۲KB — تکهٔ حالتِ «هشِ کامل» (مضربِ ۴۰۹۶)


def _is_video_kind(mime: str, kind: str) -> bool:
    """آیا این mime با حالتِ انتخابیِ کاربر می‌خواند؟ (`video` | `video+doc` | `all`)

    • `video`     ⇒ فقط ویدیو
    • `video+doc` ⇒ ویدیو + هر سندِ غیرِ عکس/صدا
    • `all`       ⇒ هر فایلِ همراه‌دار (سند، ویدیو، عکس…)
    """
    mime = str(mime or "").lower()
    kind = str(kind or "video")
    if kind == "all":
        return True
    if mime.startswith("video/"):
        return True
    if kind == "video+doc":
        return not mime.startswith(("image/", "audio/"))
    return False


def _kind_ok(row: Dict[str, Any], kind: str = "video") -> bool:
    """همان تصمیم روی **ردیفِ فایل** (عکس‌ها mime ندارند و با `has_video`/`has_photo` شناخته می‌شوند)."""
    kind = str(kind or "video")
    if kind == "all":
        return True
    mime = str(row.get("mime") or "").lower()
    if row.get("has_video") or mime.startswith("video/"):
        return True
    if kind == "video+doc":
        if mime.startswith(("image/", "audio/")):
            return False
        return bool(mime or row.get("file_name"))
    return False


class UserClient:
    """پوششِ Telethon. اگر وارد نشده باشد `ready=False` و ربات در حالتِ محدود کار می‌کند."""

    def __init__(self, api_id: int = 0, api_hash: str = "", session_string: str = "", *,
                 session_factory=None):
        # کشِ موجودیت/هشِ دسترسی — کانالِ خصوصی که فقط شناسه‌اش را داریم بدونِ این‌ها حل نمی‌شود
        self._ent_cache: Dict[int, Any] = {}
        self._peer_hash: Dict[int, int] = {}
        self._hints: Dict[int, Dict[str, Any]] = {}
        self.entity_misses: List[int] = []
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

    # ── حلِ موجودیت (کانالِ خصوصی) ──
    def set_hint(self, tg_id: int, *, username: str = "", access_hash: Optional[int] = None,
                 title: str = "") -> None:
        """اطلاعاتِ کمکیِ کانال را نگه می‌دارد تا بعداً (حتی پس از ری‌استارت) حل شود."""
        try:
            key = abs(int(tg_id))
        except Exception:
            return
        h = self._hints.setdefault(key, {})
        if username:
            h["username"] = str(username).lstrip("@")
        if title:
            h["title"] = str(title)
        if access_hash:
            self._peer_hash[key] = int(access_hash)
            h["access_hash"] = int(access_hash)

    @staticmethod
    def _channel_id_of(tg_id: Any) -> int:
        """`-1001234567890` ⇒ `1234567890` (شناسهٔ خامِ کانال برای InputPeerChannel)."""
        raw = str(tg_id).strip()
        n = abs(int(raw)) if raw.lstrip("-").isdigit() else 0
        txt = str(n)
        return int(txt[3:]) if txt.startswith("100") else n

    @staticmethod
    def _extract_hash(ent: Any) -> int:
        for obj in (ent, getattr(ent, "peer", None)):
            ah = getattr(obj, "access_hash", None)
            if ah:
                try:
                    return int(ah)
                except Exception:
                    pass
        return 0

    def _remember_entity(self, key: int, ent: Any) -> None:
        self._ent_cache[key] = ent
        ah = self._extract_hash(ent)
        if ah:
            self._peer_hash[key] = ah
            self._hints.setdefault(key, {})["access_hash"] = ah

    async def _entity(self, tg_id: Any) -> Any:
        """InputEntity با چند مسیرِ فال‌بک برای کانال‌های **خصوصی**.

        ترتیب: کشِ حافظه → کشِ سشن (`get_input_entity`) → `InputPeerChannel` با
        access_hashِ ذخیره‌شده → پیمایشِ گفتگوها (حساب عضوِ کانال است) → یوزرنیمِ کمکی.
        اگر هیچ‌کدام نشد، خطای روشنِ فارسی می‌دهد تا کاربر بداند چه کند.
        """
        raw = str(tg_id).strip()
        key = abs(int(raw)) if raw.lstrip("-").isdigit() else 0
        if key and key in self._ent_cache:
            return self._ent_cache[key]
        if not key:                                      # یوزرنیم/لینک ⇒ مسیرِ عادی
            return await self.client.get_input_entity(tg_id)

        errors: List[str] = []
        try:                                             # ۱) کشِ سشن
            ent = await self.client.get_input_entity(int(tg_id))
            self._remember_entity(key, ent)
            return ent
        except Exception as e:
            errors.append(type(e).__name__)

        ah = self._peer_hash.get(key) or int((self._hints.get(key) or {}).get("access_hash") or 0)
        if ah:                                           # ۲) access_hashِ ذخیره‌شده
            try:
                from telethon.tl.types import InputPeerChannel, PeerChannel
                cid_raw = self._channel_id_of(tg_id)
                try:
                    ent = await self.client.get_entity(PeerChannel(channel_id=cid_raw))
                    if ent is not None:
                        self._remember_entity(key, ent)
                        return ent
                except Exception as e:
                    errors.append(type(e).__name__)
                peer = InputPeerChannel(channel_id=cid_raw, access_hash=int(ah))
                self._ent_cache[key] = peer
                return peer
            except Exception as e:
                errors.append(type(e).__name__)

        try:                                             # ۳) فهرستِ گفتگوها
            # شناسه‌های ممکن: کاملِ منفی، بدونِ پیشوندِ ۱۰۰، و خودِ کلید
            wanted = {key, self._channel_id_of(tg_id), -key}
            async for d in self.client.iter_dialogs(limit=800):
                e = getattr(d, "entity", None)
                if e is not None and int(getattr(e, "id", 0) or 0) in wanted:
                    self._remember_entity(key, e)
                    log.info("کانال %s از فهرستِ گفتگوها حل شد", tg_id)
                    return e
        except Exception as e:
            errors.append(type(e).__name__)

        uname = str((self._hints.get(key) or {}).get("username") or "").lstrip("@")
        if uname:                                        # ۴) یوزرنیمِ کمکی (با کنترلِ هویت)
            try:
                ent = await self.client.get_entity("@" + uname)
                got = self._channel_id_of(getattr(ent, "id", 0) or 0) if ent is not None else 0
                want = self._channel_id_of(tg_id)
                if ent is None:
                    errors.append("username:khali")
                elif int(got) and int(got) != int(want):
                    # یوزرنیم عوض شده یا به کانالِ دیگری رسیده ⇒ **نباید** به‌جای این کانال
                    # برگردانده شود (باگِ گزارش‌شده: احتمالِ اسکنِ کانالِ اشتباه).
                    log.warning("یوزرنیمِ ذخیره‌شده (%s ⇒ %s) با کانالِ درخواستی (%s) یکی نیست؛ "
                                "نادیده گرفته شد.", uname, got, want)
                    errors.append("username:digar")
                else:
                    self._remember_entity(key, ent)
                    return ent
            except Exception as e:
                errors.append(type(e).__name__)

        self.entity_misses.append(int(key))
        log.warning("حلِ موجودیت ناموفق: tg_id=%s (تلاش‌ها: %s)", tg_id, ",".join(errors) or "-")
        extra = ("\nتوجه: یوزرنیمِ ذخیره‌شدهٔ این کانال حالا به کانالِ <b>دیگری</b> می‌رسد؛ "
                 "کانال را با لینکِ تازه‌اش دوباره به ربات بدهید." if "username:digar" in errors else "")
        raise ValueError(
            "کانال %s در سشن پیدا نشد. راهِ حل: ① کانال را با همین حساب یک‌بار باز کنید یا "
            "دوباره با لینک/یوزرنیم به ربات بدهید، ② یا حسابِ کاربری را وصل کنید (🔑) تا "
            "دسترسی‌ها تازه شود.%s" % (tg_id, extra))

    def peer_snapshot(self) -> Dict[str, Any]:
        """{tg_id: access_hash} — برای ذخیره در دیتابیس و استفاده پس از ری‌استارت."""
        return {str(k): int(v) for k, v in self._peer_hash.items() if v}

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
            ent = await self._entity(tg_id)
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
            ent = await self._entity(tg_id)
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
        """تبدیلِ پیامِ Telethon به ردیفِ فایل (هر سندِ همراه‌دار؛ فیلترِ نوع در `iter_videos`).

        ⚠️ قبلاً هر سندِ غیرِویدیویی همین‌جا رد می‌شد و در نتیجه حالت‌های
        `video+doc`/`all` هرگز به نتیجه نمی‌رسیدند (باگِ کشف‌شده در بازبینی).
        """
        try:
            doc = getattr(msg, "document", None)
            video = getattr(msg, "video", None)
            photo = getattr(msg, "photo", None)
            if doc is None and video is None and photo is None:
                return None
            mime = str(getattr(doc, "mime_type", "") or "")
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
            if not size and photo is not None:                     # عکس ⇒ حجمِ بزرگ‌ترین نسخه
                try:
                    size = max([int(getattr(t, "size", 0) or 0)
                                for t in (getattr(photo, "sizes", None) or [])] or [0])
                except Exception:
                    size = 0
            if size <= 0:
                return None                                        # ردیفِ بی‌حجم به کاری نمی‌آید
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
                "has_photo": 1 if photo is not None else 0,
                "protected": protected,
            }
        except Exception as e:  # pragma: no cover
            log.debug("msg_to_file خطا: %s", e)
            return None

    async def iter_videos(self, tg_id: int, *, min_id: int = 0, max_id: int = 0,
                          media_kinds: str = "video", wait_time: float = 0.3,
                          batch: int = 200, stats: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
        """پیمایشِ **کاملِ** تاریخچه (قدیم → جدید) و بازگرداندنِ فایل‌های ویدیویی.

        `stats` (اختیاری) آمارِ مسیر را نگه می‌دارد: `visited` تعدادِ پیام‌هایی که واقعاً
        پیمایش شد، `matched` تعدادِ فایل‌های بازگردانده‌شده و `completed=True` یعنی
        پیمایش بدونِ خطا تا انتهای تاریخچه رسید. اسکنر از همین برای تصمیمِ «پاک‌سازیِ
        رکوردهای حذف‌شده» استفاده می‌کند تا «کانالِ خالی» با «خطای گذرا» قاطی نشود.
        """
        if stats is not None:
            stats.clear()
            stats["visited"] = 0
            stats["matched"] = 0
            stats["completed"] = False
        ent = await self._entity(tg_id)
        if stats is not None:
            stats["entity_ok"] = True
        buf: List[Dict[str, Any]] = []
        kwargs: Dict[str, Any] = {"min_id": int(min_id or 0), "reverse": True, "wait_time": float(wait_time or 0)}
        if max_id:
            kwargs["max_id"] = int(max_id)
        async for msg in self.client.iter_messages(ent, **kwargs):
            if stats is not None:
                stats["visited"] = int(stats["visited"]) + 1
            if getattr(msg, "action", None) is not None and getattr(msg, "media", None) is None:
                continue
            row = self.msg_to_file(msg)
            if not row:
                continue
            if not _kind_ok(row, media_kinds):
                continue
            if stats is not None:
                stats["matched"] = int(stats["matched"]) + 1
            buf.append(row)
            if len(buf) >= batch:
                for r in buf:
                    yield r
                buf = []
        for r in buf:
            yield r
        if stats is not None:
            stats["completed"] = True

    async def channel_is_empty(self, tg_id: int) -> bool:
        """آیا کانال **واقعاً** هیچ پیامی ندارد؟ (برای پاک‌سازیِ ایمنِ ایندکسِ خالی)

        فقط وقتی `True` می‌دهد که تلگرام صریحاً بگوید پیامی نیست: هم `get_messages(limit=1)`
        خالی باشد و هم تعدادِ پیام‌های تاریخچه صفر. اگر هر خطا/ابهامی بود `False` برمی‌گردد
        تا هیچ‌وقت رکوردهای سالم به‌خاطرِ خطای گذرا پاک نشوند.
        """
        try:
            ent = await self._entity(tg_id)
        except Exception:
            return False
        try:
            msgs = await self.client.get_messages(ent, limit=1)
            if msgs:
                return False
        except Exception:
            return False
        try:
            info = await self.probe(tg_id)
            if int(info.get("total") or 0) > 0 or int(info.get("last_id") or 0) > 0:
                return False
        except Exception:
            return False
        return True

    async def probe(self, tg_id: int) -> Dict[str, Any]:
        """{total, last_id, title} — برای نوارِ درصدِ اسکن.

        `total` تعدادِ کلِ پیام‌های تاریخچهٔ کانال است (GetHistory.count) و
        `last_id` شناسهٔ تازه‌ترین پیام؛ هیچ‌کدام محتوایی دانلود نمی‌کنند.
        ⚠️ این متد را داخلِ حلقهٔ پیام‌ها صدا نزنید (یک‌بار قبل از اسکن کافی است).
        """
        out: Dict[str, Any] = {"total": 0, "last_id": 0, "title": ""}
        try:
            ent = await self._entity(tg_id)
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
                        scope: str = "sample", mode: str = "") -> Tuple[str, str]:
        """هشِ محتواییِ فایل. خروجی: (هش، دامنه)

        `scope="sample"` ⇒ فقط سر/میانه/ته (سریع، نشانهٔ قوی ولی نه قطعی).
        `scope="full"`   ⇒ **کلِ** فایل ⇒ «قطعاً همان فایل» (کند و پرمصرف).
        """
        if not scope or scope == "sample":
            scope = "full" if str(mode or "").lower() == "full" else "sample"
        try:
            ent = await self._entity(tg_id)
            msg = await self.client.get_messages(ent, ids=int(msg_id))
            if msg is None or getattr(msg, "media", None) is None:
                return "", ""
            return await self._hash_msg(msg, size, scope=scope)
        except Exception as e:
            log.debug("hash_file(%s/%s) خطا: %s", tg_id, msg_id, e)
            return "", ""

    async def hash_batch(self, tg_id: int, items: Sequence[Tuple[int, int]],
                         *, concurrency: int = 3, scope: str = "sample",
                         full_max_bytes: int = 0) -> Dict[int, Tuple[str, str]]:
        """هشِ گروهی: پیام‌ها را یک‌جا می‌گیرد و تکه‌های هر فایل را با محدودیتِ هم‌زمانی می‌خواند.

        ورودی: [(msg_id, size), …]   خروجی: {msg_id: (هش، دامنه)}
        هیچ فایلی دانلودِ کامل یا پاک نمی‌شود: در حالتِ نمونه‌ای فقط سر/میانه/دُم،
        و در حالتِ `scope="full"` کلِ فایل (فقط برای فایل‌های کوچک‌تر از
        `full_max_bytes`؛ بزرگ‌ترها خودکار به نمونه‌ای برمی‌گردند تا اسکن از پا نیفتد).
        """
        out: Dict[int, Tuple[str, str]] = {}
        todo = [(int(m), int(s or 0)) for m, s in (items or [])]
        if not todo:
            return out
        ent = await self._entity(tg_id)
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

        want_full = str(scope or "sample").lower() == "full"

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
                use = "full" if (want_full and (not full_max_bytes or size <= full_max_bytes)) else "sample"
                return await self._hash_msg(msg, size, scope=use)

        results = await asyncio.gather(*[work(m, s) for m, s in todo], return_exceptions=True)
        for (msg_id, _size), r in zip(todo, results):
            out[msg_id] = r if isinstance(r, tuple) else ("", "")
        self.hash_batches.append(len(todo))
        return out

    async def _hash_msg(self, msg: Any, size: int = 0, *, scope: str = "sample") -> Tuple[str, str]:
        """هشِ چندتکه‌ایِ یک پیامِ ازپیش‌گرفته‌شده (هستهٔ مشترکِ hash_file/hash_batch)."""
        try:
            doc = getattr(msg, "document", None)
            size = int(size or 0) or int(getattr(getattr(msg, "file", None), "size", 0) or 0) \
                or int(getattr(doc, "size", 0) or 0)
            if size <= 0:
                return "", ""
            is_full = str(scope or "sample").lower() == "full"
            h = hashlib.sha256()
            h.update(str(size).encode())
            if is_full:
                h.update(b"|full")            # دامنهٔ کامل، جدا از نمونه‌ای (تا قاطی نشوند)
            got: List[str] = []
            for off, ln in (full_chunk_plan(size, FULL_CHUNK) if is_full else chunk_plan(size, CHUNK)):
                buf = await self._download_chunk(msg, off, ln)
                if not buf:
                    return "", ""
                h.update(str(off).encode())
                h.update(buf)
                got.append("%d+%d" % (off, len(buf)))
                if self.chunk_delay and not is_full:
                    await asyncio.sleep(float(self.chunk_delay))
            return h.hexdigest()[:32], ("full" if is_full else ",".join(got))
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

    @staticmethod
    def _dest_id(to_chat: Any) -> Any:
        """مقصدِ فوروارد: شناسهٔ عددی یا `@username` (گروهِ چک ممکن است با یوزرنیم تعیین شود)."""
        if isinstance(to_chat, str) and not to_chat.strip().lstrip("-").isdigit():
            return to_chat.strip()
        return int(to_chat)

    async def forward_one(self, to_chat: int, tg_id: int, msg_id: int, *, group_key: Optional[str] = None) -> bool:
        """➡️ DK-15: فورواردِ **تک‌تک** یک پیام با حسابِ کاربری.

        خواستهٔ کاربر: «تک‌تک، خودش تا آخر» — پس ارسال‌ها یکی‌یکی و پشتِ‌سرهم می‌روند و
        `group_key` (مثلاً «g:12» یا «12:34») باعث می‌شود آلبومِ ناقصِ یک گروه با آلبومِ
        گروهِ دیگر قاطی نشود (تلگرام پیام‌هایی که پشتِ‌سرهم با فاصلهٔ کم بیایند را در یک
        آلبوم می‌چیند). اگر بشود، همان پیام‌ها به‌صورتِ **آلبوم** هم با `as_album=True`
        گروه‌بندی می‌شوند تا خروجی تمیز باشد.
        """
        try:
            ent = await self._entity(tg_id)
            await self.client.forward_messages(self._dest_id(to_chat), [int(msg_id)], ent, as_album=True)
            self.forwarded.append({"to": to_chat, "from": int(tg_id), "ids": [int(msg_id)]})
            return True
        except Exception as e:
            log.info("فورواردِ تک‌پیامیِ کاربری ناموفق (%s/%s): %s", to_chat, msg_id, e)
            return False

    async def forward(self, to_chat: int, tg_id: int, msg_ids: Sequence[int]) -> bool:
        """فوروارد با **حسابِ کاربری** (فال‌بکِ دوم وقتی ربات اجازه ندارد)."""
        try:
            ent = await self._entity(tg_id)
            await self.client.forward_messages(self._dest_id(to_chat), list(msg_ids), ent)
            self.forwarded.append({"to": to_chat, "from": int(tg_id), "ids": [int(x) for x in msg_ids]})
            return True
        except Exception as e:
            log.info("فورواردِ کاربری ناموفق: %s", e)
            return False


def full_chunk_plan(size: int, chunk: int = FULL_CHUNK) -> List[Tuple[int, int]]:
    """تکه‌های دانلودِ **کلِ** فایل (هشِ کامل) — آفست‌ها مضربِ ۴۰۹۶.

    هر تکه `chunk` بایت است و تکهٔ آخر به مضربِ ۴۰۹۶ گرد می‌شود (تلگرام بیشتر از
    حجمِ فایل برنمی‌گرداند، پس این گرد‌کردن بی‌خطر است).
    """
    size = int(size or 0)
    chunk = int(chunk or FULL_CHUNK)
    if size <= 0:
        return []
    plan: List[Tuple[int, int]] = []
    off = 0
    while off < size:
        ln = min(chunk, size - off)
        ln = min(chunk, ((int(ln) + 4095) // 4096) * 4096)
        if ln <= 0:
            break
        plan.append((off, ln))
        off += ln
    return plan


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
