import numpy as np
import pytest

from manga_recommendation.utils import GenreBinarizer
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer


REQUIRED = ["type", "genre_list", "mean_score", "chapters", "volumes", "synopsis"]


def build_pipeline():
    """Inline builder to match training script pipeline."""
    preprocessor = ColumnTransformer(transformers=[
        ("genres", GenreBinarizer(), "genre_list"),
        ("type", OneHotEncoder(sparse_output=False, handle_unknown="ignore"), ["type"]),
        ("scale", StandardScaler(), ["mean_score", "chapters", "volumes"]),
        ("synopsis", TfidfVectorizer(max_features=50), "synopsis"),
    ])

    return Pipeline([
        ("preprocess", preprocessor),
        ("classifier", RandomForestClassifier(n_estimators=10, random_state=42))
    ])


def test_pipeline_fit_and_predict_proba(tiny_supervised_df):
    X, y = tiny_supervised_df

    # Ensure required columns exist
    for col in REQUIRED:
        assert col in X.columns

    pipe = build_pipeline()
    pipe.fit(X, y)

    # Must support predict_proba for ranking
    assert hasattr(pipe, "predict_proba")

    proba = pipe.predict_proba(X)
    assert proba.shape == (len(X), 2)
    assert np.all((proba >= 0) & (proba <= 1))
