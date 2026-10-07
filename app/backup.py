"""💾 پشتیبان‌گیری و بازگرداندنِ «ایندکس + هش»ها — برای جابه‌جاییِ ربات به اکانتِ تازه.

خواستهٔ کاربر: «ریلوی ۳۰ روزه است و بعد باید ربات را روی اکانتِ جدید ببرم؛ می‌شود
اطلاعاتِ هش را جایی آپلود کند؟ مثلاً برای هر کانال یک پوشه، تا با اکانتِ جدید از صفر
اسکن نکند و هش‌ها را از آنجا بخواند.»

پس: هر کانال یک فایلِ فشردهٔ جدا می‌گیرد
(`dupfinder-hashes_<نام>_<tg_id>.json.gz`) که شاملِ **همهٔ** اطلاعاتِ گران‌قیمت است:

  • ردیف‌های `files` همان کانال — با `content_hash` و `hash_scope` (کلِ چیزی که با
    دانلودِ سنگین به‌دست آمده)
  • اطلاعاتِ فایل‌ها برای مقایسه: نام/کپشن/حجم/زمان (بدونشان نمی‌شود گروه‌ها را دوباره ساخت)
  • تنظیماتِ تشخیص (به‌شرطِ `include_settings`) تا رباتِ تازه با همان دقت کار کند

چه چیزی **داخل** نمی‌رود: توکنِ ربات، `session_string`، `api_hash`، `owner_id` و
آیدی‌های ادمین — این‌ها رازند و در فایلِ پشتیبان نمی‌آیند.

دو راهِ برگرداندن:
  ① از داخلِ خودِ ربات (دکمهٔ «♻️ بازگرداندن») — فایل را روی همان سرور می‌خواند.
  ② اگر فایل را **فوروارد** نگه داشته‌اید و دیگر روی سرور نیست، ربات با
     `forwardMessage` در چتِ خودتان یک کپی از فایل می‌گیرد و همان را می‌خواند.

نکتهٔ فنی: نحوهٔ **تشخیصِ رکوردِ یکسان** در نسخه‌های آیندهٔ ربات نباید تغییر کند؛
`FILES_UNIQUE_KEY` همان `(channel_id, msg_id)` است (نسخهٔ ۱٫۰).
"""
from __future__ import annotations

import gzip
import io
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

BACKUP_FORMAT = "dupfinder-index"
BACKUP_VERSION = 1
FILES_UNIQUE_KEY: Tuple[str, ...] = ("channel_id", "msg_id")

# ستون‌های `files` که در پشتیبان می‌آیند (id عمداً نیست؛ هنگامِ بازگرداندن نو ساخته می‌شود)
FILE_FIELDS: Tuple[str, ...] = (
    "channel_id", "msg_id", "grouped_id", "date", "doc_id", "file_unique_id", "file_identify",
    "file_name", "name_norm", "caption", "caption_norm", "size", "duration", "mime",
    "width", "height", "has_video", "protected", "content_hash", "hash_scope",
)

# کلیدهایی که هرگز نباید از فایلِ پشتیبان روی رباتِ تازه نوشته شوند
SECRET_SETTING_KEYS = {
    "bot_token", "session_string", "api_hash", "api_id", "owner_id", "admins", "admin_ids",
    "webhook", "webhook_secret", "proxy", "mtproto_proxy",
}

SETTING_PREFIX = "setting:"


def _file_fields(db: Any = None) -> Tuple[str, ...]:
    """فهرستِ ستون‌هایی که در پشتیبان می‌آید — هم‌راستا با شِمای همین نسخه."""
    base = tuple(getattr(db, "FILE_COLS", ()) or FILE_FIELDS)
    return tuple(list(base) + [c for c in ("content_hash", "hash_scope") if c not in base])


def _short(value: Any, limit: int = 120000) -> Any:
    """متنِ بلند (کپشنِ چندصدخطی) را کوتاه می‌کند تا فایلِ پشتیبان سبک بماند."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit]
    return value


def safe_name(text: str, limit: int = 36) -> str:
    """نامِ فایلِ امن (بدونِ نویسه‌های غیرمجازِ نامِ فایل)."""
    base = re.sub(r"[^0-9A-Za-z\u0600-\u06FF._-]+", "_", str(text or "").strip()).strip("_")
    return (base or "channel")[:limit]


def dump(payload: Dict[str, Any]) -> bytes:
    """فشرده‌سازیِ JSON — تارِ پشتیبان در حافظه ساخته می‌شود (هیچ فایلی روی دیسک لازم نیست)."""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as gz:
        gz.write(raw)
    return buf.getvalue()


def load(data: bytes) -> Dict[str, Any]:
    """بازکردنِ تارِ پشتیبان (هم `json` خام و هم `json.gz` پذیرفته می‌شود)."""
    if not data:
        raise ValueError("فایلِ پشتیبان خالی است.")
    blob = data
    if blob[:2] == b"\x1f\x8b":                      # gzip
        blob = gzip.decompress(blob)
    try:
        payload = json.loads(blob.decode("utf-8"))
    except Exception as e:
        raise ValueError("فایلِ پشتیبان خوانده نشد (%s)." % e)
    if not isinstance(payload, dict):
        raise ValueError("ساختارِ فایلِ پشتیبان درست نیست.")
    fmt, ver = payload.get("format"), int(payload.get("version") or 0)
    if fmt != BACKUP_FORMAT:
        raise ValueError("این فایل، پشتیبانِ «آی‌دی‌فایندر» نیست.")
    if ver > BACKUP_VERSION:
        raise ValueError("این پشتیبان با نسخهٔ جدیدتری ساخته شده (v%s)." % ver)
    return payload


def channel_meta(db: Any, channel_id: int) -> Dict[str, Any]:
    """اطلاعاتِ سه‌تاییِ هویتِ کانال (برای پیدا کردنش در رباتِ تازه)."""
    c = db.get_channel(channel_id) or {}
    return {"id": int(channel_id), "tg_id": int(c.get("tg_id") or 0),
            "username": str(c.get("username") or ""), "title": str(c.get("title") or ""),
            "kind": str(c.get("kind") or "channel")}


def export_channel(db: Any, channel_id: int, *, rev: str = "",
                   include_settings: bool = False) -> Tuple[bytes, Dict[str, Any], str]:
    """ساختِ پشتیبانِ یک کانال. خروجی: (بایت‌ها، گزارش، نامِ پیشنهادیِ فایل)."""
    meta = channel_meta(db, channel_id)
    files: List[Dict[str, Any]] = []
    hashed = hashed_full = hashed_sample = 0
    for f in db.files_of_channel(int(channel_id)):
        row: Dict[str, Any] = {}
        for k in _file_fields(db):
            row[k] = _short(f.get(k))
        row["channel_id"] = int(channel_id)
        files.append(row)
        if str(f.get("content_hash") or ""):
            hashed += 1
            if str(f.get("hash_scope") or "").lower() == "full":
                hashed_full += 1
            else:
                hashed_sample += 1
    payload: Dict[str, Any] = {
        "format": BACKUP_FORMAT, "version": BACKUP_VERSION, "rev": str(rev or ""),
        "exported_at": int(time.time()), "channel": meta, "count": len(files),
        "hashed": hashed, "hashed_full": hashed_full, "hashed_sample": hashed_sample,
        "files": files,
    }
    settings: Dict[str, str] = {}
    if include_settings:
        for k, v in (db.kv_all() or {}).items():
            if not str(k).startswith(SETTING_PREFIX):
                continue
            if str(k)[len(SETTING_PREFIX):].lower() in SECRET_SETTING_KEYS:
                continue
            settings[str(k)] = str(v)
        payload["settings"] = settings

    data = dump(payload)
    name = "dupfinder-hashes_%s_%s.json.gz" % (safe_name(meta.get("title")), int(channel_id))
    report = {"channel": meta, "count": len(files), "hashed": hashed,
              "hashed_full": hashed_full, "hashed_sample": hashed_sample,
              "bytes": len(data), "settings": len(settings)}
    return data, report, name


# ────────────────────────────── پیدا کردنِ کانالِ مقصد ──────────────────────────────

def _channels(db: Any) -> List[Dict[str, Any]]:
    """فهرستِ کانال‌های همین ربات (با هر نامی که در `db` باشد)."""
    fn = getattr(db, "list_channels", None)
    if callable(fn):
        try:
            return [dict(r) for r in (fn() or [])]
        except Exception:
            pass
    try:
        return [dict(r) for r in db._all("SELECT * FROM channels ORDER BY id")]
    except Exception:
        return []


def _norm_user(text: Any) -> str:
    return str(text or "").strip().lstrip("@").lower()


def search_channel(db: Any, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """کانالِ این ربات را با هویتِ ذخیره‌شده در پشتیبان پیدا می‌کند.

    ترتیبِ اطمینان: ① `tg_id` (قطعی — با جابه‌جاییِ اکانت هم ثابت است)
    ② یوزرنیم ③ نامِ کانال.
    """
    meta = meta or {}
    tg_id = int(meta.get("tg_id") or 0)
    if tg_id:
        by_tg = getattr(db, "get_channel_by_tg", None)
        c = by_tg(tg_id) if callable(by_tg) else None
        if not c:
            c = next((x for x in _channels(db) if int(x.get("tg_id") or 0) == tg_id), None)
        if c:
            return c
    uname = _norm_user(meta.get("username"))
    if uname:
        c = next((x for x in _channels(db) if _norm_user(x.get("username")) == uname), None)
        if c:
            return c
    title = str(meta.get("title") or "").strip().lower()
    if title:
        c = next((x for x in _channels(db) if str(x.get("title") or "").strip().lower() == title), None)
        if c:
            return c
    return None


# ────────────────────────────── ساختِ پشتیبان ──────────────────────────────

def export_settings(db: Any) -> Dict[str, str]:
    """تنظیماتِ تشخیص (بی‌راز) — تا رباتِ تازه با همان دقت کار کند."""
    out: Dict[str, str] = {}
    for k, v in (db.kv_all() or {}).items():
        key = str(k)
        if not key.startswith(SETTING_PREFIX):
            continue
        if key[len(SETTING_PREFIX):].lower() in SECRET_SETTING_KEYS:
            continue
        out[key] = str(v)
    return out


def export_snapshot(db: Any, rev: str = "") -> Tuple[bytes, Dict[str, Any], str]:
    """پشتیبانِ **همهٔ** کانال‌ها + تنظیمات در یک فایل (برای جابه‌جاییِ کاملِ اکانت)."""
    channels: List[Dict[str, Any]] = []
    for c in _channels(db):
        files: List[Dict[str, Any]] = []
        hashed = 0
        for f in db.files_of_channel(int(c["id"])):
            row: Dict[str, Any] = {}
            for k in _file_fields(db):
                row[k] = _short(f.get(k))
            row["channel_id"] = int(c["id"])
            files.append(row)
            if str(f.get("content_hash") or ""):
                hashed += 1
        channels.append({"channel": channel_meta(db, int(c["id"])), "count": len(files),
                         "hashed": hashed, "files": files})
    st = db.stats()
    payload: Dict[str, Any] = {
        "format": BACKUP_FORMAT, "version": BACKUP_VERSION, "rev": str(rev or ""),
        "exported_at": int(time.time()), "scope": "snapshot",
        "totals": {"channels": int(st.get("channels") or 0), "files": int(st.get("files") or 0),
                   "hashed": int(st.get("hashed") or 0), "groups": int(st.get("groups") or 0)},
        "settings": export_settings(db), "channels": channels,
    }
    data = dump(payload)
    name = "dupfinder-backup_%s.json.gz" % time.strftime("%Y%m%d-%H%M", time.localtime())
    report = {"channels": len(channels), "files": int(st.get("files") or 0),
              "hashed": int(st.get("hashed") or 0), "bytes": len(data),
              "settings": len(payload["settings"])}
    return data, report, name


def stats_of(payload: Dict[str, Any]) -> Dict[str, Any]:
    """خلاصهٔ خوانا از یک فایلِ پشتیبان (برای پیش‌نمایشِ قبل از بازگرداندن)."""
    if payload.get("scope") == "snapshot":
        t = payload.get("totals") or {}
        return {"scope": "snapshot", "channels": len(payload.get("channels") or []),
                "files": int(t.get("files") or 0), "hashed": int(t.get("hashed") or 0),
                "settings": len(payload.get("settings") or {}), "title": "همهٔ کانال‌ها",
                "tg_id": 0, "exported_at": int(payload.get("exported_at") or 0)}
    ch = payload.get("channel") or {}
    files = payload.get("files") or []
    hashed = sum(1 for f in files if str((f or {}).get("content_hash") or ""))
    return {"scope": "channel", "channels": 1, "files": len(files), "hashed": hashed,
            "settings": len(payload.get("settings") or {}), "title": str(ch.get("title") or ""),
            "tg_id": int(ch.get("tg_id") or 0), "exported_at": int(payload.get("exported_at") or 0)}


def human_bytes(n: Any) -> str:
    try:
        n = float(n or 0)
    except Exception:
        return "0"
    return ("%d B" % n) if n < 1024 else ("%.1f KB" % (n / 1024.0) if n < 1024 * 1024
                                          else "%.1f MB" % (n / 1048576.0))


# ────────────────────────────── بازگرداندن ──────────────────────────────

def import_plan(db: Any, payload: Dict[str, Any], *, fallback_channel_id: int = 0,
                auto_create: bool = False) -> Dict[str, Any]:
    """نقشهٔ بازگرداندن: هر بلوکِ کانال + کانالِ مقصدش روی این ربات + آمارِ پیش‌بینی‌شده."""
    items: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    if payload.get("scope") == "snapshot":
        blocks = payload.get("channels") or []
    else:
        blocks = [{"channel": payload.get("channel") or {}, "files": payload.get("files") or []}]
    for block in blocks:
        meta = dict(block.get("channel") or {})
        rows = [dict(r or {}) for r in (block.get("files") or []) if r]
        target = search_channel(db, meta)
        if not target and not payload.get("scope") == "snapshot" and fallback_channel_id:
            target = db.get_channel(int(fallback_channel_id))
        # اگر کانال روی این ربات نیست ولی شناسهٔ تلگرامش را داریم، خودمان می‌سازیمش.
        # این همان چیزی است که کاربر خواست: «بعدِ هر دیپلوی لازم نباشد کانال‌ها را دوباره وارد کنم».
        will_create = bool(auto_create and not target and int(meta.get("tg_id") or 0))
        item: Dict[str, Any] = {"meta": meta, "rows": rows, "target": target, "create": will_create,
                                "new": len(rows), "fills": 0, "updates": 0}
        if target:
            known = {(int(f.get("msg_id") or 0)): str(f.get("content_hash") or "")
                     for f in db.files_of_channel(int(target["id"]))}
            new = fills = upd = 0
            for r in rows:
                mid = int(r.get("msg_id") or 0)
                h = str(r.get("content_hash") or "")
                if mid not in known:
                    new += 1
                    fills += 1 if h else 0
                else:
                    if h and h != known[mid]:
                        fills += 1
                    upd += 1
            item.update({"new": new, "fills": fills, "updates": upd})
        elif will_create:
            item.update({"new": len(rows), "fills": sum(1 for r in rows if str(r.get("content_hash") or "")),
                         "updates": 0})
        else:
            missing.append(meta)
        items.append(item)
    return {"kind": "channel" if payload.get("scope") != "snapshot" else "snapshot",
            "items": items, "missing": missing, "settings": payload.get("settings") or {},
            "auto_create": bool(auto_create)}


def import_preview(plan: Dict[str, Any]) -> Dict[str, Any]:
    """جمعِ آمارِ نقشه — برای نشان‌دادن به کاربر قبل از تأیید."""
    rows = sum(len(i["rows"]) for i in plan.get("items") or [])
    return {"channels": len([i for i in plan.get("items") or [] if i.get("target")]),
            "rows": rows,
            "new": sum(int(i.get("new") or 0) for i in plan.get("items") or []),
            "fills": sum(int(i.get("fills") or 0) for i in plan.get("items") or []),
            "updates": sum(int(i.get("updates") or 0) for i in plan.get("items") or []),
            "settings": len(plan.get("settings") or {}),
            "missing": plan.get("missing") or []}


def apply_import(db: Any, plan: Dict[str, Any], *, with_settings: bool = False) -> Dict[str, Any]:
    """اجرای بازگرداندن: ردیف‌ها در می‌آیند و هش‌ها روی همان ردیف‌ها نوشته می‌شوند."""
    stat = {"channels": 0, "rows": 0, "new": 0, "hashes": 0, "settings": 0, "created": 0,
            "missing": len(plan.get("missing") or [])}
    for item in plan.get("items") or []:
        target = item.get("target")
        if not target and item.get("create"):
            meta = item.get("meta") or {}
            try:
                new_id = db.add_channel(int(meta.get("tg_id") or 0), title=str(meta.get("title") or ""),
                                        username=str(meta.get("username") or ""),
                                        kind=str(meta.get("kind") or "channel"))
                target = db.get_channel(int(new_id)) if new_id else None
                item["target"] = target
                if target:
                    stat["created"] += 1
            except Exception:
                target = None
        if not target:
            continue
        cid = int(target["id"])
        rows = [dict(r) for r in (item.get("rows") or [])]
        for r in rows:
            r["channel_id"] = cid
        for i in range(0, len(rows), 400):
            db.upsert_files(rows[i:i + 400])
        stat["rows"] += len(rows)
        stat["channels"] += 1
        # هش‌ها: روی ردیف‌های موجودِ همین کانال (تازه‌ساخته‌ها هم حالا موجودند)
        wanted = {int(r.get("msg_id") or 0): (str(r.get("content_hash") or ""), str(r.get("hash_scope") or "head+mid+tail"))
                  for r in rows if str(r.get("content_hash") or "")}
        if wanted:
            mids = sorted(wanted)
            ids: Dict[int, int] = {}
            for i in range(0, len(mids), 400):
                chunk = mids[i:i + 400]
                q = "SELECT id, msg_id FROM files WHERE channel_id=? AND msg_id IN (%s)" % ",".join("?" for _ in chunk)
                try:
                    for rec in db._all(q, tuple([cid] + chunk)):
                        ids[int(rec["msg_id"])] = int(rec["id"])
                except Exception:
                    for m in chunk:
                        f = db.get_file_by_msg(cid, m)
                        if f:
                            ids[m] = int(f["id"])
            for mid, (h, scope) in wanted.items():
                fid = ids.get(int(mid))
                if fid:
                    db.set_hash(int(fid), h, scope)
                    stat["hashes"] += 1
    if with_settings and plan.get("settings"):
        stat["settings"] = restore_settings(db, plan["settings"])
    return stat


def restore_settings(db: Any, settings: Dict[str, Any]) -> int:
    """نوشتنِ تنظیماتِ پشتیبان (فقط کلیدهای بی‌خطر)."""
    n = 0
    for k, v in (settings or {}).items():
        key = str(k)
        if not key.startswith(SETTING_PREFIX):
            continue
        if key[len(SETTING_PREFIX):].lower() in SECRET_SETTING_KEYS:
            continue
        db.kv_set(key, str(v))
        n += 1
    return n
