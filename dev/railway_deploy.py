"""دیپلویِ dupfinder روی Railway — بدونِ نیاز به `git` یا سشنِ مرورگریِ CLI.

چرا این فایل: کلاینتِ رسمی `railway up` با «Project-Access-Token» کار نمی‌کند
(«Invalid RAILWAY_TOKEN») در حالی که همان توکن با هدرِ `Authorization: Bearer …`
به بکبوردِ Railway معتبر است. این اسکریپت همان کاری را می‌کند که `railway up`
می‌کند: یک تاربالِ gzip از پوشهٔ پروژه می‌سازد و به اندپوینتِ آپلودِ Railway
می‌فرستد، بعد وضعیتِ دیپلوی را تا پایان دنبال می‌کند.

  POST https://backboard.railway.com/project/{project}/environment/{env}/up
       ?serviceId=…&message=…
       Content-Type: application/gzip

استفاده:
    /home/user/.tools/venv/bin/python dev/railway_deploy.py            # آپلود + انتظار تا پایانِ بیلد
    /home/user/.tools/venv/bin/python dev/railway_deploy.py --no-wait   # فقط آپلود
    /home/user/.tools/venv/bin/python dev/railway_deploy.py --status    # فقط وضعیتِ آخرین دیپلوی

⚠️ رازها هرگز داخلِ تاربال نمی‌روند (`*.session`, `.env*`, `*.db`, `dev/_*` حذف می‌شوند).
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # /home/user/dupfinder
TOKEN_FILE = Path("/home/user/railway.env")            # طبقِ قرارداد: توکن فقط بیرونِ ریپو
PROJECT_ID = os.environ.get("RAILWAY_PROJECT_ID", "7c67892f-e44e-461a-9754-b000eb1f5408")
ENV_ID = os.environ.get("RAILWAY_ENV_ID", "b7ae7c03-0b61-414a-9e03-e7f099b8d5d5")
SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID", "24e07b24-9a72-48e5-8e88-c4227431d00f")
BACKBOARD = "https://backboard.railway.com"

# چیزهایی که هرگز نباید به‌عنوانِ کدِ سورس آپلود شوند
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", "env",
             "data", ".idea", ".vscode", ".mypy_cache", ".ruff_cache"}
SKIP_FILES = re.compile(r"(^\.env$|^\.env\.(?!example)|\*|\.session|\.db(-wal|-shm)?$|^\.DS_Store$|\.log$|"
                        r"^id_ed25519|^tokens\.env|^railway\.env)", re.I)
TERMINAL = {"SUCCESS", "FAILED", "CRASHED", "REMOVED", "SKIPPED"}


def token() -> str:
    for line in TOKEN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("RAILWAY_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("RAILWAY_TOKEN در %s پیدا نشد" % TOKEN_FILE)


def rev() -> str:
    m = re.search(r'REV\s*=\s*"([^"]+)"', (ROOT / "main.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def build_tarball() -> bytes:
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("_")]
            for name in filenames:
                p = Path(dirpath) / name
                rel = p.relative_to(ROOT)
                if any(part in SKIP_DIRS for part in rel.parts):
                    continue
                if SKIP_FILES.search(name) and name != ".env.example":
                    continue
                tar.add(p, arcname="./" + str(rel).replace(os.sep, "/"))
                count += 1
    data = buf.getvalue()
    print("📦 تاربال: %d فایل · %.1f KB" % (count, len(data) / 1024.0))
    return data


def gql(query: str) -> dict:
    req = urllib.request.Request(
        BACKBOARD + "/graphql/v2", data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "dupfinder-deploy",
                 "Authorization": "Bearer " + token()})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def latest_deployment() -> tuple[str, str]:
    d = gql('query { deployments(first: 1, input: {serviceId: "%s"}) { edges { node { id status } } } }' % SERVICE_ID)
    node = d["data"]["deployments"]["edges"][0]["node"]
    return node["id"], node["status"]


def upload() -> dict:
    url = ("%s/project/%s/environment/%s/up?serviceId=%s&message=%s"
           % (BACKBOARD, PROJECT_ID, ENV_ID, SERVICE_ID,
              urllib.parse.quote("dupfinder %s" % rev())))
    body = build_tarball()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + token(), "Content-Type": "application/gzip",
        "User-Agent": "dupfinder-deploy"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit("آپلود شکست خورد — HTTP %s: %s" % (e.code, e.read().decode(errors="replace")[:400]))


def wait(deployment_id: str, timeout_s: int = 900) -> str:
    t0, last = time.time(), ""
    while time.time() - t0 < timeout_s:
        st = gql('query { deployment(id: "%s") { status } }' % deployment_id)["data"]["deployment"]["status"]
        if st != last:
            print("   … %s  (+%ds)" % (st, int(time.time() - t0)))
            last = st
        if st in TERMINAL:
            return st
        time.sleep(10)
    return last or "UNKNOWN"


def scan_running(url: str = "https://dupfinder-production.up.railway.app/health") -> bool:
    """آیا همین حالا اسکنی در جریان است؟ (تا دیپلوی، اسکنِ کاربر را نصفه نکند)

    ⚠️ درسِ گرفته‌شده: یک‌بار دیپلوی وسطِ اسکنِ هشِ کامل انجام شد و اسکن از بین رفت.
    از این به بعد دیپلوی **قبل از هر کار** این را چک می‌کند و اگر اسکنی در جریان باشد
    کاری نمی‌کند (مگر با `--force`).
    """
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return bool(json.loads(r.read().decode()).get("scan_running"))
    except Exception:
        return False          # اگر سرور جواب نداد، جلوی دیپلوی را نمی‌گیریم


def main() -> int:
    args = set(sys.argv[1:])
    if "--check" in args:
        busy = scan_running()
        print("⏳ اسکن در جریان است ⇒ الان دیپلوی نکن." if busy else "✅ اسکنی در جریان نیست ⇒ دیپلوی بی‌خطر است.")
        return 0
    if "--status" in args:
        did, st = latest_deployment()
        print("آخرین دیپلوی: %s → %s" % (did, st))
        return 0
    if "--force" not in args and scan_running():
        print("🛑 همین حالا یک اسکن در جریان است — دیپلوی می‌تواند نصفه‌اش کند. "
              "اول اسکن تمام شود (یا برای عبورِ اجباری: --force).")
        return 3
    print("🚀 دیپلویِ dupfinder روی Railway — نسخهٔ %s" % rev())
    res = upload()
    did = res.get("deploymentId") or ""
    print("✅ آپلود شد. deploymentId=%s" % did)
    if res.get("logsUrl"):
        print("   لاگِ بیلد: %s" % res["logsUrl"])
    if res.get("deploymentDomain"):
        print("   دامنه: %s" % res["deploymentDomain"])
    if "--no-wait" in args or not did:
        return 0
    st = wait(did)
    print("🏁 وضعیتِ نهایی: %s" % st)
    return 0 if st == "SUCCESS" else 2


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (فقط برای quote در upload)
    raise SystemExit(main())
