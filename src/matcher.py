"""Match a comment against the Lebanese cities dataset."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from .normalize import normalize_alias, normalize_comment, NormalizedComment


DEFAULT_CITIES_PATH = Path(__file__).resolve().parent.parent / "data" / "lebanon_cities.json"
DEFAULT_FUZZ_THRESHOLD = 88
DEFAULT_MIN_ALIAS_LEN = 4


@dataclass
class City:
    id: str
    canonical_en: str
    canonical_ar: str
    governorate: str
    aliases_arabic: list[str]
    aliases_latin: list[str]


@dataclass
class Match:
    city_id: str
    alias: str
    score: int


def load_cities(path: Path = DEFAULT_CITIES_PATH) -> list[City]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cities: list[City] = []
    for entry in raw:
        ar_set, lat_set = set(), set()
        all_aliases = [entry["canonical_en"], entry["canonical_ar"], *entry.get("aliases", [])]
        for alias in all_aliases:
            ar, lat = normalize_alias(alias)
            if ar:
                ar_set.add(ar)
            if lat:
                lat_set.add(lat)
        cities.append(
            City(
                id=entry["id"],
                canonical_en=entry["canonical_en"],
                canonical_ar=entry["canonical_ar"],
                governorate=entry.get("governorate", ""),
                aliases_arabic=sorted(ar_set, key=len, reverse=True),
                aliases_latin=sorted(lat_set, key=len, reverse=True),
            )
        )
    return cities


def _word_boundary_contains(haystack: str, needle: str) -> bool:
    if not needle or not haystack:
        return False
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return re.search(pattern, haystack) is not None


def _alias_matches(alias: str, text: str, fuzz_threshold: int, min_len: int) -> int | None:
    """Return a score (0-100) if alias matches text under our rules; None otherwise."""
    if not alias or not text:
        return None
    if len(alias) < min_len:
        return 100 if _word_boundary_contains(text, alias) else None
    if _word_boundary_contains(text, alias):
        return 100
    if alias in text:
        return 96
    score = fuzz.partial_ratio(alias, text)
    if score >= fuzz_threshold:
        return int(score)
    return None


def match_comment(
    comment_text: str,
    cities: list[City],
    fuzz_threshold: int = DEFAULT_FUZZ_THRESHOLD,
    min_alias_len: int = DEFAULT_MIN_ALIAS_LEN,
) -> list[Match]:
    """Return all city matches for a single comment.

    A comment may match multiple cities (e.g. 'saida w sour pls').
    Best (highest-scoring) alias per city is kept.
    """
    norm: NormalizedComment = normalize_comment(comment_text)
    best: dict[str, Match] = {}

    for city in cities:
        for alias in city.aliases_arabic:
            score = _alias_matches(alias, norm.arabic, fuzz_threshold, min_alias_len)
            if score is not None:
                prev = best.get(city.id)
                if prev is None or score > prev.score:
                    best[city.id] = Match(city_id=city.id, alias=alias, score=score)
                break
        if city.id in best:
            continue
        for alias in city.aliases_latin:
            for haystack in (norm.latin, norm.latin_arabizi_expanded):
                if not haystack:
                    continue
                score = _alias_matches(alias, haystack, fuzz_threshold, min_alias_len)
                if score is not None:
                    prev = best.get(city.id)
                    if prev is None or score > prev.score:
                        best[city.id] = Match(city_id=city.id, alias=alias, score=score)
                    break
            if city.id in best:
                break

    return sorted(best.values(), key=lambda m: -m.score)
