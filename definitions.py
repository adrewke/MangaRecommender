# definitions.py
"""
Centralized configuration for the Manga Recommendation system.
Uses pathlib for consistent, cross-platform paths.
"""

from pathlib import Path

# -------------------------
# Project root
# -------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# -------------------------
# Data / Model paths
# -------------------------
DB_PATH: Path = PROJECT_ROOT / "db" / "manga.db"
MANGA_JSON: Path = PROJECT_ROOT / "data" / "manga_dataset.json"
MODEL_PATH: Path = PROJECT_ROOT / "data" / "rf_manga_model.pkl"
SKIPPED_FILE: Path = PROJECT_ROOT / "data" / "skipped.json"
WEIGHTS_FILE: Path = PROJECT_ROOT / "data" / "weights.json"
LABELED_DATA_FILE: Path = PROJECT_ROOT / "data" / "labeled_data.csv"

# -------------------------
# Constants
# -------------------------
FIELDS: str = "title,mean,genres,status,num_volumes"
DEFAULT_OUTPUT_FILE: Path = PROJECT_ROOT / "data" / "manga_dataset.json"

# Genres we explicitly exclude from training/recommendations
GENRE_BLACKLIST = {
    "Avant Garde",
    "Boys Love",
    "Hentai",
}
