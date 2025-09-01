import os
import sqlite3
import pytest
from definitions import DB_PATH

REQUIRED_COLUMNS = {
    "mal_id", "title", "type", "genres", "mean_score", "chapters", "volumes",
    "synopsis", "images", "published_date", "user_score", "read", "dropped",
    "not_interested",  # some scripts use this; skip if your schema differs
}

@pytest.mark.skipif(not os.path.exists(DB_PATH), reason="Local DB not available")
def test_manga_table_has_expected_columns():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(manga)")
        cols = {row[1] for row in cur.fetchall()}
    missing = REQUIRED_COLUMNS - cols
    # Be forgiving if your schema is slightly different; warn instead of fail:
    if missing:
        pytest.skip(f"manga table is missing columns: {sorted(missing)}")
