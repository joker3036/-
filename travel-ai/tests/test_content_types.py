import pytest

from core.content_types import classify_title, summarize


@pytest.mark.parametrize("title, expected", [
    ("1박 2만원 여인숙에서 자봤습니다", "stay"),
    ("여인숙 냄새 체크 - 30년 된 여관 리뷰", "stay"),
    ("통영 게스트하우스 솔직 후기", "stay"),
    ("오사카 여행 경비 총정리", "info"),
    ("모르면 손해 보는 강릉 여행 꿀팁", "info"),
    ("강릉 당일치기 뚜벅이 브이로그", "vlog"),
    ("영월 노포 국밥 투어", "food"),
    ("전통시장 1만원으로 배 채우기", "food"),
    ("폐교에서 하룻밤 캠핑 가봤다", "explore"),
    ("무인도 체험 3일", "explore"),
    ("군산 맛집 BEST 5", "food"),  # 지역 맥락이 있어서 '맛집'이 맛집 유형으로 인정됨
])
def test_travel_titles(title, expected):
    assert classify_title(title) == expected


@pytest.mark.parametrize("title", [
    "아이폰 16 언박싱 리뷰",
    "우리나라 최고의 라면 먹방",  # '나라'는 지명으로 보지 않음, 여행 맥락 없는 먹방
    "구독자 추천 게임 TOP 10",  # 정보 단어만 있고 여행 맥락 없음
])
def test_non_travel_titles(title):
    assert classify_title(title) is None


def test_travel_category_gives_context():
    assert classify_title("오늘의 일상", category_id="19") == "vlog"


def test_summarize():
    ratio, primary, counts = summarize(["stay", "stay", "vlog", None])
    assert ratio == 0.75 and primary == "stay" and counts == {"stay": 2, "vlog": 1}
    assert summarize([]) == (0.0, None, {})
