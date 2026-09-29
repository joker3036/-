import pandas as pd
import streamlit as st

from core import analyzer, content_types, discovery, keywords, queries
from core.sources import bulk_import
from ui.common import (criteria_form, demo_banner, get_conn, get_settings, group_label, open_channel, progress_callback,
                       quota_sidebar, require_client, type_label)

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("🔎 채널 발굴")
st.caption("키워드 탐색·URL 가져오기·추천 채널로 여행 채널을 모으고, 우리 기준(꾸준함·조회수 중앙값·돌파 지수)으로 다시 검증해요.")
demo_banner()

TYPE_OPTIONS = list(content_types.TYPES) + ["custom"]


def type_option_label(k: str) -> str:
    return "✍️ 직접 추가한 키워드" if k == "custom" else content_types.label(k)


def show_report(report: discovery.Report) -> None:
    (st.warning if report.stopped_by_quota else st.success)(report.summary())
    for m in report.messages:
        st.caption("• " + m)


tab_kw, tab_import, tab_featured, tab_keywords = st.tabs(["🔎 키워드 탐색", "📥 URL·CSV 가져오기", "🤝 추천 채널 확장", "🧾 키워드 관리"])

with tab_kw:
    mode = "비공식 검색(무료, 한도 없음)이 켜져 있어요. 막히면 자동으로 공식 검색으로 바꿔요." if settings.use_unofficial_search \
        else f"공식 검색을 써요 (하루 {settings.daily_search_budget}회까지)."
    st.caption(mode + " 구독자·조회수 같은 숫자는 항상 공식 API로 가져와요.")
    c1, c2, c3 = st.columns(3)
    kinds = c1.multiselect("키워드 유형", TYPE_OPTIONS, default=TYPE_OPTIONS, format_func=type_option_label, placeholder="전체")
    n_kw = c2.slider("이번에 검색할 키워드 수", 1, settings.max_keywords_per_run, min(10, settings.max_keywords_per_run))
    order = c3.selectbox("정렬", list(discovery.ORDER_LABELS), format_func=discovery.ORDER_LABELS.get)
    duration = "medium"
    if not settings.use_unofficial_search:
        duration = st.radio("영상 길이 (공식 검색)", ["medium", "long", "any"], horizontal=True,
                            format_func={"medium": "4~20분", "long": "20분 이상", "any": "전체"}.get)
    keywords.ensure_keywords(conn)
    preview = keywords.pick_keywords(conn, 8, kinds or None)
    st.caption("다음 키워드 예시: " + ", ".join(preview))
    est = n_kw * (1 + 2 * 15)
    st.caption(f"예상 API 사용량: 최대 약 {est:,} 유닛 (새 채널 1개당 약 2유닛, 이미 스캔한 채널은 {settings.rescan_days}일 동안 건너뜀)")
    if st.button("탐색 실행", type="primary", key="run_discovery"):
        client = require_client(conn, settings)
        if client:
            with st.status("키워드 탐색 중...", expanded=True):
                cb = progress_callback("키워드")
                report = discovery.run_keyword_discovery(conn, client, settings, n_kw, kinds or None, order, duration, progress=cb)
            show_report(report)

with tab_import:
    st.markdown(
        "**1만 미만 여행 채널을 필터로 찾기 좋은 사이트** — 찾은 채널의 주소를 복사해 아래에 붙여넣거나 CSV로 내보내 올리세요.\n"
        "- [블링 vling.net](https://vling.net) — 구독자 수·급상승·카테고리 필터, '요즘 뜨는'\n"
        "- [플레이보드 playboard.co](https://playboard.co) — 카테고리 순위, 성장 추이\n"
        "- [녹스인플루언서](https://kr.noxinfluencer.com) — 카테고리·구독자·국가 필터\n"
        "- [뷰트랩 viewtrap.com](https://app.viewtrap.com) — (유료) 검색어별 조회수·구독자 필터"
    )
    text = st.text_area("채널 주소·@핸들·채널 ID·영상 주소 (여러 개, 줄바꿈이나 쉼표로 구분)", height=140,
                        placeholder="https://www.youtube.com/@채널핸들\n@다른채널\nhttps://www.youtube.com/watch?v=...")
    upload = st.file_uploader("또는 CSV 파일", type=["csv", "tsv", "txt"])
    c1, c2 = st.columns(2)
    as_role = c1.checkbox("⭐ 롤모델로 등록 (구독자 수와 상관없이 추적)")
    as_pin = c2.checkbox("📌 관심 채널로 등록")
    refs, unknown = bulk_import.parse_text(text)
    if upload is not None:
        more, unk = bulk_import.parse_csv(upload.getvalue())
        refs += [r for r in more if (r.kind, r.value) not in {(x.kind, x.value) for x in refs}]
        unknown += unk
    if refs or unknown:
        st.caption(f"해석된 채널 후보 {len(refs)}개" + (f", 해석 못 한 항목 {len(unknown)}개" if unknown else ""))
    if st.button("가져오기", type="primary", disabled=not refs):
        client = require_client(conn, settings)
        if client:
            with st.status("채널 스캔 중...", expanded=True):
                report = discovery.import_channels(conn, client, refs, settings, as_role, as_pin, progress_callback("채널"))
            show_report(report)

with tab_featured:
    st.caption("관심 채널이 채널 페이지에 걸어둔 '추천 채널'을 스캔해요. 비슷한 규모의 여행 유튜버를 찾기 좋아요 (채널당 1유닛).")
    base = conn.execute(
        "SELECT channel_id, title FROM channels WHERE pinned=1 OR grp IN ('hidden_gem','near','graduated','role_model') ORDER BY title"
    ).fetchall()
    options = {r["channel_id"]: r["title"] for r in base}
    picked = st.multiselect("기준 채널", list(options), format_func=options.get, placeholder="채널을 고르세요")
    if st.button("추천 채널 스캔", disabled=not picked):
        client = require_client(conn, settings)
        if client:
            with st.status("추천 채널 스캔 중...", expanded=True):
                report = discovery.expand_featured(conn, client, picked, settings, progress_callback("채널"))
            show_report(report)

with tab_keywords:
    st.caption("키워드는 '지역 × 수식어' 조합과 주제형 키워드로 자동 생성돼요. 좁은 지역 키워드일수록 작은 채널이 잘 나와요.")
    custom = st.text_area("직접 추가할 키워드 (줄바꿈으로 구분)", placeholder="여인숙 투어\n섬 민박 후기")
    if st.button("키워드 추가", disabled=not custom.strip()):
        n = keywords.add_custom_keywords(conn, custom.splitlines())
        st.success(f"{n}개 추가했어요. 다음 탐색에서 먼저 검색해요.")
    kw = pd.read_sql_query("SELECT * FROM keywords", conn)
    if not kw.empty:
        searched = kw[kw["searches"] > 0]
        st.caption(f"전체 {len(kw):,}개 중 {len(searched):,}개 검색함")
        if not searched.empty:
            searched = searched.assign(효율=searched["new_channels"] / searched["searches"]).sort_values("효율", ascending=False)
            st.dataframe(searched.head(30), hide_index=True, column_order=["keyword", "kind", "searches", "results", "new_channels", "효율"],
                         column_config={"keyword": "키워드", "kind": st.column_config.TextColumn("유형"), "searches": "검색 횟수",
                                        "results": "결과 수", "new_channels": "새 채널", "효율": st.column_config.NumberColumn("검색당 새 채널", format="%.1f")})

with st.expander("🎯 숨은 고수 기준 바꾸기"):
    criteria_form(conn, settings, "discover")

st.divider()
st.subheader("모은 채널")
channels = queries.channels_df(conn)
scanned = channels[channels["scan_status"] == "scanned"] if not channels.empty else channels
if scanned.empty:
    st.info("아직 모은 채널이 없어요. 위에서 키워드 탐색이나 URL 가져오기를 해 보세요.")
    st.stop()

group_keys = ["hidden_gem", "near", "graduated", "pool", "role_model", "not_travel"]
f1, f2, f3 = st.columns([2, 2, 1])
groups = f1.multiselect("그룹", group_keys, default=["hidden_gem", "near", "graduated"], format_func=group_label,
                        placeholder="전체")
types = f2.multiselect("주 유형", list(content_types.TYPES), format_func=content_types.label, placeholder="전체")
query = f3.text_input("채널 이름 검색")

view = scanned[scanned["grp"].isin(groups)] if groups else scanned
if types:
    view = view[view["primary_type"].isin(types)]
if query:
    view = view[view["title"].str.contains(query, case=False, na=False)]
view = view.sort_values(["median_to_subs"], ascending=False)


def failed_text(items) -> str:
    return ", ".join(f"{f['label']}" for f in items if f["key"] != "subscribers") or "-"


table = pd.DataFrame({
    "channel_id": view["channel_id"],
    "썸네일": view["thumbnail_url"],
    "채널": view["title"],
    "📌": view["pinned"].astype(bool),
    "그룹": view["grp"].apply(group_label),
    "주 유형": view["primary_type"].apply(type_label),
    "구독자": view["subscribers"],
    "90일 롱폼": view["uploads_90d"],
    "간격 중앙값": view["median_gap_days"],
    "최대 공백": view["max_gap_days"],
    "마지막 업로드": view["days_since_last"],
    "조회수 중앙값": view["median_views"].round(),
    "조회수 평균": view["mean_views"].round(),
    "중앙값÷구독자": view["median_to_subs"],
    "여행 비율": view["travel_ratio"],
    "미달 조건": view["failed"].apply(failed_text),
    "링크": "https://www.youtube.com/channel/" + view["channel_id"],
})
st.caption(f"{len(table)}개 채널 · 표에서 행을 골라 아래 버튼으로 관리하세요.")
event = st.dataframe(
    table, hide_index=True, on_select="rerun", selection_mode="multi-row", key="channel_table",
    column_order=[c for c in table.columns if c != "channel_id"],
    column_config={
        "썸네일": st.column_config.ImageColumn(width="small"),
        "구독자": st.column_config.NumberColumn(format="localized"),
        "간격 중앙값": st.column_config.NumberColumn(format="%.0f일"),
        "최대 공백": st.column_config.NumberColumn(format="%.0f일"),
        "마지막 업로드": st.column_config.NumberColumn(format="%.0f일 전"),
        "조회수 중앙값": st.column_config.NumberColumn(format="localized"),
        "조회수 평균": st.column_config.NumberColumn(format="localized"),
        "중앙값÷구독자": st.column_config.NumberColumn(format="%.2f배"),
        "여행 비율": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "링크": st.column_config.LinkColumn(display_text="열기"),
    },
)
selected = table.iloc[event.selection.rows]["channel_id"].tolist() if event.selection.rows else []
b1, b2, b3, b4, b5 = st.columns(5)
if b1.button("📌 관심 채널로", disabled=not selected):
    for cid in selected:
        discovery.set_pinned(conn, cid, True)
    st.rerun()
if b2.button("📌 해제", disabled=not selected):
    for cid in selected:
        discovery.set_pinned(conn, cid, False)
    st.rerun()
if b3.button("⭐ 롤모델로", disabled=not selected):
    for cid in selected:
        discovery.set_role_model(conn, cid, True, settings)
    st.rerun()
if b4.button("🤖 AI 여행 판별", disabled=not selected, help="여행 관련 비율이 애매한 채널을 AI가 제목을 보고 판별해요"):
    added = analyzer.enqueue(conn, selected, "travel_check", force=True)
    with st.status("AI 판별 중...", expanded=True):
        result = analyzer.process_queue(conn, settings, None, limit=added, progress=progress_callback("판별"))
    if result.stopped:
        st.warning(result.stopped)
    else:
        st.success(f"완료 {result.done}개")
if b5.button("자세히 보기", disabled=len(selected) != 1):
    open_channel(selected[0])

ambiguous = scanned[(scanned["travel_ratio"] >= 0.3) & (scanned["travel_ratio"] < settings.criteria.min_travel_ratio)
                    & scanned["travel_override"].isna()]
if not ambiguous.empty:
    st.caption(f"여행 관련 비율이 30~{int(settings.criteria.min_travel_ratio * 100)}%로 애매한 채널이 {len(ambiguous)}개 있어요. "
               "그룹에서 '여행 무관'을 골라 확인하고 🤖 AI 여행 판별을 돌려 보세요.")
