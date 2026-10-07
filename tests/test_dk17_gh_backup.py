"""تست‌های DK-17 — پشتیبانِ گیتهاب: پوشهٔ `backup/` در مخزن، خواندن در هر استارت، نوشتن در همان اکانت.

خواستهٔ کاربر: «برای محکم‌کاری بکاپ در گیتهاب آپلود شود؛ در قسمتِ سورس یک پوشهٔ backup باشد؛
هر دیپلوی از آن بخواند و برای نوشتن هم در همان اکانتِ اصلی آپدیت کند — تا بعد از هر دیپلوی
لازم نباشد کانال‌ها و تنظیمات را دوباره وارد کنم.»

نکتهٔ امنیتی که تست هم می‌کند: مخزنِ سورس **عمومی** است، پس فایلِ پشتیبان باید **قفل‌شده**
برود و با رمزِ غلط/فایلِ دست‌کاری‌شده باز نشود.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import gh_backup as G                        # noqa: E402
from tests.test_bot_flow import CHAT, Env             # noqa: E402

KEY = "رمزِ-تستِ-طولانی-۱۲۳"
REPO = "baddarksss/dupfinder"


class FakeGitHub:
    """مخزنِ گیتهابِ ساختگیِ درون‌حافظه‌ای (transport برای `G.GitHub`)."""

    def __init__(self):
        self.files = {}          # "backup/latest.bin" ⇒ bytes
        self.commits = []        # پیام‌های کامیت
        self.puts = 0

    # امضای transport در app.gh_backup: (method, path, payload, accept)
    def __call__(self, method, path, payload, accept="application/vnd.github+json"):
        name = path.split("/contents/", 1)[-1]
        if method == "GET":
            if name not in self.files:
                return None
            data = self.files[name]
            if "raw" in str(accept):
                return {"raw": data}
            return {"sha": "sha-" + name, "content": data.decode("latin-1"), "size": len(data)}
        if method == "PUT":
            self.puts += 1
            if allow_put is not None and not allow_put():
                raise G.GitHubError("گیتهاب PUT → 403: Forbidden")
            self.files[name] = payload["content"].encode() if isinstance(payload["content"], str) else b""
            self.files[name] = _b64decode(payload["content"])
            self.commits.append(str(payload.get("message") or ""))
            return {"content": {"sha": "sha-new-%d" % self.puts}}
        return None


allow_put = None             # قلاب: تست‌های خطا می‌توانند نوشتن را ببندند


def _b64decode(s):
    import base64
    return base64.b64decode(s)


# ───────────────────────────── ابزار ─────────────────────────────

def _env(d, fake, **kw):
    e = Env(Path(d), **kw)
    e.text("/start")
    e.bot.gh_transport = fake
    e.settings.gh_backup_repo = REPO
    e.settings.gh_backup_token = "gh-token-test"
    e.settings.backup_key = KEY
    return e


def _scan(e, **kw):
    cid = e.add_channel()
    e.settings.hash_scope, e.settings.hash_mode = "full", "all"
    e.tap("scan:full:%d" % cid)
    e.wait_scan()
    return cid


def _blob(fake):
    return fake.files["%s/latest.bin" % "backup"]


# ───────────────────────────── ① رمزنگاری ─────────────────────────────

def test_seal_unseal_roundtrip_and_failures():
    data = ("نامِ فیلم و کپشن " * 900).encode()
    blob = G.seal(data, KEY)
    assert blob.startswith(G.MAGIC) and len(blob) > len(data)
    assert G.unseal(blob, KEY) == data
    for bad in ("", "غلط"):
        try:
            G.unseal(blob, bad)
            raise AssertionError("با رمزِ '%s' نباید باز شود" % bad)
        except ValueError:
            pass
    tampered = bytearray(blob)
    tampered[40] ^= 0b1
    try:
        G.unseal(bytes(tampered), KEY)
        raise AssertionError("فایلِ دست‌کاری‌شده نباید باز شود")
    except ValueError:
        pass


# ───────────────────────────── ② آپلود به گیتهاب ─────────────────────────────

def test_push_uploads_encrypted_backup_into_backup_folder():
    """دکمهٔ «⬆️ فرستادن به گیتهاب» ⇒ `backup/latest.bin` قفل‌شده + manifest."""
    with tempfile.TemporaryDirectory() as d:
        fake = FakeGitHub()
        e = _env(d, fake)
        cid = _scan(e)
        e.tap("bk:ghup")
        assert "backup/latest.bin" in fake.files and "backup/manifest.json" in fake.files
        raw = fake.files["backup/latest.bin"]
        assert raw.startswith(G.MAGIC)
        title = str(e.db.get_channel(cid)["title"]).encode("utf-8")
        assert title not in raw, "نامِ کانال نباید به‌صورتِ خام در فایلِ عمومی باشد"
        assert b"file_name" not in raw[:200]
        m = json.loads(fake.files["backup/manifest.json"].decode("utf-8"))
        assert m["channels"] == 1 and m["files"] == e.db.count_files(cid)
        assert m["hashed"] == e.db.count_hashed_scope() and m["encrypted"] is True
        assert fake.commits and "backup:" in fake.commits[-1]
        assert "پشتیبان روی گیتهاب رفت" in e.last_view()
        # لاگِ درونِ ربات هم برای صفحهٔ پشتیبان ذخیره می‌شود
        assert e.db.kv_get("backup:gh:summary") and e.db.kv_get("backup:gh:at")


def test_push_refuses_without_password_or_token():
    """بی‌رمز (یا بی‌توکن) هیچ‌چیز آپلود نمی‌شود و دلیلش روشن گفته می‌شود."""
    with tempfile.TemporaryDirectory() as d:
        fake = FakeGitHub()
        e = _env(d, fake)
        _scan(e)
        fake.files.clear(); fake.puts = 0          # آپلودِ خودکارِ پایانِ اسکن را کنار می‌گذاریم
        e.settings.backup_key = ""
        e.db.kv_set("backup:key", "")
        e.tap("bk:ghup")
        assert fake.files == {}, "بی‌رمز نباید آپلود شود"
        assert "رمز" in e.last_view()

        e.settings.backup_key = KEY
        e.settings.gh_backup_token = ""
        e.db.kv_set("backup:gh_token", "")
        e.tap("bk:ghup")
        assert fake.files == {}, "بی‌توکن نباید آپلود شود"
        assert "توکن" in e.last_view()


def test_push_reports_github_error_kindly():
    """اگر گیتهاب ۴۰۳ بدهد، پیامِ خطا در ربات می‌آید (بی‌کرش)."""
    global allow_put
    with tempfile.TemporaryDirectory() as d:
        fake = FakeGitHub()
        e = _env(d, fake)
        _scan(e)
        fake.files.clear(); fake.puts = 0
        allow_put = lambda: False
        try:
            e.tap("bk:ghup")
        finally:
            allow_put = None
        assert fake.files == {}
        assert "❌" in e.last_view() and "403" in e.last_view()


# ───────────────────────────── ③ خواندن روی نصبِ تازه ─────────────────────────────

def test_pull_restores_everything_into_a_fresh_install():
    """همان خواستهٔ اصلی: روی نصبِ تازه، کانال‌ها + هش‌ها + تنظیمات از گیتهاب برمی‌گردد."""
    fake = FakeGitHub()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        cid = _scan(e)
        e.db.kv_set("setting:th_name_ratio", "0.93")
        e.db.kv_set("session_string", "SECRET")          # راز نباید برود
        e.tap("bk:ghup")
        n_hashed = e.db.count_hashed_scope()

    with tempfile.TemporaryDirectory() as d2:
        e2 = _env(d2, fake)
        e2.settings.backup_key = "غلط"                    # اول رمزِ اشتباه ⇒ باید خطا بدهد
        e2.tap("bk:ghdown")
        e2.tap("bk:ghyes")
        assert "رمز" in e2.last_view() and e2.db.stats()["channels"] == 0

        e2.settings.backup_key = KEY
        e2.db.kv_set("setting:th_name_ratio", "")         # تنظیمِ محلی خالی ⇒ از پشتیبان پر شود
        e2.tap("bk:ghdown")
        assert "خواندنِ پشتیبان از گیتهاب" in e2.last_view()
        e2.tap("bk:ghyes")
        assert "پشتیبانِ گیتهاب خوانده شد" in e2.last_view()
        assert e2.db.stats()["channels"] == 1
        assert e2.db.count_hashed_scope() == n_hashed, "همهٔ هش‌ها باید برگردند"
        assert str(e2.db.kv_get("setting:th_name_ratio")) == "0.93", "تنظیماتِ تشخیص هم برگشت"
        assert e2.db.kv_get("session_string") is None, "رازها نباید از پشتیبان بیایند"


def test_pull_rejects_tampered_file():
    """اگر فایل روی مخزن دست‌کاری شود (اثرِ انگشت نخواند) خوانده نمی‌شود."""
    fake = FakeGitHub()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        _scan(e)
        e.tap("bk:ghup")
    raw = bytearray(fake.files["backup/latest.bin"])
    raw[-5] ^= 0b1
    fake.files["backup/latest.bin"] = bytes(raw)
    with tempfile.TemporaryDirectory() as d2:
        e2 = _env(d2, fake)
        e2.tap("bk:ghdown")
        e2.tap("bk:ghyes")
        assert "ناقص/تغییرکرده" in e2.last_view() and e2.db.stats()["channels"] == 0


# ───────────────────────────── ④ استارت = خواندنِ خودکار ─────────────────────────────

def test_startup_auto_restore_when_database_is_empty():
    """دیتابیسِ خالی (اکانتِ تازه) ⇒ ربات خودش از گیتهاب پر می‌شود و خبر می‌دهد."""
    fake = FakeGitHub()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        cid = _scan(e)
        e.db.kv_set("setting:min_caption_len", "7")
        e.tap("bk:ghup")
        n_hashed = e.db.count_hashed_scope()
        before = e.api.sent[-1]["message_id"] if e.api.sent else 0

    with tempfile.TemporaryDirectory() as d2:
        e2 = _env(d2, fake)
        n = asyncio.new_event_loop().run_until_complete(e2.bot.restore_from_github_if_empty())
        assert n == 1, "باید یک کانال از گیتهاب برگردد"
        assert e2.db.stats()["channels"] == 1 and e2.db.count_hashed_scope() == n_hashed
        assert str(e2.db.kv_get("setting:min_caption_len")) == "7"
        txt = e2.api.sent[-1]["text"]
        assert "از پشتیبانِ گیتهاب پر شد" in txt and "کانال" in txt
        assert e2.db.kv_get("backup:gh:at")


def test_startup_restore_skips_when_database_has_data():
    """اگر دیتابیس داده دارد، استارت **هیچ‌چیز** را خودکار بازنویسی نمی‌کند."""
    fake = FakeGitHub()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        _scan(e)
        e.tap("bk:ghup")
    with tempfile.TemporaryDirectory() as d2:
        e2 = _env(d2, fake)
        cid2 = _scan(e2)                                   # دیتابیسِ خودش داده دارد
        e2.db.conn.execute("UPDATE files SET file_name='اسمِ محلی' WHERE channel_id=?", (cid2,))
        e2.db.conn.commit()
        n = asyncio.new_event_loop().run_until_complete(e2.bot.restore_from_github_if_empty())
        assert n == 0
        names = [str(f.get("file_name")) for f in e2.db.files_of_channel(cid2)]
        assert "اسمِ محلی" in names, "داده‌های محلی نباید دست بخورد"


def test_startup_without_key_tells_the_owner_what_to_do():
    """دیتابیسِ خالی + پشتیبانِ موجود + بی‌رمز ⇒ پیامِ راهنما (نه سکوت)."""
    fake = FakeGitHub()
    with tempfile.TemporaryDirectory() as d:
        e = _env(d, fake)
        _scan(e)
        e.tap("bk:ghup")
    with tempfile.TemporaryDirectory() as d2:
        e2 = _env(d2, fake)
        e2.settings.backup_key = ""
        e2.db.kv_set("backup:key", "")
        n = asyncio.new_event_loop().run_until_complete(e2.bot.restore_from_github_if_empty())
        assert n == 0
        assert "دیتابیسِ این سرور خالی است" in e2.api.sent[-1]["text"]
        assert "bk:menu" in json.dumps(e2.api.sent[-1].get("kb") or {}, ensure_ascii=False)


# ───────────────────────────── ⑤ خودکارِ پس از اسکن ─────────────────────────────

def test_auto_push_after_scan_is_debounced_and_change_aware():
    """پس از اسکن خودکار آپلود می‌شود؛ پشت‌سرهم کامیتِ بی‌فایده نمی‌سازد؛ با هشِ تازه، دوباره می‌سازد."""
    global allow_put
    with tempfile.TemporaryDirectory() as d:
        fake = FakeGitHub()
        e = _env(d, fake)
        cid = _scan(e)
        assert fake.puts == 2, "پایانِ اسکن باید پشتیبان را بفرستد (فایل + manifest)"
        # اسکنِ دوبارهٔ بدونِ تغییرِ هش ⇒ کامیتِ تازه‌ای نباید بسازد
        e.tap("scan:full:%d" % cid)
        e.wait_scan()
        assert fake.puts == 2, "هش‌ها عوض نشده‌اند ⇒ آپلودِ بی‌فایده ممنوع"
        # تغییرِ واقعی در «مجموعهٔ هش‌ها» ⇒ باید آپلود شود (سِگنِچر عوض شده)
        e.db.conn.execute("UPDATE files SET content_hash=content_hash||'-NEW' "
                          "WHERE channel_id=? AND content_hash<>''", (cid,))
        e.db.conn.commit()
        e.db.kv_set("backup:gh:ts", 0)              # فاصلهٔ ضدِ کامیتِ پشت‌سرهم را رد می‌کنیم
        loop = asyncio.new_event_loop()
        assert loop.run_until_complete(e.bot._gh_auto_push()) is True
        assert fake.puts == 4, "هشِ تازه ⇒ آپلودِ تازه"
        assert loop.run_until_complete(e.bot._gh_auto_push()) is False, "بی‌تغییر ⇒ کامیتِ تازه نه"
        # خاموش‌کردنِ خودکار
        e.tap("bk:ghauto")
        assert e.bot._gh_auto() is False
        e.db.conn.execute("UPDATE files SET content_hash='', hash_scope='' WHERE channel_id=?", (cid,))
        e.db.conn.commit()
        e.db.conn.execute("UPDATE files SET content_hash=content_hash||'-2' "
                          "WHERE channel_id=? AND content_hash<>''", (cid,))
        e.db.conn.commit()
        e.db.kv_set("backup:gh:ts", 0)
        assert asyncio.new_event_loop().run_until_complete(e.bot._gh_auto_push()) is False
        assert fake.puts == 4, "با خاموشیِ خودکار نباید چیزی آپلود شود"


def test_menu_shows_github_status_and_all_buttons():
    with tempfile.TemporaryDirectory() as d:
        fake = FakeGitHub()
        e = _env(d, fake)
        _scan(e)
        e.tap("bk:menu")
        txt = e.last_view()
        assert "🗄 گیتهاب" in txt and "backup" in txt
        datas = e.view_datas()
        for cb in ("bk:ghup", "bk:ghdown", "bk:ghinfo", "bk:ghauto", "bk:key", "bk:ghset", "bk:gttok"):
            assert cb in datas, "دکمهٔ %s نیست" % cb
        e.tap("bk:ghinfo")
        assert "وضعیتِ گیتهاب" in e.last_view() and "کانال" in e.last_view()


def test_repo_and_token_prompts_store_values_and_delete_token_message():
    """🗄 تنظیمِ مقصد · 🔐 توکنِ گیتهاب (پیامِ توکن از چت پاک می‌شود)."""
    with tempfile.TemporaryDirectory() as d:
        fake = FakeGitHub()
        e = _env(d, fake)
        e.tap("bk:ghset")
        e.text("baddarksss/dupfinder backup")
        assert e.db.kv_get("backup:gh_repo") == "baddarksss/dupfinder"
        assert e.db.kv_get("backup:gh_path") == "backup"

        e.tap("bk:gttok")
        e.text("ghp_" + "x" * 30, mid=99)
        assert str(e.db.kv_get("backup:gh_token")).startswith("ghp_")
        assert any(x["message_id"] == 99 for x in e.api.deletes), "پیامِ توکن باید پاک شود"

        # پاک‌کردنِ توکنِ ذخیره‌شده
        e.tap("bk:gttok")
        e.text("پاک")
        assert not e.db.kv_get("backup:gh_token")

        e.tap("bk:key")
        e.text("یک-رمزِ-تازه-و-بلند")
        assert e.db.kv_get("backup:key") == "یک-رمزِ-تازه-و-بلند"
        assert "رمزِ پشتیبان ثبت شد" in e.last_view()
