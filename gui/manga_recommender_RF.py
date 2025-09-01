# app_commented.py
# Full-dataset manga recommender GUI.
# This version adds clear, resume-ready comments explaining structure, choices, and tradeoffs.

from __future__ import annotations

import io
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import joblib
import numpy as np
import pandas as pd
import requests
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from PIL import Image, ImageTk, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from definitions import DB_PATH, MODEL_PATH, GENRE_BLACKLIST  # centralized project constants

# -----------------------------------------------------------------------------
# Logging: structured logs help during demos / debugging and look professional
# -----------------------------------------------------------------------------
logger = logging.getLogger("manga_recommender")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# -----------------------------------------------------------------------------
# Configuration (frozen dataclass = immutable runtime config)
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class AppConfig:
    page_size: int = 50                 # how many rows to render per UI page
    http_timeout_sec: int = 5           # network timeout for cover downloads
    img_size: Tuple[int, int] = (100, 140)
    predict_batch_size: int = 5_000     # batch size for model inference to limit RAM spikes
    user_agent: str = "MangaRecommender/1.0"
    expected_model_version: str = "rf-v1"  # stamped in training as pipeline.version_

CONFIG = AppConfig()

# Read-status display wiring
READ_CHOICES: List[Tuple[str, int]] = [
    ("0 - Unread", 0),
    ("-2 - Read Unknown", -2),
    ("-1 - Finished", -1),
]
DISP_TO_VAL = {d: v for d, v in READ_CHOICES}
VAL_TO_DISP = {v: d for d, v in READ_CHOICES}

# Case-insensitive genre blacklist used for both filtering and feature cleaning
BL_LOWER = {g.lower() for g in GENRE_BLACKLIST}

# Columns the model pipeline expects in this order
REQUIRED_COLS = ["type", "genre_list", "mean_score", "chapters", "volumes", "synopsis"]

# -----------------------------------------------------------------------------
# Helper functions / policy
# -----------------------------------------------------------------------------
def clean_genres_for_inference(raw_list: Optional[List[str]]) -> List[str]:
    """Remove blacklisted genres so the encoder never sees them (prevents unknown-category warnings)."""
    return [g.strip() for g in (raw_list or []) if g and g.strip().lower() not in BL_LOWER]

def has_blacklisted(genres_str: Optional[str]) -> bool:
    """Return True if any blacklisted genre appears in a comma-separated field (case-insensitive)."""
    if not genres_str:
        return False
    return any(g.strip().lower() in BL_LOWER for g in genres_str.split(","))

# -----------------------------------------------------------------------------
# Main App
# -----------------------------------------------------------------------------
class RecommendationApp:
    """Tkinter GUI that ranks the full manga table by model score and paginates results."""

    def __init__(self, root: tk.Tk):
        # Basic window setup
        self.root = root
        self.root.title("Manga Recommender (All Ranked)")

        # ---------------- HTTP session (retries + UA) ----------------
        # Using a persistent session with retry adapter makes image loads more reliable.
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": CONFIG.user_agent})
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.http.mount("http://", adapter)
        self.http.mount("https://", adapter)

        # Cache PhotoImage objects by mal_id to avoid re-fetching and to keep references alive
        self.img_cache: Dict[int, ImageTk.PhotoImage] = {}

        # ---------------- Load model & DB connections ----------------
        self.model = self._load_model()
        self.conn, self.cursor = self._open_db()

        # ---------------- UI state ----------------
        self.selected_type = tk.StringVar(value="")      # optional filter by type
        self.include_rated = tk.BooleanVar(value=False)  # by default, hide already-rated items
        self.include_not_interested = tk.BooleanVar(value=False)  # hide explicit opt-outs

        self.ranked_df: Optional[pd.DataFrame] = None  # the current ranked dataset
        self.page = 0                                   # active page index

        # Build static UI widgets
        self._build_controls()
        self._build_container()

        # Initial full ranking across the dataset
        self.refresh_and_rank()

        # Ensure clean shutdown on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------ Initialization helpers ------------------
    def _load_model(self):
        """Load the persisted sklearn Pipeline; warn if version stamp differs."""
        try:
            model = joblib.load(MODEL_PATH)
            ver = getattr(model, "version_", None)
            if ver is not None and ver != CONFIG.expected_model_version:
                # Non-fatal warning helps align training/runtime versions in a professional way.
                logger.warning("Model version mismatch: %s != %s", ver, CONFIG.expected_model_version)
            logger.info("Model loaded from %s", MODEL_PATH)
            return model
        except Exception as e:
            logger.exception("Failed to load model from %s", MODEL_PATH)
            messagebox.showerror("Model Load Error", f"Failed to load model: {e}")
            raise

    def _open_db(self):
        """Open SQLite safely and return (connection, cursor)."""
        try:
            conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
            cursor = conn.cursor()
            logger.info("Connected to DB %s", DB_PATH)
            return conn, cursor
        except Exception as e:
            logger.exception("Failed to connect to DB at %s", DB_PATH)
            messagebox.showerror("Database Error", f"Failed to open database: {e}")
            raise

    # ------------------ UI construction ------------------
    def _build_controls(self) -> None:
        """Top control bar: filters + re-rank button; and a nav bar for pagination."""
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=6)

        ttk.Label(bar, text="Type:").pack(side="left")
        type_dd = ttk.Combobox(
            bar, textvariable=self.selected_type,
            values=["", "Manga", "Manhwa", "Manhua"],
            state="readonly", width=10
        )
        type_dd.pack(side="left", padx=(4, 12))
        type_dd.bind("<<ComboboxSelected>>", lambda _e: self._filters_changed())

        ttk.Checkbutton(bar, text="Include rated", variable=self.include_rated,
                        command=self._filters_changed).pack(side="left")
        ttk.Checkbutton(bar, text="Include not_interested",
                        variable=self.include_not_interested,
                        command=self._filters_changed).pack(side="left", padx=(8, 0))

        ttk.Button(bar, text="Re-rank All", command=self.refresh_and_rank).pack(side="right")

        # Pagination controls
        nav = ttk.Frame(self.root)
        nav.pack(fill="x", padx=8, pady=(0, 6))
        self.prev_btn = ttk.Button(nav, text="◀ Prev", command=self.prev_page)
        self.next_btn = ttk.Button(nav, text="Next ▶", command=self.next_page)
        self.page_lbl = ttk.Label(nav, text="Page 1")
        self.prev_btn.pack(side="left")
        self.page_lbl.pack(side="left", padx=8)
        self.next_btn.pack(side="left")

    def _build_container(self) -> None:
        """Scrollable container area where rows render."""
        self.container = ttk.Frame(self.root)
        self.container.pack(fill="both", expand=True)

    # ------------------ Event handlers ------------------
    def _filters_changed(self) -> None:
        """Re-run ranking when any filter checkbox or type dropdown changes."""
        self.page = 0
        self.refresh_and_rank()

    def prev_page(self) -> None:
        """Navigate to the previous page if available."""
        if self.page > 0:
            self.page -= 1
            self.render_current_page()

    def next_page(self) -> None:
        """Navigate to the next page if available."""
        if self.ranked_df is None:
            return
        max_page = (len(self.ranked_df) - 1) // CONFIG.page_size
        if self.page < max_page:
            self.page += 1
            self.render_current_page()

    # ------------------ Core: load, score, and sort ------------------
    def refresh_and_rank(self) -> None:
        """
        Pull ALL matching rows; drop blacklisted genres; compute scores on ALL rows
        (batched predict_proba for memory safety); sort descending by model score.
        """
        # Lightweight progress text
        self._clear_container()
        ttk.Label(self.container, text="Ranking the entire dataset…").pack(pady=12)
        self.root.update_idletasks()

        # Build dynamic WHERE clause based on filters
        where: List[str] = []
        params: List = []
        if self.selected_type.get():
            where.append("type = ?")
            params.append(self.selected_type.get())
        if not self.include_rated.get():
            where.append("user_score IS NULL")
        if not self.include_not_interested.get():
            where.append("not_interested = 0")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT mal_id, title, type, genres, mean_score, chapters, volumes,
                   synopsis, images, published_date
            FROM manga
            {where_sql}
            ORDER BY mal_id ASC
        """

        # Pull rows
        try:
            self.cursor.execute(sql, params)
            rows = self.cursor.fetchall()
        except sqlite3.DatabaseError as e:
            logger.exception("DB query failed")
            messagebox.showerror("Database Error", str(e))
            self._clear_container()
            return

        # Frame the results with explicit column names
        df = pd.DataFrame(
            rows,
            columns=[
                "mal_id", "title", "type", "genres", "mean_score", "chapters", "volumes",
                "synopsis", "images", "published_date",
            ],
        )

        # Drop any titles that contain blacklisted genres (belt-and-suspenders with model-side cleaning)
        df = df[~df["genres"].fillna("").apply(has_blacklisted)].reset_index(drop=True)
        logger.info("Rows after blacklist filter: %d", len(df))

        if df.empty:
            # User feedback if filters eliminate all content
            self.ranked_df = df
            self.page = 0
            self._render_message("No titles match current filters. Try enabling 'Include rated' or changing Type.")
            return

        # --- Feature preparation (must align with training pipeline inputs) ---
        df = df.copy()
        df["genre_list"] = (
            df["genres"]
            .fillna("")
            .apply(lambda g: [x.strip() for x in g.split(",") if x.strip()])
            .apply(clean_genres_for_inference)  # remove blacklist from feature list too
        )
        df["mean_score"] = df["mean_score"].fillna(0)
        df["chapters"] = df["chapters"].fillna(0)
        df["volumes"] = df["volumes"].fillna(0)
        df["synopsis"] = df["synopsis"].fillna("")

        # Defensive check: ensure the pipeline-required columns exist
        missing = [c for c in REQUIRED_COLS if c not in df.columns]
        if missing:
            logger.error("Model input missing columns: %s", missing)
            messagebox.showerror("Model Error", f"Missing model columns: {missing}")
            self.ranked_df = pd.DataFrame()
            self.page = 0
            self._clear_container()
            return

        # --- Batched inference across the ENTIRE dataset ---
        try:
            scores = np.empty(len(df), dtype=float)
            for start in range(0, len(df), CONFIG.predict_batch_size):
                end = min(start + CONFIG.predict_batch_size, len(df))
                batch = df.iloc[start:end]
                proba = self.model.predict_proba(batch[REQUIRED_COLS])[:, 1]
                scores[start:end] = proba
            df["score"] = scores
        except Exception as e:
            logger.exception("Prediction failed on full dataset")
            messagebox.showerror("Model Error", f"Prediction failed: {e}")
            self.ranked_df = pd.DataFrame()
            self.page = 0
            self._clear_container()
            return

        # Sort highest-scoring recommendations first
        self.ranked_df = df.sort_values("score", ascending=False).reset_index(drop=True)
        self.page = 0
        self.render_current_page()

    # ------------------ Rendering helpers ------------------
    def _clear_container(self) -> None:
        """Remove all child widgets from the container before re-rendering."""
        for w in self.container.winfo_children():
            w.destroy()

    def _render_message(self, text: str) -> None:
        """Show a single message line in the container (e.g., empty state)."""
        self._clear_container()
        ttk.Label(self.container, text=text).pack(pady=12)

    def render_current_page(self) -> None:
        """Render the current page of ranked results as rows with image, facts, and synopsis."""
        self._clear_container()

        if self.ranked_df is None or self.ranked_df.empty:
            self._render_message("No rows to display.")
            self.page_lbl.config(text="Page 0")
            self.prev_btn.state(["disabled"])
            self.next_btn.state(["disabled"])
            return

        start = self.page * CONFIG.page_size
        end = start + CONFIG.page_size
        page_df = self.ranked_df.iloc[start:end]

        for _, row in page_df.iterrows():
            frame = ttk.Frame(self.container, padding=10)
            frame.pack(fill="x")

            # Cover image: placeholder text until we have it; cache by mal_id
            img_label = tk.Label(frame, cursor="hand2", text="[Loading image]", takefocus=True)
            img_label.pack(side="left", padx=5)

            mal_id = int(row["mal_id"])
            if mal_id in self.img_cache:
                # Use cached PhotoImage to avoid GC and refetch
                img_label.config(image=self.img_cache[mal_id], text="")
                img_label.image = self.img_cache[mal_id]
            else:
                # Greedy but safe image loader (handles JSON & HTTP errors gracefully)
                img = self._safe_photoimage_from_images_json(row.get("images") or "")
                if img is not None:
                    self.img_cache[mal_id] = img
                    img_label.config(image=img, text="")
                    img_label.image = img
                else:
                    img_label.config(text="[No Image]")

            # Click image to open details editor
            img_label.bind("<Button-1>", lambda e, mid=mal_id: self.open_details(mid))

            # A small "extra" line based on what fields are present
            chapters = int(row.get("chapters") or 0)
            volumes = int(row.get("volumes") or 0)
            if chapters:
                extra_info = f"Chapters: {chapters}"
            elif volumes:
                extra_info = f"Volumes: {volumes}"
            else:
                pub = row.get("published_date")
                extra_info = f"Started in: {str(pub)[:4]}" if pub else "Start date unknown"

            # Text block with key fields + model score
            info_text = (
                f"{row['title']} (id={mal_id})\n"
                f"Type: {row['type']} | Genres: {row['genres']}\n"
                f"Match Score: {row['score']:.4f}\n"
                f"{extra_info}"
            )
            tk.Label(frame, text=info_text, justify="left", font=("Arial", 10), anchor="w").pack(side="left", padx=10)

            # Read-only synopsis (scrollable, avoids giant labels)
            synopsis_box = scrolledtext.ScrolledText(frame, height=5, width=50, wrap=tk.WORD)
            synopsis_box.insert(tk.END, row.get("synopsis") or "")
            synopsis_box.config(state=tk.DISABLED)
            synopsis_box.pack(side="left", padx=5)

        # Update pagination widgets
        max_page = (len(self.ranked_df) - 1) // CONFIG.page_size
        self.page_lbl.config(text=f"Page {self.page + 1} / {max_page + 1}")
        self.prev_btn.state(["!disabled"] if self.page > 0 else ["disabled"])
        self.next_btn.state(["!disabled"] if self.page < max_page else ["disabled"])

    def _safe_photoimage_from_images_json(self, images_json: str) -> Optional[ImageTk.PhotoImage]:
        """
        Decode the Jikan-style images JSON and fetch/resize with retrying HTTP session.
        Returns a Tk PhotoImage or None if any step fails.
        """
        try:
            data = json.loads(images_json or "{}")
            url = data.get("jpg", {}).get("image_url")
            if not url:
                return None
            resp = self.http.get(url, timeout=CONFIG.http_timeout_sec)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            img = img.resize(CONFIG.img_size, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except (json.JSONDecodeError, KeyError, requests.RequestException, UnidentifiedImageError) as e:
            logger.info("Image load failed: %s", e)
            return None

    # ------------------ Detail editor dialog ------------------
    def open_details(self, mal_id: int) -> None:
        """
        Open a detail window for a single title; allow updating user_score, read, and not_interested.
        On save, we re-rank to reflect the new label/filter state.
        """
        try:
            self.cursor.execute(
                """
                SELECT title, synopsis, user_score, read, not_interested
                FROM manga WHERE mal_id = ?
                """,
                (mal_id,),
            )
            result = self.cursor.fetchone()
        except sqlite3.DatabaseError as e:
            logger.exception("DB error on open_details")
            messagebox.showerror("Database Error", f"Unable to load details: {e}")
            return

        if not result:
            return

        title, synopsis, user_score, read, not_interested = result

        # Basic dialog layout
        win = tk.Toplevel(self.root)
        win.title(f"Details for: {title}")
        win.geometry("520x420")

        tk.Label(win, text=f"Title: {title}", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=(10, 5))
        tk.Label(win, text="Synopsis:").pack(anchor="w", padx=10)
        synopsis_box = scrolledtext.ScrolledText(win, wrap=tk.WORD, height=6)
        synopsis_box.insert(tk.END, synopsis or "")
        synopsis_box.config(state=tk.DISABLED)
        synopsis_box.pack(fill="both", expand=False, padx=10)

        # User score: provide a sensible default if none
        score_default = user_score if user_score and 1 <= int(user_score) <= 10 else 7
        score_var = tk.IntVar(value=int(score_default))
        tk.Label(win, text="Your Score (1-10):").pack(anchor="w", padx=10)
        tk.Spinbox(win, from_=1, to=10, textvariable=score_var, width=6).pack(anchor="w", padx=10)

        # Read status dropdown from enum mapping above
        read_val = int(read) if read is not None else 0
        read_var = tk.StringVar(value=VAL_TO_DISP.get(read_val, "0 - Unread"))
        tk.Label(win, text="Read Status:").pack(anchor="w", padx=10)
        ttk.Combobox(
            win, textvariable=read_var,
            values=[d for d, _ in READ_CHOICES],
            state="readonly", width=18,
        ).pack(anchor="w", padx=10)

        # Not interested toggle
        interested_var = tk.BooleanVar(value=bool(not_interested))
        tk.Checkbutton(win, text="Not Interested", variable=interested_var).pack(anchor="w", padx=10, pady=5)

        # Inline callback to persist changes, then refresh the main ranking
        def save_changes():
            try:
                self.cursor.execute(
                    """
                    UPDATE manga
                    SET user_score = ?, read = ?, not_interested = ?
                    WHERE mal_id = ?
                    """,
                    (int(score_var.get()), int(DISP_TO_VAL[read_var.get()]), int(interested_var.get()), mal_id),
                )
                self.conn.commit()
            except sqlite3.DatabaseError as e:
                logger.exception("DB error on save_changes")
                messagebox.showerror("Database Error", f"Save failed: {e}")
                return
            finally:
                win.destroy()
                self.refresh_and_rank()

        tk.Button(win, text="Save", command=save_changes).pack(pady=10)

    # ------------------ Shutdown / cleanup ------------------
    def on_close(self) -> None:
        """Close network + DB resources cleanly and destroy the window."""
        try:
            self.http.close()
        except Exception:
            pass
        try:
            if self.cursor:
                self.cursor.close()
        except Exception:
            pass
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    # Standard Tkinter bootstrap
    root = tk.Tk()
    app = RecommendationApp(root)
    root.mainloop()
