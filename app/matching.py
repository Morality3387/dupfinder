"""گروه‌بندیِ تکراری‌ها — اولویت: ۱) نام  ۲) کپشن  ۳) حجم+زمان، به‌علاوهٔ هشِ قطعی.

ورودی: فهرستِ ردیف‌های فایل (dict) · خروجی: خوشه‌های تکراری با دلیل و قدرت.
تابعِ اصلی `find_clusters()` است که دو بار اجرا می‌شود: یک بار با فراداده (سریع، برای
پیدا کردنِ نامزدها) و یک بار پس از هش‌گذاریِ نامزدها (برچسبِ «قطعاً همان فایل»).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import similarity as S

REASON_TEXT = {
    "hash": "هشِ محتوا یکسان",
    "telegram_file": "همان فایلِ تلگرام (شناسهٔ یکسان)",
    "name": "نام مشابه",
    "caption": "کپشن مشابه",
    "size_time": "حجم و زمان یکسان",
}
SIGNAL_STRENGTH = {"hash": 4, "telegram_file": 4, "size_time": 3, "name": 2, "caption": 1}
# ترتیبِ بررسی = ترتیبِ اولویتِ کارفرما (نام → کپشن → حجم/زمان) + سیگنال‌های قطعی
ORDER = ("hash", "telegram_file", "name", "caption", "size_time")


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


def _size_window_pairs(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *, per_item_cap: int = 60) -> Iterable[Tuple[int, int]]:
    """جفت‌های نامزدِ «حجمِ نزدیک» با پنجرهٔ لغزان روی حجمِ مرتب — به‌جای O(n²)."""
    order = sorted(range(len(files)), key=lambda i: int(files[i].get("size") or 0))
    tol_min = int(cfg.get("size_tol_min", 2048))
    tol_pct = float(cfg.get("size_tol_pct", 0.5))
    n = len(order)
    for a_pos in range(n):
        i = order[a_pos]
        si = int(files[i].get("size") or 0)
        if si <= 0:
            continue
        tol_i = max(tol_min, int(round(si * tol_pct / 100.0)))
        used = 0
        for b_pos in range(a_pos + 1, n):
            j = order[b_pos]
            sj = int(files[j].get("size") or 0)
            if sj - si > tol_i:
                break
            if abs(si - sj) <= tol_i:
                yield i, j
                used += 1
                if used >= per_item_cap:
                    break


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
                    generic_names: Optional[Set[str]] = None) -> List[Tuple[int, int]]:
    """جفت‌های نامزدی که ارزشِ بررسی دارند (نامزدِ هر سه سیگنال)."""
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

    # ۳) حجم+زمان
    for i, j in _size_window_pairs(files, cfg):
        add(i, j)

    return pairs


def verify_pair(fa: Dict[str, Any], fb: Dict[str, Any], cfg: Dict[str, Any], *,
                generic_captions: Optional[Set[str]] = None,
                generic_names: Optional[Set[str]] = None) -> Dict[str, float]:
    """کدام سیگنال‌ها بین این دو فایل فعال است؟"""
    out: Dict[str, float] = {}
    if S.hash_equal(fa, fb):
        out["hash"] = 1.0
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
    return out


def find_clusters(files: Sequence[Dict[str, Any]], cfg: Dict[str, Any], *,
                  pairs: Optional[Sequence[Tuple[int, int]]] = None,
                  min_size: int = 2) -> List[Dict[str, Any]]:
    """خوشه‌های تکراری را پیدا می‌کند (پس از بررسیِ هر جفت، گذرا/تراگذر).

    خروجی برای هر خوشه: {ids:[file_id…], reason:'…', strength:int, exact:bool, sizetime:bool, signals:[…]}
    """
    files = list(files)
    if len(files) < 2:
        return []
    generic_captions = generic_values(files, "caption_norm")
    generic_names = generic_values(files, "name_norm")
    if pairs is None:
        pairs = candidate_pairs(files, cfg, generic_captions=generic_captions, generic_names=generic_names)
    uf = UnionFind(len(files))
    pair_signals: Dict[Tuple[int, int], Dict[str, float]] = {}
    for i, j in pairs:
        sig = verify_pair(files[i], files[j], cfg, generic_captions=generic_captions,
                          generic_names=generic_names)
        if sig:
            pair_signals[(min(i, j), max(i, j))] = sig
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
        exact = bool("hash" in agg or "telegram_file" in agg)
        st_exact = float(agg.get("size_time", 0.0)) >= 0.999      # حجم و زمانِ هر دو دقیقاً برابر
        sizetime = bool("size_time" in agg)
        # برچسبِ دقیق/تقریبی برای سیگنالِ حجم+زمان (تمرکزِ اصلیِ کارفرما)
        reason_items = []
        for sig in ORDER:
            if sig not in agg:
                continue
            if sig == "size_time":
                reason_items.append("حجم و زمان یکسان" if st_exact else "حجم و زمانِ نزدیک")
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
                       max_ids: int = 4000) -> List[int]:
    """کدام فایل‌ها ارزشِ هش‌گذاری دارند؟ (اعضای نامزدهای اولیه + هم‌حجم‌های مشکوک)

    هشِ محتوایی گران است (دانلودِ جزئی) ⇒ فقط روی نامزدها انجام می‌شود، مگر در حالتِ «all».
    """
    files = list(files)
    mode = str(cfg.get("hash_mode") or "candidates")
    if mode == "off":
        return []
    if mode == "all":
        ids = [int(f["id"]) for f in files if int(f.get("size") or 0) >= int(cfg.get("min_size_for_match", 102400))]
        return ids[:max_ids]
    pairs = candidate_pairs(files, cfg)
    hit: Set[int] = set()
    for i, j in pairs:
        hit.add(i)
        hit.add(j)
    ids = sorted({int(files[i]["id"]) for i in hit if int(files[i].get("size") or 0) >= 1024})
    return ids[:max_ids]
