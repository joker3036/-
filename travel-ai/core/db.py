"""SQLite 스키마와 공통 쿼리."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    handle TEXT,
    title TEXT,
    description TEXT,
    thumbnail_url TEXT,
    country TEXT,
    published_at TEXT,
    subscribers INTEGER,
    hidden_subscribers INTEGER DEFAULT 0,
    total_views INTEGER,
    video_count INTEGER,
    uploads_playlist TEXT,
    grp TEXT DEFAULT 'pool',
    pinned INTEGER DEFAULT 0,
    is_role_model INTEGER DEFAULT 0,
    primary_type TEXT,
    travel_ratio REAL,
    travel_override INTEGER,
    source TEXT,
    scan_status TEXT DEFAULT 'new',
    filter_reason TEXT,
    first_seen_at TEXT,
    last_scanned_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS channel_stats (
    channel_id TEXT,
    captured_at TEXT,
    subscribers INTEGER,
    total_views INTEGER,
    video_count INTEGER,
    PRIMARY KEY (channel_id, captured_at)
);
CREATE TABLE IF NOT EXISTS channel_metrics (
    channel_id TEXT PRIMARY KEY,
    computed_at TEXT,
    longform_count INTEGER,
    uploads_90d INTEGER,
    median_gap_days REAL,
    max_gap_days REAL,
    days_since_last REAL,
    median_views REAL,
    mean_views REAL,
    min_views REAL,
    median_to_subs REAL,
    travel_ratio REAL,
    primary_type TEXT,
    type_counts_json TEXT,
    shorts_ratio REAL,
    failed_json TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT,
    title TEXT,
    description TEXT,
    published_at TEXT,
    duration_s INTEGER,
    is_short INTEGER DEFAULT 0,
    category_id TEXT,
    tags_json TEXT,
    thumbnail_url TEXT,
    content_type TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    found_via TEXT,
    first_seen_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE TABLE IF NOT EXISTS video_stats (
    video_id TEXT,
    captured_at TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    PRIMARY KEY (video_id, captured_at)
);
CREATE TABLE IF NOT EXISTS video_extras (
    video_id TEXT PRIMARY KEY,
    transcript TEXT,
    transcript_lang TEXT,
    transcript_note TEXT,
    comments_json TEXT,
    thumb_path TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS keywords (
    keyword TEXT PRIMARY KEY,
    kind TEXT,
    last_searched_at TEXT,
    searches INTEGER DEFAULT 0,
    results INTEGER DEFAULT 0,
    new_channels INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS analyses (
    target_id TEXT,
    kind TEXT,
    status TEXT,
    result_json TEXT,
    model TEXT,
    error TEXT,
    created_at TEXT,
    PRIMARY KEY (target_id, kind)
);
CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT,
    bucket TEXT,
    amount INTEGER,
    PRIMARY KEY (day, bucket)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# YouTube API 할당량은 태평양 시간 자정에 초기화된다.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def connect(path: Path | str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _upsert(conn: sqlite3.Connection, table: str, key: str, row: dict) -> None:
    cols = list(row)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != key)
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT({key}) DO UPDATE SET {updates}"
    conn.execute(sql, [row[c] for c in cols])


def upsert_channel(conn: sqlite3.Connection, row: dict) -> None:
    row = dict(row)
    row.setdefault("updated_at", now_iso())
    existing = conn.execute("SELECT first_seen_at FROM channels WHERE channel_id=?", (row["channel_id"],)).fetchone()
    if existing is None:
        row.setdefault("first_seen_at", now_iso())
    _upsert(conn, "channels", "channel_id", row)


def upsert_video(conn: sqlite3.Connection, row: dict) -> None:
    row = dict(row)
    row.setdefault("updated_at", now_iso())
    existing = conn.execute("SELECT found_via, first_seen_at FROM videos WHERE video_id=?", (row["video_id"],)).fetchone()
    if existing is None:
        row.setdefault("first_seen_at", now_iso())
    elif existing["found_via"] and row.get("found_via") in (None, "uploads"):
        # 검색으로 처음 발견된 영상이면 그 출처를 유지
        row.pop("found_via", None)
    _upsert(conn, "videos", "video_id", row)


def add_video_snapshot(conn: sqlite3.Connection, video_id: str, views, likes, comments, captured_at: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO video_stats (video_id, captured_at, views, likes, comments) VALUES (?,?,?,?,?)",
        (video_id, captured_at or now_iso(), views, likes, comments),
    )


def add_channel_snapshot(conn: sqlite3.Connection, channel_id: str, subscribers, total_views, video_count, captured_at: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO channel_stats (channel_id, captured_at, subscribers, total_views, video_count) VALUES (?,?,?,?,?)",
        (channel_id, captured_at or now_iso(), subscribers, total_views, video_count),
    )


def quota_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(QUOTA_TZ).strftime("%Y-%m-%d")


def record_usage(conn: sqlite3.Connection, bucket: str, amount: int, day: str | None = None) -> None:
    conn.execute(
        "INSERT INTO api_usage (day, bucket, amount) VALUES (?,?,?) "
        "ON CONFLICT(day, bucket) DO UPDATE SET amount = amount + excluded.amount",
        (day or quota_day(), bucket, amount),
    )
    conn.commit()


def get_usage(conn: sqlite3.Connection, bucket: str, day: str | None = None) -> int:
    row = conn.execute("SELECT amount FROM api_usage WHERE day=? AND bucket=?", (day or quota_day(), bucket)).fetchone()
    return int(row["amount"]) if row else 0


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))
    conn.commit()


def save_analysis(conn: sqlite3.Connection, target_id: str, kind: str, status: str, result: dict | None = None,
                  model: str | None = None, error: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO analyses (target_id, kind, status, result_json, model, error, created_at) VALUES (?,?,?,?,?,?,?)",
        (target_id, kind, status, json.dumps(result, ensure_ascii=False) if result is not None else None, model, error, now_iso()),
    )
    conn.commit()


def get_analysis(conn: sqlite3.Connection, target_id: str, kind: str) -> dict | None:
    row = conn.execute("SELECT * FROM analyses WHERE target_id=? AND kind=?", (target_id, kind)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["result"] = json.loads(row["result_json"]) if row["result_json"] else None
    return out


def channel_videos(conn: sqlite3.Connection, channel_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM videos WHERE channel_id=? ORDER BY published_at DESC", (channel_id,)).fetchall()
    return [dict(r) for r in rows]


def channel_history(conn: sqlite3.Connection, channel_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM channel_stats WHERE channel_id=? ORDER BY captured_at", (channel_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def video_history(conn: sqlite3.Connection, video_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM video_stats WHERE video_id=? ORDER BY captured_at", (video_id,)).fetchall()
    return [dict(r) for r in rows]
