import json

import pandas as pd
import streamlit as st

from core import analyzer, db, metrics, queries
from ui import render
from ui.common import (demo_banner, fmt_int, fmt_ratio, get_client, get_conn, get_settings, open_channel, quota_sidebar,
                       type_label, video_url)

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("🎬 영상 상세")
demo_banner()

videos = queries.videos_df(conn, settings)
if videos.empty:
    st.info("아직 영상이 없어요.")
    st.stop()

pool = videos[(videos["is_short"] == 0)].sort_values("breakout", ascending=False)
options = pool["video_id"].tolist()
labels = dict(zip(pool["video_id"], pool["title"].fillna("") + " — " + pool["channel_title"].fillna("")))
default = st.session_state.get("video_id")
if default not in options and default in videos["video_id"].values:
    options.insert(0, default)
    labels[default] = videos.set_index("video_id").loc[default, "title"]
vid = st.selectbox("영상 (돌파 지수 순)", options, index=options.index(default) if default in options else 0, format_func=labels.get)
st.session_state["video_id"] = vid
v = videos[videos["video_id"] == vid].iloc[0]

c1, c2 = st.columns([1, 2])
with c1:
    if isinstance(v["thumbnail_url"], str):
        st.image(v["thumbnail_url"], width="stretch")
with c2:
    st.markdown(f"### {v['title']}")
    st.markdown(f"{v['channel_title']} · 구독자 {fmt_int(v['subscribers'])} · {type_label(v['content_type'])}  \n"
                f"[유튜브에서 보기]({video_url(vid)})")
    if st.button("채널 보기"):
        open_channel(v["channel_id"])
m = st.columns(6)
m[0].metric("조회수", fmt_int(v["views"]))
m[1].metric("돌파 지수", fmt_ratio(v["breakout"]), help="조회수 ÷ 구독자")
m[2].metric("채널 평소 대비", fmt_ratio(v["outlier"]), help=f"채널 최근 롱폼 조회수 중앙값 {fmt_int(v['channel_median'])}")
m[3].metric("일평균 조회수", fmt_int(v["daily_views"]))
m[4].metric("길이", f"{int(v['duration_s'] or 0) // 60}분")
m[5].metric("업로드", v["published"].strftime("%y.%m.%d") if not pd.isna(v["published"]) else "-")
tail = metrics.longtail_index(db.video_history(conn, vid), v["published_at"])
if tail is not None:
    st.caption(f"롱테일 지수 {tail:.2f} — 1에 가까울수록 업로드 30일 이후에도 조회수가 꾸준히 늘어요.")

st.divider()
existing = db.get_analysis(conn, vid, "video")
label = "다시 분석" if existing and existing["status"] == "done" else "AI 분석 실행"
if st.button(label, type="primary"):
    analyzer.enqueue(conn, [vid], "video", force=True)
    with st.spinner("자막·댓글·썸네일을 모아 분석하는 중... (1~2분)"):
        try:
            analyzer.analyze_video(conn, vid, settings, get_client(conn, settings))
        except Exception as exc:
            db.save_analysis(conn, vid, "video", "error", error=str(exc))
            st.error(f"분석 실패: {exc}")
    st.rerun()

if existing and existing["status"] == "done":
    st.caption(f"분석: {existing['created_at'][:16].replace('T', ' ')} · 모델 {existing['model']}")
    render.video_analysis(existing["result"])
elif existing and existing["status"] == "pending":
    st.info("AI 분석 대기열에 있어요. 떡상 영상 페이지에서 대기열을 실행하세요.")
elif existing and existing["status"] == "error":
    st.warning(f"지난 분석 오류: {existing['error']}")

extras = conn.execute("SELECT * FROM video_extras WHERE video_id=?", (vid,)).fetchone()
if extras:
    with st.expander(f"자막 ({extras['transcript_note'] or '-'})"):
        st.text(extras["transcript"] or "자막 없음")
    comments = json.loads(extras["comments_json"] or "[]")
    with st.expander(f"댓글 {len(comments)}개"):
        for c in sorted(comments, key=lambda c: -c.get("likes", 0))[:50]:
            st.markdown(f"- (👍 {c.get('likes', 0)}) {c.get('text', '')}")
