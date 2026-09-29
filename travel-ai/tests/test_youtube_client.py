import pytest

from core import db
from core.youtube import MissingApiKey, QuotaExceeded, YouTubeClient, YouTubeError


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append((url, params))
        return self.responses.pop(0)


def test_missing_key():
    with pytest.raises(MissingApiKey):
        YouTubeClient("")


def test_search_and_units_are_counted_separately(conn):
    session = FakeSession([
        FakeResponse(200, {"items": [{"id": {"videoId": "abcdefghijk"}, "snippet": {"channelId": "UCx", "title": "t"}}]}),
        FakeResponse(200, {"items": []}),
    ])
    client = YouTubeClient("k", conn, session)
    results = client.search_videos("강릉 여행", order="date")
    assert results == [{"video_id": "abcdefghijk", "channel_id": "UCx", "title": "t"}]
    client.videos_by_ids(["abcdefghijk"])
    assert db.get_usage(conn, "search") == 1 and db.get_usage(conn, "units") == 1
    params = session.requests[0][1]
    assert params["regionCode"] == "KR" and params["type"] == "video" and params["videoDuration"] == "medium"


def test_budget_blocks_before_calling(conn):
    session = FakeSession([])
    client = YouTubeClient("k", conn, session, unit_budget=5, search_budget=1)
    db.record_usage(conn, "search", 1)
    with pytest.raises(QuotaExceeded):
        client.search_videos("x")
    db.record_usage(conn, "units", 5)
    with pytest.raises(QuotaExceeded):
        client.channels_by_ids(["UCx"])
    assert session.requests == []


def test_http_errors_are_mapped(conn):
    quota = FakeResponse(403, {"error": {"message": "exceeded", "errors": [{"reason": "quotaExceeded"}]}})
    other = FakeResponse(400, {"error": {"message": "bad", "errors": [{"reason": "badRequest"}]}})
    client = YouTubeClient("k", conn, FakeSession([quota, other]))
    with pytest.raises(QuotaExceeded):
        client.channels_by_ids(["UCx"])
    with pytest.raises(YouTubeError, match="badRequest"):
        client.channels_by_ids(["UCx"])


def test_channels_are_batched_by_50(conn):
    session = FakeSession([FakeResponse(200, {"items": []}), FakeResponse(200, {"items": []})])
    YouTubeClient("k", conn, session).channels_by_ids([f"UC{i:022d}" for i in range(60)])
    assert len(session.requests) == 2 and db.get_usage(conn, "units") == 2
