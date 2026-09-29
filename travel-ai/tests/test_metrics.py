import pytest

from core import metrics
from core.config import Criteria

from .conftest import NOW, make_video


def weekly_channel(n=12, views=12_000, gap=7.0, start=3.0, content_type="stay"):
    return [make_video(f"v{i:02d}", start + i * gap, views, content_type=content_type) for i in range(n)]


def test_breakout_and_outlier():
    assert metrics.breakout_index(100_000, 1_000_000) == pytest.approx(0.1)
    assert metrics.breakout_index(100_000, 5_000) == pytest.approx(20)
    assert metrics.breakout_index(100, 0) is None
    assert metrics.outlier_score(30_000, 10_000) == pytest.approx(3)
    assert metrics.outlier_score(None, 10_000) is None


def test_channel_median_excludes_young_and_shorts():
    videos = [make_video("young", 2, 999_999), make_video("short", 20, 999_999, is_short=1),
              make_video("a", 10, 1_000), make_video("b", 20, 3_000), make_video("c", 30, 2_000)]
    assert metrics.channel_median_views(videos, NOW, min_age_days=7) == 2_000


def test_consistent_channel_metrics():
    m = metrics.compute_channel_metrics(weekly_channel(), 8_000, NOW)
    assert m["uploads_90d"] == 12
    assert m["median_gap_days"] == pytest.approx(7)
    assert m["max_gap_days"] == pytest.approx(7)
    assert m["days_since_last"] == pytest.approx(3)
    assert m["median_views"] == 12_000
    assert m["median_to_subs"] == pytest.approx(1.5)
    assert m["travel_ratio"] == 1.0 and m["primary_type"] == "stay"


def test_median_resists_one_viral_video():
    videos = weekly_channel(views=2_000)
    videos[1]["views"] = 200_000  # 한 영상만 터짐
    m = metrics.compute_channel_metrics(videos, 5_000, NOW)
    assert m["median_views"] == 2_000
    assert m["mean_views"] > 10_000  # 평균은 1만을 넘지만


def test_evaluate_criteria_boundaries():
    cr = Criteria()
    base = {"uploads_90d": 6, "median_gap_days": 14.0, "max_gap_days": 28.0, "days_since_last": 21.0,
            "median_views": 10_000, "travel_ratio": 0.5}
    assert metrics.evaluate_criteria(base, 9_999, cr) == []
    assert [f["key"] for f in metrics.evaluate_criteria(base, 10_000, cr)] == ["subscribers"]
    worse = {**base, "median_views": 9_999, "median_gap_days": None}
    assert {f["key"] for f in metrics.evaluate_criteria(worse, 5_000, cr)} == {"median_views", "median_gap_days"}


@pytest.mark.parametrize("subs, failed, history, role, expected", [
    (5_000, [], [], False, "hidden_gem"),
    (5_000, ["median_views"], [], False, "near"),
    (5_000, ["median_views", "uploads_90d"], [], False, "pool"),
    (5_000, ["travel_ratio"], [], False, "not_travel"),
    (50_000, ["subscribers"], [], False, "big"),
    (10_400, ["subscribers"], [{"captured_at": "1", "subscribers": 9_800}, {"captured_at": "2", "subscribers": 10_400}], False, "graduated"),
    (500_000, ["subscribers"], [], True, "role_model"),
])
def test_classify_group(subs, failed, history, role, expected):
    f = [{"key": k} for k in failed]
    assert metrics.classify_group(role, subs, {}, f, history, Criteria()) == expected


def test_graduated_needs_history_below_threshold():
    assert not metrics.graduated([{"captured_at": "1", "subscribers": 12_000}, {"captured_at": "2", "subscribers": 13_000}], 10_000)
    assert not metrics.graduated([{"captured_at": "1", "subscribers": 12_000}], 10_000)


def test_turning_point_detects_type_change():
    old = [make_video(f"o{i}", 200 - i * 7, 1_000 + i * 10, content_type="vlog") for i in range(10)]
    tp_video = make_video("tp", 128, 9_000, content_type="stay")
    new = [make_video(f"n{i}", 121 - i * 7, 6_000, content_type="stay") for i in range(10)]
    tp = metrics.turning_point(old + [tp_video] + new, factor=3, now=NOW)
    assert tp["video_id"] == "tp"
    assert tp["type_before"] == "vlog" and tp["type_after"] == "stay" and tp["type_changed"]
    assert tp["ratio"] > 8


def test_turning_point_none_for_flat_channel():
    assert metrics.turning_point(weekly_channel(), now=NOW) is None


def test_longtail_index():
    pub = "2026-01-01T00:00:00+00:00"
    # 100일 동안 10만 → 일평균 1,000. 최근 10일 동안 5,000 증가 → 일평균 500 → 지수 0.5
    history = [{"captured_at": "2026-04-01T00:00:00+00:00", "views": 95_000},
               {"captured_at": "2026-04-11T00:00:00+00:00", "views": 100_000}]
    assert metrics.longtail_index(history, pub) == pytest.approx(500 / (100_000 / 100), rel=1e-3)
    # 업로드 30일 전 스냅샷은 쓰지 않음
    early = [{"captured_at": "2026-01-10T00:00:00+00:00", "views": 10_000}, history[1]]
    assert metrics.longtail_index(early, pub) is None
