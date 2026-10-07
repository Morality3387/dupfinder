"""کلاینتِ Bot API — HTTP خامِ سبک با تلاشِ دوباره، احترام به 429 و فاصله‌گذاریِ ارسال."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

log = logging.getLogger("dup.tgapi")

API = "https://api.telegram.org"


def esc(s: Any) -> str:
    """فرارِ HTML برای parse_mode=HTML (نامِ فایل‌ها می‌توانند هر چیزی باشند)."""
    return html.escape(str(s if s is not None else ""), quote=False)


class TgError(Exception):
    def __init__(self, method: str, code: int, desc: str, retry_after: float = 0.0):
        super().__init__("%s failed: %s (%s)" % (method, desc, code))
        self.method, self.code, self.desc, self.retry_after = method, code, desc, retry_after


class TgApi:
    """پوششِ نازکِ Bot API. `Transport` قابلِ تعویض است تا در تست‌ها fake شود."""

    def __init__(self, token: str, *, timeout: float = 90.0, min_send_interval: float = 0.34,
                 session: Optional[aiohttp.ClientSession] = None):
        self.token = token
        self.timeout = timeout
        self.min_send_interval = min_send_interval
        self._session = session
        self._own_session = session is None
        self._chat_last: Dict[int, float] = {}
        self._lock = asyncio.Lock()
        self.calls = 0

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
            self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._session and self._own_session and not self._session.closed:
            await self._session.close()

    async def _throttle(self, chat_id: Optional[int]) -> None:
        """فاصلهٔ کمینهٔ ارسال به هر چت (ضدِ 429)."""
        if chat_id is None or self.min_send_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            last = self._chat_last.get(int(chat_id), 0.0)
            wait = self.min_send_interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._chat_last[int(chat_id)] = time.monotonic()

    async def call(self, method: str, *, _throttle_chat: Optional[int] = None, **params: Any) -> Any:
        url = "%s/bot%s/%s" % (API, self.token, method)
        payload = {k: v for k, v in params.items() if v is not None}
        if _throttle_chat is not None:
            await self._throttle(_throttle_chat)
        for attempt in range(5):
            self.calls += 1
            try:
                s = await self.session()
                async with s.post(url, json=payload) as r:
                    data = await r.json(content_type=None)
                if isinstance(data, dict) and data.get("ok"):
                    return data.get("result")
                code = int((data or {}).get("error_code") or r.status or 0)
                desc = str((data or {}).get("description") or "")
                if code == 429:
                    ra = float(((data or {}).get("parameters") or {}).get("retry_after") or 2)
                    log.warning("429 روی %s ⇒ %ss صبر", method, ra)
                    await asyncio.sleep(min(30.0, ra + 0.5))
                    continue
                if code in (500, 502, 503, 504, 520) and attempt < 4:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise TgError(method, code, desc)
            except TgError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("خطای شبکه در %s (%s) — تلاشِ %d", method, e, attempt + 1)
                await asyncio.sleep(1.0 + attempt)
        raise TgError(method, 0, "unreachable after retries")

    # ── متدهای پرکاربرد ──
    async def get_me(self) -> Dict[str, Any]:
        return await self.call("getMe")

    async def get_updates(self, offset: int = 0, timeout: int = 25) -> List[Dict[str, Any]]:
        res = await self.call("getUpdates", offset=offset, timeout=timeout,
                              allowed_updates=["message", "callback_query", "channel_post"])
        return res or []

    async def send_message(self, chat_id: int, text: str, *, kb: Optional[dict] = None,
                           parse_mode: str = "HTML", preview: bool = False,
                           silent: bool = False, reply_to: Optional[int] = None,
                           kb_extra: Optional[dict] = None) -> Dict[str, Any]:
        """kb_extra برای ReplyKeyboard (مثلِ دکمهٔ شماره یا remove_keyboard) است."""
        markup = kb if kb else kb_extra
        return await self.call("sendMessage", _throttle_chat=chat_id, chat_id=chat_id, text=text,
                               parse_mode=parse_mode, reply_markup=json.dumps(markup) if markup else None,
                               disable_web_page_preview=None if preview else True,
                               disable_notification=True if silent else None,
                               reply_to_message_id=reply_to)

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, *,
                                kb: Optional[dict] = None, parse_mode: str = "HTML") -> Any:
        try:
            return await self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                                   parse_mode=parse_mode, reply_markup=json.dumps(kb) if kb else None,
                                   disable_web_page_preview=True)
        except TgError as e:
            if "not modified" in (e.desc or "").lower():
                return None
            raise

    async def delete_message(self, chat_id: int, message_id: int) -> Any:
        """⚠️ فقط برای پیام‌های خودِ ربات استفاده می‌شود (هیچ‌گاه روی پستِ کانال)."""
        try:
            return await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)
        except TgError:
            return None

    async def answer_callback(self, cq_id: str, text: str = "", *, alert: bool = False) -> Any:
        try:
            return await self.call("answerCallbackQuery", callback_query_id=cq_id, text=text[:190],
                                   show_alert=True if alert else None)
        except TgError:
            return None

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> Any:
        try:
            return await self.call("sendChatAction", chat_id=chat_id, action=action)
        except TgError:
            return None

    async def forward_message(self, to_chat: int, from_chat: int, message_id: int) -> Dict[str, Any]:
        return await self.call("forwardMessage", _throttle_chat=to_chat, chat_id=to_chat,
                               from_chat_id=from_chat, message_id=message_id)

    async def send_media_group(self, to_chat: int, from_chat: int, message_ids: List[int]) -> List[Dict[str, Any]]:
        """📎 DK-15: ارسالِ چند پیامِ کانال **یک‌جا** (آلبوم) تا فایل‌های هر گروه دوباره‌چرخی نباشند.

        تلگرام این متد را **فقط** با `media` می‌پذیرد؛ `media` همان پیام‌های کانالِ مبدأ است
        (`{"type":"video","media":"<message_id>","chat_id":…}`) ⇒ فایل دوباره آپلود نمی‌شود و
        مصرف پهنای‌باند ندارد. اگر تلگرام رد کند، مسیرِ عادی (تک‌تک) ادامه پیدا می‌کند.
        """
        ids = [int(x) for x in (message_ids or [])][:10]          # سقفِ آلبوم = ۱۰ قلم
        if len(ids) < 2:
            return []
        media = [{"type": "video", "media": str(mid), "chat_id": int(from_chat)} for mid in ids]
        res = await self.call("sendMediaGroup", _throttle_chat=to_chat, chat_id=to_chat,
                              media=media)
        return list(res or []) if isinstance(res, list) else []

    async def copy_message(self, to_chat: int, from_chat: int, message_id: int) -> Dict[str, Any]:
        return await self.call("copyMessage", _throttle_chat=to_chat, chat_id=to_chat,
                               from_chat_id=from_chat, message_id=message_id)

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, *,
                                        kb: Optional[Dict[str, Any]] = None) -> Any:
        """✏️ DK-15: فقط دکمه‌های یک پیام عوض می‌شود (مثلاً بعد از «🗑 این گروه را نفرست»)."""
        return await self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                               reply_markup=kb or {"inline_keyboard": []})

    async def get_chat(self, chat_id: Any) -> Dict[str, Any]:
        return await self.call("getChat", chat_id=chat_id)

    async def get_chat_member(self, chat_id: Any, user_id: int) -> Dict[str, Any]:
        return await self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    async def get_chat_member_count(self, chat_id: Any) -> int:
        try:
            return int(await self.call("getChatMemberCount", chat_id=chat_id) or 0)
        except TgError:
            return 0

    async def set_my_commands(self, commands: List[Dict[str, str]]) -> Any:
        return await self.call("setMyCommands", commands=commands)

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        return await self.call("getFile", file_id=file_id)
