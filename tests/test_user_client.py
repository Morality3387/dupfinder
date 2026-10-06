"""تستِ کلاینتِ کاربریِ **واقعی** (Telethon) با یک لایهٔ تله‌تونِ ساختگی.

هدف: فقط منطقِ `probe` / `iter_videos` / `hash_batch` / `hash_file` آزمایش شود —
بدونِ شبکه و بدونِ تلگرام. این تست همان مسیری را می‌پیماید که در Railway اجرا می‌شود.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Db                                    # noqa: E402
from app.scanner import Scanner                          # noqa: E402
from app.user_client import CHUNK, UserClient, chunk_plan  # noqa: E402
from dev.fake_telegram import channel_dataset            # noqa: E402
from tests.test_scanner import CFG                       # noqa: E402

MB = 1024 * 1024


# ───────────────────────── لایهٔ تله‌تونِ ساختگی ─────────────────────────
class DocumentAttributeFilename:
    def __init__(self, file_name):
        self.file_name = file_name


class DocumentAttributeVideo:
    def __init__(self, duration=0, w=0, h=0):
        self.duration, self.w, self.h = duration, w, h


class Msg:
    """پیامِ تله‌تون با همان فیلدهایی که `msg_to_file` می‌خواند."""

    def __init__(self, spec, seed: bytes):
        self.id = int(spec["msg_id"])
        self.grouped_id = int(spec.get("grouped_id") or 0)
        self.date = datetime.fromtimestamp(int(spec.get("date") or 0), tz=timezone.utc)
        self.message = spec.get("caption") or ""
        self.noforwards = False
        self.action = None
        self.video = SimpleNamespace()
        self.document = SimpleNamespace(
            id=int(spec.get("doc_id") or 0), mime_type=spec.get("mime") or "video/mp4",
            size=int(spec["size"]),
            attributes=[DocumentAttributeFilename(spec.get("file_name") or "f.mp4"),
                        DocumentAttributeVideo(int(spec.get("duration") or 0),
                                               int(spec.get("width") or 0), int(spec.get("height") or 0))])
        self.file = SimpleNamespace(size=int(spec["size"]), name=spec.get("file_name") or "f.mp4",
                                    duration=int(spec.get("duration") or 0),
                                    width=int(spec.get("width") or 0), height=int(spec.get("height") or 0),
                                    unique_id=spec.get("file_unique_id") or "")
        self.media = self.document
        self.seed = seed

    # «فایل» = تکرارِ seed تا حجمِ اعلام‌شده؛ پس هر offset/limit قابلِ تولید است
    def bytes_at(self, off: int, ln: int) -> bytes:
        seed = self.seed or b"\x00"
        out = bytearray()
        pos = int(off)
        while len(out) < ln:
            i = pos % len(seed)
            take = min(ln - len(out), len(seed) - i)
            out += seed[i:i + take]
            pos += take
        return bytes(out)


class FakeTelethon:
    """جایِ `TelegramClient` — همان متدهایی که کدِ ما صدا می‌زند."""

    def __init__(self, msgs, *, title="کانالِ تست", fail_iter=False):
        self.msgs = {int(m.id): m for m in msgs}
        self.title = title
        self.fail_iter = fail_iter
        self.count = len(self.msgs) + 7          # چند پیامِ غیرِ‌ویدیویی هم هست
        self.downloads = []                      # (msg_id, offset, length)
        self._by_media = {id(m.media): m for m in self.msgs.values()}

    # اتصال
    def is_connected(self):
        return True

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return SimpleNamespace(id=777, username="dupe_user", first_name="Dup", last_name="User")

    # مسیرها
    async def get_input_entity(self, ref):
        return ("peer", int(ref))

    async def get_entity(self, ref):
        return SimpleNamespace(id=int(ref), title=self.title, username="testchan",
                               broadcast=True, first_name="", last_name="")

    async def get_messages(self, ent, ids=None, limit=None):
        if ids is None:                                   # تازه‌ترین
            if not self.msgs:
                return []
            return [self.msgs[max(self.msgs)]]
        if isinstance(ids, (list, tuple)):
            return [self.msgs.get(int(i)) for i in ids]
        return self.msgs.get(int(ids))

    async def __call__(self, req):                        # GetHistoryRequest
        newest = self.msgs[max(self.msgs)] if self.msgs else None
        return SimpleNamespace(count=self.count, messages=[newest] if newest else [])

    async def iter_messages(self, ent, **kw):
        if self.fail_iter:
            raise RuntimeError("ITER_FAIL")
        min_id = int(kw.get("min_id") or 0)
        for mid in sorted(self.msgs):
            if mid > min_id:
                yield self.msgs[mid]

    def iter_download(self, media, offset=0, limit=0, request_size=0, chunk_size=0):
        return self._download(media, int(offset or 0), int(limit or 0))

    async def _download(self, media, off, ln):
        msg = self._by_media.get(id(media))
        if msg is None:
            return
        self.downloads.append((msg.id, off, ln))
        yield msg.bytes_at(off, ln)


def build(rows, contents):
    """(کلاینتِ کاربریِ آماده، لایهٔ تله‌تون) از داده‌های `channel_dataset`."""
    msgs = [Msg(r, contents.get((55, int(r["msg_id"])), b"")) for r in rows]
    tg = FakeTelethon(msgs)
    uc = UserClient(api_id=12345, api_hash="x" * 32, session_string="S")
    uc.client = tg
    return uc, tg


def run(coro):
    return asyncio.run(coro)


# ───────────────────────── probe ─────────────────────────
def test_probe_reads_total_and_last_id():
    ds = channel_dataset()
    uc, tg = build(ds["videos"], ds["contents"])
    info = run(uc.probe(55))
    assert info["total"] == tg.count and info["last_id"] == 150
    assert info["title"] == "کانالِ تست"
    assert uc.probed == [55]
    assert uc.ready is True


def test_probe_survives_broken_client():
    uc, _ = build([], {})
    uc.client = None
    info = run(uc.probe(55))          # نباید استثنا بدهد
    assert info == {"total": 0, "last_id": 0, "title": ""}


# ───────────────────────── iter_videos ─────────────────────────
def test_iter_videos_reads_full_history_and_shapes_rows():
    ds = channel_dataset()
    uc, tg = build(ds["videos"], ds["contents"])

    async def collect():
        return [r async for r in uc.iter_videos(55, min_id=0, wait_time=0.0)]

    rows = run(collect())
    assert [r["msg_id"] for r in rows] == [101, 102, 110, 111, 120, 121, 130, 131, 132, 140, 141, 142, 150]
    r = rows[0]
    assert r["file_name"] == "Black.Mirror.S01E01.1080p.WEB-DL.x265.mkv"
    assert r["size"] == 200 * MB and r["duration"] == 3600 and r["mime"] == "video/mp4"
    assert r["has_video"] == 1 and r["protected"] == 0
    assert r["caption"] == "قسمت اول فصل یک" and r["date"] > 0


def test_iter_videos_respects_min_id():
    ds = channel_dataset()
    uc, _ = build(ds["videos"], ds["contents"])

    async def collect():
        return [r["msg_id"] async for r in uc.iter_videos(55, min_id=131, wait_time=0.0)]

    assert run(collect()) == [132, 140, 141, 142, 150]


# ───────────────────────── هش ─────────────────────────
def test_chunk_plan_is_mtproto_aligned():
    plan = chunk_plan(250 * MB, CHUNK)
    assert len(plan) == 3                                     # سر + میانه + دُم
    assert plan[0] == (0, CHUNK)
    assert all(off % 4096 == 0 for off, _ in plan)
    assert all(ln <= CHUNK for _, ln in plan)
    assert plan[-1][0] + plan[-1][1] == 250 * MB
    assert chunk_plan(1000, CHUNK) == [(0, 1000)]             # فایلِ کوچک: یک تکه


def test_hash_batch_equal_content_equal_hash():
    ds = channel_dataset()
    uc, tg = build(ds["videos"], ds["contents"])
    out = run(uc.hash_batch(55, [(101, 200 * MB), (102, 200 * MB), (130, 50 * MB)]))
    h1, scope1 = out[101]
    assert len(h1) == 32 and "0+131072" in scope1
    assert out[102][0] == h1                                  # محتوای یکسان ⇒ هشِ یکسان
    assert out[130][0] != h1                                  # محتوای متفاوت ⇒ هشِ متفاوت
    # هر فایل دقیقاً ۳ تکه (سر/میانه/دُم) دانلود شده و هیچ‌کدام کلِ فایل نیست
    assert len(tg.downloads) == 9
    assert all(ln == CHUNK for _, _, ln in tg.downloads)
    assert uc.hash_batches == [3]
    assert uc.chunk_delay == 0.12


def test_hash_batch_missing_or_protected_is_empty_not_crash():
    ds = channel_dataset()
    uc, _ = build(ds["videos"], ds["contents"])
    out = run(uc.hash_batch(55, [(101, 200 * MB), (9999, 10 * MB)]))
    assert out[101][0] and out[9999] == ("", "")
    assert run(uc.hash_batch(55, [])) == {}


def test_hash_batch_hash_is_stable_across_calls():
    ds = channel_dataset()
    uc, _ = build(ds["videos"], ds["contents"])
    a = run(uc.hash_file(55, 130, 50 * MB))
    b = run(uc.hash_batch(55, [(130, 50 * MB)]))[130]
    assert a == b and a[0]                                  # hash_file و hash_batch سازگارند


def test_hash_file_reports_empty_when_download_blocked():
    ds = channel_dataset()
    uc, tg = build(ds["videos"], ds["contents"])
    uc.chunk_delay = 0.0
    tg._by_media = {}                                       # دانلود ناممکن (فایلِ محافظت‌شده)
    assert run(uc.hash_file(55, 101, 200 * MB)) == ("", "")


# ───────────────────────── اسکنِ واقعی با کلاینتِ واقعی ─────────────────────────
def test_scanner_with_real_user_client_end_to_end(tmp_path):
    """همان مسیرِ Railway: کلاینتِ کاربریِ واقعی + موتورِ اسکن ⇒ گروه‌بندیِ درست."""
    ds = channel_dataset()
    uc, _ = build(ds["videos"], ds["contents"])
    uc.chunk_delay = 0.0
    db = Db(str(tmp_path / "real.db"))
    cid = db.add_channel(55, "کانالِ تست", "testchan")
    chan = db.get_channel(cid)
    res = run(Scanner(db, uc, lambda: CFG).run(chan, full=True))

    assert res.status == "done" and res.files == 13 and res.found == 13
    assert res.hashed >= 2 and res.groups == 4
    groups = db.groups_of_scan(res.scan_id)
    by_reason = {g["id"]: g for g in groups}
    # گروهِ قطعی: ۱۰۱/۱۰۲ (هشِ محتوای یکسان)
    exact = [g for g in groups if g["exact"]]
    assert len(exact) == 1 and "هش" in exact[0]["reason"]
    assert sorted(m["msg_id"] for m in db.group_members(exact[0]["id"])) == [101, 102]
    # گروهِ ★★★ کارفرما: ۱۳۰/۱۳۱/۱۳۲ با حجم+زمانِ یکسان
    sizetime = [g for g in groups if "حجم و زمان" in g["reason"] and g["id"] != exact[0]["id"]]
    assert sizetime and sorted(m["msg_id"] for m in db.group_members(sizetime[0]["id"])) == [130, 131, 132]
    # قسمت‌های پشت‌سرهم نباید در یک گروه بیفتند
    for g in groups:
        ids = [m["msg_id"] for m in db.group_members(g["id"])]
        assert not ({140, 141, 142} <= set(ids))
    assert db.get_scan(res.scan_id)["files_found"] == 13
    assert len(by_reason) == 4
    db.close()


def test_scanner_reports_error_without_crashing_when_history_fails(tmp_path):
    ds = channel_dataset()
    uc, tg = build(ds["videos"], ds["contents"])
    tg.fail_iter = True
    db = Db(str(tmp_path / "err.db"))
    cid = db.add_channel(55, "کانالِ تست", "testchan")
    res = run(Scanner(db, uc, lambda: CFG).run(db.get_channel(cid), full=True))
    assert res.status == "error" and "ITER_FAIL" in res.error
    assert db.get_scan(res.scan_id)["status"] == "error"
    db.close()
