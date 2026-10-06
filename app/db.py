"""لایهٔ دیتابیس (SQLite/WAL) — بدونِ وابستگیِ سنگین، قابلِ تستِ کامل."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id        INTEGER UNIQUE,
  username     TEXT,
  title        TEXT,
  kind         TEXT DEFAULT 'channel',
  added_at     INTEGER DEFAULT 0,
  last_scan_id INTEGER,
  last_scan_at INTEGER,
  paused_min_id INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS files (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id    INTEGER NOT NULL,
  msg_id        INTEGER NOT NULL,
  grouped_id    INTEGER DEFAULT 0,
  date          INTEGER DEFAULT 0,
  doc_id        INTEGER DEFAULT 0,
  file_unique_id TEXT DEFAULT '',
  file_identify  TEXT DEFAULT '',
  file_name      TEXT DEFAULT '',
  name_norm      TEXT DEFAULT '',
  caption        TEXT DEFAULT '',
  caption_norm   TEXT DEFAULT '',
  size           INTEGER DEFAULT 0,
  duration       INTEGER DEFAULT 0,
  mime           TEXT DEFAULT '',
  width          INTEGER DEFAULT 0,
  height         INTEGER DEFAULT 0,
  has_video      INTEGER DEFAULT 0,
  protected      INTEGER DEFAULT 0,
  content_hash   TEXT DEFAULT '',
  hash_scope     TEXT DEFAULT '',
  UNIQUE (channel_id, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_files_ch_size  ON files(channel_id, size);
CREATE INDEX IF NOT EXISTS idx_files_ch_name  ON files(channel_id, name_norm);
CREATE INDEX IF NOT EXISTS idx_files_ch_hash  ON files(channel_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_files_ch_uniq  ON files(channel_id, file_unique_id);
CREATE TABLE IF NOT EXISTS scans (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id   INTEGER NOT NULL,
  started_at   INTEGER DEFAULT 0,
  finished_at  INTEGER DEFAULT 0,
  status       TEXT DEFAULT 'running',         -- running|done|canceled|error
  phase        TEXT DEFAULT '',
  total_msgs   INTEGER DEFAULT 0,
  seen_msgs    INTEGER DEFAULT 0,
  files_found  INTEGER DEFAULT 0,
  hashed       INTEGER DEFAULT 0,
  groups_found INTEGER DEFAULT 0,
  min_id       INTEGER DEFAULT 0,
  max_id       INTEGER DEFAULT 0,
  error        TEXT DEFAULT '',
  params       TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS groups (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id      INTEGER NOT NULL,
  channel_id   INTEGER NOT NULL,
  reason       TEXT DEFAULT '',
  strength     INTEGER DEFAULT 0,
  count        INTEGER DEFAULT 0,
  exact        INTEGER DEFAULT 0,
  sizetime     INTEGER DEFAULT 0,
  state        TEXT DEFAULT 'open',            -- open|done|ignored
  created_at   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_groups_scan ON groups(scan_id, strength, count);
CREATE TABLE IF NOT EXISTS group_members (
  group_id INTEGER NOT NULL,
  file_id  INTEGER NOT NULL,
  PRIMARY KEY (group_id, file_id)
);
CREATE TABLE IF NOT EXISTS actions (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  at        INTEGER DEFAULT 0,
  kind      TEXT DEFAULT '',
  detail    TEXT DEFAULT ''
);
"""


def now() -> int:
    return int(time.time())


class Db:
    """SQLite با یک اتصال و قفلِ async (نوشتن‌ها سبک‌اند؛ گلوگاه شبکه است)."""

    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d) and path != ":memory:":
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = asyncio.Lock()
        self._init()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass

    # ── اجرای کمکی (همگام؛ فقط از داخلِ حلقهٔ async صدا زده می‌شود) ──
    def _exec(self, sql: str, args: Sequence[Any] = ()) -> sqlite3.Cursor:
        cur = self.conn.cursor()
        cur.execute(sql, args)
        return cur

    def _all(self, sql: str, args: Sequence[Any] = ()) -> List[sqlite3.Row]:
        return list(self._exec(sql, args).fetchall())

    def _one(self, sql: str, args: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        r = self._exec(sql, args).fetchone()
        return r

    # ═══════════════ kv ═══════════════
    def kv_get(self, key: str, default: Any = None) -> Any:
        r = self._one("SELECT v FROM kv WHERE k=?", (key,))
        if not r:
            return default
        try:
            return json.loads(r["v"])
        except Exception:
            return r["v"]

    def kv_set(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                   (key, json.dumps(value, ensure_ascii=False)))
        self.conn.commit()

    def kv_all(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for r in self._all("SELECT k,v FROM kv"):
            try:
                out[r["k"]] = json.loads(r["v"])
            except Exception:
                out[r["k"]] = r["v"]
        return out

    # ═══════════════ channels ═══════════════
    def add_channel(self, tg_id: int, title: str = "", username: str = "", kind: str = "channel") -> int:
        cur = self._exec("SELECT id FROM channels WHERE tg_id=?", (tg_id,))
        row = cur.fetchone()
        if row:
            self._exec("UPDATE channels SET title=?, username=?, kind=? WHERE id=?",
                       (title or "", (username or "").lstrip("@"), kind or "channel", row["id"]))
            self.conn.commit()
            return int(row["id"])
        cur = self._exec(
            "INSERT INTO channels(tg_id,title,username,kind,added_at) VALUES(?,?,?,?,?)",
            (tg_id, title or "", (username or "").lstrip("@"), kind or "channel", now()))
        self.conn.commit()
        return int(cur.lastrowid)

    def get_channel(self, cid: int) -> Optional[Dict[str, Any]]:
        r = self._one("SELECT * FROM channels WHERE id=?", (cid,))
        return dict(r) if r else None

    def get_channel_by_tg(self, tg_id: int) -> Optional[Dict[str, Any]]:
        r = self._one("SELECT * FROM channels WHERE tg_id=?", (tg_id,))
        return dict(r) if r else None

    def list_channels(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._all("SELECT * FROM channels ORDER BY id")]

    def delete_channel(self, cid: int) -> None:
        self._exec("DELETE FROM channels WHERE id=?", (cid,))
        self.conn.commit()

    def set_channel_scan(self, cid: int, scan_id: int, at: int) -> None:
        self._exec("UPDATE channels SET last_scan_id=?, last_scan_at=? WHERE id=?", (scan_id, at, cid))
        self.conn.commit()

    def set_paused_min_id(self, cid: int, min_id: int) -> None:
        self._exec("UPDATE channels SET paused_min_id=? WHERE id=?", (int(min_id or 0), cid))
        self.conn.commit()

    # ═══════════════ files ═══════════════
    FILE_COLS = ("channel_id", "msg_id", "grouped_id", "date", "doc_id", "file_unique_id", "file_identify",
                 "file_name", "name_norm", "caption", "caption_norm", "size", "duration", "mime",
                 "width", "height", "has_video", "protected")

    def add_files(self, rows: Iterable[Dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = ("INSERT INTO files(" + ",".join(self.FILE_COLS) + ") VALUES(" +
               ",".join("?" for _ in self.FILE_COLS) + ") ON CONFLICT(channel_id,msg_id) DO UPDATE SET "
               "grouped_id=excluded.grouped_id, date=excluded.date, doc_id=excluded.doc_id, "
               "file_unique_id=excluded.file_unique_id, file_identify=excluded.file_identify, "
               "file_name=excluded.file_name, name_norm=excluded.name_norm, caption=excluded.caption, "
               "caption_norm=excluded.caption_norm, size=excluded.size, duration=excluded.duration, "
               "mime=excluded.mime, width=excluded.width, height=excluded.height, "
               "has_video=excluded.has_video, protected=excluded.protected")
        vals = [tuple(r.get(c, 0) if c not in ("file_name", "name_norm", "caption", "caption_norm",
                                               "mime", "file_unique_id", "file_identify")
                      else str(r.get(c) or "") for c in self.FILE_COLS) for r in rows]
        self.conn.executemany(sql, vals)
        self.conn.commit()
        return len(vals)

    def set_hash(self, file_id: int, content_hash: str, scope: str = "head+mid+tail") -> None:
        self._exec("UPDATE files SET content_hash=?, hash_scope=? WHERE id=?", (content_hash, scope, file_id))
        self.conn.commit()

    def files_of_channel(self, channel_id: int, limit: int = 0) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM files WHERE channel_id=? ORDER BY msg_id"
        if limit:
            sql += " LIMIT %d" % int(limit)
        return [dict(r) for r in self._all(sql, (channel_id,))]

    def get_file(self, fid: int) -> Optional[Dict[str, Any]]:
        r = self._one("SELECT * FROM files WHERE id=?", (fid,))
        return dict(r) if r else None

    def files_by_ids(self, ids: Sequence[int]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        q = ",".join("?" for _ in ids)
        return [dict(r) for r in self._all("SELECT * FROM files WHERE id IN (%s)" % q, tuple(ids))]

    def max_msg_id(self, channel_id: int) -> int:
        r = self._one("SELECT MAX(msg_id) m FROM files WHERE channel_id=?", (channel_id,))
        return int((r["m"] if r else 0) or 0)

    def count_files(self, channel_id: int) -> int:
        r = self._one("SELECT COUNT(*) c FROM files WHERE channel_id=?", (channel_id,))
        return int((r["c"] if r else 0) or 0)

    def delete_files_older_than(self, channel_id: int, msg_id: int) -> int:
        """حذفِ رکوردهای قدیمیِ یک کانال (فقط ردیف‌های دیتابیسِ خودمان — هیچ فایلی در تلگرام پاک نمی‌شود)."""
        cur = self._exec("DELETE FROM files WHERE channel_id=? AND msg_id<=?", (channel_id, int(msg_id)))
        self.conn.commit()
        return cur.rowcount or 0

    # ═══════════════ scans ═══════════════
    def create_scan(self, channel_id: int, params: Dict[str, Any], min_id: int = 0) -> int:
        cur = self._exec("INSERT INTO scans(channel_id,started_at,status,phase,min_id,params) VALUES(?,?,?,?,?,?)",
                         (channel_id, now(), "running", "start", int(min_id or 0),
                          json.dumps(params, ensure_ascii=False)))
        self.conn.commit()
        return int(cur.lastrowid)

    def update_scan(self, scan_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ",".join("%s=?" % k for k in fields)
        self._exec("UPDATE scans SET %s WHERE id=?" % cols, tuple(fields.values()) + (scan_id,))
        self.conn.commit()

    def get_scan(self, scan_id: int) -> Optional[Dict[str, Any]]:
        r = self._one("SELECT * FROM scans WHERE id=?", (scan_id,))
        return dict(r) if r else None

    def last_scan(self, channel_id: int) -> Optional[Dict[str, Any]]:
        r = self._one("SELECT * FROM scans WHERE channel_id=? ORDER BY id DESC LIMIT 1", (channel_id,))
        return dict(r) if r else None

    def scans_of(self, channel_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._all(
            "SELECT * FROM scans WHERE channel_id=? ORDER BY id DESC LIMIT %d" % int(limit), (channel_id,))]

    # ═══════════════ groups ═══════════════
    def replace_groups(self, scan_id: int, channel_id: int, clusters: List[Dict[str, Any]]) -> int:
        self._exec("DELETE FROM group_members WHERE group_id IN (SELECT id FROM groups WHERE scan_id=?)", (scan_id,))
        self._exec("DELETE FROM groups WHERE scan_id=?", (scan_id,))
        for cl in clusters:
            cur = self._exec(
                "INSERT INTO groups(scan_id,channel_id,reason,strength,count,exact,sizetime,state,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (scan_id, channel_id, cl.get("reason", ""), int(cl.get("strength", 0)), len(cl.get("ids", [])),
                 1 if cl.get("exact") else 0, 1 if cl.get("sizetime") else 0, "open", now()))
            gid = int(cur.lastrowid)
            self.conn.executemany("INSERT OR IGNORE INTO group_members(group_id,file_id) VALUES(?,?)",
                                  [(gid, int(fid)) for fid in cl.get("ids", [])])
        self.conn.commit()
        return len(clusters)

    def groups_of_scan(self, scan_id: int, *, strength_min: int = 0, signal: str = "",
                       only_open: bool = False, state: str = "") -> List[Dict[str, Any]]:
        sql = "SELECT * FROM groups WHERE scan_id=?"
        args: List[Any] = [scan_id]
        if strength_min:
            sql += " AND strength>=?"
            args.append(int(strength_min))
        if signal == "exact":
            sql += " AND exact=1"
        elif signal == "sizetime":
            sql += " AND sizetime=1"
        elif signal == "name":
            sql += " AND reason LIKE '%نام%'"
        elif signal == "caption":
            sql += " AND reason LIKE '%کپشن%'"
        if only_open:
            sql += " AND state='open'"
        if state:
            sql += " AND state=?"
            args.append(state)
        sql += " ORDER BY strength DESC, count DESC, id"
        return [dict(r) for r in self._all(sql, tuple(args))]

    def get_group(self, gid: int) -> Optional[Dict[str, Any]]:
        r = self._one("SELECT * FROM groups WHERE id=?", (gid,))
        return dict(r) if r else None

    def group_members(self, gid: int) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._all(
            "SELECT f.* FROM group_members m JOIN files f ON f.id=m.file_id WHERE m.group_id=? ORDER BY f.msg_id",
            (gid,))]

    def set_group_state(self, gid: int, state: str) -> None:
        self._exec("UPDATE groups SET state=? WHERE id=?", (state, gid))
        self.conn.commit()

    def count_groups(self, scan_id: int, **kw: Any) -> int:
        return len(self.groups_of_scan(scan_id, **kw))

    def log_action(self, kind: str, detail: str = "") -> None:
        self._exec("INSERT INTO actions(at,kind,detail) VALUES(?,?,?)", (now(), kind, detail))
        self.conn.commit()

    def stats(self) -> Dict[str, Any]:
        return {
            "channels": (self._one("SELECT COUNT(*) c FROM channels") or {"c": 0})["c"],
            "files": (self._one("SELECT COUNT(*) c FROM files") or {"c": 0})["c"],
            "hashed": (self._one("SELECT COUNT(*) c FROM files WHERE content_hash<>''") or {"c": 0})["c"],
            "scans": (self._one("SELECT COUNT(*) c FROM scans") or {"c": 0})["c"],
            "groups": (self._one("SELECT COUNT(*) c FROM groups") or {"c": 0})["c"],
        }
