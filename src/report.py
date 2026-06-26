"""Aggregate cached comments into a ranked city-trend report."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .matcher import City, load_cities, match_comment, DEFAULT_FUZZ_THRESHOLD, DEFAULT_MIN_ALIAS_LEN
from .scraper import CommentRecord, load_cached_comments


REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"


@dataclass
class CityRollup:
    city: City
    mention_count: int
    unique_videos: int
    top_videos: list[tuple[str, int]]
    sample_comments: list[str]


def build_rollup(
    comments: list[CommentRecord],
    cities: list[City],
    fuzz_threshold: int = DEFAULT_FUZZ_THRESHOLD,
    min_alias_len: int = DEFAULT_MIN_ALIAS_LEN,
    samples_per_city: int = 5,
) -> list[CityRollup]:
    cities_by_id = {c.id: c for c in cities}
    mentions: Counter[str] = Counter()
    video_hits: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[str, list[str]] = defaultdict(list)

    for c in comments:
        matches = match_comment(c.text, cities, fuzz_threshold, min_alias_len)
        for m in matches:
            mentions[m.city_id] += 1
            video_hits[m.city_id][c.video_id] += 1
            if len(samples[m.city_id]) < samples_per_city:
                samples[m.city_id].append(c.text)

    rollups: list[CityRollup] = []
    for cid, count in mentions.most_common():
        city = cities_by_id[cid]
        per_video = video_hits[cid]
        rollups.append(
            CityRollup(
                city=city,
                mention_count=count,
                unique_videos=len(per_video),
                top_videos=per_video.most_common(5),
                sample_comments=samples[cid],
            )
        )
    return rollups


def write_csv(rollups: list[CityRollup], path: Path, username: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "rank",
                "city_en",
                "city_ar",
                "governorate",
                "mention_count",
                "unique_videos",
                "top_video_url",
                "sample_comment_1",
                "sample_comment_2",
                "sample_comment_3",
            ]
        )
        for rank, r in enumerate(rollups, 1):
            top_vid = r.top_videos[0][0] if r.top_videos else ""
            top_url = (
                f"https://www.tiktok.com/@{username.lstrip('@')}/video/{top_vid}"
                if username and top_vid
                else (f"https://www.tiktok.com/video/{top_vid}" if top_vid else "")
            )
            samples = (r.sample_comments + ["", "", ""])[:3]
            w.writerow(
                [
                    rank,
                    r.city.canonical_en,
                    r.city.canonical_ar,
                    r.city.governorate,
                    r.mention_count,
                    r.unique_videos,
                    top_url,
                    *samples,
                ]
            )


def write_json(rollups: list[CityRollup], path: Path, username: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "username": username,
        "city_count": len(rollups),
        "rankings": [
            {
                "rank": idx,
                "city_id": r.city.id,
                "city_en": r.city.canonical_en,
                "city_ar": r.city.canonical_ar,
                "governorate": r.city.governorate,
                "mention_count": r.mention_count,
                "unique_videos": r.unique_videos,
                "top_videos": [{"video_id": vid, "mentions": n} for vid, n in r.top_videos],
                "sample_comments": r.sample_comments,
            }
            for idx, r in enumerate(rollups, 1)
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze(
    username: str | None = None,
    fuzz_threshold: int = DEFAULT_FUZZ_THRESHOLD,
    min_alias_len: int = DEFAULT_MIN_ALIAS_LEN,
    output_dir: Path = OUTPUT_DIR,
) -> dict:
    cities = load_cities()
    comments = list(load_cached_comments())
    if not comments:
        print("No cached comments found. Run `scrape` first.")
        return {"comments": 0, "cities_matched": 0}

    rollups = build_rollup(comments, cities, fuzz_threshold, min_alias_len)
    csv_path = output_dir / "trends.csv"
    json_path = output_dir / "trends.json"
    write_csv(rollups, csv_path, username=username)
    write_json(rollups, json_path, username=username)

    print(f"Analyzed {len(comments)} comments across {len({c.video_id for c in comments})} videos.")
    print(f"Matched {len(rollups)} cities.")
    print(f"  CSV : {csv_path}")
    print(f"  JSON: {json_path}")
    if rollups:
        print("\nTop 10:")
        for i, r in enumerate(rollups[:10], 1):
            print(
                f"  {i:>2}. {r.city.canonical_en:<20} ({r.city.canonical_ar})  "
                f"mentions={r.mention_count}  videos={r.unique_videos}"
            )
    return {"comments": len(comments), "cities_matched": len(rollups)}
