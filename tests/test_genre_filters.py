from definitions import GENRE_BLACKLIST

BL_LOWER = {g.lower() for g in GENRE_BLACKLIST}

def clean_genres_for_inference(raw_list):
    return [g.strip() for g in (raw_list or []) if g and g.strip().lower() not in BL_LOWER]

def has_blacklisted(genres_str):
    if not genres_str:
        return False
    return any(g.strip().lower() in BL_LOWER for g in genres_str.split(","))

def test_clean_genres_for_inference_removes_blacklisted():
    sample = ["Action", "Boys Love", "Fantasy", " Hentai "]
    out = clean_genres_for_inference(sample)
    assert "Action" in out and "Fantasy" in out
    assert "Boys Love" not in out and " Hentai " not in out

def test_has_blacklisted_detects_presence():
    assert has_blacklisted("Action, Romance, Hentai") is True
    assert has_blacklisted("Action, Romance") is False
    assert has_blacklisted("") is False
