# ── DupFinder — رباتِ پیدا کردنِ فیلم‌های تکراریِ کانال (Railway) ──
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# دیتابیس روی والیومِ Railway (در صورتِ نبود، ./data)
# ⚠️ دستورِ VOLUME در داکرفایل روی Railway پشتیبانی نمی‌شود (خطای build)؛
# والیوم را از داشبورد Railway با Mount path = /data بسازید.
ENV DB_PATH=/data/dup.db

CMD ["python3", "main.py"]
