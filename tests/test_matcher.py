from src.matcher import load_cities, match_comment


CITIES = load_cities()


def matched_ids(comment: str) -> set[str]:
    return {m.city_id for m in match_comment(comment, CITIES)}


def test_matches_arabic_saida():
    assert "saida" in matched_ids("صيدا أرجوكم")


def test_matches_english_saida_with_typo():
    assert "saida" in matched_ids("Saidaaaa pls!!!")


def test_matches_alternate_spelling():
    assert "saida" in matched_ids("can you do Sidon?")


def test_matches_arabizi_baalbek():
    assert "baalbek" in matched_ids("ba3labak please")


def test_matches_multiple_cities_in_one_comment():
    ids = matched_ids("saida w sour 3anjad")
    assert "saida" in ids
    assert "tyre" in ids


def test_does_not_match_substring_of_unrelated_word():
    assert "tyre" not in matched_ids("i am so tired today")


def test_does_not_match_random_text():
    assert matched_ids("hahahahha lol nice video") == set()


def test_matches_arabic_with_diacritics():
    assert "tripoli" in matched_ids("طَرابُلس please")


def test_matches_arabizi_khiam():
    assert "khiam" in matched_ids("5iam pls")


def test_matches_partial_with_emoji():
    assert "nabatieh" in matched_ids("nabatié 🇱🇧❤️🔥")
