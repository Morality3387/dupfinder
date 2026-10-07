"""پوشِ کدِ محلی روی گیت‌هاب — برای پروژهٔ dupfinder (بدونِ نیاز به `git`).

چرا این فایل: روی این ماشین `git` نصب نیست و کلاینتِ Railway هم سشن ندارد؛ پس هم
بکاپِ گیت‌هاب و هم (از این پس) دیپلویِ Railway از راهِ همین مخزن انجام می‌شود.

قواعد:
  • فقط فایل‌های **سورس** پوش می‌شوند (فهرستِ پایین) — هیچ فایلِ رمز/سشن/دیتابیس.
  • توکن فقط از `/home/user/tokens.env` (خارجِ ریپو) خوانده می‌شود.
  • درختِ جدید روی درختِ فعلیِ `main` ساخته می‌شود؛ فقط فایل‌های تغییریافته blob تازه می‌گیرند.

استفاده:
    python3 dev/gh_push.py "پیامِ کامیت"
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = "baddarksss/dupfinder"
BRANCH = "main"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # /home/user/dupfinder
TOKENS = "/home/user/tokens.env"

# فایل‌هایی که پوش می‌شوند — **خودکار** از پوشه‌ها ساخته می‌شود تا هیچ فایلی جا نیفتد
# (درسِ گرفته‌شده: با فهرستِ دستی، `app/railway.py` در پوش جا افتاد).
TOP_FILES = [".env.example", ".gitignore", "Dockerfile", "README.fa.md", "README.md", "main.py",
             "pytest.ini", "railway.json", "requirements.txt"]
SCAN_DIRS = ["app", "dev", "tests"]


def _collect() -> list:
    out = list(TOP_FILES)
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            out.append("%s/%s" % (d, name))
    return out


INCLUDE = _collect()
# ⚠️ پوشهٔ `backup/` عمداً در این فهرست نیست: آن را خودِ ربات روی گیتهاب می‌نویسد
#    (فایلِ قفل‌شدهٔ پشتیبان + manifest) و پوشِ سورس نباید دستش بزند.


def token() -> str:
    for line in open(TOKENS, encoding="utf-8"):
        line = line.strip()
        if line.startswith("GH_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("GH_TOKEN پیدا نشد")


def api(path: str, *, method: str = "GET", payload: dict | None = None, tok: str = "",
        tries: int = 4) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + tok, "User-Agent": "dupfinder-push",
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    # گیتهاب گاهی 5xx می‌دهد (قطعیِ موقت)؛ چند تلاش با فاصلهٔ پله‌ای می‌کنیم تا پوشِ سورس معطل نماند.
    for attempt in range(max(1, int(tries))):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode(errors="replace")
            if e.code >= 500 and attempt + 1 < tries:
                time.sleep(2 + 3 * attempt)
                continue
            raise SystemExit("GitHub %s %s → %s: %s" % (method, path, e.code, body))
        except Exception as e:
            if attempt + 1 < tries:
                time.sleep(2 + 3 * attempt)
                continue
            raise SystemExit("GitHub %s %s → شبکه: %s" % (method, path, e))


def blob_sha(data: bytes) -> str:
    """sha1 گیت برای محتوا (پیشوندِ «blob <size>\\0») — تا فقط فایل‌های واقعاً تغییریافته پوش شوند."""
    head = b"blob %d\0" % len(data)
    return hashlib.sha1(head + data).hexdigest()


def main() -> int:
    msg = sys.argv[1] if len(sys.argv) > 1 else "sync"
    tok = token()
    ref = api("/repos/%s/git/ref/heads/%s" % (REPO, BRANCH), tok=tok)
    parent = ref["object"]["sha"]
    base_tree = api("/repos/%s/git/commits/%s" % (REPO, parent), tok=tok)["tree"]["sha"]
    cur = {x["path"]: x["sha"] for x in api(
        "/repos/%s/git/trees/%s?recursive=1" % (REPO, base_tree), tok=tok)["tree"] if x["type"] == "blob"}

    entries, pushed, skipped, missing = [], [], [], []
    for rel in INCLUDE:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            missing.append(rel)
            continue
        with open(p, "rb") as fh:
            data = fh.read()
        sha = blob_sha(data)
        if cur.get(rel) == sha:
            skipped.append(rel)
            continue
        blob = api("/repos/%s/git/blobs" % REPO, method="POST", tok=tok, payload={
            "content": base64.b64encode(data).decode(), "encoding": "base64"})
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        pushed.append(rel)

    if not entries:
        print("چیزی برای پوش نبود — همهٔ %d فایل هم‌اکنون روی گیت‌هاب هستند." % len(skipped))
        return 0

    tree = api("/repos/%s/git/trees" % REPO, method="POST", tok=tok,
               payload={"base_tree": base_tree, "tree": entries})
    commit = api("/repos/%s/git/commits" % REPO, method="POST", tok=tok, payload={
        "message": msg, "tree": tree["sha"], "parents": [parent]})
    api("/repos/%s/git/refs/heads/%s" % (REPO, BRANCH), method="PATCH", tok=tok,
        payload={"sha": commit["sha"], "force": False})
    print("✅ پوش شد: %s → %s" % (commit["sha"][:10], REPO))
    print("   فایل‌های تغییریافته (%d): %s" % (len(pushed), ", ".join(pushed)))
    if missing:
        print("   ⚠️ در ورک‌اسپیس نبود: %s" % ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
