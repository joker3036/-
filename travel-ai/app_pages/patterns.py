import pandas as pd
import streamlit as st

from core import analyzer, content_types, db, queries
from ui import charts, render
from ui.common import demo_banner, get_conn, get_settings, quota_sidebar

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("📊 패턴 분석")
st.caption("어떤 기획·제목·유형이 구독자에 비해 조회수를 잘 뽑았는지 모아서 봐요. 값은 돌파 지수(조회수÷구독자)의 중앙값이에요.")
demo_banner()

videos = queries.videos_df(conn, settings)
if videos.empty:
    st.info("아직 영상이 없어요.")
    st.stop()

scope = st.radio("범위", ["small", "all"], horizontal=True,
                 format_func={"small": "구독 1만 미만 채널", "all": "전체 채널"}.get)
base = videos[(videos["is_short"] == 0) & videos["mature"] & videos["breakout"].notna()]
if scope == "small":
    base = base[base["subscribers"] < settings.criteria.max_subscribers]


def grouped(df: pd.DataFrame, col: str) -> pd.DataFrame:
    g = df.groupby(col)["breakout"].agg(["median", "count"]).reset_index()
    return g.rename(columns={col: "항목", "median": "값", "count": "개수"})


def show(df: pd.DataFrame, title: str, min_count: int = 1) -> None:
    df = df[df["개수"] >= min_count]
    if df.empty:
        st.caption(f"{title}: 데이터 부족")
        return
    st.markdown(f"**{title}**")
    st.altair_chart(charts.mean_bars(df, "항목", "값", "개수", "돌파 지수 중앙값 (배)"), width="stretch")


st.subheader("🤖 AI 분석 기반")
an = queries.analyses_df(conn, "video")
if an.empty:
    st.info("아직 AI 분석한 영상이 없어요. 떡상 영상 페이지에서 분석을 돌려 보세요.")
else:
    merged = an.merge(base[["video_id", "breakout"]], left_on="target_id", right_on="video_id")
    st.caption(f"분석한 영상 {len(merged)}개 기준" + (" — 표본이 적어서 참고용이에요." if len(merged) < 10 else ""))
    if not merged.empty:
        c1, c2 = st.columns(2)
        with c1:
            show(grouped(merged.explode("planning_devices").dropna(subset=["planning_devices"]), "planning_devices"), "기획 장치별")
            sig = merged.assign(시그니처=merged["signature_elements"].apply(lambda x: "시그니처 있음" if x else "시그니처 없음"))
            show(grouped(sig, "시그니처"), "매 영상 반복되는 시그니처 요소")
        with c2:
            show(grouped(merged.explode("title_devices").dropna(subset=["title_devices"]), "title_devices"), "제목 장치별")
            dens = merged.assign(정보=merged["info_density"].apply(lambda d: f"정보 밀도 {(d or {}).get('level', '-')}"))
            show(grouped(dens, "정보"), "정보 밀도별")
            hook = merged.assign(훅=merged["hook"].apply(lambda d: (d or {}).get("type", "-")))
            show(grouped(hook, "훅"), "훅 유형별")

st.subheader("📐 규칙 기반 (전체 롱폼)")
st.caption(f"롱폼 {len(base):,}개 기준. 제목 사전으로 나눈 유형·길이·요일별 비교예요.")
c1, c2 = st.columns(2)
with c1:
    typed = base.assign(유형=base["content_type"].apply(lambda k: content_types.label(k if isinstance(k, str) else None, with_icon=False)))
    show(grouped(typed, "유형"), "콘텐츠 유형별", 3)
    bins = pd.cut(base["duration_s"] / 60, [0, 10, 20, 30, 1_000], labels=["10분 미만", "10~20분", "20~30분", "30분 이상"])
    show(grouped(base.assign(길이=bins.astype(str)), "길이"), "영상 길이별", 3)
with c2:
    days = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = base["published"].dt.tz_convert("Asia/Seoul").dt.weekday.map(lambda d: f"{days[d]}요일")
    show(grouped(base.assign(요일=weekday), "요일"), "업로드 요일별 (한국 시간)", 3)
    tail = queries.longtail_df(conn)
    if not tail.empty:
        tail = tail.assign(항목=tail["content_type"].apply(lambda k: content_types.label(k if isinstance(k, str) else None, with_icon=False)))
        g = tail.groupby("항목")["longtail"].agg(["mean", "count"]).reset_index().rename(columns={"mean": "값", "count": "개수"})
        st.markdown("**유형별 롱테일 지수** (1에 가까울수록 30일 이후에도 꾸준히 조회)")
        st.altair_chart(charts.mean_bars(g, "항목", "값", "개수", "롱테일 지수 평균", ".2f"), width="stretch")
    else:
        st.caption("롱테일 지수: 관심 채널을 두 번 이상 갱신하면 계산돼요.")

st.subheader("📝 채널 분석 리포트")
rows = conn.execute(
    "SELECT a.target_id, a.kind, a.created_at, c.title FROM analyses a JOIN channels c ON c.channel_id = a.target_id "
    "WHERE a.status='done' AND a.kind IN ('hidden_gem','contrast','growth') ORDER BY a.created_at DESC"
).fetchall()
if not rows:
    st.caption("관심 채널 페이지에서 채널 분석을 돌리면 여기 모여요.")
for r in rows:
    with st.expander(f"{r['title']} — {analyzer.KIND_LABELS[r['kind']]} ({r['created_at'][:10]})"):
        render.channel_analysis(r["kind"], db.get_analysis(conn, r["target_id"], r["kind"])["result"])
