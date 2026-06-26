"""CLI entry point: scrape / analyze / run."""

from __future__ import annotations

import argparse
import sys

from .matcher import DEFAULT_FUZZ_THRESHOLD, DEFAULT_MIN_ALIAS_LEN
from .report import analyze
from .scraper import import_cookies, login, scrape_profile
from .scraper_ytdlp import scrape_profile_ytdlp


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tiktok-lebanon", description="TikTok comment trend analyzer for Lebanese cities.")
    sub = p.add_subparsers(dest="command", required=True)

    l = sub.add_parser(
        "login",
        help="Open a browser so you can log in to TikTok once; cookies are saved for later scrapes.",
    )
    l.add_argument(
        "--browser",
        default="chrome",
        help="Browser channel: chrome | msedge | chromium (default: chrome — least bot-detected).",
    )

    ic = sub.add_parser(
        "import-cookies",
        help="Import a cookies.json/cookies.txt exported from your regular Chrome (see SETUP.md).",
    )
    ic.add_argument("cookies_file", help="Path to the cookies file you exported.")

    s = sub.add_parser("scrape", help="Scrape a TikTok profile's videos and comments.")
    s.add_argument("username", help="TikTok handle, e.g. @your_handle (the @ is optional)")
    s.add_argument("--max-videos", type=int, default=None, help="Limit number of videos to scrape.")
    s.add_argument("--max-comments", type=int, default=100, help="Max comments per video (default: 100).")
    s.add_argument("--headless", action="store_true", help="Run browser headless (default: visible).")
    s.add_argument("--refresh", action="store_true", help="Re-scrape videos already in cache.")
    s.add_argument("--browser", default="chrome", help="Browser channel: chrome | msedge | chromium.")
    s.add_argument(
        "--attach",
        type=int,
        default=None,
        metavar="PORT",
        help="Attach to a Chrome you already started with --remote-debugging-port=PORT. Bypasses bot detection.",
    )
    s.add_argument(
        "--backend",
        choices=["playwright", "ytdlp"],
        default="playwright",
        help="Scraping backend. 'ytdlp' uses yt-dlp (no browser, bypasses TikTok's web bot wall).",
    )
    s.add_argument(
        "--cookies-browser",
        default="chrome",
        choices=["chrome", "msedge", "firefox", "brave", "none"],
        help="Browser to pull TikTok cookies from for ytdlp backend (default: chrome). Use 'none' to disable.",
    )
    s.add_argument(
        "--cookies-file",
        default=None,
        help="Path to a Netscape cookies.txt file (overrides --cookies-browser). Use for Chrome on Win11.",
    )

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
    r.add_argument("--browser", default="chrome")
    r.add_argument("--attach", type=int, default=None, metavar="PORT")
    r.add_argument("--backend", choices=["playwright", "ytdlp"], default="playwright")
    r.add_argument("--cookies-browser", default="chrome", choices=["chrome", "msedge", "firefox", "brave", "none"])
    r.add_argument("--cookies-file", default=None)
    r.add_argument("--fuzz-threshold", type=int, default=DEFAULT_FUZZ_THRESHOLD)
    r.add_argument("--min-alias-len", type=int, default=DEFAULT_MIN_ALIAS_LEN)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "login":
        channel = None if args.browser == "chromium" else args.browser
        login(browser_channel=channel)
        return 0

    if args.command == "import-cookies":
        from pathlib import Path
        import_cookies(Path(args.cookies_file))
        return 0

    if args.command == "scrape":
        if args.backend == "ytdlp":
            cb = None if args.cookies_browser == "none" else args.cookies_browser
            summary = scrape_profile_ytdlp(
                username=args.username,
                max_videos=args.max_videos,
                max_comments_per_video=args.max_comments,
                refresh=args.refresh,
                cookies_from_browser=cb,
                cookies_file=args.cookies_file,
            )
        else:
            channel = None if args.browser == "chromium" else args.browser
            summary = scrape_profile(
                username=args.username,
                max_videos=args.max_videos,
                max_comments_per_video=args.max_comments,
                headless=args.headless,
                refresh=args.refresh,
                browser_channel=channel,
                attach_port=args.attach,
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
        if args.backend == "ytdlp":
            cb = None if args.cookies_browser == "none" else args.cookies_browser
            scrape_profile_ytdlp(
                username=args.username,
                max_videos=args.max_videos,
                max_comments_per_video=args.max_comments,
                refresh=args.refresh,
                cookies_from_browser=cb,
                cookies_file=args.cookies_file,
            )
        else:
            channel = None if args.browser == "chromium" else args.browser
            scrape_profile(
                username=args.username,
                max_videos=args.max_videos,
                max_comments_per_video=args.max_comments,
                headless=args.headless,
                refresh=args.refresh,
                browser_channel=channel,
                attach_port=args.attach,
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
