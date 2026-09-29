from core.sources import bulk_import
from core.transcripts import format_snippets
from core.youtube import channel_row, parse_channel_input, parse_duration, video_row

CID = "UC" + "x" * 22


def test_parse_channel_input_variants():
    assert parse_channel_input(CID).kind == "id"
    assert parse_channel_input("@여행러").value == "@여행러"
    assert parse_channel_input("https://www.youtube.com/@%EC%97%AC%ED%96%89%EB%9F%AC").value == "@여행러"
    assert parse_channel_input(f"https://youtube.com/channel/{CID}/videos").value == CID
    assert parse_channel_input("youtube.com/user/oldname").kind == "username"
    assert parse_channel_input("https://m.youtube.com/watch?v=abcdefghijk&t=10").value == "abcdefghijk"
    assert parse_channel_input("https://youtu.be/abcdefghijk").kind == "video"
    assert parse_channel_input("https://www.youtube.com/shorts/abcdefghijk").kind == "video"
    assert parse_channel_input("https://www.youtube.com/c/legacy").kind == "custom"
    assert parse_channel_input("https://vling.net/channel/123") is None
    assert parse_channel_input("") is None


def test_parse_duration():
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("PT15M") == 900
    assert parse_duration("P1DT1S") == 86401
    assert parse_duration("PT59S") == 59
    assert parse_duration(None) == 0
    assert parse_duration("bogus") == 0


def test_bulk_import_text_ignores_emails_and_dedupes():
    text = f"""문의 contact@naver.com
    https://www.youtube.com/@여행러, @여행러
    {CID} 그리고 https://www.youtube.com/watch?v=abcdefghijk"""
    refs, unknown = bulk_import.parse_text(text)
    assert [(r.kind, r.value) for r in refs] == [("handle", "@여행러"), ("id", CID), ("video", "abcdefghijk")]
    assert unknown == []


def test_bulk_import_csv_cp949():
    csv_text = f"채널명,채널 링크,구독자\n숙소러,https://www.youtube.com/@stay_lover,8200\n탐험가,https://youtube.com/channel/{CID},5100\n"
    refs, _ = bulk_import.parse_csv(csv_text.encode("cp949"))
    assert {r.value for r in refs} == {"@stay_lover", CID}


def test_channel_and_video_rows():
    ch = channel_row({"id": CID, "snippet": {"title": "채널", "customUrl": "@ch"},
                      "statistics": {"subscriberCount": "8200", "viewCount": "100", "videoCount": "40"},
                      "contentDetails": {"relatedPlaylists": {"uploads": "UU" + "x" * 22}}})
    assert ch["subscribers"] == 8200 and ch["uploads_playlist"].startswith("UU") and ch["hidden_subscribers"] == 0
    hidden = channel_row({"id": CID, "snippet": {}, "statistics": {"hiddenSubscriberCount": True}, "contentDetails": {}})
    assert hidden["subscribers"] is None and hidden["hidden_subscribers"] == 1

    v = video_row({"id": "abcdefghijk", "snippet": {"channelId": CID, "title": "t", "publishedAt": "2026-01-01T00:00:00Z",
                                                    "categoryId": "19", "tags": ["a"]},
                   "statistics": {"viewCount": "1234"}, "contentDetails": {"duration": "PT2M"}})
    assert v["is_short"] == 1 and v["views"] == 1234 and v["likes"] is None
    long = video_row({"id": "x" * 11, "snippet": {}, "statistics": {}, "contentDetails": {"duration": "PT12M"}})
    assert long["is_short"] == 0


def test_format_snippets_groups_by_time():
    snippets = [{"text": "안녕", "start": 0}, {"text": "하세요", "start": 5}, {"text": "여기는", "start": 25},
                {"text": "강릉", "start": 70}]
    assert format_snippets(snippets, every_sec=20) == "[00:00] 안녕 하세요\n[00:25] 여기는\n[01:10] 강릉"
