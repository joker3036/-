"""대시보드 공통 도우미 (DB 연결, 설정, 숫자 표기, 색상, 진행 표시)."""
from __future__ import annotations

import math

import streamlit as st

from core import collector, config, content_types, db, demo, metrics
from core.youtube import MissingApiKey, YouTubeClient

# 차트 색상 (dataviz 기본 팔레트, 모드별로 따로 고른 값)
PALETTE = {
    "light": {"series1": "#2a78d6", "series2": "#eb6834", "muted": "#898781", "grid": "#e1e0d9", "surface": "#fcfcfb",
              "text2": "#52514e"},
    "dark": {"series1": "#3987e5", "series2": "#d95926", "muted": "#898781", "grid": "#2c2c2a", "surface": "#1a1a19",
             "text2": "#c3c2b7"},
}


def colors() -> dict:
    try:
        mode = st.context.theme.type or "light"
    except Exception:
        mode = "light"
    return PALETTE["dark" if mode == "dark" else "light"]


@st.cache_resource
def _connect(path: str):
    conn = db.connect(path)
    return conn


def get_settings() -> config.Settings:
    if "settings" not in st.session_state:
        st.session_state["settings"] = config.load_settings()
    return st.session_state["settings"]


def save_settings(settings: config.Settings) -> None:
    config.save_settings(settings)
    st.session_state["settings"] = settings


def get_conn():
    settings = get_settings()
    conn = _connect(str(config.db_path()))
    if config.is_demo() and db.get_meta(conn, "demo_built") is None:
        with st.spinner("데모 데이터를 만드는 중..."):
            demo.build_demo(conn, settings)
    if not config.is_demo() and "pruned" not in st.session_state:
        removed = collector.prune_if_due(conn, settings)
        st.session_state["pruned"] = removed
        if removed:
            st.toast(f"30일 넘게 갱신 안 된 채널 {removed}개의 데이터를 정리했어요.")
    return conn


def get_client(conn, settings: config.Settings) -> YouTubeClient | None:
    if config.is_demo():
        return None
    try:
        return YouTubeClient(settings.api_key, conn, unit_budget=settings.daily_unit_budget,
                             search_budget=settings.daily_search_budget)
    except MissingApiKey:
        return None


def require_client(conn, settings) -> YouTubeClient | None:
    client = get_client(conn, settings)
    if client is None:
        if config.is_demo():
            st.info("데모 모드에서는 실제 수집을 하지 않아요.")
        else:
            st.warning("YouTube API 키가 필요해요. **설정** 페이지에서 입력해 주세요.")
    return client


def demo_banner() -> None:
    if config.is_demo():
        st.caption("🧪 데모 모드 — 모든 채널·영상·분석은 가상 데이터입니다.")


def fmt_int(n) -> str:
    """한국식 큰 수 표기: 12,345 → 1.2만, 123,456,789 → 1.2억."""
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return "-"
    n = float(n)
    if abs(n) >= 1e8:
        return f"{n / 1e8:.1f}억"
    if abs(n) >= 1e4:
        return f"{n / 1e4:.1f}만"
    return f"{n:,.0f}"


def fmt_ratio(x, digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:.{digits}f}배"


def fmt_days(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:.0f}일"


def type_label(key) -> str:
    return content_types.label(key if isinstance(key, str) else None)


def group_label(key) -> str:
    return metrics.GROUPS.get(key, key or "-")


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def progress_callback(label: str):
    bar = st.progress(0.0, text=label)

    def update(n: int, total: int, item: str) -> None:
        bar.progress(min(n / max(total, 1), 1.0), text=f"{label} ({n}/{total}) {item}")

    return update


def quota_sidebar(conn, settings) -> None:
    with st.sidebar:
        st.caption("오늘 사용량 (태평양 시간 기준 초기화)")
        c1, c2 = st.columns(2)
        c1.metric("공식 검색", f"{db.get_usage(conn, 'search')}/{settings.daily_search_budget}")
        c2.metric("API 유닛", f"{fmt_int(db.get_usage(conn, 'units'))}")
        pending = conn.execute("SELECT COUNT(*) FROM analyses WHERE status='pending'").fetchone()[0]
        st.caption(f"AI 분석 대기열: {pending}개")
        if settings.use_unofficial_search:
            st.caption("비공식 검색: 켜짐")


def criteria_form(conn, settings: config.Settings, key: str) -> None:
    """숨은 고수 기준 슬라이더. 저장하면 모든 채널을 다시 분류한다 (API 호출 없음)."""
    from core import discovery

    cr = settings.criteria
    with st.form(f"criteria_{key}"):
        c1, c2, c3 = st.columns(3)
        max_subs = c1.number_input("구독자 미만", 1_000, 1_000_000, cr.max_subscribers, step=1_000)
        min_views = c1.number_input("최근 롱폼 조회수 중앙값 이상", 0, 10_000_000, cr.min_median_views, step=1_000)
        recent_n = c1.slider("조회수 계산에 쓸 최근 영상 수", 5, 30, cr.recent_n)
        min_uploads = c2.slider("최근 90일 롱폼 수 이상", 1, 30, cr.min_uploads_90d)
        med_gap = c2.slider("업로드 간격 중앙값 (일 이하)", 1, 60, int(cr.max_median_gap_days))
        max_gap = c2.slider("가장 긴 공백 (일 이하)", 1, 120, int(cr.max_gap_days))
        since_last = c3.slider("마지막 업로드 (일 이내)", 1, 120, int(cr.max_days_since_last))
        travel = c3.slider("여행 관련 영상 비율 (% 이상)", 0, 100, int(cr.min_travel_ratio * 100), step=5)
        if st.form_submit_button("기준 저장하고 다시 분류", type="primary"):
            cr.max_subscribers, cr.min_median_views, cr.recent_n = int(max_subs), int(min_views), int(recent_n)
            cr.min_uploads_90d, cr.max_median_gap_days, cr.max_gap_days = int(min_uploads), float(med_gap), float(max_gap)
            cr.max_days_since_last, cr.min_travel_ratio = float(since_last), travel / 100
            save_settings(settings)
            groups = discovery.reclassify_all(conn, settings)
            st.success("다시 분류했어요: " + ", ".join(f"{group_label(g)} {n}" for g, n in groups.most_common()))


def open_video(video_id: str) -> None:
    st.session_state["video_id"] = video_id
    st.switch_page("app_pages/video.py")


def open_channel(channel_id: str) -> None:
    st.session_state["channel_id"] = channel_id
    st.switch_page("app_pages/watchlist.py")
