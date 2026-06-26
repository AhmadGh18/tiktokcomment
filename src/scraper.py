"""Playwright-based TikTok profile + comments scraper.

Strategy:
- Use a persistent browser context so login cookies / TikTok challenges survive between runs.
- Scroll the profile grid to collect video URLs.
- For each video: open it, intercept JSON responses from TikTok's /api/comment/list/ endpoint
  (more reliable than DOM scraping), then scroll the comment panel to trigger more loads.
- Cache each video's comments under data/cache/<video_id>.json.

TikTok occasionally reshuffles its internal API. If comment collection drops to zero, check
network traffic in DevTools and update _is_comment_response / _extract_comments accordingly.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from playwright.sync_api import (
    BrowserContext,
    Page,
    Response,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache"
PROFILE_DIR = REPO_ROOT / ".playwright-profile"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

VIDEO_HREF_RE = re.compile(r"/(@[^/]+)/video/(\d+)")
COMMENT_API_PATHS = ("/api/comment/list", "/aweme/v1/web/comment/list", "/api/v1/comment/list")


@dataclass
class CommentRecord:
    comment_id: str
    text: str
    author: str
    likes: int
    video_id: str


def _is_comment_response(url: str) -> bool:
    return any(p in url for p in COMMENT_API_PATHS)


def _extract_comments(data: dict, video_id: str) -> list[CommentRecord]:
    """Pull comments from a TikTok JSON response, defensively across field-name variations."""
    out: list[CommentRecord] = []
    raw_list = (
        data.get("comments")
        or data.get("comment_list")
        or data.get("data", {}).get("comments")
        or []
    )
    for c in raw_list:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("cid") or c.get("id") or c.get("comment_id") or "")
        text = c.get("text") or c.get("share_info", {}).get("desc") or ""
        user = c.get("user") or {}
        author = (
            user.get("unique_id")
            or user.get("uniqueId")
            or user.get("nickname")
            or c.get("author", "")
        )
        likes = int(c.get("digg_count") or c.get("like_count") or 0)
        if not cid or not text:
            continue
        out.append(
            CommentRecord(
                comment_id=cid, text=text, author=author, likes=likes, video_id=video_id
            )
        )
    return out


def _polite_sleep(min_s: float = 1.0, max_s: float = 2.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _scroll_until_stable(page: Page, scroll_target: str, max_rounds: int, target_count_js: str) -> int:
    """Scroll an element until the JS-evaluated target count stops growing.

    `scroll_target` is a JS expression that returns a scrollable Element (or window).
    `target_count_js` is a JS expression that returns an int.
    """
    last = -1
    stagnant = 0
    for _ in range(max_rounds):
        count = page.evaluate(target_count_js)
        if count == last:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
            last = count
        page.evaluate(
            f"(() => {{ const t = {scroll_target}; if (t === window) {{ window.scrollBy(0, window.innerHeight); }} else if (t) {{ t.scrollTop = t.scrollHeight; }} }})()"
        )
        _polite_sleep(0.8, 1.6)
    return last


def _collect_video_urls(page: Page, username: str, max_videos: int | None) -> list[str]:
    handle = username.lstrip("@")
    profile_url = f"https://www.tiktok.com/@{handle}"
    page.goto(profile_url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("a[href*='/video/']", timeout=15_000)
    except PlaywrightTimeoutError:
        print(f"  no videos visible yet on {profile_url}; the page may be private or blocked")
        return []

    seen: list[str] = []
    seen_set: set[str] = set()
    stagnant_rounds = 0

    while True:
        anchors = page.eval_on_selector_all(
            "a[href*='/video/']", "els => els.map(e => e.href)"
        )
        before = len(seen_set)
        for href in anchors:
            m = VIDEO_HREF_RE.search(href)
            if not m:
                continue
            url = f"https://www.tiktok.com{m.group(0)}"
            if url not in seen_set:
                seen_set.add(url)
                seen.append(url)
                if max_videos is not None and len(seen) >= max_videos:
                    return seen

        if len(seen_set) == before:
            stagnant_rounds += 1
            if stagnant_rounds >= 4:
                break
        else:
            stagnant_rounds = 0

        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        _polite_sleep(1.2, 2.0)

    return seen


def _scrape_comments_for_video(
    page: Page, video_url: str, max_comments: int
) -> list[CommentRecord]:
    m = VIDEO_HREF_RE.search(video_url)
    if not m:
        return []
    video_id = m.group(2)

    captured: list[CommentRecord] = []
    seen_ids: set[str] = set()

    def _on_response(response: Response) -> None:
        if not _is_comment_response(response.url):
            return
        try:
            data = response.json()
        except Exception:
            return
        for rec in _extract_comments(data, video_id):
            if rec.comment_id in seen_ids:
                continue
            seen_ids.add(rec.comment_id)
            captured.append(rec)

    page.on("response", _on_response)
    try:
        page.goto(video_url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("[data-e2e='comment-level-1'], [data-e2e='comment-item']", timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        for _ in range(40):
            if len(captured) >= max_comments:
                break
            page.evaluate(
                """
                () => {
                  const items = document.querySelectorAll("[data-e2e='comment-level-1'], [data-e2e='comment-item']");
                  if (items.length) {
                    items[items.length - 1].scrollIntoView({ block: 'end' });
                  } else {
                    window.scrollBy(0, window.innerHeight);
                  }
                }
                """
            )
            _polite_sleep(0.9, 1.6)
    finally:
        page.remove_listener("response", _on_response)

    return captured[:max_comments]


def _cache_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}.json"


def _save(video_id: str, comments: list[CommentRecord]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "video_id": video_id,
        "comment_count": len(comments),
        "comments": [asdict(c) for c in comments],
    }
    _cache_path(video_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _video_id_from_url(url: str) -> str | None:
    m = VIDEO_HREF_RE.search(url)
    return m.group(2) if m else None


def scrape_profile(
    username: str,
    max_videos: int | None = None,
    max_comments_per_video: int = 100,
    headless: bool = False,
    refresh: bool = False,
) -> dict:
    """Scrape a TikTok profile's videos and comments. Returns a summary dict."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    summary = {"username": username, "videos_total": 0, "videos_scraped": 0, "videos_cached": 0, "comments_collected": 0}

    with sync_playwright() as pw:
        context: BrowserContext = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        print(f"Collecting video URLs for {username} ...")
        video_urls = _collect_video_urls(page, username, max_videos)
        summary["videos_total"] = len(video_urls)
        print(f"  found {len(video_urls)} videos")

        for idx, url in enumerate(video_urls, 1):
            vid = _video_id_from_url(url)
            if vid is None:
                continue
            if not refresh and _cache_path(vid).exists():
                summary["videos_cached"] += 1
                print(f"  [{idx}/{len(video_urls)}] {vid} cached, skipping")
                continue

            print(f"  [{idx}/{len(video_urls)}] scraping {vid} ...")
            try:
                comments = _scrape_comments_for_video(page, url, max_comments_per_video)
            except Exception as e:
                print(f"    error: {e}")
                comments = []
            _save(vid, comments)
            summary["videos_scraped"] += 1
            summary["comments_collected"] += len(comments)
            print(f"    saved {len(comments)} comments")
            _polite_sleep(2.0, 4.5)

        context.close()
    return summary


def login(start_url: str = "https://www.tiktok.com/login") -> None:
    """Open a persistent Chromium so the user can log in to TikTok by hand.

    Cookies are saved to `.playwright-profile/` and reused by future `scrape` runs,
    which dramatically reduces TikTok's bot challenges.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        print("\n" + "=" * 60)
        print("A Chromium window is open.")
        print("Log in to TikTok in that window (any method works).")
        print("Once you see your TikTok feed, return here and press ENTER.")
        print("=" * 60 + "\n")
        try:
            input("Press ENTER after you've logged in to save the session... ")
        except EOFError:
            pass
        context.close()
    print("Session saved. You can now run `scrape`.")


def load_cached_comments(cache_dir: Path = CACHE_DIR) -> Iterable[CommentRecord]:
    if not cache_dir.exists():
        return []
    out: list[CommentRecord] = []
    for f in sorted(cache_dir.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for c in payload.get("comments", []):
            out.append(
                CommentRecord(
                    comment_id=c.get("comment_id", ""),
                    text=c.get("text", ""),
                    author=c.get("author", ""),
                    likes=int(c.get("likes", 0)),
                    video_id=c.get("video_id", payload.get("video_id", "")),
                )
            )
    return out
