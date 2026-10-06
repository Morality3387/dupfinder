"""تست‌های باگ‌های ۵…۹ + هشدارِ نامزدها (بازبینیِ کاربر)."""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main                                                # noqa: E402
from app import matching as M                              # noqa: E402
from app.db import Db                                      # noqa: E402
from app.scanner import Progress, Scanner                  # noqa: E402
from app.user_client import UserClient                     # noqa: E402

MB = 1024 * 1024
CFG = {"hash_mode": "off", "size_tol_pct": 0.5, "size_tol_min": 2048, "dur_tol_s": 2.0,
       "min_size_for_match": 102400, "min_duration_s": 3, "size_time_require_one_exact": True,
       "th_name_ratio": 0.82, "th_name_jaccard": 0.60, "th_cap_ratio": 0.80, "th_cap_jaccard": 0.60}


# ═══════════════ ۸) uptime ═══════════════
def test_uptime_is_elapsed_time_not_monotonic():
    """`uptime_s` قبلاً ساعتِ monotonic حلقه بود (عددِ بزرگ/بی‌معنی)."""
    assert 0 <= main.uptime_seconds() < 300
    main._STARTED_AT = time.time() - 125
    assert 123 <= main.uptime_seconds() <= 127
    main._STARTED_AT = time.time() + 999          # ساعت به عقب (مثلاً NTP) ⇒ منفی نشود
    assert main.uptime_seconds() == 0


# ═══════════════ ۶) حذفِ آبشاریِ کانال ═══════════════
def test_delete_channel_removes_all_related_rows(tmp_path):
    db = Db(str(tmp_path / "c.db"))
    cid = db.add_channel(-1001234567890, "کانالِ تست", "chan", "channel")
    db.add_files([{"channel_id": cid, "msg_id": i, "file_name": "f%d.mkv" % i,
                   "name_norm": "f%d" % i, "caption": "", "caption_norm": "", "size": 50 * MB,
                   "duration": 60, "mime": "video/mp4"} for i in (1, 2, 3)])
    sid = db.create_scan(cid, {"x": 1})
    fids = [int(f["id"]) for f in db.files_of_channel(cid)]
    db.replace_groups(sid, cid, [{"ids": fids[:2], "reason": "نام مشابه", "strength": 2, "exact": False,
                                  "sizetime": False, "count": 2}])
    db.kv_set("botadmin:%d" % cid, 1)
    gid = int(db.groups_of_scan(sid)[0]["id"])
    assert db.group_members(gid) and db.count_files(cid) == 3

    stats = db.delete_channel(cid)
    assert stats["files"] == 3 and stats["scans"] == 1 and stats["groups"] == 1
    assert stats["group_members"] == 2 and stats["channels"] == 1
    # هیچ داده‌ی orphan نمانده باشد
    for sql in ("SELECT COUNT(*) c FROM files WHERE channel_id=?",
                "SELECT COUNT(*) c FROM scans WHERE channel_id=?",
                "SELECT COUNT(*) c FROM groups WHERE channel_id=?",
                "SELECT COUNT(*) c FROM group_members WHERE group_id=?",
                "SELECT COUNT(*) c FROM channels WHERE id=?"):
        arg = gid if "group_members" in sql else cid
        assert int(db._one(sql, (arg,))["c"]) == 0, sql
    assert db.kv_get("botadmin:%d" % cid) is None      # کلیدِ ادمینِ کانال هم پاک شد
    assert db.get_channel(cid) is None
    db.close()


# ═══════════════ ۷) درصدِ پیشرفت بر پایهٔ شمارهٔ پیام ═══════════════
def test_progress_percent_uses_message_ids(tmp_path):
    """۱۰۰هزار پیام و ۱۰هزار ویدیو ⇒ درصد بر اساسِ موقعیتِ شناسه است، نه نسبتِ ویدیو/پیام."""
    db = Db(str(tmp_path / "p.db"))
    sc = Scanner(db, None, lambda: CFG)
    sc.progress = Progress(total=100_000, seen=10_000, top_id=500_000, last_msg_id=400_000, new_since=0)
    assert abs(sc._pct_index() - 54.4) < 0.01          # ۶۸ × ۴۰۰k/۵۰۰k
    # فرمولِ باگ‌دار قبلی ۶۸ × ۱۰k/۱۰۰k = ۶.۸ می‌داد ⇒ مطمئن شویم دیگر آن نیست
    assert sc._pct_index() > 20
    # بی‌شناسه (top نامعلوم) ⇒ تخمینِ محافظه‌کارانه و یکنوا
    sc.progress = Progress(total=100_000, seen=10_000)
    assert sc._pct_index() <= 34.0
    db.close()


# ═══════════════ ۹) حلِ موجودیتِ کانالِ خصوصی ═══════════════
class _Peer:
    def __init__(self, cid, access_hash):
        self.id = cid
        self.access_hash = access_hash


class _Dialog:
    def __init__(self, entity):
        self.entity = entity


class _TG:
    """تله‌تونِ ساختگی: کشِ سشن خالی، ولی فهرستِ گفتگوها کانال را دارد."""

    def __init__(self, *, dialogs=None, raise_all=False):
        self.dialogs = list(dialogs or [])
        self.raise_all = raise_all
        self.calls = []

    async def get_input_entity(self, ref):
        self.calls.append(("get_input_entity", ref))
        raise ValueError("Could not find the input entity for %r" % (ref,))

    async def get_entity(self, ref):
        self.calls.append(("get_entity", ref))
        raise ValueError("nope")

    def iter_dialogs(self, limit=0):
        async def gen():
            for d in self.dialogs:
                yield d
        return gen()


def _uc(tg):
    uc = UserClient(api_id=1, api_hash="h" * 32, session_string="S")
    uc.client = tg
    return uc


def test_private_channel_resolved_from_dialogs():
    """کانالِ خصوصی که access_hash در سشن نیست ⇒ از فهرستِ گفتگوها حل می‌شود."""
    tg = _TG(dialogs=[_Dialog(_Peer(-1001234567890, 987654321))])
    uc = _uc(tg)
    ent = asyncio.run(uc._entity(-1001234567890))
    assert int(ent.access_hash) == 987654321
    assert uc.peer_snapshot() == {"1001234567890": 987654321}   # برای ذخیرهٔ بعدی
    assert asyncio.run(uc._entity(-1001234567890)) is ent        # بارِ دوم از کش


def test_private_channel_resolved_from_cached_hash_and_hint_username():
    tg = _TG(raise_all=True)
    uc = _uc(tg)
    uc.set_hint(-1001234567890, username="mypriv", access_hash=555)
    ent = asyncio.run(uc._entity(-1001234567890))
    assert ent is not None                                   # با InputPeerChannel ساخته شد
    tg2 = _TG(raise_all=True)
    uc2 = _uc(tg2)
    uc2.set_hint(-1001234567890, username="mypriv")

    async def get_entity(ref):
        uc2.client.calls.append(("get_entity", ref))
        if isinstance(ref, str) and ref.startswith("@"):
            return _Peer(-1001234567890, 4242)
        raise ValueError("nope")

    tg2.get_entity = get_entity
    ent2 = asyncio.run(uc2._entity(-1001234567890))
    assert int(ent2.access_hash) == 4242


def test_unresolvable_channel_raises_clear_persian_error():
    tg = _TG(raise_all=True)
    uc = _uc(tg)
    try:
        asyncio.run(uc._entity(-1009999999999))
    except ValueError as e:
        assert "پیدا نشد" in str(e) and "حسابِ کاربری" in str(e) or "🔑" in str(e)
    else:
        raise AssertionError("باید خطای روشن می‌داد")
    assert uc.entity_misses


# ═══════════════ ۴) هشدارِ سقفِ نامزدها ═══════════════
def test_candidate_cap_produces_honest_warning(tmp_path):
    """سقفِ جفت‌های حجم نباید بی‌صدا چیزی را بیندازد: آمار برمی‌گردد و هشدار ساخته می‌شود."""
    rows = [{"id": i, "message_id": i, "channel_id": 1, "name_norm": "", "caption_norm": "",
             "file_name": "", "caption": "", "size": 900 * MB + i * 4096,
             "duration": 3000 + i, "content_hash": ""} for i in range(40)]
    stats = {}
    M.find_clusters(rows, dict(CFG, size_pair_cap=2), stats=stats)
    assert stats.get("size_pairs_dropped", 0) > 0


# ═══════════════ بازبینیِ سورس: ایرادهای دیگری که در پیمایشِ کد پیدا شد ═══════════════
def test_hash_candidates_respect_min_size_and_report_cap():
    """هشِ نامزدها باید آستانهٔ حجمِ تنظیمات و سقفِ تعداد را رعایت کند (قبلاً ۱KBِ سخت‌کد)."""
    files = [{"id": 1, "file_name": "a.mkv", "name_norm": "a", "caption_norm": "", "size": 100 * MB,
              "duration": 60},
             {"id": 2, "file_name": "a copy.mkv", "name_norm": "a", "caption_norm": "", "size": 100 * MB,
              "duration": 60},
             {"id": 3, "file_name": "a small.mkv", "name_norm": "a", "caption_norm": "", "size": 4096,
              "duration": 60}]
    ids = M.hash_candidate_ids(files, dict(CFG, hash_mode="candidates"))
    assert 1 in ids and 2 in ids and 3 not in ids          # فایلِ ۴KB هش نمی‌شود
    # حالتِ all با سقفِ کوچک ⇒ باید «بخشِ هش‌نشده» را گزارش کند (نه بی‌صدا)
    many = [{"id": i, "file_name": "f%d.mkv" % i, "name_norm": "f%d" % i, "caption_norm": "",
             "size": 100 * MB, "duration": 60} for i in range(40)]
    stats = {}
    capped = M.hash_candidate_ids(many, dict(CFG, hash_mode="all"), max_ids=5, stats=stats)
    assert len(capped) == 5 and stats["hash_capped"] == 35


def test_generic_name_bucket_is_reported_not_silently_dropped():
    """سبدِ نامِ خیلی عمومی (>۶۰ فایلِ هم‌نام) باید شمرده شود، نه بی‌صدا نادیده."""
    rows = [{"id": i, "message_id": i, "channel_id": 1, "file_name": "clip-%04d.mkv" % i,
             "name_norm": "clip %04d" % i, "caption_norm": "", "caption": "",
             "size": 900 * MB + i * 4096, "duration": 5000 + i, "content_hash": ""} for i in range(80)]
    stats = {}
    M.candidate_pairs(rows, CFG, stats=stats)
    assert stats.get("name_bucket_skipped", 0) >= 80


def test_forward_all_never_sends_a_file_twice(tmp_path):
    """نوبت‌های بودجه‌دار نباید فایلی را دوباره بفرستند (ادامه از نیمهٔ گروه)."""
    from tests.test_bot_flow import Env
    with tempfile.TemporaryDirectory() as d:
        e = Env(Path(d))
        e.bot.forward_all_budget = 3
        cid = e.add_channel()
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        scan_id = e.db.last_scan(cid)["id"]
        e.tap("fa:%d:%d:all:0" % (scan_id, cid))
        e.tap("fa:%d:%d:all:0" % (scan_id, cid))
        e.tap("fa:%d:%d:all:0" % (scan_id, cid))
        e.tap("fa:%d:%d:all:0" % (scan_id, cid))
        sent = [(f["from"], f["msg_id"]) for f in e.api.forwards]
        assert len(sent) == 9, sent                       # کلِ ۹ فایلِ تکراری
        assert len(set(sent)) == len(sent), "فایلی دو بار فرستاده شد"
        e.close()


def test_candidate_pairs_works_without_pre_normalized_fields():
    """اگر ردیف‌ها فقط `file_name` داشته باشند هم سیگنالِ نام باید کار کند، نه اینکه بی‌صدا خاموش شود."""
    rows = [{"id": i, "message_id": i, "channel_id": 1, "file_name": nm, "caption": "",
             "size": 700 * MB + i * 8192, "duration": 3600 + i, "content_hash": ""}
            for i, nm in enumerate(["Atomic.Blonde.2017.1080p.WEB-DL.mkv",
                                    "Atomic.Blonde.2017.720p.HDTV.mkv",
                                    "Atomic.Blonde.2017.480p.DVDRip.mkv"])]
    assert M.candidate_pairs(rows, CFG), "سیگنالِ نام با ردیف‌های خام باید نامزد بسازد"


def test_same_name_different_quality_is_matched():
    """سه نسخهٔ یک فیلم با کیفیت‌های مختلف (حجم/مدتِ متفاوت) باید تکراری شناخته شوند."""
    rows = [{"id": i + 1, "message_id": i + 1, "channel_id": 1, "file_name": nm, "caption": "",
             "size": sz, "duration": dur, "content_hash": ""}
            for i, (nm, sz, dur) in enumerate([
                ("فیلم تست 1080p.mkv", 1200 * MB, 5400),
                ("فیلم تست 720p.mkv", 640 * MB, 5400),
                ("فیلم تست 480p.mkv", 260 * MB, 5410)])]
    rows = [{**r, "name_norm": __import__("app.similarity", fromlist=["x"]).name_norm(r["file_name"]),
             "caption_norm": ""} for r in rows]
    cands = M.candidate_pairs(rows, CFG)
    assert cands, "کاندیدای نام ساخته نشد"
    sigs = [M.verify_pair(rows[a], rows[b], CFG) for a, b in cands]
    assert all(sigs), [c for c, s in zip(cands, sigs) if not s]      # هر جفت تأیید شود
    assert all("name" in s for s in sigs)                            # از راهِ سیگنالِ نام
    clusters = M.find_clusters(rows, CFG)
    assert len(clusters) == 1 and sorted(clusters[0]["ids"]) == [1, 2, 3]
