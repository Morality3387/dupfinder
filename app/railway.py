"""🚂 اطلاعاتِ حسابِ Railway — اعتبار، مصرف و «چند روز مانده» (DK-18).

خواستهٔ کاربر: «یه فیچر دیگه هم اضافه کن که توکنِ ریلوی رو استفاده کنه و تو صفحهٔ اصلی
کردیت و روزِ باقی‌ماندهٔ ریلوی رو نشون بده».

چیزی که خوانده می‌شود (تنها خواندن — هیچ‌وقت چیزی روی حساب تغییر نمی‌کند):

    me { email, workspaces { name, plan,
         customer { creditBalance, currentUsage, remainingUsageCreditBalance,
                    trialDaysRemaining, isTrialing, state,
                    billingPeriod { start, end } } } }

«اعتبارِ باقی‌مانده» همان عددی است که پنلِ خودِ Railway نشان می‌دهد
(`remainingUsageCreditBalance` = اعتبارِ کل − مصرفِ این دوره)؛ پس کاربر دقیقاً
همان چیزی را می‌بیند که در داشبورد می‌بیند.

همان توکنِ «Project Access Token» که برای دیپلوی داریم با هدرِ
`Authorization: Bearer …` برای همین پرس‌وجو هم کار می‌کند (تست‌شده).

نکتهٔ مهم: اگر توکن مالکِ پروژه باشد، پاسخ فقط همان ورک‌اسپیس را برمی‌گرداند؛ پس اگر
`project_id` بدهیم و در فهرست نباشد، باز هم اولین ورک‌اسپیس را خلاصه می‌کنیم.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("dup.railway")

API = "https://backboard.railway.com/graphql/v2"

QUERY = """query {
  me {
    id
    email
    workspaces {
      id
      name
      plan
      customer {
        id
        creditBalance
        currentUsage
        remainingUsageCreditBalance
        trialDaysRemaining
        isTrialing
        state
        billingPeriod { start end }
      }
    }
  }
}"""


class RailwayError(Exception):
    """خطای گفتگو با Railway (توکن/شبکه/ساختارِ پاسخ)."""


def _as_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _parse_dt(text: Any) -> Optional[float]:
    """`2026-10-07T23:59:59.999Z` ⇒ timestamp (برای شمردنِ روزهای ماندهٔ دوره)."""
    s = str(text or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def remaining_of(cust: Dict[str, Any], credit: float, usage: float) -> float:
    """اعتبارِ باقی‌مانده — همان عددی که پنلِ Railway نشان می‌دهد.

    اول از خودِ Railway می‌پرسیم (`remainingUsageCreditBalance`)؛ اگر نبود، مثلِ پنل
    خودمان «کل − مصرف» را حساب می‌کنیم. هیچ‌وقت زیرِ صفر نمی‌رود.
    """
    raw = (cust or {}).get("remainingUsageCreditBalance")
    if raw is None:
        return max(0.0, _as_float(credit) - _as_float(usage))
    return max(0.0, _as_float(raw))


def used_pct(info: Dict[str, Any]) -> float:
    """چند درصد از اعتبار مصرف شده (۰ تا ۱۰۰)."""
    credit = _as_float((info or {}).get("credit"))
    if credit <= 0:
        return 0.0
    return max(0.0, min(100.0, (_as_float((info or {}).get("usage")) / credit) * 100.0))


def bar_text(pct: float, width: int = 10) -> str:
    """نوارِ کوچکِ مصرف (مثل پنلِ Railway): «▰▰▱▱▱▱▱▱▱▱»."""
    try:
        p = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        p = 0.0
    n = int(width)
    filled = int(round(p / 100.0 * n))
    if p > 0 and filled == 0:            # مصرف شروع شده ⇒ حداقل یک خانه، تا گمراه نکند
        filled = 1
    if p < 100 and filled == n:          # هنوز کامل نشده ⇒ حداقل یک خانه خالی بماند
        filled = n - 1
    return "▰" * filled + "▱" * max(0, n - filled)


def summarise(raw: Dict[str, Any], *, project_id: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    """پاسخِ خامِ Railway ⇒ دیکشنریِ ساده برای نمایش در ربات."""
    now = float(now if now is not None else time.time())
    me = (raw or {}).get("me") or {}
    spaces = list(me.get("workspaces") or [])
    chosen: Dict[str, Any] = {}
    for w in spaces:
        if project_id and str(w.get("id") or "") == str(project_id):
            chosen = w
            break
    if not chosen:
        chosen = (spaces[0] if spaces else {}) or {}
    cust = dict(chosen.get("customer") or {})
    period = dict(cust.get("billingPeriod") or {})
    end_ts = _parse_dt(period.get("end"))
    start_ts = _parse_dt(period.get("start"))
    trial_days = _as_int(cust.get("trialDaysRemaining"))
    is_trial = bool(cust.get("isTrialing"))
    credit = round(_as_float(cust.get("creditBalance")), 2)
    usage = round(_as_float(cust.get("currentUsage")), 4)
    left = round(remaining_of(cust, credit, usage), 2)
    days_left = trial_days if is_trial else (
        max(0, int((end_ts - now) // 86400)) if end_ts else 0)
    return {
        "ok": True,
        "fetched_at": int(now),
        "email": str(me.get("email") or ""),
        "workspace": str(chosen.get("name") or ""),
        "workspace_id": str(chosen.get("id") or ""),
        "plan": str(chosen.get("plan") or "").upper(),
        "credit": credit,          # اعتبارِ کل (همان که ریخته‌اند)
        "usage": usage,            # مصرفِ این دوره
        "credit_left": left,       # 💳 باقی‌مانده — همان عددی که پنلِ ریلوی نشان می‌دهد
        "is_trial": is_trial,
        "trial_days": trial_days,
        "days_left": int(days_left),
        "period_end": int(end_ts) if end_ts else 0,
        "period_start": int(start_ts) if start_ts else 0,
        "state": str(cust.get("state") or ""),
    }


def warn_text(info: Dict[str, Any], *, low_days: int = 5, low_credit: float = 0.5) -> str:
    """هشدارِ کوتاه وقتی اعتبار یا روزها ته کشیده (برای نشان‌دادن در صفحهٔ اصلی)."""
    msgs = []
    if int(info.get("days_left") or 0) <= int(low_days):
        msgs.append("فقط %d روز مانده" % int(info.get("days_left") or 0))
    left = info.get("credit_left")
    if left is None:                 # سازگاری با فراخوانی‌های قدیمی‌تر
        left = _as_float(info.get("credit")) - _as_float(info.get("usage"))
    if _as_float(left) <= float(low_credit):
        msgs.append("اعتبار تقریباً تمام است")
    return " · ".join(msgs)


class Railway:
    """کلاینتِ کوچکِ Railway (فقط `me`). `transport` برای تست تزریق می‌شود."""

    def __init__(self, token: str = "", *, project_id: str = "", api: str = API,
                 timeout: float = 45.0,
                 transport: Optional[Callable[[str, dict], Any]] = None):
        self.token = str(token or "").strip()
        self.project_id = str(project_id or "").strip()
        self.api = api
        self.timeout = float(timeout)
        self.transport = transport

    def configured(self) -> bool:
        return bool(self.token)

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.transport is not None:
            return self.transport(self.api, body)
        req = urllib.request.Request(
            self.api, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": "Bearer " + self.token, "User-Agent": "dupfinder-railway",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body_txt = e.read()[:300].decode(errors="replace")
            if e.code in (401, 403):
                raise RailwayError("توکنِ Railway پذیرفته نشد (%s) — یک توکنِ تازه بسازید." % e.code)
            raise RailwayError("Railway → %s: %s" % (e.code, body_txt))
        except Exception as e:
            raise RailwayError("ارتباط با Railway نشد: %s" % e)

    async def fetch(self) -> Dict[str, Any]:
        """اطلاعاتِ حساب (در تردِ جدا ⇒ حلقهٔ رویدادِ ربات قفل نمی‌شود)."""
        if not self.configured():
            raise RailwayError("توکنِ Railway تنظیم نشده است.")
        raw = await asyncio.to_thread(self._post, {"query": QUERY})
        if not isinstance(raw, dict):
            raise RailwayError("پاسخِ Railway قابلِ خواندن نبود.")
        if raw.get("errors"):
            msg = str(((raw.get("errors") or [{}])[0] or {}).get("message") or "خطای نامعلوم")
            raise RailwayError("Railway: %s" % msg)
        data = raw.get("data") or {}
        if not (data.get("me") or {}).get("workspaces"):
            raise RailwayError("این توکن به هیچ ورک‌اسپیسی دسترسی ندارد.")
        return summarise(data, project_id=self.project_id)
