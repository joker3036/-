"""관심 채널 갱신, 성장 타임라인, 떡상 영상 심층 수집(자막·댓글·썸네일), 오래된 데이터 정리."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import db, transcripts
from .config import Settings
from .discovery import Progress, Report, scan_channels, store_videos, update_channel_metrics
from .youtube import QuotaExceeded, YouTubeClient, YouTubeError


def refresh_channels(conn: sqlite3.Connection, client: YouTubeClient, channel_ids: list[str], settings: Settings,
                     progress: Progress | None = None) -> Report:
    """스냅샷을 새로 찍는다 (구독자·조회수). 관문 돌파 판정도 여기서 갱신된다."""
    report = Report()
    try:
        scan_channels(conn, client, channel_ids, settings, "refresh", report, force=True, progress=progress)
    except QuotaExceeded as exc:
        report.stopped_by_quota = True
        report.messages.append(str(exc))
    return report


def fetch_full_timeline(conn: sqlite3.Connection, client: YouTubeClient, channel_id: str, settings: Settings,
                        max_videos: int = 500) -> int:
    """채널 전체 업로드를 수집해 성장 타임라인을 만든다. 저장한 영상 수 반환."""
    row = conn.execute("SELECT uploads_playlist FROM channels WHERE channel_id=?", (channel_id,)).fetchone()
    if not row or not row["uploads_playlist"]:
        return 0
    ids = client.playlist_video_ids(row["uploads_playlist"], max_videos)
    stored = store_videos(conn, client.videos_by_ids(ids), settings, "uploads")
    db.set_meta(conn, f"timeline:{channel_id}", db.now_iso())
    update_channel_metrics(conn, channel_id, settings)
    return len(stored)


def ensure_video_extras(conn: sqlite3.Connection, video_id: str, work_dir: Path, client: YouTubeClient | None = None,
                        transcript_fn=transcripts.fetch_transcript, http_get=requests.get) -> dict:
    """AI 분석에 필요한 자막·댓글·썸네일을 모은다. 이미 있으면 그대로 반환."""
    existing = conn.execute("SELECT * FROM video_extras WHERE video_id=?", (video_id,)).fetchone()
    if existing and existing["fetched_at"]:
        return dict(existing)
    video = conn.execute("SELECT thumbnail_url FROM videos WHERE video_id=?", (video_id,)).fetchone()

    text, lang, note = transcript_fn(video_id)

    comments: list[dict] = []
    if client is not None:
        try:
            comments = client.comment_threads(video_id, 100)
        except QuotaExceeded:
            raise
        except YouTubeError as exc:
            note += f" / 댓글 수집 실패: {exc}"

    thumb_path = None
    if video and video["thumbnail_url"]:
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / f"thumb_{video_id}.jpg"
        try:
            resp = http_get(video["thumbnail_url"], timeout=15)
            if resp.status_code == 200 and resp.content:
                path.write_bytes(resp.content)
                thumb_path = path.name
        except requests.RequestException:
            pass

    row = {
        "video_id": video_id,
        "transcript": text,
        "transcript_lang": lang,
        "transcript_note": note,
        "comments_json": json.dumps(comments, ensure_ascii=False),
        "thumb_path": thumb_path,
        "fetched_at": db.now_iso(),
    }
    conn.execute(
        "INSERT OR REPLACE INTO video_extras (video_id, transcript, transcript_lang, transcript_note, comments_json, thumb_path, fetched_at)"
        " VALUES (:video_id, :transcript, :transcript_lang, :transcript_note, :comments_json, :thumb_path, :fetched_at)",
        row,
    )
    conn.commit()
    return row


def prune_stale(conn: sqlite3.Connection, stale_days: int = 30) -> int:
    """관심·롤모델이 아닌 채널 중 stale_days 넘게 갱신 안 된 채널의 수집 데이터를 지운다.

    YouTube API 정책상 API로 받은 데이터는 주기적으로 갱신하거나 지워야 한다.
    관심 채널(📌)과 롤모델은 사용자가 갱신하므로 남겨둔다. 지운 채널 수 반환.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).replace(microsecond=0).isoformat()
    rows = conn.execute(
        "SELECT channel_id FROM channels WHERE pinned=0 AND is_role_model=0 AND (last_scanned_at IS NULL OR last_scanned_at < ?)",
        (cutoff,),
    ).fetchall()
    ids = [r["channel_id"] for r in rows]
    for cid in ids:
        video_ids = [r["video_id"] for r in conn.execute("SELECT video_id FROM videos WHERE channel_id=?", (cid,))]
        for table in ("video_stats", "video_extras"):
            conn.executemany(f"DELETE FROM {table} WHERE video_id=?", [(v,) for v in video_ids])
        conn.executemany("DELETE FROM analyses WHERE target_id=?", [(v,) for v in video_ids] + [(cid,)])
        conn.execute("DELETE FROM videos WHERE channel_id=?", (cid,))
        conn.execute("DELETE FROM channel_stats WHERE channel_id=?", (cid,))
        conn.execute("DELETE FROM channel_metrics WHERE channel_id=?", (cid,))
        conn.execute("DELETE FROM channels WHERE channel_id=?", (cid,))
    conn.commit()
    return len(ids)


def prune_if_due(conn: sqlite3.Connection, settings: Settings) -> int:
    """하루 한 번만 정리."""
    if not settings.auto_prune:
        return 0
    today = db.quota_day()
    if db.get_meta(conn, "last_prune") == today:
        return 0
    removed = prune_stale(conn, settings.stale_days)
    db.set_meta(conn, "last_prune", today)
    return removed
