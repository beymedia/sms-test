"""SQLite storage: message queue, daily limits and opt-out list."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "sms.db")
PER_NUMBER_DAILY_LIMIT = int(os.environ.get("PER_NUMBER_DAILY_LIMIT", "3"))
GLOBAL_DAILY_LIMIT = int(os.environ.get("GLOBAL_DAILY_LIMIT", "100"))

# Statuses that count against the daily limits.
COUNTED_STATUSES = ("queued", "sent", "simulated")

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    to_number   TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL,  -- queued | sent | simulated | failed | blocked
    provider_id TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_to_day ON messages(to_number, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status, id);
CREATE TABLE IF NOT EXISTS opt_outs (
    to_number  TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _day_start_iso():
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)


def _count_today(conn, number=None):
    placeholders = ",".join("?" * len(COUNTED_STATUSES))
    sql = (
        "SELECT COUNT(*) FROM messages "
        f"WHERE created_at >= ? AND status IN ({placeholders})"
    )
    params = [_day_start_iso(), *COUNTED_STATUSES]
    if number is not None:
        sql += " AND to_number = ?"
        params.append(number)
    return conn.execute(sql, params).fetchone()[0]


def usage_today(number=None):
    with db() as conn:
        return _count_today(conn, number)


def enqueue(numbers, body):
    """Queue `body` for each number, enforcing opt-outs and daily limits.

    Returns one result dict per unique number, in the order given.
    Blocked numbers are recorded with status 'blocked' for audit but are not sent.
    """
    results = []
    now = _now_iso()
    with db() as conn:
        global_used = _count_today(conn)
        for number in dict.fromkeys(numbers):
            reason = None
            opted_out = conn.execute(
                "SELECT 1 FROM opt_outs WHERE to_number = ?", (number,)
            ).fetchone()
            if opted_out:
                reason = "opted_out"
            elif global_used >= GLOBAL_DAILY_LIMIT:
                reason = "global_daily_limit"
            elif _count_today(conn, number) >= PER_NUMBER_DAILY_LIMIT:
                reason = "number_daily_limit"

            if reason:
                cur = conn.execute(
                    "INSERT INTO messages (to_number, body, status, error, created_at, updated_at)"
                    " VALUES (?, ?, 'blocked', ?, ?, ?)",
                    (number, body, reason, now, now),
                )
                results.append({"id": cur.lastrowid, "to": number,
                                "status": "blocked", "reason": reason})
            else:
                cur = conn.execute(
                    "INSERT INTO messages (to_number, body, status, created_at, updated_at)"
                    " VALUES (?, ?, 'queued', ?, ?)",
                    (number, body, now, now),
                )
                global_used += 1
                results.append({"id": cur.lastrowid, "to": number, "status": "queued"})
    return results


def next_queued():
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def update_message(msg_id, status, provider_id=None, error=None):
    with db() as conn:
        conn.execute(
            "UPDATE messages SET status = ?, provider_id = ?, error = ?, updated_at = ?"
            " WHERE id = ?",
            (status, provider_id, error, _now_iso(), msg_id),
        )


def get_message(msg_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return dict(row) if row else None


def is_opted_out(number):
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM opt_outs WHERE to_number = ?", (number,)
        ).fetchone() is not None


def add_opt_out(number):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO opt_outs (to_number, created_at) VALUES (?, ?)",
            (number, _now_iso()),
        )
