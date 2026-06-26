"""Alternative scraper using yt-dlp instead of Playwright.

yt-dlp talks to TikTok's mobile/internal API endpoints directly, which usually
works when Playwright + browser is blocked by TikTok's anti-bot wall.
No browser, no CAPTCHA, no login dance.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .scraper import CACHE_DIR, CommentRecord, _cache_path


def scrape_profile_ytdlp(
    username: str,
    max_videos: int | None = None,
    max_comments_per_video: int = 100,
    refresh: bool = False,
    cookies_from_browser: str | None = "chrome",
    cookies_file: str | None = None,
) -> dict:
    try:
        import yt_dlp
    except ImportError as e:
        raise SystemExit("yt-dlp is not installed. Run: pip install yt-dlp") from e

    handle = username.lstrip("@")
    profile_url = f"https://www.tiktok.com/@{handle}"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    summary = {
        "username": username,
        "videos_total": 0,
        "videos_scraped": 0,
        "videos_cached": 0,
        "comments_collected": 0,
    }

    base_opts: dict = {
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_file:
        base_opts["cookiefile"] = cookies_file
        print(f"  using cookies file: {cookies_file}")
    elif cookies_from_browser:
        base_opts["cookiesfrombrowser"] = (cookies_from_browser,)
        print(f"  using cookies from your installed {cookies_from_browser} browser")

    list_opts = {**base_opts, "extract_flat": True, "playlistend": max_videos}
    print(f"Listing videos for @{handle} via yt-dlp ...")
    try:
        with yt_dlp.YoutubeDL(list_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
    except Exception as e:
        print(f"  listing failed: {e}")
        return summary

    entries = info.get("entries", []) or []
    summary["videos_total"] = len(entries)
    print(f"  found {len(entries)} videos")

    empty_streak = 0
    for idx, entry in enumerate(entries, 1):
        video_id = str(entry.get("id") or "")
        video_url = entry.get("url") or entry.get("webpage_url") or ""
        if not video_id or not video_url:
            continue
        if not refresh and _cache_path(video_id).exists():
            payload = json.loads(_cache_path(video_id).read_text(encoding="utf-8"))
            if payload.get("comment_count", 0) > 0:
                summary["videos_cached"] += 1
                print(f"  [{idx}/{len(entries)}] {video_id} cached ({payload['comment_count']} comments), skipping")
                continue

        print(f"  [{idx}/{len(entries)}] scraping {video_id} ...")
        comment_opts = {
            **base_opts,
            "getcomments": True,
            "skip_download": True,
            "extractor_args": {
                "tiktok": {"max_comments": [str(max_comments_per_video)]}
            },
        }
        try:
            with yt_dlp.YoutubeDL(comment_opts) as ydl:
                video_info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            print(f"    error: {e}")
            video_info = {}

        raw_comments = (video_info or {}).get("comments", []) or []
        records: list[CommentRecord] = []
        for c in raw_comments:
            records.append(
                CommentRecord(
                    comment_id=str(c.get("id", "")),
                    text=c.get("text", "") or "",
                    author=c.get("author", "") or c.get("author_id", "") or "",
                    likes=int(c.get("like_count", 0) or 0),
                    video_id=video_id,
                )
            )

        payload = {
            "video_id": video_id,
            "comment_count": len(records),
            "comments": [asdict(c) for c in records],
        }
        _cache_path(video_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary["videos_scraped"] += 1
        summary["comments_collected"] += len(records)
        print(f"    saved {len(records)} comments")
        if len(records) == 0:
            empty_streak += 1
            if empty_streak >= 3:
                print()
                print("  ! 3 videos in a row returned 0 comments.")
                print("  ! TikTok is gating comments behind login. Make sure you are logged into")
                print(f"  ! TikTok in your normal {cookies_from_browser} browser, then re-run with --refresh.")
                print("  ! If you're already logged in, try --cookies-browser msedge instead.")
                print()
                break
        else:
            empty_streak = 0

    return summary
