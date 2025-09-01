from __future__ import annotations

import io
import json
import logging
import os
import random
import sqlite3
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import requests
import tkinter as tk
from PIL import Image, ImageTk, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from tkinter import messagebox, scrolledtext, ttk
from urllib3.util.retry import Retry

from definitions import DB_PATH, SKIPPED_FILE, GENRE_BLACKLIST

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("manga_rater")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# -------------------------
# Config
# -------------------------
@dataclass(frozen=True)
class AppConfig:
    http_timeout: int = 5
    img_size: Tuple[int, int] = (150, 220)
    user_agent: str = "MangaRater/1.0"
    sample_batch: int = 20  # how many items to enqueue per refresh

CONFIG = AppConfig()

READ_CHOICES: List[Tuple[str, int]] = [
    ("0 - Unread", 0),
    ("-2 - Read but not finished", -2),
    ("-1 - Finished", -1),
]
READ_DISP_TO_VAL = {d: v for d, v in READ_CHOICES}
BL_LOWER = {g.lower() for g in GENRE_BLACKLIST}


def _split_genres(s: Optional[str]) -> List[str]:
    """Split a comma-separated genre string, trim, and drop empties."""
    if not s:
        return []
    return [g.strip() for g in s.split(",") if g.strip()]


def _has_blacklisted(genres_str: Optional[str]) -> bool:
    """Return True if any blacklisted genre appears (case-insensitive)."""
    return any(g.lower() in BL_LOWER for g in _split_genres(genres_str))


class MangaRater:
    """Desktop app to rate random manga by selected genre & type."""

    def __init__(self) -> None:
        # --- DB
        try:
            self.conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
            self.cursor = self.conn.cursor()
            logger.info("Connected to DB %s", DB_PATH)
        except Exception as e:
            logger.exception("Failed to connect DB")
            raise

        # --- HTTP session (retries + UA)
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": CONFIG.user_agent})
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.http.mount("http://", adapter)
        self.http.mount("https://", adapter)

        # --- State
        self.shown_ids: set[int] = set()
        self.manga_queue: List[Tuple] = []
        self.current_manga: Optional[Tuple] = None
        self.skipped = self.load_skipped()

        # --- UI
        self.root = tk.Tk()
        self.root.title("Rate Random Manga by Genre")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        top_frame = tk.Frame(self.root)
        top_frame.pack(pady=5, fill=tk.X)

        self.type_var = tk.StringVar(value="Manga")
        tk.Label(top_frame, text="Type:").pack(side=tk.LEFT, padx=(10, 0))
        self.type_dropdown = ttk.Combobox(top_frame, textvariable=self.type_var, state="readonly", width=10)
        self.type_dropdown["values"] = ["Manga", "Manhwa", "Manhua"]
        self.type_dropdown.pack(side=tk.LEFT, padx=5)
        self.type_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_random_manga(reset=True))

        self.genre_var = tk.StringVar()
        tk.Label(top_frame, text="Genre:").pack(side=tk.LEFT)
        self.genre_dropdown = ttk.Combobox(top_frame, textvariable=self.genre_var, state="readonly", width=24)
        self.genre_dropdown.pack(side=tk.LEFT, padx=4)
        self.genre_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_random_manga(reset=True))

        self.read_count_label = tk.Label(top_frame, text="Read: 0 | Not Interested: 0")
        self.read_count_label.pack(side=tk.RIGHT, padx=10)

        self.cover_label = tk.Label(self.root)
        self.cover_label.pack(pady=5)

        self.info_label = tk.Label(self.root, text="", font=("Arial", 12), wraplength=480, justify="left", anchor="w")
        self.info_label.pack(padx=10, pady=6, fill=tk.X)

        self.synopsis_box = scrolledtext.ScrolledText(self.root, height=8, width=70, wrap=tk.WORD)
        self.synopsis_box.pack(padx=10, pady=5)
        self.synopsis_box.config(state=tk.DISABLED)

        # Rating controls
        self.score_var = tk.IntVar(value=0)
        tk.Label(self.root, text="Your Score (1-10):").pack()
        tk.Spinbox(self.root, from_=1, to=10, textvariable=self.score_var, width=5).pack()

        self.read_var = tk.StringVar(value="0 - Unread")
        tk.Label(self.root, text="Read Status:").pack(pady=(5, 0))
        self.read_dropdown = ttk.Combobox(self.root, textvariable=self.read_var, state="readonly", width=28)
        self.read_dropdown["values"] = [d for d, _ in READ_CHOICES]
        self.read_dropdown.pack(pady=2)

        self.drop_var = tk.StringVar(value="Not Dropped")
        tk.Label(self.root, text="Dropped Status:").pack(pady=(5, 0))
        self.drop_dropdown = ttk.Combobox(self.root, textvariable=self.drop_var, state="readonly", width=28)
        self.drop_dropdown["values"] = ["Not Dropped", "Dropped", "Dropped but would pick back up"]
        self.drop_dropdown.pack(pady=2)

        self.not_interested_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.root, text="Not Interested", variable=self.not_interested_var).pack(pady=5)

        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Save & Next", command=self.save_and_next).grid(row=0, column=0, padx=6)
        ttk.Button(button_frame, text="Skip", command=self.skip_and_next).grid(row=0, column=1, padx=6)

        # Populate genres (excluding blacklisted-only values) and kick off
        self.genre_dropdown["values"] = self.get_all_genres()
        if self.genre_dropdown["values"]:
            self.genre_var.set(self.genre_dropdown["values"][0])
            self.load_random_manga(reset=True)
        else:
            messagebox.showinfo("Setup", "No genres found in database.")

        self.root.mainloop()

    # -------------------------
    # Persistence of skipped
    # -------------------------
    def load_skipped(self) -> set[int]:
        if os.path.exists(SKIPPED_FILE):
            try:
                with open(SKIPPED_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {int(x) for x in data}
            except Exception as e:
                logger.warning("Failed to load skipped file: %s", e)
        return set()

    def save_skipped(self) -> None:
        try:
            with open(SKIPPED_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(self.skipped), f)
        except Exception as e:
            logger.warning("Failed to save skipped file: %s", e)

    # -------------------------
    # DB helpers
    # -------------------------
    def get_all_genres(self) -> List[str]:
        """Collect all distinct genres, filter out blacklist-only tokens, return sorted."""
        try:
            self.cursor.execute("SELECT genres FROM manga")
            genres: set[str] = set()
            for (gstr,) in self.cursor.fetchall():
                for g in _split_genres(gstr):
                    if g and g.lower() not in BL_LOWER:
                        genres.add(g)
            vals = sorted(genres)
            logger.info("Discovered %d distinct genres (post-blacklist)", len(vals))
            return vals
        except sqlite3.DatabaseError as e:
            logger.exception("Genre query failed")
            messagebox.showerror("Database Error", f"Failed to load genres: {e}")
            return []

    def update_read_count(self) -> None:
        try:
            self.cursor.execute("SELECT COUNT(*) FROM manga WHERE read != 0")
            read_count = self.cursor.fetchone()[0]
            self.cursor.execute("SELECT COUNT(*) FROM manga WHERE not_interested = 1")
            not_interested_count = self.cursor.fetchone()[0]
            self.read_count_label.config(text=f"Read: {read_count} | Not Interested: {not_interested_count}")
        except sqlite3.DatabaseError as e:
            logger.warning("Count update failed: %s", e)

    # -------------------------
    # Core flow
    # -------------------------
    def load_random_manga(self, reset: bool = False) -> None:
        """Refresh queue with a random sample of candidates for the chosen genre/type."""
        if reset:
            self.shown_ids.clear()
            self.manga_queue.clear()

        genre = self.genre_var.get()
        type_ = self.type_var.get()

        # SQL pre-filter + Python blacklist guard (belt-and-suspenders)
        try:
            self.cursor.execute(
                """
                SELECT mal_id, title, mean_score, genres, user_score, read, images, synopsis
                FROM manga
                WHERE type = ?
                  AND (user_score IS NULL OR user_score = '')
                  AND not_interested = 0
                  AND genres LIKE ?
                """,
                (type_, f"%{genre}%"),
            )
            rows = []
            for r in self.cursor.fetchall():
                mal_id, title, mean_score, genres, user_score, read, images, synopsis = r
                if (
                    mal_id not in self.shown_ids
                    and mal_id not in self.skipped
                    and not _has_blacklisted(genres)  # exclude blacklisted titles
                ):
                    rows.append(r)

            if not rows:
                self.manga_queue.clear()
            else:
                k = min(CONFIG.sample_batch, len(rows))
                # Randomly sample without replacement
                self.manga_queue.extend(random.sample(rows, k))

            logger.info("Queued %d candidates (genre=%s, type=%s)", len(self.manga_queue), genre, type_)
            self.show_next_manga()
        except sqlite3.DatabaseError as e:
            logger.exception("DB query failed in load_random_manga")
            messagebox.showerror("Database Error", f"Query failed: {e}")

    def show_next_manga(self) -> None:
        while not self.manga_queue:
            # Try to refill once; if still empty, inform and bail.
            self.load_random_manga()
            if not self.manga_queue:
                messagebox.showinfo("Notice", "No more manga available for this genre and type.")
                return

        self.current_manga = self.manga_queue.pop(0)
        mal_id, title, score, genres, _, _, images_json, synopsis = self.current_manga
        self.shown_ids.add(mal_id)

        # Secure JSON parse (no eval) + resilient HTTP
        img = None
        try:
            data = json.loads(images_json or "{}")
            image_url = (data.get("jpg") or {}).get("image_url")
            if image_url:
                resp = self.http.get(image_url, timeout=CONFIG.http_timeout)
                resp.raise_for_status()
                img_obj = Image.open(io.BytesIO(resp.content))
                img_obj = img_obj.resize(CONFIG.img_size, Image.Resampling.LANCZOS)
                img = ImageTk.PhotoImage(img_obj)
        except (json.JSONDecodeError, UnidentifiedImageError, requests.RequestException) as e:
            logger.info("Cover load failed for id=%s: %s", mal_id, e)

        if img is not None:
            self.cover_label.config(image=img, text="")
            self.cover_label.image = img
        else:
            self.cover_label.config(image=None, text="[No Image]")
            self.cover_label.image = None

        self.info_label.config(
            text=f"Title: {title}\nMAL Score: {score if score is not None else 'N/A'}\nGenres: {genres or 'N/A'}"
        )

        self.synopsis_box.config(state=tk.NORMAL)
        self.synopsis_box.delete(1.0, tk.END)
        self.synopsis_box.insert(tk.END, synopsis or "[No synopsis available]")
        self.synopsis_box.config(state=tk.DISABLED)

        # Reset inputs
        self.score_var.set(0)
        self.read_var.set("0 - Unread")
        self.drop_var.set("Not Dropped")
        self.not_interested_var.set(False)
        self.update_read_count()

    def save_and_next(self) -> None:
        if not self.current_manga:
            return
        mal_id = int(self.current_manga[0])
        score = int(self.score_var.get() or 0)
        read_value = READ_DISP_TO_VAL.get(self.read_var.get(), 0)
        dropped_value = {
            "Not Dropped": 0,
            "Dropped": 1,
            "Dropped but would pick back up": 2,
        }.get(self.drop_var.get(), 0)
        not_interested = 1 if self.not_interested_var.get() else 0

        try:
            self.cursor.execute(
                """
                UPDATE manga
                SET user_score = ?, read = ?, dropped = ?, not_interested = ?
                WHERE mal_id = ?
                """,
                (score if score > 0 else None, read_value, dropped_value, not_interested, mal_id),
            )
            self.conn.commit()
            logger.info("Saved rating for id=%s (score=%s, read=%s, dropped=%s, not_int=%s)",
                        mal_id, score, read_value, dropped_value, not_interested)
        except sqlite3.DatabaseError as e:
            logger.exception("Save failed")
            messagebox.showerror("Database Error", f"Save failed: {e}")
            return

        self.show_next_manga()

    def skip_and_next(self) -> None:
        if not self.current_manga:
            return
        mal_id = int(self.current_manga[0])
        self.skipped.add(mal_id)
        self.save_skipped()
        logger.info("Skipped id=%s", mal_id)
        self.show_next_manga()

    # -------------------------
    # Shutdown
    # -------------------------
    def on_close(self) -> None:
        try:
            self.save_skipped()
        except Exception:
            pass
        try:
            self.http.close()
        except Exception:
            pass
        try:
            self.cursor.close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    MangaRater()
