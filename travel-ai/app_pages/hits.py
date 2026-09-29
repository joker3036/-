import pandas as pd
import streamlit as st

from core import analyzer, content_types, queries
from ui import charts
from ui.common import (demo_banner, get_client, get_conn, get_settings, open_video, progress_callback, quota_sidebar,
                       type_label)

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("🔥 떡상 영상")
st.caption("돌파 지수 = 조회수 ÷ 구독자. 구독 100만 채널의 10만 조회는 0.1배지만, 구독 5천 채널의 10만 조회는 20배예요. "
           "채널 평소 대비 = 조회수 ÷ 그 채널 최근 롱폼 조회수 중앙값.")
demo_banner()

videos = queries.videos_df(conn, settings)
if videos.empty:
    st.info("아직 영상이 없어요. 채널 발굴부터 해 주세요.")
    st.stop()

f1, f2, f3, f4, f5 = st.columns([1.2, 1.2, 2, 1.2, 1.2])
period = f1.selectbox("업로드 기간", [30, 90, 365, 0], index=1, format_func=lambda d: f"최근 {d}일" if d else "전체")
size = f2.selectbox("채널 규모", ["small", "all"], format_func={"small": "구독 1만 미만만", "all": "전체 (대형 채널과 비교)"}.get)
types = f3.multiselect("유형", list(content_types.TYPES), format_func=content_types.label, placeholder="전체")
min_breakout = f4.number_input("돌파 지수 이상", 0.0, 1000.0, 0.0, step=0.5)
status = f5.selectbox("AI 분석", ["all", "done", "todo"], format_func={"all": "전체", "done": "분석함", "todo": "안 함"}.get)

view = videos[(videos["is_short"] == 0) & videos["mature"] & videos["views"].notna() & videos["subscribers"].notna()]
if period:
    view = view[view["age_days"] <= period]
if size == "small":
    view = view[view["subscribers"] < settings.criteria.max_subscribers]
if types:
    view = view[view["content_type"].isin(types)]
if min_breakout:
    view = view[view["breakout"] >= min_breakout]
if status == "done":
    view = view[view["analysis_status"] == "done"]
elif status == "todo":
    view = view[view["analysis_status"] != "done"]
st.caption(f"롱폼 {len(view):,}개 (업로드 {settings.min_video_age_days}일 이상 지난 영상만). 점을 누르면 아래에서 상세로 갈 수 있어요.")

if view.empty:
    st.info("조건에 맞는 영상이 없어요.")
    st.stop()

state = st.altair_chart(charts.breakout_scatter(view, settings.criteria.max_subscribers), width="stretch",
                        on_select="rerun", key="scatter")
picked = (state.selection.get("pick") or []) if state and hasattr(state, "selection") else []
if picked:
    vid = picked[0].get("video_id")
    row = view[view["video_id"] == vid]
    if not row.empty and st.button(f"🎬 '{row.iloc[0]['title'][:40]}' 상세 보기", type="primary"):
        open_video(vid)

st.subheader("돌파 지수 순")
ranked = view.sort_values("breakout", ascending=False).head(200)
table = pd.DataFrame({
    "video_id": ranked["video_id"], "썸네일": ranked["thumbnail_url"], "제목": ranked["title"], "채널": ranked["channel_title"],
    "구독자": ranked["subscribers"], "조회수": ranked["views"], "돌파 지수": ranked["breakout"], "채널 평소 대비": ranked["outlier"],
    "유형": ranked["content_type"].apply(type_label), "업로드": ranked["published"].dt.strftime("%Y-%m-%d"),
    "분석": ranked["analysis_status"].map({"done": "✅", "pending": "⏳", "error": "⚠️"}).fillna(""),
})
event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="multi-row", key="hits_table",
                     column_order=[c for c in table.columns if c != "video_id"],
                     column_config={"썸네일": st.column_config.ImageColumn(width="small"),
                                    "제목": st.column_config.TextColumn(width="large"),
                                    "구독자": st.column_config.NumberColumn(format="localized"),
                                    "조회수": st.column_config.NumberColumn(format="localized"),
                                    "돌파 지수": st.column_config.NumberColumn(format="%.1f배"),
                                    "채널 평소 대비": st.column_config.NumberColumn(format="%.1f배")})
selected = table.iloc[event.selection.rows]["video_id"].tolist() if event.selection.rows else []

st.markdown("#### 🤖 AI 분석")
st.caption("Claude 구독으로 분석해요 (영상당 1~2분). 자막·댓글·썸네일을 모아 기획 장치·시그니처·훅·시청자 니즈를 뽑아요.")
c1, c2, c3, c4 = st.columns(4)
if c1.button(f"선택한 {len(selected)}개 대기열에 추가", disabled=not selected):
    st.success(f"{analyzer.enqueue(conn, selected, 'video', force=True)}개 추가했어요.")
auto_n = c2.number_input("자동 선택 개수", 1, 50, 10)
if c3.button("돌파 영상 자동 선택"):
    cands = analyzer.candidate_videos(conn, settings, int(auto_n))
    added = analyzer.enqueue(conn, cands["video_id"].tolist() if not cands.empty else [], "video")
    st.success(f"기준(돌파 지수 {settings.breakout_threshold}배 또는 채널 평소 대비 {settings.outlier_threshold}배 이상)에 맞는 영상 {added}개를 추가했어요.")
pending = len(analyzer.pending_items(conn))
if c4.button(f"대기열 실행 ({min(pending, settings.analysis_batch_size)}개)", type="primary", disabled=pending == 0):
    with st.status("AI 분석 중... 창을 닫지 마세요", expanded=True):
        result = analyzer.process_queue(conn, settings, get_client(conn, settings), progress=progress_callback("분석"))
    st.success(f"완료 {result.done}개")
    for e in result.errors:
        st.caption("⚠️ " + e)
    if result.stopped:
        st.warning(result.stopped)
if len(selected) == 1 and st.button("🎬 선택한 영상 상세 보기"):
    open_video(selected[0])
