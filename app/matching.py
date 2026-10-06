"""گروه‌بندیِ تکراری‌ها — اولویت: ۱) نام  ۲) کپشن  ۳) حجم+زمان، به‌علاوهٔ هشِ قطعی.

ورودی: فهرستِ ردیف‌های فایل (dict) · خروجی: خوشه‌های تکراری با دلیل و قدرت.
تابعِ اصلی `find_clusters()` است که دو بار اجرا می‌شود: یک بار با فراداده (سریع، برای
پیدا کردنِ نامزدها) و یک بار پس از هش‌گذاریِ نامزدها (برچسبِ «قطعاً همان فایل»).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import similarity as S

log = logging.getLogger("dup.match")

REASON_TEXT = {
    "hash": "هشِ کاملِ محتوا یکسان (بایت‌به‌بایت)",
    "telegram_file": "همان فایلِ تلگرام (شناسهٔ یکسان)",
    "hash_partial": "نمونهٔ محتوا یکسان (سر+میانه+ته)",
    "name": "نام مشابه",
    "caption": "کپشن مشابه",
    "size_time": "حجم و زمان یکسان",
}
# «قطعی» فقط وقتی است که **کلِ محتوا** (هشِ کامل) یا خودِ آپلودِ تلگرام یکی باشد.
# هشِ نمونه‌ای (سه تکه) سیگنالِ قوی است ولی «قطعی» نیست ⇒ درجهٔ ۳.
SIGNAL_STRENGTH = {"hash": 4, "telegram_file": 4, "hash_partial": 3, "size_time": 3, "name": 2, "caption": 1}
# ترتیبِ بررسی = ترتیبِ اولویتِ کارفرما (نام → کپشن → حجم/زمان) + سیگنال‌های قطعی
ORDER = ("hash", "telegram_file", "hash_partial", "name", "caption", "size_time")


class UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1
        return True

    def groups(self) -> Dict[int, List[int]]:
        out: Dict[int, List[int]] = defaultdict(list)
        for i in range(len(self.p)):
            out[self.find(i)].append(i)
        return out


def _rare_token_index(files: Sequence[Dict[str, Any]], field: str, *, max_df_ratio: float = 0.05,
                      max_df_abs: int = 400, skip_values: Optional[Set[str]] = None) -> Dict[str, List[int]]:
    """ایندکسِ معکوسِ توکن‌های «کمیاب» (توکنِ پرتکرار ⇒ نامزدِ بی‌فایده)."""
    idx: Dict[str, List[int]] = defaultdict(list)
    for i, f in enumerate(files):
        text = str(f.get(field) or "")
        if skip_values and text in skip_values:
            continue
        for tk in set(S.tokens(text)):
            if len(tk) < 2:
                continue
            idx[tk].append(i)
    n = max(1, len(files))
    cap = max(4, min(max_df_abs, int(n * max_df_ratio) + 2))
    return {tk: ids for tk, ids in idx.items() if len(ids) <= cap}


def _size_window_pairs(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *,
                       per_item_cap: Optional[int] = None,
                       stats: Optional[Dict[str, int]] = None) -> Iterable[Tuple[int, int]]:
    """جفت‌های نامزدِ «حجمِ نزدیک» با پنجرهٔ لغزان روی حجمِ مرتب — به‌جای O(n²).

    قاعده‌های مهم (فیکسِ ازقلم‌افتادنِ تکراری‌ها):
      • هم‌حجم‌های **دقیق** هیچ‌وقتِ‌وقت به‌خاطرِ سقف حذف نمی‌شوند (لنگرِ اصلیِ سیگنالِ
        حجم+زمان)؛ فقط زنجیره‌ای بررسی می‌شوند تا در کانال‌های حجیم کند نشود.
      • رسیدن به سقف باعثِ `break` نمی‌شود بلکه `continue` می‌کند، چون ممکن است
        بعد از آن هم فایلِ هم‌حجمِ دقیق در همین پنجره باشد.
      • جفت‌های حذف‌شده شمرده و در `stats` برگردانده می‌شوند.
    """
    cap = int(cfg.get("size_pair_cap") or per_item_cap or 240)
    cap = max(8, cap)
    exact_cap = max(cap, int(cfg.get("size_pair_exact_cap") or 400))
    order = sorted(range(len(files)), key=lambda i: int(files[i].get("size") or 0))
    tol_min = int(cfg.get("size_tol_min", 2048))
    tol_pct = float(cfg.get("size_tol_pct", 0.5))
    n = len(order)
    dropped = 0
    for a_pos in range(n):
        i = order[a_pos]
        si = int(files[i].get("size") or 0)
        if si <= 0:
            continue
        tol_i = max(tol_min, int(round(si * tol_pct / 100.0)))
        used = 0
        used_exact = 0
        for b_pos in range(a_pos + 1, n):
            j = order[b_pos]
            sj = int(files[j].get("size") or 0)
            if sj - si > tol_i:
                break
            if sj == si:                       # هم‌حجمِ بایت‌به‌بایت ⇒ همیشه نامزد
                if used_exact < exact_cap:
                    used_exact += 1
                    yield i, j
                else:
                    dropped += 1
                continue                       # سقفِ پنجرهٔ تقریبی روش اثر ندارد
            if abs(si - sj) <= tol_i:
                if used >= cap:
                    dropped += 1
                else:
                    used += 1
                    yield i, j
    if stats is not None and dropped:
        stats["size_pairs_dropped"] = int(stats.get("size_pairs_dropped", 0)) + dropped


def _duration_pairs(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *,
                    stats: Optional[Dict[str, int]] = None) -> Iterable[Tuple[int, int]]:
    """جفت‌های نامزدِ «زمانِ دقیقاً یکسان» — لنگرِ دومِ سیگنالِ حجم+زمان.

    با `size_time_require_one_exact=True`، وقتی حجم‌ها بایت‌به‌بایت برابر نیستند
    «زمان» است که تطبیق را ممکن می‌کند؛ پس این ایندکس مستقل از پنجرهٔ حجم است و
    تضمین می‌کند پر شدنِ سقفِ پنجره باعثِ ازقلم‌افتادنِ تکراری نشود.
    """
    min_dur = int(cfg.get("min_duration_s", 3) or 3)
    chain = max(8, int(cfg.get("duration_pair_cap") or 60))
    by_dur: Dict[int, List[int]] = defaultdict(list)
    for i, f in enumerate(files):
        d = int(f.get("duration") or 0)
        if d >= min_dur and int(f.get("size") or 0) > 0:
            by_dur[d].append(i)
    dropped = 0
    for _d, ids in by_dur.items():
        if len(ids) < 2:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, min(len(ids), a + 1 + chain)):
                yield ids[a], ids[b]
            if len(ids) - a - 1 > chain:
                dropped += len(ids) - a - 1 - chain
    if stats is not None and dropped:
        stats["duration_pairs_dropped"] = int(stats.get("duration_pairs_dropped", 0)) + dropped


def generic_values(files: Sequence[Dict[str, Any]], field: str, *, min_abs: int = 20,
                   min_ratio: float = 0.10) -> Set[str]:
    """مقدارهایی که «امضای کانال» هستند (روی بخشِ بزرگی از فایل‌ها تکرار شده‌اند).

    نمونهٔ واقعی: کپشنِ ثابتِ «کانالِ فیلم و سریال…» زیرِ همهٔ پست‌ها، یا نام‌های
    قالبیِ «video-1». اگر این‌ها را سیگنالِ تکرار حساب کنیم، **همه‌چیز** تکراری
    می‌شود. پس این مقدارها از تولیدِ نامزد و از تشخیص کنار گذاشته می‌شوند (ولی
    همچنان حجم/زمان و هش کار می‌کنند).
    """
    counts: Dict[str, int] = defaultdict(int)
    for f in files:
        v = str(f.get(field) or "")
        if v:
            counts[v] += 1
    n = max(1, len(files))
    thr = max(int(min_abs), int(n * float(min_ratio)))
    return {v for v, c in counts.items() if c >= thr}


def candidate_pairs(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *,
                    generic_captions: Optional[Set[str]] = None,
                    generic_names: Optional[Set[str]] = None,
                    stats: Optional[Dict[str, int]] = None) -> List[Tuple[int, int]]:
    """جفت‌های نامزدی که ارزشِ بررسی دارند (نامزدِ هر سه سیگنال).

    `stats` آمارِ نامزدسازی را نگه می‌دارد (مثلِ تعدادِ جفت‌های بررسی‌نشده).
    """
    pairs: List[Tuple[int, int]] = []
    seen: Set[Tuple[int, int]] = set()

    def add(i: int, j: int) -> None:
        if i == j:
            return
        k = (i, j) if i < j else (j, i)
        if k in seen:
            return
        seen.add(k)
        pairs.append(k)

    generic_captions = generic_captions if generic_captions is not None else generic_values(files, "caption_norm")
    generic_names = generic_names if generic_names is not None else generic_values(files, "name_norm")

    # ۱) نام: ایندکسِ توکنی + سبدِ «امضای قسمت + توکنِ اول»
    ni = _rare_token_index(files, "name_norm", skip_values=generic_names)
    for ids in ni.values():
        if len(ids) < 2:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                add(ids[a], ids[b])
    buckets: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for i, f in enumerate(files):
        nm = str(f.get("name_norm") or "")
        if not nm or nm in generic_names:
            continue
        sig = S.episode_signature(nm)
        toks = S.tokens(nm)
        head = toks[0] if toks else ""
        buckets[(sig, head)].append(i)
    for ids in buckets.values():
        if 2 <= len(ids) <= 60:
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    add(ids[a], ids[b])
        elif len(ids) > 60 and stats is not None:
            # نامِ خیلی عمومی (مثلِ «video-1») در یک سبدِ بزرگ ⇒ عمداً نامزدِ نام نمی‌سازیم،
            # ولی تعدادش را برمی‌گردانیم تا کاربر بداند چرا روی آن فایل‌ها فقط حجم/زمان کار می‌کند.
            stats["name_bucket_skipped"] = int(stats.get("name_bucket_skipped", 0)) + len(ids)

    # ۲) کپشن
    by_token: Dict[str, List[int]] = defaultdict(list)
    for i, f in enumerate(files):
        cn = str(f.get("caption_norm") or "")
        if len(cn) < S.MIN_CAPTION_LEN or cn in generic_captions:
            continue
        for tk in set(S.tokens(cn)):
            if len(tk) < 3:
                continue
            by_token[tk].append(i)
    # توکنِ خیلی پرتکرار (مثلِ «فیلم») نامزدِ بی‌فایده می‌سازد ⇒ حذف
    df_cap = max(60, int(len(files) * 0.02))
    by_token = {tk: ids for tk, ids in by_token.items() if 1 < len(ids) <= df_cap}
    # نامزدِ کپشن فقط با ≥۲ توکنِ مشترک
    shared: Dict[Tuple[int, int], int] = defaultdict(int)
    for tk, ids in by_token.items():
        if len(ids) > 0:
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    k = (ids[a], ids[b]) if ids[a] < ids[b] else (ids[b], ids[a])
                    shared[k] += 1
    for k, c in shared.items():
        if c >= 2:
            add(k[0], k[1])

    # ۳) حجم+زمان — دو ایندکسِ مکمل: پنجرهٔ حجم + زمانِ دقیقاً یکسان
    for i, j in _size_window_pairs(files, cfg, stats=stats):
        add(i, j)
    for i, j in _duration_pairs(files, cfg, stats=stats):
        add(i, j)

    return pairs


def _is_full_hash(fa: Dict[str, Any]) -> bool:
    """آیا هشِ این ردیف از **کلِ** فایل گرفته شده؟ (scope = `full`)"""
    return str(fa.get("hash_scope") or "").strip().lower() == "full"


def verify_pair(fa: Dict[str, Any], fb: Dict[str, Any], cfg: Dict[str, Any], *,
                generic_captions: Optional[Set[str]] = None,
                generic_names: Optional[Set[str]] = None,
                detail: Optional[Dict[str, bool]] = None) -> Dict[str, float]:
    """کدام سیگنال‌ها بین این دو فایل فعال است؟

    اگر `detail` بدهید، جزئیاتِ دقیقِ حجم/زمان در آن نوشته می‌شود
    (`size_eq` / `dur_eq`) تا برچسبِ «حجم و زمان یکسان» از **خودِ داده** بیاید.
    """
    out: Dict[str, float] = {}
    if S.hash_equal(fa, fb):
        out["hash" if (_is_full_hash(fa) and _is_full_hash(fb)) else "hash_partial"] = 1.0
    if S.same_telegram_file(fa, fb):
        out["telegram_file"] = 1.0
    na, nb = (fa.get("name_norm") or fa.get("file_name") or ""), (fb.get("name_norm") or fb.get("file_name") or "")
    if not (generic_names and (na in generic_names or nb in generic_names)):
        ok, sc = S.name_similar(na, nb, th_ratio=float(cfg.get("th_name_ratio", 0.82)),
                                th_jaccard=float(cfg.get("th_name_jaccard", 0.60)))
        if ok:
            out["name"] = sc
    ca, cb = (fa.get("caption_norm") or fa.get("caption") or ""), (fb.get("caption_norm") or fb.get("caption") or "")
    if not (generic_captions and (ca in generic_captions or cb in generic_captions)):
        ok, sc = S.caption_similar(ca, cb, th_ratio=float(cfg.get("th_cap_ratio", 0.80)),
                                   th_jaccard=float(cfg.get("th_cap_jaccard", 0.60)))
        if ok:
            out["caption"] = sc
    ok, sc = S.size_time_same(fa, fb,
                              size_tol_pct=float(cfg.get("size_tol_pct", 0.5)),
                              size_tol_min=int(cfg.get("size_tol_min", 2048)),
                              dur_tol_s=float(cfg.get("dur_tol_s", 2.0)),
                              min_size=int(cfg.get("min_size_for_match", 102400)),
                              min_duration_s=int(cfg.get("min_duration_s", 3)),
                              require_one_exact=bool(cfg.get("size_time_require_one_exact", True)))
    if ok:
        out["size_time"] = sc
        if detail is not None:
            detail["size_eq"] = bool(int(fa.get("size") or 0) == int(fb.get("size") or 0))
            detail["dur_eq"] = bool(int(fa.get("duration") or 0) == int(fb.get("duration") or 0))
    return out


def find_clusters(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *,
                  pairs: Optional[Sequence[Tuple[int, int]]] = None,
                  min_size: int = 2, stats: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """خوشه‌های تکراری را پیدا می‌کند (پس از بررسیِ هر جفت، گذرا/تراگذر).

    خروجی برای هر خوشه: {ids:[file_id…], reason:'…', strength:int, exact:bool, sizetime:bool, signals:[…]}

    `exact` یعنی **محتوای کامل** یکی است (هشِ کامل یا همان آپلودِ تلگرام) — هشِ
    نمونه‌ای (سه‌تکه) دیگر «قطعی» شمرده نمی‌شود. `stats` هم آمارِ نامزدسازی را
    برمی‌گرداند (مثلِ تعدادِ جفت‌هایی که به‌خاطرِ سقف بررسی نشدند).
    """
    files = list(files)
    if len(files) < 2:
        return []
    generic_captions = generic_values(files, "caption_norm")
    generic_names = generic_values(files, "name_norm")
    if pairs is None:
        pairs = candidate_pairs(files, cfg, generic_captions=generic_captions, generic_names=generic_names,
                                stats=stats)
    uf = UnionFind(len(files))
    pair_signals: Dict[Tuple[int, int], Dict[str, float]] = {}
    pair_flags: Dict[Tuple[int, int], Dict[str, bool]] = {}
    for i, j in pairs:
        det: Dict[str, bool] = {}
        sig = verify_pair(files[i], files[j], cfg, generic_captions=generic_captions,
                          generic_names=generic_names, detail=det)
        if sig:
            pair_signals[(min(i, j), max(i, j))] = sig
            pair_flags[(min(i, j), max(i, j))] = det
            uf.union(i, j)
    if not pair_signals:
        return []
    comps = uf.groups()
    out: List[Dict[str, Any]] = []
    for root, idxs in comps.items():
        if len(idxs) < min_size:
            continue
        members = set(idxs)
        agg: Dict[str, float] = {}
        for (i, j), sig in pair_signals.items():
            if i in members and j in members:
                for k, v in sig.items():
                    agg[k] = max(agg.get(k, 0.0), v)
        if not agg:
            continue
        signals = [s for s in ORDER if s in agg]
        strength = max(SIGNAL_STRENGTH[s] for s in signals)
        # «قطعی» = محتوای کامل یکی است (هشِ کامل یا همان آپلودِ تلگرام).
        # هشِ نمونه‌ای (سه‌تکه) عمداً این‌جا شمرده نمی‌شود.
        exact = bool("hash" in agg or "telegram_file" in agg)
        sizetime = bool("size_time" in agg)
        # پرچمِ «حجم/زمان دقیقاً برابر» از **خودِ بایت‌ها و ثانیه‌ها** می‌آید
        # (قبلاً از امتیازِ `size_time` خوانده می‌شد که باگ بود).
        size_eq = dur_eq = False
        for (i, j), det in pair_flags.items():
            if i in members and j in members:
                size_eq = size_eq or bool(det.get("size_eq"))
                dur_eq = dur_eq or bool(det.get("dur_eq"))
        st_exact = bool(size_eq and dur_eq)
        # برچسبِ دلیلِ حجم/زمان دقیقاً می‌گوید کدام‌شان برابر بود
        reason_items = []
        for sig in ORDER:
            if sig not in agg:
                continue
            if sig == "size_time":
                if size_eq and dur_eq:
                    reason_items.append("حجم و زمان یکسان")
                elif dur_eq:
                    reason_items.append("زمان یکسان + حجمِ نزدیک")
                elif size_eq:
                    reason_items.append("حجم یکسان + زمانِ نزدیک")
                else:
                    reason_items.append("حجم و زمانِ نزدیک")
            else:
                reason_items.append(REASON_TEXT[sig])
        ids = sorted([int(files[i]["id"]) for i in idxs])
        weak_only = (signals == ["size_time"])
        out.append({
            "ids": ids,
            "signals": signals,
            "reason": " + ".join(reason_items),
            "size_time_exact": st_exact,
            "approx": bool(weak_only and not st_exact),
            "review": bool(weak_only and len(ids) > 50),
            "strength": strength,
            "exact": exact,
            "sizetime": sizetime,
            "count": len(ids),
            "first_msg_id": min(int(files[i].get("msg_id") or 0) for i in idxs),
            "score": round(sum(agg.values()), 4),
        })
    out.sort(key=lambda c: (-c["strength"], -c["count"], c["first_msg_id"], c["ids"][0]))
    return out


def hash_candidate_ids(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *,
                       max_ids: int = 4000, stats: Optional[Dict[str, int]] = None) -> List[int]:
    """کدام فایل‌ها ارزشِ هش‌گذاری دارند؟ (اعضای نامزدهای اولیه + هم‌حجم‌های مشکوک)

    هشِ محتوایی گران است (دانلودِ جزئی) ⇒ فقط روی نامزدها انجام می‌شود، مگر در حالتِ «all».
    """
    files = list(files)
    mode = str(cfg.get("hash_mode") or "candidates")
    if mode == "off":
        return []
    min_size = int(cfg.get("min_size_for_match", 102400))
    if mode == "all":
        # در حالتِ all هم فایل‌های خیلی کوچک هش نمی‌شوند (قبلاً بی‌دلیل برای همه دانلود می‌شد)
        ids = [int(f["id"]) for f in files if int(f.get("size") or 0) >= min_size]
    else:
        pairs = candidate_pairs(files, cfg, stats=stats)
        hit: Set[int] = set()
        for i, j in pairs:
            hit.add(i)
            hit.add(j)
        # آستانهٔ حجم از تنظیمات می‌آید (قبلاً ۱۰۲۴ بایتِ سخت‌کد بود و کلی دانلودِ بی‌فایده می‌ساخت)
        ids = sorted({int(files[i]["id"]) for i in hit if int(files[i].get("size") or 0) >= min_size})
    if len(ids) > max_ids:
        if stats is not None:
            stats["hash_capped"] = int(len(ids) - max_ids)
        log.warning("hash_candidate_ids: %s فایل بیش از سقفِ %s ⇒ بخشی هش نمی‌شود", len(ids), max_ids)
        ids = ids[:max_ids]
    return ids
