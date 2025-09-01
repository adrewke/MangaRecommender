import numpy as np
import pandas as pd
from manga_recommendation.utils import GenreBinarizer

def test_genre_binarizer_fit_transform_basic():
    X = pd.Series([["Action", "Romance"], ["Romance"], ["Fantasy"], []], name="genre_list")
    gb = GenreBinarizer()
    Xt = gb.fit_transform(X)
    # Columns should include all seen genres
    cols = list(gb.classes_)
    assert set(cols) == {"Action", "Romance", "Fantasy"}
    # Shape matches samples x classes
    assert Xt.shape == (4, len(cols))
    # Check one-hot presence
    row0 = Xt[0].toarray().ravel() if hasattr(Xt[0], "toarray") else np.array(Xt[0]).ravel()
    assert row0.sum() == 2  # Action + Romance for first row

def test_genre_binarizer_handles_unknown_on_transform():
    X_train = pd.Series([["Action"], ["Romance"]], name="genre_list")
    X_test = pd.Series([["Action", "UnknownTag"]], name="genre_list")
    gb = GenreBinarizer()
    gb.fit(X_train)
    Xt = gb.transform(X_test)
    # UnknownTag should be ignored (no crash, no extra column)
    assert Xt.shape[1] == len(gb.classes_)
