import sqlite3
import requests
import time
from difflib import get_close_matches
from definitions import DB_PATH

SEARCH_URL = "https://api.mangadex.org/manga"
CHAPTER_URL = "https://api.mangadex.org/chapter"
COMMIT_BATCH_SIZE = 100

def search_manga_id(title):
    params = {
        "title": title,
        "limit": 10
    }
    try:
        response = requests.get(SEARCH_URL, params=params)
        response.raise_for_status()
        results = response.json().get("data", [])

        titles = {
            r["id"]: r["attributes"]["title"].get("en", list(r["attributes"]["title"].values())[0])
            for r in results
        }

        best = get_close_matches(title, titles.values(), n=1, cutoff=0.6)
        if best:
            best_id = [k for k, v in titles.items() if v == best[0]]
            return best_id[0] if best_id else None

    except Exception as e:
        print(f"❌ Search error for '{title}': {e}")
    return None

def get_latest_chapter(manga_id):
    params = {
        "manga": manga_id,
        "translatedLanguage[]": "en",
        "order[chapter]": "desc",
        "limit": 1
    }
    try:
        response = requests.get(CHAPTER_URL, params=params)
        response.raise_for_status()
        data = response.json().get("data", [])
        if data:
            chapter = data[0]["attributes"].get("chapter")
            return int(float(chapter)) if chapter and chapter.replace('.', '', 1).isdigit() else None
    except Exception as e:
        print(f"❌ Chapter fetch error for manga ID {manga_id}: {e}")
    return None

def update_manga_chapters():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT mal_id, title, chapters FROM manga WHERE status = 'Publishing'")
    manga_list = cursor.fetchall()

    updated = 0
    changes_in_batch = 0

    for idx, (mal_id, title, current) in enumerate(manga_list, start=1):
        print(f"🔍 Searching MangaDex for '{title}'")
        manga_id = search_manga_id(title)
        if manga_id:
            chapter_count = get_latest_chapter(manga_id)
            if chapter_count and (current is None or chapter_count > current):
                print(f"✅ Updating '{title}' to {chapter_count} chapters (was {current})")
                cursor.execute("UPDATE manga SET chapters = ? WHERE mal_id = ?", (chapter_count, mal_id))
                updated += 1
                changes_in_batch += 1
            else:
                print(f"➖ No newer chapter count for '{title}'")
        else:
            print(f"❌ No match found for '{title}'")

        if changes_in_batch >= COMMIT_BATCH_SIZE:
            conn.commit()
            print(f"🗂️ Committed batch of {changes_in_batch} updates at record {idx}")
            changes_in_batch = 0

        time.sleep(1.2)  # Rate limiting

    if changes_in_batch > 0:
        conn.commit()
        print(f"🗂️ Final batch commit of {changes_in_batch} remaining updates.")

    conn.close()
    print(f"\n✅ Done. Updated {updated} manga entries.")

if __name__ == "__main__":
    update_manga_chapters()
