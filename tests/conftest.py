import pytest
import pandas as pd

@pytest.fixture
def tiny_supervised_df():
    """Small, deterministic dataframe for pipeline smoke tests."""
    return pd.DataFrame(
        [
            {
                "type": "Manga",
                "genre_list": ["Action", "Adventure"],
                "mean_score": 7.8,
                "chapters": 100,
                "volumes": 20,
                "synopsis": "A hero starts an adventure."
            },
            {
                "type": "Manga",
                "genre_list": ["Romance"],
                "mean_score": 5.5,
                "chapters": 30,
                "volumes": 6,
                "synopsis": "Two students in love at school."
            },
            {
                "type": "Manhwa",
                "genre_list": ["Action", "Fantasy"],
                "mean_score": 8.6,
                "chapters": 80,
                "volumes": 15,
                "synopsis": "Dungeon crawling and leveling."
            },
            {
                "type": "Manhua",
                "genre_list": ["Comedy"],
                "mean_score": 6.2,
                "chapters": 25,
                "volumes": 5,
                "synopsis": "Slice of life comedic events."
            },
        ]
    ), pd.Series([1, 0, 1, 0], name="label")
