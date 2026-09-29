"""경로, 기본 기준값, 사용자 설정(data/settings.json) 로드·저장."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TRAVEL_AI_DATA", ROOT / "data"))
SETTINGS_PATH = DATA_DIR / "settings.json"
LLM_WORK_DIR = DATA_DIR / "llm-work"


def is_demo() -> bool:
    return os.environ.get("DEMO") == "1"


def db_path() -> Path:
    return DATA_DIR / ("demo.db" if is_demo() else "travel_ai.db")


@dataclass
class Criteria:
    """숨은 고수 판정 기준 (롱폼 기준)."""

    max_subscribers: int = 10_000
    min_uploads_90d: int = 6
    max_median_gap_days: float = 14
    max_gap_days: float = 28
    max_days_since_last: float = 21
    min_median_views: int = 10_000
    min_travel_ratio: float = 0.5
    recent_n: int = 10


@dataclass
class Settings:
    youtube_api_key: str = ""
    # 발굴
    use_unofficial_search: bool = True
    unofficial_sleep_sec: float = 1.5
    max_keywords_per_run: int = 30
    results_per_keyword: int = 50
    daily_unit_budget: int = 9_000
    daily_search_budget: int = 95
    rescan_days: int = 14
    min_video_count: int = 10
    # 지표
    criteria: Criteria = field(default_factory=Criteria)
    outlier_threshold: float = 3.0
    breakout_threshold: float = 5.0
    min_video_age_days: int = 7
    shorts_max_seconds: int = 180
    median_window: int = 30
    turning_point_factor: float = 3.0
    # AI 분석
    analysis_batch_size: int = 20
    model_video: str = "sonnet"
    model_channel: str = "opus"
    llm_timeout_sec: int = 600
    # 데이터 정리 (YouTube API 정책: 30일 넘게 갱신 안 된 데이터 정리)
    auto_prune: bool = True
    stale_days: int = 30

    @property
    def api_key(self) -> str:
        return os.environ.get("YOUTUBE_API_KEY") or self.youtube_api_key


def _from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def load_settings(path: Path | None = None) -> Settings:
    path = path or SETTINGS_PATH
    _load_dotenv()
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    criteria = Criteria(**_from_dict(Criteria, raw.pop("criteria", {}) or {}))
    return Settings(criteria=criteria, **_from_dict(Settings, raw))


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env", override=False)
