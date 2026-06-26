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
    Playwright,
    Response,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
const origQuery = navigator.permissions && navigator.permissions.query;
if (origQuery) {
  navigator.permissions.query = (p) => p.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : origQuery(p);
}
"""


def _launch_browser(
    pw: Playwright,
    headless: bool,
    channel: str | None = "chrome",
) -> BrowserContext:
    """Launch a persistent context. Prefer the user's real Chrome to defeat TikTok bot checks;
    fall back to bundled Chromium if Chrome isn't installed."""
    common_kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    try_order: list[str | None] = []
    if channel:
        try_order.append(channel)
    try_order.extend([c for c in ("chrome", "msedge", None) if c not in try_order])

    last_error: Exception | None = None
    for ch in try_order:
        try:
            if ch is None:
                ctx = pw.chromium.launch_persistent_context(
                    user_agent=USER_AGENT, **common_kwargs
                )
                print("  using bundled Chromium (TikTok may flag this)")
            else:
                ctx = pw.chromium.launch_persistent_context(channel=ch, **common_kwargs)
                print(f"  using installed {ch}")
            ctx.add_init_script(STEALTH_SCRIPT)
            return ctx
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"Could not launch any browser: {last_error}")


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


def _wait_for_human(page: Page, what: str) -> None:
    """Pause and ask the user to solve a CAPTCHA / log in / dismiss a banner in the visible browser."""
    print()
    print("=" * 60)
    print(f"  TikTok did not load the {what} automatically.")
    print("  Look at the browser window — solve any CAPTCHA (slider/puzzle),")
    print("  dismiss any banner, or scroll a bit so the content appears.")
    print("  Then come back here and press ENTER to continue.")
    print("=" * 60)
    try:
        input("Press ENTER when ready... ")
    except EOFError:
        pass


def _collect_video_urls(page: Page, username: str, max_videos: int | None) -> list[str]:
    handle = username.lstrip("@")
    profile_url = f"https://www.tiktok.com/@{handle}"
    page.goto(profile_url, wait_until="domcontentloaded")

    for attempt in range(3):
        try:
            page.wait_for_selector("a[href*='/video/']", timeout=15_000)
            break
        except PlaywrightTimeoutError:
            if attempt == 2:
                print(f"  no videos after 3 attempts on {profile_url}; giving up")
                return []
            _wait_for_human(page, "profile videos")
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:
                pass

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
        for attempt in range(2):
            try:
                page.wait_for_selector(
                    "[data-e2e='comment-level-1'], [data-e2e='comment-item']", timeout=15_000
                )
                break
            except PlaywrightTimeoutError:
                if attempt == 1:
                    break
                _wait_for_human(page, f"comments for video {video_id}")

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
    browser_channel: str | None = "chrome",
    attach_port: int | None = None,
) -> dict:
    """Scrape a TikTok profile's videos and comments. Returns a summary dict.

    If `attach_port` is set, connect to an already-running Chrome with
    --remote-debugging-port=<port> instead of launching our own. This is the most
    reliable way past TikTok's bot detection because TikTok sees your real Chrome.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    summary = {"username": username, "videos_total": 0, "videos_scraped": 0, "videos_cached": 0, "comments_collected": 0}

    with sync_playwright() as pw:
        if attach_port:
            print(f"  attaching to Chrome on port {attach_port} ...")
            browser = pw.chromium.connect_over_cdp(f"http://localhost:{attach_port}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
        else:
            context = _launch_browser(pw, headless=headless, channel=browser_channel)
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

        if not attach_port:
            context.close()
    return summary


def login(start_url: str = "https://www.tiktok.com/login", browser_channel: str | None = "chrome") -> None:
    """Open a persistent Chromium so the user can log in to TikTok by hand.

    Cookies are saved to `.playwright-profile/` and reused by future `scrape` runs,
    which dramatically reduces TikTok's bot challenges.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = _launch_browser(pw, headless=False, channel=browser_channel)
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


def import_cookies(cookies_path: Path, browser_channel: str | None = "chrome") -> int:
    """Inject cookies exported from your regular Chrome (via the Cookie-Editor extension)
    into the persistent profile, so future scrapes look logged-in to TikTok.

    Accepts either:
      - Cookie-Editor JSON export (a list of cookie objects), or
      - Netscape cookies.txt format.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cookies_path = Path(cookies_path)
    text = cookies_path.read_text(encoding="utf-8")

    cookies: list[dict] = []
    text_stripped = text.lstrip()
    if text_stripped.startswith("["):
        raw = json.loads(text)
        for c in raw:
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".tiktok.com"),
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", False)),
            }
            same_site = c.get("sameSite")
            if isinstance(same_site, str):
                same_site_norm = same_site.lower()
                if same_site_norm in ("no_restriction", "none", "unspecified"):
                    cookie["sameSite"] = "None"
                elif same_site_norm == "lax":
                    cookie["sameSite"] = "Lax"
                elif same_site_norm == "strict":
                    cookie["sameSite"] = "Strict"
            exp = c.get("expirationDate") or c.get("expires")
            if exp and not c.get("session"):
                cookie["expires"] = float(exp)
            cookies.append(cookie)
    else:
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _flag, path, secure, expires, name, value = parts[:7]
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path,
                    "secure": secure.upper() == "TRUE",
                    "expires": float(expires) if expires.isdigit() else -1,
                }
            )

    if not cookies:
        print("No cookies found in file.")
        return 0

    with sync_playwright() as pw:
        context = _launch_browser(pw, headless=True, channel=browser_channel)
        context.add_cookies(cookies)
        context.close()

    print(f"Imported {len(cookies)} cookies into {PROFILE_DIR}")
    print("You can now run `scrape` — TikTok should see you as logged-in.")
    return len(cookies)


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
