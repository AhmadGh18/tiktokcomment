from src.normalize import (
    expand_arabizi,
    normalize_arabic,
    normalize_comment,
    normalize_latin,
)


def test_arabic_strips_tashkeel():
    assert normalize_arabic("صَيْدَا") == "صيدا"


def test_arabic_collapses_repeats():
    assert normalize_arabic("صيداااا") == "صيدااا"[:-1]


def test_arabic_normalizes_alef_and_ya_and_ta():
    assert normalize_arabic("إصيدى") == normalize_arabic("اصيدي")
    assert normalize_arabic("صيدة") == normalize_arabic("صيده")


def test_latin_lowercases_and_strips_punct():
    assert normalize_latin("Saida, please!!!") == "saida please"


def test_latin_collapses_repeats():
    assert normalize_latin("Saidaaaa") == "saidaa"


def test_latin_strips_emoji():
    assert "saida" in normalize_latin("Saida 🇱🇧❤️")


def test_arabizi_expansion():
    assert expand_arabizi("ba3labak") == "baalabak"
    assert expand_arabizi("7asbaya") == "hasbaya"
    assert expand_arabizi("5iam") == "khiam"


def test_normalize_comment_mixed():
    n = normalize_comment("saida pls صيدا ❤️")
    assert "saida" in n.latin
    assert "صيدا" in n.arabic


def test_normalize_comment_no_arabic_when_empty():
    n = normalize_comment("just english")
    assert n.arabic == ""
    assert "english" in n.latin
