import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageTk
import requests
import io
import json
import os
import random

from definitions import DB_PATH, SKIPPED_FILE

class MangaRater:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.shown_ids = set()
        self.manga_queue = []
        self.current_manga = None

        self.skipped = self.load_skipped()

        self.root = tk.Tk()
        self.root.title("Rate Random Manga by Genre")

        top_frame = tk.Frame(self.root)
        top_frame.pack(pady=5, fill=tk.X)

        self.type_var = tk.StringVar(value="Manga")
        tk.Label(top_frame, text="Type:").pack(side=tk.LEFT, padx=(10, 0))
        self.type_dropdown = ttk.Combobox(top_frame, textvariable=self.type_var, state="readonly")
        self.type_dropdown["values"] = ["Manga", "Manhwa", "Manhua"]
        self.type_dropdown.pack(side=tk.LEFT, padx=5)
        self.type_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_random_manga(reset=True))

        self.genre_var = tk.StringVar()
        tk.Label(top_frame, text="Genre:").pack(side=tk.LEFT)
        self.genre_dropdown = ttk.Combobox(top_frame, textvariable=self.genre_var, state="readonly")
        self.genre_dropdown.pack(side=tk.LEFT)
        self.genre_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_random_manga(reset=True))

        self.read_count_label = tk.Label(top_frame, text="Read: 0 | Not Interested: 0")
        self.read_count_label.pack(side=tk.RIGHT, padx=10)

        self.cover_label = tk.Label(self.root)
        self.cover_label.pack(pady=5)

        self.info_label = tk.Label(self.root, text="", font=("Arial", 14), wraplength=400, justify="left")
        self.info_label.pack(pady=10)

        self.synopsis_box = scrolledtext.ScrolledText(self.root, height=6, width=60, wrap=tk.WORD)
        self.synopsis_box.pack(padx=10, pady=5)
        self.synopsis_box.config(state=tk.DISABLED)

        self.score_var = tk.IntVar()
        tk.Label(self.root, text="Your Score (1-10):").pack()
        tk.Spinbox(self.root, from_=1, to=10, textvariable=self.score_var, width=5).pack()

        self.read_var = tk.StringVar(value="0")
        tk.Label(self.root, text="Read Status:").pack(pady=(5, 0))
        self.read_dropdown = ttk.Combobox(self.root, textvariable=self.read_var, state="readonly")
        self.read_dropdown["values"] = ["0 - Unread", "-2 - Read but not finished", "-1 - Finished"]
        self.read_dropdown.pack(pady=2)

        self.drop_var = tk.StringVar(value="Not Dropped")
        tk.Label(self.root, text="Dropped Status:").pack(pady=(5, 0))
        self.drop_dropdown = ttk.Combobox(self.root, textvariable=self.drop_var, state="readonly")
        self.drop_dropdown["values"] = ["Not Dropped", "Dropped", "Dropped but would pick back up"]
        self.drop_dropdown.pack(pady=2)

        self.not_interested_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.root, text="Not Interested", variable=self.not_interested_var).pack(pady=5)

        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="Save & Next", command=self.save_and_next).grid(row=0, column=0, padx=5)
        tk.Button(button_frame, text="Skip", command=self.skip_and_next).grid(row=0, column=1, padx=5)

        self.genre_dropdown["values"] = self.get_all_genres()
        if self.genre_dropdown["values"]:
            self.genre_var.set(self.genre_dropdown["values"][0])
            self.load_random_manga(reset=True)

        self.root.mainloop()

    def load_skipped(self):
        if os.path.exists(SKIPPED_FILE):
            with open(SKIPPED_FILE, "r") as f:
                return set(json.load(f))
        return set()

    def save_skipped(self):
        with open(SKIPPED_FILE, "w") as f:
            json.dump(list(self.skipped), f)

    def get_all_genres(self):
        self.cursor.execute("SELECT genres FROM manga")
        genres = set()
        for row in self.cursor.fetchall():
            if row[0]:
                for g in row[0].split(", "):
                    genres.add(g)
        return sorted(genres)

    def update_read_count(self):
        self.cursor.execute("SELECT COUNT(*) FROM manga WHERE read != 0")
        read_count = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM manga WHERE not_interested = 1")
        not_interested_count = self.cursor.fetchone()[0]
        self.read_count_label.config(text=f"Read: {read_count} | Not Interested: {not_interested_count}")

    def load_random_manga(self, reset=False):
        if reset:
            self.shown_ids.clear()
            self.manga_queue.clear()

        genre = self.genre_var.get()
        type_ = self.type_var.get()
        self.cursor.execute("""
            SELECT mal_id, title, mean_score, genres, user_score, read, images, synopsis
            FROM manga
            WHERE genres LIKE ? AND genres NOT LIKE '%Boys Love%' AND type = ? AND (user_score IS NULL OR user_score = '') AND not_interested = 0
        """, (f"%{genre}%", type_))
        rows = [r for r in self.cursor.fetchall() if r[0] not in self.shown_ids and r[0] not in self.skipped]
        self.manga_queue.extend(random.sample(rows, min(20, len(rows))))
        self.show_next_manga()

    def show_next_manga(self):
        while not self.manga_queue:
            self.load_random_manga()
            if not self.manga_queue:
                messagebox.showinfo("Notice", "No more manga available for this genre and type.")
                return

        self.current_manga = self.manga_queue.pop(0)
        mal_id, title, score, genres, _, _, images_json, synopsis = self.current_manga
        self.shown_ids.add(mal_id)

        try:
            image_url = eval(images_json)["jpg"]["image_url"]
            image_data = requests.get(image_url).content
            img = Image.open(io.BytesIO(image_data)).resize((150, 220))
            img_tk = ImageTk.PhotoImage(img)
            self.cover_label.config(image=img_tk)
            self.cover_label.image = img_tk
        except:
            self.cover_label.config(image=None, text="[No Image]")

        self.info_label.config(text=f"Title: {title}\nScore: {score}\nGenres: {genres}")

        self.synopsis_box.config(state=tk.NORMAL)
        self.synopsis_box.delete(1.0, tk.END)
        self.synopsis_box.insert(tk.END, synopsis or "[No synopsis available]")
        self.synopsis_box.config(state=tk.DISABLED)

        self.score_var.set(0)
        self.read_var.set("0")
        self.drop_var.set("Not Dropped")
        self.not_interested_var.set(False)
        self.update_read_count()

    def save_and_next(self):
        if not self.current_manga:
            return
        mal_id = self.current_manga[0]
        score = self.score_var.get()
        read_value = int(self.read_var.get().split(" ")[0])
        dropped_value = {
            "Not Dropped": 0,
            "Dropped": 1,
            "Dropped but would pick back up": 2
        }.get(self.drop_var.get(), 0)
        not_interested = 1 if self.not_interested_var.get() else 0

        self.cursor.execute("""
            UPDATE manga SET user_score = ?, read = ?, dropped = ?, not_interested = ? WHERE mal_id = ?
        """, (score if score > 0 else None, read_value, dropped_value, not_interested, mal_id))
        self.conn.commit()
        self.show_next_manga()

    def skip_and_next(self):
        if not self.current_manga:
            return
        self.skipped.add(self.current_manga[0])
        self.show_next_manga()

if __name__ == "__main__":
    MangaRater()
