"""CLI entry point: scrape / analyze / run."""

from __future__ import annotations

import argparse
import sys

from .matcher import DEFAULT_FUZZ_THRESHOLD, DEFAULT_MIN_ALIAS_LEN
from .report import analyze
from .scraper import login, scrape_profile


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tiktok-lebanon", description="TikTok comment trend analyzer for Lebanese cities.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "login",
        help="Open a browser so you can log in to TikTok once; cookies are saved for later scrapes.",
    )

    s = sub.add_parser("scrape", help="Scrape a TikTok profile's videos and comments.")
    s.add_argument("username", help="TikTok handle, e.g. @your_handle (the @ is optional)")
    s.add_argument("--max-videos", type=int, default=None, help="Limit number of videos to scrape.")
    s.add_argument("--max-comments", type=int, default=100, help="Max comments per video (default: 100).")
    s.add_argument("--headless", action="store_true", help="Run browser headless (default: visible).")
    s.add_argument("--refresh", action="store_true", help="Re-scrape videos already in cache.")

    a = sub.add_parser("analyze", help="Aggregate cached comments into a ranked report.")
    a.add_argument("--username", default=None, help="Used to build clickable video URLs in the report.")
    a.add_argument("--fuzz-threshold", type=int, default=DEFAULT_FUZZ_THRESHOLD)
    a.add_argument("--min-alias-len", type=int, default=DEFAULT_MIN_ALIAS_LEN)

    r = sub.add_parser("run", help="Scrape then analyze in one shot.")
    r.add_argument("username")
    r.add_argument("--max-videos", type=int, default=None)
    r.add_argument("--max-comments", type=int, default=100)
    r.add_argument("--headless", action="store_true")
    r.add_argument("--refresh", action="store_true")
    r.add_argument("--fuzz-threshold", type=int, default=DEFAULT_FUZZ_THRESHOLD)
    r.add_argument("--min-alias-len", type=int, default=DEFAULT_MIN_ALIAS_LEN)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "login":
        login()
        return 0

    if args.command == "scrape":
        summary = scrape_profile(
            username=args.username,
            max_videos=args.max_videos,
            max_comments_per_video=args.max_comments,
            headless=args.headless,
            refresh=args.refresh,
        )
        print(f"\nDone. {summary}")
        return 0

    if args.command == "analyze":
        analyze(
            username=args.username,
            fuzz_threshold=args.fuzz_threshold,
            min_alias_len=args.min_alias_len,
        )
        return 0

    if args.command == "run":
        scrape_profile(
            username=args.username,
            max_videos=args.max_videos,
            max_comments_per_video=args.max_comments,
            headless=args.headless,
            refresh=args.refresh,
        )
        analyze(
            username=args.username,
            fuzz_threshold=args.fuzz_threshold,
            min_alias_len=args.min_alias_len,
        )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
