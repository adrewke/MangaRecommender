import sqlite3
import csv
import logging

from definitions import DB_PATH, LABELED_DATA_FILE  # Centralized project paths

# Configure logger
logger = logging.getLogger("label_exporter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def label_row(score, read, dropped, not_interested):
    """
    Derive binary label for recommendation training.
    - Positive (1): high score (>=8) or fully read (-1).
    - Negative (0): dropped, marked not interested, or low score (<=4).
    - None: unlabeled.
    """
    if score is not None and score >= 8:
        return 1
    if read == -1:
        return 1
    if dropped == 1 or not_interested == 1 or (score is not None and score <= 4):
        return 0
    return None


def extract_labeled_data():
    """Extract labeled rows from the manga DB for model training."""
    labeled_rows = []

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT mal_id, title, type, genres, mean_score, chapters, volumes,
                   user_score, read, dropped, not_interested
            FROM manga
        """)

        for row in cursor.fetchall():
            mal_id, title, type_, genres, mean_score, chapters, volumes, \
            user_score, read, dropped, not_interested = row

            label = label_row(user_score, read, dropped, not_interested)
            if label is not None:
                labeled_rows.append([
                    mal_id,
                    title,
                    type_,
                    genres,
                    mean_score or 0,
                    chapters or 0,
                    volumes or 0,
                    user_score or 0,
                    read or 0,
                    dropped,
                    not_interested,
                    label,
                ])

    return labeled_rows


def export_to_csv(data, path=LABELED_DATA_FILE):
    """Write labeled dataset to CSV for inspection/training."""
    headers = [
        "mal_id", "title", "type", "genres", "mean_score", "chapters", "volumes",
        "user_score", "read", "dropped", "not_interested", "label",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)
    logger.info("Exported %d labeled entries to %s", len(data), path)


if __name__ == "__main__":
    data = extract_labeled_data()
    export_to_csv(data)
