"""Apify YouTube 스크래퍼 연결 자리 (아직 미구현).

검색 결과에 채널 구독자까지 붙여 주는 유료 액터(결과 1,000건당 약 $0.25~0.5)를 쓰고 싶어지면
여기에 search(keyword, ...) -> list[Candidate] 를 구현하고 discovery.KEYWORD_SOURCES 에 등록하면 된다.
"""
from __future__ import annotations

from . import Candidate, SourceError


def search(keyword: str, **_kwargs) -> list[Candidate]:
    raise SourceError("Apify 소스는 아직 연결되지 않았습니다.")
