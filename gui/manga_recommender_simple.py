import sqlite3
from collections import Counter
import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageTk
import requests
import io
import json
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from definitions import DB_PATH, WEIGHTS_FILE  # ✅ updated path import

RECOMMEND_LIMIT = 50

DEFAULT_WEIGHTS = {
    "match_score": 1.0,
    "mean_score": 1.0,
    "chapters": 1.0,
    "published_date": 1.0
}

class MangaRecommender:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.root = tk.Tk()
        self.root.title("Manga Recommendations")
        self.weights = self.load_weights()
        self.genre_counter = Counter()
        self.setup_ui()
        self.recommendations = self.generate_recommendations()
        self.show_top_images()
        self.root.mainloop()

    def load_weights(self):
        if os.path.exists(WEIGHTS_FILE):
            with open(WEIGHTS_FILE, "r") as f:
                return json.load(f)
        return DEFAULT_WEIGHTS.copy()

    def save_weights(self):
        with open(WEIGHTS_FILE, "w") as f:
            json.dump(self.weights, f)

    def setup_ui(self):
        self.top_frame = tk.Frame(self.root)
        self.top_frame.pack(pady=10)

        self.image_labels = []
        for i in range(5):
            label = tk.Label(self.top_frame, text="Loading...", compound=tk.TOP)
            label.pack(side="left", padx=5)
            label.bind("<Button-1>", lambda e, i=i: self.show_details(i))
            self.image_labels.append(label)

        self.button_frame = tk.Frame(self.root)
        self.button_frame.pack(pady=10)

        tk.Button(self.button_frame, text="View Full List", command=self.show_full_list).pack(side="left", padx=10)
        tk.Button(self.button_frame, text="Adjust Weights", command=self.adjust_weights).pack(side="left", padx=10)
        tk.Button(self.button_frame, text="Genre Coverage", command=self.show_genre_coverage).pack(side="left", padx=10)

    def fetch_image(self, image_url):
        try:
            image_data = requests.get(image_url).content
            img = Image.open(io.BytesIO(image_data)).resize((120, 170))
            return ImageTk.PhotoImage(img)
        except:
            return None

    def generate_recommendations(self):
        self.cursor.execute("""
            SELECT genres FROM manga
            WHERE user_score >= 8 AND read != 0 AND dropped = 0
        """)
        genre_rows = self.cursor.fetchall()
        self.genre_counter = Counter()
        for row in genre_rows:
            genres = row[0].split(", ") if row[0] else []
            self.genre_counter.update(genres)

        self.cursor.execute("""
            SELECT mal_id, title, genres, mean_score, chapters, published_date, images, synopsis
            FROM manga
            WHERE (user_score IS NULL OR user_score = '')
              AND read = 0 AND dropped = 0
        """)
        candidates = self.cursor.fetchall()

        recommendations = []
        total_genre_weight = sum(self.genre_counter.values()) or 1  # avoid division by zero

        for mal_id, title, genres_str, mean_score, chapters, pub_date, images_json, synopsis in candidates:
            genres = genres_str.split(", ") if genres_str else []
            breakdown = {g: self.genre_counter.get(g, 0) for g in genres if g in self.genre_counter}
            if breakdown:
                match_raw = sum(breakdown.values())
                match_score = (match_raw / total_genre_weight) * self.weights["match_score"]
            else:
                match_score = 0
            recommendations.append({
                "mal_id": mal_id,
                "title": title,
                "match_score": match_score,
                "mean_score": mean_score or 0,
                "chapters": chapters if chapters else -1,
                "published_date": pub_date or "0000-00-00",
                "images": eval(images_json) if images_json else {},
                "synopsis": synopsis or "",
                "genres": genres_str or "",
                "match_breakdown": breakdown
            })

        w = self.weights
        recommendations.sort(
            key=lambda x: (
                -x["match_score"],
                -x["mean_score"] * w["mean_score"],
                -x["chapters"] * w["chapters"] if x["chapters"] != -1 else 0,
                x["published_date"]
            )
        )
        return recommendations[:RECOMMEND_LIMIT]

    def show_top_images(self):
        for i, rec in enumerate(self.recommendations[:5]):
            img_url = rec["images"].get("jpg", {}).get("image_url")
            img_tk = self.fetch_image(img_url) if img_url else None
            label = self.image_labels[i]
            label.config(image=img_tk, text=rec["title"])
            label.image = img_tk

    def show_details(self, index):
        rec = self.recommendations[index]
        win = tk.Toplevel(self.root)
        win.title(rec["title"])
        win.geometry("600x500")

        if rec["images"]:
            img_url = rec["images"].get("jpg", {}).get("image_url")
            if img_url:
                img_tk = self.fetch_image(img_url)
                if img_tk:
                    tk.Label(win, image=img_tk).pack()
                    win.image = img_tk

        tk.Label(win, text=rec["title"], font=("Arial", 14, "bold")).pack(pady=5)
        tk.Label(win, text=f"Rating: {rec['mean_score']}, Chapters: {rec['chapters']}, Published: {rec['published_date']}\nMatch Score: {rec['match_score']:.2f}").pack()

        breakdown_text = "\nMatch Breakdown (Normalized):\n"
        for genre, count in rec["match_breakdown"].items():
            breakdown_text += f"  {genre}: {count}\n"
        tk.Label(win, text=breakdown_text, justify="left", font=("Courier", 10)).pack(padx=10, pady=5, anchor="w")

        synopsis_box = scrolledtext.ScrolledText(win, wrap=tk.WORD, height=15)
        synopsis_box.insert(tk.END, rec["synopsis"])
        synopsis_box.config(state=tk.DISABLED)
        synopsis_box.pack(fill="both", expand=True, padx=10, pady=10)

    def show_full_list(self):
        win = tk.Toplevel(self.root)
        win.title("Full Recommendations")
        win.geometry("1200x600")

        columns = ("Title", "Match", "Score", "Chapters", "Start Date")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=200)
        tree.pack(fill="both", expand=True)

        for rec in self.recommendations:
            tree.insert("", tk.END, values=(
                rec["title"],
                round(rec["match_score"], 2),
                rec["mean_score"],
                rec["chapters"],
                rec["published_date"]
            ))

    def adjust_weights(self):
        win = tk.Toplevel(self.root)
        win.title("Adjust Weights")
        sliders = {}

        def update_weights():
            for key in sliders:
                self.weights[key] = sliders[key].get()
            self.save_weights()
            self.recommendations = self.generate_recommendations()
            self.show_top_images()
            win.destroy()

        for i, key in enumerate(self.weights):
            tk.Label(win, text=f"{key}").grid(row=i, column=0, sticky="w", padx=10, pady=5)
            sliders[key] = tk.Scale(win, from_=0.0, to=5.0, resolution=0.1, orient="horizontal")
            sliders[key].set(self.weights[key])
            sliders[key].grid(row=i, column=1, padx=10, pady=5)

        tk.Button(win, text="Apply", command=update_weights).grid(row=len(self.weights)+1, column=0, columnspan=2, pady=10)

    def show_genre_coverage(self):
        win = tk.Toplevel(self.root)
        win.title("Genre Coverage")
        fig, ax = plt.subplots(figsize=(8, 6))
        genres, counts = zip(*self.genre_counter.most_common(20))
        ax.barh(genres[::-1], counts[::-1])
        ax.set_xlabel("Count")
        ax.set_title("Top Genres from Your Favorites")
        plt.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

if __name__ == "__main__":
    MangaRecommender()