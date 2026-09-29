"""블링·플레이보드·녹스인플루언서 등에서 찾은 채널을 한 번에 가져오기 (URL 목록 / CSV)."""
from __future__ import annotations

import csv
import io
import re

from ..youtube import ChannelRef, parse_channel_input

# 이메일 주소(abc@naver.com)는 핸들로 잡지 않도록 @ 앞에 글자가 없을 때만 핸들로 봄
_TOKEN_RE = re.compile(
    r"(https?://[^\s,;\"'<>]+|(?:www\.|m\.)?youtube\.com/[^\s,;\"'<>]+|youtu\.be/[^\s,;\"'<>]+"
    r"|(?<![\w.])@[^\s,;\"'<>/@]+|UC[0-9A-Za-z_-]{22})"
)


def parse_text(text: str) -> tuple[list[ChannelRef], list[str]]:
    """자유 형식 텍스트에서 채널 URL·@핸들·채널 ID를 뽑는다. (해석된 목록, 해석 못 한 토큰)"""
    refs: list[ChannelRef] = []
    unknown: list[str] = []
    seen: set[tuple[str, str]] = set()
    for token in _TOKEN_RE.findall(text or ""):
        ref = parse_channel_input(token)
        if ref is None:
            unknown.append(token)
            continue
        key = (ref.kind, ref.value)
        if key not in seen:
            seen.add(key)
            refs.append(ref)
    return refs, unknown


def decode_bytes(data: bytes) -> str:
    """CSV 파일 디코딩. 한국어 엑셀에서 내보낸 파일은 cp949인 경우가 많다."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def parse_csv(data: bytes | str) -> tuple[list[ChannelRef], list[str]]:
    """CSV의 모든 칸에서 채널 URL·핸들·ID를 찾는다 (열 이름이 사이트마다 달라서)."""
    text = decode_bytes(data) if isinstance(data, bytes) else data
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    cells = []
    for row in csv.reader(io.StringIO(text), dialect):
        cells.extend(row)
    return parse_text("\n".join(cells))
