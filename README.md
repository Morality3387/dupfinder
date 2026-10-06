# 🔁 DupFinder — Duplicate Video Finder Bot for Telegram Channels

A Telegram bot that **scans the full history of your channels**, finds duplicate videos using
**file name → caption → size + duration** (plus a **content hash** for a definitive match), and
**forwards** each duplicate group to your chat so you can jump back to the original post with one click.

> 🛡 **The bot never deletes or edits anything.** It only reads, compares and forwards.
> 🗑 Full Persian guide: **[README.fa.md](README.fa.md)** — راهنمای کاملِ فارسی.

---

## Why

Telegram's Bot API hides a channel's past: a bot sees only posts made **after** it was added as
admin. To read the **whole history** DupFinder also supports an optional **user account (Telethon,
MTProto)** — that is what makes "see every video in the channel" actually work.

## Features

| | |
|---|---|
| 🔍 **Full history scan** | Telethon `messages.getHistory`, old → new |
| 📊 **Live progress bar** | percent + messages scanned + videos found |
| ⏹ **Cancel / resume** | partial results are kept; `🔄 continue` reads only new posts |
| 🧬 **Content hash** | head + middle + tail of each file (3 × 128 KB), partial downloads only |
| 📎 **Forward results** | `forwardMessage` (bot) → `copyMessage` → user-account forward → plain links |
| 📤 **One-tap forward all** | every duplicate group is sent in one go, with a header (original vs duplicates) |
| 📷 **QR login** | connect the user account without ever typing a login code into the chat |
| ➕ **One-tap admin** | the bot adds itself as channel admin (never with delete rights) |
| 🗂 **Grouped output** | ★★★★ hash-identical · ★★★ same size+duration · ★★ similar name · ★ similar caption |
| 📡 **Multi-channel** | tap a channel to scan it, `/scanall` for all of them |
| 🧠 **Smart matching** | Persian/Arabic normalization, episode detection, false-positive guards |
| 💾 **SQLite on a Railway volume** | incremental rescans, group states (`done` / `ignored`) |
| 🇮🇷 **Persian UI** | buttons, filters, Jalali-friendly dates in Tehran time |

## Quick start (Railway)

1. Create a bot with [@BotFather](https://t.me/BotFather) → copy the token.
2. Get your numeric id from [@userinfobot](https://t.me/userinfobot).
3. Push this repo to GitHub → Railway → *Deploy from GitHub repo* (Dockerfile + `railway.json` included).
4. Set variables:

   ```
   BOT_TOKEN=123456:AA...
   OWNER_ID=123456789
   DB_PATH=/data/dup.db
   TG_API_ID=<from my.telegram.org>        # optional but required for full history
   TG_API_HASH=<from my.telegram.org>
   ```
5. Add a **Volume** mounted at `/data`.
6. Add the bot as **admin** of your channel → send `/start` → `➕ افزودنِ کانال` → `🔍 اسکن کامل`.

## Local run / tests (no Telegram needed)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q     # 163 tests
python3 dev/mock_e2e.py         # offline end-to-end demo: prints the real bot messages & buttons
```

## Layout

```
main.py               entrypoint: polling + /health server
app/config.py         Settings (env + DB overrides)
app/similarity.py     normalization, name/caption similarity, size+duration rule
app/db.py             SQLite schema (channels, files, scans, groups, actions)
app/matching.py       candidate pairs, verification, clustering, reason labels
app/scanner.py        scan engine: progress, cancel, candidate hashing
app/user_client.py    Telethon: full history, probe(), partial hash (hash_file/hash_batch)
app/tg_api.py         raw Bot API client (retry, 429/FLOOD_WAIT)
app/report.py         message texts, progress bar, keyboards, Tehran dates
app/bot_app.py        bot logic: menus, wizards, callbacks
dev/fake_telegram.py  offline Telegram simulator
dev/mock_e2e.py       offline demo of the full user journey
tests/                163 tests (unit + end-to-end bot flow + real client path)
```

## Safety

* No `deleteMessage` on channel content — the only deletions are the bot's own
  code/password messages in your private chat.
* Tokens/session strings are never printed in chat and stripped from public settings views.
* Only metadata (name, size, duration, caption, message id, short hash) is stored — videos are never downloaded in full.
* If `OWNER_ID` is empty the bot does **not** hand ownership to the first messenger: a one-time
  claim code is printed in the server log and you must send `/claim <code>` (or set `OWNER_CLAIM_CODE`).

**Version 1.0.0**
