"""YouTube Data API v3 클라이언트와 URL·응답 파싱 도우미.

할당량
- search.list: 하루 100회 별도 제한 ("search" 버킷), 호출당 100 유닛으로도 계산됨
- 그 외 호출: 호출당 1 유닛 ("units" 버킷, 하루 10,000)
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import requests

from . import db

API_BASE = "https://www.googleapis.com/youtube/v3/"
COSTS = {"search": 100, "channels": 1, "videos": 1, "playlistItems": 1, "commentThreads": 1, "channelSections": 1}


class YouTubeError(Exception):
    pass


class QuotaExceeded(YouTubeError):
    """할당량(검색 100회 또는 1만 유닛)을 다 썼을 때."""


class MissingApiKey(YouTubeError):
    pass


@dataclass
class ChannelRef:
    """사용자 입력(URL·핸들·ID)을 해석한 결과."""

    kind: str  # "id" | "handle" | "username" | "video" | "custom"
    value: str
    raw: str


_CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
_VIDEO_ID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")


def parse_channel_input(text: str) -> ChannelRef | None:
    """채널 URL, @핸들, 채널 ID, 영상 URL을 해석한다. 해석할 수 없으면 None."""
    raw = text.strip().strip("\"'<>")
    if not raw:
        return None
    if _CHANNEL_ID_RE.match(raw):
        return ChannelRef("id", raw, text)
    if raw.startswith("@") and len(raw) > 1:
        return ChannelRef("handle", unquote(raw), text)

    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    parts = [unquote(p) for p in parsed.path.split("/") if p]

    if host == "youtu.be" and parts and _VIDEO_ID_RE.match(parts[0]):
        return ChannelRef("video", parts[0], text)
    if host not in ("youtube.com", "music.youtube.com"):
        return None
    if not parts:
        video = parse_qs(parsed.query).get("v", [None])[0]
        return ChannelRef("video", video, text) if video and _VIDEO_ID_RE.match(video) else None
    head = parts[0]
    if head.startswith("@"):
        return ChannelRef("handle", head, text)
    if head == "channel" and len(parts) > 1 and _CHANNEL_ID_RE.match(parts[1]):
        return ChannelRef("id", parts[1], text)
    if head == "user" and len(parts) > 1:
        return ChannelRef("username", parts[1], text)
    if head == "watch":
        video = parse_qs(parsed.query).get("v", [None])[0]
        return ChannelRef("video", video, text) if video and _VIDEO_ID_RE.match(video) else None
    if head in ("shorts", "live", "embed") and len(parts) > 1 and _VIDEO_ID_RE.match(parts[1]):
        return ChannelRef("video", parts[1], text)
    if head == "c" and len(parts) > 1:
        return ChannelRef("custom", parts[1], text)
    return None


_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_duration(value: str | None) -> int:
    """ISO 8601 길이(PT1H2M3S)를 초로 변환. 해석 불가면 0."""
    if not value:
        return 0
    m = _DURATION_RE.match(value)
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def channel_row(item: dict) -> dict:
    """channels.list 응답 항목 → channels 테이블 행."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    hidden = bool(stats.get("hiddenSubscriberCount"))
    return {
        "channel_id": item["id"],
        "handle": snippet.get("customUrl"),
        "title": snippet.get("title"),
        "description": (snippet.get("description") or "")[:1000],
        "thumbnail_url": thumb,
        "country": snippet.get("country"),
        "published_at": snippet.get("publishedAt"),
        "subscribers": None if hidden else _int(stats.get("subscriberCount")),
        "hidden_subscribers": int(hidden),
        "total_views": _int(stats.get("viewCount")),
        "video_count": _int(stats.get("videoCount")),
        "uploads_playlist": details.get("relatedPlaylists", {}).get("uploads"),
    }


def video_row(item: dict, shorts_max_seconds: int = 180) -> dict:
    """videos.list 응답 항목 → videos 테이블 행 (content_type은 호출 측에서 채움)."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    details = item.get("contentDetails", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    duration = parse_duration(details.get("duration"))
    return {
        "video_id": item["id"],
        "channel_id": snippet.get("channelId"),
        "title": snippet.get("title"),
        "description": (snippet.get("description") or "")[:2000],
        "published_at": snippet.get("publishedAt"),
        "duration_s": duration,
        "is_short": int(0 < duration <= shorts_max_seconds),
        "category_id": snippet.get("categoryId"),
        "tags_json": json.dumps(snippet.get("tags", [])[:30], ensure_ascii=False),
        "thumbnail_url": thumb,
        "views": _int(stats.get("viewCount")),
        "likes": _int(stats.get("likeCount")),
        "comments": _int(stats.get("commentCount")),
    }


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class YouTubeClient:
    """공식 API 호출. 호출할 때마다 api_usage에 사용량을 기록하고 예산을 넘으면 QuotaExceeded."""

    def __init__(self, api_key: str, conn: sqlite3.Connection | None = None, session: requests.Session | None = None,
                 unit_budget: int = 9_000, search_budget: int = 95, timeout: int = 20):
        if not api_key:
            raise MissingApiKey("YouTube API 키가 없습니다. 설정 페이지에서 입력하세요.")
        self.api_key = api_key
        self.conn = conn
        self.session = session or requests.Session()
        self.unit_budget = unit_budget
        self.search_budget = search_budget
        self.timeout = timeout

    # --- 할당량 -----------------------------------------------------------
    def _check_budget(self, endpoint: str) -> None:
        if self.conn is None:
            return
        if endpoint == "search":
            if db.get_usage(self.conn, "search") >= self.search_budget:
                raise QuotaExceeded(f"오늘 공식 검색 예산({self.search_budget}회)을 다 썼습니다.")
        elif db.get_usage(self.conn, "units") + COSTS[endpoint] > self.unit_budget:
            raise QuotaExceeded(f"오늘 API 유닛 예산({self.unit_budget})을 다 썼습니다.")

    def _record(self, endpoint: str) -> None:
        if self.conn is None:
            return
        if endpoint == "search":
            db.record_usage(self.conn, "search", 1)
        else:
            db.record_usage(self.conn, "units", COSTS[endpoint])

    def _get(self, endpoint: str, params: dict) -> dict:
        self._check_budget(endpoint)
        resp = self.session.get(API_BASE + endpoint, params={**params, "key": self.api_key}, timeout=self.timeout)
        self._record(endpoint)
        if resp.status_code == 200:
            return resp.json()
        try:
            error = resp.json().get("error", {})
        except ValueError:
            error = {}
        reasons = {e.get("reason") for e in error.get("errors", [])}
        message = error.get("message") or resp.text[:200]
        if resp.status_code == 403 and reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
            raise QuotaExceeded(f"YouTube 할당량 초과: {message}")
        raise YouTubeError(f"YouTube API 오류 {resp.status_code} ({', '.join(sorted(r for r in reasons if r)) or '-'}): {message}")

    # --- 채널 --------------------------------------------------------------
    def channels_by_ids(self, channel_ids: list[str]) -> list[dict]:
        out: list[dict] = []
        ids = list(dict.fromkeys(channel_ids))
        for chunk in _chunks(ids, 50):
            data = self._get("channels", {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk), "maxResults": 50})
            out.extend(data.get("items", []))
        return out

    def channel_by_handle(self, handle: str) -> dict | None:
        handle = handle if handle.startswith("@") else f"@{handle}"
        data = self._get("channels", {"part": "snippet,statistics,contentDetails", "forHandle": handle})
        items = data.get("items", [])
        return items[0] if items else None

    def channel_by_username(self, username: str) -> dict | None:
        data = self._get("channels", {"part": "snippet,statistics,contentDetails", "forUsername": username})
        items = data.get("items", [])
        return items[0] if items else None

    def featured_channel_ids(self, channel_id: str) -> list[str]:
        """채널 페이지에 걸어둔 추천 채널 목록."""
        data = self._get("channelSections", {"part": "contentDetails", "channelId": channel_id})
        ids: list[str] = []
        for section in data.get("items", []):
            ids.extend(section.get("contentDetails", {}).get("channels", []))
        return list(dict.fromkeys(i for i in ids if i != channel_id))

    # --- 영상 --------------------------------------------------------------
    def playlist_video_ids(self, playlist_id: str, max_items: int = 50) -> list[str]:
        ids: list[str] = []
        token = None
        while len(ids) < max_items:
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": min(50, max_items - len(ids))}
            if token:
                params["pageToken"] = token
            try:
                data = self._get("playlistItems", params)
            except YouTubeError as exc:
                if "playlistNotFound" in str(exc):
                    return ids
                raise
            ids.extend(i["contentDetails"]["videoId"] for i in data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return ids

    def videos_by_ids(self, video_ids: list[str]) -> list[dict]:
        out: list[dict] = []
        ids = list(dict.fromkeys(video_ids))
        for chunk in _chunks(ids, 50):
            data = self._get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk), "maxResults": 50})
            out.extend(data.get("items", []))
        return out

    def search_videos(self, query: str, order: str = "relevance", published_after: datetime | None = None,
                      duration: str | None = "medium", max_results: int = 50) -> list[dict]:
        """영상 검색 (1회 = 검색 버킷 1회). 반환: [{video_id, channel_id, title}]"""
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": order,
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "maxResults": max(1, min(max_results, 50)),
        }
        if duration and duration != "any":
            params["videoDuration"] = duration
        if published_after:
            params["publishedAfter"] = published_after.strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._get("search", params)
        results = []
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if not vid:
                continue
            snippet = item.get("snippet", {})
            results.append({"video_id": vid, "channel_id": snippet.get("channelId"), "title": snippet.get("title")})
        return results

    def comment_threads(self, video_id: str, max_results: int = 100) -> list[dict]:
        try:
            data = self._get("commentThreads", {
                "part": "snippet", "videoId": video_id, "maxResults": min(max_results, 100),
                "order": "relevance", "textFormat": "plainText",
            })
        except YouTubeError as exc:
            if "commentsDisabled" in str(exc):
                return []
            raise
        out = []
        for item in data.get("items", []):
            top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            out.append({
                "text": (top.get("textDisplay") or "")[:500],
                "likes": top.get("likeCount", 0),
                "replies": item.get("snippet", {}).get("totalReplyCount", 0),
            })
        return out

    # --- 해석 --------------------------------------------------------------
    def resolve_refs(self, refs: list[ChannelRef]) -> tuple[list[str], list[str]]:
        """ChannelRef 목록 → (채널 ID 목록, 해석 실패 메시지 목록)."""
        ids: list[str] = []
        errors: list[str] = []
        video_refs = []
        for ref in refs:
            if ref.kind == "id":
                ids.append(ref.value)
            elif ref.kind in ("handle", "username"):
                lookup = self.channel_by_handle if ref.kind == "handle" else self.channel_by_username
                item = lookup(ref.value)
                if item:
                    ids.append(item["id"])
                else:
                    errors.append(f"채널을 찾을 수 없음: {ref.raw}")
            elif ref.kind == "video":
                video_refs.append(ref)
            else:
                errors.append(f"예전 형식(/c/) 주소는 해석할 수 없어요. 채널 페이지의 @핸들 주소를 넣어주세요: {ref.raw}")
        if video_refs:
            found = {v["id"]: v["snippet"]["channelId"] for v in self.videos_by_ids([r.value for r in video_refs])}
            for ref in video_refs:
                if ref.value in found:
                    ids.append(found[ref.value])
                else:
                    errors.append(f"영상을 찾을 수 없음: {ref.raw}")
        return list(dict.fromkeys(ids)), errors
