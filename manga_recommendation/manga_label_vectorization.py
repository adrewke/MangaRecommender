from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    RocCurveDisplay,
    accuracy_score,
    classification_report,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from definitions import DB_PATH, LABELED_DATA_FILE, MODEL_PATH, GENRE_BLACKLIST
from manga_recommendation.utils import GenreBinarizer  # custom transformer for list[str] genres

# -------------------------
# Config
# -------------------------
@dataclass(frozen=True)
class TrainConfig:
    test_size: float = 0.25
    random_state: int = 42
    model_version: str = "rf-v1"
    tfidf_max_features: int = 300
    n_estimators: int = 200  # a touch higher for stability

CONFIG = TrainConfig()
BL_LOWER = {g.lower() for g in GENRE_BLACKLIST}

# -------------------------
# Labeling logic
# -------------------------
def label_row(score: Optional[int], read: Optional[int], dropped: Optional[int], not_interested: Optional[int]) -> Optional[int]:
    """
    Heuristic labeling:
      - Positive (1): high user score (>=8) OR explicitly finished (read == -1)
      - Negative (0): dropped, not interested, or low score (<=4)
      - None: ambiguous / not enough signal (excluded from training)
    """
    if score is not None and score >= 8:
        return 1
    if read == -1:
        return 1
    if dropped == 1 or not_interested == 1 or (score is not None and score <= 4):
        return 0
    return None

def _split_genres(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [g.strip() for g in s.split(",") if g.strip()]

def _clean_genres_for_training(genres: Iterable[str]) -> List[str]:
    """Remove blacklisted genres so the encoder never sees them."""
    return [g for g in genres if g and g.lower() not in BL_LOWER]

# -------------------------
# Data extraction
# -------------------------
def extract_labeled_data() -> pd.DataFrame:
    """
    Pulls user-labeled signals from the DB and returns a supervised dataset with:
    [type, genre_list, mean_score, chapters, volumes, synopsis] + label
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT mal_id, title, type, genres, mean_score, chapters, volumes,
                   user_score, read, dropped, not_interested, synopsis
            FROM manga
            """
        )
        rows = cur.fetchall()

    labeled_rows: List[dict] = []
    for (
        mal_id,
        title,
        type_,
        genres,
        mean_score,
        chapters,
        volumes,
        user_score,
        read,
        dropped,
        not_interested,
        synopsis,
    ) in rows:
        y = label_row(user_score, read, dropped, not_interested)
        if y is None:
            continue

        genres_list = _clean_genres_for_training(_split_genres(genres))
        labeled_rows.append(
            {
                "mal_id": mal_id,
                "title": title,
                "type": type_ or "",
                "genre_list": genres_list,
                "mean_score": float(mean_score or 0.0),
                "chapters": int(chapters or 0),
                "volumes": int(volumes or 0),
                "synopsis": synopsis or "",
                "label": int(y),
            }
        )

    df = pd.DataFrame(labeled_rows)
    return df

# -------------------------
# Training
# -------------------------
def _print_class_balance(y: pd.Series) -> None:
    counts = y.value_counts(dropna=False).to_dict()
    total = int(y.shape[0])
    pos = counts.get(1, 0)
    neg = counts.get(0, 0)
    print(f"Class balance — total={total}, pos={pos} ({pos/total:.1%}), neg={neg} ({neg/total:.1%})")

def build_pipeline() -> Pipeline:
    """
    Build an sklearn Pipeline:
      - GenreBinarizer() for list[str] "genre_list"
      - OneHotEncoder for "type"
      - StandardScaler for numeric
      - TfidfVectorizer on raw "synopsis" text
      - RandomForestClassifier
    """
    pre = ColumnTransformer(
        transformers=[
            ("genres", GenreBinarizer(), "genre_list"),
            ("type", OneHotEncoder(sparse_output=False, handle_unknown="ignore"), ["type"]),
            ("scale", StandardScaler(), ["mean_score", "chapters", "volumes"]),
            ("synopsis", TfidfVectorizer(max_features=CONFIG.tfidf_max_features), "synopsis"),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )

    clf = RandomForestClassifier(
        n_estimators=CONFIG.n_estimators,
        random_state=CONFIG.random_state,
        n_jobs=-1,
    )

    pipe = Pipeline(
        steps=[
            ("preprocess", pre),
            ("classifier", clf),
        ]
    )
    return pipe

def train_model(df: pd.DataFrame) -> Pipeline:
    """
    Train/test split with stratification; fall back gracefully if the minority class is too small.
    Prints classification_report and ROC-AUC (if possible).
    """
    features = df[["type", "genre_list", "mean_score", "chapters", "volumes", "synopsis"]]
    labels = df["label"].astype(int)

    _print_class_balance(labels)

    # Guard: need at least one sample in each class
    classes = labels.unique().tolist()
    if len(classes) < 2:
        raise ValueError("Need at least two classes to train. Collected only: " + str(classes))

    # Stratified split (fallback to regular split if it fails due to tiny minority)
    try:
        X_train, X_test, y_train, y_test = train_test_split(
            features,
            labels,
            test_size=CONFIG.test_size,
            stratify=labels,
            random_state=CONFIG.random_state,
        )
    except ValueError:
        # Fallback: no stratify
        X_train, X_test, y_train, y_test = train_test_split(
            features,
            labels,
            test_size=CONFIG.test_size,
            random_state=CONFIG.random_state,
        )

    pipeline = build_pipeline()

    # Silence benign sklearn warnings about feature names/unknown categories
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)

    print("\n=== Evaluation ===")
    print(classification_report(y_test, y_pred, digits=3))
    try:
        if hasattr(pipeline, "predict_proba"):
            y_proba = pipeline.predict_proba(X_test)[:, 1]
            auc = roc_auc_score(y_test, y_proba)
            print(f"ROC-AUC: {auc:.3f}")
    except Exception:
        pass

    # Stamp version for runtime guard
    setattr(pipeline, "version_", CONFIG.model_version)
    return pipeline

# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    df = extract_labeled_data()
    if df.empty:
        raise SystemExit("No labeled rows found. Add a few ratings/drops to generate training data.")

    # Persist the supervised dataset for inspection
    pd.DataFrame(df).to_csv(LABELED_DATA_FILE, index=False, encoding="utf-8")
    print(f"📁 Exported {len(df)} labeled entries to {LABELED_DATA_FILE}")

    model = train_model(df)

    # Ensure parent directory exists and save
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"✅ Model trained and saved to {MODEL_PATH} (version={CONFIG.model_version})")
