"""تستِ موتورِ اسکن: ایندکس، هشِ نامزدها، نوارِ پیشرفت، کنسل و ادامه."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Db                                    # noqa: E402
from app.scanner import Scanner                          # noqa: E402
from dev.fake_telegram import FakeUser, channel_dataset  # noqa: E402

CFG = {"th_name_ratio": 0.82, "th_name_jaccard": 0.60, "th_cap_ratio": 0.80, "th_cap_jaccard": 0.60,
       "size_tol_pct": 0.5, "size_tol_min": 2048, "dur_tol_s": 2.0, "min_size_for_match": 102400,
       "min_duration_s": 3, "hash_mode": "candidates", "media_kinds": "video", "progress_interval": 0.0,
       "scan_wait_time": 0.0, "size_time_require_one_exact": True}


def setup(tmp_path, **kw):
    db = Db(str(tmp_path / "s.db"))
    ds = channel_dataset()
    user = FakeUser(videos={55: ds["videos"]}, contents=ds["contents"],
                    titles={55: ds["title"], 77: {"tg_id": 77, "title": "کانال دو", "username": "chan2", "kind": "channel"}}, **kw)
    cid = db.add_channel(55, "کانالِ تست", "testchan")
    return db, user, db.get_channel(cid)


def run(coro):
    return asyncio.run(coro)


def test_full_scan_indexes_and_groups(tmp_path):
    db, user, chan = setup(tmp_path)
    seen = []

    async def on_prog(p):
        seen.append(p.as_dict())

    sc = Scanner(db, user, lambda: CFG, on_progress=on_prog)
    res = run(sc.run(chan, full=True))
    assert res.status == "done" and not res.canceled
    assert res.files == 13
    assert res.groups == 4
    assert res.hashed > 0
    # پیشرفت باید یکنوا باشد و به ۱۰۰ برسد
    pcts = [s["pct"] for s in seen]
    assert pcts == sorted(pcts) and pcts[-1] == 100.0
    assert {s["phase"] for s in seen} >= {"index", "match", "done"}
    # گروهِ «حجم و زمان» و گروهِ «هش»
    groups = db.groups_of_scan(res.scan_id)
    reasons = " | ".join(g["reason"] for g in groups)
    assert "حجم و زمان" in reasons and "نام" in reasons and "کپشن" in reasons
    sid = res.scan_id
    # هشِ پیش‌فرض «نمونه‌ای» است ⇒ قوی ولی نه قطعی (★★★★ فقط برای هشِ کامل/شناسهٔ تلگرام)
    content = [g for g in groups if "نمونهٔ محتوا" in g["reason"]]
    assert content and content[0]["strength"] == 3
    assert [g for g in groups if g["exact"]] == []
    # شمارش‌های خلاصه
    assert db.count_groups(sid, signal="sizetime") >= 1
    assert db.get_scan(sid)["status"] == "done"
    assert db.get_channel(chan["id"])["last_scan_id"] == sid
    db.close()


def test_hashes_only_candidates(tmp_path):
    db, user, chan = setup(tmp_path)
    sc = Scanner(db, user, lambda: CFG)
    res = run(sc.run(chan, full=True))
    hashed = [f for f in db.files_of_channel(chan["id"]) if f["content_hash"]]
    assert 0 < len(hashed) < 13        # همه هش نمی‌شوند؛ فقط نامزدها
    # فایلِ یگانه (۱۵۰) هش نمی‌شود
    assert not any(f["msg_id"] == 150 for f in hashed)
    # ۱۰۱ و ۱۰۲ هشِ یکسان دارند و «قطعی» شده‌اند
    h = {f["msg_id"]: f["content_hash"] for f in hashed}
    assert h.get(101) and h.get(101) == h.get(102)
    db.close()


def test_hash_mode_off_skips_downloads(tmp_path):
    db, user, chan = setup(tmp_path)
    sc = Scanner(db, user, lambda: dict(CFG, hash_mode="off"))
    res = run(sc.run(chan, full=True))
    assert res.hashed == 0 and user.hash_batches == []
    assert all(not f["content_hash"] for f in db.files_of_channel(chan["id"]))
    assert db.count_groups(res.scan_id, signal="exact") == 0
    db.close()


def test_cancel_mid_scan_keeps_partial(tmp_path):
    db, user, chan = setup(tmp_path, delay=0.02)
    holder = {}

    async def on_prog(p):
        if p.phase == "index" and p.files >= 5 and not holder.get("canceled"):
            holder["canceled"] = True
            holder["scanner"].cancel()

    sc = Scanner(db, user, lambda: CFG, on_progress=on_prog)
    holder["scanner"] = sc
    res = run(sc.run(chan, full=True))
    assert res.status == "canceled" and res.canceled
    assert 0 < res.files < 13
    scan = db.get_scan(res.scan_id)
    assert scan["status"] == "canceled"
    assert db.count_files(chan["id"]) == res.files        # آنچه خوانده شد حفظ شده
    db.close()


def test_resume_indexes_only_new_messages(tmp_path):
    db, user, chan = setup(tmp_path)
    sc = Scanner(db, user, lambda: CFG)
    res1 = run(sc.run(chan, full=True))
    assert res1.files == 13
    # دو ویدیوی تازه اضافه می‌کنیم
    user.videos[55] = list(user.videos[55]) + [
        {"msg_id": 160, "grouped_id": 0, "date": 1760000000, "doc_id": 9060, "file_unique_id": "U160",
         "file_identify": "9060", "file_name": "New.Clip.S01E01.1080p.mkv", "caption": "",
         "size": 30 * 1024 * 1024, "duration": 45, "mime": "video/mp4", "width": 1280, "height": 720,
         "has_video": 1, "protected": 0},
        {"msg_id": 161, "grouped_id": 0, "date": 1760000000, "doc_id": 9061, "file_unique_id": "U161",
         "file_identify": "9061", "file_name": "New.Clip.S01E01.720p.mkv", "caption": "",
         "size": 30 * 1024 * 1024, "duration": 45, "mime": "video/mp4", "width": 1280, "height": 720,
         "has_video": 1, "protected": 0},
    ]
    sc2 = Scanner(db, user, lambda: CFG)
    res2 = run(sc2.run(chan, full=False))
    assert res2.files == 15                              # کلِ ایندکس
    assert db.get_scan(res2.scan_id)["min_id"] == 150     # فقط از بعدِ آخرین پیامِ دیده‌شده
    # گروه‌بندی روی کلِ ایندکس اجرا می‌شود ⇒ تکراریِ تازه پیدا شد
    assert res2.groups >= 1
    db.close()


def test_error_in_scan_is_reported(tmp_path):
    db, user, chan = setup(tmp_path)

    async def boom(*a, **kw):
        raise RuntimeError("شبکه قطع شد")
        yield 1  # pragma: no cover

    user.iter_videos = boom
    sc = Scanner(db, user, lambda: CFG)
    res = run(sc.run(chan, full=True))
    assert res.status == "error" and "شبکه قطع شد" in res.error
    assert db.get_scan(res.scan_id)["status"] == "error"
    db.close()


def test_probe_used_for_progress_total(tmp_path):
    db, user, chan = setup(tmp_path, total_hint=40)
    sc = Scanner(db, user, lambda: CFG)
    res = run(sc.run(chan, full=True))
    assert user.probed == [55]
    assert db.get_scan(res.scan_id)["total_msgs"] == 40
    db.close()


def test_scanning_two_channels_is_isolated(tmp_path):
    db, user, chan = setup(tmp_path)
    ds = channel_dataset()
    cid2 = db.add_channel(77, "کانال دو", "chan2")
    user.videos[77] = [ds["videos"][0], ds["videos"][1]]      # همان دو فایلِ ۱۰۱/۱۰۲
    sc = Scanner(db, user, lambda: CFG)
    r1 = run(sc.run(db.get_channel(chan["id"]), full=True))
    r2 = run(sc.run(db.get_channel(cid2), full=True))
    assert r1.files == 13 and r2.files == 2
    assert db.count_files(chan["id"]) == 13 and db.count_files(cid2) == 2
    # گروه‌ها بینِ کانال‌ها قاطی نمی‌شوند
    assert all(g["channel_id"] == cid2 for g in db.groups_of_scan(r2.scan_id))
    db.close()
