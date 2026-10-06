"""تستِ لایهٔ دیتابیس: کانال‌ها، فایل‌ها، اسکن‌ها، گروه‌ها و ادامه از نقطهٔ قطع."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Db  # noqa: E402


def mkdb(tmp_path):
    return Db(str(tmp_path / "t.db"))


def test_kv_roundtrip(tmp_path):
    db = mkdb(tmp_path)
    db.kv_set("a", {"x": 1})
    db.kv_set("b", [1, 2, 3])
    db.kv_set("c", "متن")
    assert db.kv_get("a") == {"x": 1}
    assert db.kv_get("b") == [1, 2, 3]
    assert db.kv_get("c") == "متن"
    assert db.kv_get("nope", "def") == "def"
    assert set(db.kv_all()) == {"a", "b", "c"}
    db.close()


def test_channels_crud(tmp_path):
    db = mkdb(tmp_path)
    cid = db.add_channel(-1001234, "کانال یک", "@one")
    assert cid == 1
    assert db.add_channel(-1001234, "کانال یک (تازه)", "@one") == cid       # idempotent
    c = db.get_channel(cid)
    assert c["title"] == "کانال یک (تازه)" and c["username"] == "one"
    assert db.get_channel_by_tg(-1001234)["id"] == cid
    db.add_channel(-1009999, "کانال دو", "two")
    assert len(db.list_channels()) == 2
    db.set_paused_min_id(cid, 500)
    assert db.get_channel(cid)["paused_min_id"] == 500
    db.delete_channel(cid)
    assert db.get_channel(cid) is None and len(db.list_channels()) == 1
    db.close()


def row(msg_id, **kw):
    base = {"channel_id": 1, "msg_id": msg_id, "grouped_id": 0, "date": 1760000000, "doc_id": msg_id,
            "file_unique_id": "U%d" % msg_id, "file_identify": str(msg_id), "file_name": "f%d.mp4" % msg_id,
            "name_norm": "f %d" % msg_id, "caption": "c%d" % msg_id, "caption_norm": "c %d" % msg_id,
            "size": 10 * 1024 * 1024, "duration": 60, "mime": "video/mp4", "width": 1920, "height": 1080,
            "has_video": 1, "protected": 0}
    base.update(kw)
    return base


def test_files_upsert_and_queries(tmp_path):
    db = mkdb(tmp_path)
    assert db.add_files([row(1), row(2)]) == 2
    db.add_files([row(1, duration=99)])                    # upsert، نه تکراری
    assert db.count_files(1) == 2
    f = db.files_of_channel(1)
    assert [x["msg_id"] for x in f] == [1, 2]
    assert f[0]["duration"] == 99
    assert db.max_msg_id(1) == 2
    fid = f[1]["id"]
    db.set_hash(fid, "abc", "scope")
    assert db.get_file(fid)["content_hash"] == "abc"
    assert db.files_by_ids([fid])[0]["hash_scope"] == "scope"
    db.delete_files_older_than(1, 1)
    assert db.count_files(1) == 1
    db.close()


def test_scans_and_resume(tmp_path):
    db = mkdb(tmp_path)
    cid = db.add_channel(-1001, "c")
    sid = db.create_scan(cid, {"full": True}, min_id=0)
    db.update_scan(sid, seen_msgs=10, files_found=4, phase="index")
    s = db.get_scan(sid)
    assert s["status"] == "running" and s["seen_msgs"] == 10
    db.update_scan(sid, status="done", groups_found=2, finished_at=1)
    assert db.last_scan(cid)["groups_found"] == 2
    db.create_scan(cid, {"full": False}, min_id=99)
    assert len(db.scans_of(cid)) == 2
    assert db.last_scan(cid)["min_id"] == 99          # ادامه از نقطهٔ قطع
    db.close()


def test_groups_and_members_states(tmp_path):
    db = mkdb(tmp_path)
    cid = db.add_channel(-1001, "c")
    db.add_files([row(1), row(2), row(3)])
    ids = [f["id"] for f in db.files_of_channel(cid)]
    sid = db.create_scan(cid, {})
    n = db.replace_groups(sid, cid, [
        {"ids": ids[:2], "reason": "نام مشابه + حجم و زمان یکسان", "strength": 3, "exact": False, "sizetime": True},
        {"ids": [ids[2]], "reason": "x", "strength": 1},
    ])
    assert n == 2
    groups = db.groups_of_scan(sid)
    assert len(groups) == 2 and groups[0]["count"] == 2 and groups[0]["sizetime"] == 1
    assert db.count_groups(sid, signal="sizetime") == 1
    assert db.count_groups(sid, signal="name") == 1
    assert db.count_groups(sid, signal="exact") == 0
    gid = groups[0]["id"]
    members = db.group_members(gid)
    assert [m["msg_id"] for m in members] == [1, 2]
    db.set_group_state(gid, "done")
    assert db.get_group(gid)["state"] == "done"
    assert gid not in [g["id"] for g in db.groups_of_scan(sid, only_open=True)]
    assert [g["id"] for g in db.groups_of_scan(sid, state="done")] == [gid]
    # جایگزینی دوباره نباید ردیفِ یتیم بگذارد
    db.replace_groups(sid, cid, [{"ids": ids, "reason": "همه", "strength": 4, "exact": True}])
    assert len(db.groups_of_scan(sid)) == 1
    assert db.get_group(gid) is None
    db.close()


def test_stats_and_actions(tmp_path):
    db = mkdb(tmp_path)
    cid = db.add_channel(-1001, "c")
    db.add_files([row(1)])
    db.create_scan(cid, {})
    db.log_action("scan_done", "x")
    st = db.stats()
    assert st["channels"] == 1 and st["files"] == 1 and st["scans"] == 1 and st["hashed"] == 0
    db.close()
