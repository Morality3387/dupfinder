"""موتورِ اسکن: ایندکسِ تاریخچهٔ کامل کانال ← نامزدها ← هش‌گذاری جزئی ← گروه‌بندی.

ویژگی‌ها: نوارِ درصدِ زنده، توقف/کنسل، ادامه از نقطهٔ قطع، و **فقط خواندن**
(هیچ پیام یا فایلی در تلگرام پاک/ویرایش نمی‌شود).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from . import matching as M
from . import similarity as S

log = logging.getLogger("dup.scan")


def _with_norms(files: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """اطمینان از پر بودنِ `name_norm`/`caption_norm`.

    نامزدسازیِ «نام» و «کپشن» روی همین دو فیلد کار می‌کند؛ اگر برای رکوردی خالی
    باشند (مثلاً رکوردِ قدیمیِ دیتابیس یا مسیرِ دیگری که فایل را ذخیره کرده)،
    سیگنالِ نام بی‌صدا خاموش می‌شود ⇒ این‌جا دوباره محاسبه می‌شوند.
    """
    out: List[Dict[str, Any]] = []
    for f in files or []:
        d = dict(f)
        if not str(d.get("name_norm") or "").strip():
            d["name_norm"] = S.name_norm(d.get("file_name"))
        if not str(d.get("caption_norm") or "").strip():
            d["caption_norm"] = S.caption_norm(d.get("caption"))
        out.append(d)
    return out


@dataclass
class Progress:
    phase: str = "index"          # index|hash|match|done|canceled|error
    seen: int = 0                 # پیام‌های پیمایش‌شده
    total: int = 0                # برآوردِ کلِ پیام‌ها (۰ = نامعلوم)
    files: int = 0                # فایل‌های ویدیوییِ پیداشده
    hashed: int = 0               # فایل‌های هش‌شده
    hash_total: int = 0
    pct: float = 0.0
    note: str = ""
    new_since: int = 0
    last_msg_id: int = 0
    top_id: int = 0               # آخرین شناسهٔ پیامِ کانال (از probe) — برای تخمینِ درصد

    def as_dict(self) -> Dict[str, Any]:
        return {"phase": self.phase, "seen": self.seen, "total": self.total, "files": self.files,
                "hashed": self.hashed, "hash_total": self.hash_total, "pct": round(self.pct, 2),
                "note": self.note}


@dataclass
class ScanResult:
    scan_id: int = 0
    channel_id: int = 0
    status: str = "done"
    files: int = 0                # کلِ فایل‌های ایندکس‌شدهٔ کانال
    found: int = 0                # فایل‌هایی که در همین اسکن دیده شدند
    hashed: int = 0
    groups: int = 0
    error: str = ""
    canceled: bool = False
    seconds: float = 0.0
    notes: List[str] = field(default_factory=list)   # هشدارهای صادقانه (مثلِ سقفِ نامزدها)


class Canceled(Exception):
    pass


class Scanner:
    def __init__(self, db, user, cfg: Callable[[], Dict[str, Any]], *,
                 on_progress: Optional[Callable[[Progress], Awaitable[None]]] = None):
        self.db = db
        self.user = user
        self.cfg = cfg                    # تابعی که دیکشنریِ تنظیماتِ فعلی را می‌دهد
        self.on_progress = on_progress
        self._cancel = asyncio.Event()
        self.progress = Progress()
        self.scan_id = 0
        self._last_emit = 0.0
        self.running = False

    # ── کنترل ──
    def cancel(self) -> None:
        self._cancel.set()

    @property
    def canceled(self) -> bool:
        return self._cancel.is_set()

    def _check(self) -> None:
        if self._cancel.is_set():
            raise Canceled()

    async def _emit(self, *, force: bool = False) -> None:
        now = time.monotonic()
        # ⚠️ صفر یعنی «هر بار بفرست» — پس نباید با `or` به پیش‌فرض برگردد (باگِ واقعی).
        try:
            interval = float(self.cfg().get("progress_interval", 2.0))
        except (TypeError, ValueError):
            interval = 2.0
        if interval < 0:
            interval = 0.0
        if not force and (now - self._last_emit) < interval:
            return
        self._last_emit = now
        if self.on_progress:
            try:
                await self.on_progress(self.progress)
            except Exception as e:  # نمایشِ پیشرفت نباید اسکن را بشکند
                log.debug("on_progress خطا: %s", e)

    # ── اجرا ──
    async def run(self, channel: Dict[str, Any], *, full: bool = False) -> ScanResult:
        cfg = self.cfg()
        t0 = time.time()
        self.running = True
        self._cancel = asyncio.Event()
        cid = int(channel["id"])
        tg_id = int(channel["tg_id"])
        # اگر کاربر نوعِ فایل‌های اسکن را عوض کند (مثلاً video ⇒ all)، ایندکسِ قبلی ناقص است
        # و ادامه‌دادن از `max_msg_id` باعث می‌شود سند/عکس‌های **قدیمی‌تر** هرگز ایندکس نشوند.
        # پس تغییرِ `media_kinds` خودکار به «اسکنِ کامل» ارتقا داده می‌شود (باگِ گزارش‌شده).
        kinds_now = str(cfg.get("media_kinds") or "video")
        kinds_prev = str(self.db.kv_get("scan_media_kinds:%d" % cid) or "")
        kinds_changed = bool(kinds_prev) and kinds_prev != kinds_now
        eff_full = bool(full) or kinds_changed
        from_db = self.db.max_msg_id(cid)
        since = 0 if eff_full else from_db
        # ۲ نکتهٔ مهمِ اسکنِ ادامه‌ای (باگِ گزارش‌شده):
        #   ① پستِ قدیمی می‌تواند **ویرایش** شود و فایلش عوض شود. اگر فقط از `max_msg_id` به بعد
        #      بخوانیم، آن پیام هرگز بازخوانی نمی‌شود و رکورد/هشِ کهنه در دیتابیس می‌ماند.
        #      پس نوکِ کانال به اندازهٔ `incr_tail` پیام عقب‌تر بازخوانی می‌شود (پیش‌فرض ۲۰۰).
        #   ② فایل‌هایی که محتوایشان عوض شده (db.upsert_files) در `self.rehash_ids` جمع می‌شوند
        #      تا حتی اگر در نامزدهای معمول نبودند، هششان از نو حساب شود.
        tail = 0 if eff_full else max(0, int(cfg.get("incr_tail") or 0))
        # ⚠️ در اسکنِ کامل همیشه از صفر خوانده می‌شود؛ `from_db - tail` فقط برای «ادامه‌ای» است
        # (باگِ واقعیِ کشف‌شده در تستِ DK-8: در اسکنِ کاملِ دوم روی همان کانال، `iter_from`
        #  با `from_db` برابر می‌شد و هیچ پیامی بازخوانی نمی‌شد!)
        iter_from = 0 if eff_full else max(0, from_db - tail)
        self.rehash_ids = set()
        params = {"full": eff_full, "auto_full_kinds": kinds_changed,
                  "hash_mode": cfg.get("hash_mode"), "hash_scope": cfg.get("hash_scope"),
                  "media_kinds": kinds_now,
                  "since": since, "iter_from": iter_from, "incr_tail": tail,
                  "th_name_ratio": cfg.get("th_name_ratio"),
                  "th_name_jaccard": cfg.get("th_name_jaccard"), "th_cap_ratio": cfg.get("th_cap_ratio"),
                  "th_cap_jaccard": cfg.get("th_cap_jaccard"), "size_tol_pct": cfg.get("size_tol_pct"),
                  "dur_tol_s": cfg.get("dur_tol_s")}
        self.scan_id = self.db.create_scan(cid, params, min_id=since)
        # 🧹 DK-15 (خواستهٔ کاربر): «با اسکنِ جدید، تاریخچهٔ اسکنِ قبلی پاک شود — انگار از نو
        # اسکن زده». نتایج/گروه‌ها/وضعیتِ فورواردِ اسکن‌های قبلیِ همین کانال پاک می‌شوند تا
        # لیست و تیک‌های «رسیدگی» و «قبلاً فرستاده شده» از صفر شروع شوند. ایندکس و هشِ
        # فایل‌ها دست‌نخورده می‌ماند (اسکنِ تازه سریع است) و در تلگرام هیچ‌چیزی لمس نمی‌شود.
        self._reset_prev = self.db.reset_results(cid, keep_scan_id=int(self.scan_id or 0))
        self.progress = Progress(phase="index", new_since=since, pct=0.0)
        res = ScanResult(scan_id=self.scan_id, channel_id=cid)
        if self._reset_prev.get("groups"):
            res.notes.append(
                "🧹 نتایجِ اسکنِ قبلی پاک شد (%s گروه) — این اسکن از صفر شمرده می‌شود."
                % self._reset_prev.get("groups"))
        if kinds_changed:
            res.notes.append(
                "♻️ نوعِ فایل‌های اسکن از «%s» به «%s» عوض شده بود ⇒ این اسکن **خودکار کامل** شد "
                "تا فایل‌های قدیمیِ نوعِ تازه هم ایندکس شوند." % (kinds_prev, kinds_now))
        seen_ids: set = set()             # شناسهٔ پیام‌هایی که در این اسکن دیده شدند (برای پاک‌سازی)
        istats: Dict[str, Any] = {}       # آمارِ مسیرِ پیمایش (visited/completed) از user.iter_videos
        buf: List[Dict[str, Any]] = []      # بافرِ درجِ فایل‌ها (بیرونِ try: در کنسل/خطا هم ذخیره می‌شود)
        seen = 0                            # بیرونِ try تا در کنسل/خطا هم در دسترس باشند
        found = 0
        try:
            # ── فازِ ۱: ایندکس ──
            total, last_id = await self._probe(tg_id)
            self.progress.total = total
            self.progress.top_id = last_id
            self.progress.last_msg_id = int(iter_from or 0)
            await self._emit(force=True)
            async for row in self.user.iter_videos(tg_id, min_id=iter_from, media_kinds=kinds_now,
                                                  wait_time=float(cfg.get("scan_wait_time", 0.35) or 0),
                                                  stats=istats):
                self._check()
                row = dict(row)
                row["channel_id"] = cid
                row["name_norm"] = S.name_norm(row.get("file_name"))
                row["caption_norm"] = S.caption_norm(row.get("caption"))
                buf.append(row)
                seen_ids.add(int(row.get("msg_id") or 0))
                found += 1
                seen += 1
                if len(buf) >= 200:
                    self.rehash_ids.update(self.db.upsert_files(buf).get("changed") or [])
                    buf = []
                self.progress.seen = seen
                self.progress.files = found
                self.progress.note = "شناسهٔ پیام: #%d از #%d" % (
                    self.progress.last_msg_id, self.progress.top_id) if self.progress.top_id else ""
                self.progress.last_msg_id = max(self.progress.last_msg_id, int(row.get("msg_id") or 0))
                self.progress.pct = self._pct_index()
                self.db.update_scan(self.scan_id, seen_msgs=seen, files_found=found,
                                    phase="index", max_id=self.progress.last_msg_id)
                await self._emit()
            if buf:
                self.rehash_ids.update(self.db.upsert_files(buf).get("changed") or [])
            # فایل‌هایی که کاربر در تلگرام پاک کرده، نباید در ایندکس و گروه‌ها بمانند.
            # ملاکِ «اسکنِ سالم» جداست از «فایل پیدا شد» (باگِ گزارش‌شده): کافی است پیمایشِ
            # کامل بدونِ خطا/کنسل تمام شده باشد — اگر کانال هیچ ویدیویی نداشته باشد،
            # `seen_ids` خالی است و **همهٔ** رکوردهای آن نوع باید پاک شوند.
            visited = int(istats.get("visited") or 0)
            scan_ok = bool(eff_full and istats.get("completed") and not self._cancel.is_set())
            empty_ok = False
            if scan_ok and not seen_ids and visited == 0:
                # حتی یک پیام هم پیمایش نشد: شاید کانال واقعاً خالی است، شاید دسترسی قطع شده.
                # فقط وقتی پاک می‌کنیم که تلگرام صریحاً «هیچ پیامی نیست» را تأیید کند.
                try:
                    empty_ok = bool(await self.user.channel_is_empty(tg_id))
                except Exception as e:
                    log.info("بررسیِ خالی‌بودنِ کانال ناموفق: %s", e)
                    empty_ok = False
                if not empty_ok:
                    res.notes.append(
                        "ℹ️ هیچ فایلی در این اسکن خوانده نشد و «خالی‌بودنِ کانال» هم تأیید نشد، پس "
                        "رکوردهای قبلی دست‌نخورده ماندند (برای اطمینان دوباره اسکن کنید).")
            # کافی است پیمایش سالم انجام شده باشد: اگر حتی یک پیام هم پیمایش شد (visited>0)،
            # `seen_ids` معتبر است — حتی اگر خالی باشد (مثلاً همهٔ ویدیوها حذف شده و فقط سند مانده).
            # و اگر هیچ پیامی پیمایش نشد، فقط با تأییدِ «کانال خالی است» پاک می‌کنیم.
            if scan_ok and (visited > 0 or empty_ok) and bool(cfg.get("prune_missing", True)):
                from .user_client import _kind_ok
                pr = self.db.prune_missing_files(cid, seen_ids, media_kinds=kinds_now, kinds_check=_kind_ok)
                if pr.get("files"):
                    res.notes.append(
                        "🗑 %s رکورد که دیگر در کانال نیست از ایندکس پاک شد%s (فقط از دیتابیسِ ربات — "
                        "هیچ فایلی در تلگرام حذف نمی‌شود)."
                        % (int(pr["files"]),
                           " (کانال هیچ فایلِ واجدِ‌شرطی نداشت)" if not seen_ids else ""))
                    log.info("پاک‌سازیِ رکوردهای حذف‌شده: %s", pr)
            self.db.kv_set("scan_media_kinds:%d" % cid, kinds_now)   # برای تشخیصِ تغییر در اسکنِ بعدی
            self.progress.pct = 70.0
            self.progress.phase = "match"
            self.progress.note = "تحلیلِ نامزدها…"
            await self._emit(force=True)

            # ── فازِ ۲: هش‌گذاریِ نامزدها ──
            files = _with_norms(self.db.files_of_channel(cid))
            res.files = len(files)
            res.found = found
            if str(cfg.get("hash_mode") or "candidates") != "off" and files:
                hstats: Dict[str, int] = {}
                ids = M.hash_candidate_ids(files, cfg, stats=hstats)
                if self.rehash_ids:
                    # فایل‌هایی که همین حالا محتوایشان عوض شده (پستِ ویرایش‌شده) — هشِ نو لازم دارند
                    fresh = {int(f["id"]) for f in files if int(f["id"]) in set(self.rehash_ids)}
                    if fresh:
                        ids = sorted(set(int(x) for x in ids) | fresh)
                        res.notes.append(
                            "♻️ %s فایل در کانال تغییر کرده بود (پستِ ویرایش/جابه‌جاشده) ⇒ هششان از نو "
                            "حساب شد تا نتیجهٔ تکراری بر پایهٔ دادهٔ کهنه نباشد." % len(fresh))
                if hstats.get("hash_capped"):
                    res.notes.append(
                        "⚠️ %s فایل به‌خاطرِ سقفِ هش (۴۰۰۰) هش نشد؛ حالتِ هش را روی «candidates» "
                        "بگذارید یا کانال را تکه‌تکه اسکن کنید." % int(hstats["hash_capped"]))
                if hstats.get("name_bucket_skipped"):
                    res.notes.append(
                        "ℹ️ %s فایل نامِ خیلی عمومی داشتند (سبدِ نامِ بزرگ)؛ برای آن‌ها فقط سیگنال‌های "
                        "حجم/زمان و هش بررسی شد." % int(hstats["name_bucket_skipped"]))
                self.progress.hash_total = len(ids)
                if ids:
                    self.progress.note = "هش‌گذاریِ نامزدها (دانلودِ جزئی)…"
                    await self._emit(force=True)
                    await self._hash_ids(cfg, tg_id, files, ids)
                    files = _with_norms(self.db.files_of_channel(cid))
                    res.hashed = self.progress.hashed
                    if getattr(self, "hash_upgraded", 0):
                        res.notes.append(
                            "🔼 %s فایل با دامنهٔ قدیمی (نمونه‌ای) هش شده بود و حالا با دامنهٔ «full» "
                            "از نو هش شد (چون تنظیمِ دامنهٔ هش عوض شده است)." % self.hash_upgraded)
                    if getattr(self, "hash_stuck_sample", 0):
                        res.notes.append(
                            "ℹ️ %s فایل بزرگ‌تر از سقفِ «hash_full_max_mb» است ⇒ با هشِ نمونه‌ای ماند؛ "
                            "برای هشِ کاملِ آن‌ها سقف را بالا ببرید." % self.hash_stuck_sample)
            self._check()

            # ── فازِ ۳: گروه‌بندیِ نهایی ──
            self.progress.phase = "match"
            self.progress.pct = max(self.progress.pct, 96.0)
            self.progress.note = "گروه‌بندیِ نهایی…"
            await self._emit(force=True)
            stats: Dict[str, int] = {}
            clusters = M.find_clusters(files, cfg, stats=stats)
            self.db.replace_groups(self.scan_id, cid, clusters)
            res.groups = len(clusters)
            dropped = int(stats.get("size_pairs_dropped", 0)) + int(stats.get("duration_pairs_dropped", 0))
            if dropped:
                res.notes.append(
                    "⚠️ حدوداً %s جفت‌کاندید به‌خاطرِ سقفِ «size_pair_cap»/«duration_pair_cap» بررسی "
                    "نشدند (کانالِ حجیم با حجم/زمانِ خیلی مشابه). هم‌حجم‌های دقیق و هم‌زمان‌های دقیق "
                    "همیشه بررسی می‌شوند، ولی اگر نگرانید این عدد را در تنظیمات بالا ببرید." % dropped)
                log.warning("نامزدسازی: %s جفت بررسی‌نشده (stats=%s)", dropped, stats)
            if eff_full and int(res.found or 0) == 0:
                # صفر فایل در اسکنِ کامل معمولاً یعنی «دسترسی» یا «نوعِ فایل»، نه «ترک بودنِ کانال»
                res.notes.append(
                    "ℹ️ در این اسکنِ کامل هیچ فایلی با نوعِ «%s» پیدا نشد. اگر مطمئنید کانال فایل دارد: "
                    "① نوعِ فایلِ اسکن را در «⚙️ تنظیمات» بررسی کنید، ② مطمئن شوید حسابِ کاربری "
                    "<b>عضوِ کانال</b> است (ادمین‌بودن لازم نیست؛ برای کانالِ عمومی عضویت هم لازم نیست) "
                    "و ③ دکمهٔ «🩺 دسترسی‌های لازم» را در کارتِ کانال بزنید." % kinds_now)
            res.status = "done"
            res.seconds = round(time.time() - t0, 1)
            self.progress.phase = "done"
            self.progress.pct = 100.0
            self.progress.note = "تمام شد"
            # `seen_msgs` را از روی شناسه‌ها تخمین می‌زنیم (تعدادِ واقعیِ پیام‌های پیمایش‌شده)
            seen_msgs = max(int(self.progress.seen),
                            int(self.progress.last_msg_id) - int(self.progress.new_since or 0)) \
                if self.progress.top_id else int(self.progress.seen)
            self.db.update_scan(self.scan_id, status="done", phase="done", finished_at=int(time.time()),
                                total_msgs=total, seen_msgs=seen_msgs, files_found=res.found,
                                hashed=res.hashed, groups_found=res.groups)
            self.db.set_channel_scan(cid, self.scan_id, int(time.time()))
            self.db.log_action("scan_done", "channel=%s files=%d groups=%d in=%ss" % (cid, res.files, res.groups, res.seconds))
            await self._emit(force=True)
        except Canceled:
            if buf:                              # 🩹 آنچه خوانده شده بود حفظ می‌شود
                try:
                    self.db.add_files(buf)
                    buf = []
                except Exception:
                    pass
            res.canceled = True
            res.status = "canceled"
            res.seconds = round(time.time() - t0, 1)
            res.found = found
            res.files = self.db.count_files(cid)
            try:  # نتایجِ جزئی هم بی‌فایده نباشد
                clusters = M.find_clusters(_with_norms(self.db.files_of_channel(cid)), cfg)
                self.db.replace_groups(self.scan_id, cid, clusters)
                res.groups = len(clusters)
            except Exception:
                pass
            self.progress.phase = "canceled"
            self.progress.note = "کنسل شد"
            self.db.update_scan(self.scan_id, status="canceled", phase="canceled", finished_at=int(time.time()),
                                files_found=res.found, groups_found=res.groups)
            self.db.set_channel_scan(cid, self.scan_id, int(time.time()))
            self.db.log_action("scan_cancel", "channel=%s files=%d" % (cid, res.files))
            await self._emit(force=True)
        except Exception as e:
            if buf:
                try:
                    self.db.add_files(buf)
                    buf = []
                except Exception:
                    pass
            res.status = "error"
            res.error = str(e)[:400]
            res.seconds = round(time.time() - t0, 1)
            self.progress.phase = "error"
            self.progress.note = res.error
            log.exception("اسکنِ کانال %s شکست خورد", cid)
            self.db.update_scan(self.scan_id, status="error", phase="error", finished_at=int(time.time()),
                                error=res.error)
            await self._emit(force=True)
        finally:
            self.running = False
        return res

    def _pct_index(self) -> float:
        """درصدِ فازِ ایندکس (۰..۶۸) — بر پایهٔ **شمارهٔ پیام**، نه تعدادِ ویدیوها.

        باگِ قبلی: درصد از `seen` (تعدادِ ویدیوهای پیداشده) تقسیم بر `total`
        (تعدادِ کلِ پیام‌های کانال) حساب می‌شد؛ در کانالی با ۱۰۰هزار پیام و ۱۰هزار
        ویدیو، نوار در پایانِ اسکن هم حدودِ ۷٪ می‌ماند. حالا مبنای درصد موقعیتِ
        شناسهٔ پیام در بازهٔ [شروع … آخرین پیامِ کانال] است (یکنوا و بی‌خواب).
        """
        p = self.progress
        top = int(p.top_id or 0)
        base = int(p.new_since or 0)
        cur = int(p.last_msg_id or 0)
        if top > base and cur > base:
            return min(68.0, 68.0 * float(cur - base) / float(top - base))
        if p.total and p.total > 0:
            # ناچاریم تخمین بزنیم (شناسهٔ آخرِ کانال معلوم نیست) ⇒ محافظه‌کارانه و نصفِ سهم
            return min(68.0, 34.0 * float(p.seen) / float(p.total))
        return 1.0

    async def _probe(self, tg_id: int) -> Tuple[int, int]:
        """(تعدادِ کلِ پیام‌های کانال، آخرین شناسهٔ پیام) — برای نوارِ درصد."""
        total = 0
        last = 0
        try:
            msgs = await self.user.probe(tg_id)
            total = int(msgs.get("total") or 0)
            last = int(msgs.get("last_id") or 0)
        except Exception as e:
            log.debug("probe خطا: %s", e)
        return total, last

    async def _hash_ids(self, cfg: Dict[str, Any], tg_id: int, files: Sequence[Dict[str, Any]],
                        ids: Sequence[int]) -> None:
        by_id = {int(f["id"]): f for f in files}
        todo: List[Tuple[int, int]] = []      # (msg_id, size)
        # باگِ گزارش‌شده: قبلاً فقط «بودنِ content_hash» بررسی می‌شد، پس عوض‌کردنِ
        # `hash_scope` از sample به full هیچ‌وقت اثر نمی‌کرد و فایل‌ها با هشِ نمونه‌ای می‌ماندند.
        # حالا **دامنهٔ ذخیره‌شده** با دامنهٔ لازم مقایسه می‌شود.
        need_full = str(cfg.get("hash_scope") or "sample").lower() == "full"
        full_max = max(0, int(cfg.get("hash_full_max_mb") or 0)) * 1024 * 1024
        self.hash_upgraded = 0
        self.hash_stuck_sample = 0
        for fid in ids:
            f = by_id.get(int(fid))
            if not f:
                continue
            size = int(f.get("size") or 0)
            have = str(f.get("content_hash") or "")
            sc = str(f.get("hash_scope") or "").strip().lower()
            if have:
                if not (need_full and sc != "full"):
                    self.progress.hashed += 1
                    continue                       # دامنه همان است ⇒ هشِ موجود معتبر است
                if full_max and size > full_max:
                    self.hash_stuck_sample += 1    # بزرگ‌تر از سقفِ هشِ کامل ⇒ تلاشِ دوباره بی‌فایده
                    self.progress.hashed += 1
                    continue
                self.hash_upgraded += 1            # دامنه عوض شده ⇒ باید از نو هش شود
            todo.append((int(f["msg_id"]), size))
        batch = 100
        for i in range(0, len(todo), batch):
            self._check()
            chunk = todo[i:i + batch]
            try:
                out = await self.user.hash_batch(
                    tg_id, chunk,
                    scope=str(cfg.get("hash_scope") or "sample"),
                    full_max_bytes=int(cfg.get("hash_full_max_mb") or 0) * 1024 * 1024)
            except Exception as e:
                log.info("hash_batch خطا: %s", e)
                out = {}
            for msg_id, size in chunk:
                res = out.get(int(msg_id)) or ("", "")
                h, scope = (res if isinstance(res, tuple) else (res or "", ""))
                self.progress.hashed += 1
                if h:
                    for f in files:
                        if int(f.get("msg_id") or 0) == int(msg_id) and int(f["id"]) in by_id:
                            self.db.set_hash(int(f["id"]), str(h), str(scope))
                            break
            self.progress.pct = 70.0 + (25.0 * min(
                1.0, float(self.progress.hashed) / max(1, self.progress.hash_total or len(todo))))
            self.progress.note = "هش‌گذاری: %d از %d" % (self.progress.hashed, len(todo))
            await self._emit()
        self.progress.pct = 95.0
        await self._emit(force=True)
