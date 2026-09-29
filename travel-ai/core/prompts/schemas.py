"""AI 분석 결과 JSON 스키마 (claude -p --json-schema).

구조화 출력이 확실히 지원하는 키워드만 사용한다: type, properties, required, items, enum, description,
additionalProperties. (minItems·maxItems 등은 쓰지 않음)
"""
from __future__ import annotations

CONTENT_TYPE_ENUM = ["여행 브이로그·예능", "정보성 여행", "숙소·시설 리뷰/탐방", "이색 장소 탐방·체험", "로컬 맛집·시장 탐방", "여행 무관"]
PLANNING_DEVICES = ["제약·미션", "극한·체험", "사람·교류", "발굴", "음식", "비교·순위", "시리즈", "리뷰·검증"]
TITLE_DEVICES = ["의문형", "대사 인용", "금액·숫자", "극단 표현", "반전·호기심", "지명 강조"]
HOOK_TYPES = ["상황 설정", "결과 선공개", "갈등 예고", "질문", "기타"]
CONFIDENCE = ["높음", "보통", "낮음"]


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


STR = {"type": "string"}
STR_LIST = {"type": "array", "items": {"type": "string"}}

VIDEO_SCHEMA = _obj({
    "content_type": {"type": "string", "enum": CONTENT_TYPE_ENUM},
    "situation": {"type": "string", "description": "이 영상의 상황 설정을 한 줄로"},
    "planning_devices": {"type": "array", "items": {"type": "string", "enum": PLANNING_DEVICES}},
    "signature_elements": {"type": "array", "items": STR, "description": "매 영상 반복되는 코너·말버릇·검증 의식 (없으면 빈 배열)"},
    "info_density": _obj({
        "level": {"type": "string", "enum": ["상", "중", "하"]},
        "examples": {"type": "array", "items": STR, "description": "영상에 나온 실용 정보 예시 (가격·위치·시간·팁)"},
    }),
    "title_devices": {"type": "array", "items": {"type": "string", "enum": TITLE_DEVICES}},
    "title_comment": {"type": "string", "description": "제목이 클릭을 부르는 이유"},
    "thumbnail": _obj({
        "available": {"type": "boolean"},
        "has_face": {"type": "boolean"},
        "reaction": STR,
        "text": {"type": "string", "description": "썸네일 문구 그대로"},
        "text_length": {"type": "integer"},
        "composition": STR,
        "comment": STR,
    }),
    "hook": _obj({
        "type": {"type": "string", "enum": HOOK_TYPES},
        "summary": {"type": "string", "description": "첫 60초 요약"},
        "quote": {"type": "string", "description": "훅이 되는 대사 인용 (자막 없으면 빈 문자열)"},
    }),
    "chapters": {"type": "array", "items": _obj({"time": STR, "title": STR})},
    "audience": _obj({"questions": STR_LIST, "requests": STR_LIST, "praise": STR_LIST, "complaints": STR_LIST}),
    "success_hypotheses": {"type": "array", "items": STR, "description": "이 영상이 잘 된 이유 가설 3개"},
    "apply_to_my_channel": {"type": "array", "items": STR, "description": "구독 1만 목표인 내 채널에 적용할 점"},
    "confidence": {"type": "string", "enum": CONFIDENCE},
    "data_notes": {"type": "string", "description": "부족했던 데이터 (자막 없음 등)"},
})

CONTRAST_SCHEMA = _obj({
    "summary": STR,
    "differences": {"type": "array", "items": _obj({"aspect": STR, "hit_videos": STR, "normal_videos": STR})},
    "patterns": STR_LIST,
    "what_to_copy": STR_LIST,
    "what_to_avoid": STR_LIST,
    "confidence": {"type": "string", "enum": CONFIDENCE},
})

HIDDEN_GEM_SCHEMA = _obj({
    "summary": STR,
    "why_views": {"type": "array", "items": STR, "description": "구독자에 비해 조회수가 잘 나오는 이유"},
    "traffic_guess": {"type": "string", "enum": ["검색 유입형", "추천 유입형", "혼합", "판단 어려움"]},
    "traffic_reason": STR,
    "positioning": {"type": "string", "description": "채널의 포지셔닝·차별점"},
    "signature_elements": STR_LIST,
    "topic_patterns": STR_LIST,
    "title_thumbnail_patterns": STR_LIST,
    "consistency": {"type": "string", "description": "업로드 리듬·시리즈 운영 방식"},
    "lessons_for_10k": {"type": "array", "items": STR, "description": "구독 1만 달성을 위해 따라 할 점"},
    "confidence": {"type": "string", "enum": CONFIDENCE},
})

GROWTH_SCHEMA = _obj({
    "summary": STR,
    "turning_point_video": {"type": "string", "description": "터닝포인트 영상 제목 (없으면 빈 문자열)"},
    "what_changed": {"type": "array", "items": _obj({"aspect": STR, "before": STR, "after": STR})},
    "why_it_worked": STR_LIST,
    "graduation_notes": {"type": "string", "description": "구독 1만을 넘기 직전에 달라진 점 (해당 없으면 빈 문자열)"},
    "lessons_for_10k": STR_LIST,
    "confidence": {"type": "string", "enum": CONFIDENCE},
})

TRAVEL_CHECK_SCHEMA = _obj({
    "is_travel": {"type": "boolean"},
    "primary_type": {"type": "string", "enum": CONTENT_TYPE_ENUM},
    "reason": STR,
})

SCHEMAS = {
    "video": VIDEO_SCHEMA,
    "contrast": CONTRAST_SCHEMA,
    "hidden_gem": HIDDEN_GEM_SCHEMA,
    "growth": GROWTH_SCHEMA,
    "travel_check": TRAVEL_CHECK_SCHEMA,
}
