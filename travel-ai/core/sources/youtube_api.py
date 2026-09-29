"""공식 YouTube Data API 검색 (하루 100회 제한)."""
from __future__ import annotations

from datetime import datetime

from ..youtube import YouTubeClient
from . import Candidate

ORDER_MAP = {"relevance": "relevance", "date": "date", "views": "viewCount"}


def search(client: YouTubeClient, keyword: str, order: str = "relevance", published_after: datetime | None = None,
           duration: str | None = "medium", limit: int = 50) -> list[Candidate]:
    items = client.search_videos(keyword, order=ORDER_MAP.get(order, "relevance"), published_after=published_after,
                                 duration=duration, max_results=limit)
    return [Candidate(i["video_id"], i["channel_id"], i.get("title"), "api_search", keyword) for i in items]
