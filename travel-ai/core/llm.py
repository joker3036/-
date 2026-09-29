"""Claude 호출 (본인 Claude 구독 사용).

Mac에 설치·로그인해 둔 Claude Code를 headless 모드(`claude -p`)로 실행한다.
- `--bare`를 쓰면 구독 로그인을 읽지 않으므로 절대 넣지 않는다.
- 실행 폴더는 빈 작업 폴더(data/llm-work)로 두어 이 저장소의 CLAUDE.md·hooks가 끼어들지 않게 한다.
- 도구는 Read만 켠다 (썸네일 이미지를 읽기 위해).
- 이 방식은 본인 PC에서 본인이 쓰는 용도다. 다른 사람에게 서비스하려면 API 키 방식으로 바꿔야 한다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LIMIT_MARKERS = ("usage limit", "rate limit", "rate_limit", "limit reached", "limit will reset", "too many requests",
                  "overloaded", "quota")


class LLMError(Exception):
    pass


class LLMNotAvailable(LLMError):
    """claude 명령을 찾을 수 없거나 로그인이 안 되어 있을 때."""


class LLMUsageLimit(LLMError):
    """구독 사용 한도에 걸렸을 때. 잠시 후(보통 몇 시간 뒤) 다시 시도."""


@dataclass
class LLMResult:
    data: dict
    cost_usd: float | None
    model: str


def claude_path() -> str | None:
    return shutil.which("claude")


def build_command(schema: dict, model: str, system_prompt: str | None = None, instruction: str | None = None) -> list[str]:
    cmd = [
        "claude", "-p", instruction or "표준 입력으로 받은 지시와 자료를 읽고, 지정된 JSON 스키마에 맞춰 한국어로 답하세요.",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--model", model,
        "--tools", "Read",
        "--allowedTools", "Read",
        "--permission-mode", "dontAsk",
        "--no-session-persistence",
        "--strict-mcp-config",
    ]
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]
    return cmd


def parse_output(stdout: str, stderr: str = "") -> dict:
    """claude -p --output-format json 결과에서 structured_output을 꺼낸다."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        text = (stdout + " " + stderr).strip()
        if any(m in text.lower() for m in _LIMIT_MARKERS):
            raise LLMUsageLimit(text[:300])
        if "not logged in" in text.lower() or "login" in text.lower():
            raise LLMNotAvailable("Claude Code 로그인이 필요합니다. 터미널에서 `claude`를 한 번 실행해 로그인하세요.")
        raise LLMError(f"Claude 응답을 해석할 수 없습니다: {text[:300]}")
    if isinstance(payload, list):  # 혹시 이벤트 목록이면 마지막 result를 사용
        payload = next((p for p in reversed(payload) if p.get("type") == "result"), {})
    if payload.get("is_error") or payload.get("subtype") != "success":
        message = str(payload.get("result") or payload.get("subtype") or payload)
        lower = message.lower()
        if any(m in lower for m in _LIMIT_MARKERS) or payload.get("api_error_status") == 429:
            raise LLMUsageLimit(message[:300])
        if "not logged in" in lower or "invalid api key" in lower or "authentication" in lower:
            raise LLMNotAvailable("Claude Code 로그인이 필요합니다. 터미널에서 `claude`를 한 번 실행해 로그인하세요.")
        raise LLMError(message[:500])
    data = payload.get("structured_output")
    if data is None:
        try:
            data = json.loads(payload.get("result") or "")
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMError("구조화된 결과(structured_output)가 없습니다.") from exc
    return {"data": data, "cost_usd": payload.get("total_cost_usd")}


def run_structured(prompt: str, schema: dict, model: str, work_dir: Path, system_prompt: str | None = None,
                   timeout: int = 600, runner=subprocess.run) -> LLMResult:
    """프롬프트를 표준 입력으로 넘기고 스키마에 맞는 JSON을 받는다."""
    if runner is subprocess.run and claude_path() is None:
        raise LLMNotAvailable("`claude` 명령을 찾을 수 없습니다. Claude Code를 설치하고 로그인하세요 (README 참고).")
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(schema, model, system_prompt)
    try:
        proc = runner(cmd, input=prompt, cwd=str(work_dir), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LLMError(f"Claude 응답이 {timeout}초 안에 오지 않았습니다.") from exc
    out = parse_output(proc.stdout or "", proc.stderr or "")
    return LLMResult(data=out["data"], cost_usd=out["cost_usd"], model=model)
