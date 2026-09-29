import streamlit as st

from core import collector, config, llm
from core.youtube import YouTubeClient, YouTubeError
from ui.common import criteria_form, demo_banner, get_conn, get_settings, quota_sidebar, save_settings

settings = get_settings()
conn = get_conn()
quota_sidebar(conn, settings)

st.title("⚙️ 설정")
demo_banner()

st.subheader("YouTube API")
key = st.text_input("YouTube Data API 키", value=settings.youtube_api_key, type="password",
                    help="Google Cloud Console에서 무료로 발급 (README 참고). .env의 YOUTUBE_API_KEY가 있으면 그걸 먼저 써요.")
c1, c2 = st.columns(2)
search_budget = c1.number_input("하루 공식 검색 예산 (최대 100회)", 1, 100, settings.daily_search_budget)
unit_budget = c2.number_input("하루 API 유닛 예산 (최대 10,000)", 100, 10_000, settings.daily_unit_budget, step=500)
if st.button("키 확인 (1유닛)"):
    try:
        YouTubeClient(key or settings.api_key, conn).channels_by_ids(["UC_x5XG1OV2P6uZZ5FSM9Ttw"])
        st.success("키가 정상이에요.")
    except YouTubeError as exc:
        st.error(str(exc))

st.subheader("채널 발굴")
unofficial = st.toggle("비공식 검색 사용 (scrapetube)", value=settings.use_unofficial_search)
st.caption("⚠️ 공식 검색은 하루 100회로 제한돼요. 비공식 검색은 한도 없이 무료지만 YouTube 약관상 자동화된 접근에 해당할 수 있고, "
           "YouTube 구조가 바뀌거나 차단되면 언제든 멈출 수 있어요. 멈추면 자동으로 공식 검색으로 바꿔요. "
           "구독자·조회수 같은 숫자는 항상 공식 API로 가져와요.")
c1, c2, c3 = st.columns(3)
sleep = c1.number_input("비공식 검색 요청 간격 (초)", 0.5, 10.0, settings.unofficial_sleep_sec, step=0.5)
max_kw = c2.number_input("1회 탐색 최대 키워드 수", 1, 200, settings.max_keywords_per_run)
rescan = c3.number_input("재스캔 간격 (일)", 1, 60, settings.rescan_days)

st.subheader("지표 기준")
c1, c2, c3 = st.columns(3)
breakout = c1.number_input("돌파 영상 기준: 조회수÷구독자 (배)", 0.5, 100.0, settings.breakout_threshold, step=0.5)
outlier = c2.number_input("떡상 기준: 채널 평소 대비 (배)", 1.0, 50.0, settings.outlier_threshold, step=0.5)
tp_factor = c3.number_input("터닝포인트 기준 (배)", 1.5, 20.0, settings.turning_point_factor, step=0.5)
c1, c2, c3 = st.columns(3)
min_age = c1.number_input("비교에서 뺄 최근 영상 (일 미만)", 0, 60, settings.min_video_age_days)
shorts = c2.number_input("숏폼으로 볼 길이 (초 이하)", 60, 600, settings.shorts_max_seconds, step=10)
window = c3.number_input("채널 중앙값에 쓸 최근 롱폼 수", 5, 100, settings.median_window)

st.subheader("AI 분석 (Claude 구독)")
path = llm.claude_path()
st.caption(f"claude 명령: {path or '찾을 수 없음 — Claude Code를 설치하고 터미널에서 `claude`로 로그인하세요'}")
models = ["sonnet", "opus", "haiku", "fable"]
c1, c2, c3 = st.columns(3)
model_video = c1.selectbox("영상 분석 모델", models, index=models.index(settings.model_video) if settings.model_video in models else 0)
model_channel = c2.selectbox("채널 분석 모델", models, index=models.index(settings.model_channel) if settings.model_channel in models else 1)
batch = c3.number_input("대기열 1회 처리 개수", 1, 100, settings.analysis_batch_size)
if st.button("Claude 연결 테스트"):
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    try:
        with st.spinner("테스트 중..."):
            res = llm.run_structured("ok=true로 답하세요.", schema, "haiku", config.LLM_WORK_DIR, timeout=120)
        st.success(f"연결됐어요: {res.data}")
    except llm.LLMError as exc:
        st.error(str(exc))

st.subheader("데이터")
auto_prune = st.toggle("30일 넘게 갱신 안 된 채널 데이터 자동 정리 (📌 관심·⭐ 롤모델 제외)", value=settings.auto_prune)
st.caption(f"데이터 위치: {config.db_path()}")
if st.button("지금 정리"):
    st.success(f"{collector.prune_stale(conn, settings.stale_days)}개 채널의 데이터를 정리했어요.")

if st.button("설정 저장", type="primary"):
    settings.youtube_api_key = key
    settings.daily_search_budget, settings.daily_unit_budget = int(search_budget), int(unit_budget)
    settings.use_unofficial_search, settings.unofficial_sleep_sec = unofficial, float(sleep)
    settings.max_keywords_per_run, settings.rescan_days = int(max_kw), int(rescan)
    settings.breakout_threshold, settings.outlier_threshold = float(breakout), float(outlier)
    settings.turning_point_factor, settings.min_video_age_days = float(tp_factor), int(min_age)
    settings.shorts_max_seconds, settings.median_window = int(shorts), int(window)
    settings.model_video, settings.model_channel, settings.analysis_batch_size = model_video, model_channel, int(batch)
    settings.auto_prune = auto_prune
    save_settings(settings)
    st.success("저장했어요.")

st.subheader("🎯 숨은 고수 기준")
criteria_form(conn, settings, "settings")
