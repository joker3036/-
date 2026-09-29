"""대시보드·분석에서 쓰는 표(DataFrame) 만들기."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from . import metrics
from .config import Settings


def videos_df(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> pd.DataFrame:
    """영상 + 채널 정보 + 돌파 지수·떡상 점수·일평균 조회수·분석 상태."""
    now = now or datetime.now(timezone.utc)
    df = pd.read_sql_query(
        """SELECT v.video_id, v.channel_id, v.title, v.published_at, v.duration_s, v.is_short, v.content_type,
                  v.views, v.likes, v.comments, v.thumbnail_url, v.found_via,
                  c.title AS channel_title, c.subscribers, c.grp, c.pinned, c.is_role_model, c.primary_type,
                  a.status AS analysis_status
           FROM videos v
           LEFT JOIN channels c ON c.channel_id = v.channel_id
           LEFT JOIN analyses a ON a.target_id = v.video_id AND a.kind = 'video'""",
        conn,
    )
    if df.empty:
        return df
    df["published"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    df["age_days"] = (pd.Timestamp(now) - df["published"]).dt.total_seconds() / 86400
    df["mature"] = df["age_days"] >= settings.min_video_age_days

    # 채널 조회수 중앙값: 같은 채널 롱폼 중 성숙한(7일+) 최근 N개
    base = df[(df["is_short"] == 0) & df["mature"] & df["views"].notna()].sort_values("published", ascending=False)
    medians = base.groupby("channel_id")["views"].apply(lambda s: s.head(settings.median_window).median())
    df["channel_median"] = df["channel_id"].map(medians)
    df["outlier"] = df["views"] / df["channel_median"]
    df["breakout"] = df["views"] / df["subscribers"].where(df["subscribers"] > 0)
    df["daily_views"] = df["views"] / df["age_days"].clip(lower=1)
    return df


def channels_df(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT c.*, m.longform_count, m.uploads_90d, m.median_gap_days, m.max_gap_days, m.days_since_last,
                  m.median_views, m.mean_views, m.min_views, m.median_to_subs, m.type_counts_json, m.shorts_ratio,
                  m.failed_json, m.computed_at
           FROM channels c LEFT JOIN channel_metrics m ON m.channel_id = c.channel_id""",
        conn,
    )
    if not df.empty:
        df["failed"] = df["failed_json"].apply(lambda s: json.loads(s) if isinstance(s, str) and s else [])
    return df


def recent_thumbnails(conn: sqlite3.Connection, channel_ids: list[str], n: int = 3) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cid in channel_ids:
        rows = conn.execute(
            "SELECT thumbnail_url FROM videos WHERE channel_id=? AND is_short=0 AND thumbnail_url IS NOT NULL "
            "ORDER BY published_at DESC LIMIT ?", (cid, n)).fetchall()
        out[cid] = [r["thumbnail_url"] for r in rows]
    return out


def longtail_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """스냅샷이 2회 이상 쌓인 영상의 롱테일 지수."""
    rows = conn.execute(
        """SELECT s.video_id, s.captured_at, s.views, v.published_at, v.content_type, v.is_short
           FROM video_stats s JOIN videos v ON v.video_id = s.video_id
           WHERE s.video_id IN (SELECT video_id FROM video_stats GROUP BY video_id HAVING COUNT(*) >= 2)
           ORDER BY s.video_id, s.captured_at"""
    ).fetchall()
    by_video: dict[str, dict] = {}
    for r in rows:
        item = by_video.setdefault(r["video_id"], {"published_at": r["published_at"], "content_type": r["content_type"],
                                                   "is_short": r["is_short"], "history": []})
        item["history"].append({"captured_at": r["captured_at"], "views": r["views"]})
    records = []
    for vid, item in by_video.items():
        if item["is_short"]:
            continue
        idx = metrics.longtail_index(item["history"], item["published_at"])
        if idx is not None:
            records.append({"video_id": vid, "content_type": item["content_type"], "longtail": idx})
    return pd.DataFrame(records)


def analyses_df(conn: sqlite3.Connection, kind: str = "video") -> pd.DataFrame:
    rows = conn.execute("SELECT target_id, result_json FROM analyses WHERE kind=? AND status='done'", (kind,)).fetchall()
    records = []
    for r in rows:
        try:
            data = json.loads(r["result_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        records.append({"target_id": r["target_id"], **data})
    return pd.DataFrame(records)
