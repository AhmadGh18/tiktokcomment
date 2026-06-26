"""Text normalization for mixed Arabic / Latin / Arabizi comments."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

try:
    from pyarabic import araby as _araby
except ImportError:
    _araby = None


ARABIC_RANGE = r"؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿"
_ARABIC_CHAR_RE = re.compile(f"[{ARABIC_RANGE}]")
_NON_ARABIC_RE = re.compile(f"[^{ARABIC_RANGE}\\s]+")
_NON_LATIN_RE = re.compile(f"[{ARABIC_RANGE}]+")
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_DIGIT_REPEAT_RE = re.compile(r"(.)\1{2,}")
_WHITESPACE_RE = re.compile(r"\s+")

ARABIZI_MAP = {
    "2": "a",
    "3": "a",
    "5": "kh",
    "6": "t",
    "7": "h",
    "8": "gh",
    "9": "q",
}


@dataclass(frozen=True)
class NormalizedComment:
    arabic: str
    latin: str
    latin_arabizi_expanded: str

    def all_variants(self) -> list[str]:
        seen, out = set(), []
        for v in (self.arabic, self.latin, self.latin_arabizi_expanded):
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out


def _strip_emoji_and_symbols(text: str) -> str:
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("C") or cat.startswith("S"):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def normalize_arabic(text: str) -> str:
    """Normalize Arabic script: strip diacritics, unify alef/ya/ta-marbuta, collapse repeats."""
    if not text:
        return ""
    text = _strip_emoji_and_symbols(text)
    text = _NON_ARABIC_RE.sub(" ", text)

    if _araby is not None:
        text = _araby.strip_tashkeel(text)
        text = _araby.strip_tatweel(text)
    else:
        text = re.sub(r"[ً-ْٰـ]", "", text)

    text = re.sub(r"[آأإٱ]", "ا", text)
    text = text.replace("ى", "ي")
    text = text.replace("ة", "ه")
    text = text.replace("ؤ", "و")
    text = text.replace("ئ", "ي")

    text = _DIGIT_REPEAT_RE.sub(r"\1\1", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_latin(text: str) -> str:
    """Normalize Latin script: lowercase, strip punctuation/emoji, collapse repeats."""
    if not text:
        return ""
    text = _strip_emoji_and_symbols(text)
    text = _NON_LATIN_RE.sub(" ", text)
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT_RE.sub(" ", text)
    text = _DIGIT_REPEAT_RE.sub(r"\1\1", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def expand_arabizi(latin_text: str) -> str:
    """Replace digit-substitutes (3→a, 7→h, 5→kh, 2→a, etc.) so 'ba3labak' matches 'baalbak'."""
    if not latin_text:
        return ""
    out = []
    for ch in latin_text:
        out.append(ARABIZI_MAP.get(ch, ch))
    expanded = "".join(out)
    expanded = _DIGIT_REPEAT_RE.sub(r"\1\1", expanded)
    return _WHITESPACE_RE.sub(" ", expanded).strip()


def normalize_comment(text: str) -> NormalizedComment:
    arabic = normalize_arabic(text)
    latin = normalize_latin(text)
    expanded = expand_arabizi(latin) if latin != expand_arabizi(latin) else ""
    return NormalizedComment(arabic=arabic, latin=latin, latin_arabizi_expanded=expanded)


def normalize_alias(text: str) -> tuple[str, str]:
    """Normalize a city alias the same way as comments — returns (arabic, latin_or_expanded)."""
    arabic = normalize_arabic(text)
    latin = normalize_latin(text)
    if latin:
        latin = expand_arabizi(latin)
    return arabic, latin
