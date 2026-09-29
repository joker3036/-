"""데모 모드(DEMO=1)용 가상 데이터.

실제 채널을 흉내 내지 않도록 채널명은 모두 "샘플"로 시작하고, 수치는 난수로 만든다.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import content_types, db, discovery, keywords
from .config import Settings

TYPE_COLORS = {"vlog": "#2a78d6", "info": "#1baf7a", "stay": "#eb6834", "explore": "#4a3aa7", "food": "#e34948", None: "#898781"}
TYPE_WORD = {"vlog": "브이로그", "info": "정보", "stay": "숙소", "explore": "탐방", "food": "맛집", None: "기타"}

TITLES = {
    "vlog": ["{r} 당일치기 뚜벅이 브이로그", "{r} 1박2일 혼자 여행", "비 오는 날 {r} 기차 여행", "{r}에서 보낸 3일", "{r} 여행 가서 생긴 일"],
    "info": ["{r} 여행 경비 총정리 (1박 기준)", "{r} 가볼만한곳 코스 추천 BEST 7", "{r} 가는 법 · 교통 꿀팁 정리", "모르면 손해 보는 {r} 여행 꿀팁", "{r} 여행 전 필수 체크리스트"],
    "stay": ["{r} 1박 2만원 여인숙에서 자봤습니다", "{r} 최저가 모텔 솔직 후기", "{r} 게스트하우스 3곳 비교해봄", "1박 3만원 {r} 이색 숙소 리뷰", "{r} 30년 된 여관 하룻밤"],
    "explore": ["{r}에 이런 곳이 있다고? 숨은 명소 탐방", "{r} 폐교 캠핑장 가봤다", "아무도 모르는 {r} 무인도 체험", "{r} 오지 마을 탐방기", "{r} 이색 체험 끝판왕"],
    "food": ["{r} 40년 노포 국밥 투어", "{r} 전통시장 먹거리 투어", "{r} 현지인만 아는 로컬 맛집", "{r} 시장 1만원으로 배 채우기", "{r} 새벽 장터 탐방"],
}
REGIONS = ["강릉", "영월", "통영", "여수", "목포", "안동", "군산", "단양", "태백", "남해", "정선", "부여", "후쿠오카", "오사카"]

# (이름, 구독자, 조회수 중앙값, 업로드 간격(일), 마지막 업로드(일 전), 주 유형, 두 번째 유형, 영상 수, 특이사항)
CHANNELS = [
    ("샘플 롤모델 A", 850_000, 420_000, 7, 3, "vlog", "food", 50, "role_model"),
    ("샘플 롤모델 B", 410_000, 150_000, 10, 5, "stay", "vlog", 50, "role_model"),
    ("샘플 숙소탐방러", 7_800, 21_000, 7, 4, "stay", "vlog", 60, "turning"),
    ("샘플 이색여행", 5_200, 14_000, 10, 6, "explore", "vlog", 45, None),
    ("샘플 정보여행 노트", 9_100, 18_000, 12, 9, "info", "vlog", 40, None),
    ("샘플 시장투어", 3_400, 11_500, 9, 2, "food", "vlog", 38, None),
    ("샘플 뚜벅이", 6_600, 7_200, 8, 5, "vlog", "info", 42, None),  # 조회수만 미달 → 근접 후보
    ("샘플 기차여행", 8_300, 13_000, 15, 12, "vlog", "info", 35, None),  # 간격 미달 → 근접 후보
    ("샘플 소도시 탐구", 2_900, 12_500, 9, 40, "explore", "info", 30, None),  # 쉬는 중 → 근접 후보
    ("샘플 관문돌파", 11_300, 16_000, 7, 3, "stay", "explore", 50, "graduated"),
    ("샘플 주말여행", 4_100, 2_300, 11, 8, "vlog", "food", 36, None),
    ("샘플 섬여행", 1_700, 1_100, 25, 30, "explore", "vlog", 22, None),
    ("샘플 캠핑로그", 6_900, 3_900, 14, 10, "vlog", "stay", 28, None),
    ("샘플 먹방여행", 8_800, 5_500, 6, 2, "food", "info", 50, None),
]


def _svg_thumb(title: str, type_key: str | None) -> str:
    color = TYPE_COLORS.get(type_key, "#898781")
    word = TYPE_WORD.get(type_key, "기타")
    short = (title[:14] + "…") if len(title) > 14 else title
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180'>"
           f"<rect width='320' height='180' fill='{color}'/>"
           f"<text x='16' y='40' font-size='22' font-family='sans-serif' fill='white' font-weight='bold'>{word}</text>"
           f"<text x='16' y='150' font-size='16' font-family='sans-serif' fill='white'>{short}</text></svg>")
    return "data:image/svg+xml;utf8," + quote(svg)


def _cid(i: int) -> str:
    return f"UCdemo{i:02d}" + "x" * 16


def build_demo(conn: sqlite3.Connection, settings: Settings, seed: int = 7) -> None:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snaps = [now - timedelta(days=d) for d in (21, 14, 7, 0)]
    keywords.ensure_keywords(conn)

    for i, (name, subs, med, gap, last, t1, t2, n_videos, flag) in enumerate(CHANNELS):
        cid = _cid(i)
        # 채널 스냅샷 (구독자 추이)
        if flag == "graduated":
            subs_hist = [8_900, 9_600, 10_400, subs]
        else:
            growth = rng.uniform(0.005, 0.03)
            subs_hist = [int(subs / (1 + growth) ** (3 - k)) for k in range(4)]
        db.upsert_channel(conn, {
            "channel_id": cid, "handle": f"@sample{i:02d}", "title": name,
            "description": "데모용 가상 채널입니다. 실제 채널이 아닙니다.",
            "thumbnail_url": _svg_thumb(name, t1), "country": "KR",
            "published_at": (now - timedelta(days=rng.randint(500, 2000))).isoformat(),
            "subscribers": subs, "hidden_subscribers": 0, "total_views": med * n_videos * 3, "video_count": n_videos + 20,
            "uploads_playlist": None, "pinned": int(flag in ("role_model", "turning", "graduated")),
            "is_role_model": int(flag == "role_model"), "source": "demo", "last_scanned_at": now.isoformat(),
        })
        for at, s in zip(snaps, subs_hist):
            db.add_channel_snapshot(conn, cid, s, None, None, at.isoformat())

        # 영상
        for k in range(n_videos):
            age = last + k * gap + rng.uniform(-1.5, 1.5)
            published = now - timedelta(days=max(age, 0.5))
            if flag == "turning" and k >= 30:  # 오래된 영상: 브이로그 위주, 조회수 낮음 → 이후 숙소 탐방으로 전환
                vtype, base = "vlog", med * 0.12
            else:
                vtype = t1 if rng.random() < 0.7 else t2
                base = med
            views = int(base * rng.lognormvariate(0, 0.35))
            if rng.random() < 0.08 and not (flag == "turning" and k >= 29):
                views = int(views * rng.uniform(3.5, 8))  # 떡상
            if flag == "turning" and k == 29:
                vtype, views = "stay", int(med * 0.12 * 9)  # 터닝포인트 영상
            title = rng.choice(TITLES[vtype]).format(r=rng.choice(REGIONS))
            is_short = int(rng.random() < 0.15)
            vid = f"d{i:02d}{k:03d}" + "v" * 6
            row = {
                "video_id": vid, "channel_id": cid, "title": title, "description": "데모용 가상 영상입니다.",
                "published_at": published.isoformat(), "duration_s": rng.randint(20, 58) if is_short else rng.randint(420, 1500),
                "is_short": is_short, "category_id": "19", "tags_json": "[]", "thumbnail_url": _svg_thumb(title, vtype),
                "content_type": vtype, "views": views if not is_short else views * 3,
                "likes": int(views * 0.03), "comments": int(views * 0.004), "found_via": "demo",
            }
            db.upsert_video(conn, row)
            # 조회수 스냅샷 2회 (롱테일 지수용): 정보성 영상은 계속 늘고, 브이로그는 거의 멈춤
            if age > 45:
                tail = {"info": 0.9, "stay": 0.5, "food": 0.4, "explore": 0.35, "vlog": 0.15}.get(vtype, 0.3)
                lifetime_rate = views / age
                earlier = int(views - lifetime_rate * tail * 14)
                db.add_video_snapshot(conn, vid, earlier, None, None, (now - timedelta(days=14)).isoformat())
            db.add_video_snapshot(conn, vid, row["views"], row["likes"], row["comments"], now.isoformat())
        conn.commit()
        discovery.update_channel_metrics(conn, cid, settings)

    # 걸러진 대형 채널 몇 개 (산점도 비교용)
    for j in range(3):
        cid = _cid(50 + j)
        db.upsert_channel(conn, {"channel_id": cid, "title": f"샘플 대형채널 {j + 1}", "subscribers": [120_000, 260_000, 1_300_000][j],
                                 "grp": "big", "scan_status": "filtered", "filter_reason": "too_big", "source": "demo",
                                 "last_scanned_at": now.isoformat()})
        for k in range(8):
            title = rng.choice(TITLES["vlog"]).format(r=rng.choice(REGIONS))
            views = int([60_000, 90_000, 300_000][j] * rng.lognormvariate(0, 0.5))
            db.upsert_video(conn, {"video_id": f"b{j}{k:03d}" + "v" * 7, "channel_id": cid, "title": title,
                                   "published_at": (now - timedelta(days=10 + k * 9)).isoformat(), "duration_s": 900,
                                   "is_short": 0, "category_id": "19", "content_type": "vlog", "views": views,
                                   "thumbnail_url": _svg_thumb(title, "vlog"), "found_via": "search:데모"})

    _demo_analyses(conn)
    for kw in keywords.pick_keywords(conn, 25):
        keywords.record_search(conn, kw, rng.randint(20, 50), rng.randint(0, 6))
    db.record_usage(conn, "units", 1_240)
    db.record_usage(conn, "search", 3)
    db.set_meta(conn, "demo_built", now.isoformat())
    conn.commit()


def _demo_analyses(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT v.video_id, v.title, v.content_type FROM videos v JOIN channels c ON c.channel_id=v.channel_id "
        "WHERE c.grp IN ('hidden_gem','near') AND v.is_short=0 ORDER BY v.views * 1.0 / c.subscribers DESC LIMIT 6"
    ).fetchall()
    devices = [["리뷰·검증", "제약·미션"], ["발굴", "극한·체험"], ["리뷰·검증", "비교·순위"], ["음식", "사람·교류"],
               ["발굴", "시리즈"], ["제약·미션", "리뷰·검증"]]
    for n, r in enumerate(rows):
        db.save_analysis(conn, r["video_id"], "video", "done", {
            "content_type": content_types.label(r["content_type"], with_icon=False),
            "situation": f"(데모) '{r['title']}' 영상의 상황 설정 예시",
            "planning_devices": devices[n % len(devices)],
            "signature_elements": ["(데모) 매 숙소마다 하는 고정 검증 코너"] if n % 2 == 0 else [],
            "info_density": {"level": ["상", "중", "하"][n % 3], "examples": ["(데모) 숙박비", "(데모) 위치·교통"]},
            "title_devices": ["금액·숫자", "반전·호기심"] if n % 2 == 0 else ["의문형", "지명 강조"],
            "title_comment": "(데모) 구체적인 금액이 호기심을 만든다",
            "thumbnail": {"available": False, "has_face": n % 2 == 0, "reaction": "", "text": "", "text_length": 0,
                          "composition": "", "comment": "데모 데이터라 썸네일 분석 없음"},
            "hook": {"type": "결과 선공개", "summary": "(데모) 첫 장면에서 방 상태를 먼저 보여줌", "quote": ""},
            "chapters": [],
            "audience": {"questions": ["(데모) 위치가 어디인가요?"], "requests": ["(데모) 다른 지역도 가 주세요"],
                         "praise": ["(데모) 솔직해서 좋아요"], "complaints": []},
            "success_hypotheses": ["(데모) 가격이라는 명확한 기준", "(데모) 반복되는 검증 코너", "(데모) 검색 수요가 있는 지명"],
            "apply_to_my_channel": ["(데모) 매 영상 같은 기준으로 평가하는 고정 코너 만들기"],
            "confidence": "낮음",
            "data_notes": "데모 모드의 가상 분석 결과입니다.",
        }, model="demo")
    gem = conn.execute("SELECT channel_id FROM channels WHERE grp='hidden_gem' LIMIT 1").fetchone()
    if gem:
        db.save_analysis(conn, gem["channel_id"], "hidden_gem", "done", {
            "summary": "(데모) 좁은 주제를 같은 형식으로 꾸준히 반복하는 채널",
            "why_views": ["(데모) 제목에 지명+가격이 들어가 검색 수요를 받음", "(데모) 시리즈라 연속 시청이 일어남"],
            "traffic_guess": "혼합", "traffic_reason": "(데모) 지명형 제목과 호기심형 제목이 섞여 있음",
            "positioning": "(데모) 최저가 숙소 전문", "signature_elements": ["(데모) 고정 검증 코너"],
            "topic_patterns": ["(데모) 1박 N만원"], "title_thumbnail_patterns": ["(데모) 금액을 크게"],
            "consistency": "(데모) 주 1회, 같은 요일", "lessons_for_10k": ["(데모) 한 가지 기준으로 시리즈 만들기"],
            "confidence": "낮음",
        }, model="demo")
