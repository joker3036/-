"""터미널에서 실행하는 수집·분석 명령.

사용 예
  python collect.py discover --keywords 20            # 키워드 탐색 (비공식 검색 켜져 있으면 우선 사용)
  python collect.py discover --kinds stay explore     # 숙소 리뷰·이색 탐방 키워드만
  python collect.py import channels.csv               # 블링·녹스 등에서 내보낸 CSV/URL 목록 가져오기
  python collect.py import urls.txt --role-model      # 롤모델로 등록
  python collect.py refresh                           # 관심 채널 갱신 (스냅샷)
  python collect.py analyze --auto 10                 # 돌파 영상 10개를 골라 AI 분석
  python collect.py prune                             # 30일 넘게 갱신 안 된 데이터 정리
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core import analyzer, collector, config, db, discovery
from core.sources import bulk_import
from core.youtube import MissingApiKey, YouTubeClient


def _progress(n: int, total: int, label: str) -> None:
    print(f"  [{n}/{total}] {label}", flush=True)


def _client(conn, settings) -> YouTubeClient:
    try:
        return YouTubeClient(settings.api_key, conn, unit_budget=settings.daily_unit_budget,
                             search_budget=settings.daily_search_budget)
    except MissingApiKey as exc:
        sys.exit(f"오류: {exc}  (.env 파일에 YOUTUBE_API_KEY=... 를 넣거나 대시보드 설정에서 입력하세요)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="여행 유튜브 벤치마킹 수집·분석")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("discover", help="키워드 탐색으로 채널 발굴")
    p.add_argument("--keywords", type=int, default=10)
    p.add_argument("--kinds", nargs="*", choices=["vlog", "info", "stay", "explore", "food", "custom"])
    p.add_argument("--order", default="alternate", choices=list(discovery.ORDER_LABELS))

    p = sub.add_parser("import", help="URL 목록·CSV 파일에서 채널 가져오기")
    p.add_argument("file", type=Path)
    p.add_argument("--role-model", action="store_true")
    p.add_argument("--pin", action="store_true")

    sub.add_parser("refresh", help="관심 채널(📌)·롤모델 갱신")

    p = sub.add_parser("analyze", help="AI 분석 대기열 처리")
    p.add_argument("--auto", type=int, default=0, help="돌파 영상 N개를 자동으로 대기열에 추가")
    p.add_argument("--limit", type=int, default=None)

    sub.add_parser("prune", help="오래된 데이터 정리")

    args = parser.parse_args(argv)
    settings = config.load_settings()
    conn = db.connect(config.db_path())

    if args.cmd == "discover":
        report = discovery.run_keyword_discovery(conn, _client(conn, settings), settings, args.keywords, args.kinds,
                                                 args.order, progress=_progress)
    elif args.cmd == "import":
        data = args.file.read_bytes()
        refs, unknown = (bulk_import.parse_csv(data) if args.file.suffix.lower() in (".csv", ".tsv")
                         else bulk_import.parse_text(bulk_import.decode_bytes(data)))
        print(f"채널 후보 {len(refs)}개 (해석 못 함 {len(unknown)}개)")
        report = discovery.import_channels(conn, _client(conn, settings), refs, settings, args.role_model, args.pin, _progress)
    elif args.cmd == "refresh":
        ids = [r["channel_id"] for r in conn.execute("SELECT channel_id FROM channels WHERE pinned=1 OR is_role_model=1")]
        print(f"관심 채널 {len(ids)}개 갱신")
        report = collector.refresh_channels(conn, _client(conn, settings), ids, settings, _progress)
    elif args.cmd == "analyze":
        client = _client(conn, settings) if settings.api_key else None
        if args.auto:
            cands = analyzer.candidate_videos(conn, settings, args.auto)
            added = analyzer.enqueue(conn, list(cands["video_id"]) if not cands.empty else [], "video")
            print(f"대기열에 영상 {added}개 추가")
        result = analyzer.process_queue(conn, settings, client, args.limit, progress=_progress)
        print(f"완료 {result.done}개, 오류 {len(result.errors)}개")
        for e in result.errors:
            print("  -", e)
        if result.stopped:
            print("멈춤:", result.stopped)
        return 0
    else:
        print(f"정리한 채널 {collector.prune_stale(conn, settings.stale_days)}개")
        return 0

    print(report.summary())
    for m in report.messages:
        print("  -", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
