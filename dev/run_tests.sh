#!/usr/bin/env bash
# اجرای تست‌ها — بدونِ وابستگی به venv (روی این ماشین venv ناقص شد؛ بسته‌ها سرِ جایشان‌اند)
# استفاده:  bash dev/run_tests.sh [-q]
set -e
SP="$(ls -d /home/user/.tools/venv/lib/python*/site-packages 2>/dev/null | head -1)"
cd "$(dirname "$0")/.."
if [ -n "$SP" ]; then
  PYTHONPATH="$SP" python3 -m pytest tests/ "$@"
else
  python3 -m pytest tests/ "$@"     # اگر بسته‌ها سیستم‌نصب بودند
fi
