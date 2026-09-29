"""제목 사전 기반 콘텐츠 유형 분류 (여행 관련 5개 유형)."""
from __future__ import annotations

import re
from collections import Counter

from .keywords import ALL_REGIONS

TYPES: dict[str, tuple[str, str]] = {
    "vlog": ("🎒", "여행 브이로그·예능"),
    "info": ("📘", "정보성 여행"),
    "stay": ("🏨", "숙소·시설 리뷰/탐방"),
    "explore": ("🗺️", "이색 장소 탐방·체험"),
    "food": ("🍜", "로컬 맛집·시장 탐방"),
}

# 점수가 같으면 더 구체적인 유형을 우선
PRIORITY = ["stay", "explore", "food", "info", "vlog"]

WORDS: dict[str, list[str]] = {
    "vlog": ["여행", "브이로그", "vlog", "당일치기", "뚜벅이", "혼자", "기차", "투어", "일주", "한달살기", "여행기",
             "하룻밤", "trip", "travel", "캠핑", "차박", "무전", "배낭"],
    "info": ["총정리", "꿀팁", "가이드", "코스", "경비", "비용", "가격", "추천", "필수", "주의", "모르면", "방법",
             "가는법", "가는 법", "정보", "top", "베스트", "순위", "비교", "가성비", "예약", "루트", "일정", "준비물",
             "환전", "교통", "패스", "정리"],
    "stay": ["숙소", "호텔", "모텔", "여인숙", "여관", "게스트하우스", "게하", "펜션", "리조트", "료칸", "캡슐",
             "찜질방", "민박", "한옥스테이", "에어비앤비", "객실", "룸투어", "휴게소", "글램핑", "캠핑장"],
    "explore": ["이색", "가봤다", "가봄", "가보았", "탐방", "체험", "폐교", "폐역", "폐허", "무인도", "오지", "숨은",
                "비밀", "아무도", "최초", "기묘", "신기한", "이런 곳", "이런곳", "잠입", "실화", "섬마을"],
    # 시장·노포처럼 그 자체로 지역성이 있는 단어만 강한 신호로 봄
    "food": ["노포", "시장", "로컬", "현지인", "길거리 음식", "포장마차", "장터"],
}

# 이 단어들은 여행 맥락(지역명·여행 단어)이 있을 때만 맛집 유형으로 인정 (순수 먹방 제외)
WEAK_FOOD = ["맛집", "먹방", "식당", "국밥", "백반", "먹거리", "먹부림", "야시장"]

_NIGHTS_RE = re.compile(r"\d\s*박\s*\d?\s*일?")
_CHEAP_STAY_RE = re.compile(r"\d\s*박\s*[0-9,.]+\s*(만\s*)?원")

TRAVEL_CATEGORY_ID = "19"

# 일반 단어 안에 자주 섞여 나오는 지명은 여행 맥락 판단에서 뺌 (예: 우리"나라", "세종"대왕, 생선 "대구")
_AMBIGUOUS_REGIONS = {"나라", "세종", "대구", "인제", "영도", "우도", "성산", "진도", "사천", "광주", "보성", "대천"}
CONTEXT_REGIONS = [r for r in ALL_REGIONS if r not in _AMBIGUOUS_REGIONS]


def _hits(text: str, words: list[str]) -> int:
    return sum(1 for w in words if w in text)


def classify_title(title: str | None, category_id: str | None = None, tags: list[str] | None = None) -> str | None:
    """영상 제목 → 유형 키(vlog/info/stay/explore/food) 또는 여행과 무관하면 None."""
    text = (title or "").lower()
    context = text + " " + " ".join((tags or [])[:15]).lower()
    has_region = any(r in context for r in CONTEXT_REGIONS)
    has_nights = bool(_NIGHTS_RE.search(text))
    travel_ctx = has_region or has_nights or category_id == TRAVEL_CATEGORY_ID or _hits(context, WORDS["vlog"]) > 0

    scores = Counter({t: _hits(text, words) for t, words in WORDS.items()})
    if _CHEAP_STAY_RE.search(text):
        scores["stay"] += 2
    if travel_ctx:
        scores["food"] += _hits(text, WEAK_FOOD)
    if has_nights:
        scores["vlog"] += 1

    best = max(scores.values())
    if best > 0:
        # info 단어("추천", "정리" 등)만 있고 여행 맥락이 없으면 여행 영상으로 보지 않음
        top = [t for t in PRIORITY if scores[t] == best]
        choice = top[0]
        if choice == "info" and not travel_ctx:
            return None
        return choice
    return "vlog" if travel_ctx else None


def label(type_key: str | None, with_icon: bool = True) -> str:
    if not type_key or type_key not in TYPES:
        return "여행 무관"
    icon, name = TYPES[type_key]
    return f"{icon} {name}" if with_icon else name


def summarize(type_keys: list[str | None]) -> tuple[float, str | None, dict[str, int]]:
    """영상 유형 목록 → (여행 관련 비율, 주 유형, 유형별 개수)."""
    if not type_keys:
        return 0.0, None, {}
    counts = Counter(t for t in type_keys if t)
    ratio = sum(counts.values()) / len(type_keys)
    primary = None
    if counts:
        best = max(counts.values())
        primary = next(t for t in PRIORITY if counts.get(t) == best)
    return ratio, primary, dict(counts)
