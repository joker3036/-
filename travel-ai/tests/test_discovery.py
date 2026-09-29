from core import collector, db, discovery, keywords
from core.sources import SourceError, unofficial
from core.youtube import ChannelRef

from .fakes import FakeClient, channel_item, video_item

GEM = "UC" + "g" * 22
BIG = "UC" + "b" * 22
GOV = "UC" + "o" * 22
HIDDEN = "UC" + "h" * 22
NEAR = "UC" + "n" * 22


def world():
    stay_titles = ["{i}번째 1박 2만원 여인숙 후기", "통영 모텔 솔직 리뷰 {i}"]
    uploads = {
        GEM: [video_item(f"g{i:03d}xxxxxxx"[:11], GEM, stay_titles[i % 2].format(i=i), 3 + i * 7, 15_000) for i in range(20)],
        NEAR: [video_item(f"n{i:03d}xxxxxxx"[:11], NEAR, f"강릉 여행 브이로그 {i}", 3 + i * 7, 6_000) for i in range(20)],
        BIG: [video_item("bigvidxxxxx", BIG, "강릉 여행", 10, 500_000)],
    }
    channels = {
        GEM: channel_item(GEM, "숙소러", 7_000),
        NEAR: channel_item(NEAR, "뚜벅이", 4_000),
        BIG: channel_item(BIG, "대형채널", 900_000),
        GOV: channel_item(GOV, "OO군청", 3_000),
        HIDDEN: channel_item(HIDDEN, "비공개", None, hidden=True),
    }
    search = [{"video_id": "g000xxxxxxx", "channel_id": GEM}, {"video_id": "n000xxxxxxx", "channel_id": NEAR},
              {"video_id": "bigvidxxxxx", "channel_id": BIG}, {"video_id": "nonexistent", "channel_id": GOV},
              {"video_id": "nonexisten2", "channel_id": HIDDEN}]
    return FakeClient(channels, uploads, search)


def test_keyword_discovery_filters_and_groups(conn, settings):
    client = world()
    report = discovery.run_keyword_discovery(conn, client, settings, n_keywords=1)
    assert report.official_searches == 1
    groups = {r["channel_id"]: r["grp"] for r in conn.execute("SELECT channel_id, grp FROM channels")}
    assert groups[GEM] == "hidden_gem"
    assert groups[NEAR] == "near"  # 조회수 중앙값만 미달
    assert groups[BIG] == "big"
    reasons = {r["channel_id"]: r["filter_reason"] for r in conn.execute("SELECT channel_id, filter_reason FROM channels")}
    assert reasons[GOV] == "institution" and reasons[HIDDEN] == "hidden_subs" and reasons[BIG] == "too_big"
    # 대형 채널은 업로드 목록을 가져오지 않음 (유닛 절약)
    assert conn.execute("SELECT COUNT(*) FROM videos WHERE channel_id=?", (BIG,)).fetchone()[0] == 1
    gem = conn.execute("SELECT * FROM channel_metrics WHERE channel_id=?", (GEM,)).fetchone()
    assert gem["primary_type"] == "stay" and gem["median_views"] == 15_000
    searched = conn.execute("SELECT * FROM keywords WHERE searches > 0").fetchall()
    assert len(searched) == 1 and searched[0]["new_channels"] == 5


def test_recently_scanned_channels_are_skipped(conn, settings):
    client = world()
    discovery.scan_channels(conn, client, [GEM], settings, "test")
    client.calls.clear()
    report = discovery.scan_channels(conn, client, [GEM], settings, "test")
    assert client.calls == [] and report.scanned == 0
    discovery.scan_channels(conn, client, [GEM], settings, "test", force=True)
    assert "channels" in client.calls


def test_unofficial_failure_falls_back_to_official(conn, settings):
    settings.use_unofficial_search = True

    def broken(*args, **kwargs):
        raise RuntimeError("blocked")
        yield  # pragma: no cover

    report = discovery.run_keyword_discovery(conn, world(), settings, n_keywords=2, unofficial_fn=broken)
    assert report.fallback_used
    assert report.unofficial_searches == 0 and report.official_searches == 2
    assert any("공식 검색으로 전환" in m for m in report.messages)


def test_unofficial_search_used_when_working(conn, settings):
    settings.use_unofficial_search = True

    def fake_search(query, limit, sleep, sort_by):
        yield {"videoId": "g000xxxxxxx", "title": {"runs": [{"text": "t"}]},
               "ownerText": {"runs": [{"text": "숙소러", "navigationEndpoint": {"browseEndpoint": {"browseId": GEM}}}]}}

    client = world()
    report = discovery.run_keyword_discovery(conn, client, settings, n_keywords=2, unofficial_fn=fake_search)
    assert report.unofficial_searches == 2 and report.official_searches == 0
    assert "search" not in client.calls
    assert conn.execute("SELECT grp FROM channels WHERE channel_id=?", (GEM,)).fetchone()["grp"] == "hidden_gem"


def test_quota_stops_discovery(conn, settings):
    client = world()
    client.quota_after_searches = 1
    report = discovery.run_keyword_discovery(conn, client, settings, n_keywords=3)
    assert report.stopped_by_quota and report.official_searches == 1


def test_parse_video_renderer_and_errors():
    vid, cid, title = unofficial.parse_video_renderer({
        "videoId": "abcdefghijk", "title": {"runs": [{"text": "여인숙 "}, {"text": "탐방"}]},
        "longBylineText": {"runs": [{"navigationEndpoint": {"browseEndpoint": {"browseId": GEM}}}]}})
    assert (vid, cid, title) == ("abcdefghijk", GEM, "여인숙 탐방")

    def boom(*a, **k):
        raise ValueError("구조 변경")

    try:
        unofficial.search("키워드", search_fn=boom)
    except SourceError as exc:
        assert "구조 변경" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("SourceError expected")


def test_import_role_model_bypasses_filters(conn, settings):
    report = discovery.import_channels(conn, world(), [ChannelRef("id", BIG, BIG), ChannelRef("custom", "x", "/c/x")],
                                       settings, role_model=True)
    row = conn.execute("SELECT * FROM channels WHERE channel_id=?", (BIG,)).fetchone()
    assert row["grp"] == "role_model" and row["pinned"] == 1
    assert report.messages  # /c/ 주소는 해석 실패 메시지


def test_graduation_and_reclassify(conn, settings):
    client = world()
    discovery.scan_channels(conn, client, [GEM], settings, "test", pin=True)
    client.channels[GEM] = channel_item(GEM, "숙소러", 10_500)
    db.add_channel_snapshot(conn, GEM, 7_000, None, None, "2026-01-01T00:00:00+00:00")
    discovery.scan_channels(conn, client, [GEM], settings, "refresh", force=True)
    assert conn.execute("SELECT grp FROM channels WHERE channel_id=?", (GEM,)).fetchone()["grp"] == "graduated"

    discovery.scan_channels(conn, client, [NEAR], settings, "test")
    assert conn.execute("SELECT grp FROM channels WHERE channel_id=?", (NEAR,)).fetchone()["grp"] == "near"
    settings.criteria.min_median_views = 5_000  # 기준을 낮추면 API 호출 없이 다시 분류
    client.calls.clear()
    groups = discovery.reclassify_all(conn, settings)
    assert client.calls == [] and groups["hidden_gem"] == 1
    assert conn.execute("SELECT grp FROM channels WHERE channel_id=?", (NEAR,)).fetchone()["grp"] == "hidden_gem"


def test_keyword_queue(conn):
    keywords.ensure_keywords(conn)
    keywords.add_custom_keywords(conn, ["여인숙 투어"])
    assert keywords.pick_keywords(conn, 1)[0] == "여인숙 투어"
    keywords.record_search(conn, "여인숙 투어", 50, 3)
    assert "여인숙 투어" not in keywords.pick_keywords(conn, 5000)  # 7일 쿨다운
    picked = keywords.pick_keywords(conn, 5, ["stay"])
    kinds = {conn.execute("SELECT kind FROM keywords WHERE keyword=?", (k,)).fetchone()["kind"] for k in picked}
    assert kinds == {"stay"}


def test_prune_keeps_pinned(conn, settings):
    client = world()
    discovery.scan_channels(conn, client, [GEM], settings, "test", pin=True)
    discovery.scan_channels(conn, client, [NEAR], settings, "test")
    conn.execute("UPDATE channels SET last_scanned_at='2020-01-01T00:00:00+00:00'")
    conn.commit()
    removed = collector.prune_stale(conn, 30)
    ids = {r["channel_id"] for r in conn.execute("SELECT channel_id FROM channels")}
    assert GEM in ids and NEAR not in ids and removed >= 1
    assert conn.execute("SELECT COUNT(*) FROM videos WHERE channel_id=?", (NEAR,)).fetchone()[0] == 0
