import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402
from core.config import Settings  # noqa: E402

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def settings():
    return Settings(youtube_api_key="test-key", use_unofficial_search=False)


def make_video(vid: str, days_ago: float, views: int, *, is_short: int = 0, content_type: str | None = "vlog",
               channel_id: str = "UC" + "a" * 22, title: str | None = None) -> dict:
    return {
        "video_id": vid,
        "channel_id": channel_id,
        "title": title or f"영상 {vid}",
        "published_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "views": views,
        "is_short": is_short,
        "content_type": content_type,
    }
