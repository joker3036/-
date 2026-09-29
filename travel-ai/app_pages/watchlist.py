import pandas as pd
import streamlit as st

from core import analyzer, collector, db, discovery, metrics, queries
from ui import charts, render
from ui.common import (channel_url, demo_banner, fmt_days, fmt_int, fmt_ratio, get_conn, get_settings, group_label,
                       open_video, progress_callback, quota_sidebar, require_client, type_label)

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("📌 관심 채널")
st.caption("롤모델·숨은 고수·근접 후보·관문 돌파 채널을 추적해요. 갱신할 때마다 구독자·조회수 스냅샷이 쌓여요 (주 1회 권장).")
demo_banner()

channels = queries.channels_df(conn)
if channels.empty:
    st.info("아직 채널이 없어요. 채널 발굴에서 먼저 채널을 모아 주세요.")
    st.stop()

tracked = channels[(channels["pinned"] == 1) | (channels["is_role_model"] == 1)]
c1, c2 = st.columns([3, 1])
c1.caption(f"📌 관심 채널 {len(tracked)}개 · 갱신 예상 사용량 약 {len(tracked) * 3} 유닛")
if c2.button("🔄 관심 채널 전체 갱신", disabled=tracked.empty):
    client = require_client(conn, settings)
    if client:
        with st.status("갱신 중...", expanded=True):
            report = collector.refresh_channels(conn, client, tracked["channel_id"].tolist(), settings, progress_callback("채널"))
        st.success(report.summary())
        for m in report.messages:
            st.caption("• " + m)

GROUP_TABS = [("pinned", "📌 전체 관심"), ("role_model", "⭐ 롤모델"), ("hidden_gem", "🎯 숨은 고수"), ("near", "🌱 근접 후보"),
              ("graduated", "🎓 관문 돌파")]
tabs = st.tabs([label for _, label in GROUP_TABS])
for (key, _label), tab in zip(GROUP_TABS, tabs):
    with tab:
        subset = tracked if key == "pinned" else channels[channels["grp"] == key]
        if subset.empty:
            st.caption("해당하는 채널이 없어요.")
            continue
        view = pd.DataFrame({
            "채널": subset["title"], "📌": subset["pinned"].astype(bool), "그룹": subset["grp"].apply(group_label),
            "주 유형": subset["primary_type"].apply(type_label), "구독자": subset["subscribers"],
            "조회수 중앙값": subset["median_views"].round(), "중앙값÷구독자": subset["median_to_subs"],
            "90일 롱폼": subset["uploads_90d"], "마지막 업로드": subset["days_since_last"],
        })
        st.dataframe(view, hide_index=True, column_config={
            "구독자": st.column_config.NumberColumn(format="localized"),
            "조회수 중앙값": st.column_config.NumberColumn(format="localized"),
            "중앙값÷구독자": st.column_config.NumberColumn(format="%.2f배"),
            "마지막 업로드": st.column_config.NumberColumn(format="%.0f일 전"),
        })
        if key in ("hidden_gem", "near", "graduated") and st.button("이 그룹 전부 📌 관심 채널로", key=f"pin_{key}"):
            for cid in subset["channel_id"]:
                discovery.set_pinned(conn, cid, True)
            st.rerun()

st.divider()
st.subheader("채널 자세히 보기")
candidates = channels[(channels["pinned"] == 1) | channels["grp"].isin(["role_model", "hidden_gem", "near", "graduated", "pool"])]
options = candidates.sort_values("title")["channel_id"].tolist()
titles = dict(zip(candidates["channel_id"], candidates["title"] + " · " + candidates["grp"].apply(group_label)))
default = st.session_state.get("channel_id")
index = options.index(default) if default in options else 0
cid = st.selectbox("채널", options, index=index, format_func=titles.get)
if not cid:
    st.stop()
st.session_state["channel_id"] = cid
ch = channels[channels["channel_id"] == cid].iloc[0]

st.markdown(f"### {ch['title']}  \n{group_label(ch['grp'])} · {type_label(ch['primary_type'])} · [유튜브에서 열기]({channel_url(cid)})")
m = st.columns(6)
m[0].metric("구독자", fmt_int(ch["subscribers"]))
m[1].metric("조회수 중앙값", fmt_int(ch["median_views"]), help=f"평균 {fmt_int(ch['mean_views'])}")
m[2].metric("중앙값÷구독자", fmt_ratio(ch["median_to_subs"], 2))
m[3].metric("90일 롱폼", f"{int(ch['uploads_90d'] or 0)}개")
m[4].metric("업로드 간격", fmt_days(ch["median_gap_days"]), help=f"최대 공백 {fmt_days(ch['max_gap_days'])}")
m[5].metric("여행 관련", f"{(ch['travel_ratio'] or 0) * 100:.0f}%")
failed = [f for f in ch["failed"] if f["key"] != "subscribers"]
if failed and ch["grp"] not in ("role_model",):
    st.caption("숨은 고수 기준 미달: " + ", ".join(
        f"{f['label']} ({'-' if f['actual'] is None else round(f['actual'], 1)} → 기준 {f['threshold']}{f['unit']})" for f in failed))

t1, t2, t3, t4 = st.columns(4)
if t1.toggle("📌 관심 채널", value=bool(ch["pinned"]), key=f"pin_toggle_{cid}") != bool(ch["pinned"]):
    discovery.set_pinned(conn, cid, not bool(ch["pinned"]))
    st.rerun()
if t2.toggle("⭐ 롤모델", value=bool(ch["is_role_model"]), key=f"rm_toggle_{cid}") != bool(ch["is_role_model"]):
    discovery.set_role_model(conn, cid, not bool(ch["is_role_model"]), settings)
    st.rerun()
override_opts = {None: "자동 판별", True: "여행 채널로 인정", False: "여행 무관으로"}
current = None if pd.isna(ch["travel_override"]) else bool(ch["travel_override"])
choice = t3.selectbox("여행 판별", list(override_opts), index=list(override_opts).index(current), format_func=override_opts.get,
                      key=f"override_{cid}")
if choice != current:
    discovery.set_travel_override(conn, cid, choice, settings)
    st.rerun()

history = pd.DataFrame(db.channel_history(conn, cid))
if len(history) >= 2:
    st.markdown("#### 구독자 추이")
    st.altair_chart(charts.subscriber_trend(history, settings.criteria.max_subscribers), width="stretch")

st.markdown("#### 📈 성장 타임라인 (롱폼)")
videos = queries.videos_df(conn, settings)
chv = videos[(videos["channel_id"] == cid) & (videos["is_short"] == 0) & videos["views"].notna()] if not videos.empty else videos
timeline_at = db.get_meta(conn, f"timeline:{cid}")
st.caption(f"저장된 롱폼 {len(chv)}개" + (f" · 전체 업로드 수집: {timeline_at[:10]}" if timeline_at else
           " · 최근 영상만 있어요. 전체 업로드를 모으면 성장 과정을 정확히 볼 수 있어요."))
if t4.button("전체 업로드 수집", help="채널의 모든 영상을 가져와요 (영상 50개당 약 2유닛)"):
    client = require_client(conn, settings)
    if client:
        with st.spinner("전체 업로드 수집 중..."):
            n = collector.fetch_full_timeline(conn, client, cid, settings)
        st.success(f"{n}개 영상을 저장했어요.")
        st.rerun()

if not chv.empty:
    records = chv.astype(object).where(chv.notna(), None).to_dict("records")
    tp = metrics.turning_point(records, settings.turning_point_factor, min_age_days=settings.min_video_age_days)
    st.altair_chart(charts.timeline_chart(chv, tp["video_id"] if tp else None), width="stretch")
    if tp:
        change = (f" · 유형 변화: {type_label(tp['type_before'])} → {type_label(tp['type_after'])}" if tp["type_changed"] else "")
        st.info(f"**터닝포인트**: {tp['published_at'][:10]} \"{tp['title']}\" — 직전 10개 중앙값 {fmt_int(tp['prior_median'])}의 "
                f"{tp['ratio']:.1f}배 ({fmt_int(tp['views'])}회){change}")
    else:
        st.caption("직전 10개 중앙값의 3배 이상 나온 영상이 아직 없어요.")

st.markdown("#### 🤖 AI 채널 분석")
kinds = [("hidden_gem", "숨은 고수 분석"), ("contrast", "대조 분석 (떡상 vs 평범)"), ("growth", "성장·터닝포인트 분석")]
cols = st.columns(len(kinds))
for col, (kind, label) in zip(cols, kinds):
    existing = db.get_analysis(conn, cid, kind)
    run_label = ("다시 " if existing and existing["status"] == "done" else "") + label
    if col.button(run_label, key=f"run_{kind}"):
        analyzer.enqueue(conn, [cid], kind, force=True)
        with st.spinner(f"{label} 중... (1~3분)"):
            try:
                analyzer.analyze_channel(conn, cid, kind, settings)
            except Exception as exc:
                db.save_analysis(conn, cid, kind, "error", error=str(exc))
                st.error(f"실패: {exc}")
        st.rerun()
for kind, label in kinds:
    existing = db.get_analysis(conn, cid, kind)
    if existing and existing["status"] == "done":
        with st.expander(f"{label} 결과 ({existing['created_at'][:10]}, {existing['model']})", expanded=kind == "hidden_gem"):
            render.channel_analysis(kind, existing["result"])
    elif existing and existing["status"] == "error":
        st.caption(f"{label} 오류: {existing['error']}")

st.markdown("#### 최근 영상")
if not chv.empty:
    recent = chv.sort_values("published", ascending=False).head(50)
    table = pd.DataFrame({
        "video_id": recent["video_id"], "썸네일": recent["thumbnail_url"], "제목": recent["title"],
        "업로드": recent["published"].dt.strftime("%Y-%m-%d"), "조회수": recent["views"], "채널 평소 대비": recent["outlier"],
        "돌파 지수": recent["breakout"], "유형": recent["content_type"].apply(type_label),
        "분석": recent["analysis_status"].map({"done": "✅", "pending": "⏳", "error": "⚠️"}).fillna(""),
    })
    event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", key="ch_videos",
                         column_order=[c for c in table.columns if c != "video_id"],
                         column_config={"썸네일": st.column_config.ImageColumn(width="small"),
                                        "조회수": st.column_config.NumberColumn(format="localized"),
                                        "채널 평소 대비": st.column_config.NumberColumn(format="%.1f배"),
                                        "돌파 지수": st.column_config.NumberColumn(format="%.1f배")})
    if event.selection.rows:
        vid = table.iloc[event.selection.rows[0]]["video_id"]
        if st.button("🎬 선택한 영상 상세 보기"):
            open_video(vid)
