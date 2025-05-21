import sqlite3
import csv

from definitions import DB_PATH, LABELED_DATA_FILE  # ✅ Use centralized paths

def label_row(score, read, dropped, not_interested):
    if score is not None and score >= 8:
        return 1
    if read == -1:
        return 1
    if dropped == 1 or not_interested == 1 or (score is not None and score <= 4):
        return 0
    return None

def extract_labeled_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT mal_id, title, type, genres, mean_score, chapters, volumes,
               user_score, read, dropped, not_interested
        FROM manga
    """)

    labeled_rows = []

    for row in cursor.fetchall():
        mal_id, title, type_, genres, mean_score, chapters, volumes, \
        user_score, read, dropped, not_interested = row

        label = label_row(user_score, read, dropped, not_interested)
        if label is not None:
            labeled_rows.append([
                mal_id, title, type_, genres, mean_score or 0, chapters or 0,
                volumes or 0, user_score or 0, read or 0, dropped, not_interested, label
            ])

    conn.close()
    return labeled_rows

def export_to_csv(data, path=LABELED_DATA_FILE):
    headers = ["mal_id", "title", "type", "genres", "mean_score", "chapters", "volumes",
               "user_score", "read", "dropped", "not_interested", "label"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)

if __name__ == "__main__":
    data = extract_labeled_data()
    export_to_csv(data)
    print(f"✅ Exported {len(data)} labeled entries to {LABELED_DATA_FILE}")
