import json
import subprocess

import pytest

from core import analyzer, db, discovery, llm
from core.prompts.schemas import SCHEMAS

from .fakes import channel_item, video_item
from .test_discovery import GEM, world


def fake_runner(payload: dict | str, calls: list | None = None):
    def run(cmd, input=None, cwd=None, capture_output=True, text=True, timeout=None):
        if calls is not None:
            calls.append({"cmd": cmd, "input": input, "cwd": cwd})
        out = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    return run


def success(data: dict) -> dict:
    return {"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(data), "structured_output": data,
            "total_cost_usd": 0.01}


def test_command_uses_subscription_login():
    cmd = llm.build_command(SCHEMAS["video"], "sonnet", "sys")
    assert "--bare" not in cmd  # bare 모드는 구독 로그인을 읽지 않음
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMAS["video"]


def test_run_structured_passes_prompt_on_stdin(tmp_path):
    calls = []
    res = llm.run_structured("긴 프롬프트", {"type": "object"}, "sonnet", tmp_path, runner=fake_runner(success({"ok": True}), calls))
    assert res.data == {"ok": True} and res.cost_usd == 0.01
    assert calls[0]["input"] == "긴 프롬프트" and calls[0]["cwd"] == str(tmp_path)


@pytest.mark.parametrize("payload, exc", [
    ({"type": "result", "subtype": "success", "is_error": True, "result": "Claude AI usage limit reached|1790000000"}, llm.LLMUsageLimit),
    ({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Not logged in · Please run /login"}, llm.LLMNotAvailable),
    ({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "something else"}, llm.LLMError),
    ("not json at all", llm.LLMError),
])
def test_run_structured_errors(tmp_path, payload, exc):
    with pytest.raises(exc):
        llm.run_structured("p", {"type": "object"}, "sonnet", tmp_path, runner=fake_runner(payload))


def test_structured_output_falls_back_to_result_text():
    out = llm.parse_output(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "{\"a\": 1}"}))
    assert out["data"] == {"a": 1}


def _fake_extras(conn, video_id, work_dir, client=None):
    return {"transcript": "[00:00] 안녕하세요", "transcript_note": "업로더 자막", "comments_json": "[]", "thumb_path": None}


def test_process_queue_and_usage_limit(conn, settings, monkeypatch):
    monkeypatch.setattr(llm, "claude_path", lambda: "/usr/bin/claude")
    client = world()
    discovery.scan_channels(conn, client, [GEM], settings, "test")
    vids = [r["video_id"] for r in conn.execute("SELECT video_id FROM videos WHERE channel_id=? LIMIT 3", (GEM,))]
    assert analyzer.enqueue(conn, vids, "video") == 3
    assert analyzer.enqueue(conn, vids, "video") == 0  # 이미 대기 중

    prompts_seen = []

    def runner(cmd, input=None, **kw):
        prompts_seen.append(input)
        if len(prompts_seen) == 2:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
                {"type": "result", "subtype": "success", "is_error": True, "result": "usage limit reached"}), stderr="")
        return fake_runner(success({"summary": "ok"}))(cmd, input=input)

    result = analyzer.process_queue(conn, settings, None, runner=runner, extras_fn=_fake_extras)
    assert result.done == 1 and "사용 한도" in result.stopped
    statuses = [r["status"] for r in conn.execute("SELECT status FROM analyses ORDER BY created_at")]
    assert statuses.count("done") == 1 and statuses.count("pending") == 2
    assert "<자막>" in prompts_seen[0] and "돌파 지수" in prompts_seen[0]


def test_process_queue_stops_on_usage_limit(conn, settings, monkeypatch):
    client = world()
    discovery.scan_channels(conn, client, [GEM], settings, "test")
    analyzer.enqueue(conn, [GEM], "hidden_gem")
    analyzer.enqueue(conn, [GEM], "contrast")
    monkeypatch.setattr(llm, "claude_path", lambda: "/usr/bin/claude")
    limit = fake_runner({"type": "result", "subtype": "success", "is_error": True, "result": "rate limit"})
    result = analyzer.process_queue(conn, settings, runner=limit)
    assert result.done == 0 and "사용 한도" in result.stopped
    assert len(analyzer.pending_items(conn)) == 2


def test_channel_analyses_and_travel_check(conn, settings):
    client = world()
    discovery.scan_channels(conn, client, [GEM], settings, "test")
    seen = []
    for kind in ("hidden_gem", "contrast", "growth"):
        data = analyzer.analyze_channel(conn, GEM, kind, settings, runner=fake_runner(success({"summary": kind}), seen))
        assert data == {"summary": kind}
        assert db.get_analysis(conn, GEM, kind)["status"] == "done"
    assert seen[0]["cmd"][seen[0]["cmd"].index("--model") + 1] == settings.model_channel
    analyzer.analyze_channel(conn, GEM, "travel_check", settings,
                             runner=fake_runner(success({"is_travel": False, "primary_type": "여행 무관", "reason": "x"})))
    assert conn.execute("SELECT grp FROM channels WHERE channel_id=?", (GEM,)).fetchone()["grp"] == "not_travel"


def test_candidate_videos_prefers_breakouts(conn, settings):
    small = "UC" + "s" * 22
    uploads = [video_item(f"s{i:02d}xxxxxxxx"[:11], small, f"강릉 여행 {i}", 10 + i * 7, 1_000) for i in range(12)]
    uploads[3] = video_item("s03xxxxxxxx", small, "강릉 여인숙 1박 2만원", 31, 60_000)
    from .fakes import FakeClient
    client = FakeClient({small: channel_item(small, "작은채널", 2_000)}, {small: uploads})
    discovery.scan_channels(conn, client, [small], settings, "test")
    cands = analyzer.candidate_videos(conn, settings, 5)
    assert cands.iloc[0]["video_id"] == "s03xxxxxxxx"
    assert cands.iloc[0]["breakout"] == pytest.approx(30)
