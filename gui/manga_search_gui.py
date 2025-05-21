import sqlite3
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime
from PIL import Image, ImageTk
import requests
import io

from definitions import DB_PATH

class MangaSearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Manga Search Tool")
        self.sort_column = "MAL Score"
        self.sort_reverse = True
        self.manga_data = []

        self.setup_ui()

    def setup_ui(self):
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
        self.type_menu = ttk.Combobox(self.root, textvariable=self.type_var, values=["", "Manga", "Manhwa", "Manhua", "Novel", "Light Novel", "Doujinshi"])
        self.type_menu.grid(row=0, column=3, padx=5)

        tk.Button(self.root, text="Search", command=self.on_search).grid(row=0, column=4, rowspan=2, padx=10, pady=5)

        self.title_entry.bind("<Return>", lambda event: self.on_search())
        self.genre_entry.bind("<Return>", lambda event: self.on_search())

        columns = ("Title", "Type", "Status", "Chapters", "Volumes", "MAL Score", "My Score", "Read", "Dropped", "Genres", "Not Interested")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings")
        self.tree.grid(row=2, column=0, columnspan=5, sticky="nsew", padx=5, pady=10)

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=2, column=5, sticky="ns")

        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            self.tree.column(col, anchor="w", width=120 if col != "Genres" else 300)

        style = ttk.Style()
        style.map("Treeview", background=[("selected", "#ccccff")])
        self.tree.tag_configure("dropped", background="#ffe5e5")
        self.tree.tag_configure("finished", background="#e5ffe5")
        self.tree.tag_configure("ongoing", background="#e5f0ff")

        self.tree.bind("<Double-1>", self.on_double_click)

    def parse_genre_filter(self, genre_string):
        include, exclude = [], []
        parts = genre_string.split()
        for i, part in enumerate(parts):
            if part.startswith("+"):
                include.append(part[1:])
            elif part.startswith("-"):
                exclude.append(part[1:])
            elif i == 0:
                include.append(part)
        return include, exclude

    def fetch_data(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = """
            SELECT mal_id, title, type, status, chapters, volumes,
                   mean_score, user_score, read, dropped, genres, synopsis, published_date, not_interested, images
            FROM manga WHERE 1=1
              AND genres NOT LIKE '%Boys Love%'
        """
        params = []

        title = self.title_entry.get()
        genre_filter = self.genre_entry.get()
        type_filter = self.type_var.get()

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

        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return results

    def on_search(self):
        data = self.fetch_data()
        self.display_data(data)
        # Only sort if explicitly set
        if self.sort_column:
            self.sort_by(self.sort_column, keep_order=True)

    def display_data(self, data):
        for i in self.tree.get_children():
            self.tree.delete(i)

        self.manga_data = data
        for row in data:
            (mal_id, title, type_, status, chapters, volumes, mean_score,
             user_score, read, dropped, genres, _, published_date, not_interested, _) = row

            if (not chapters or chapters == 0) and status == "Publishing" and published_date:
                try:
                    start_year = datetime.strptime(published_date[:10], "%Y-%m-%d").year
                    display_chap = f"Started in: {start_year}"
                except:
                    display_chap = "Started in: ?"
            else:
                display_chap = chapters

            if read == 0:
                read_symbol = "❌"
            elif read == -1:
                read_symbol = "✅"
            elif read == -2:
                read_symbol = "📘"
            else:
                read_symbol = str(read)

            if dropped == 1:
                dropped_text = "🔴 Dropped"
            elif dropped == 2:
                dropped_text = "🔄 Might Pick Up"
            else:
                dropped_text = "🟢 Not Dropped"

            not_interested_text = "🚫" if not_interested else ""

            row_tag = ""
            if read != 0:
                if dropped == 1:
                    row_tag = "dropped"
                elif status.lower() == "finished":
                    row_tag = "finished"
                else:
                    row_tag = "ongoing"

            self.tree.insert(
                "", tk.END,
                values=(title, type_, status, display_chap, volumes, mean_score, user_score, read_symbol, dropped_text, genres, not_interested_text),
                iid=str(mal_id),
                tags=(row_tag,) if row_tag else ()
            )

    def sort_by(self, column, keep_order=False):
        col_map = {
            "Title": 1, "Type": 2, "Status": 3, "Chapters": 4, "Volumes": 5,
            "MAL Score": 6, "My Score": 7, "Read": 8, "Dropped": 9, "Genres": 10, "Not Interested": 11
        }
        col_idx = col_map.get(column)
        if col_idx is None:
            return

        if not keep_order:
            if self.sort_column == column:
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_column = column
                self.sort_reverse = False

        def sort_key(x):
            val = x[col_idx]
            if isinstance(val, str):
                return val.lstrip('"').lower()
            return val if val is not None else 0

        sorted_data = sorted(self.manga_data, key=sort_key, reverse=self.sort_reverse)
        self.display_data(sorted_data)

    def on_double_click(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, type, status, chapters, volumes, mean_score,
                   user_score, read, dropped, genres, synopsis, not_interested, images
            FROM manga WHERE mal_id = ?
        """, (item_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            self.open_details_window(item_id, *result)

    def open_details_window(self, mal_id, title, type_, status, chapters, volumes,
                             mean_score, user_score, read, dropped, genres, synopsis, not_interested, images):
        win = tk.Toplevel(self.root)
        win.title(f"Details for: {title}")
        win.geometry("600x750")
        win.minsize(500, 400)

        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(12, weight=1)

        if images:
            try:
                import ast
                img_url = ast.literal_eval(images)["jpg"]["image_url"]
                image_data = requests.get(img_url).content
                img = Image.open(io.BytesIO(image_data)).resize((120, 160))
                img_tk = ImageTk.PhotoImage(img)
                img_label = tk.Label(win, image=img_tk)
                img_label.image = img_tk
                img_label.grid(row=0, column=1, rowspan=6, sticky="ne", padx=10, pady=10)
            except:
                pass

        tk.Label(win, text=f"Title: {title}", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=5)
        tk.Label(win, text=f"Genres: {genres}", wraplength=440).grid(row=1, column=0, sticky="w", padx=10)
        tk.Label(win, text=f"Type: {type_} | Status: {status} | Chapters: {chapters or '??'} | Volumes: {volumes or '??'}").grid(row=2, column=0, sticky="w", padx=10)

        score_var = tk.IntVar(value=user_score if user_score else 0)
        tk.Label(win, text="Your Score (1-10):").grid(row=3, column=0, sticky="w", padx=10)
        tk.Spinbox(win, from_=1, to=10, textvariable=score_var).grid(row=4, column=0, sticky="w", padx=10)

        chapter_var = tk.IntVar(value=read if read is not None else 0)
        tk.Label(win, text="Current Chapter (0 = Unread, -1 = Finished, -2 = Read Unknown):").grid(row=5, column=0, sticky="w", padx=10)
        tk.Spinbox(win, from_=-2, to=9999, textvariable=chapter_var).grid(row=6, column=0, sticky="w", padx=10)

        drop_var = tk.StringVar(value=f"{dropped} - Dropped" if dropped == 1 else "2 - Might Pick Up" if dropped == 2 else "0 - Not Dropped")
        tk.Label(win, text="Dropped Status:").grid(row=7, column=0, sticky="w", padx=10)
        drop_box = ttk.Combobox(win, textvariable=drop_var, values=[
            "0 - Not Dropped",
            "1 - Dropped",
            "2 - Might Pick Up"
        ], state="readonly")
        drop_box.grid(row=8, column=0, sticky="w", padx=10)

        not_interested_var = tk.BooleanVar(value=bool(not_interested))
        tk.Checkbutton(win, text="Not Interested", variable=not_interested_var).grid(row=9, column=0, sticky="w", padx=10)

        tk.Label(win, text="Synopsis:").grid(row=10, column=0, sticky="nw", padx=10)
        synopsis_box = scrolledtext.ScrolledText(win, wrap=tk.WORD)
        synopsis_box.insert(tk.END, synopsis or "[No synopsis available]")
        synopsis_box.config(state=tk.DISABLED)
        synopsis_box.grid(row=11, column=0, sticky="nsew", padx=10, pady=(0, 10))

        footer = tk.Frame(win)
        footer.grid(row=13, column=0, columnspan=2, sticky="ew", pady=10)
        footer.grid_columnconfigure(0, weight=1)
        tk.Button(footer, text="Save", command=lambda: self._save_changes(win, mal_id, score_var, chapter_var, drop_var, not_interested_var)).pack(anchor="center")

    def _save_changes(self, win, mal_id, score_var, chapter_var, drop_var, not_interested_var):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE manga SET user_score = ?, read = ?, dropped = ?, not_interested = ? WHERE mal_id = ?",
            (score_var.get(), chapter_var.get(), int(drop_var.get().split(" ")[0]), int(not_interested_var.get()), mal_id)
        )
        conn.commit()
        conn.close()
        self.on_search()
        win.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MangaSearchApp(root)
    root.mainloop()
