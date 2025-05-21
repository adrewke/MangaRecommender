import json
import sqlite3
from definitions import MANGA_JSON, DB_PATH

def load_json_data():
    with open(MANGA_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def create_database(data, db_name=DB_PATH):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # Drop existing table
    cursor.execute("DROP TABLE IF EXISTS manga")

    # Create new table with 'dropped' and 'not_interested' fields
    cursor.execute("""
        CREATE TABLE manga (
            mal_id INTEGER PRIMARY KEY,
            title TEXT,
            type TEXT,
            mean_score REAL,
            chapters INTEGER,
            volumes INTEGER,
            status TEXT,
            genres TEXT,
            synopsis TEXT,
            images TEXT,
            published_date TEXT,
            user_score REAL,
            read INTEGER,
            dropped INTEGER DEFAULT 0,
            not_interested INTEGER DEFAULT 0
        )
    """)

    for entry in data:
        mal_id = entry.get("mal_id")
        title = entry.get("title")
        type_ = entry.get("type")
        mean_score = entry.get("score")
        chapters = entry.get("chapters")
        volumes = entry.get("volumes")
        status = entry.get("status")
        genres = ", ".join(g.get("name", "") for g in entry.get("genres", []))
        synopsis = entry.get("synopsis", "")
        images = json.dumps(entry.get("images", {}))
        published_date = entry.get("published", {}).get("from", None)

        user_data = entry.get("user_data", {})
        user_score = user_data.get("score", None)
        read = user_data.get("read", 0)
        dropped = user_data.get("dropped", 0)
        not_interested = user_data.get("not_interested", 0)

        cursor.execute("""
            INSERT INTO manga (
                mal_id, title, type, mean_score, chapters, volumes, status,
                genres, synopsis, images, published_date,
                user_score, read, dropped, not_interested
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mal_id, title, type_, mean_score, chapters, volumes, status,
            genres, synopsis, images, published_date,
            user_score, read, dropped, not_interested
        ))

    conn.commit()
    conn.close()
    print(f"✅ Converted {len(data)} entries into {db_name} with 'dropped' and 'not_interested' fields")

if __name__ == "__main__":
    data = load_json_data()
    create_database(data)
