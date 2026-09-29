"""여행 유튜브 벤치마킹·분석 대시보드.

실행: streamlit run app.py   (데모: DEMO=1 streamlit run app.py)
"""
import streamlit as st

st.set_page_config(page_title="여행 유튜브 벤치마킹", page_icon="🧳", layout="wide")

pages = {
    "시작": [st.Page("app_pages/home.py", title="홈", icon="🏠", default=True)],
    "벤치마킹": [
        st.Page("app_pages/discover.py", title="채널 발굴", icon="🔎"),
        st.Page("app_pages/watchlist.py", title="관심 채널", icon="📌"),
        st.Page("app_pages/hits.py", title="떡상 영상", icon="🔥"),
        st.Page("app_pages/video.py", title="영상 상세", icon="🎬"),
        st.Page("app_pages/patterns.py", title="패턴 분석", icon="📊"),
    ],
    "관리": [st.Page("app_pages/settings.py", title="설정", icon="⚙️")],
}
st.navigation(pages).run()
