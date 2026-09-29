"""비공식 검색 (scrapetube, YouTube 내부 API).

- API 키·할당량 없이 검색만 수행하고, 수치(구독자·조회수·길이)는 공식 API로 다시 조회한다.
- YouTube 약관상 자동화된 접근에 해당할 수 있고, 구조가 바뀌거나 차단되면 언제든 실패할 수 있다.
  실패하면 SourceError를 던지고, 호출 측은 공식 검색으로 전환한다.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from . import Candidate, SourceError

SORT_MAP = {"relevance": "relevance", "date": "upload_date", "views": "view_count"}


def _text(node: dict | None) -> str | None:
    if not node:
        return None
    if "simpleText" in node:
        return node["simpleText"]
    runs = node.get("runs") or []
    return "".join(r.get("text", "") for r in runs) or None


def parse_video_renderer(item: dict) -> tuple[str | None, str | None, str | None]:
    """videoRenderer → (video_id, channel_id, title)."""
    video_id = item.get("videoId")
    channel_id = None
    for key in ("ownerText", "longBylineText", "shortBylineText"):
        for run in (item.get(key) or {}).get("runs", []):
            browse = run.get("navigationEndpoint", {}).get("browseEndpoint", {})
            if browse.get("browseId", "").startswith("UC"):
                channel_id = browse["browseId"]
                break
        if channel_id:
            break
    return video_id, channel_id, _text(item.get("title"))


def search(keyword: str, order: str = "relevance", limit: int = 50, sleep: float = 1.5, search_fn=None) -> list[Candidate]:
    if search_fn is None:
        try:
            import scrapetube
        except ImportError as exc:  # pragma: no cover - 설치 문제
            raise SourceError("scrapetube가 설치되어 있지 않습니다 (pip install scrapetube).") from exc
        search_fn = scrapetube.get_search
    out: list[Candidate] = []
    try:
        for item in search_fn(quote_plus(keyword), limit=limit, sleep=sleep, sort_by=SORT_MAP.get(order, "relevance")):
            video_id, channel_id, title = parse_video_renderer(item)
            if video_id and channel_id:
                out.append(Candidate(video_id, channel_id, title, "unofficial_search", keyword))
    except Exception as exc:  # 네트워크 차단·구조 변경 등 어떤 실패든 소스 실패로 처리
        raise SourceError(f"비공식 검색 실패: {type(exc).__name__}: {exc}") from exc
    return out
