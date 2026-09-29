"""검색 키워드 생성(지역 × 수식어 + 주제형)과 키워드 큐 관리."""
from __future__ import annotations

import sqlite3

from . import db

REGIONS_PROVINCE = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
                    "충북", "충남", "전북", "전남", "경북", "경남", "제주"]

REGIONS_LOCAL = [
    "강릉", "속초", "양양", "동해", "삼척", "정선", "영월", "평창", "춘천", "홍천", "인제", "태백", "철원",
    "가평", "양평", "파주", "수원", "포천", "강화도", "영종도", "대부도",
    "단양", "제천", "충주", "청주", "괴산", "공주", "부여", "보령", "태안", "서산", "당진", "아산", "대천",
    "전주", "군산", "남원", "무주", "부안", "고창", "익산",
    "여수", "순천", "목포", "담양", "보성", "완도", "진도", "신안", "해남", "구례", "강진",
    "경주", "안동", "포항", "영덕", "울진", "문경", "영주", "청송", "울릉도",
    "통영", "거제", "남해", "하동", "진주", "사천", "창원", "김해", "밀양", "합천", "산청",
    "기장", "해운대", "광안리", "영도", "서귀포", "우도", "애월", "성산",
]

REGIONS_JAPAN = ["오사카", "교토", "도쿄", "후쿠오카", "삿포로", "오키나와", "나고야", "고베", "나라",
                 "벳부", "유후인", "대마도", "가고시마", "히로시마", "하코네", "요코하마"]

ALL_REGIONS = REGIONS_PROVINCE + REGIONS_LOCAL + REGIONS_JAPAN

# 수식어: 콘텐츠 유형(content_types.TYPES 키)별
MODIFIERS: dict[str, list[str]] = {
    "vlog": ["여행", "브이로그", "당일치기", "1박2일", "뚜벅이 여행", "혼자 여행", "기차 여행"],
    "info": ["가볼만한곳", "여행 코스", "여행 경비", "여행 총정리", "여행 꿀팁", "가는 법"],
    "stay": ["숙소 리뷰", "숙소 추천", "모텔 후기", "게스트하우스", "호텔 후기", "가성비 숙소", "이색 숙소"],
    "explore": ["가봤다", "탐방", "숨은 명소", "이색 체험"],
    "food": ["노포", "시장 투어", "현지인 맛집", "로컬 맛집"],
}

# 지역 없이 쓰는 주제형 키워드
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "vlog": ["국내 소도시 여행", "시골 여행 브이로그", "무궁화호 여행", "버스 여행", "도보 여행", "차박 여행",
             "섬 여행 브이로그", "1인 국내여행"],
    "info": ["국내 여행 경비", "국내 여행 코스 추천", "기차 여행 꿀팁", "국내 여행 꿀팁", "일본 여행 경비 총정리"],
    "stay": ["여인숙 탐방", "여인숙 후기", "최저가 숙소", "1박 1만원 숙소", "모텔 리뷰", "찜질방 숙박",
             "이색 숙소 후기", "캡슐호텔 후기", "료칸 후기"],
    "explore": ["무인도 여행", "폐교 탐방", "폐역 여행", "국내 숨은 명소", "한국에 이런 곳이", "국내 이색 여행",
                "오지 마을 여행"],
    "food": ["노포 투어", "전통시장 투어", "휴게소 투어", "휴게소 맛집", "시골 장터"],
}


def generate_keywords() -> list[tuple[str, str]]:
    """(키워드, 유형) 목록."""
    out: list[tuple[str, str]] = []
    for kind, mods in MODIFIERS.items():
        for region in ALL_REGIONS:
            for mod in mods:
                out.append((f"{region} {mod}", kind))
    for kind, words in TOPIC_KEYWORDS.items():
        out.extend((w, kind) for w in words)
    return out


def ensure_keywords(conn: sqlite3.Connection) -> int:
    """키워드 큐가 비어 있으면 채운다. 추가된 개수 반환."""
    before = conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO keywords (keyword, kind) VALUES (?, ?)",
        generate_keywords(),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] - before


def add_custom_keywords(conn: sqlite3.Connection, words: list[str], kind: str = "custom") -> int:
    words = [w.strip() for w in words if w.strip()]
    cur = conn.executemany("INSERT OR IGNORE INTO keywords (keyword, kind) VALUES (?, ?)", [(w, kind) for w in words])
    conn.commit()
    return cur.rowcount


def pick_keywords(conn: sqlite3.Connection, n: int, kinds: list[str] | None = None, cooldown_days: int = 7) -> list[str]:
    """다음에 검색할 키워드.

    1순위: 아직 한 번도 검색 안 한 키워드 (사용자 키워드 먼저, 나머지는 무작위로 골고루)
    2순위: 쿨다운이 지난 키워드 중 "검색당 새 채널 수"가 높은 순
    """
    params: list = []
    where = ["(last_searched_at IS NULL OR last_searched_at < datetime('now', ?))"]
    params.append(f"-{int(cooldown_days)} days")
    if kinds:
        where.append(f"kind IN ({','.join('?' for _ in kinds)})")
        params.extend(kinds)
    sql = (
        "SELECT keyword FROM keywords WHERE " + " AND ".join(where) +
        " ORDER BY last_searched_at IS NOT NULL, kind != 'custom',"
        " CAST(new_channels AS REAL) / MAX(searches, 1) DESC, RANDOM() LIMIT ?"
    )
    params.append(n)
    return [r["keyword"] for r in conn.execute(sql, params).fetchall()]


def record_search(conn: sqlite3.Connection, keyword: str, results: int, new_channels: int) -> None:
    conn.execute(
        "UPDATE keywords SET last_searched_at=?, searches=searches+1, results=results+?, new_channels=new_channels+? WHERE keyword=?",
        (db.now_iso().replace("T", " ").replace("+00:00", ""), results, new_channels, keyword),
    )
    conn.commit()
