"""채널 발굴: 키워드 탐색 · URL 가져오기 · 추천 채널 확장 → 채널 스캔 → 지표 → 그룹 분류."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import content_types, db, keywords, metrics, youtube
from .config import Settings
from .sources import Candidate, SourceError, unofficial, youtube_api
from .youtube import ChannelRef, QuotaExceeded, YouTubeClient

# 기관·방송 채널 (개인 크리에이터가 아닌 곳)
INSTITUTION_WORDS = ["군청", "시청", "구청", "도청", "관광공사", "관광재단", "관광협회", "문화관광", "문화재단", "진흥원",
                     "공단", "KBS", "MBC", "SBS", "JTBC", "YTN", "MBN", "EBS", "tvN", "연합뉴스", "뉴스", "방송국",
                     "신문", "일보", "대한민국 구석구석"]

FILTER_REASONS = {
    "hidden_subs": "구독자 수 비공개",
    "too_big": "구독자 1만 이상",
    "too_few_videos": "영상 수 부족",
    "institution": "기관·방송 채널",
}

ORDER_LABELS = {"alternate": "번갈아 (최신순·조회수순)", "date": "최신순", "views": "조회수순", "relevance": "관련도순"}

Progress = Callable[[int, int, str], None]


@dataclass
class Report:
    keywords: list[str] = field(default_factory=list)
    official_searches: int = 0
    unofficial_searches: int = 0
    candidates: int = 0
    new_channels: int = 0
    scanned: int = 0
    filtered: Counter = field(default_factory=Counter)
    groups: Counter = field(default_factory=Counter)
    messages: list[str] = field(default_factory=list)
    fallback_used: bool = False
    stopped_by_quota: bool = False

    def summary(self) -> str:
        parts = []
        if self.keywords:
            parts.append(f"키워드 {len(self.keywords)}개 (비공식 검색 {self.unofficial_searches}회, 공식 검색 {self.official_searches}회)")
        parts.append(f"새 채널 {self.new_channels}개, 스캔 {self.scanned}개")
        if self.groups:
            parts.append(", ".join(f"{metrics.GROUPS.get(g, g)} {n}" for g, n in self.groups.most_common()))
        if self.filtered:
            parts.append("제외: " + ", ".join(f"{FILTER_REASONS.get(r, r)} {n}" for r, n in self.filtered.most_common()))
        return " · ".join(parts)


def is_institution(title: str | None) -> bool:
    t = title or ""
    return any(w.lower() in t.lower() for w in INSTITUTION_WORDS)


def _first_filter(row: dict, settings: Settings, tracked: bool) -> str | None:
    if tracked:
        return None
    if row.get("hidden_subscribers"):
        return "hidden_subs"
    if row.get("subscribers") is not None and row["subscribers"] >= settings.criteria.max_subscribers:
        return "too_big"
    if (row.get("video_count") or 0) < settings.min_video_count:
        return "too_few_videos"
    if is_institution(row.get("title")):
        return "institution"
    return None


def store_videos(conn: sqlite3.Connection, items: list[dict], settings: Settings, found_via: str) -> list[dict]:
    """videos.list 응답을 저장하고 조회수 스냅샷을 남긴다."""
    rows = []
    captured = db.now_iso()
    for item in items:
        row = youtube.video_row(item, settings.shorts_max_seconds)
        tags = json.loads(row["tags_json"] or "[]")
        row["content_type"] = content_types.classify_title(row["title"], row["category_id"], tags)
        row["found_via"] = found_via
        db.upsert_video(conn, row)
        db.add_video_snapshot(conn, row["video_id"], row["views"], row["likes"], row["comments"], captured)
        rows.append(row)
    conn.commit()
    return rows


def update_channel_metrics(conn: sqlite3.Connection, channel_id: str, settings: Settings, now: datetime | None = None) -> str:
    """DB에 있는 영상으로 채널 지표를 다시 계산하고 그룹을 정한다 (API 호출 없음)."""
    ch = conn.execute("SELECT * FROM channels WHERE channel_id=?", (channel_id,)).fetchone()
    if ch is None:
        return "filtered"
    criteria = settings.criteria
    videos = db.channel_videos(conn, channel_id)
    m = metrics.compute_channel_metrics(videos, ch["subscribers"], now, criteria, settings.min_video_age_days)
    failed = metrics.evaluate_criteria(m, ch["subscribers"], criteria)
    if ch["travel_override"] == 1:
        failed = [f for f in failed if f["key"] != "travel_ratio"]
    elif ch["travel_override"] == 0 and not any(f["key"] == "travel_ratio" for f in failed):
        failed.append({"key": "travel_ratio", "label": "여행 관련 비율", "actual": m["travel_ratio"],
                       "threshold": criteria.min_travel_ratio, "unit": "이상"})
    history = db.channel_history(conn, channel_id)
    group = metrics.classify_group(bool(ch["is_role_model"]), ch["subscribers"], m, failed, history, criteria)
    conn.execute(
        """INSERT OR REPLACE INTO channel_metrics (channel_id, computed_at, longform_count, uploads_90d, median_gap_days,
           max_gap_days, days_since_last, median_views, mean_views, min_views, median_to_subs, travel_ratio, primary_type,
           type_counts_json, shorts_ratio, failed_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (channel_id, db.now_iso(), m["longform_count"], m["uploads_90d"], m["median_gap_days"], m["max_gap_days"],
         m["days_since_last"], m["median_views"], m["mean_views"], m["min_views"], m["median_to_subs"], m["travel_ratio"],
         m["primary_type"], json.dumps(m["type_counts"], ensure_ascii=False), m["shorts_ratio"],
         json.dumps(failed, ensure_ascii=False)),
    )
    conn.execute(
        "UPDATE channels SET grp=?, primary_type=?, travel_ratio=?, scan_status='scanned', filter_reason=NULL WHERE channel_id=?",
        (group, m["primary_type"], m["travel_ratio"], channel_id),
    )
    conn.commit()
    return group


def reclassify_all(conn: sqlite3.Connection, settings: Settings) -> Counter:
    """기준값을 바꿨을 때 모든 스캔된 채널의 그룹을 다시 계산 (API 호출 없음)."""
    groups: Counter = Counter()
    for row in conn.execute("SELECT channel_id FROM channels WHERE scan_status='scanned'").fetchall():
        groups[update_channel_metrics(conn, row["channel_id"], settings)] += 1
    return groups


def scan_channels(conn: sqlite3.Connection, client: YouTubeClient, channel_ids: list[str], settings: Settings,
                  source: str, report: Report | None = None, force: bool = False, role_model: bool = False,
                  pin: bool = False, progress: Progress | None = None) -> Report:
    """채널 정보 → 1차 필터 → 최근 업로드 50개 → 지표·그룹."""
    report = report or Report()
    ids = list(dict.fromkeys(i for i in channel_ids if i))
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.rescan_days)
    to_fetch = []
    for cid in ids:
        row = conn.execute("SELECT last_scanned_at FROM channels WHERE channel_id=?", (cid,)).fetchone()
        if row is None:
            report.new_channels += 1
        if role_model or pin:
            _set_flags(conn, cid, role_model, pin)
        last = db.parse_dt(row["last_scanned_at"]) if row else None
        if not force and last and last > cutoff:
            continue
        to_fetch.append(cid)
    if not to_fetch:
        return report

    items = client.channels_by_ids(to_fetch)
    captured = db.now_iso()
    for n, item in enumerate(items, 1):
        row = youtube.channel_row(item)
        existing = conn.execute("SELECT source, is_role_model, pinned FROM channels WHERE channel_id=?", (row["channel_id"],)).fetchone()
        is_rm = bool(role_model or (existing and existing["is_role_model"]))
        pinned = bool(pin or role_model or (existing and existing["pinned"]))
        row.update({
            "source": (existing["source"] if existing and existing["source"] else source),
            "is_role_model": int(is_rm),
            "pinned": int(pinned),
            "last_scanned_at": captured,
        })
        reason = _first_filter(row, settings, tracked=is_rm or pinned)
        if reason:
            row.update({"scan_status": "filtered", "filter_reason": reason, "grp": "big" if reason == "too_big" else "filtered"})
            db.upsert_channel(conn, row)
            db.add_channel_snapshot(conn, row["channel_id"], row["subscribers"], row["total_views"], row["video_count"], captured)
            conn.commit()
            report.filtered[reason] += 1
            continue
        db.upsert_channel(conn, row)
        db.add_channel_snapshot(conn, row["channel_id"], row["subscribers"], row["total_views"], row["video_count"], captured)
        if row["uploads_playlist"]:
            video_ids = client.playlist_video_ids(row["uploads_playlist"], 50)
            store_videos(conn, client.videos_by_ids(video_ids), settings, "uploads")
        group = update_channel_metrics(conn, row["channel_id"], settings)
        report.scanned += 1
        report.groups[group] += 1
        if progress:
            progress(n, len(items), row["title"] or row["channel_id"])
    missing = set(to_fetch) - {i["id"] for i in items}
    if missing:
        report.messages.append(f"찾을 수 없는 채널 {len(missing)}개 (삭제됐거나 비공개)")
    return report


def _set_flags(conn: sqlite3.Connection, channel_id: str, role_model: bool, pin: bool) -> None:
    if role_model:
        conn.execute("UPDATE channels SET is_role_model=1, pinned=1 WHERE channel_id=?", (channel_id,))
    if pin:
        conn.execute("UPDATE channels SET pinned=1 WHERE channel_id=?", (channel_id,))
    conn.commit()


def run_keyword_discovery(conn: sqlite3.Connection, client: YouTubeClient, settings: Settings, n_keywords: int,
                          kinds: list[str] | None = None, order: str = "alternate", duration: str = "medium",
                          published_within_days: int = 90, progress: Progress | None = None,
                          unofficial_fn=None) -> Report:
    """키워드 큐에서 n개를 골라 검색 → 영상 상세 조회 → 채널 스캔."""
    report = Report()
    keywords.ensure_keywords(conn)
    picked = keywords.pick_keywords(conn, min(n_keywords, settings.max_keywords_per_run), kinds)
    report.keywords = picked
    use_unofficial = settings.use_unofficial_search
    published_after = datetime.now(timezone.utc) - timedelta(days=published_within_days)

    for i, kw in enumerate(picked):
        kw_order = order if order != "alternate" else ("date" if i % 2 == 0 else "views")
        candidates: list[Candidate] | None = None
        try:
            if use_unofficial:
                try:
                    candidates = unofficial.search(kw, kw_order, settings.results_per_keyword,
                                                   settings.unofficial_sleep_sec, search_fn=unofficial_fn)
                    report.unofficial_searches += 1
                except SourceError as exc:
                    use_unofficial = False
                    report.fallback_used = True
                    report.messages.append(f"{exc} → 이번 실행은 공식 검색으로 전환합니다.")
            if candidates is None:
                candidates = youtube_api.search(client, kw, kw_order, published_after, duration, settings.results_per_keyword)
                report.official_searches += 1

            report.candidates += len(candidates)
            before = report.new_channels
            items = client.videos_by_ids([c.video_id for c in candidates if c.video_id])
            store_videos(conn, items, settings, f"search:{kw}")
            channel_ids = [i["snippet"]["channelId"] for i in items] + [c.channel_id for c in candidates]
            scan_channels(conn, client, channel_ids, settings, "unofficial_search" if use_unofficial else "api_search", report)
            keywords.record_search(conn, kw, len(candidates), report.new_channels - before)
        except QuotaExceeded as exc:
            report.stopped_by_quota = True
            report.messages.append(f"{exc} 내일(한국 시간 오후 4~5시 초기화) 이어서 진행하세요.")
            break
        if progress:
            progress(i + 1, len(picked), kw)
    return report


def import_channels(conn: sqlite3.Connection, client: YouTubeClient, refs: list[ChannelRef], settings: Settings,
                    role_model: bool = False, pin: bool = False, progress: Progress | None = None) -> Report:
    report = Report()
    try:
        ids, errors = client.resolve_refs(refs)
        report.messages.extend(errors)
        scan_channels(conn, client, ids, settings, "import", report, force=role_model or pin,
                      role_model=role_model, pin=pin, progress=progress)
    except QuotaExceeded as exc:
        report.stopped_by_quota = True
        report.messages.append(str(exc))
    return report


def expand_featured(conn: sqlite3.Connection, client: YouTubeClient, channel_ids: list[str], settings: Settings,
                    progress: Progress | None = None) -> Report:
    """관심 채널이 채널 페이지에 걸어둔 추천 채널을 스캔."""
    report = Report()
    try:
        for n, cid in enumerate(channel_ids, 1):
            featured = client.featured_channel_ids(cid)
            if featured:
                scan_channels(conn, client, featured, settings, "featured", report)
            if progress:
                progress(n, len(channel_ids), cid)
    except QuotaExceeded as exc:
        report.stopped_by_quota = True
        report.messages.append(str(exc))
    return report


def set_pinned(conn: sqlite3.Connection, channel_id: str, pinned: bool) -> None:
    conn.execute("UPDATE channels SET pinned=? WHERE channel_id=?", (int(pinned), channel_id))
    conn.commit()


def set_role_model(conn: sqlite3.Connection, channel_id: str, value: bool, settings: Settings) -> None:
    conn.execute("UPDATE channels SET is_role_model=?, pinned=CASE WHEN ? THEN 1 ELSE pinned END WHERE channel_id=?",
                 (int(value), int(value), channel_id))
    conn.commit()
    update_channel_metrics(conn, channel_id, settings)


def set_travel_override(conn: sqlite3.Connection, channel_id: str, value: bool | None, settings: Settings) -> None:
    conn.execute("UPDATE channels SET travel_override=? WHERE channel_id=?", (None if value is None else int(value), channel_id))
    conn.commit()
    update_channel_metrics(conn, channel_id, settings)
