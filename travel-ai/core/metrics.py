"""영상·채널 지표와 그룹 판정. 모두 순수 함수 (DB 접근 없음)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import mean, median

from . import content_types
from .config import Criteria
from .db import parse_dt

GROUPS: dict[str, str] = {
    "role_model": "⭐ 롤모델",
    "hidden_gem": "🎯 숨은 고수",
    "near": "🌱 근접 후보",
    "graduated": "🎓 관문 돌파",
    "pool": "📋 후보 풀",
    "big": "구독 1만 이상",
    "not_travel": "여행 무관",
    "filtered": "제외",
}

CRITERIA_LABELS = {
    "subscribers": "구독자",
    "uploads_90d": "90일 롱폼 수",
    "median_gap_days": "업로드 간격 중앙값",
    "max_gap_days": "최대 공백",
    "days_since_last": "마지막 업로드",
    "median_views": "조회수 중앙값",
    "travel_ratio": "여행 관련 비율",
}


def age_days(published_at: str | datetime | None, now: datetime | None = None) -> float | None:
    dt = parse_dt(published_at) if isinstance(published_at, str) or published_at is None else published_at
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max((now - dt).total_seconds() / 86400, 0.0)


def longform(videos: list[dict]) -> list[dict]:
    return [v for v in videos if not v.get("is_short")]


def breakout_index(views: int | None, subscribers: int | None) -> float | None:
    """돌파 지수 = 조회수 ÷ 구독자."""
    if views is None or not subscribers:
        return None
    return views / subscribers


def channel_median_views(videos: list[dict], now: datetime, min_age_days: int = 7, window: int = 30) -> float | None:
    """같은 채널 최근 롱폼(업로드 min_age_days 이상 경과) window개의 조회수 중앙값."""
    matured = [v for v in _sorted_desc(longform(videos))
               if v.get("views") is not None and (age_days(v.get("published_at"), now) or 0) >= min_age_days]
    views = [v["views"] for v in matured[:window]]
    return float(median(views)) if views else None


def outlier_score(views: int | None, channel_median: float | None) -> float | None:
    """채널 내 떡상 점수 = 조회수 ÷ 채널 조회수 중앙값."""
    if views is None or not channel_median:
        return None
    return views / channel_median


def daily_views(views: int | None, published_at: str | None, now: datetime | None = None) -> float | None:
    age = age_days(published_at, now)
    if views is None or age is None:
        return None
    return views / max(age, 1.0)


def longtail_index(history: list[dict], published_at: str | None, min_age_days: int = 30) -> float | None:
    """롱테일 지수 = (업로드 30일 이후 스냅샷 사이의 일평균 증가) ÷ (전체 기간 일평균).

    0에 가까우면 조회수가 멈춘 영상, 1에 가까우면 초반과 비슷한 속도로 계속 늘어나는 영상.
    """
    pub = parse_dt(published_at)
    if pub is None:
        return None
    points = []
    for h in history:
        at = parse_dt(h.get("captured_at"))
        if at is not None and h.get("views") is not None and (at - pub).total_seconds() / 86400 >= min_age_days:
            points.append((at, h["views"]))
    if len(points) < 2:
        return None
    points.sort()
    (t0, v0), (t1, v1) = points[0], points[-1]
    span = (t1 - t0).total_seconds() / 86400
    lifetime = (t1 - pub).total_seconds() / 86400
    if span < 1 or v1 <= 0 or lifetime <= 0:
        return None
    return ((v1 - v0) / span) / (v1 / lifetime)


def _sorted_desc(videos: list[dict]) -> list[dict]:
    return sorted((v for v in videos if v.get("published_at")), key=lambda v: v["published_at"], reverse=True)


def compute_channel_metrics(videos: list[dict], subscribers: int | None, now: datetime | None = None,
                            criteria: Criteria | None = None, min_age_days: int = 7) -> dict:
    now = now or datetime.now(timezone.utc)
    criteria = criteria or Criteria()
    all_sorted = _sorted_desc(videos)
    longs = longform(all_sorted)

    in90 = [v for v in longs if (age_days(v["published_at"], now) or 0) <= 90]
    window = in90 + longs[len(in90):len(in90) + 1]  # 90일 창으로 들어오기 직전 영상까지 포함해 공백 계산
    dates = sorted(parse_dt(v["published_at"]) for v in window)
    gaps = [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]

    matured = [v for v in longs
               if v.get("views") is not None and (age_days(v["published_at"], now) or 0) >= min_age_days][:criteria.recent_n]
    views = [v["views"] for v in matured]
    median_views = float(median(views)) if views else None

    ratio, primary, counts = content_types.summarize([v.get("content_type") for v in longs[:20]])
    recent_all = all_sorted[:50]
    shorts_ratio = (sum(1 for v in recent_all if v.get("is_short")) / len(recent_all)) if recent_all else 0.0

    return {
        "longform_count": len(longs),
        "uploads_90d": len(in90),
        "median_gap_days": float(median(gaps)) if gaps else None,
        "max_gap_days": max(gaps) if gaps else None,
        "days_since_last": age_days(longs[0]["published_at"], now) if longs else None,
        "median_views": median_views,
        "mean_views": float(mean(views)) if views else None,
        "min_views": float(min(views)) if views else None,
        "median_to_subs": (median_views / subscribers) if median_views is not None and subscribers else None,
        "travel_ratio": ratio,
        "primary_type": primary,
        "type_counts": counts,
        "shorts_ratio": shorts_ratio,
    }


def evaluate_criteria(metrics: dict, subscribers: int | None, criteria: Criteria) -> list[dict]:
    """숨은 고수 조건 중 못 채운 항목 목록 (비어 있으면 통과)."""
    checks = [
        ("subscribers", subscribers, criteria.max_subscribers, lambda a, t: a is not None and a < t, "미만"),
        ("uploads_90d", metrics.get("uploads_90d"), criteria.min_uploads_90d, lambda a, t: a is not None and a >= t, "이상"),
        ("median_gap_days", metrics.get("median_gap_days"), criteria.max_median_gap_days, lambda a, t: a is not None and a <= t, "일 이하"),
        ("max_gap_days", metrics.get("max_gap_days"), criteria.max_gap_days, lambda a, t: a is not None and a <= t, "일 이하"),
        ("days_since_last", metrics.get("days_since_last"), criteria.max_days_since_last, lambda a, t: a is not None and a <= t, "일 이내"),
        ("median_views", metrics.get("median_views"), criteria.min_median_views, lambda a, t: a is not None and a >= t, "이상"),
        ("travel_ratio", metrics.get("travel_ratio"), criteria.min_travel_ratio, lambda a, t: a is not None and a >= t, "이상"),
    ]
    failed = []
    for key, actual, threshold, ok, unit in checks:
        if not ok(actual, threshold):
            failed.append({"key": key, "label": CRITERIA_LABELS[key], "actual": actual, "threshold": threshold, "unit": unit})
    return failed


def graduated(history: list[dict], threshold: int) -> bool:
    """스냅샷 기록상 threshold 미만이었다가 넘어선 채널인가."""
    subs = [h.get("subscribers") for h in sorted(history, key=lambda h: h.get("captured_at") or "") if h.get("subscribers") is not None]
    if len(subs) < 2:
        return False
    return subs[-1] >= threshold and any(s < threshold for s in subs[:-1])


def classify_group(is_role_model: bool, subscribers: int | None, metrics: dict, failed: list[dict],
                   history: list[dict], criteria: Criteria) -> str:
    if is_role_model:
        return "role_model"
    if graduated(history, criteria.max_subscribers):
        return "graduated"
    if subscribers is None or subscribers >= criteria.max_subscribers:
        return "big"
    failed_keys = {f["key"] for f in failed}
    if "travel_ratio" in failed_keys:
        return "not_travel"
    if not failed_keys:
        return "hidden_gem"
    if len(failed_keys) == 1:
        return "near"
    return "pool"


def turning_point(videos: list[dict], factor: float = 3.0, window: int = 10, min_prior: int = 5,
                  now: datetime | None = None, min_age_days: int = 7) -> dict | None:
    """직전 window개 롱폼 조회수 중앙값의 factor배 이상 나온 첫 영상."""
    now = now or datetime.now(timezone.utc)
    longs = [v for v in sorted(longform(videos), key=lambda v: v.get("published_at") or "")
             if v.get("views") is not None and (age_days(v.get("published_at"), now) or 0) >= min_age_days]
    for i in range(min_prior, len(longs)):
        prior = longs[max(0, i - window):i]
        prior_median = median(v["views"] for v in prior)
        if prior_median > 0 and longs[i]["views"] >= factor * prior_median:
            after = longs[i:i + window]
            type_before = _dominant([v.get("content_type") for v in prior])
            type_after = _dominant([v.get("content_type") for v in after])
            return {
                "video_id": longs[i]["video_id"],
                "title": longs[i].get("title"),
                "index": i,
                "published_at": longs[i]["published_at"],
                "views": longs[i]["views"],
                "prior_median": float(prior_median),
                "ratio": longs[i]["views"] / prior_median,
                "type_before": type_before,
                "type_after": type_after,
                "type_changed": bool(type_before and type_after and type_before != type_after),
            }
    return None


def _dominant(types: list[str | None]) -> str | None:
    counts = Counter(t for t in types if t)
    return counts.most_common(1)[0][0] if counts else None
