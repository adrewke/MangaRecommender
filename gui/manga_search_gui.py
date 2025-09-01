# manga_search_resume_ready.py
# Search & review tool for a manga SQLite library.
# Polished for resume: type hints, structured logging, persistent DB & HTTP sessions,
# safe JSON parsing, configurable blacklist/filters, robust sorting, and tidy resource cleanup.

from __future__ import annotations

import io
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import requests
import tkinter as tk
from PIL import Image, ImageTk, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from tkinter import ttk, scrolledtext
from urllib3.util.retry import Retry

from definitions import DB_PATH, GENRE_BLACKLIST  # expects GENRE_BLACKLIST to be defined

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("manga_search")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# -------------------------
# Config
# -------------------------
@dataclass(frozen=True)
class AppConfig:
    http_timeout: int = 5
    img_size: Tuple[int, int] = (120, 160)
    user_agent: str = "MangaSearch/1.0"
    # Default sort column & order
    default_sort_col: str = "MAL Score"
    default_sort_desc: bool = True

CONFIG = AppConfig()
BL_LOWER = {g.lower() for g in GENRE_BLACKLIST}

# Column definition for Treeview
COLUMNS: Tuple[str, ...] = (
    "Title", "Type", "Status", "Chapters", "Volumes",
    "MAL Score", "My Score", "Read", "Dropped", "Genres", "Not Interested"
)

COL_INDEX: Dict[str, int] = {
    "Title": 1, "Type": 2, "Status": 3, "Chapters": 4, "Volumes": 5,
    "MAL Score": 6, "My Score": 7, "Read": 8, "Dropped": 9, "Genres": 10, "Not Interested": 11
}

# -------------------------
# Helpers
# -------------------------
def split_genres(s: Optional[str]) -> List[str]:
    if not s:
        return []
    # DB often stores as "A, B, C"
    return [g.strip() for g in s.split(",") if g.strip()]

def has_blacklisted(genres_str: Optional[str]) -> bool:
    return any(g.lower() in BL_LOWER for g in split_genres(genres_str))


class MangaSearchApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Manga Search Tool")
        self.sort_column: str = CONFIG.default_sort_col
        self.sort_reverse: bool = CONFIG.default_sort_desc
        self.manga_data: List[Tuple] = []

        # Persistent DB & HTTP sessions
        self.conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        self.cursor = self.conn.cursor()
        logger.info("Connected to DB %s", DB_PATH)

        self.http = requests.Session()
        self.http.headers.update({"User-Agent": CONFIG.user_agent})
        retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.http.mount("http://", adapter)
        self.http.mount("https://", adapter)

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -------------------------
    # UI
    # -------------------------
    def setup_ui(self) -> None:
        self.root.geometry("1350x600")
        self.root.minsize(1000, 400)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        tk.Label(self.root, text="Search by Title:").grid(row=0, column=0, sticky="w", padx=5)
        self.title_entry = tk.Entry(self.root)
        self.title_entry.grid(row=0, column=1, sticky="ew", padx=5)

        tk.Label(self.root, text="Filter by Genre(s):").grid(row=1, column=0, sticky="w", padx=5)
        self.genre_entry = tk.Entry(self.root)
        self.genre_entry.grid(row=1, column=1, sticky="ew", padx=5)

        tk.Label(self.root, text="Filter by Type:").grid(row=0, column=2, sticky="w", padx=5)
        self.type_var = tk.StringVar()
        self.type_menu = ttk.Combobox(
            self.root,
            textvariable=self.type_var,
            values=["", "Manga", "Manhwa", "Manhua", "Novel", "Light Novel", "Doujinshi"],
            state="readonly",
            width=16,
        )
        self.type_menu.grid(row=0, column=3, padx=5)

        tk.Button(self.root, text="Search", command=self.on_search).grid(row=0, column=4, rowspan=2, padx=10, pady=5)

        self.title_entry.bind("<Return>", lambda event: self.on_search())
        self.genre_entry.bind("<Return>", lambda event: self.on_search())

        self.tree = ttk.Treeview(self.root, columns=COLUMNS, show="headings")
        self.tree.grid(row=2, column=0, columnspan=5, sticky="nsew", padx=5, pady=10)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=5, sticky="ns")

        for col in COLUMNS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            self.tree.column(col, anchor="w", width=120 if col != "Genres" else 300)

        style = ttk.Style()
        style.map("Treeview", background=[("selected", "#ccccff")])
        self.tree.tag_configure("dropped", background="#ffe5e5")
        self.tree.tag_configure("finished", background="#e5ffe5")
        self.tree.tag_configure("ongoing", background="#e5f0ff")

        self.tree.bind("<Double-1>", self.on_double_click)

    # -------------------------
    # Filters
    # -------------------------
    def parse_genre_filter(self, genre_string: str) -> Tuple[List[str], List[str]]:
        """
        Parse a simple include/exclude grammar:
        - tokens starting with '+' are include
        - tokens starting with '-' are exclude
        - first bare token is treated as include
        """
        include, exclude = [], []
        parts = [p.strip() for p in genre_string.split() if p.strip()]
        for i, part in enumerate(parts):
            if part.startswith("+"):
                include.append(part[1:])
            elif part.startswith("-"):
                exclude.append(part[1:])
            elif i == 0:
                include.append(part)
        return include, exclude

    # -------------------------
    # Data
    # -------------------------
    def fetch_data(self) -> List[Tuple]:
        """
        Fetch rows applying title/type/genre LIKE filters in SQL,
        then apply blacklist filtering in Python (case-insensitive).
        """
        query = """
            SELECT mal_id, title, type, status, chapters, volumes,
                   mean_score, user_score, read, dropped, genres, synopsis,
                   published_date, not_interested, images
            FROM manga
            WHERE 1=1
        """
        params: List[object] = []

        title = (self.title_entry.get() or "").strip()
        genre_filter = (self.genre_entry.get() or "").strip()
        type_filter = (self.type_var.get() or "").strip()

        if title:
            query += " AND title LIKE ?"
            params.append(f"%{title}%")
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)

        include, exclude = self.parse_genre_filter(genre_filter)
        for g in include:
            query += " AND genres LIKE ?"
            params.append(f"%{g}%")
        for g in exclude:
            query += " AND genres NOT LIKE ?"
            params.append(f"%{g}%")

        # Execute
        try:
            self.cursor.execute(query, params)
            results = self.cursor.fetchall()
        except sqlite3.DatabaseError as e:
            logger.exception("DB query failed")
            return []

        # Python-side blacklist filter (handles any case)
        filtered = [r for r in results if not has_blacklisted(r[10])]
        logger.info("Fetched %d rows (post-blacklist)", len(filtered))
        return filtered

    # -------------------------
    # Actions
    # -------------------------
    def on_search(self) -> None:
        data = self.fetch_data()
        self.display_data(data)
        if self.sort_column:
            self.sort_by(self.sort_column, keep_order=True)

    def display_data(self, data: Sequence[Tuple]) -> None:
        for i in self.tree.get_children():
            self.tree.delete(i)

        self.manga_data = list(data)
        for row in data:
            (mal_id, title, type_, status, chapters, volumes, mean_score,
             user_score, read, dropped, genres, _synopsis, published_date, not_interested, _images) = row

            # Chapters column UX: show start year if publishing & chapters unknown
            if (not chapters or chapters == 0) and status and status.lower() == "publishing" and published_date:
                try:
                    start_year = datetime.strptime(str(published_date)[:10], "%Y-%m-%d").year
                    display_chap = f"Started in: {start_year}"
                except Exception:
                    display_chap = "Started in: ?"
            else:
                display_chap = chapters

            # Read symbol
            if read == 0:
                read_symbol = "❌"
            elif read == -1:
                read_symbol = "✅"
            elif read == -2:
                read_symbol = "📘"
            else:
                read_symbol = str(read)

            # Dropped text
            if dropped == 1:
                dropped_text = "🔴 Dropped"
            elif dropped == 2:
                dropped_text = "🔄 Might Pick Up"
            else:
                dropped_text = "🟢 Not Dropped"

            not_interested_text = "🚫" if not_interested else ""

            # Row tag for coloring
            row_tag = ""
            if read != 0:
                if dropped == 1:
                    row_tag = "dropped"
                elif (status or "").lower() == "finished":
                    row_tag = "finished"
                else:
                    row_tag = "ongoing"

            self.tree.insert(
                "", tk.END,
                values=(title, type_, status, display_chap, volumes, mean_score, user_score,
                        read_symbol, dropped_text, genres, not_interested_text),
                iid=str(mal_id),
                tags=(row_tag,) if row_tag else ()
            )

    def sort_by(self, column: str, keep_order: bool = False) -> None:
        col_idx = COL_INDEX.get(column)
        if col_idx is None:
            return

        if not keep_order:
            if self.sort_column == column:
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_column = column
                # default to ascending for text, descending for numeric-ish
                self.sort_reverse = column in {"MAL Score", "My Score", "Chapters", "Volumes"}

        def coerce_numeric(val):
            # Try int, then float; fallback to string lower
            if val is None:
                return float("-inf") if self.sort_reverse else float("inf")
            if isinstance(val, (int, float)):
                return val
            s = str(val).strip()
            # map emojis back to sortable magnitude for Read/Dropped
            emoji_map = {"❌": -3, "📘": -2, "✅": 10}
            if s in emoji_map:
                return emoji_map[s]
            try:
                return int(s)
            except Exception:
                try:
                    return float(s)
                except Exception:
                    return s.lower()

        # Build a list of tuples matching display order used in Treeview
        display_rows = []
        for row in self.manga_data:
            (mal_id, title, type_, status, chapters, volumes, mean_score,
             user_score, read, dropped, genres, _synopsis, published_date, not_interested, _images) = row

            # Recreate the display row used above for consistent sorting
            if (not chapters or chapters == 0) and status and status.lower() == "publishing" and published_date:
                try:
                    start_year = datetime.strptime(str(published_date)[:10], "%Y-%m-%d").year
                    display_chap = f"Started in: {start_year}"
                except Exception:
                    display_chap = "Started in: ?"
            else:
                display_chap = chapters

            if read == 0: read_symbol = "❌"
            elif read == -1: read_symbol = "✅"
            elif read == -2: read_symbol = "📘"
            else: read_symbol = str(read)

            if dropped == 1: dropped_text = "🔴 Dropped"
            elif dropped == 2: dropped_text = "🔄 Might Pick Up"
            else: dropped_text = "🟢 Not Dropped"

            not_interested_text = "🚫" if not_interested else ""

            display_rows.append((
                title, type_, status, display_chap, volumes, mean_score, user_score,
                read_symbol, dropped_text, genres, not_interested_text,  # 11 visible columns
                mal_id  # keep original id to re-map later if needed
            ))

        # Sort
        sorted_display = sorted(display_rows, key=lambda r: coerce_numeric(r[col_idx - 1]), reverse=self.sort_reverse)

        # Rebuild a light dataset to render (we can reuse display_data for consistent code path)
        # Map back to original self.manga_data order by mal_id
        id_to_row = {str(r[0]): r for r in self.manga_data}  # key by mal_id string
        sorted_original = [id_to_row[str(r[-1])] for r in sorted_display]
        self.display_data(sorted_original)

    def on_double_click(self, event) -> None:
        item_id = self.tree.focus()
        if not item_id:
            return

        try:
            self.cursor.execute(
                """
                SELECT title, type, status, chapters, volumes, mean_score,
                       user_score, read, dropped, genres, synopsis, not_interested, images
                FROM manga WHERE mal_id = ?
                """,
                (item_id,),
            )
            result = self.cursor.fetchone()
        except sqlite3.DatabaseError as e:
            logger.exception("DB fetch (details) failed")
            return

        if result:
            self.open_details_window(item_id, *result)

    # -------------------------
    # Details
    # -------------------------
    def open_details_window(
        self,
        mal_id: str,
        title: str,
        type_: str,
        status: str,
        chapters: Optional[int],
        volumes: Optional[int],
        mean_score: Optional[float],
        user_score: Optional[int],
        read: Optional[int],
        dropped: Optional[int],
        genres: Optional[str],
        synopsis: Optional[str],
        not_interested: Optional[int],
        images: Optional[str],
    ) -> None:
        win = tk.Toplevel(self.root)
        win.title(f"Details for: {title}")
        win.geometry("600x750")
        win.minsize(500, 400)

        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(12, weight=1)

        # Image (safe JSON, retries, timeout)
        if images:
            try:
                data = json.loads(images or "{}")
                img_url = (data.get("jpg") or {}).get("image_url")
                if img_url:
                    resp = self.http.get(img_url, timeout=CONFIG.http_timeout)
                    resp.raise_for_status()
                    img = Image.open(io.BytesIO(resp.content)).resize(CONFIG.img_size, Image.Resampling.LANCZOS)
                    img_tk = ImageTk.PhotoImage(img)
                    img_label = tk.Label(win, image=img_tk)
                    img_label.image = img_tk
                    img_label.grid(row=0, column=1, rowspan=6, sticky="ne", padx=10, pady=10)
            except (json.JSONDecodeError, UnidentifiedImageError, requests.RequestException) as e:
                logger.info("Image load failed (details) for id=%s: %s", mal_id, e)

        tk.Label(win, text=f"Title: {title}", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=5)
        tk.Label(win, text=f"Genres: {genres or 'N/A'}", wraplength=440).grid(row=1, column=0, sticky="w", padx=10)
        tk.Label(
            win,
            text=f"Type: {type_} | Status: {status} | Chapters: {chapters or '??'} | Volumes: {volumes or '??'}",
        ).grid(row=2, column=0, sticky="w", padx=10)

        score_var = tk.IntVar(value=user_score if user_score else 0)
        tk.Label(win, text="Your Score (1-10):").grid(row=3, column=0, sticky="w", padx=10)
        tk.Spinbox(win, from_=1, to=10, textvariable=score_var, width=6).grid(row=4, column=0, sticky="w", padx=10)

        chapter_var = tk.IntVar(value=read if read is not None else 0)
        tk.Label(win, text="Current Chapter (0 = Unread, -1 = Finished, -2 = Read Unknown):").grid(row=5, column=0, sticky="w", padx=10)
        tk.Spinbox(win, from_=-2, to=9999, textvariable=chapter_var, width=8).grid(row=6, column=0, sticky="w", padx=10)

        drop_val = 1 if dropped == 1 else 2 if dropped == 2 else 0
        drop_var = tk.StringVar(value=f"{drop_val} - " + ("Dropped" if drop_val == 1 else "Might Pick Up" if drop_val == 2 else "Not Dropped"))
        tk.Label(win, text="Dropped Status:").grid(row=7, column=0, sticky="w", padx=10)
        drop_box = ttk.Combobox(win, textvariable=drop_var, values=["0 - Not Dropped", "1 - Dropped", "2 - Might Pick Up"], state="readonly", width=18)
        drop_box.grid(row=8, column=0, sticky="w", padx=10)

        not_interested_var = tk.BooleanVar(value=bool(not_interested))
        ttk.Checkbutton(win, text="Not Interested", variable=not_interested_var).grid(row=9, column=0, sticky="w", padx=10)

        tk.Label(win, text="Synopsis:").grid(row=10, column=0, sticky="nw", padx=10)
        synopsis_box = scrolledtext.ScrolledText(win, wrap=tk.WORD)
        synopsis_box.insert(tk.END, synopsis or "[No synopsis available]")
        synopsis_box.config(state=tk.DISABLED)
        synopsis_box.grid(row=11, column=0, sticky="nsew", padx=10, pady=(0, 10))

        footer = tk.Frame(win)
        footer.grid(row=13, column=0, columnspan=2, sticky="ew", pady=10)
        footer.grid_columnconfigure(0, weight=1)
        ttk.Button(
            footer,
            text="Save",
            command=lambda: self._save_changes(
                win, mal_id, score_var, chapter_var, drop_var, not_interested_var
            ),
        ).pack(anchor="center")

    def _save_changes(
        self,
        win: tk.Toplevel,
        mal_id: str,
        score_var: tk.IntVar,
        chapter_var: tk.IntVar,
        drop_var: tk.StringVar,
        not_interested_var: tk.BooleanVar,
    ) -> None:
        try:
            dropped_int = int(drop_var.get().split(" ")[0])
            self.cursor.execute(
                """
                UPDATE manga
                SET user_score = ?, read = ?, dropped = ?, not_interested = ?
                WHERE mal_id = ?
                """,
                (int(score_var.get()), int(chapter_var.get()), dropped_int, int(not_interested_var.get()), mal_id),
            )
            self.conn.commit()
            logger.info("Saved changes for mal_id=%s", mal_id)
        except sqlite3.DatabaseError as e:
            logger.exception("Save failed")
            return
        finally:
            win.destroy()
            self.on_search()

    # -------------------------
    # Shutdown
    # -------------------------
    def on_close(self) -> None:
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
    root = tk.Tk()
    app = MangaSearchApp(root)
    root.mainloop()
