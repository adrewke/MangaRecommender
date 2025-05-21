import os
FIELDS = "title,mean,genres,status,num_volumes"
DEFAULT_OUTPUT_FILE = "data/manga_dataset.json"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(PROJECT_ROOT, "db", "manga.db")
MANGA_JSON = os.path.join(PROJECT_ROOT, "data", "manga_dataset.json")
MODEL_PATH = os.path.join(PROJECT_ROOT, "data", "rf_manga_model.pkl")
SKIPPED_FILE = os.path.join(PROJECT_ROOT, "data", "skipped.json")
WEIGHTS_FILE = os.path.join(PROJECT_ROOT, "data", "weights.json")
LABELED_DATA_FILE = os.path.join(PROJECT_ROOT, "data", "labeled_data.csv")