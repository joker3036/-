"""AI 분석 대기열: 영상 분석, 채널 대조 분석, 숨은 고수 분석, 성장(터닝포인트·관문 돌파) 분석."""
from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from . import collector, db, discovery, llm, metrics, prompts, queries
from .config import LLM_WORK_DIR, Settings
from .prompts.schemas import SCHEMAS
from .youtube import QuotaExceeded, YouTubeClient

KIND_LABELS = {
    "video": "영상 분석",
    "contrast": "대조 분석",
    "hidden_gem": "숨은 고수 분석",
    "growth": "성장·터닝포인트 분석",
    "travel_check": "여행 채널 판별",
}
CHANNEL_KINDS = ("contrast", "hidden_gem", "growth", "travel_check")


@dataclass
class QueueResult:
    done: int = 0
    errors: list[str] = field(default_factory=list)
    stopped: str | None = None


def candidate_videos(conn: sqlite3.Connection, settings: Settings, limit: int = 50, only_small: bool = True) -> pd.DataFrame:
    """AI 분석 1순위: 돌파 지수 또는 떡상 점수가 기준 이상이고 아직 분석 안 한 롱폼."""
    df = queries.videos_df(conn, settings)
    if df.empty:
        return df
    df = df[(df["is_short"] == 0) & df["mature"] & df["views"].notna()]
    if only_small:
        df = df[df["subscribers"] < settings.criteria.max_subscribers]
    df = df[df["analysis_status"].isna() | (df["analysis_status"] == "error")]
    df = df[(df["breakout"] >= settings.breakout_threshold) | (df["outlier"] >= settings.outlier_threshold)]
    return df.sort_values(["breakout", "outlier"], ascending=False).head(limit)


def enqueue(conn: sqlite3.Connection, target_ids: list[str], kind: str, force: bool = False) -> int:
    added = 0
    for tid in target_ids:
        existing = db.get_analysis(conn, tid, kind)
        if existing and existing["status"] in ("done", "pending") and not force:
            continue
        db.save_analysis(conn, tid, kind, "pending")
        added += 1
    return added


def pending_items(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT target_id, kind FROM analyses WHERE status='pending' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def _with_scores(videos: list[dict], settings: Settings, now: datetime) -> tuple[list[dict], float | None]:
    median = metrics.channel_median_views(videos, now, settings.min_video_age_days, settings.median_window)
    out = []
    for v in videos:
        v = dict(v)
        v["outlier"] = metrics.outlier_score(v.get("views"), median)
        out.append(v)
    return out, median


def _channel_context(conn: sqlite3.Connection, channel_id: str) -> tuple[dict, dict]:
    channel = conn.execute("SELECT * FROM channels WHERE channel_id=?", (channel_id,)).fetchone()
    if channel is None:
        raise ValueError(f"채널 없음: {channel_id}")
    m = conn.execute("SELECT * FROM channel_metrics WHERE channel_id=?", (channel_id,)).fetchone()
    return dict(channel), (dict(m) if m else {})


def _hit_analyses(conn: sqlite3.Connection, videos: list[dict]) -> list[dict]:
    out = []
    for v in videos:
        a = db.get_analysis(conn, v["video_id"], "video")
        if a and a["status"] == "done":
            out.append({"title": v.get("title"), "result": a["result"]})
    return out


def analyze_video(conn: sqlite3.Connection, video_id: str, settings: Settings, client: YouTubeClient | None = None,
                  runner=subprocess.run, extras_fn=collector.ensure_video_extras, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    video = conn.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
    if video is None:
        raise ValueError(f"영상 없음: {video_id}")
    video = dict(video)
    channel, _ = _channel_context(conn, video["channel_id"])
    siblings, median = _with_scores(metrics.longform(db.channel_videos(conn, video["channel_id"])), settings, now)
    stats = {
        "channel_median": median,
        "breakout": metrics.breakout_index(video.get("views"), channel.get("subscribers")),
        "outlier": metrics.outlier_score(video.get("views"), median),
    }
    normal = [v["title"] for v in siblings if v["video_id"] != video_id and v.get("outlier") is not None and v["outlier"] <= 1.2]
    extras = extras_fn(conn, video_id, LLM_WORK_DIR, client)
    prompt = prompts.video_prompt(video, channel, stats, extras, normal)
    res = llm.run_structured(prompt, SCHEMAS["video"], settings.model_video, LLM_WORK_DIR, prompts.SYSTEM_PROMPT,
                             settings.llm_timeout_sec, runner)
    db.save_analysis(conn, video_id, "video", "done", res.data, res.model)
    return res.data


def analyze_channel(conn: sqlite3.Connection, channel_id: str, kind: str, settings: Settings, runner=subprocess.run,
                    now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    channel, m = _channel_context(conn, channel_id)
    videos, _ = _with_scores(metrics.longform(db.channel_videos(conn, channel_id)), settings, now)  # 최신순
    model = settings.model_channel

    if kind == "contrast":
        scored = [v for v in videos if v.get("outlier") is not None]
        hits = sorted((v for v in scored if v["outlier"] >= settings.outlier_threshold), key=lambda v: -v["outlier"])[:8]
        if not hits:
            hits = sorted(scored, key=lambda v: -v["outlier"])[:3]
        hit_ids = {v["video_id"] for v in hits}
        normals = [v for v in scored if v["video_id"] not in hit_ids and 0.5 <= v["outlier"] <= 1.5][:15]
        prompt = prompts.contrast_prompt(channel, m, hits, normals, _hit_analyses(conn, hits))
    elif kind == "hidden_gem":
        top = sorted((v for v in videos if v.get("outlier") is not None), key=lambda v: -v["outlier"])[:5]
        prompt = prompts.hidden_gem_prompt(channel, m, videos[:40], _hit_analyses(conn, top))
    elif kind == "growth":
        timeline = list(reversed(videos))
        tp = metrics.turning_point(timeline, settings.turning_point_factor, now=now, min_age_days=settings.min_video_age_days)
        before = None
        if channel.get("grp") == "graduated":
            crossed = next((h["captured_at"] for h in db.channel_history(conn, channel_id)
                            if (h.get("subscribers") or 0) >= settings.criteria.max_subscribers), None)
            if crossed:
                before = [v for v in videos if (v.get("published_at") or "") <= crossed][:10]
        prompt = prompts.growth_prompt(channel, m, timeline, tp, before)
    elif kind == "travel_check":
        prompt = prompts.travel_check_prompt(channel, [v["title"] for v in videos[:20]])
        model = settings.model_video
    else:
        raise ValueError(f"알 수 없는 분석 종류: {kind}")

    res = llm.run_structured(prompt, SCHEMAS[kind], model, LLM_WORK_DIR, prompts.SYSTEM_PROMPT, settings.llm_timeout_sec, runner)
    db.save_analysis(conn, channel_id, kind, "done", res.data, res.model)
    if kind == "travel_check":
        discovery.set_travel_override(conn, channel_id, bool(res.data.get("is_travel")), settings)
    return res.data


def process_queue(conn: sqlite3.Connection, settings: Settings, client: YouTubeClient | None = None, limit: int | None = None,
                  runner=subprocess.run, progress: Callable[[int, int, str], None] | None = None,
                  extras_fn=collector.ensure_video_extras) -> QueueResult:
    """대기열을 순서대로 처리. 구독 사용 한도에 걸리면 멈추고 나머지는 대기열에 남긴다."""
    result = QueueResult()
    items = pending_items(conn)[: limit or settings.analysis_batch_size]
    for n, item in enumerate(items, 1):
        tid, kind = item["target_id"], item["kind"]
        if progress:
            progress(n, len(items), f"{KIND_LABELS.get(kind, kind)}: {tid}")
        try:
            if kind == "video":
                analyze_video(conn, tid, settings, client, runner, extras_fn)
            else:
                analyze_channel(conn, tid, kind, settings, runner)
            result.done += 1
        except llm.LLMUsageLimit as exc:
            result.stopped = f"Claude 구독 사용 한도에 걸려 멈췄습니다. 몇 시간 뒤 다시 실행하면 이어서 분석합니다. ({exc})"
            break
        except (llm.LLMNotAvailable, QuotaExceeded) as exc:
            result.stopped = str(exc)
            break
        except Exception as exc:  # 개별 실패는 기록하고 다음으로
            db.save_analysis(conn, tid, kind, "error", error=f"{type(exc).__name__}: {exc}")
            result.errors.append(f"{KIND_LABELS.get(kind, kind)} {tid}: {exc}")
    return result
