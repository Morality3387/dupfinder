"""رباتِ تلگرام: منوها، جادوگرِ افزودنِ کانال، اسکن با نوارِ درصد، گزارش و فوروارد."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import preview as P
from . import report as R
from .config import LABELS, Settings
from .scanner import Progress, ScanResult, Scanner
from .tg_api import TgError, esc
from .user_client import looks_like_phone, norm_digits, norm_phone

log = logging.getLogger("dup.bot")

HELP_TEXT = """🤖 <b>رباتِ پیدا کردنِ فیلم‌های تکراریِ کانال</b>

<b>کارِ ربات:</b> کانال‌های شما را می‌خواند، همهٔ ویدیوها را ایندکس می‌کند و تکراری‌ها را با سه اولویت پیدا می‌کند:
 ۱) <b>نامِ فایل</b> — بیشترین شباهت را اول می‌بیند
 ۲) <b>کپشن</b> — متنِ پستِ ویدیو
 ۳) <b>حجم + زمانِ ویدیو</b> — مثلِ «دو فایلِ ۵۰ مگ و ۱ دقیقه» (تمرکزِ اصلی روی همین حالت)
➕ <b>هشِ محتوا</b> (اثرِ انگشتِ خودِ فایل) برای تأییدِ قطعی — با دانلودِ ۳ تکهٔ کوچک، نه کلِ فایل.

<b>گام‌به‌گام:</b>
۱) «📡 کانال‌های من» ← «➕ افزودنِ کانال» ← یوزرنیم/لینک بفرستید یا یک پست از کانال برایم <b>فوروارد</b> کنید (بات باید در کانال ادمین باشد).
۲) روی نامِ کانال بزنید ← «🔍 اسکن کامل».
۳) نوارِ درصد، تعدادِ پیام‌ها و فایل‌های پیداشده را زنده می‌بینید. هر وقت خواستید «⏹ توقف و کنسل».
۴) نتیجه: گروه‌های تکراری با دلیلِ تشخیص؛ هر گروه را با <b>فوروارد</b> به همین چت می‌فرستم تا با یک کلیک بپَرید روی همان پستِ کانال و تصمیم بگیرید.

⚠️ <b>ربات هیچ‌چیز را پاک/ویرایش نمی‌کند</b> — فقط می‌خواند و فوروارد می‌کند. تصمیمِ پاک‌کردن کاملاً با شماست.

🩺 <b>چه دسترسی‌ای لازم است؟</b> (پاسخِ کوتاه: «اکانت لازم نیست ادمین باشد»)
• <b>اسکنِ کاملِ تاریخچه</b> ⇒ فقط <b>حسابِ کاربری</b> لازم است و آن هم فقط باید <b>عضوِ کانال</b> باشد
(ادمین‌بودن <b>لازم نیست</b>)؛ برای کانالِ <b>عمومی</b> حتی عضویت هم لازم نیست.
• <b>ربات</b> برای اسکن لازم نیست ادمین باشد. ادمین‌بودنِ ربات سه چیز می‌دهد: دکمهٔ
«➕ ادمین‌کردنِ ربات»، خواندنِ نامِ کانال از خودِ تلگرام، و فورواردِ نتیجه با خودِ ربات
(اگر ربات نباشد، فوروارد با حسابِ کاربری انجام می‌شود).
• اگر نه ربات ادمین باشد و نه حسابِ کاربری دسترسی داشته باشد، هیچ راهی برای خواندنِ
تاریخچهٔ کانال نیست (Bot API چنین امکانی ندارد) — دو راه‌حل: ربات را ادمین کنید + حساب را
عضو کنید، یا پست‌های قدیمی را در یک <b>کانالِ آرشیو</b> فوروارد کنید و همان را اسکن کنیم.
• 📡 <b>نامِ کانال:</b> در فهرست همیشه نام دیده می‌شود. اگر نام خوانده نشد، از کارتِ کانال
«✏️ نامِ کانال را دستی بگذار» را بزنید یا یک <b>پستِ همان کانال</b> را برایم فوروارد کنید.
• دکمهٔ «🩺 دسترسی‌های لازم» در کارتِ هر کانال، وضعیتِ واقعی را نشان می‌دهد.

🩺 <b>چه دسترسی‌ای لازم است؟</b> (پاسخِ کوتاه: «اکانت لازم نیست ادمین باشد»)
• <b>اسکنِ کاملِ تاریخچه</b> ⇒ فقط <b>حسابِ کاربری</b> لازم است و آن هم فقط باید <b>عضوِ کانال</b> باشد
(ادمین‌بودن <b>لازم نیست</b>)؛ برای کانالِ <b>عمومی</b> حتی عضویت هم لازم نیست.
• <b>ربات</b> برای اسکن لازم نیست ادمین باشد. ادمین‌بودنِ ربات سه چیز می‌دهد: دکمهٔ
«➕ ادمین‌کردنِ ربات»، خواندنِ نامِ کانال از خودِ تلگرام، و فورواردِ نتیجه با خودِ ربات
(اگر ربات نباشد، فوروارد با حسابِ کاربری انجام می‌شود).
• اگر نه ربات ادمین باشد و نه حسابِ کاربری دسترسی داشته باشد، هیچ راهی برای خواندنِ
تاریخچهٔ کانال نیست (Bot API چنین امکانی ندارد) — دو راه‌حل: ربات را ادمین کنید + حساب را
عضو کنید، یا پست‌های قدیمی را در یک <b>کانالِ آرشیو</b> فوروارد کنید و همان را اسکن کنیم.
• 📡 <b>نامِ کانال:</b> در فهرست همیشه نام دیده می‌شود. اگر نام خوانده نشد، از کارتِ کانال
«✏️ نامِ کانال را دستی بگذار» را بزنید یا یک <b>پستِ همان کانال</b> را برایم فوروارد کنید.
• دکمهٔ «🩺 دسترسی‌های لازم» در کارتِ هر کانال، وضعیتِ واقعی را نشان می‌دهد.

👥 <b>ادمین‌های ربات:</b> مالک می‌تواند چند نفر را ادمین کند تا با ربات کار کنند
(اسکن، دیدنِ نتیجه، فوروارد). «👥 ادمین‌های ربات» ← «➕ افزودنِ ادمین» و فرستادنِ <b>شناسهٔ عددی</b>
یا یک <b>پیامِ فورواردشده از آن شخص</b>؛ دستورِ سریع: <code>/addadmin 123456789</code> ·
حذف: <code>/deladmin 123456789</code> · فهرست: <code>/admins</code>.
ادمین‌ها «تنظیمات»، اسکن، گزارش و فوروارد را دارند؛ فقط «حسابِ کاربری» (سشنِ تلگرامِ مالک)،
«مدیریتِ ادمین‌ها» و «حذفِ کانال از فهرست» در دستِ مالک است.

⚙️ <b>تنظیمات:</b> از منوی اصلی («⚙️ تنظیمات») یا دستورِ <code>/settings</code>. نمی‌دانید هر گزینه
چیست؟ روی همان گزینه بزنید تا <b>توضیحِ کاملِ فارسی</b> + مقدارهای پیشنهادی بیاید، یا «❓ هر گزینه یعنی چه؟»
را بزنید (یا <code>/settings راهنما</code>). مقدارها با یک کلیک عوض می‌شوند. تغییرِ متنی:
<code>/set کلید مقدار</code> — مثلاً <code>/set hash_scope full</code> · <code>/set گروه‌بندی سخت‌گیرانه</code>.
مقدارهای فارسی هم قبول است («کامل»، «همه»، «خاموش/روشن») و ارقامِ فارسی («۰.۶») هم کار می‌کند.

📡 <b>نامِ کانال‌ها:</b> در فهرست همیشه <b>نام</b> دیده می‌شود؛ اگر نامی از تلگرام خوانده نشده باشد
دکمهٔ «🔄 تلاشِ دوباره برای نامِ کانال‌ها» آن را تازه می‌کند.

🔎 <b>دربارهٔ دیدنِ تاریخچهٔ کامل:</b> ربات‌های معمولی (Bot API) از پست‌های <b>قبل از ادمین‌شدن‌شان</b> هیچ اطلاعی ندارند؛ در گروه‌ها هم فقط پیام‌های بعد از اضافه‌شدن. برای «<b>کلِ تاریخچه</b>» باید یک <b>حسابِ کاربری</b> وصل شود (همان حسابِ ادمینِ کانال یا یک اکانتِ مخصوصِ کار) — با دستورِ «🔑 اتصالِ حسابِ کاربری». آن‌وقت ربات از اولین پستِ کانال تا آخرین را می‌بیند. راهِ جایگزین اگر حساب نمی‌دهید: پست‌های قدیمی را در یک کانالِ آرشیو فوروارد کنید و همان را اسکن کنیم.
"""


# ═══════════ نرمال‌سازیِ مقدارهای تنظیمات (پذیرشِ فارسی، ارقامِ فارسی، مترادف‌ها) ═══════════
# ═══════════ توضیحِ فارسیِ هر تنظیم (برای اینکه معلوم باشد هر دکمه چه کار می‌کند) ═══════════
# ساختارِ هر مورد:  icon · title (برچسبِ کوتاهِ دکمه) · what (این گزینه چیست) · tip (نکته)
#   options = مقدارهای «گزینه‌ای»: (مقدارِ ذخیره‌شده، برچسب، توضیحِ یک‌خطی)
#   presets = مقدارهای عددیِ پیشنهادی: (مقدار، برچسب، توضیحِ یک‌خطی)
SETTING_INFO: Dict[str, Dict[str, Any]] = {
    "hash_mode": {
        "icon": "🔑", "title": "حالتِ هش",
        "what": "برای تأییدِ قطعیِ «این دو فایل یکی‌اند»، ربات چند تکهٔ کوچک از فایل را دانلود می‌کند و "
                "«اثرِ انگشت» (هش) می‌سازد. این گزینه می‌گوید برای کدام فایل‌ها این کار انجام شود.",
        "options": [("off", "خاموش", "هیچ دانلودی نمی‌کند؛ فقط با نام/کپشن/حجم/زمان تشخیص می‌دهد (سریع‌ترین)"),
                    ("candidates", "فقط نامزدها (توصیه‌شده)", "فقط فایل‌هایی که با نام/حجم/زمان مشکوک‌اند دانلود می‌شوند"),
                    ("all", "همه", "همهٔ فایل‌ها دانلود می‌شوند (کند و پُرترافیک)")],
        "tip": "اگر کنارِ گروه‌ها «⭐⭐⭐⭐ تأییدِ قطعی» نمی‌بینید، این را <code>candidates</code> و "
               "«🔑 دامنهٔ هش» را <code>full</code> بگذارید.",
    },
    "hash_scope": {
        "icon": "🔑", "title": "دامنهٔ هش",
        "what": "از هر فایل چه چیزی هش شود: فقط چند تکهٔ کوچک یا کلِ فایل. هرچه بیشتر، دقیق‌تر ولی کندتر.",
        "options": [("sample", "نمونه (سریع)", "۳ تکهٔ سر/میانه/ته — در گزارش «نشانهٔ قوی»"),
                    ("full", "کامل (قطعی)", "کلِ فایل — کندتر؛ در گزارش «تأییدِ قطعی»")],
        "tip": "برای کانال‌های حجیم اول <code>sample</code> بگذارید و فقط برای گروه‌های مشکوک <code>full</code> کنید. "
               "حداکثر حجمِ این کار با <code>hash_full_max_mb</code> محدود می‌شود.",
    },
    "media_kinds": {
        "icon": "📥", "title": "چه فایل‌هایی اسکن شود",
        "what": "ربات از کانال چه نوع فایل‌هایی را ایندکس کند (ویدیو، سند، عکس…).",
        "options": [("video", "فقط ویدیو", "سریع‌ترین؛ فقط فیلم‌ها بررسی می‌شوند"),
                    ("video+doc", "ویدیو + سند", "فیلم‌ها و فایل‌های PDF/زیپ و…"),
                    ("all", "همه", "هر فایلِ مدیادار (عکس و صدا هم)")],
        "tip": "با عوض‌کردنِ این گزینه، اسکنِ بعدی <b>خودکار کامل</b> می‌شود تا فایل‌های قدیمیِ نوعِ تازه هم دیده شوند.",
    },
    "cluster_mode": {
        "icon": "🧩", "title": "سختگیریِ گروه‌بندی",
        "what": "وقتی A شبیه B و B شبیه C است، آیا هر سه یک گروه می‌شوند؟ این گزینه تصمیم می‌گیرد.",
        "options": [("loose", "زنجیره‌ای (پیش‌فرض)", "همه در یک گروه؛ اگر واقعاً یکی نباشند با نشانِ 🔗 مشخص می‌شوند"),
                    ("strict", "سخت‌گیرانه", "هر عضو باید با همهٔ اعضای گروه شبیه باشد (گروه‌های کوچک‌تر ولی مطمئن‌تر)")],
        "tip": "اگر می‌خواهید <b>همهٔ</b> اعضای یک گروه واقعاً با هم تکراری باشند، <code>strict</code> را انتخاب کنید.",
    },
    "max_forward_per_group": {
        "icon": "📎", "title": "سقفِ فوروارد در هر گروه",
        "what": "هنگامِ «📤 فورواردِ همهٔ تکراری‌ها»، از هر گروه حداکثر چند فایل به چتِ شما فرستاده شود.",
        "presets": [("5", "۵ فایل", "برای گروه‌های شلوغ، چتِ شما کمتر پُر می‌شود"),
                    ("12", "۱۲ فایل (پیش‌فرض)", "تعادل"),
                    ("25", "۲۵ فایل", "وقتی می‌خواهید همه را یک‌جا ببینید")],
        "tip": "این سقف جلوی اسپم‌شدنِ چت را می‌گیرد؛ بقیهٔ فایل‌ها در گزارشِ گروه با لینک در دسترس‌اند.",
    },
    "th_name_ratio": {
        "icon": "🎯", "title": "حساسیتِ نامِ فایل",
        "what": "نامِ فایل باید حداقل این‌قدر شبیه باشد تا «تکراری» حساب شود (بین ۰ و ۱). "
                "کوچک‌تر ⇒ حساسِ بیشتر؛ بزرگ‌تر ⇒ سخت‌گیرِ بیشتر.",
        "presets": [("0.6", "حساس‌تر", "تکراریِ بیشتر پیدا می‌شود، ریسکِ اشتباه هم بیشتر"),
                    ("0.82", "پیش‌فرض", "تعادلِ مناسبِ بیشتر کانال‌ها"),
                    ("0.95", "سخت‌گیرتر", "فقط نام‌های تقریباً یکسان")],
        "tip": "اگر تکراری‌های واضح از دستتان می‌رود، ۰.۷ را امتحان کنید؛ اگر اشتباهِ زیاد می‌بینید، بالا ببرید.",
    },
    "th_name_jaccard": {
        "icon": "🎯", "title": "حساسیتِ نام (کلمه‌ای)",
        "what": "شباهتِ کلمه‌به‌کلمهٔ نام (مثلِ «فیلم ۱» و «فیلم ۲») بین ۰ و ۱ — مکملِ گزینهٔ بالاست.",
        "presets": [("0.5", "حساس‌تر", "کلماتِ مشترکِ کمتر هم کافی است"),
                    ("0.6", "پیش‌فرض", "تعادل"),
                    ("0.8", "سخت‌گیرتر", "باید تقریباً همهٔ کلمات یکی باشند")],
    },
    "th_cap_ratio": {
        "icon": "🎯", "title": "حساسیتِ کپشن",
        "what": "متنِ پست (کپشن) باید حداقل این‌قدر شبیه باشد تا سیگنالِ تکراری‌بودن حساب شود (۰ تا ۱).",
        "presets": [("0.6", "حساس‌تر", "کپشن‌های شبیه هم زودتر سیگنال می‌شوند"),
                    ("0.8", "پیش‌فرض", "تعادل"),
                    ("0.95", "سخت‌گیرتر", "فقط کپشن‌های تقریباً یکسان")],
        "tip": "کپشن‌های عمومیِ کوتاه (مثلِ «فیلم اول») عمداً سیگنال نیستند تا اشتباه پیش نیاید — "
               "با «🎯 حداقلِ طولِ کپشن» می‌توانید این حد را کم کنید.",
    },
    "th_cap_jaccard": {
        "icon": "🎯", "title": "حساسیتِ کپشن (کلمه‌ای)",
        "what": "شباهتِ کلمه‌به‌کلمهٔ کپشن بین ۰ و ۱ — مکملِ گزینهٔ بالاست.",
        "presets": [("0.5", "حساس‌تر", ""), ("0.6", "پیش‌فرض", ""), ("0.8", "سخت‌گیرتر", "")],
    },
    "min_caption_len": {
        "icon": "🎯", "title": "حداقلِ طولِ کپشن",
        "what": "کپشن‌های کوتاه‌تر از این تعداد نویسه نادیده گرفته می‌شوند (تا کپشنِ تکراریِ «فیلم» همه را تکراری نکند).",
        "presets": [("8", "۸ نویسه", "فقط کپشن‌های خیلی کوتاه نادیده می‌مانند (حساسیتِ بیشتر)"),
                    ("12", "۱۲ نویسه (پیش‌فرض)", "تعادل"),
                    ("25", "۲۵ نویسه", "فقط کپشن‌های بلند سیگنال‌اند (اشتباهِ کمتر)")],
        "tip": "پایین‌آوردنِ این عدد ریسکِ «مثبتِ کاذب» را زیاد می‌کند؛ محتاطانه تغییر دهید.",
    },
    "size_tol_pct": {
        "icon": "📏", "title": "اختلافِ حجم (٪)",
        "what": "چند درصد اختلاف در حجمِ دو فایل قابلِ قبول است (۰ = دقیقاً برابر).",
        "presets": [("0", "دقیقاً برابر", "بدونِ هیچ اغماضی؛ سخت‌گیرترین حالت"),
                    ("0.5", "۰.۵٪ (پیش‌فرض)", "تعادل"),
                    ("2", "۲٪", "اگر فایل‌های هم‌محتوا حجمشان کمی فرق دارد"),
                    ("5", "۵٪", "پرتسامح‌ترین حالت (ریسکِ اشتباهِ بیشتر)")],
        "tip": "«📏 حجم یا زمانِ دقیق» تعیین می‌کند آیا همین تلورانس کافی است یا باید یکی دقیقاً برابر باشد.",
    },
    "size_tol_min": {
        "icon": "📏", "title": "اختلافِ حجم (بایت)",
        "what": "اختلافِ کمتر از این مقدار (بایت) نادیده گرفته می‌شود؛ مثلاً ۱ مگابایت = 1048576.",
        "presets": [("0", "صفر", "هیچ اغماضی در حجمِ کوچک نیست"),
                    ("2048", "۲ کیلوبایت (پیش‌فرض)", "تعادل"),
                    ("1048576", "۱ مگابایت", "برای فایل‌های بزرگ مناسب است")],
    },
    "dur_tol_s": {
        "icon": "⏱", "title": "اختلافِ زمان (ثانیه)",
        "what": "چند ثانیه اختلاف در مدتِ ویدیو قابلِ قبول است.",
        "presets": [("1", "۱ ثانیه", "سخت‌گیرتر"), ("2", "۲ ثانیه (پیش‌فرض)", "تعادل"),
                    ("5", "۵ ثانیه", "وقتی ویدیوها برشِ کوچک خورده‌اند")],
    },
    "min_duration_s": {
        "icon": "⏱", "title": "حداقلِ زمانِ ویدیو",
        "what": "ویدیوهای کوتاه‌تر از این (ثانیه) اصلاً بررسی نمی‌شوند (مثلِ کلیپ‌های چندثانیه‌ای که تکراری‌شان "
                "اهمیتی ندارد).",
        "presets": [("0", "بدونِ محدودیت", "همهٔ ویدیوها بررسی می‌شوند"),
                    ("3", "۳ ثانیه (پیش‌فرض)", "تعادل"), ("30", "۳۰ ثانیه", "فقط ویدیوهای جدی")],
    },
    "size_time_require_one_exact": {
        "icon": "📏", "title": "حجم یا زمانِ دقیق",
        "what": "برای اطمینانِ بیشتر: آیا حتماً باید یکی از دو مورد (حجم یا زمان) دقیقاً برابر باشد؟",
        "options": [("1", "روشن (پیش‌فرض)", "حداقل یکی دقیقاً برابر — اشتباهِ کمتر"),
                    ("0", "خاموش", "نزدیک‌بودنِ هر دو هم کافی است — تکراریِ بیشتر، ریسکِ بیشتر")],
    },
    "prune_missing": {
        "icon": "🗑", "title": "رکوردهای حذف‌شده",
        "what": "اگر فایلی را در تلگرام حذف کرده باشید، در «اسکنِ کامل» رکوردش از دیتابیسِ ربات هم پاک شود؟",
        "options": [("1", "روشن (پیش‌فرض)", "ایندکس تمیز می‌ماند و گروه‌ها به فایلِ نبوده اشاره نمی‌کنند"),
                    ("0", "خاموش", "رکوردها می‌مانند (گروه‌ها ممکن است فایلِ حذف‌شده نشان دهند)")],
        "tip": "این کار <b>هیچ‌وقت</b> چیزی را در تلگرام پاک نمی‌کند — فقط دیتابیسِ خودِ ربات تمیز می‌شود.",
    },
    "incr_tail": {
        "icon": "🔄", "title": "بازخوانیِ پیام‌های آخر",
        "what": "در «🔄 ادامهٔ اسکن» (فقط جدیدها)، چند پیامِ آخرِ کانال دوباره خوانده شود تا پستِ "
                "ویرایش‌شده/فایلِ عوض‌شده از دست نرود.",
        "presets": [("50", "۵۰ پیام", "سبک‌تر و سریع‌تر"),
                    ("200", "۲۰۰ پیام (پیش‌فرض)", "تعادل"),
                    ("500", "۵۰۰ پیام", "برای کانال‌هایی که زیاد ویرایش می‌شوند")],
        "tip": "این عدد روی «اسکنِ کامل» اثری ندارد (آن همیشه از اول می‌خواند).",
    },
}

# دسته‌بندیِ منو: (عنوانِ سرگروه، کلیدها) — ترتیب همان‌طور که دیده می‌شود
SETTING_GROUPS: List[Tuple[str, Tuple[str, ...]]] = [
    ("🔑 تشخیص و هش", ("hash_mode", "hash_scope")),
    ("🎯 حساسیتِ تشخیص (آستانه‌ها)", ("th_name_ratio", "th_name_jaccard",
                                      "th_cap_ratio", "th_cap_jaccard", "min_caption_len")),
    ("📏 حجم و زمان", ("size_tol_pct", "size_tol_min", "dur_tol_s", "min_duration_s",
                       "size_time_require_one_exact")),
    ("🧩 گروه‌بندی", ("cluster_mode",)),
    ("📥 اسکن و ایندکس", ("media_kinds", "incr_tail", "prune_missing")),
    ("📎 فوروارد به چتِ شما", ("max_forward_per_group",)),
]

# برچسبِ کوتاهِ هر کلید = عنوانِ همان توضیح (برای `/set` و دکمه‌ها)
SHORT_LABELS = {k: str(v.get("title") or k) for k, v in SETTING_INFO.items()}


def _squash(v: str) -> str:
    """نرمال‌سازیِ سخت‌گیرانه: بدونِ فاصله/نیم‌فاصله/اعراب + یکسان‌سازیِ حروفِ عربی/فارسی.

    تا «دامنهٔ هش»، «دامنه هش»، «سخت‌گیرانه» و «سخت گیرانه» همه یک چیز حساب شوند
    (و ی/ک عربی و «آ/أ/إ» هم به شکلِ فارسیِ ساده بیایند).
    """
    import unicodedata
    v = unicodedata.normalize("NFKC", str(v or "")).lower()
    v = "".join(ch for ch in v if not unicodedata.combining(ch))     # اعراب/همزهٔ ترکیبی
    for a, b in (("\u064a", "\u06cc"), ("\u0649", "\u06cc"), ("\u0643", "\u06a9"),
                 ("\u0629", "\u0647"), ("\u06c0", "\u0647"), ("\u06d5", "\u0647"),
                 ("\u0622", "\u0627"), ("\u0623", "\u0627"), ("\u0625", "\u0627"),
                 ("\u200c", ""), ("\u0650", ""), ("\u0640", "")):
        v = v.replace(a, b)
    return "".join(v.split())


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TRUE_WORDS = {"1", "true", "yes", "y", "on", "روشن", "بله", "درست", "فعال", "اره", "آره"}
_FALSE_WORDS = {"0", "false", "no", "n", "off", "خاموش", "نه", "غلط", "غیرفعال", "نخیر", "خیر"}

# مترادف‌های مجاز برای کلیدهای «گزینه‌ای» (فارسی و انگلیسی، همه به مقدارِ انگلیسی نگاشت می‌شوند)
VALUE_ALIASES: Dict[str, Dict[str, str]] = {
    "hash_mode": {"off": "off", "خاموش": "off", "بدون": "off", "بدون هش": "off", "—": "off",
                  "candidates": "candidates", "candidate": "candidates", "نامزد": "candidates",
                  "نامزدها": "candidates", "نامزدی": "candidates",
                  "all": "all", "همه": "all", "کامل": "all", "همگی": "all"},
    "hash_scope": {"sample": "sample", "نمونه": "sample", "نمونه‌گیری": "sample", "سریع": "sample",
                   "full": "full", "کامل": "full", "همه": "full", "کاملِ فایل": "full"},
    "media_kinds": {"video": "video", "ویدیو": "video", "ویدئو": "video", "فیلم": "video",
                    "video+doc": "video+doc", "video,doc": "video+doc", "video doc": "video+doc",
                    "ویدیو+سند": "video+doc", "ویدیو و سند": "video+doc", "ویدیو,سند": "video+doc",
                    "all": "all", "همه": "all", "کامل": "all", "همه چیز": "all"},
    "cluster_mode": {"loose": "loose", "ازاد": "loose", "آزاد": "loose", "زنجیره‌ای": "loose",
                     "زنجیره": "loose", "پیش‌فرض": "loose",
                     "strict": "strict", "سخت": "strict", "سختگیر": "strict", "سختگیرانه": "strict",
                     "همه با همه": "strict"},
}

# نمایهٔ «بی‌فاصله»ی همان مترادف‌ها (برای «سخت‌گیرانه»/«سخت گیرانه»/«بی‌فاصله» و ی/ک عربی)
VALUE_ALIASES_SQUASHED: Dict[str, Dict[str, str]] = {
    k: {_squash(kk): vv for kk, vv in m.items()} for k, m in VALUE_ALIASES.items()}

# راهنمای مقدار (هم در پرسش و هم در پیامِ خطا استفاده می‌شود)
VALUE_HELP: Dict[str, str] = {
    "hash_mode": "off = بدونِ هش · candidates = فقط نامزدها (سریع) · all = همه (کند)",
    "hash_scope": "sample = سه تکهٔ سر/میانه/ته (سریع) · full = کلِ فایل (کند، قطعی)",
    "media_kinds": "video = فقط ویدیو · video+doc = ویدیو و سند · all = همه",
    "cluster_mode": "loose = زنجیره‌ای (پیش‌فرض) · strict = هر عضو با همهٔ اعضا شبیه باشد",
    "min_caption_len": "یک عدد (نویسه)؛ پیش‌فرض ۱۲ — کمتر = حساس‌تر و ریسکِ مثبتِ کاذب",
    "min_duration_s": "یک عدد (ثانیه) — پیش‌فرض ۳",
    "prune_missing": "1/روشن = رکوردهای حذف‌شده از کانال در اسکنِ کامل پاک شوند · 0/خاموش = نه",
    "size_time_require_one_exact": "1/روشن = یکی از حجم یا زمان باید دقیقاً برابر باشد · 0/خاموش = فقط نزدیک بودن",
    "incr_tail": "یک عدد = چند پیامِ آخر در اسکنِ ادامه‌ای بازخوانی شود (پیش‌فرض ۲۰۰)",
}

class BotApp:
    def __init__(self, api, db, settings: Settings, user=None, *,
                 scanner_factory: Optional[Callable[..., Scanner]] = None,
                 reporter: Optional[R.Reporter] = None):
        self.api = api
        self.db = db
        self.settings = settings
        self.user = user
        self.reporter = reporter or R.Reporter(api, user, max_per_group=settings.max_forward_per_group)
        # سقفِ فایل در هر نوبتِ «📤 فورواردِ همهٔ تکراری‌ها» (بقیه با دکمهٔ ادامه می‌آید)
        self.forward_all_budget = int(getattr(settings, "forward_all_budget", 40) or 40)
        self._scanner_factory = scanner_factory or (lambda **kw: Scanner(db, user, self.cfg_dict, **kw))
        self.bot_username = ""
        self.bot_id = 0
        self._qr_task: Optional[asyncio.Task] = None
        self.owner_id = int(settings.owner_id or 0)
        self.pending: Dict[int, Dict[str, Any]] = {}
        self.scan: Optional[Dict[str, Any]] = None
        self._scan_lock = asyncio.Lock()
        self._offset = int(db.kv_get("tg_offset", 0) or 0)
        self._cmds_set = False
        self.claim_code = ""          # کدِ یک‌بارمصرفِ مالکیت (فقط وقتی OWNER_ID خالی است)
        self.admin_ids: set = set()   # ادمین‌های ربات (به‌جز مالک) — از دیتابیس بارگذاری می‌شود
        self.admin_names: Dict[str, str] = {}
        self.owner_name = ""
        self._access_seen: set = set()   # برای اینکه هر غریبه فقط یک‌بار به مالک معرفی شود
        self._title_tries: Dict[int, float] = {}   # کول‌داونِ تلاش برای گرفتنِ نامِ کانال
        self.title_refresh_max: int = 5            # حداکثر تلاش در هر بازکردنِ فهرست
        self.started_at = int(time.time())
        # قلابِ خواندنِ پیش‌نمایشِ عمومی (در تست‌ها با تابعِ ساختگی جایگزین می‌شود)
        self.preview_fetch = P.fetch_page

    # ── دسترسی ──
    def cfg_dict(self) -> Dict[str, Any]:
        d = self.settings.as_public()
        d.update({k: getattr(self.settings, k) for k in ("hash_mode", "media_kinds")})
        return d

    def _ensure_claim_code(self) -> str:
        """کدِ یک‌بارمصرفِ مالکیت — فقط در لاگِ سرور چاپ می‌شود (نه در چت).

        باگِ امنیتیِ قبلی: اگر `OWNER_ID` تنظیم نشده بود، **اولین کسی که به ربات پیام
        می‌داد مالک می‌شد**؛ در دیپلویِ عمومی یعنی هر غریبه‌ای ربات را می‌گرفت.
        حالا تا وقتی کسی `/claim <کد>` نزند، هیچ‌کس مالک نیست و ربات فقط پیامِ
        «مالک تنظیم نشده» می‌دهد. کد از `OWNER_CLAIM_CODE` (متغیرهای محیطی) هم
        قابلِ تعیین است تا پس از ری‌استارت ثابت بماند.
        """
        if self.owner_id:
            return ""
        if not self.claim_code:
            env_code = str(getattr(self.settings, "owner_claim_code", "") or "").strip()
            self.claim_code = env_code or ("%06d" % random.randint(0, 999999))
            log.warning("مالکِ ربات تنظیم نشده است (OWNER_ID خالی). کدِ مالکیت: %s — "
                        "برای مالک‌شدن در چتِ ربات بفرستید: /claim %s", self.claim_code, self.claim_code)
        return self.claim_code

    async def is_owner(self, uid: int) -> bool:
        """آیا این کاربر مالک است؟ (بدونِ بوت‌استرپِ خودکار — باگِ امنیتیِ رفع‌شده)"""
        if not self.owner_id:
            self._ensure_claim_code()
            return False
        return int(uid) == int(self.owner_id)

    # ── ادمین‌ها (خواستهٔ کاربر: «بتونم برای ربات ادمین اضافه کنم») ──
    def _load_admins(self) -> None:
        """ادمین‌های ذخیره‌شده را از دیتابیس می‌خواند (کلیدهای `admins` و `admin_names`)."""
        try:
            raw = self.db.kv_get("admins", "[]")
            ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
            self.admin_ids = {int(x) for x in ids if str(x).strip().lstrip("-").isdigit()}
        except Exception:
            self.admin_ids = set()
        try:
            raw = self.db.kv_get("admin_names", "{}")
            names = json.loads(raw) if isinstance(raw, str) else (raw or {})
            self.admin_names = {str(k): str(v) for k, v in dict(names or {}).items()}
        except Exception:
            self.admin_names = {}
        if self.owner_id and self.admin_names.get(str(self.owner_id)):
            self.owner_name = self.admin_names[str(self.owner_id)]

    def _save_admins(self) -> None:
        self.db.kv_set("admins", json.dumps(sorted(self.admin_ids)))
        self.db.kv_set("admin_names", json.dumps(self.admin_names, ensure_ascii=False))

    def is_admin(self, uid: int) -> bool:
        """مالک یا ادمینِ اضافه‌شده؟"""
        return bool(self.owner_id and int(uid) == int(self.owner_id)) or int(uid) in self.admin_ids

    async def is_allowed(self, uid: int) -> bool:
        """دروازهٔ دسترسیِ ربات: مالک یا ادمین (بقیه رد می‌شوند)."""
        if not self.owner_id:
            self._ensure_claim_code()
            return False
        return self.is_admin(uid)

    @staticmethod
    def _display_name(u: Optional[Dict[str, Any]], uid: int = 0) -> str:
        u = u or {}
        name = " ".join(x for x in (str(u.get("first_name") or "").strip(),
                                    str(u.get("last_name") or "").strip()) if x).strip()
        uname = str(u.get("username") or "").strip().lstrip("@")
        if name and uname:
            return "%s (@%s)" % (name, uname)
        return name or ("@" + uname if uname else ("کاربرِ %s" % uid))

    def add_admin(self, uid: int, name: str = "") -> bool:
        uid = int(uid)
        if not uid or uid == int(self.owner_id or 0):
            return False
        self.admin_ids.add(uid)
        if name:
            self.admin_names[str(uid)] = str(name)
        self._save_admins()
        return True

    def remove_admin(self, uid: int) -> bool:
        uid = int(uid)
        if uid not in self.admin_ids:
            return False
        self.admin_ids.discard(uid)
        self.admin_names.pop(str(uid), None)
        self._save_admins()
        return True

    async def _access_denied(self, chat: int, uid: int, m: Optional[Dict[str, Any]] = None) -> None:
        """به غریبه «دسترسی ندارید» می‌گوید و **یک‌بار** به مالک اطلاع می‌دهد (بدونِ اسپم)."""
        if not self.owner_id:
            await self.api.send_message(
                chat, "⛔️ این ربات هنوز مالک ندارد. کدِ مالکیت در <b>لاگِ سرور</b> چاپ شده؛ "
                      "آن را این‌طور بفرستید: <code>/claim 123456</code>")
            return
        await self.api.send_message(
            chat, "⛔️ دسترسی ندارید — این ربات خصوصی است.\n"
                  "<i>اگر مالکِ ربات شما را به‌عنوانِ ادمین اضافه کند، می‌توانید از آن استفاده کنید.</i>")
        if int(uid) in self._access_seen:
            return
        self._access_seen.add(int(uid))
        name = self._display_name(((m or {}).get("from") or {}), int(uid))
        try:
            await self.api.send_message(
                int(self.owner_id),
                "🔔 <b>درخواستِ دسترسی</b>\n%s با شناسهٔ <code>%d</code> به ربات پیام داد.\n\n"
                "اگر می‌خواهید به‌عنوانِ ادمین به ربات دسترسی داشته باشد، دکمهٔ زیر را بزنید "
                "(یا <code>/addadmin %d</code>)." % (esc(name), int(uid), int(uid)),
                kb=R.kb([[R.btn("➕ افزودن به‌عنوان ادمین", "own:add:%d" % int(uid))],
                         [R.btn("👥 ادمین‌ها", "own:menu")]]))
        except Exception as e:
            log.info("اطلاع‌دادن به مالک ناموفق: %s", e)

    # ── منوی ادمین‌ها ──
    async def _admins_menu(self, chat: int, edit: Optional[int] = None) -> None:
        lines = ["👥 <b>ادمین‌های ربات</b>", "",
                 "👑 <b>مالک</b>: %s%s" % (esc(self.owner_name or "—"),
                                          " · <code>%d</code>" % self.owner_id if self.owner_id else "")]
        if self.admin_ids:
            lines.append("")
            lines.append("🛡 <b>ادمین‌ها</b> (%d):" % len(self.admin_ids))
            for uid in sorted(self.admin_ids):
                lines.append("• %s · <code>%d</code>" % (esc(self.admin_names.get(str(uid)) or "—"), uid))
        else:
            lines += ["", "<i>هنوز ادمینی اضافه نشده.</i>"]
        lines += ["",
                  "<b>چطور ادمین اضافه کنم؟</b>",
                  "① اینترفیسِ زیر را بزنید و <b>شناسهٔ عددی</b> طرف را بفرستید (با <code>/id</code> خودش می‌فهمد)،",
                  "② یا یک <b>پیامِ فورواردشده از او</b> را برای ربات بفرستید،",
                  "③ یا وقتی غریبه‌ای به ربات پیام می‌دهد، مالک یک دکمهٔ «➕ افزودن» می‌گیرد.",
                  "",
                  "<i>ادمین‌ها همه‌کارهٔ اسکن/گزارش/فوروارد و «⚙️ تنظیمات» هستند؛ فقط «🔑 حسابِ کاربری» "
                  "(سشنِ تلگرامِ مالک)، «👥 مدیریتِ ادمین‌ها» و «🗑 حذفِ کانال از فهرست» در دستِ مالک است.</i>"]
        rows: List[List[Dict[str, str]]] = [[R.btn("➕ افزودنِ ادمین", "own:ask")]]
        if self.admin_ids:
            rows.append([R.btn("🗑 حذفِ ادمین", "own:delmenu")])
        rows.append([R.btn("🏠 منوی اصلی", "home")])
        if edit:
            await self.api.edit_message_text(chat, edit, "\n".join(lines), kb=R.kb(rows))
        else:
            await self.api.send_message(chat, "\n".join(lines), kb=R.kb(rows))

    async def _admins_del_menu(self, chat: int, edit: Optional[int] = None) -> None:
        rows = [[R.btn("🗑 %s · %d" % ((self.admin_names.get(str(u)) or "کاربر")[:24], u), "own:del:%d" % u)]
                for u in sorted(self.admin_ids)]
        rows.append([R.btn("⬅️ ادمین‌ها", "own:menu")])
        txt = "🗑 کدام ادمین حذف شود؟" if self.admin_ids else "ادمینی برای حذف نیست."
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, txt, kb=R.kb(rows))

    async def _admin_add_by_text(self, chat: int, text: str, m: Dict[str, Any]) -> None:
        """افزودنِ ادمین از متنِ مالک: شناسهٔ عددی یا پیامِ فورواردشده از آن کاربر."""
        self.pending.pop(chat, None)
        fwd_user = ((m.get("forward_origin") or {}).get("sender_user") or m.get("forward_from") or {})
        uid = int(fwd_user.get("id") or 0) if fwd_user else 0
        name = self._display_name(fwd_user, uid) if uid else ""
        if not uid:
            digits = re.sub(r"[^0-9]", "", text)
            uid = int(digits) if digits else 0
        if not uid:
            await self.api.send_message(
                chat, "❌ شناسهٔ عددی نفرستادید. مثال: <code>/addadmin 123456789</code>\n"
                      "<i>شناسهٔ خودِ طرف را از پروفایلش (یا با <code>/id</code>) بگیرید؛ "
                      "یا یک پیامِ فورواردشده از او بفرستید.</i>")
            return
        if int(uid) == int(self.owner_id or 0):
            await self.api.send_message(chat, "ℹ️ این خودِ مالک است و از قبل همهٔ دسترسی‌ها را دارد.")
            return
        if not name:
            name = self.admin_names.get(str(uid)) or ""
        if uid in self.admin_ids:
            await self.api.send_message(chat, "ℹ️ این کاربر از قبل ادمین است: <code>%d</code>" % uid)
            return
        self.add_admin(uid, name)
        await self.api.send_message(
            chat, "✅ <b>%s</b> به‌عنوانِ ادمینِ ربات اضافه شد (<code>%d</code>).\n"
                  "<i>ادمین می‌تواند کانال اضافه/اسکن کند، تنظیمات را عوض کند و نتیجه ببیند؛ "
                  "«حسابِ کاربری» و «مدیریتِ ادمین‌ها» فقط در دستِ مالک است.</i>" % (esc(name or "کاربر"), uid),
            kb=R.kb([[R.btn("👥 ادمین‌ها", "own:menu")]]))

    # ── مالکیتِ یک‌بارمصرف (claim) ──
    async def _try_claim_owner(self, chat: int, uid: int, text: str) -> bool:
        """`/claim <کد>` ⇒ مالک‌شدن. قبل از دروازهٔ مالکیت صدا زده می‌شود."""
        parts = text.split()
        if not parts or parts[0].split("@")[0].lower() != "/claim":
            return False
        code = str(self._ensure_claim_code() or "")
        given = parts[1].strip() if len(parts) > 1 else ""
        if self.owner_id:                                  # قبلاً مالک دارد
            await self.api.send_message(chat, "ℹ️ این ربات مالک دارد. اگر مالکیت را گم کرده‌اید، "
                                              "کلیدِ <code>owner_id</code> را از دیتابیس پاک کنید.")
            return True
        if code and given and given == code:
            self.owner_id = int(uid)
            self.db.kv_set("owner_id", self.owner_id)
            self.claim_code = ""
            log.info("مالکِ ربات تعیین شد: %s", uid)
            await self.api.send_message(chat, "✅ شما مالکِ ربات شدید. حالا /start را بزنید.\n"
                                              "<i>برای امنیت، رمزِ مالکیت باطل شد.</i>")
            return True
        await self.api.send_message(
            chat, "⛔️ کدِ مالکیت نادرست یا خالی است.\n"
                  "کد در <b>لاگِ سرور</b> چاپ شده (Railway → سرویس → Logs) و شکلِ دستورش این است:\n"
                  "<code>/claim 123456</code>\n\n"
                  "<i>می‌خواهید کد ثابت باشد؟ متغیر <code>OWNER_CLAIM_CODE</code> را در Variables بگذارید. "
                  "یا مستقیم <code>OWNER_ID</code> را به شناسهٔ عددی خودتان تنظیم کنید.</i>")
        return True

    # ═════════════════════ حلقهٔ اصلی ═════════════════════
    async def run(self) -> None:
        try:
            me = await self.api.get_me()
            self.bot_username = str(me.get("username") or "")
            self.bot_id = int(me.get("id") or 0)
        except Exception as e:
            log.error("getMe ناموفق: %s", e)
        await self._set_commands()
        self._load_peer_hashes()      # access_hashهای کانال‌های خصوصی از دورهای قبل
        self._load_admins()
        if not self.owner_id:
            self._ensure_claim_code()  # کدِ مالکیت فقط در لاگ (هرگز در چت)
        log.info("ربات آماده است (@%s)", self.bot_username)
        while True:
            try:
                updates = await self.api.get_updates(self._offset, timeout=25)
            except Exception as e:
                log.warning("getUpdates خطا: %s", e)
                await asyncio.sleep(3)
                continue
            for u in updates:
                self._offset = max(self._offset, int(u.get("update_id", 0)) + 1)
                try:
                    await self.handle_update(u)
                except Exception as e:
                    log.exception("خطا در پردازشِ آپدیت: %s", e)
            if updates:
                self.db.kv_set("tg_offset", self._offset)

    async def _set_commands(self) -> None:
        cmds = [{"command": "start", "description": "🏠 منوی اصلی"},
                {"command": "channels", "description": "📡 کانال‌های من"},
                {"command": "scanall", "description": "🔍 اسکنِ همهٔ کانال‌ها"},
                {"command": "cancel", "description": "⏹ توقفِ اسکن"},
                {"command": "admins", "description": "👥 ادمین‌های ربات (فقط مالک)"},
                {"command": "history", "description": "🔎 تاریخچهٔ کامل (راهنما)"},
                {"command": "help", "description": "❓ راهنما"}]
        try:
            await self.api.set_my_commands(cmds)
            self._cmds_set = True
        except Exception:
            pass

    # ═════════════════════ ورودی‌ها ═════════════════════
    async def handle_update(self, u: Dict[str, Any]) -> None:
        if "callback_query" in u:
            await self.handle_callback(u["callback_query"])
        elif "message" in u:
            await self.handle_message(u["message"])
        elif "channel_post" in u:
            pass  # پستِ کانال‌ها نادیده (فقط به‌عنوانِ منبعِ اسکن مهم‌اند)

    async def handle_message(self, m: Dict[str, Any]) -> None:
        chat = int(m.get("chat", {}).get("id", 0))
        uid = int(m.get("from", {}).get("id", chat) or chat)
        text = str(m.get("text") or "").strip()
        if not self.owner_id and await self._try_claim_owner(chat, uid, text):
            return
        if not await self.is_allowed(uid):
            await self._access_denied(chat, uid, m)
            return
        if self.owner_id and int(uid) == int(self.owner_id):
            self.owner_name = self._display_name((m or {}).get("from"), int(uid)) or self.owner_name
            if self.owner_name and self.admin_names.get(str(uid)) != self.owner_name:
                self.admin_names[str(uid)] = self.owner_name
                self._save_admins()
        # 📱 شمارهٔ اشتراک‌گذاشته‌شده با دکمهٔ «ارسالِ شمارهٔ من»
        contact = m.get("contact") or {}
        p_now = self.pending.get(chat)
        if contact.get("phone_number") and p_now and p_now.get("kind") == "login_phone":
            cu = int(contact.get("user_id") or 0)
            if cu and cu != uid:
                await self.api.send_message(chat, "❌ لطفاً شمارهٔ <b>خودتان</b> را با دکمهٔ «📱 ارسالِ شمارهٔ من» بفرستید.")
                return
            await self._login_phone_got(chat, str(contact["phone_number"]), m)
            return
        # حالتِ انتظارِ «افزودنِ ادمین»: هم متن و هم پیامِ فورواردشده پذیرفته می‌شود
        p_adm = self.pending.get(chat)
        if p_adm and p_adm.get("kind") == "admin_add" and (self.owner_id and int(uid) == int(self.owner_id)):
            await self._admin_add_by_text(chat, text, m)
            return
        # پیامِ فورواردشده از کانال ⇒ افزودنِ سریعِ کانال
        fwd = self._forwarded_chat(m)
        if fwd and (not text or text.startswith("/")):
            await self._add_channel_from_forward(chat, fwd)
            return
        # هر پستِ فورواردشدهٔ دیگری (با متن یا بدونِ متن): اگر آن کانال را داریم و بی‌نام است،
        # همین‌جا نامش را از دلِ پیام برمی‌داریم ⇒ رفعِ «بدون نام» بدونِ دکمه‌زدن.
        if fwd and not self.pending.get(chat):
            if await self._learn_title_from_forward(chat, fwd):
                return
        # حالتِ انتظار برای مقدار (افزودنِ کانال/تنظیمات/ورود)
        p = self.pending.get(chat)
        if p and text and not text.startswith("/"):
            if p["kind"] == "add_channel":
                await self._add_channel_from_text(chat, text, m)
                return
            if p["kind"] == "setting":
                await self._apply_setting(chat, p["key"], text)
                return
            if p["kind"] == "chan_title":
                await self._set_channel_name(chat, int(p.get("cid") or 0), text)
                return
            if p["kind"].startswith("login_"):
                await self._login_step(chat, p, text, m)
                return
        if text.startswith("/"):
            await self.handle_command(chat, uid, text, m)
            return
        # متنِ آزاد
        if text:
            await self._menu_main(chat, uid, m)

    @staticmethod
    def _forwarded_chat(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        o = m.get("forward_origin") or {}
        if o.get("type") == "channel" and o.get("chat"):
            c = o["chat"]
            return {"id": c.get("id"), "title": c.get("title") or "", "username": c.get("username") or ""}
        if o.get("type") == "chat" and o.get("sender_chat"):
            c = o["sender_chat"]
            return {"id": c.get("id"), "title": c.get("title") or "", "username": c.get("username") or ""}
        fc = m.get("forward_from_chat")
        if fc:
            return {"id": fc.get("id"), "title": fc.get("title") or "", "username": fc.get("username") or ""}
        return None

    async def handle_command(self, chat: int, uid: int, text: str, m: Dict[str, Any]) -> None:
        cmd = text.split()[0].lower().lstrip("/").split("@")[0]
        arg = text[len(text.split()[0]):].strip()
        if cmd == "start":
            if not self._cmds_set:                      # 🩹 اگر در استارتاپ نشد، همین‌جا تلاش دوباره
                await self._set_commands()
            if arg.startswith("card_"):
                await self.api.send_message(chat, "این کارت مخصوصِ رباتِ پنل است.")
                return
            await self._menu_main(chat, uid, m)
        elif cmd in ("help", "history"):
            await self.api.send_message(chat, HELP_TEXT, kb=R.kb([[R.btn("🏠 منوی اصلی", "home")]]))
        elif cmd in ("channels", "ch"):
            await self._channels_menu(chat)
        elif cmd in ("scanall", "scan_all"):
            await self._start_scan_for_all(chat)
        elif cmd in ("cancel", "stop"):
            await self._cancel_scan(chat)
        elif cmd in ("id",):
            await self.api.send_message(chat, "🆔 chat_id: <code>%d</code> · user_id: <code>%d</code>" % (chat, uid))
        elif cmd in ("status", "diag"):
            st = self.db.stats()
            lines = ["📈 <b>وضعیت</b>",
                     "کانال‌ها: <b>%s</b>" % st["channels"],
                     "فایل‌های ایندکس‌شده: <b>%s</b>" % "{:,}".format(st["files"]),
                     "هش‌شده: <b>%s</b>" % "{:,}".format(st["hashed"]),
                     "اسکن‌ها: <b>%s</b> · گروه‌های تکراری: <b>%s</b>" % (st["scans"], st["groups"]),
                     "حسابِ کاربری: %s" % ("✅ وصل" if getattr(self.user, "ready", False) else "❌ وصل نیست"),
                     "اسکنِ جاری: %s" % ("⏳ بله" if (self.scan and not self.scan.get("done")) else "—")]
            await self.api.send_message(chat, "\n".join(lines))
        elif cmd in ("settings", "st", "config"):
            if _squash(arg).startswith("guide") or "راهنما" in arg or "توضیح" in arg:
                await self._settings_guide(chat)
            else:
                await self._settings_menu(chat)
        elif cmd in ("set", "setting"):
            await self._apply_setting_text(chat, arg)
        elif cmd in ("admins", "admin"):
            if not (self.owner_id and int(uid) == int(self.owner_id)):
                await self.api.send_message(chat, "⛔️ فقط مالکِ ربات.")
                return
            await self._admins_menu(chat)
        elif cmd in ("addadmin", "add_admin"):
            if not (self.owner_id and int(uid) == int(self.owner_id)):
                await self.api.send_message(chat, "⛔️ فقط مالکِ ربات.")
                return
            await self._admin_add_by_text(chat, arg, m)
        elif cmd in ("deladmin", "del_admin", "rmadmin"):
            if not (self.owner_id and int(uid) == int(self.owner_id)):
                await self.api.send_message(chat, "⛔️ فقط مالکِ ربات.")
                return
            target = int(re.sub(r"[^0-9]", "", arg) or 0)
            if not target or not self.remove_admin(target):
                await self.api.send_message(chat, "❌ این کاربر ادمین نیست. فهرست: /admins")
            else:
                await self.api.send_message(chat, "🗑 ادمین <code>%d</code> حذف شد." % target)
        elif cmd in ("setsession",):
            if not (self.owner_id and int(uid) == int(self.owner_id)):
                await self.api.send_message(chat, "⛔️ فقط مالکِ ربات.")
                return
            await self._save_session_from_text(chat, arg)
        else:
            await self._menu_main(chat, uid, m)

    # ═════════════════════ منوها ═════════════════════
    async def _menu_main(self, chat: int, uid: int, m: Optional[Dict[str, Any]] = None) -> None:
        self.pending.pop(chat, None)
        st = self.db.stats()
        acc = "✅ وصل" if getattr(self.user, "ready", False) else "❌ وصل نیست"
        scanning = "⏳ یک اسکن در جریان است" if (self.scan and not self.scan.get("done")) else "آماده"
        text = ("🏠 <b>منوی اصلی</b>\n\n"
                "📡 کانال‌ها: <b>%s</b> · 🎬 فایل‌ها: <b>%s</b>\n"
                "🔁 گروه‌های تکراریِ یافته‌شده: <b>%s</b>\n"
                "🔑 حسابِ کاربری (برای تاریخچهٔ کامل): %s\n"
                "⚙️ وضعیت: %s\n\n"
                "<i>ربات فقط می‌خواند و فوروارد می‌کند — هیچ‌چیزی پاک نمی‌شود.</i>") % (
            st["channels"], "{:,}".format(st["files"]), "{:,}".format(st["groups"]), acc, scanning)
        rows = [[R.btn("📡 کانال‌های من", "ch:list"), R.btn("➕ افزودنِ کانال", "ch:add")],
                [R.btn("🔑 اتصالِ حسابِ کاربری", "acc:menu"), R.btn("⚙️ تنظیمات", "st:menu")]]
        if self.owner_id and int(uid) == int(self.owner_id):
            rows.append([R.btn("👥 ادمین‌های ربات (%d)" % len(self.admin_ids), "own:menu")])
        rows.append([R.btn("❓ راهنما", "help")])
        if self.scan and not self.scan.get("done"):
            rows.insert(0, [R.btn("⏹ توقف و کنسل", "scan:cancel")])
        if m:
            await self.api.send_message(chat, text, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, text, kb=R.kb(rows))

    async def _refresh_channel_titles(self, chans: List[Dict[str, Any]], *, force: bool = False) -> int:
        """نام/یوزرنیمِ کانال‌هایی که نامشان «نامعلوم/شناسه‌ای» است را از تلگرام می‌گیرد.

        خواستهٔ کاربر: در فهرستِ کانال‌ها به‌جای شناسه، **نامِ کانال** دیده شود. کانال‌هایی
        که قبلاً با شناسه ذخیره شده بودند یا هنگامِ افزودن نامشان در دسترس نبود، همین‌جا
        (با حسابِ کاربری، وگرنه با Bot API) تازه می‌شوند و در دیتابیس ذخیره می‌گردند.
        """
        fixed = 0
        attempts = 0
        tries = self._title_tries
        now = time.time()
        for c in (chans or []):
            if not force and not R.title_unknown(c):
                continue
            tg_id = int(c.get("tg_id") or 0)
            if not tg_id:
                continue
            # ضدِ کندی/محدودیتِ تلگرام: در هر بار حداکثر `title_refresh_max` تلاش و
            # برای هر کانال یک کول‌داونِ ۱۰ دقیقه‌ای (مگر با `force`).
            if not force:
                if attempts >= self.title_refresh_max:     # سقفِ تلاش در هر بازکردنِ فهرست
                    break
                if now - float(tries.get(tg_id, 0) or 0) < 600:
                    continue
            tries[tg_id] = now
            attempts += 1
            got = await self._learn_title(tg_id, str(c.get("username") or ""), "")
            if got["title"] or got["username"]:
                self.db.set_channel_title(int(c["id"]), got["title"], got["username"])
                fixed += 1
        return fixed

    async def _channels_menu(self, chat: int) -> None:
        chans = self.db.list_channels()
        if not chans:
            await self.api.send_message(
                chat,
                "📡 هنوز کانالی اضافه نشده.\n\n"
                "روی «➕ افزودنِ کانال» بزنید و یکی از این‌ها را بفرستید:\n"
                "• <code>@username</code> کانال\n• لینک <code>https://t.me/username</code>\n"
                "• یا یک پست از کانال را برایم <b>فوروارد</b> کنید\n\n"
                "⚠️ یادتان باشد ربات باید در کانال <b>ادمین</b> باشد.",
                kb=R.kb([[R.btn("➕ افزودنِ کانال", "ch:add")], [R.btn("🏠 منوی اصلی", "home")]]))
            return
        fixed = await self._refresh_channel_titles(chans)      # نام‌ها را از تلگرام تازه می‌کند
        if fixed:
            chans = self.db.list_channels()
        rows: List[List[Dict[str, str]]] = []
        for c in chans:
            last = self.db.last_scan(int(c["id"]))
            mark = "🆕" if not last else ("⏹" if last.get("status") == "canceled" else
                                          ("⚠️" if last.get("status") == "error" else "✅"))
            rows.append([R.btn("%s %s" % (mark, R.channel_title(c)[:40]),
                               "c:%d" % int(c["id"]))])
        rows.append([R.btn("➕ افزودنِ کانال", "ch:add"), R.btn("🔍 اسکنِ همه", "scan:all")])
        if any(R.title_unknown(c) for c in chans):
            rows.append([R.btn("🔄 تلاشِ دوباره برای نامِ کانال‌ها", "ch:fix"),
                         R.btn("✏️ نامِ دستی", "name:%d" % int([c for c in chans if R.title_unknown(c)][0]["id"]))])
        rows.append([R.btn("🏠 منوی اصلی", "home")])
        extra = ("\n<i>✨ نامِ %d کانال از تلگرام تازه شد.</i>" % fixed) if fixed else ""
        await self.api.send_message(chat, self._channels_text(chans) + extra, kb=R.kb(rows))

    def _channels_text(self, chans: List[Dict[str, Any]]) -> str:
        """فهرستِ کانال‌ها با **نام** (نه شناسه) + وضعیتِ اسکن و تعدادِ فایل."""
        lines = ["📡 <b>کانال‌های شما</b> (<b>%d</b>)" % len(chans), ""]
        for c in chans:
            cid = int(c["id"])
            last = self.db.last_scan(cid)
            st = "🆕 اسکن‌نشده" if not last else {
                "done": "✅ اسکن‌شده", "canceled": "⏹ کنسل‌شده", "error": "⚠️ خطا",
                "running": "⏳ در حالِ اسکن"}.get(str(last.get("status")), "✅ اسکن‌شده")
            # «ربات ادمین نیست» مانعِ اسکن نیست (اسکن با حسابِ کاربری انجام می‌شود) ⇒ لحن آرام
            warn = "" if self.db.kv_get("botadmin:%d" % cid) else \
                " <i>(ربات ادمین نیست — برای اسکن لازم نیست)</i>"
            lines.append("• <b>%s</b> — %s · %s فایل%s" % (
                esc(R.channel_title(c)), st, "{:,}".format(self.db.count_files(cid)), warn))
            if R.title_unknown(c):
                lines.append("   <i>نامش خوانده نشد: یک <b>پستِ همین کانال</b> را برایم فوروارد کنید "
                             "یا ⌨️ «✏️ نامِ کانال» را از کارتِ کانال بزنید.</i>")
        lines += ["", "<i>روی هر کانال بزنید تا اسکن کنید و نتیجه را ببینید.</i>"]
        return "\n".join(lines)

    async def _access_check(self, cid: int, chat: int, *, edit: Optional[int] = None) -> None:
        """🩺 پاسخِ صریح به «چه دسترسی‌ای لازم است؟» برای همین کانال (با یک نگاهِ زنده)."""
        c = self.db.get_channel(cid) or {}
        tg_id = int(c.get("tg_id") or 0)
        bot_state = await self._bot_membership(tg_id)
        bot_line = {"admin": "✅ ادمینِ کانال است",
                    "member": "🟡 عضو است (ادمین نیست)",
                    "out": "⛔️ عضوِ کانال نیست",
                    "unknown": "❔ قابلِ بررسی نبود"}[bot_state]
        user_line = "⛔️ وصل نیست (با «🔑 اتصالِ حسابِ کاربری» وصلش کنید)"
        user_ok = False
        if getattr(self.user, "ready", False):
            try:
                info = await self.user.probe(tg_id) if tg_id else {}
                total = int((info or {}).get("total") or 0)
                last = int((info or {}).get("last_id") or 0)
                user_ok = bool(total or last)
                user_line = ("✅ تاریخچه خوانده می‌شود (%s پیام)" % "{:,}".format(total)) if user_ok else \
                    "🟡 چیزی خوانده نشد (یا کانال خالی است یا حساب دسترسی/عضویت ندارد)"
            except Exception as e:
                user_line = "⚠️ خطا در بررسی: <code>%s</code>" % esc(e)
        lines = ["🩺 <b>چه دسترسی‌ای لازم است؟</b> — %s" % esc(R.channel_title(c)), "",
                 "🤖 <b>ربات</b>: %s" % bot_line,
                 "👤 <b>حسابِ کاربری</b>: %s" % user_line, ""]
        if user_ok:
            lines += ["✅ <b>وضعیت خوب است.</b> اسکنِ کامل و فورواردِ نتیجه کار می‌کند.",
                      "<i>ربات برای «اسکن» لازم نیست ادمین باشد؛ اسکن با حسابِ کاربری انجام می‌شود "
                      "و فوروارد هم اگر ربات نتواند، با حسابِ کاربری انجام می‌شود.</i>"]
        elif bot_state in ("admin", "member"):
            lines += ["⚠️ اسکنِ کاملِ تاریخچه کار <b>نمی‌کند</b>، چون Bot API اصلاً «تاریخچهٔ کانال» ندارد.",
                      "یکی از این دو کار را بکنید:",
                      "① حسابِ کاربری را در کانال <b>عضو</b> کنید (لازم نیست ادمین باشد!) — برای کانالِ "
                      "<b>عمومی</b> حتی عضو‌شدن هم لازم نیست.",
                      "② یا پست‌های قدیمی را در یک کانالِ آرشیو فوروارد کنید و همان را اسکن کنیم."]
        else:
            lines += ["⚠️ نه ربات و نه حسابِ کاربری به این کانال دسترسی ندارند.",
                      "• ربات را ادمین کنید (دکمهٔ پایین) ⇒ نامِ خودکار + فوروارد با ربات.",
                      "• و/یا حسابِ کاربری را <b>عضو</b> کانال کنید ⇒ اسکنِ کاملِ تاریخچه.",
                      "<i>حسابِ کاربری لازم نیست ادمین باشد؛ فقط عضویت کافی است.</i>"]
        if R.title_unknown(c):
            lines += ["", "✏️ نامِ این کانال را هم دستی بگذارید یا یک پستِ کانال را برایم فوروارد کنید."]
        rows = [[R.btn("➕ ادمین‌کردنِ ربات", "adm:%d" % cid)]] if bot_state != "admin" else []
        if R.title_unknown(c):
            rows.append([R.btn("✏️ نامِ کانال را دستی بگذار", "name:%d" % cid)])
        rows.append([R.btn("🔍 اسکن کامل", "scan:full:%d" % cid)])
        rows.append([R.btn("⬅️ کانال", "c:%d" % cid)])
        txt = "\n".join(lines)
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, txt, kb=R.kb(rows))

    async def _ask_channel_name(self, chat: int, cid: int) -> None:
        self.pending[chat] = {"kind": "chan_title", "cid": int(cid)}
        c = self.db.get_channel(cid) or {}
        await self.api.send_message(
            chat, "✏️ <b>نامِ کانال</b> — «%s»\n\nنامی که می‌خواهید در فهرست دیده شود را "
                  "بفرستید (فقط برای نمایش در ربات؛ چیزی در تلگرام عوض نمی‌شود)." % esc(R.channel_title(c)),
            kb=R.kb([[R.btn("⬅️ انصراف", "c:%d" % int(cid))]]))

    async def _set_channel_name(self, chat: int, cid: int, name: str) -> None:
        self.pending.pop(chat, None)
        name = " ".join(str(name or "").split())[:64]
        if not name:
            await self.api.send_message(chat, "❌ نامِ خالی قبول نیست.")
            return
        self.db.set_channel_title(int(cid), name)
        c = self.db.get_channel(cid) or {}
        await self.api.send_message(
            chat, "✅ نامِ کانال ذخیره شد: <b>%s</b>" % esc(R.channel_title(c)),
            kb=R.kb([[R.btn("📡 کانال", "c:%d" % int(cid))], [R.btn("📡 کانال‌ها", "ch:list")]]))

    async def _channel_view(self, chat: int, cid: int, edit: Optional[int] = None) -> None:
        c = self.db.get_channel(cid)
        if not c:
            await self.api.send_message(chat, "این کانال پیدا نشد.")
            return
        last = self.db.last_scan(cid)
        files = self.db.count_files(cid)
        state = "—"
        if last:
            state = "%s · %s فایل · %s گروه" % (
                {"done": "✅ کامل", "canceled": "⏹ کنسل‌شده", "error": "⚠️ خطا", "running": "⏳"}.get(
                    last.get("status"), last.get("status")),
                "{:,}".format(int(last.get("files_found") or 0)), "{:,}".format(int(last.get("groups_found") or 0)))
        name_note = ("\n<i>⚠️ نامِ این کانال از تلگرام خوانده نشد؛ «✏️ نامِ کانال» را بزنید یا یک "
                     "پست از همین کانال را برایم فوروارد کنید.</i>") if R.title_unknown(c) else ""
        text = ("📡 <b>%s</b>\n🔗 %s%s\n\n"
                "🎬 فایل‌های ایندکس‌شده: <b>%s</b>\n📊 آخرین اسکن: %s") % (
            esc(R.channel_title(c)), esc("@" + (c.get("username") or "—")), name_note,
            "{:,}".format(files), state)
        rows = [[R.btn("🔍 اسکن کامل (تاریخچهٔ کامل)", "scan:full:%d" % cid)],
                [R.btn("🔄 ادامهٔ اسکن (فقط جدیدها)", "scan:cont:%d" % cid)]]
        # «اسکنِ محدود» فقط برای کانال‌های **عمومی** (یوزرنیم‌دار) معنا دارد — از پیش‌نمایشِ
        # t.me/s خوانده می‌شود؛ دکمه فقط وقتی نشان داده می‌شود که کار کند (نه دکمهٔ بی‌اثر).
        if str(c.get("username") or "").strip():
            rows.append([R.btn("⚠️ اسکن محدود (چند صفحهٔ آخرِ عمومی، بدونِ حجم/هش)",
                               "scan:limited:%d" % cid)])
        if last:
            rows.append([R.btn("📊 نتیجهٔ آخرین اسکن", "s:%d:%d" % (int(last["id"]), cid)),
                         R.btn("🔁 گروه‌های تکراری", "l:%d:%d:all:0" % (int(last["id"]), cid))])
        if self.scan and not self.scan.get("done"):
            rows.insert(0, [R.btn("⏹ توقف و کنسل", "scan:cancel")])
        if R.title_unknown(c):
            rows.append([R.btn("✏️ نامِ کانال را دستی بگذار (یا یک پستش را فوروارد کنید)",
                               "name:%d" % cid)])
        rows.append([R.btn("➕ ادمین‌کردنِ ربات در این کانال", "adm:%d" % cid),
                     R.btn("🩺 دسترسی‌های لازم", "chk:%d" % cid)])
        rows.append([R.btn("🗑 حذف از فهرست", "ch:del:%d" % cid), R.btn("⬅️ کانال‌ها", "ch:list")])
        if edit:
            await self.api.edit_message_text(chat, edit, text, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, text, kb=R.kb(rows))

    # ═════════════════════ افزودنِ کانال ═════════════════════
    async def _ask_add_channel(self, chat: int) -> None:
        self.pending[chat] = {"kind": "add_channel"}
        await self.api.send_message(
            chat,
            "➕ <b>افزودنِ کانال</b>\n\n"
            "یکی از این‌ها را بفرستید:\n"
            "• <code>@username</code>\n• لینک <code>https://t.me/username</code>\n"
            "• شناسهٔ عددی مثل <code>-1001234567890</code>\n"
            "• یا یک <b>پستِ فورواردشده</b> از همان کانال\n\n"
            "⚠️ ربات باید در کانال <b>ادمین</b> باشد (برای فوروارد). برای دیدنِ <b>کلِ تاریخچه</b> هم «🔑 اتصالِ حسابِ کاربری» را انجام دهید.",
            kb=R.kb([[R.btn("⬅️ کانال‌ها", "ch:list")]]))

    async def _learn_title_from_forward(self, chat: int, fwd: Dict[str, Any]) -> bool:
        """اگر کانالِ فورواردشده را داریم و نامش نامعلوم است، از خودِ پیام نامش را بگیر.

        خروجی `True` یعنی «نام تازه ثبت شد» ⇒ پیامِ تأیید فرستاده شده و نیازی به ادامهٔ
        پردازش این پیام (منوی اصلی) نیست.
        """
        tg_id = int(fwd.get("id") or 0)
        if not tg_id:
            return False
        c = self.db.get_channel_by_tg(tg_id)
        if not c or not R.title_unknown(c):
            return False
        title = str(fwd.get("title") or "").strip()
        username = str(fwd.get("username") or "").strip().lstrip("@")
        if not title and not username:
            return False
        got = await self._learn_title(tg_id, username, title)
        if got["title"] or got["username"]:
            self.db.set_channel_title(int(c["id"]), got["title"], got["username"])
            await self.api.send_message(
                chat, "✏️ نامِ کانال از پستِ فورواردشده خوانده شد: <b>%s</b>" % esc(R.channel_title(
                    self.db.get_channel(int(c["id"])) or {})),
                kb=R.kb([[R.btn("📡 کانال", "c:%d" % int(c["id"]))], [R.btn("📡 کانال‌ها", "ch:list")]]))
            return True
        return False

    async def _add_channel_from_forward(self, chat: int, fwd: Dict[str, Any]) -> None:
        tg_id = int(fwd.get("id") or 0)
        await self._register_channel(chat, tg_id, fwd.get("username") or "", fwd.get("title") or "")

    async def _add_channel_from_text(self, chat: int, text: str, m: Dict[str, Any]) -> None:
        t = text.strip()
        tg_id = 0
        username = ""
        if "t.me/+" in t or "telegram.me/+" in t or t.startswith("+"):
            await self.api.send_message(
                chat,
                "⚠️ لینکِ دعوتِ خصوصی (<code>+</code>) پشتیبانی نمی‌شود.\n"
                "یک پست از کانال را برایم <b>فوروارد</b> کنید، یا <code>@username</code> یا شناسهٔ عددی بفرستید.")
            return
        mm = re.search(r"(?:t\.me|telegram\.me)/(?:c/)?([A-Za-z0-9_]+)", t)
        if mm and not t.startswith("-"):
            username = mm.group(1)
        elif t.startswith("@"):
            username = t.lstrip("@")
        elif t.startswith("-") or t.lstrip("-").isdigit():
            try:
                tg_id = int(t)
            except Exception:
                tg_id = 0
        title = ""
        if not tg_id and username:
            try:
                info = await self.api.get_chat("@" + username)
                tg_id = int(info.get("id") or 0)
                title = info.get("title") or ""
            except Exception as e:
                await self.api.send_message(chat, "❌ کانال پیدا نشد یا ربات عضو نیست: <code>%s</code>" % esc(e))
                return
        if not tg_id:
            await self.api.send_message(chat, "❌ ورودی نامعتبر. یوزرنیم/لینک/شناسه یا پستِ فورواردشده بفرستید.")
            return
        await self._register_channel(chat, tg_id, username, title)

    async def _learn_title(self, tg_id: int, username: str = "", title: str = "",
                           *, kind: str = "") -> Dict[str, str]:
        """نردبانِ گرفتنِ نامِ کانال: ① فوروارد ② حسابِ کاربری ③ Bot API ④ probe.

        هر پله که جواب بدهد کافی است؛ خروجی همیشه نام/یوزرنیم/نوعِ بهترین چیزی است که
        پیدا شد. **هیچ‌وقت** نامِ پیدا‌شده را با نامِ خالی خراب نمی‌کند.
        """
        out = {"title": str(title or "").strip(), "username": str(username or "").strip().lstrip("@"),
               "kind": kind or "channel"}
        _tg = str(tg_id or "").strip()
        if out["title"] and out["title"].lstrip("-").isdigit() and \
                out["title"] in (_tg, _tg.lstrip("-"), "-" + _tg):
            out["title"] = ""            # عنوانی که خودِ شناسه است، «نام» حساب نمی‌شود
        if out["title"] and out["username"]:
            return out
        # ② حسابِ کاربری (کافی است اکانت **عضو** باشد؛ برای کانالِ عمومی نیاز به عضویت هم نیست)
        if getattr(self.user, "ready", False):
            try:
                info = await self.user.resolve(tg_id or ("@" + out["username"])) or {}
                out["title"] = out["title"] or str(info.get("title") or "").strip()
                out["username"] = out["username"] or str(info.get("username") or "").strip().lstrip("@")
                out["kind"] = str(info.get("kind") or out["kind"])
                try:
                    self.user.set_hint(int(info.get("tg_id") or tg_id or 0),
                                       username=out["username"], title=out["title"])
                    self._remember_peer_hashes()
                except Exception:
                    pass
            except Exception as e:
                log.debug("resolve برای نامِ %s ناموفق: %s", tg_id, e)
        # ③ Bot API (اگر ربات در کانال عضو/ادمین باشد)
        if tg_id and (not out["title"] or not out["username"]):
            try:
                info = await self.api.get_chat(tg_id)
                out["title"] = out["title"] or str(info.get("title") or "").strip()
                out["username"] = out["username"] or str(info.get("username") or "").strip().lstrip("@")
            except Exception as e:
                log.debug("getChat برای %s ناموفق: %s", tg_id, e)
        # ④ probe (عنوان از GetHistory/entity)
        if tg_id and not out["title"] and getattr(self.user, "ready", False):
            try:
                info = await self.user.probe(tg_id) or {}
                out["title"] = str(info.get("title") or "").strip()
            except Exception:
                pass
        if tg_id:
            try:
                self.user.set_hint(int(tg_id), username=out["username"], title=out["title"])
            except Exception:
                pass
        return out

    async def _bot_membership(self, tg_id: int) -> str:
        """وضعیتِ ربات در کانال: `admin` · `member` · `out` (عضو/ادمین نیست) · `unknown`."""
        try:
            me = await self.api.get_me()
            st = await self.api.get_chat_member(tg_id, int(me.get("id") or 0))
            status = str(st.get("status") or "")
            if status in ("administrator", "creator"):
                return "admin"
            if status in ("member", "restricted"):
                return "member"
            return "out"
        except Exception:
            return "unknown"

    async def _register_channel(self, chat: int, tg_id: int, username: str, title: str) -> None:
        bot_state = await self._bot_membership(tg_id)          # فقط برای اطلاع؛ مانعِ افزودن نیست
        prev = self.db.get_channel_by_tg(tg_id) or {}
        kind = "channel"
        got = await self._learn_title(tg_id, username, title, kind=kind)
        # نامِ موجود در دیتابیس هرگز با نامِ خالی پاک نمی‌شود
        title = got["title"] or str(prev.get("title") or "").strip()
        username = got["username"] or str(prev.get("username") or "").strip()
        kind = got["kind"] or kind
        cid = self.db.add_channel(tg_id, title, username, kind)
        self.pending.pop(chat, None)
        c = self.db.get_channel(cid) or {}
        if bot_state in ("admin", "member"):
            self.db.kv_set("botadmin:%d" % cid, 1)
        warn = ""
        if bot_state == "out":
            warn = ("\n\n⚠️ ربات <b>عضوِ</b> «%s» نیست. برای اسکن لازم نیست ربات ادمین باشد "
                    "(اسکن با حسابِ کاربری انجام می‌شود)، ولی «نامِ خودکار» و «فوروارد با ربات» "
                    "کار می‌کند اگر ربات را ادمین کنید." % esc(R.channel_title(c)))
        rows = [[R.btn("🔍 اسکن کامل", "scan:full:%d" % cid)]]
        if bot_state in ("out", "unknown"):
            rows.insert(0, [R.btn("➕ ادمین‌کردنِ ربات در «%s»" % R.channel_title(c)[:28], "adm:%d" % cid)])
        if R.title_unknown(c):
            rows.insert(0, [R.btn("✏️ نامِ کانال را دستی بگذار", "name:%d" % cid)])
        rows.append([R.btn("🩺 چه دسترسی‌ای لازم است؟", "chk:%d" % cid)])
        rows.append([R.btn("📡 کانال‌ها", "ch:list")])
        await self.api.send_message(
            chat, "✅ کانال ذخیره شد: <b>%s</b>%s\n\n%s" % (
                esc(R.channel_title(c)), warn,
                "حالا اسکن را شروع کنیم؟" if not R.title_unknown(c) else
                "نامش را از تلگرام نخواندم — با دکمهٔ «✏️ نامِ کانال» خودتان بگذارید، یا یک "
                "<b>پستِ همین کانال</b> را برایم فوروارد کنید تا نامش را بردارم."),
            kb=R.kb(rows))

    def _remember_peer_hashes(self) -> None:
        """هشِ دسترسیِ کانال‌ها را در DB نگه می‌دارد (برای کانالِ خصوصی پس از ری‌استارت)."""
        try:
            snap = self.user.peer_snapshot()
        except Exception:
            return
        for tg_id, ah in (snap or {}).items():
            self.db.kv_set("peerhash:%s" % tg_id, int(ah))

    def _load_peer_hashes(self) -> None:
        """هش‌های ذخیره‌شده را در حافظهٔ کلاینت برمی‌گرداند (بعد از ری‌استارت)."""
        try:
            for k, v in (self.db.kv_all() or {}).items():
                if str(k).startswith("peerhash:"):
                    tg_id = int(str(k).split(":", 1)[1])
                    try:
                        self.user.set_hint(tg_id, access_hash=int(v))
                    except Exception:
                        pass
        except Exception:
            pass

    async def _make_bot_admin(self, chat: int, cid: int) -> None:
        """ربات را با حسابِ کاربری ادمینِ کانال می‌کند — فقط حقِ خواندن/فوروارد، بدونِ حذف."""
        c = self.db.get_channel(cid)
        if not c:
            await self.api.send_message(chat, "این کانال پیدا نشد.")
            return
        name = R.channel_title(c)
        tg_id = int(c.get("tg_id") or 0)
        if not getattr(self.user, "ready", False):
            await self.api.send_message(
                chat, "🔑 برای این کار باید حسابِ کاربری وصل باشد (چون فقط ادمین‌ها می‌توانند ادمین اضافه کنند).",
                kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")], [R.btn("⬅️ کانال", "c:%d" % cid)]]))
            return
        bot_id = int(self.bot_id or 0)
        if not bot_id:
            try:
                me = await self.api.get_me()
                bot_id = int(me.get("id") or 0)
                self.bot_id = bot_id
            except Exception:
                pass
        if not bot_id:
            await self.api.send_message(chat, "❌ شناسهٔ ربات معلوم نشد؛ یک‌بار /start بزنید.")
            return
        if await self.user.is_bot_admin(tg_id, bot_id):
            await self.api.send_message(
                chat, "✅ ربات از قبل ادمینِ «%s» است." % esc(name), kb=R.kb([[R.btn("⬅️ کانال", "c:%d" % cid)]]))
            return
        await self.api.send_message(chat, "⏳ دارم ربات را ادمینِ «%s» می‌کنم…" % esc(name))
        res = await self.user.add_bot_admin(tg_id, bot_id)
        if res.get("ok"):
            await self.api.send_message(
                chat,
                "✅ ربات ادمینِ «%s» شد.\n"
                "🛡 فقط حقِ لازم داده شد (<b>بدونِ</b> مجوزِ حذفِ پیام) — ربات هیچ‌وقت چیزی پاک نمی‌کند.\n"
                "اگر خودتان هم ادمین هستید، در «Manage Channel → Administrators» می‌بینیدش." % esc(name),
                kb=R.kb([[R.btn("🔍 اسکن کامل", "scan:full:%d" % cid)], [R.btn("⬅️ کانال", "c:%d" % cid)]]))
        else:
            err = str(res.get("error") or "")
            hint = ""
            if "CHAT_ADMIN_REQUIRED" in err or "not enough rights" in err.lower():
                hint = "\n<i>حسابِ وصل‌شده باید ادمینِ آن کانال با حقِ «افزودنِ ادمین» باشد.</i>"
            elif "USER_NOT_MUTUAL_CONTACT" in err or "USER_PRIVACY" in err:
                hint = "\n<i>حریمِ خصوصی/تنظیماتِ ادمین‌ها اجازه نمی‌دهد؛ دستی اضافه کنید.</i>"
            await self.api.send_message(
                chat, "❌ ادمین‌کردن ناموفق: <code>%s</code>%s\n\n"
                      "راهِ دستی: کانال → Manage → Administrators → Add Admin → %s" % (
                          esc(err), hint, esc("@" + (self.bot_username or "ربات"))),
                kb=R.kb([[R.btn("🔁 تلاشِ دوباره", "adm:%d" % cid)], [R.btn("⬅️ کانال", "c:%d" % cid)]]))

    # ═════════════════════ تنظیمات ═════════════════════
    # ── توضیحِ هر تنظیم: عنوان/چیستی/گزینه‌ها/نکته ──
    @staticmethod
    def _setting_default(key: str) -> Any:
        try:
            return getattr(Settings(), key)
        except Exception:
            return "—"

    @staticmethod
    def _setting_info(key: str) -> Dict[str, Any]:
        return SETTING_INFO.get(key) or {}

    def _setting_display(self, key: str) -> str:
        """مقدارِ فعلی به شکلِ خوانا: True/False ⇒ «روشن/خاموش» (نه اصطلاحِ انگلیسی)."""
        v = getattr(self.settings, key, "—")
        if isinstance(v, bool):
            return "روشن" if v else "خاموش"
        return str(v)

    def _setting_choices(self, key: str) -> List[Tuple[str, str, str]]:
        """مقدارهای پیشنهادی برای دکمه‌ها: [(مقدار، برچسب، توضیح)]."""
        info = self._setting_info(key)
        return list(info.get("options") or info.get("presets") or [])

    def _setting_rows(self) -> List[List[Dict[str, str]]]:
        """منوی تنظیمات: دسته‌بندی‌شده، دوستونه، با برچسبِ فارسیِ کوتاه + مقدارِ فعلی."""
        rows: List[List[Dict[str, str]]] = []
        for group, keys in SETTING_GROUPS:
            rows.append([R.btn(group, "nop:")])          # سرگروه (غیرِکلیک‌شدنی)
            pairs: List[Tuple[str, str]] = []
            for k in keys:
                if k not in SETTING_INFO or not hasattr(self.settings, k):
                    continue
                info = SETTING_INFO[k]
                pairs.append(("%s %s: %s" % (info.get("icon", "⚙️"), info.get("title", k),
                                             self._setting_display(k)), "st:%s" % k))
            for i in range(0, len(pairs), 2):
                rows.append([R.btn(t, c) for t, c in pairs[i:i + 2]])
        rows.append([R.btn("❓ هر گزینه یعنی چه؟ (راهنمای کامل)", "st:guide")])
        rows.append([R.btn("♻️ بازگشتِ همه به پیش‌فرض", "st:reset"), R.btn("🏠 منوی اصلی", "home")])
        return rows

    async def _settings_menu(self, chat: int) -> None:
        text = ("⚙️ <b>تنظیماتِ تطبیق</b>\n\n"
                "کارِ ربات: کانال را می‌خواند و فایل‌های <b>تکراری</b> را با ۳ سیگنال پیدا می‌کند:\n"
                "① <b>نامِ فایل</b> ② <b>کپشن</b> ③ <b>حجم + زمان</b> — و برای تأییدِ قطعی، <b>هشِ محتوا</b>.\n\n"
                "👇 هر دکمه یک تنظیم است. اگر نمی‌دانید هرکدام چه کار می‌کند: روی خودش بزنید (توضیح + "
                "گزینه‌ها می‌آید) یا «❓ هر گزینه یعنی چه؟» را بزنید.\n\n"
                "<i>هر تغییر همان لحظه ذخیره می‌شود و تا تغییرِ بعدی می‌ماند.</i>")
        try:
            await self.api.send_message(chat, text, kb=R.kb(self._setting_rows()))
        except Exception as e:
            # فال‌بک: اگر تلگرام کیبورد را نپذیرفت، متن می‌رود و راهِ /set گفته می‌شود
            log.warning("ارسالِ منوی تنظیمات با کیبورد ناموفق: %s", e)
            await self.api.send_message(
                chat, text + "\n\n⚠️ دکمه‌ها ارسال نشد (<code>%s</code>)؛ با دستورِ "
                             "<code>/set کلید مقدار</code> تغییر دهید." % esc(e))

    async def _setting_detail(self, chat: int, key: str, *, edit: Optional[int] = None,
                              note: str = "") -> None:
        """صفحهٔ توضیحِ یک تنظیم: «این چیست؟» + «گزینه‌ها با نتیجه‌شان» + دکمه‌های انتخاب."""
        info = self._setting_info(key)
        if not info:
            await self.api.send_message(chat, "این گزینه پیدا نشد.")
            return
        cur = self._setting_display(key)
        _d = self._setting_default(key)
        default = ("روشن" if _d else "خاموش") if isinstance(_d, bool) else str(_d)
        lines: List[str] = []
        if note:
            lines += [note, ""]
        lines += ["%s <b>%s</b>" % (info.get("icon", "⚙️"), info.get("title", key)),
                  "مقدارِ فعلی: <b>%s</b> · پیش‌فرض: <code>%s</code>" % (esc(cur), esc(default)), "",
                  info.get("what", ""), ""]
        choices = self._setting_choices(key)
        if choices:
            lines.append("<b>گزینه‌ها (روی دکمه بزنید = همان لحظه تغییر می‌کند):</b>")
            for value, label, desc in choices:
                mark = "✅" if str(value) == cur else "▫️"
                lines.append("%s <b>%s</b>%s — <code>%s</code>" % (
                    mark, esc(label), (" (فعلی)" if str(value) == cur else ""),
                    esc(desc) if desc else esc(str(value))))
            lines.append("")
        if info.get("tip"):
            lines += ["💡 %s" % info["tip"], ""]
        lines.append("<i>مقدارِ دلخواه هم می‌شود: «✏️ تایپ می‌کنم». عددها با ارقامِ فارسی هم قبول است.</i>")
        rows: List[List[Dict[str, str]]] = []
        for value, label, _desc in choices:
            if str(value) == cur:
                rows.append([R.btn("✅ %s (فعلی)" % label, "nop:")])
            else:
                rows.append([R.btn("▫️ %s" % label, "stv:%s:%s" % (key, value))])
        rows.append([R.btn("✏️ تایپ می‌کنم (مقدارِ دلخواه)", "sta:%s" % key)])
        if cur != default:
            rows.append([R.btn("♻️ پیش‌فرضِ همین گزینه (%s)" % default, "std:%s" % key)])
        rows.append([R.btn("❓ راهنمای همه", "st:guide"), R.btn("⬅️ تنظیمات", "st:menu")])
        txt = "\n".join(lines)
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, txt, kb=R.kb(rows))

    async def _settings_guide(self, chat: int, *, edit: Optional[int] = None) -> None:
        """«هر گزینه یعنی چه؟» — راهنمای فارسیِ همهٔ تنظیم‌ها با مقدارِ فعلی و پیش‌فرض."""
        parts: List[str] = []
        buf = ("📖 <b>راهنمای تنظیمات — هر گزینه چه کار می‌کند</b>\n\n"
               "<i>مقدارِ فعلی و پیش‌فرض هر مورد کنارش نوشته شده. برای تغییر، از «⚙️ تنظیمات» "
               "روی همان گزینه بزنید.</i>\n\n")
        for group, keys in SETTING_GROUPS:
            buf += "<b>%s</b>\n" % group
            for k in keys:
                info = self._setting_info(k)
                if not info:
                    continue
                _d = self._setting_default(k)
                if isinstance(_d, bool):
                    _d = "روشن" if _d else "خاموش"
                buf += "• %s <b>%s</b> — %s\n  الان: <code>%s</code> · پیش‌فرض: <code>%s</code>\n" % (
                    info.get("icon", ""), info.get("title", k), info.get("what", ""),
                    self._setting_display(k), _d)
            buf += "\n"
            if len(buf) > 3000:                       # مرزِ ۴۰۹۶ نویسه‌ایِ تلگرام
                parts.append(buf)
                buf = ""
        if buf:
            parts.append(buf)
        parts.append("<i>هر تغییر همان لحظه ذخیره می‌شود و تا تغییرِ بعدی می‌ماند.</i>")
        kb = R.kb([[R.btn("⚙️ تنظیمات", "st:menu")], [R.btn("🏠 منوی اصلی", "home")]])
        for i, part in enumerate(parts):
            if i == 0 and edit:
                await self.api.edit_message_text(chat, edit, part, kb=kb)
            else:
                await self.api.send_message(chat, part, kb=kb)

    async def _reset_one_setting(self, chat: int, key: str, *, edit: Optional[int] = None) -> None:
        default = self._setting_default(key)
        try:
            setattr(self.settings, key, default)
            self.db.kv_set("setting:" + key, default)
        except Exception as e:
            await self.api.send_message(chat, "⚠️ نشد: <code>%s</code>" % esc(e))
            return
        show = "روشن" if default is True else ("خاموش" if default is False else str(default))
        await self._setting_detail(chat, key, edit=edit,
                                   note="♻️ به پیش‌فرض برگشت: <code>%s</code>" % esc(show))

    # ── راهِ متنی (وقتی دکمه‌ها دردسر دارند): `/set <کلید> <مقدار>` ──
    @staticmethod
    def _match_setting_key(cand: str) -> Optional[str]:
        """کلیدِ تنظیمات را از نامِ انگلیسی، برچسبِ کوتاه یا عنوانِ فارسی پیدا می‌کند."""
        c = str(cand or "").strip()
        if not c:
            return None
        if c in LABELS or c in SHORT_LABELS:
            return c
        sq = _squash(c)
        for k in SHORT_LABELS:
            if sq and sq in (_squash(SHORT_LABELS[k]), _squash(LABELS.get(k, "")), _squash(k)):
                return k
        return None

    async def _apply_setting_text(self, chat: int, text: str) -> None:
        """`/set <کلید> <مقدار>` — کلیدِ فارسیِ چندکلمه‌ای هم قبول است («دامنهٔ هش کامل»)."""
        words = str(text or "").split()
        if len(words) >= 2:
            for take in (3, 2, 1):                       # بلندترین تطابق را اول امتحان می‌کنیم
                if take >= len(words):
                    continue
                k = self._match_setting_key(" ".join(words[:take]))
                if k:
                    await self._apply_setting(chat, k, " ".join(words[take:]))
                    return
        await self.api.send_message(
            chat,
            "❌ کلیدِ نامعتبر.\nکلیدها (انگلیسی یا برچسبِ فارسی):\n<code>%s</code>\n\n"
            "مثال: <code>/set hash_scope full</code> · <code>/set دامنهٔ هش کامل</code>"
            % " · ".join(sorted(SHORT_LABELS)))

    @staticmethod
    def _norm_value(value: str) -> str:
        """ارقامِ فارسی/عربی و جداکنندهٔ اعشارِ فارسی ⇒ ASCII (تا «۰.۶» هم کار کند)."""
        return str(value or "").strip().translate(_DIGITS).replace("٫", ".").replace("،", ",").lower()

    async def _invalid_setting(self, chat: int, key: str, *, keep: bool = True) -> None:
        """مقدارِ نامعتبر: پیامِ روشن + **حفظِ حالتِ انتظار** تا مقدارِ درستِ بعدی گم نشود."""
        if keep:
            self.pending[chat] = {"kind": "setting", "key": key}
        info = self._setting_info(key)
        choices = self._setting_choices(key)
        lines = ["❌ مقدارِ نامعتبر برای «%s»." % esc(info.get("title", key)),
                 "مقدارِ فعلی: <code>%s</code>" % esc(self._setting_display(key))]
        if info.get("what"):
            lines.append(info["what"])
        if choices:
            lines.append("مقدارهای مجاز: " + " · ".join("<code>%s</code> (%s)" % (esc(str(v)), esc(lab))
                                                        for v, lab, _d in choices))
        elif key in VALUE_HELP:
            lines.append("مقدارهای مجاز: " + VALUE_HELP[key])
        if keep:
            lines.append("دوباره بفرستید (یا /cancel).")
        info2 = self._setting_info(key)
        kb = R.kb([[R.btn("⬅️ توضیحِ همین گزینه", "st:%s" % key)], [R.btn("⚙️ تنظیمات", "st:menu")]]) \
            if info2 else R.kb([[R.btn("⚙️ تنظیمات", "st:menu")]])
        await self.api.send_message(chat, "\n".join(lines), kb=kb)

    async def _ask_setting(self, chat: int, key: str) -> None:
        self.pending[chat] = {"kind": "setting", "key": key}
        info = self._setting_info(key)
        hint = VALUE_HELP.get(key, "یک عدد")
        choices = self._setting_choices(key)
        opts = ""
        if choices:
            opts = "\nمقدارهای مجاز: " + " · ".join("<code>%s</code>" % esc(str(v)) for v, _l, _d in choices)
        await self.api.send_message(
            chat, "✏️ مقدارِ تازهٔ <b>%s</b> را بفرستید.\nمقدارِ فعلی: <code>%s</code>\n(%s)%s" % (
                info.get("title", key), esc(self._setting_display(key)), hint, opts),
            kb=R.kb([[R.btn("⬅️ توضیحِ گزینه", "st:%s" % key)], [R.btn("⚙️ تنظیمات", "st:menu")]]))

    async def _apply_setting(self, chat: int, key: str, value: str, *, silent: bool = False) -> bool:
        """اعتبارسنجی و ذخیره. `silent=True` ⇒ پیامِ تأیید نمی‌فرستد (صفحهٔ توضیح خودش نشان می‌دهد)."""
        v = self._norm_value(value)
        cur = getattr(self.settings, key, None)
        v2: Any = None
        if key in VALUE_ALIASES:                        # گزینه‌ای‌ها: مترادفِ فارسی/انگلیسی
            v2 = VALUE_ALIASES[key].get(v) or VALUE_ALIASES_SQUASHED[key].get(_squash(v))
            if v2 is None:
                await self._invalid_setting(chat, key)
                return False
        elif isinstance(cur, bool):
            if v in _TRUE_WORDS:
                v2 = True
            elif v in _FALSE_WORDS:
                v2 = False
            else:
                await self._invalid_setting(chat, key)
                return False
        elif isinstance(cur, int):
            try:
                v2 = int(float(v))
            except Exception:
                await self._invalid_setting(chat, key)
                return False
            if v2 < 0 or (key == "min_duration_s" and v2 > 3600) or (key == "incr_tail" and v2 > 100000):
                await self._invalid_setting(chat, key)
                return False
        elif isinstance(cur, float):
            try:
                v2 = float(v)
            except Exception:
                await self._invalid_setting(chat, key)
                return False
            if key.startswith("th_") and not (0.0 < v2 <= 1.0):
                await self.api.send_message(
                    chat, "❌ آستانه‌ها باید بین ۰ و ۱ باشند (مثلِ <code>0.6</code>)، نه <code>%s</code>.\n"
                          "دوباره بفرستید." % esc(str(value)),
                    kb=R.kb([[R.btn("⬅️ توضیحِ همین گزینه", "st:%s" % key)]]))
                self.pending[chat] = {"kind": "setting", "key": key}
                return False
            if key == "size_tol_pct" and v2 < 0:
                await self._invalid_setting(chat, key)
                return False
        else:
            v2 = str(value).strip()
        self.pending.pop(chat, None)
        setattr(self.settings, key, v2)
        self.db.kv_set("setting:" + key, v2)
        if silent:
            return True
        info = self._setting_info(key)
        await self.api.send_message(
            chat, "✅ ذخیره شد: <b>%s</b> = <code>%s</code>" % (
                info.get("title", LABELS.get(key, key)), self._setting_display(key)),
            kb=R.kb([[R.btn("⬅️ همین گزینه (توضیح/تغییرِ بعدی)", "st:%s" % key),
                      R.btn("⚙️ تنظیمات", "st:menu")], [R.btn("🏠 منوی اصلی", "home")]]))
        return True

    async def _set_setting_value(self, chat: int, key: str, value: str, *, edit: Optional[int] = None) -> None:
        """کلیک روی دکمهٔ یک مقدارِ مشخص: ذخیره + تازه‌سازیِ همان صفحه (با ✅ روی مقدارِ تازه)."""
        ok = await self._apply_setting(chat, key, value, silent=True)
        info = self._setting_info(key)
        note = "✅ ذخیره شد: <b>%s</b> = <code>%s</code>" % (
            esc(info.get("title", key)), esc(self._setting_display(key))) if ok else ""
        await self._setting_detail(chat, key, edit=edit, note=note)

    # ═════════════════════ ورودِ حسابِ کاربری ═════════════════════
    async def _account_menu(self, chat: int) -> None:
        u = self.user
        status = "✅ وصل" if getattr(u, "ready", False) else "❌ وصل نیست"
        who = ""
        if getattr(u, "ready", False) and getattr(u, "me", None):
            who = "\n👤 <b>%s</b> (@%s · <code>%s</code>)" % (esc(u.me.get("name") or ""), esc(u.me.get("username") or "—"),
                                                            u.me.get("id"))
        rows = [[R.btn("🔑 شروعِ ورود / تغییرِ حساب", "acc:login")],
                [R.btn("📷 ورود با QR (بدونِ کد)", "acc:qr")],
                [R.btn("🔧 تغییرِ api_id/api_hash", "acc:reset")],
                [R.btn("📋 نمایشِ رشتهٔ سشن (SESSion)", "acc:session")],
                [R.btn("🏠 منوی اصلی", "home")]]
        if getattr(u, "ready", False):
            rows.insert(0, [R.btn("🔌 تستِ اتصال", "acc:test"), R.btn("⛔️ قطعِ اتصال", "acc:logout")])
        s = self.settings
        keys_line = ("🔧 <code>api_id</code>/<code>api_hash</code>: ✅ از قبل تنظیم شده "
                     "(فقط شماره و کد لازم است)" if (s.api_id and s.api_hash) else
                     "🔧 <code>api_id</code>/<code>api_hash</code>: باید یک‌بار داده شوند "
                     "(یا در Variables سرویس بگذارید)")
        await self.api.send_message(
            chat,
            "🔑 <b>حسابِ کاربری (برای تاریخچهٔ کامل)</b>\n\n"
            "وضعیت: %s%s\n%s\n\n"
            "با Bot API نمی‌شود پست‌های قبل از ادمین‌شدنِ ربات را دید. با یک حسابِ کاربری (MTProto) "
            "کلِ تاریخچه خوانده می‌شود و ربات می‌تواند از اولین پست اسکن کند.\n\n"
            "🔒 نکته‌های امنیتی: از <b>کدِ ورود و رمزِ دو مرحله‌ای</b> فقط برای همین ورود استفاده می‌شود و "
            "هیچ‌جا ذخیره نمی‌شود؛ فقط «رشتهٔ سشن» در دیتابیسِ سرویس می‌ماند (قابلِ لغو از "
            "Telegram → Devices)." % (status, who, keys_line),
            kb=R.kb(rows))

    # ── گام‌های ورود (فقط آن‌چه لازم است پرسیده می‌شود) ──
    def _login_total(self) -> int:
        """تعدادِ گام‌ها: برای api_id/api_hash فقط اگر تنظیم نشده باشند، + شماره + کد."""
        s = self.settings
        return (0 if s.api_id else 1) + (0 if s.api_hash else 1) + 2

    async def _login_start(self, chat: int) -> None:
        s = self.settings
        p: Dict[str, Any] = {"kind": "login_api_id", "api_id": int(s.api_id or 0),
                             "api_hash": str(s.api_hash or ""), "step": 0}
        self.pending[chat] = p
        total = self._login_total()
        if p["api_id"] and p["api_hash"]:          # همه‌چیز از قبل در Variables هست
            await self._login_ask_phone(chat, total)
            return
        p["step"] += 1
        if p["api_id"]:                            # فقط api_hash می‌خواهیم
            p["kind"] = "login_api_hash"
            await self.api.send_message(
                chat, "🔑 <b>گام %d از %d</b> — <code>api_hash</code> را بفرستید (۳۲ نویسه).\n"
                      "<i>api_id از قبل تنظیم شده است.</i>" % (R.fa_digits(p["step"]), R.fa_digits(total)),
                kb=R.kb([[R.btn("⛔️ انصراف", "acc:cancel")]]))
            return
        await self.api.send_message(
            chat,
            "🔑 <b>گام %s از %s</b> — <code>api_id</code> را بفرستید.\n"
            "از <a href=\"https://my.telegram.org/apps\">my.telegram.org/apps</a> بگیرید (یک عدد است).\n"
            "<i>اگر در Variables سرویس گذاشته باشید، این گام‌ها پریده می‌شوند.</i>"
            % (R.fa_digits(p["step"]), R.fa_digits(total)),
            kb=R.kb([[R.btn("⛔️ انصراف", "acc:cancel")]]))

    async def _login_ask_phone(self, chat: int, total: int) -> None:
        p = self.pending.setdefault(chat, {})
        p["kind"] = "login_phone"
        p["step"] = total - 1
        await self.api.send_message(
            chat,
            "🔑 <b>گام %s از %s</b> — شمارهٔ همان حسابِ تلگرام.\n\n"
            "👇 روی دکمهٔ <b>«📱 ارسالِ شمارهٔ من»</b> بزنید تا خودش برود (بدونِ تایپ)، "
            "یا شماره را با کدِ کشور بنویسید: <code>+98912…</code>"
            % (R.fa_digits(p["step"]), R.fa_digits(total)),
            kb=R.reply_kb([[R.contact_btn()], [R.text_btn("⛔️ انصراف")]],
                          placeholder="شماره را تایپ کنید یا دکمهٔ بالا را بزنید"))

    async def _login_phone_got(self, chat: int, raw_phone: str, m: Optional[Dict[str, Any]] = None) -> None:
        phone = norm_phone(raw_phone)
        if phone.startswith("+0"):        # شمارهٔ محلیِ بدونِ کدِ کشور (مثلِ 0912…)
            await self.api.send_message(
                chat, "❌ شماره باید <b>با کدِ کشور</b> باشد.\nشما فرستادید: <code>%s</code>\n"
                      "درست: <code>+%s</code> (بدونِ صفرِ اول)\n"
                      "یا دکمهٔ <b>«📱 ارسالِ شمارهٔ من»</b> را بزنید تا خودش درست برود." % (
                          esc(phone), esc(phone[2:])),
                kb=R.reply_kb([[R.contact_btn()], [R.text_btn("⛔️ انصراف")]]))
            return
        if not looks_like_phone(phone):
            await self.api.send_message(chat, "❌ شماره نامعتبر: <code>%s</code>\nمثلِ <code>+98912…</code>"
                                              % esc(str(raw_phone)[:30]))
            return
        p = self.pending.get(chat) or {}
        p["phone"] = phone
        if m:
            await self._try_delete(chat, m.get("message_id"))
        await self._login_send_code(chat, p, self._login_total())

    async def _login_send_code(self, chat: int, p: Dict[str, Any], total: int, *, resend: bool = False) -> None:
        try:
            self.user.api_id = int(p.get("api_id") or self.settings.api_id or 0)
            self.user.api_hash = str(p.get("api_hash") or self.settings.api_hash or "")
            code_hash = await self.user.send_code(p["phone"])
        except Exception as e:
            log.warning("send_code ناموفق: %s", e)
            low = str(e).lower()
            hint = ""
            if "api_id" in low or "api_hash" in low or "api id" in low:
                hint = ("\n<i>کلیدِ api اشتباه است — با «🔧 تغییرِ api_id/api_hash» پاکش کنید و "
                        "از <a href=\"https://my.telegram.org/apps\">my.telegram.org</a> مقدارِ درست را بگذارید.</i>")
            elif "flood" in low or "too many" in low or "wait" in low:
                hint = "\n<i>تلگرام موقتاً محدود کرده؛ چند دقیقه بعد «🔁 تلاشِ دوباره».</i>"
            await self.api.send_message(
                chat, "❌ ارسالِ کد ناموفق: <code>%s</code>%s" % (esc(e), hint),
                kb=R.kb([[R.btn("🔁 تلاشِ دوباره", "acc:resend"), R.btn("🔧 کلیدها", "acc:reset")],
                         [R.btn("⛔️ انصراف", "acc:cancel")]]))
            return
        p["phone_code_hash"] = code_hash
        p["kind"] = "login_code"
        p["code_tries"] = 0
        p["step"] = total
        self.db.kv_set("api_id", p.get("api_id") or self.settings.api_id)
        self.db.kv_set("api_hash", p.get("api_hash") or self.settings.api_hash)
        head = ("🔁 <b>کدِ تازه فرستاده شد.</b>\n<i>کدِ پیامِ قبلی دیگر کار نمی‌کند.</i>"
                if resend else "🔑 <b>گام %s از %s</b> — کدِ پیامک/تلگرام."
                % (R.fa_digits(p["step"]), R.fa_digits(total)))
        await self.api.send_message(
            chat,
            "%s\n\n%s\n\nمثال: <code>1 2 3 4 5</code> یا <code>1.2.3.4.5</code> یا <code>1-2-3-4-5</code>\n"
            "⏱ کد نیامد؟ «🔁 ارسالِ کدِ تازه». هر بار کدِ تازه بگیرید، <b>آخرین</b> کد معتبر است."
            % (head, R.CODE_FORMAT_HELP),
            kb=R.kb([[R.btn("🔁 ارسالِ کدِ تازه", "acc:resend"), R.btn("⛔️ انصراف", "acc:cancel")]]))

    @staticmethod
    def _parse_code(text: str) -> Tuple[str, str]:
        """کد را از متنِ کاربر درمی‌آورد. خروجی: (کد، how) با how ∈ ok|joined|bad

        ⛔️ «joined» = کدِ ۴ تا ۶ رقمیِ یک‌پارچه؛ تلگرام آن را «قبلاً به‌اشتراک‌گذاشته»
        می‌شمارد و ورود را بلاک می‌کند (با خطای گمراه‌کنندهٔ «code has expired»).
        برای همین حالت هیچ‌وقت `sign_in` صدا زده نمی‌شود.
        """
        raw = norm_digits(str(text or "")).strip()
        compact = re.sub(r"[\s.\-_,،:؛|/\\]+", "", raw)
        if not compact.isdigit():
            return "", "bad"
        if 4 <= len(compact) <= 6 and re.search(r"[\s.\-_,،:؛|/\\]", raw):
            return compact, "ok"
        if 4 <= len(compact) <= 6:
            return "", "joined"
        return "", "bad"

    @staticmethod
    def _login_err_kind(res: Dict[str, Any]) -> str:
        k = str(res.get("kind") or "").lower()
        if k:
            return k
        low = str(res.get("error") or "").lower()
        if "expired" in low:
            return "expired"
        if "flood" in low or "too many" in low:
            return "flood"
        if "invalid" in low:
            return "invalid"
        return "other"

    async def _login_step(self, chat: int, p: Dict[str, Any], text: str, m: Dict[str, Any]) -> None:
        kind = p["kind"]
        total = self._login_total()
        if kind == "login_api_id":
            if not text.isdigit() or not (1 <= len(text) <= 10):
                await self.api.send_message(chat, "❌ api_id باید عدد باشد.")
                return
            p["api_id"] = int(text)
            self.settings.api_id = p["api_id"]
            self.db.kv_set("api_id", p["api_id"])
            await self._try_delete(chat, m.get("message_id"))
            p["step"] = 1 if not self.settings.api_hash else 1
            if self.settings.api_hash:
                await self._login_ask_phone(chat, total)
                return
            p["kind"] = "login_api_hash"
            p["step"] += 1
            await self.api.send_message(chat, "🔑 <b>گام %s از %s</b> — <code>api_hash</code> را بفرستید (۳۲ نویسه)."
                                              % (R.fa_digits(p["step"]), R.fa_digits(total)))
            return
        if kind == "login_api_hash":
            if len(text.strip()) < 20:
                await self.api.send_message(chat, "❌ api_hash نامعتبر (۳۲ نویسه لازم است).")
                return
            p["api_hash"] = text.strip()
            self.settings.api_hash = p["api_hash"]
            self.db.kv_set("api_hash", p["api_hash"])
            await self._try_delete(chat, m.get("message_id"))
            p["step"] = 1 if not self.settings.api_id else 1
            await self._login_ask_phone(chat, total)
            return
        if kind == "login_phone":
            if text.strip() in ("⛔️ انصراف", "انصراف", "لغو", "/cancel"):
                await self._login_cancel(chat)
                return
            await self._login_phone_got(chat, text, m)
            return
        if kind == "login_code":
            await self._try_delete(chat, m.get("message_id"))
            code, how = self._parse_code(text)
            if how == "joined":
                log.warning("کدِ یک‌پارچه آمد؛ sign_in صدا زده نشد (ریسکِ بلاکِ «code previously shared»)")
                await self.api.send_message(
                    chat,
                    "⚠️ <b>این کد را قبول نکردم</b> — چون تلگرام کدِ به‌هم‌چسبیده را "
                    "«قبلاً به‌اشتراک‌گذاشته» می‌شمارد و ورود را بلاک می‌کند "
                    "(همان پیامِ «Incomplete login attempt»).\n"
                    "♻️ <b>خودم کدِ تازه فرستادم</b> — این کد دیگر معتبر نیست:\n\n" + R.CODE_FORMAT_HELP)
                p["code_tries"] = int(p.get("code_tries") or 0) + 1
                if int(p.get("code_tries") or 0) <= 3:
                    await self._login_send_code(chat, p, total, resend=True)
                return
            if how == "bad":
                await self.api.send_message(
                    chat, "❌ این متن کدِ ورود نیست.\n" + R.CODE_FORMAT_HELP,
                    kb=R.kb([[R.btn("🔁 ارسالِ کدِ تازه", "acc:resend"), R.btn("⛔️ انصراف", "acc:cancel")]]))
                return
            res = await self.user.sign_in(p["phone"], code, p.get("phone_code_hash") or "")
            if res.get("ok"):
                self.pending.pop(chat, None)
                self.db.kv_set("session_string", self.user.session_string)
                log.info("حسابِ کاربری وصل شد (id=%s)", (self.user.me or {}).get("id"))
                await self.api.send_message(
                    chat, "✅ حساب وصل شد: <b>%s</b>\nاز این پس «🔍 اسکن کامل» کلِ تاریخچه را می‌خواند."
                          % esc((self.user.me or {}).get("name") or ""), kb_extra=R.remove_kb(),
                    kb=R.kb([[R.btn("📡 کانال‌ها", "ch:list")], [R.btn("🏠 منوی اصلی", "home")]]))
                return
            if res.get("need_password") or self._login_err_kind(res) == "password":
                p["kind"] = "login_password"
                p["pass_tries"] = 0
                await self.api.send_message(
                    chat, "🔐 <b>این حساب رمزِ دو مرحله‌ای (Two-Step) دارد.</b>\n"
                          "رمزِ حساب را بفرستید (بعد از ذخیره، پیامتان را پاک می‌کنم).",
                    kb=R.kb([[R.btn("⛔️ انصراف", "acc:cancel")]]))
                return
            ek = self._login_err_kind(res)
            log.warning("ورود ناموفق (%s): %s", ek, res.get("error"))
            if ek == "expired":
                await self.api.send_message(
                    chat, "⌛️ <b>این کد پذیرفته نشد.</b>\n"
                          "دو علتِ رایج: ۱) کدِ پیامِ قبلی را زده‌اید  ۲) تلگرام کد را «قبلاً به‌اشتراک‌گذاشته» "
                          "می‌داند (اگر پیامِ «Incomplete login attempt» در تلگرام آمده، همین است).\n"
                          "«🔁 ارسالِ کدِ تازه» را بزنید و <b>آخرین</b> کد را <b>رقم‌رقم</b> بفرستید:\n"
                          "<code>1 2 3 4 5</code>",
                    kb=R.kb([[R.btn("🔁 ارسالِ کدِ تازه", "acc:resend"), R.btn("⛔️ انصراف", "acc:cancel")]]))
                return
            if ek == "invalid":
                await self.api.send_message(
                    chat, "❌ کد اشتباه است. همان آخرین کد را با دقت بفرستید، یا «🔁 ارسالِ کدِ تازه».",
                    kb=R.kb([[R.btn("🔁 ارسالِ کدِ تازه", "acc:resend"), R.btn("⛔️ انصراف", "acc:cancel")]]))
                return
            if ek == "flood":
                await self.api.send_message(
                    chat, "⏳ تلگرام موقتاً اجازهٔ درخواستِ کد نمی‌دهد (<code>%s</code>).\n"
                          "چند دقیقه صبر کنید و بعد «🔁 ارسالِ کدِ تازه» را بزنید." % esc(res.get("error")),
                    kb=R.kb([[R.btn("🔁 ارسالِ کدِ تازه", "acc:resend"), R.btn("⛔️ انصراف", "acc:cancel")]]))
                return
            await self.api.send_message(
                chat, "❌ ورود ناموفق: <code>%s</code>" % esc(res.get("error")),
                kb=R.kb([[R.btn("🔁 ارسالِ کدِ تازه", "acc:resend"), R.btn("🔑 از اول", "acc:login")]]))
            return
        if kind == "login_password":
            await self._try_delete(chat, m.get("message_id"))
            tries = int(p.get("pass_tries") or 0) + 1
            p["pass_tries"] = tries
            res = await self.user.sign_in_password(text)
            if res.get("ok"):
                self.pending.pop(chat, None)
                self.db.kv_set("session_string", self.user.session_string)
                log.info("رمزِ دو مرحله‌ای پذیرفته شد؛ سشن ذخیره شد")
                await self.api.send_message(
                    chat, "✅ رمز پذیرفته شد و حساب وصل است.",
                    kb=R.kb([[R.btn("📡 کانال‌ها", "ch:list")], [R.btn("🏠 منوی اصلی", "home")]]))
                return
            log.warning("رمز اشتباه (%s/%d): %s", tries, 3, res.get("error"))
            if tries >= 3:
                self.pending.pop(chat, None)
                await self.api.send_message(
                    chat, "❌ سه بار رمز اشتباه بود. برای امنیت، ورود لغو شد.\n"
                          "دوباره از «🔑 اتصالِ حسابِ کاربری» شروع کنید.",
                    kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")], [R.btn("🏠 منوی اصلی", "home")]]))
                return
            await self.api.send_message(
                chat, "❌ رمز اشتباه: <code>%s</code>\nتلاشِ %s از ۳ — دوباره رمز را بفرستید."
                      % (esc(res.get("error")), R.fa_digits(tries)),
                kb=R.kb([[R.btn("⛔️ انصراف", "acc:cancel")]]))
            return

    async def _login_resend(self, chat: int) -> None:
        p = self.pending.get(chat) or {}
        if not p.get("phone"):
            await self.api.send_message(chat, "⌛️ گامِ ورود منقضی شده. دوباره «🔑 اتصالِ حسابِ کاربری» را بزنید.",
                                        kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")]]))
            return
        await self._login_send_code(chat, p, self._login_total(), resend=True)

    # ── ورود با QR: بدونِ کدِ ورود ⇒ بدونِ ریسکِ «code previously shared» ──
    async def _qr_login_start(self, chat: int) -> None:
        self.pending.pop(chat, None)
        if not (self.settings.api_id and self.settings.api_hash):
            await self.api.send_message(
                chat, "❌ برای ورود با QR هم <code>api_id</code>/<code>api_hash</code> لازم است.",
                kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")]]))
            return
        self.user.api_id = int(self.settings.api_id or 0)
        self.user.api_hash = str(self.settings.api_hash or "")
        info = await self.user.qr_login_start()
        if not info or not info.get("url"):
            await self.api.send_message(
                chat, "❌ شروعِ ورود با QR ناموفق بود: <code>%s</code>" % esc(getattr(self.user, "last_error", "")),
                kb=R.kb([[R.btn("🔑 ورودِ کدی", "acc:login")], [R.btn("🏠 منوی اصلی", "home")]]))
            return
        sent = await self.api.send_message(chat, self._qr_text(info["url"], 0))
        if self._qr_task and not self._qr_task.done():
            self._qr_task.cancel()
        self._qr_task = asyncio.create_task(self._qr_login_wait(chat, int(sent["message_id"])))

    @staticmethod
    def _qr_text(url: str, refresh: int) -> str:
        head = "📷 <b>ورود با QR — بدونِ کدِ ورود</b>"
        if refresh:
            head += "\n<i>♻️ توکنِ تازه (نوبتِ %d). لینکِ قبلی باطل شد.</i>" % refresh
        return (head + "\n\n"
                "۱) روی همین لینک بزنید و در تلگرام «تأیید» را بزنید:\n"
                "<a href=\"%s\">🔓 تأییدِ ورود</a>\n\n"
                "۲) اگر باز نشد، این متن را در یک تبِ مرورگر باز کنید یا با دستگاهِ دیگری اسکنش کنید:\n"
                "<code>%s</code>\n\n"
                "⏱ این لینک چند دقیقه اعتبار دارد و خودش تازه می‌شود؛ لازم نیست کاری بکنید."
                % (url, esc(url)))

    async def _qr_login_wait(self, chat: int, mid: int) -> None:
        """تا تأییدِ کاربر صبر می‌کند؛ توکن را تازه می‌کند و در پایان نتیجه را می‌فرستد."""
        try:
            for i in range(8):                      # ~۴ دقیقه (۸ × ۳۰ ثانیه)
                res = await self.user.qr_login_wait(timeout=30.0)
                if res.get("ok"):
                    self.db.kv_set("session_string", self.user.session_string)
                    log.info("ورودِ QR کامل شد")
                    await self.api.edit_message_text(
                        chat, mid, "✅ <b>حساب وصل شد</b> (با تأییدِ QR): <b>%s</b>"
                        % esc((self.user.me or {}).get("name") or ""),
                        kb=R.kb([[R.btn("📡 کانال‌ها", "ch:list")], [R.btn("🏠 منوی اصلی", "home")]]))
                    return
                if not res.get("expired"):
                    break
                url = await self.user.qr_login_recreate()
                if not url:
                    break
                await self.api.edit_message_text(chat, mid, self._qr_text(url, i + 1))
            await self.api.edit_message_text(
                chat, mid,
                "⌛️ <b>این QR منقضی شد.</b>\nدوباره «📷 ورود با QR» را بزنید، یا کدِ ورود را "
                "<b>رقم‌رقم</b> بفرستید: <code>1 2 3 4 5</code>",
                kb=R.kb([[R.btn("📷 QR تازه", "acc:qr")], [R.btn("🔑 ورودِ کدی", "acc:login")]]))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("qr_login_wait خطا: %s", e)

    async def _login_cancel(self, chat: int) -> None:
        self.pending.pop(chat, None)
        await self.api.send_message(chat, "⛔️ ورود لغو شد.", kb=R.kb([[R.btn("🔑 حسابِ کاربری", "acc:menu")]]))

    async def _save_session_from_text(self, chat: int, text: str) -> None:
        s = text.strip()
        if len(s) < 50:
            await self.api.send_message(chat, "❌ رشتهٔ سشن نامعتبر. مثال: <code>/setsession 1BVtsOK…</code>")
            return
        self.user.session_string = s
        self.db.kv_set("session_string", s)
        ok = await self.user.start()
        await self.api.send_message(chat, "✅ ذخیره شد. اتصال: %s" % ("برقرار ✅" if ok else "ناموفق ❌"))

    async def _try_delete(self, chat: int, msg_id: Optional[int]) -> None:
        """حذفِ پیامِ خودِ کاربر در چتِ ربات (برای پاک‌کردنِ کد/رمز). فقط در چتِ همین ربات."""
        if not msg_id:
            return
        try:
            await self.api.delete_message(chat, int(msg_id))
        except Exception:
            pass

    # ═════════════════════ اسکن ═════════════════════
    async def _start_scan_for_all(self, chat: int) -> None:
        chans = self.db.list_channels()
        if not chans:
            await self._channels_menu(chat)
            return
        await self.api.send_message(chat, "🔍 اسکنِ %d کانال پشتِ‌سرهم شروع می‌شود…" % len(chans))
        for c in chans:
            await self._start_scan(chat, int(c["id"]), full=False, wait=True)

    async def _start_scan(self, chat: int, cid: int, *, full: bool, wait: bool = False) -> None:
        c = self.db.get_channel(cid)
        if not c:
            await self.api.send_message(chat, "کانال پیدا نشد.")
            return
        if self.scan and not self.scan.get("done"):
            await self.api.send_message(chat, "⏳ یک اسکن در جریان است. اول «⏹ توقف» را بزنید یا تمام شود.")
            return
        if not getattr(self.user, "ready", False):
            await self.api.send_message(
                chat,
                "⚠️ برای دیدنِ <b>کلِ تاریخچهٔ کانال</b> باید حسابِ کاربری وصل باشد.\n"
                "بدونِ آن، رباتِ معمولی فقط پست‌های بعد از ادمین‌شدنش را می‌بیند.\n\n"
                "• «🔑 اتصالِ حسابِ کاربری» را بزنید (۳۰ ثانیه کار دارد)، یا\n"
                "• اگر می‌خواهید فعلاً بدونِ آن اسکن کنید، دکمهٔ زیر را بزنید.",
                kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")],
                         [R.btn("⚠️ اسکنِ محدود (بدونِ حساب)", "scan:limited:%d" % cid)],
                         [R.btn("⬅️ کانال", "c:%d" % cid)]]))
            return
        if self._scan_lock.locked():
            await self.api.send_message(chat, "⏳ یک اسکن دیگر در جریان است.")
            return
        msg = await self.api.send_message(chat, R.progress_text("index", R.channel_title(c), 0.0), kb=R.progress_kb())
        self.scan = {"chat_id": chat, "msg_id": int(msg.get("message_id") or 0), "done": False,
                     "channel": c, "cid": cid, "full": full, "started": time.time()}

        async def on_progress(p: Progress) -> None:
            if self.scan and not self.scan.get("done"):
                try:
                    await self.api.edit_message_text(chat, self.scan["msg_id"],
                        R.progress_text(p.phase, R.channel_title(c), p.pct, seen=p.seen, total=p.total,
                                        files=p.files, hashed=p.hashed, hash_total=p.hash_total, note=p.note,
                                        cur_id=p.last_msg_id, top_id=p.top_id),
                        kb=R.progress_kb() if p.phase not in ("done", "canceled", "error") else None)
                except TgError:
                    pass

        scanner = self._scanner_factory(on_progress=on_progress)
        self.scan["scanner"] = scanner

        async def runner() -> None:
            self.user.set_hint(int(c.get("tg_id") or 0), username=str(c.get("username") or ""),
                               title=str(c.get("title") or ""))
            async with self._scan_lock:
                res: ScanResult = await scanner.run(c, full=full)
            self._remember_peer_hashes()          # access_hashهای تازه در DB می‌مانند
            await self._finish_scan(res, c)

        self.scan["task"] = asyncio.create_task(runner())
        if wait:
            try:
                await self.scan["task"]
            except Exception:
                pass

    async def _finish_scan(self, res: ScanResult, c: Dict[str, Any]) -> None:
        sc = self.scan or {}
        self.scan = dict(sc, done=True, result=res)
        chat = int(sc.get("chat_id") or 0)
        scan = self.db.get_scan(res.scan_id) or {}
        counts = {
            "exact": self.db.count_groups(res.scan_id, signal="exact"),
            "content": self.db.count_groups(res.scan_id, signal="content"),
            "sizetime": self.db.count_groups(res.scan_id, signal="sizetime"),
            "name": self.db.count_groups(res.scan_id, signal="name"),
            "caption": self.db.count_groups(res.scan_id, signal="caption"),
        }
        head = {"done": "✅ اسکن تمام شد", "canceled": "⏹ اسکن کنسل شد", "error": "⚠️ خطا در اسکن"}.get(res.status, res.status)
        self._store_notes(scan, getattr(res, "notes", None))
        txt = "%s\n\n%s" % (head, R.scan_summary_text(scan, c, counts,
                                                       total_indexed=self.db.count_files(int(c["id"])),
                                                       notes=self._scan_notes(scan)))
        rows = []
        if res.groups:
            rows.append([R.btn("🔁 دیدنِ %d گروهِ تکراری" % res.groups, "l:%d:%d:all:0" % (res.scan_id, res.channel_id))])
            rows.append([R.btn("📤 فورواردِ همهٔ تکراری‌ها", "fa:%d:%d:all:0" % (res.scan_id, res.channel_id))])
        rows.append([R.btn("🔍 اسکن مجدد", "scan:full:%d" % res.channel_id), R.btn("📡 کانال", "c:%d" % res.channel_id)])
        rows.append([R.btn("🏠 منوی اصلی", "home")])
        try:
            await self.api.edit_message_text(chat, int(sc.get("msg_id") or 0), txt, kb=R.kb(rows))
        except Exception:
            await self.api.send_message(chat, txt, kb=R.kb(rows))
        if chat:
            await self.api.send_chat_action(chat, "typing")
        if self.scan and self.scan.get("task") and not self.scan["task"].done():
            pass

    async def _cancel_scan(self, chat: int) -> None:
        if not self.scan or self.scan.get("done"):
            await self.api.send_message(chat, "ℹ️ اسکنی در جریان نیست.")
            return
        sc = self.scan.get("scanner")
        if sc:
            sc.cancel()
        await self.api.send_message(chat, "⏹ درخواستِ توقف فرستاده شد…")

    async def _scan_limited(self, chat: int, cid: int) -> None:
        """اسکنِ محدود (بدونِ حسابِ کاربری) از **پیش‌نمایشِ عمومیِ** `t.me/s/<username>`.

        چه چیزی دارد: شمارهٔ پیام، تاریخ، کپشن و زمانِ ویدیو. چه چیزی ندارد: حجمِ فایل و
        کلِ تاریخچه. پس گروه‌ها فقط بر پایهٔ نام/کپشن ساخته می‌شوند و فورواردِ فایل ممکن
        نیست (به‌جایش «🔗 لینکِ پیام‌ها»).
        """
        c = self.db.get_channel(cid)
        if not c:
            await self.api.send_message(chat, "این کانال پیدا نشد.")
            return
        uname = str(c.get("username") or "").lstrip("@").strip()
        if not uname:
            await self.api.send_message(
                chat,
                "⚠️ اسکنِ محدود فقط برای کانال‌های <b>عمومی</b> (با یوزرنیم) کار می‌کند؛ "
                "دلیلش این است که تلگرام تاریخچهٔ کانالِ خصوصی را بدونِ حسابِ کاربری نمی‌دهد.\n\n"
                "دو راهِ عملی:\n"
                "① «🔑 اتصالِ حسابِ کاربری» (۳۰ ثانیه) ⇒ اسکنِ کامل با حجم و هش\n"
                "② اگر کانال را خودتان ادمینید، «➕ ادمین‌کردنِ ربات» و بعد پست‌های تازه را "
                "بفرستید تا با متن/کپشن مقایسه شود\n"
                "③ یوزرنیمِ عمومیِ کانال را به ربات بدهید تا این حالت کار کند.",
                kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")],
                         [R.btn("📡 کانال", "c:%d" % cid)]]))
            return
        if self._scan_lock.locked():
            await self.api.send_message(chat, "⏳ یک اسکن دیگر در جریان است.")
            return
        msg = await self.api.send_message(
            chat, R.progress_text("index", c.get("title") or uname, 2.0,
                                  note="حالتِ محدود: خواندنِ پیش‌نمایشِ عمومیِ t.me/s/%s…" % uname),
            kb=R.progress_kb())
        mid = int(msg.get("message_id") or 0)
        from .scanner import _with_norms
        from . import matching as M
        cfg = dict(self.cfg_dict())
        cfg["hash_mode"] = "off"                       # بدونِ دانلود ⇒ هشی در کار نیست
        pages = max(1, int(getattr(self.settings, "preview_pages", 6) or 6))
        per_msg_ids = 20
        rows: Dict[int, Dict[str, Any]] = {}
        before = 0
        stop = False
        for page in range(pages):
            try:
                html_txt = await self.preview_fetch(uname, before=before)
            except Exception as e:
                log.info("preview fetch خطا (%s): %s", uname, e)
                html_txt = ""
            page_rows = P.parse_messages(html_txt, uname)
            fresh = [r for r in page_rows if int(r["msg_id"]) not in rows]
            for r in fresh:
                r["channel_id"] = cid
                rows[int(r["msg_id"])] = r
            oldest = P.oldest_id(page_rows)
            pct = min(66.0, 66.0 * float(page + 1) / float(pages))
            try:
                await self.api.edit_message_text(
                    chat, mid,
                    R.progress_text("index", c.get("title") or uname, pct,
                                    files=len(rows),
                                    note="صفحهٔ %d از %d · پیام‌های دیده‌شده: %d"
                                         % (page + 1, pages, len(rows))),
                    kb=R.progress_kb())
            except TgError:
                pass
            if not page_rows or not oldest or oldest == before or len(fresh) < per_msg_ids:
                stop = True                              # صفحهٔ خالی ⇒ به ابتدای کانال رسیدیم
            before = oldest or before
            if stop:
                break
            await asyncio.sleep(float(getattr(self.settings, "preview_delay", 1.2) or 0))
        lst = list(rows.values())
        if not lst:
            try:
                await self.api.edit_message_text(
                    chat, mid, "⚠️ هیچ پستِ رسانه‌ای در پیش‌نمایشِ عمومیِ <code>%s</code> پیدا نشد.\n"
                               "أما حسابِ کاربری وصل کنید تا کلِ تاریخچه خوانده شود." % esc(uname))
            except TgError:
                pass
            return
        scan_id = self.db.create_scan(cid, {"mode": "preview", "pages": pages,
                                            "media_kinds": cfg.get("media_kinds")})
        self.db.upsert_files(_with_norms(lst))
        # باگِ گزارش‌شده: قبلاً `find_clusters` روی **همهٔ** فایل‌های ذخیره‌شدهٔ کانال اجرا می‌شد،
        # پس خروجی می‌توانست گروه‌هایی باشد که هیچ ربطی به صفحاتِ تازهٔ پیش‌نمایش ندارند (و
        # روی کانالِ حجیم کند هم بود). حالا فقط جفت‌هایی بررسی می‌شوند که **یک سرشان در همین
        # پنجرهٔ تازه** باشد؛ در نتیجه هر گروه حداقل یک پستِ تازه دارد.
        window_msgs = set(int(x) for x in rows.keys())
        all_files = _with_norms(self.db.files_of_channel(cid))
        win_idx = {i for i, f in enumerate(all_files) if int(f.get("msg_id") or 0) in window_msgs}
        pairs = [(a, b) for a, b in M.candidate_pairs(all_files, cfg) if a in win_idx or b in win_idx]
        clusters = M.find_clusters(all_files, cfg, pairs=pairs)
        clusters = [cl for cl in clusters
                    if any(int(fid) in {int(all_files[i]["id"]) for i in win_idx} for fid in cl["ids"])]
        self.db.replace_groups(scan_id, cid, clusters)
        note = ("این «اسکنِ محدود» است: فقط %s صفحهٔ آخرِ کانالِ عمومی (پست‌های تازه) و فقط بر پایهٔ "
                "کپشن/نام — حجم و هش در دسترسِ تلگرام نیست و **فورواردِ فایل ممکن نیست** "
                "(از «🔗 لینکِ پیام‌ها» استفاده کنید). هر گروه دستِ‌کم یک پستِ تازه دارد. "
                "برای نتیجهٔ کامل، حسابِ کاربری را وصل کنید." % pages)
        self.db.update_scan(scan_id, status="done", phase="done", finished_at=int(time.time()),
                            total_msgs=len(lst), seen_msgs=len(lst), files_found=len(lst),
                            hashed=0, groups_found=len(clusters),
                            params=json.dumps({"mode": "preview", "pages": pages, "notes": [note]},
                                              ensure_ascii=False))
        self.db.set_channel_scan(cid, scan_id, int(time.time()))
        try:
            await self.api.edit_message_text(chat, mid, "✅ اسکنِ محدود تمام شد — گزارش:",
                                             kb=None)
        except TgError:
            pass
        await self._summary(chat, scan_id, cid)

    # ═════════════════════ نتیجه‌ها ═════════════════════
    @staticmethod
    def _scan_is_preview(scan: Dict[str, Any]) -> bool:
        """آیا این اسکن «محدود/پیش‌نمایش» بوده؟ (پس فایل قابلِ‌فوروارد وجود ندارد)"""
        try:
            prm = scan.get("params")
            data = json.loads(prm) if isinstance(prm, str) else (prm or {})
            return str((data or {}).get("mode") or "") == "preview"
        except Exception:
            return False

    @staticmethod
    def _scan_notes(scan: Dict[str, Any]) -> List[str]:
        """هشدارهای ذخیره‌شدهٔ اسکن (در `params` به‌صورتِ JSON نگه داشته می‌شوند)."""
        try:
            params = scan.get("params")
            data = json.loads(params) if isinstance(params, str) else (params or {})
            notes = data.get("notes") if isinstance(data, dict) else None
            return [str(x) for x in notes] if isinstance(notes, list) else []
        except Exception:
            return []


    def _store_notes(self, scan: Dict[str, Any], notes: Optional[List[str]]) -> None:
        """هشدارها را در `params` می‌نویسد تا در گزارش‌های بعدی هم دیده شوند."""
        if not notes:
            return
        try:
            params = scan.get("params")
            data = json.loads(params) if isinstance(params, str) else (params or {})
            if not isinstance(data, dict):
                data = {}
            data["notes"] = [str(x) for x in notes]
            self.db.update_scan(int(scan.get("id") or 0), params=json.dumps(data, ensure_ascii=False))
        except Exception:
            pass

    async def _summary(self, chat: int, scan_id: int, cid: int, edit: Optional[int] = None) -> None:
        scan = self.db.get_scan(scan_id)
        c = self.db.get_channel(cid)
        if not scan or not c:
            await self.api.send_message(chat, "اسکن پیدا نشد.")
            return
        counts = {"exact": self.db.count_groups(scan_id, signal="exact"),
                  "content": self.db.count_groups(scan_id, signal="content"),
                  "sizetime": self.db.count_groups(scan_id, signal="sizetime"),
                  "name": self.db.count_groups(scan_id, signal="name"),
                  "caption": self.db.count_groups(scan_id, signal="caption")}
        txt = R.scan_summary_text(scan, c, counts, total_indexed=self.db.count_files(cid),
                                  notes=self._scan_notes(scan))
        rows = [[R.btn("🔁 دیدنِ گروه‌ها", "l:%d:%d:all:0" % (scan_id, cid))],
                [R.btn("📤 فورواردِ همهٔ تکراری‌ها", "fa:%d:%d:all:0" % (scan_id, cid))],
                [R.btn("🔍 اسکن مجدد", "scan:full:%d" % cid), R.btn("📡 کانال", "c:%d" % cid)]]
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, txt, kb=R.kb(rows))

    async def _groups_list(self, chat: int, scan_id: int, cid: int, filt: str, page: int,
                           edit: Optional[int] = None) -> None:
        kw: Dict[str, Any] = {}
        if filt == "exact":
            kw["signal"] = "exact"
        elif filt in ("content", "sizetime", "name", "caption"):
            kw["signal"] = filt
        if filt == "open":
            kw["only_open"] = True
        groups = self.db.groups_of_scan(scan_id, **kw)
        ps = max(1, int(self.settings.page_size or 8))
        pages = max(1, (len(groups) + ps - 1) // ps)
        page = max(0, min(page, pages - 1))
        chunk = groups[page * ps: (page + 1) * ps]
        c = self.db.get_channel(cid) or {}
        txt = R.groups_page_text(c, chunk, page, pages, filt, len(groups))
        keyboard = R.groups_kb(cid, scan_id, filt, page, pages, chunk)
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=keyboard)
        else:
            await self.api.send_message(chat, txt, kb=keyboard)

    async def _group_view(self, chat: int, scan_id: int, cid: int, filt: str, page: int, gid: int,
                          edit: Optional[int] = None) -> None:
        g = self.db.get_group(gid)
        c = self.db.get_channel(cid)
        if not g or not c:
            await self.api.send_message(chat, "گروه پیدا نشد.")
            return
        members = self.db.group_members(gid)
        sc = self.db.get_scan(scan_id) or {}
        preview = self._scan_is_preview(sc)
        txt = R.group_detail_text(c, g, members)
        if preview:
            txt += ("\n\n<i>⚠️ نتیجهٔ «اسکنِ محدود» (پیش‌نمایشِ عمومی) است: حجم/هش در دسترس نبود؛ "
                    "فورواردِ فایل ممکن نیست — از «🔗 لینکِ پیام‌ها» استفاده کنید.</i>")
        keyboard = R.group_kb(cid, scan_id, filt, page, gid, can_forward=not preview)
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=keyboard)
        else:
            await self.api.send_message(chat, txt, kb=keyboard)

    async def _forward_group(self, chat: int, scan_id: int, cid: int, filt: str, page: int, gid: int,
                             offset: int = 0) -> None:
        g = self.db.get_group(gid)
        c = self.db.get_channel(cid)
        if not g or not c:
            return
        if self._scan_is_preview(self.db.get_scan(scan_id) or {}):
            # نتیجهٔ «اسکنِ محدود» فقط کپشن/زمان دارد (نه فایل) ⇒ فوروارد معنا ندارد
            await self.api.send_message(
                chat,
                "⚠️ این گروه از «اسکنِ محدود» آمده و ربات در آن حالت به **خودِ فایل** دسترسی ندارد، "
                "پس فوروارد ممکن نیست.\n"
                "① «🔗 لینکِ پیام‌ها» را بزنید و در کانال ببینید، یا\n"
                "② «🔑 اتصالِ حسابِ کاربری» و بعد «🔍 اسکن کامل» ⇒ فورواردِ تک‌کلیکی.")
            return
        members = self.db.group_members(gid)
        await self.api.send_chat_action(chat, "upload_document")
        res = await self.reporter.forward_group(chat, c, members, offset=offset)
        self.db.log_action("forward", "group=%s sent=%s" % (gid, res["sent"]))
        lines = ["📎 <b>فورواردِ گروه #%s</b>" % gid,
                 "فرستاده‌شده: <b>%s</b> از <b>%s</b>" % (res["sent"], res["total"])]
        if res["failed"]:
            lines.append("⚠️ ناموفق: <code>%s</code> (محتوا محافظت‌شده یا حذف‌شده — لینک‌ها را از دکمهٔ «🔗 لینکِ پیام‌ها» بگیرید)" % (
                ",".join(str(x) for x in res["failed"])))
        if res["remaining"]:
            lines.append("🕘 <b>%d</b> فایلِ دیگر مانده — دکمهٔ ادامه را بزنید." % res["remaining"])
        else:
            lines.append("✅ همهٔ فایل‌های این گروه فرستاده شد. با کلیک روی هر پیام، همان پستِ کانال باز می‌شود.")
        rows = []
        if res["remaining"]:
            rows.append([R.btn("📎 ادامه (%d فایلِ بعدی)" % min(self.reporter.max_per_group, res["remaining"]),
                               "f2:%d:%d:%s:%d:%d:%d" % (scan_id, cid, filt, page, gid, res["offset"]))])
        rows.append([R.btn("🔗 لینکِ پیام‌ها", "u:%d:%d:%d" % (scan_id, cid, gid)),
                     R.btn("⬅️ گروه", "g:%d:%d:%s:%d:%d" % (scan_id, cid, filt, page, gid))])
        await self.api.send_message(chat, "\n".join(lines), kb=R.kb(rows))

    async def _forward_all(self, chat: int, scan_id: int, cid: int, filt: str, offset: int,
                           *, edit: Optional[int] = None, budget: Optional[int] = None) -> None:
        """📤 فورواردِ **همهٔ** تکراری‌های اسکن (یا فیلترِ جاری) پشتِ‌سرهم در چتِ کاربر.

        هر گروه با یک سرتیتر («گروه #۳ · ★★★ · دلیل») و بعد فایل‌هایش می‌آید تا کاربر
        سریع بررسی و خودش تصمیم به پاک‌کردن بگیرد. گروه‌های «🔒 نادیده‌گرفته‌شده» رد می‌شوند
        و هر گروه فقط یک‌بار فرستاده می‌شود.
        """
        c = self.db.get_channel(cid)
        if not c:
            return
        budget = int(budget or self.forward_all_budget)
        kw = {"only_open": True} if filt == "open" else ({} if filt == "all" else {"signal": filt})
        groups = self.db.groups_of_scan(scan_id, **kw)
        todo = []
        for g in groups:
            if str(g.get("state") or "open") == "ignored":       # تصمیمِ کاربر: رد
                continue
            if self.db.kv_get("fwd:%d:%d" % (scan_id, int(g["id"]))):
                continue                                          # قبلاً کامل فرستاده شده
            todo.append(g)
        if not todo:
            await self.api.send_message(
                chat, "✅ چیزی برای فوروارد نمانده — همهٔ گروه‌های این فیلتر قبلاً فرستاده شده‌اند.",
                kb=R.kb([[R.btn("🔁 گروه‌های تکراری", "l:%d:%d:%s:0" % (scan_id, cid, filt))],
                         [R.btn("🏠 منوی اصلی", "home")]]))
            return
        # سهمِ کل **قبل از حلقه** حساب می‌شود تا گزارشِ پایانی درست باشد
        plan: List[Dict[str, Any]] = []
        for g in todo:
            members = [m for m in self.db.group_members(g["id"]) if str(m.get("state") or "") != "ignored"]
            if members:
                plan.append({"g": g, "members": members})
        total_files = sum(len(x["members"]) for x in plan)
        sent_files = 0
        sent_groups = 0
        failed: List[int] = []
        await self.api.send_chat_action(chat, "upload_document")
        for gi, item in enumerate(plan):
            g, members = item["g"], item["members"]
            before_files = sent_files                              # برای شمارشِ درستِ گروه‌های واقعاً فرستاده‌شده
            if sent_files >= budget:                              # سهمِ این نوبت تمام شد
                break
            gid = int(g["id"])
            stars = R.STARS.get(int(g.get("strength") or 0), "★")
            # در هر گروه، قدیمی‌ترین پست «اصلی» و بقیه «تکراری» در نظر گرفته می‌شود
            by_id = sorted(members, key=lambda m: int(m.get("msg_id") or 0))
            orig = int(by_id[0].get("msg_id") or 0)
            dupes = [int(m.get("msg_id") or 0) for m in by_id[1:]]
            # اگر نوبتِ قبل وسطِ همین گروه تمام شد، از همان‌جا ادامه می‌دهیم (فایل دوباره فرستاده نمی‌شود)
            off = int(self.db.kv_get("fwd:%d:%d:off" % (scan_id, gid), 0) or 0)
            if off > 0:
                await self.api.send_message(
                    chat, "📤 <b>ادامهٔ گروهِ %d از %d</b> %s — از فایلِ %d ادامه می‌دهیم." % (
                        gi + 1, len(plan), stars, off + 1))
            else:
                head = ("📤 <b>گروهِ %d از %d</b> %s\n<b>%s</b> · %d فایل\n<i>%s</i>\n"
                        "🆕 اصلی‌ترین پست: <code>%s</code> · تکراری‌ها: <code>%s</code>" % (
                            gi + 1, len(plan), stars, esc(R.channel_title(c)), len(by_id),
                            esc(g.get("reason") or ""), orig,
                            ", ".join(str(x) for x in dupes[:25]) or "—"))
                await self.api.send_message(chat, head)
            # فایل‌ها را تا سقفِ این نوبت می‌فرستیم؛ گروه فقط وقتی «تمام‌شده» علامت می‌خورد
            # که همهٔ اعضایش فرستاده شده باشند (تا با «ادامه» ناقص نماند).
            while off < len(by_id) and sent_files < budget:
                res = await self.reporter.forward_group(chat, c, by_id, offset=off)
                sent_files += res["sent"]
                failed += res["failed"]
                off = res["offset"]
                if res["sent"] == 0:
                    break                                         # چیزی نرفت ⇒ بی‌فایده است ادامه
            if sent_files > before_files:
                sent_groups += 1
            full = (off >= len(by_id))
            if full:
                self.db.kv_set("fwd:%d:%d" % (scan_id, gid), 1)
                self.db.kv_set("fwd:%d:%d:off" % (scan_id, gid), 0)
            else:
                self.db.kv_set("fwd:%d:%d:off" % (scan_id, gid), int(off))   # ادامه از همین‌جا
            self.db.log_action("fwd_all", "scan=%s group=%s sent_files=%s full=%s" % (
                scan_id, gid, sent_files, full))
        remaining_groups = len([g for g in todo if not self.db.kv_get("fwd:%d:%d" % (scan_id, int(g["id"])))])
        # تصویرِ کاملِ فیلتر (نه فقط این نوبت)
        all_sel = [g for g in groups if str(g.get("state") or "open") != "ignored"]
        all_files = sum(len([m for m in self.db.group_members(g["id"]) if str(m.get("state") or "") != "ignored"])
                        for g in all_sel)
        done_groups = len([g for g in all_sel if self.db.kv_get("fwd:%d:%d" % (scan_id, int(g["id"])))])
        done_files = sum(len([m for m in self.db.group_members(g["id"]) if str(m.get("state") or "") != "ignored"])
                         for g in all_sel if self.db.kv_get("fwd:%d:%d" % (scan_id, int(g["id"]))))
        lines = ["📤 <b>فورواردِ همهٔ تکراری‌ها</b> — %s" % esc(R.channel_title(c)),
                 "این نوبت: <b>%d</b> گروه · <b>%d</b> فایل (از <b>%d</b> فایلی که این نوبت "
                 "در نوبت بود؛ سقفِ هر نوبت <b>%d</b> فایل)" % (
                     sent_groups, sent_files, total_files, budget),
                 "کلِ این فیلتر: <b>%d</b> گروه · <b>%d</b> فایل — تا حالا <b>%d</b> فایل از <b>%d</b> گروه" % (
                     len(all_sel), all_files, done_files, done_groups)]
        if failed:
            lines.append("⚠️ ناموفق: <code>%s</code> (محتوا محافظت‌شده/حذف‌شده — با «🔗 لینکِ پیام‌ها» بگیرید)"
                         % ",".join(str(x) for x in failed[:20]))
        if remaining_groups:
            lines.append("🕘 <b>%d</b> گروهِ دیگر مانده." % remaining_groups)
            lines.append("<i>روی «📤 ادامهٔ فوروارد» بزنید تا بقیه هم بیاید.</i>")
        else:
            lines.append("✅ همهٔ گروه‌های این فیلتر فرستاده شد. حالا در همین چت می‌توانید مقایسه و "
                         "تصمیم بگیرید (ربات خودش هیچ‌چیز را پاک نمی‌کند).")
        rows = []
        if remaining_groups:
            rows.append([R.btn("📤 ادامهٔ فوروارد", "fa:%d:%d:%s:0" % (scan_id, cid, filt))])
        rows.append([R.btn("🔁 گروه‌های تکراری", "l:%d:%d:%s:0" % (scan_id, cid, filt)),
                     R.btn("🏠 منوی اصلی", "home")])
        txt = "\n".join(lines)
        if edit:
            await self.api.edit_message_text(chat, edit, txt, kb=R.kb(rows))
        else:
            await self.api.send_message(chat, txt, kb=R.kb(rows))

    # ═════════════════════ کال‌بک‌ها ═════════════════════
    async def handle_callback(self, cq: Dict[str, Any]) -> None:
        data = str(cq.get("data") or "")
        msg = cq.get("message") or {}
        chat = int((msg.get("chat") or {}).get("id") or 0)
        mid = int(msg.get("message_id") or 0)
        uid = int((cq.get("from") or {}).get("id") or 0)
        cq_id = str(cq.get("id") or "")
        await self.api.answer_callback(cq_id)
        log.info("callback: uid=%s data=%r", uid, data)
        if not await self.is_allowed(uid):
            await self.api.answer_callback(cq_id, "⛔️ دسترسی ندارید", alert=True)
            return
        parts = data.split(":")
        op = parts[0] if parts else ""
        # فقط این‌ها مالکانه می‌مانند: «حسابِ کاربری» (سشنِ تلگرامِ مالک)، «مدیریتِ ادمین‌ها»
        # و «حذفِ کانال از فهرست» (دادهٔ ایندکس را پاک می‌کند). تنظیماتِ تطبیق برای ادمین‌ها آزاد است
        # (پرسشِ کاربر: با حسابِ ادمین، «⚙️ تنظیمات» هیچ کاری نمی‌کرد).
        owner_only_op = op in ("acc", "own") or data.startswith("ch:del:")
        if owner_only_op and not (self.owner_id and int(uid) == int(self.owner_id)):
            await self.api.answer_callback(cq_id, "⛔️ فقط مالکِ ربات به این بخش دسترسی دارد", alert=True)
            # پیامِ روشن هم می‌فرستیم (alertِ گذرا ممکن است دیده نشود ⇒ «کار نمی‌کند»)
            which = "«🔑 حسابِ کاربری»" if op == "acc" else ("«👥 مدیریتِ ادمین‌ها»" if op == "own"
                                                            else "«🗑 حذفِ کانال»")
            await self.api.send_message(
                chat, "⛔️ %s فقط در دستِ <b>مالکِ ربات</b> است.\n"
                      "<i>شما ادمین هستید: اسکن، تنظیمات، نتیجه و فوروارد برایتان آزاد است.</i>" % which)
            return
        try:
            if data == "home" or op == "home":
                await self._menu_main(chat, uid)
            elif op == "help":
                await self.api.send_message(chat, HELP_TEXT, kb=R.kb([[R.btn("🏠 منوی اصلی", "home")]]))
            elif op == "own":
                sub = parts[1] if len(parts) > 1 else "menu"
                if sub == "menu":
                    await self._admins_menu(chat, edit=mid)
                elif sub == "ask":
                    self.pending[chat] = {"kind": "admin_add"}
                    await self.api.send_message(
                        chat,
                        "➕ <b>افزودنِ ادمین</b>\n\nشناسهٔ <b>عددی</b> طرف را بفرستید "
                        "(مثال: <code>123456789</code>) یا یک <b>پیامِ فورواردشده از او</b>.\n"
                        "<i>شناسهٔ خودش را با فرستادنِ <code>/id</code> در چتِ ربات می‌بیند.</i>",
                        kb=R.kb([[R.btn("⬅️ ادمین‌ها", "own:menu")]]))
                elif sub == "delmenu":
                    await self._admins_del_menu(chat, edit=mid)
                elif sub == "add" and len(parts) > 2:
                    target = int(parts[2])
                    name = self.admin_names.get(str(target)) or ""
                    if self.add_admin(target, name):
                        await self.api.send_message(
                            chat, "✅ <b>%s</b> ادمین شد (<code>%d</code>)." % (esc(name or "کاربر"), target),
                            kb=R.kb([[R.btn("👥 ادمین‌ها", "own:menu")]]))
                    else:
                        await self.api.send_message(chat, "ℹ️ این شناسه ادمین نشد (خودِ مالک یا نامعتبر).")
                elif sub == "del" and len(parts) > 2:
                    target = int(parts[2])
                    if self.remove_admin(target):
                        await self.api.send_message(
                            chat, "🗑 ادمین <code>%d</code> حذف شد." % target,
                            kb=R.kb([[R.btn("👥 ادمین‌ها", "own:menu")]]))
                    else:
                        await self.api.send_message(chat, "❌ این کاربر ادمین نبود.")
            elif op == "name":
                await self._ask_channel_name(chat, int(parts[1]))
            elif op == "chk":
                await self._access_check(int(parts[1]), chat, edit=mid)
            elif op == "ch":
                sub = parts[1] if len(parts) > 1 else "list"
                if sub == "list":
                    await self._channels_menu(chat)
                elif sub == "name":
                    await self._ask_channel_name(chat, int(parts[2]))
                elif sub == "chk":
                    await self._access_check(int(parts[2]), chat, edit=mid)
                elif sub == "add":
                    await self._ask_add_channel(chat)
                elif sub == "fix":
                    chans = self.db.list_channels()
                    n = await self._refresh_channel_titles(chans, force=True)
                    if n:
                        await self.api.send_message(chat, "✅ نامِ <b>%d</b> کانال از تلگرام تازه شد." % n)
                    else:
                        await self.api.send_message(
                            chat, "⚠️ نتوانستم نامِ تازه‌ای پیدا کنم.\n"
                                  "دلیل‌های رایج: ربات در آن کانال ادمین نیست، یا حسابِ کاربری وصل نیست.\n"
                                  "<i>می‌توانید «🔑 اتصالِ حسابِ کاربری» کنید یا کانال را با "
                                  "<code>@username</code> دوباره اضافه کنید.</i>",
                            kb=R.kb([[R.btn("🔑 اتصالِ حساب", "acc:login")],
                                     [R.btn("📡 کانال‌ها", "ch:list")]]))
                    await self._channels_menu(chat)
                elif sub == "del":
                    cid = int(parts[2])
                    stats = self.db.delete_channel(cid) or {}
                    await self.api.send_message(
                        chat,
                        "🗑 از فهرستِ ربات حذف شد و تمامِ داده‌هایش از دیتابیس پاک شد:\n"
                        "• فایل‌ها: <b>%s</b>\n• اسکن‌ها: <b>%s</b>\n• گروه‌ها: <b>%s</b>\n"
                        "• اعضای گروه‌ها: <b>%s</b>\n\n"
                        "<i>هیچ فایلی در تلگرام پاک نشد.</i>" % (
                            int(stats.get("files") or 0), int(stats.get("scans") or 0),
                            int(stats.get("groups") or 0), int(stats.get("group_members") or 0)),
                        kb=R.kb([[R.btn("📡 کانال‌ها", "ch:list")]]))
            elif op == "c":
                await self._channel_view(chat, int(parts[1]))
            elif op == "acc":
                sub = parts[1] if len(parts) > 1 else "menu"
                if sub == "menu":
                    await self._account_menu(chat)
                elif sub == "login":
                    await self._login_start(chat)
                elif sub == "resend":
                    await self._login_resend(chat)
                elif sub == "cancel":
                    await self._login_cancel(chat)
                elif sub == "qr":
                    await self._qr_login_start(chat)
                elif sub == "reset":
                    self.pending.pop(chat, None)
                    for k in ("api_id", "api_hash"):
                        self.db.kv_set(k, 0 if k == "api_id" else "")
                    self.settings.api_id = 0
                    self.settings.api_hash = ""
                    self.user.api_id = 0
                    self.user.api_hash = ""
                    await self.api.send_message(
                        chat, "🔧 کلیدهای <code>api_id</code>/<code>api_hash</code> پاک شد.\n"
                              "اکنون یا در Variables سرویس بگذارید، یا با «🔑 شروعِ ورود» از اول وارد کنید.",
                        kb=R.kb([[R.btn("🔑 شروعِ ورود", "acc:login")], [R.btn("🏠 منوی اصلی", "home")]]))
                elif sub == "session":
                    s = self.user.session_string or ""
                    if not s:
                        await self.api.send_message(chat, "سشنی ذخیره نشده.")
                    else:
                        await self.api.send_message(
                            chat,
                            "📋 رشتهٔ سشن (برای متغیرِ محیطی <code>TG_SESSION_STRING</code> یا استفادهٔ مجدد):\n"
                            "<code>%s</code>\n\n⚠️ این رشته مثلِ رمز است — جایی که دیگران می‌بینند نگه ندارید." % esc(s))
                elif sub == "test":
                    ok = await self.user.start()
                    await self.api.send_message(chat, "اتصال: %s" % ("✅ برقرار" if ok else "❌ ناموفق — " + esc(getattr(self.user, "last_error", ""))))
                elif sub == "logout":
                    self.user.session_string = ""
                    self.db.kv_set("session_string", "")
                    await self.user.stop()
                    await self.api.send_message(chat, "⛔️ اتصال قطع شد (برای لغوِ کامل، از Telegram → Devices هم خارج شوید).")
            elif op == "adm":
                await self._make_bot_admin(chat, int(parts[1]))
            elif op == "st":
                sub = parts[1] if len(parts) > 1 else "menu"
                if sub == "menu":
                    await self._settings_menu(chat)
                elif sub == "guide":
                    await self._settings_guide(chat, edit=mid)
                elif sub == "reset":
                    self.db.kv_set("setting:reset", 1)
                    defaults = Settings()
                    for k in LABELS:
                        setattr(self.settings, k, getattr(defaults, k))
                        self.db.kv_set("setting:" + k, getattr(defaults, k))
                    await self.api.send_message(
                        chat, "♻️ همهٔ تنظیمات به پیش‌فرض برگشت.\n"
                              "<i>پیش‌فرض‌ها برای بیشترِ کانال‌ها مناسب‌اند.</i>",
                        kb=R.kb([[R.btn("⚙️ تنظیمات", "st:menu")], [R.btn("🏠 منوی اصلی", "home")]]))
                elif sub in LABELS:
                    await self._setting_detail(chat, sub, edit=mid)     # اول توضیح، بعد انتخاب
            elif op == "sta":
                await self._ask_setting(chat, parts[1])                 # «✏️ تایپ می‌کنم»
            elif op == "stv":
                await self._set_setting_value(chat, parts[1], ":".join(parts[2:]), edit=mid)
            elif op == "std":
                await self._reset_one_setting(chat, parts[1], edit=mid)
            elif op == "scan":
                sub = parts[1]
                if sub == "cancel":
                    await self._cancel_scan(chat)
                elif sub == "all":
                    await self._start_scan_for_all(chat)
                elif sub == "full":
                    await self._start_scan(chat, int(parts[2]), full=True)
                elif sub == "cont":
                    await self._start_scan(chat, int(parts[2]), full=False)
                elif sub == "limited":
                    await self._scan_limited(chat, int(parts[2]))
            elif op == "s":
                await self._summary(chat, int(parts[1]), int(parts[2]), edit=mid)
            elif op in ("l", "p"):
                scan_id, cid, filt = int(parts[1]), int(parts[2]), parts[3]
                page = int(parts[4]) if len(parts) > 4 else 0
                await self._groups_list(chat, scan_id, cid, filt, page, edit=mid)
            elif op == "g":
                scan_id, cid, filt, page, gid = int(parts[1]), int(parts[2]), parts[3], int(parts[4]), int(parts[5])
                await self._group_view(chat, scan_id, cid, filt, page, gid, edit=mid)
            elif op == "f":
                scan_id, cid, filt, page, gid = int(parts[1]), int(parts[2]), parts[3], int(parts[4]), int(parts[5])
                await self._forward_group(chat, scan_id, cid, filt, page, gid, offset=0)
            elif op == "fa":
                scan_id, cid, filt, off = int(parts[1]), int(parts[2]), parts[3], int(parts[4])
                await self._forward_all(chat, scan_id, cid, filt, off, edit=mid)
            elif op == "f2":
                scan_id, cid, filt, page, gid, off = (int(parts[1]), int(parts[2]), parts[3], int(parts[4]),
                                                      int(parts[5]), int(parts[6]))
                await self._forward_group(chat, scan_id, cid, filt, page, gid, offset=off)
            elif op == "u":
                scan_id, cid, gid = int(parts[1]), int(parts[2]), int(parts[3])
                c = self.db.get_channel(cid) or {}
                members = self.db.group_members(gid)
                await self.api.send_message(chat, R.links_text(c, members),
                                            kb=R.kb([[R.btn("⬅️ گروه", "g:%d:%d:all:0:%d" % (scan_id, cid, gid))]]))
            elif op == "m":
                scan_id, cid, gid, state = int(parts[1]), int(parts[2]), int(parts[3]), parts[4]
                self.db.set_group_state(gid, "done" if state == "done" else "ignored")
                await self.api.answer_callback(cq_id, "✅ ثبت شد")
                await self._group_view(chat, scan_id, cid, "all", 0, gid, edit=mid)
            elif op == "nop":
                pass
        except Exception as e:
            log.exception("خطا در کال‌بک %s", data)
            try:
                await self.api.send_message(chat, "⚠️ خطا: <code>%s</code>" % esc(e))
            except Exception:
                pass
