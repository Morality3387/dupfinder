"""گروه‌بندیِ تکراری‌ها روی مجموعهٔ ساختگی — همان چیزی که کاربرِ واقعی انتظار دارد."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import matching as M  # noqa: E402
from app import similarity as S  # noqa: E402
from dev.fake_telegram import channel_dataset  # noqa: E402

CFG = {"th_name_ratio": 0.82, "th_name_jaccard": 0.60, "th_cap_ratio": 0.80, "th_cap_jaccard": 0.60,
       "size_tol_pct": 0.5, "size_tol_min": 2048, "dur_tol_s": 2.0, "min_size_for_match": 102400,
       "min_duration_s": 3, "hash_mode": "candidates"}


def load_rows():
    ds = channel_dataset()
    rows = []
    for i, r in enumerate(ds["videos"], start=1):
        row = dict(r)
        row["id"] = i
        row["channel_id"] = 1
        row["name_norm"] = S.name_norm(row.get("file_name"))
        row["caption_norm"] = S.caption_norm(row.get("caption"))
        row["content_hash"] = ""
        row["hash_scope"] = ""
        rows.append(row)
    return rows


def ids_by_msg(clusters):
    return [sorted(int(r["first_msg_id"]) for r in [c]) for c in clusters]


def cluster_of(clusters, msg_id, rows):
    """کدام خوشه شاملِ فایلی با msg_id داده‌شده است؟"""
    fid = next(r["id"] for r in rows if r["msg_id"] == msg_id)
    for c in clusters:
        if fid in c["ids"]:
            return c
    return None


def test_pipeline_finds_expected_groups():
    rows = load_rows()
    clusters = M.find_clusters(rows, CFG)
    assert len(clusters) == 4, [(c["reason"], c["count"], [r["msg_id"] for r in rows if r["id"] in c["ids"]])
                                for c in clusters]
    # ۱) دو آپلودِ جدا با نامِ یکسان
    c = cluster_of(clusters, 101, rows)
    assert c and sorted(r["msg_id"] for r in rows if r["id"] in c["ids"]) == [101, 102]
    assert "نام" in c["reason"] and "حجم و زمان" in c["reason"]
    # ۲) نسخه‌های ۱۰۸۰p و ۷۲۰p
    c = cluster_of(clusters, 110, rows)
    assert c and sorted(r["msg_id"] for r in rows if r["id"] in c["ids"]) == [110, 111]
    # ۳) کپشنِ یکسان با نام‌های بی‌ربط
    c = cluster_of(clusters, 120, rows)
    assert c and sorted(r["msg_id"] for r in rows if r["id"] in c["ids"]) == [120, 121]
    assert "کپشن" in c["reason"]
    # ۴) حجم و زمانِ یکسان (تمرکزِ اصلیِ کارفرما)
    c = cluster_of(clusters, 130, rows)
    assert c and sorted(r["msg_id"] for r in rows if r["id"] in c["ids"]) == [130, 131, 132]
    assert c["sizetime"] and c["strength"] == 3
    # ۵) قسمت‌های پشت‌سرهم هرگز تکراری نمی‌شوند
    for m in (140, 141, 142):
        assert cluster_of(clusters, m, rows) is None
    # ۶) فایلِ یگانه
    assert cluster_of(clusters, 150, rows) is None


def test_clusters_sorted_by_strength():
    rows = load_rows()
    clusters = M.find_clusters(rows, CFG)
    strengths = [c["strength"] for c in clusters]
    assert strengths == sorted(strengths, reverse=True)
    assert strengths[0] == 3        # قبل از هش‌گذاری، بالاترین ★★★ (حجم+زمان)


def test_hash_upgrades_group_to_exact():
    rows = load_rows()
    first = M.find_clusters(rows, CFG)
    assert cluster_of(first, 101, rows)["exact"] is False
    # هشِ یکسان برای ۱۰۱ و ۱۰۲ (شبیه‌سازیِ خروجیِ واقعیِ هش‌گذاری)
    for r in rows:
        if r["msg_id"] in (101, 102):
            r["content_hash"] = "9f2c1d" + "0" * 26
            r["hash_scope"] = "0+131072,100352+131072"
    second = M.find_clusters(rows, CFG)
    c = cluster_of(second, 101, rows)
    assert c["exact"] is True and c["strength"] == 4
    assert "هش" in c["reason"]
    # نامزدِ هش‌گذاری باید شاملِ همین دو باشد
    ids = M.hash_candidate_ids(rows, CFG)
    byid = {r["id"]: r["msg_id"] for r in rows}
    assert 101 in {byid[i] for i in ids} and 102 in {byid[i] for i in ids}


def test_hash_mode_off_and_all():
    rows = load_rows()
    assert M.hash_candidate_ids(rows, dict(CFG, hash_mode="off")) == []
    allids = M.hash_candidate_ids(rows, dict(CFG, hash_mode="all"))
    assert len(allids) == len(rows)      # همه بزرگ‌تر از حدِ ۱۰۰KB هستند
    # نامزدها زیرمجموعهٔ همه‌اند
    cands = set(M.hash_candidate_ids(rows, dict(CFG, hash_mode="candidates")))
    assert cands and cands.issubset(set(allids))


def test_same_telegram_file_is_exact():
    rows = load_rows()
    for r in rows:
        if r["msg_id"] == 111:
            r["file_unique_id"] = rows[2]["file_unique_id"]     # همان آپلودِ ۱۱۰
    clusters = M.find_clusters(rows, CFG)
    c = cluster_of(clusters, 110, rows)
    assert c["exact"] is True and "شناسهٔ یکسان" in c["reason"]


def test_transitivity_and_reason_merge():
    """زنجیره: A~B (نام) و B~C (کپشن) ⇒ یک گروه با هر دو دلیل."""
    rows = [
        {"id": 1, "msg_id": 1, "file_name": "Lecture.Physics.2024.mp4", "name_norm": "lecture physics 2024",
         "caption_norm": "", "caption": "", "size": 10 * 1024 * 1024, "duration": 600, "content_hash": ""},
        {"id": 2, "msg_id": 2, "file_name": "Lecture-Physics-2024-final.mp4", "name_norm": "lecture physics 2024 final",
         "caption_norm": "جلسهٔ اول فیزیک پایه با مثال‌های حل‌شده", "caption": "جلسهٔ اول فیزیک پایه با مثال‌های حل‌شده",
         "size": 11 * 1024 * 1024, "duration": 610, "content_hash": ""},
        {"id": 3, "msg_id": 3, "file_name": "zaban-77.mp4", "name_norm": "zaban 77",
         "caption_norm": "جلسهٔ اول فیزیک پایه با مثال‌های حل‌شده", "caption": "جلسهٔ اول فیزیک پایه با مثال‌های حل‌شده",
         "size": 9 * 1024 * 1024, "duration": 590, "content_hash": ""},
    ]
    clusters = M.find_clusters(rows, CFG)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["count"] == 3
    assert "نام" in c["reason"] and "کپشن" in c["reason"]


def test_no_false_positive_same_show_different_episodes():
    rows = []
    for i, ep in enumerate([1, 2, 3, 4], start=1):
        name = "The.Show.S03E%02d.1080p.WEB-DL.x265.mkv" % ep
        rows.append({"id": i, "msg_id": 100 + i, "file_name": name, "name_norm": S.name_norm(name),
                     "caption_norm": "قسمت %d فصل سه" % ep, "caption": "قسمت %d فصل سه" % ep,
                     "size": (700 + i) * 1024 * 1024, "duration": 2700 + i * 60, "content_hash": ""})
    assert M.find_clusters(rows, CFG) == []


def test_album_siblings_are_not_flagged_when_different():
    """۲ فایلِ یک پستِ آلبومی که واقعاً متفاوت‌اند نباید تکراری شمرده شوند."""
    rows = [
        {"id": 1, "msg_id": 1, "grouped_id": 55, "file_name": "a-part1.mp4", "name_norm": "a part1",
         "caption_norm": "رویداد ورزشی امشب در سالن مرکزی", "caption": "رویداد ورزشی امشب در سالن مرکزی",
         "size": 20 * 1024 * 1024, "duration": 30, "content_hash": ""},
        {"id": 2, "msg_id": 2, "grouped_id": 55, "file_name": "a-part2.mp4", "name_norm": "a part2",
         "caption_norm": "رویداد ورزشی امشب در سالن مرکزی", "caption": "رویداد ورزشی امشب در سالن مرکزی",
         "size": 21 * 1024 * 1024, "duration": 31, "content_hash": ""},
    ]
    clusters = M.find_clusters(rows, CFG)
    # کپشنِ یکسان + نامِ نزدیک ⇒ طبیعتاً تطبیق می‌شود (همان رویداد) — ولی حجم/زمانِ
    # متفاوت باعثِ «قطعی» شدن نمی‌شود؛ فقط سیگنال‌های ضعیف‌تر فعال‌اند.
    assert len(clusters) == 1
    assert clusters[0]["exact"] is False and clusters[0]["sizetime"] is False


def test_verify_pair_reports_each_signal():
    a = {"file_name": "x.1080p.mkv", "name_norm": "x", "caption": "", "caption_norm": "", "size": 50 * 1024 * 1024,
         "duration": 60, "content_hash": "h1", "hash_scope": "s"}
    b = dict(a, id=2)
    sig = M.verify_pair(a, b, CFG)
    assert set(sig) == {"hash", "name", "size_time"}


def test_candidate_pairs_bounded_on_big_channel():
    """کانالِ بزرگ با نام‌های یکسان نباید منفجر شود (سقفِ نامزد)."""
    rows = []
    for i in range(1500):
        name = "film-%04d.1080p.mkv" % i
        rows.append({"id": i, "msg_id": i, "file_name": name, "name_norm": S.name_norm(name),
                     "caption_norm": "کانال فیلم و سریال دانلود کنید", "caption": "کانال فیلم و سریال دانلود کنید",
                     "size": 10 * 1024 * 1024 + (i % 400) * 250_000, "duration": 100 + (i % 900),
                     "content_hash": ""})
    pairs = M.candidate_pairs(rows, CFG)
    assert len(pairs) < 30_000       # بدونِ سقف‌ها، میلیون‌ها جفت می‌شد
    clusters = M.find_clusters(rows, CFG, pairs=pairs)
    assert clusters == []            # هیچ‌کدام واقعاً تکراری نیستند


def test_generic_signature_caption_is_not_a_duplicate_signal():
    """کپشنِ امضاییِ کانال (روی همهٔ پست‌ها) نباید همه را «تکراری» کند."""
    rows = []
    sig_caption = "🔻 کانال فیلم و سریال ما را دنبال کنید"
    for i in range(40):
        name = "video-%d.mp4" % i
        rows.append({"id": i, "msg_id": i, "file_name": name, "name_norm": S.name_norm(name),
                     "caption": sig_caption, "caption_norm": S.caption_norm(sig_caption),
                     "size": (20 + i * 7) * 1024 * 1024, "duration": 120 + i * 9, "content_hash": ""})
    assert M.generic_values(rows, "caption_norm") == {S.caption_norm(sig_caption)}
    assert M.find_clusters(rows, CFG) == []
    # ولی اگر فقط ۳ فایل از ۴۰ کپشنِ یکسانِ واقعی داشته باشند، سیگنال فعال می‌ماند
    for r in rows[:3]:
        r["caption"] = "قسمتِ پایانی سریال با بازیگران اصلی امشب منتشر شد و دیدنش را از دست ندهید"
        r["caption_norm"] = S.caption_norm(r["caption"])
    clusters = M.find_clusters(rows, CFG)
    assert len(clusters) == 1 and clusters[0]["count"] == 3
