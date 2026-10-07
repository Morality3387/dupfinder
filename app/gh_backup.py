"""🗄 پشتیبانِ گیتهاب — «منبعِ یکتا» برای هش‌ها، کانال‌ها و تنظیمات (DK-17).

خواستهٔ کاربر: «برای محکم‌کاری بکاپ در گیتهاب آپلود شود؛ در قسمتِ سورس یک پوشهٔ `backup`
باشد؛ هر دیپلوی از آن بخواند و برای نوشتن هم در همان اکانتِ اصلی آپدیت کند — تا بعد از هر
دیپلوی لازم نباشد کانال‌ها و تنظیمات را دوباره وارد کنم.»

پس این ماژول:
  ① یک «عکسِ کامل» از دیتابیس می‌سازد (همان `app/backup.export_snapshot`: کانال‌ها +
     فایل‌ها + هش‌ها + تنظیماتِ تشخیص — بدونِ رمزها).
  ② آن را **رمزنگاری** می‌کند و در مخزنِ گیتهاب می‌گذارد:
        `backup/latest.bin`     → قفل‌شده (salt | iv | ciphertext | tag)
        `backup/manifest.json`  → فقط شمارش‌ها/زمان/اثرِ انگشت — بی‌اطلاعاتِ حساس
  ③ هنگامِ بالا آمدنِ ربات، اگر دیتابیس **خالی** باشد، همان فایل را برمی‌گردانَد
     (کانال‌ها + هش‌ها + تنظیمات) تا روی اکانتِ تازه اسکنِ از صفر لازم نباشد.

چرا رمزنگاری واجب است: مخزنِ `baddarksss/dupfinder` **عمومی** است؛ نامِ فایل‌ها،
کپشن‌ها و نامِ کانال‌ها نباید عمومی شوند. کلید فقط در متغیرهای محیطیِ سرور
(`BACKUP_KEY`) یا دیتابیسِ همان ربات می‌مانَد و هرگز داخلِ فایل یا مخزن نمی‌رود.

رمزنگاری: PBKDF2-HMAC-SHA256 (۲۰۰٬۰۰۰ تکرار) ⇒ کلیدِ ۶۴ بایتی (۳۲ رمز + ۳۲ امضا) ⇒
AES-256-CBC (`pyaes` — همان بستهٔ وابستهٔ Telethon، بدونِ نصبِ چیزی) + HMAC-SHA256
با ساختارِ **encrypt-then-MAC**: اول امضا بررسی می‌شود، بعد رمزگشایی می‌شود.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import posixpath
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from . import backup as B

log = logging.getLogger("dup.ghbackup")

API = "https://api.github.com"
MAGIC = b"DUPB1"                    # شناسهٔ نسخهٔ قالبِ فایلِ قفل‌شده
PBKDF2_ITERS = 200_000
SALT_LEN, IV_LEN, TAG_LEN = 16, 16, 32
MANIFEST = "manifest.json"
DATA_FILE = "latest.bin"
MAX_PULL_BYTES = 45 * 1024 * 1024   # سقفِ خواندن (بزرگ‌تر از این یعنی چیزی اشتباه است)


class GitHubError(Exception):
    """خطای گفتگو با گیتهاب (توکن/مخزن/شبکه)."""


# ────────────────────────────── رمزنگاری (استاندارد، بی‌بستهٔ بیرونی) ──────────────────────────────

def derive_key(password: str, salt: bytes, *, iters: int = PBKDF2_ITERS) -> bytes:
    """کلیدِ ۶۴ بایتی از رمزِ کاربر (۳۲ بایت اول = رمزِ AES، ۳۲ بایتِ دوم = کلیدِ امضا)."""
    if not password:
        raise ValueError("رمزِ پشتیبان خالی است.")
    return hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, int(iters), dklen=64)


def _aes_cbc(data: bytes, key: bytes, iv: bytes, *, encrypt: bool) -> bytes:
    """AES-256-CBC با padding استانداردِ PKCS#7 (با `pyaes` که همراهِ Telethon می‌آید)."""
    import pyaes
    block, chunk = 16, 16                   # pyaes هر بلوک را جدا می‌گیرد (۱۶ بایت)
    if encrypt:
        pad = block - (len(data) % block)
        data = bytes(data) + bytes([pad]) * pad
    mode = pyaes.AESModeOfOperationCBC(key, iv=iv)
    fn = mode.encrypt if encrypt else mode.decrypt
    out = b"".join(fn(bytes(data[i:i + chunk])) for i in range(0, len(data), chunk))
    if not encrypt:
        pad = out[-1] if out else 0
        if pad < 1 or pad > block or out[-pad:] != bytes([pad]) * pad:
            raise ValueError("داده‌های رمزگشایی‌شده معتبر نیستند.")
        out = out[:-pad]
    return out


def seal(data: bytes, password: str, *, iters: int = PBKDF2_ITERS) -> bytes:
    """قفل‌کردنِ داده + امضا (encrypt-then-MAC)."""
    salt, iv = os.urandom(SALT_LEN), os.urandom(IV_LEN)
    key = derive_key(password, salt, iters=iters)
    body = MAGIC + salt + iv + _aes_cbc(bytes(data), key[:32], iv, encrypt=True)
    tag = hmac.new(key[32:], body, hashlib.sha256).digest()
    return body + tag


def unseal(blob: bytes, password: str) -> bytes:
    """بازکردنِ فایلِ قفل‌شده — اول امضا، بعد رمزگشایی (اگر رمز غلط باشد، خطای روشن می‌دهیم)."""
    blob = bytes(blob or b"")
    if len(blob) < len(MAGIC) + SALT_LEN + IV_LEN + TAG_LEN or not blob.startswith(MAGIC):
        raise ValueError("این فایل، پشتیبانِ قفل‌شدهٔ آی‌دی‌فایندر نیست.")
    body, tag = blob[:-TAG_LEN], blob[-TAG_LEN:]
    salt = blob[len(MAGIC):len(MAGIC) + SALT_LEN]
    iv = blob[len(MAGIC) + SALT_LEN:len(MAGIC) + SALT_LEN + IV_LEN]
    # تعدادِ تکرارِ PBKDF2 را از خودِ فایل نمی‌خوانیم (ثابت است) تا ساده و قابلِ پیش‌بینی بمانَد.
    key = derive_key(password, salt)
    if not hmac.compare_digest(hmac.new(key[32:], body, hashlib.sha256).digest(), tag):
        raise ValueError("رمزِ پشتیبان درست نیست (یا فایل تغییر کرده است).")
    return _aes_cbc(body[len(MAGIC) + SALT_LEN + IV_LEN:], key[:32], iv, encrypt=False)


# ────────────────────────────── کلاینتِ مخزنِ گیتهاب ──────────────────────────────

class GitHub:
    """پوششِ نازکِ Contents API — فقط خواندن/نوشتنِ دو فایلِ پشتیبان.

    برای تست، `transport` تزریق می‌شود: `transport(method, path, payload, accept) -> dict|None`.
    """

    def __init__(self, token: str = "", repo: str = "", path: str = "backup", *,
                 api: str = API, timeout: float = 60.0,
                 transport: Optional[Callable[..., Any]] = None):
        self.token = str(token or "").strip()
        self.repo = str(repo or "").strip().strip("/")
        self.path = str(path or "backup").strip("/") or "backup"
        self.api = api
        self.timeout = float(timeout)
        self.transport = transport

    # ── کمکی‌ها ──
    def configured(self) -> bool:
        return bool(self.token and self.repo and "/" in self.repo)

    def url(self, name: str) -> str:
        return "/repos/%s/contents/%s" % (self.repo, posixpath.join(self.path, str(name)))

    def describe(self) -> str:
        return "%s/%s" % (self.repo or "—", self.path)

    def _req(self, method: str, path: str, payload: Optional[dict] = None, *,
             accept: str = "application/vnd.github+json") -> Any:
        if self.transport is not None:
            return self.transport(method, path, payload, accept)
        if not self.configured():
            raise GitHubError("تنظیماتِ گیتهاب کامل نیست (توکن/مخزن).")
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.api + path, data=data, method=method,
            headers={"Authorization": "Bearer " + self.token, "User-Agent": "dupfinder-backup",
                     "Accept": accept, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                ctype = str(r.headers.get("Content-Type") or "")
                if "json" in ctype:
                    return json.loads(raw.decode() or "{}")
                return {"raw": raw}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            body = e.read()[:300].decode(errors="replace")
            if e.code in (401, 403):
                raise GitHubError("دسترسیِ گیتهاب رد شد (%s) — توکن را بررسی کنید: %s" % (e.code, body))
            raise GitHubError("گیتهاب %s %s → %s: %s" % (method, path, e.code, body))

    # ── خواندن/نوشتن ──
    def meta(self, name: str) -> Optional[dict]:
        return self._req("GET", self.url(name))

    def get(self, name: str) -> Optional[bytes]:
        """محتوای خامِ فایل (None اگر نبود)."""
        r = self._req("GET", self.url(name), accept="application/vnd.github.raw")
        if r is None:
            return None
        if isinstance(r, dict) and isinstance(r.get("raw"), (bytes, bytearray)):
            return bytes(r["raw"])
        content = ""
        if isinstance(r, dict):
            content = str(r.get("content") or "")
        return base64.b64decode(content) if content else None

    def get_json(self, name: str) -> Optional[dict]:
        raw = self.get(name)
        if not raw:
            return None
        try:
            val = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        return val if isinstance(val, dict) else None

    def put(self, name: str, data: bytes, message: str) -> str:
        """نوشتنِ فایل (اگر بود، همان را به‌روز می‌کند). خروجی: sha جدید."""
        payload: Dict[str, Any] = {"message": str(message)[:300],
                                   "content": base64.b64encode(bytes(data)).decode()}
        old = self.meta(name)
        if isinstance(old, dict) and old.get("sha"):
            payload["sha"] = old["sha"]
        r = self._req("PUT", self.url(name), payload)
        return str(((r or {}).get("content") or {}).get("sha") or "")

    def put_json(self, name: str, obj: dict, message: str) -> str:
        return self.put(name, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"), message)


# ────────────────────────────── عملیاتِ پشتیبان ──────────────────────────────

def build_manifest(db: Any, rep: Dict[str, Any], blob: bytes, *, rev: str = "") -> Dict[str, Any]:
    """اطلاعاتِ عمومیِ فایلِ پشتیبان — بی‌هیچ نام/شناسه‌ای (برای مخزنِ عمومی بی‌خطر)."""
    return {"format": "dupfinder-gh-backup", "version": 1, "rev": str(rev or ""),
            "exported_at": int(time.time()), "encrypted": True,
            "crypto": "PBKDF2-SHA256/%dk + AES-256-CBC + HMAC-SHA256" % (PBKDF2_ITERS // 1000),
            "channels": int(rep.get("channels") or 0), "files": int(rep.get("files") or 0),
            "hashed": int(rep.get("hashed") or 0), "settings": int(rep.get("settings") or 0),
            "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
            "unique_key": list(B.FILES_UNIQUE_KEY)}


async def push(db: Any, gh: GitHub, password: str, *, rev: str = "", message: str = "") -> Dict[str, Any]:
    """ساخت + قفل + آپلودِ «عکسِ کامل» روی گیتهاب."""
    data, rep, _name = await asyncio.to_thread(B.export_snapshot, db, rev)
    blob = await asyncio.to_thread(seal, data, password)      # رمزنگاری سنگین است ⇒ بیرون از حلقهٔ رویداد
    manifest = build_manifest(db, rep, blob, rev=rev)
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    msg = message or ("backup: %s · %d کانال · %s فایل · %s هش" % (
        stamp, manifest["channels"], "{:,}".format(manifest["files"]), "{:,}".format(manifest["hashed"])))
    await asyncio.to_thread(gh.put, DATA_FILE, blob, msg)
    await asyncio.to_thread(gh.put_json, MANIFEST, manifest, msg)
    log.info("🗄 پشتیبان روی گیتهاب رفت: %s (%s بایت)", gh.describe(), manifest["bytes"])
    return {"repo": gh.repo, "path": gh.path, "bytes": len(blob), "manifest": manifest, "report": rep}


async def fetch_manifest(gh: GitHub) -> Optional[Dict[str, Any]]:
    """manifest بدونِ نیاز به رمز (برای نمایشِ وضعیت)."""
    return await asyncio.to_thread(gh.get_json, MANIFEST)


async def pull(db: Any, gh: GitHub, password: str, *, with_settings: bool = True) -> Dict[str, Any]:
    """خواندن + بازکردن + نشاندنِ پشتیبانِ گیتهاب در دیتابیسِ همین ربات."""
    blob = await asyncio.to_thread(gh.get, DATA_FILE)
    if not blob:
        raise GitHubError("روی گیتهاب فایلِ پشتیبان پیدا نشد (%s)." % gh.describe())
    if len(blob) > MAX_PULL_BYTES:
        raise GitHubError("فایلِ پشتیبان غیرمنتظره بزرگ است (%s بایت)." % len(blob))
    manifest = await asyncio.to_thread(gh.get_json, MANIFEST) or {}
    want = str(manifest.get("sha256") or "")
    got = hashlib.sha256(blob).hexdigest()
    if want and want != got:
        raise GitHubError("فایلِ پشتیبان روی گیتهاب ناقص/تغییرکرده است (اثرِ انگشت نمی‌خواند).")
    try:
        data = await asyncio.to_thread(unseal, blob, password)
    except ValueError as e:
        raise GitHubError(str(e))
    payload = B.load(data)
    plan = B.import_plan(db, payload, auto_create=True)   # کانالِ نبوده هم ساخته می‌شود
    st = await asyncio.to_thread(B.apply_import, db, plan, with_settings=bool(with_settings))
    log.info("🗄 پشتیبانِ گیتهاب بازگردانده شد: %s", st)
    return {"stats": st, "manifest": manifest, "payload_scope": payload.get("scope"),
            "settings": int(st.get("settings") or 0)}


def human_manifest(m: Optional[Dict[str, Any]]) -> str:
    """یک خطِ خوانا از manifest برای نمایش در ربات."""
    if not m:
        return "—"
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(m.get("exported_at") or 0))) \
        if m.get("exported_at") else "—"
    return "%s · %d کانال · %s فایل · %s هش · %s" % (
        when, int(m.get("channels") or 0), "{:,}".format(int(m.get("files") or 0)),
        "{:,}".format(int(m.get("hashed") or 0)), B.human_bytes(int(m.get("bytes") or 0)))
