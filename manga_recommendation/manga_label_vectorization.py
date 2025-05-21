import sqlite3
import pandas as pd
import joblib
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.feature_extraction.text import TfidfVectorizer

from definitions import DB_PATH, LABELED_DATA_FILE, MODEL_PATH
from manga_recommendation.utils import GenreBinarizer  # ✅ updated import path

### --- Step 1: Labeling logic ---
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
               user_score, read, dropped, not_interested, synopsis
        FROM manga
    """)
    labeled_rows = []
    for row in cursor.fetchall():
        mal_id, title, type_, genres, mean_score, chapters, volumes, \
        user_score, read, dropped, not_interested, synopsis = row

        label = label_row(user_score, read, dropped, not_interested)
        if label is not None:
            genre_list = [g.strip() for g in (genres or "").split(",") if g.strip()]
            labeled_rows.append({
                "mal_id": mal_id,
                "title": title,
                "type": type_,
                "genre_list": genre_list,
                "mean_score": mean_score or 0,
                "chapters": chapters or 0,
                "volumes": volumes or 0,
                "synopsis": synopsis or "",
                "label": label
            })

    conn.close()
    return pd.DataFrame(labeled_rows)

### --- Step 2: Train the model ---
def train_model(df):
    features = df[["type", "genre_list", "mean_score", "chapters", "volumes", "synopsis"]]
    labels = df["label"]

    preprocessor = ColumnTransformer(transformers=[
        ("genres", GenreBinarizer(), "genre_list"),
        ("type", OneHotEncoder(sparse_output=False, handle_unknown="ignore"), ["type"]),
        ("scale", StandardScaler(), ["mean_score", "chapters", "volumes"]),
        ("synopsis", TfidfVectorizer(max_features=300), "synopsis")
    ])

    pipeline = Pipeline([
        ("preprocess", preprocessor),
        ("classifier", RandomForestClassifier(n_estimators=100, random_state=42))
    ])

    X_train, X_test, y_train, y_test = train_test_split(features, labels, test_size=0.25, stratify=labels)
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    print(classification_report(y_test, y_pred))
    joblib.dump(pipeline, MODEL_PATH)
    print(f"✅ Model trained and saved to {MODEL_PATH}")

if __name__ == "__main__":
    df = extract_labeled_data()
    df.to_csv(LABELED_DATA_FILE, index=False)
    print(f"📁 Exported {len(df)} labeled entries to {LABELED_DATA_FILE}")
    train_model(df)
