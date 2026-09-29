"""테스트용 가짜 YouTube 클라이언트 (공식 API 응답 형태를 흉내 냄)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.youtube import QuotaExceeded


def channel_item(cid: str, title: str, subs: int | None, videos: int = 40, hidden: bool = False) -> dict:
    stats = {"viewCount": "1000000", "videoCount": str(videos)}
    if hidden:
        stats["hiddenSubscriberCount"] = True
    else:
        stats["subscriberCount"] = str(subs)
    return {"id": cid, "snippet": {"title": title, "customUrl": f"@{title}", "publishedAt": "2020-01-01T00:00:00Z"},
            "statistics": stats, "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid[2:]}}}


def video_item(vid: str, cid: str, title: str, days_ago: float, views: int, seconds: int = 900) -> dict:
    return {"id": vid, "snippet": {"channelId": cid, "title": title, "categoryId": "22",
                                   "publishedAt": (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": f"PT{seconds // 60}M{seconds % 60}S"}}


class FakeClient:
    def __init__(self, channels: dict[str, dict], uploads: dict[str, list[dict]], search_results: list[dict] | None = None,
                 quota_after_searches: int | None = None):
        self.channels = channels
        self.uploads = uploads
        self.videos = {v["id"]: v for vs in uploads.values() for v in vs}
        self.search_results = search_results or []
        self.calls: list[str] = []
        self.searches = 0
        self.quota_after_searches = quota_after_searches

    def channels_by_ids(self, ids):
        self.calls.append("channels")
        return [self.channels[i] for i in ids if i in self.channels]

    def playlist_video_ids(self, playlist_id, max_items=50):
        self.calls.append("playlistItems")
        cid = "UC" + playlist_id[2:]
        return [v["id"] for v in self.uploads.get(cid, [])][:max_items]

    def videos_by_ids(self, ids):
        self.calls.append("videos")
        return [self.videos[i] for i in ids if i in self.videos]

    def search_videos(self, query, order="relevance", published_after=None, duration="medium", max_results=50):
        self.searches += 1
        if self.quota_after_searches is not None and self.searches > self.quota_after_searches:
            raise QuotaExceeded("검색 예산 초과")
        self.calls.append("search")
        return list(self.search_results)

    def featured_channel_ids(self, channel_id):
        return []

    def comment_threads(self, video_id, max_results=100):
        return [{"text": "위치가 어디인가요?", "likes": 5, "replies": 0}]

    def resolve_refs(self, refs):
        ids = [r.value for r in refs if r.kind == "id"]
        errors = [f"찾을 수 없음: {r.raw}" for r in refs if r.kind != "id"]
        return ids, errors
