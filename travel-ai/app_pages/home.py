import streamlit as st

from core import queries
from ui.common import (demo_banner, fmt_int, fmt_ratio, get_conn, get_settings, group_label, open_channel, open_video,
                       quota_sidebar, type_label)

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("🧳 여행 유튜브 벤치마킹")
st.caption("구독 1만이라는 1차 목표를 위해, 작은 채널의 돌파 영상과 숨은 고수 채널을 모아 공부하는 도구")
demo_banner()

channels = queries.channels_df(conn)
scanned = channels[channels["scan_status"] == "scanned"] if not channels.empty else channels

if scanned.empty:
    st.subheader("시작하기")
    st.markdown(
        "1. **설정**에서 YouTube API 키를 넣으세요 (README에 발급 방법이 있어요).\n"
        "2. **채널 발굴**에서 롤모델 채널 URL을 붙여넣고, 키워드 탐색을 한 번 실행하세요.\n"
        "3. **떡상 영상**에서 구독자에 비해 조회수가 크게 나온 영상을 골라 AI 분석을 돌리세요.\n"
        "4. 쌓인 분석은 **패턴 분석**에서 한눈에 보세요."
    )
    st.page_link("app_pages/settings.py", label="설정으로 가기", icon="⚙️")
    st.page_link("app_pages/discover.py", label="채널 발굴로 가기", icon="🔎")
    st.stop()

counts = scanned["grp"].value_counts()
analyzed = conn.execute("SELECT COUNT(*) FROM analyses WHERE kind='video' AND status='done'").fetchone()[0]
cols = st.columns(5)
cols[0].metric("스캔한 여행 채널", fmt_int(len(scanned[scanned["grp"] != "not_travel"])))
cols[1].metric("🎯 숨은 고수", int(counts.get("hidden_gem", 0)))
cols[2].metric("🌱 근접 후보", int(counts.get("near", 0)))
cols[3].metric("🎓 관문 돌파", int(counts.get("graduated", 0)))
cols[4].metric("🤖 분석한 영상", analyzed)

st.subheader("🔥 최근 30일 돌파 영상 (구독 1만 미만 채널)")
st.caption("돌파 지수 = 조회수 ÷ 구독자. 구독자보다 조회수가 몇 배 나왔는지 보여줘요.")
videos = queries.videos_df(conn, settings)
if not videos.empty:
    top = videos[(videos["is_short"] == 0) & (videos["age_days"] <= 30) & (videos["subscribers"] < settings.criteria.max_subscribers)]
    top = top.sort_values("breakout", ascending=False).head(10)
    if top.empty:
        st.info("최근 30일 안에 올라온 작은 채널 영상이 아직 없어요. 키워드 탐색을 실행해 보세요.")
    else:
        view = top.assign(유형=top["content_type"].apply(type_label))[
            ["thumbnail_url", "title", "channel_title", "subscribers", "views", "breakout", "outlier", "유형", "video_id"]]
        event = st.dataframe(
            view, hide_index=True, on_select="rerun", selection_mode="single-row", key="home_top",
            column_order=["thumbnail_url", "title", "channel_title", "subscribers", "views", "breakout", "outlier", "유형"],
            column_config={
                "thumbnail_url": st.column_config.ImageColumn("썸네일", width="small"),
                "title": st.column_config.TextColumn("제목", width="large"),
                "channel_title": "채널",
                "subscribers": st.column_config.NumberColumn("구독자", format="localized"),
                "views": st.column_config.NumberColumn("조회수", format="localized"),
                "breakout": st.column_config.NumberColumn("돌파 지수", format="%.1f배"),
                "outlier": st.column_config.NumberColumn("채널 평소 대비", format="%.1f배"),
            },
        )
        if event.selection.rows:
            row = view.iloc[event.selection.rows[0]]
            if st.button(f"🎬 '{row['title'][:30]}' 상세 보기"):
                open_video(row["video_id"])

st.subheader("🎯 최근 발견한 숨은 고수")
gems = scanned[scanned["grp"].isin(["hidden_gem", "graduated"])].sort_values("first_seen_at", ascending=False).head(6)
if gems.empty:
    st.info("아직 숨은 고수가 없어요. 채널 발굴에서 키워드 탐색이나 URL 가져오기를 해 보세요.")
for _, g in gems.iterrows():
    c1, c2 = st.columns([5, 1])
    c1.markdown(
        f"**{g['title']}** · {group_label(g['grp'])} · {type_label(g['primary_type'])}  \n"
        f"구독자 {fmt_int(g['subscribers'])} · 조회수 중앙값 {fmt_int(g['median_views'])} "
        f"(구독자의 {fmt_ratio(g['median_to_subs'])}) · 90일 롱폼 {int(g['uploads_90d'] or 0)}개"
    )
    if c2.button("자세히", key=f"gem_{g['channel_id']}"):
        open_channel(g["channel_id"])
