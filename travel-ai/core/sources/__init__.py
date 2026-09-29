"""채널·영상 후보를 찾아오는 소스들. 모두 같은 형태의 Candidate 목록을 반환한다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candidate:
    video_id: str | None
    channel_id: str | None
    title: str | None = None
    source: str = ""
    keyword: str | None = None


class SourceError(Exception):
    """소스가 실패했을 때 (차단, 구조 변경 등). 호출 측은 다른 소스로 전환한다."""
