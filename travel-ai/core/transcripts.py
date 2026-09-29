"""자막 가져오기 (youtube-transcript-api, 비공식).

다른 채널 영상의 자막은 공식 API로 받을 수 없어서 비공식 라이브러리를 쓴다.
Mac 로컬(가정용 인터넷)에서는 잘 되지만 클라우드 서버 IP에서는 막히는 경우가 많다.
"""
from __future__ import annotations

MAX_CHARS = 40_000


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def format_snippets(snippets: list[dict], every_sec: float = 20.0) -> str:
    """[mm:ss] 시간 표시를 약 every_sec초마다 넣은 자막 텍스트."""
    lines: list[str] = []
    buf: list[str] = []
    block_start = None
    for sn in snippets:
        start = float(sn.get("start", 0))
        if block_start is None:
            block_start = start
        if start - block_start >= every_sec and buf:
            lines.append(f"[{_fmt_time(block_start)}] {' '.join(buf)}")
            buf, block_start = [], start
        text = (sn.get("text") or "").replace("\n", " ").strip()
        if text:
            buf.append(text)
    if buf:
        lines.append(f"[{_fmt_time(block_start or 0)}] {' '.join(buf)}")
    return "\n".join(lines)


def fetch_transcript(video_id: str, api=None) -> tuple[str | None, str | None, str]:
    """(자막 텍스트, 언어 코드, 메모). 자막을 못 가져오면 텍스트는 None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, None, "youtube-transcript-api 미설치"
    api = api or YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
        transcript = None
        for finder in (listing.find_manually_created_transcript, listing.find_generated_transcript):
            try:
                transcript = finder(["ko"])
                break
            except Exception:
                continue
        if transcript is None:
            transcript = listing.find_transcript(["ko", "en", "ja"])
        fetched = transcript.fetch()
        raw = fetched.to_raw_data()
    except Exception as exc:  # 자막 없음, 차단 등
        return None, None, f"자막 없음 ({type(exc).__name__})"
    text = format_snippets(raw)
    note = "자동 생성 자막" if getattr(transcript, "is_generated", False) else "업로더 자막"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        note += f", 앞부분 {MAX_CHARS:,}자만 사용"
    return text, getattr(transcript, "language_code", None), note
