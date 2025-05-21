import tkinter as tk
from tkinter import ttk, scrolledtext
import sqlite3
import pandas as pd
import joblib
import requests
from PIL import Image, ImageTk
import io

from definitions import DB_PATH, MODEL_PATH
from manga_recommendation.utils import GenreBinarizer

TOP_N = 5

class RecommendationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Manga Recommender")

        self.model = joblib.load(MODEL_PATH)
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()

        self.selected_type = tk.StringVar(value="")

        self.type_dropdown = ttk.Combobox(self.root, textvariable=self.selected_type, values=["", "Manga", "Manhwa", "Manhua"], state="readonly")
        self.type_dropdown.pack(pady=5)
        self.type_dropdown.bind("<<ComboboxSelected>>", lambda e: self.refresh_recommendations())

        self.shown_ids = set()
        self.recommendations = self.get_recommendations()

        self.container = ttk.Frame(self.root)
        self.container.pack(fill="both", expand=True)

        self.refresh_button = tk.Button(self.root, text="Next Recommendations", command=self.refresh_recommendations)
        self.refresh_button.pack(pady=5)

        self.setup_ui()

    def get_recommendations(self):
        type_filter = self.selected_type.get()
        query = """
            SELECT mal_id, title, type, genres, mean_score, chapters, volumes, synopsis, images
            FROM manga
            WHERE user_score IS NULL AND not_interested = 0 AND genres NOT LIKE '%Boys Love%'
        """
        params = []
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)

        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()

        df = pd.DataFrame(rows, columns=[
            "mal_id", "title", "type", "genres", "mean_score", "chapters", "volumes", "synopsis", "images"
        ])
        df = df[~df["mal_id"].isin(self.shown_ids)]
        if df.empty:
            return pd.DataFrame()

        df["genre_list"] = df["genres"].fillna("").apply(lambda g: [x.strip() for x in g.split(",") if x.strip()])
        df["mean_score"] = df["mean_score"].fillna(0)
        df["chapters"] = df["chapters"].fillna(0)
        df["volumes"] = df["volumes"].fillna(0)
        df["synopsis"] = df["synopsis"].fillna("")

        preds = self.model.predict_proba(df[["type", "genre_list", "mean_score", "chapters", "volumes", "synopsis"]])
        df["score"] = preds[:, 1]
        result = df.sort_values("score", ascending=False).head(TOP_N)
        self.shown_ids.update(result["mal_id"].tolist())
        return result

    def refresh_recommendations(self):
        for widget in self.container.winfo_children():
            widget.destroy()
        self.recommendations = self.get_recommendations()
        self.setup_ui()

    def setup_ui(self):
        for idx, row in self.recommendations.iterrows():
            frame = ttk.Frame(self.container, padding=10)
            frame.pack(fill="x")

            img_label = tk.Label(frame, cursor="hand2")
            img_label.pack(side="left", padx=5)

            try:
                url = eval(row["images"])["jpg"]["image_url"]
                img_data = requests.get(url).content
                img = Image.open(io.BytesIO(img_data)).resize((100, 140))
                img_tk = ImageTk.PhotoImage(img)
                img_label.config(image=img_tk)
                img_label.image = img_tk
            except:
                img_label.config(text="[No Image]")

            img_label.bind("<Button-1>", lambda e, mal_id=row["mal_id"]: self.open_details(mal_id))

            # Show chapter or volume or start year
            if row["chapters"]:
                extra_info = f"Chapters: {int(row['chapters'])}"
            elif row["volumes"]:
                extra_info = f"Volumes: {int(row['volumes'])}"
            else:
                self.cursor.execute("SELECT published_date FROM manga WHERE mal_id = ?", (row["mal_id"],))
                pub = self.cursor.fetchone()
                extra_info = f"Started in: {pub[0][:4]}" if pub and pub[0] else "Start date unknown"

            info = tk.Label(frame, text=f"{row['title']}\nGenres: {row['genres']}\nMatch Score: {row['score']:.2f}\n{extra_info}",
                            justify="left", font=("Arial", 10), anchor="w")
            info.pack(side="left", padx=10)

            synopsis_box = scrolledtext.ScrolledText(frame, height=5, width=50, wrap=tk.WORD)
            synopsis_box.insert(tk.END, row["synopsis"])
            synopsis_box.config(state=tk.DISABLED)
            synopsis_box.pack(side="left", padx=5)

    def open_details(self, mal_id):
        self.cursor.execute("""
            SELECT title, synopsis, user_score, read, not_interested
            FROM manga WHERE mal_id = ?
        """, (mal_id,))
        result = self.cursor.fetchone()
        if not result:
            return

        title, synopsis, user_score, read, not_interested = result

        win = tk.Toplevel(self.root)
        win.title(f"Details for: {title}")
        win.geometry("500x400")

        tk.Label(win, text=f"Title: {title}", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        tk.Label(win, text="Synopsis:").pack(anchor="w", padx=10)
        synopsis_box = scrolledtext.ScrolledText(win, wrap=tk.WORD, height=6)
        synopsis_box.insert(tk.END, synopsis)
        synopsis_box.config(state=tk.DISABLED)
        synopsis_box.pack(fill="both", expand=False, padx=10)

        score_var = tk.IntVar(value=user_score if user_score else 0)
        tk.Label(win, text="Your Score (1-10):").pack(anchor="w", padx=10)
        tk.Spinbox(win, from_=1, to=10, textvariable=score_var).pack(anchor="w", padx=10)

        read_var = tk.StringVar(value=str(read or 0))
        tk.Label(win, text="Read Status:").pack(anchor="w", padx=10)
        ttk.Combobox(win, textvariable=read_var, values=["0 - Unread", "-2 - Read Unknown", "-1 - Finished"], state="readonly").pack(anchor="w", padx=10)

        interested_var = tk.BooleanVar(value=bool(not_interested))
        tk.Checkbutton(win, text="Not Interested", variable=interested_var).pack(anchor="w", padx=10, pady=5)

        def save_changes():
            self.cursor.execute("""
                UPDATE manga SET user_score = ?, read = ?, not_interested = ? WHERE mal_id = ?
            """, (score_var.get(), int(read_var.get().split(" ")[0]), int(interested_var.get()), mal_id))
            self.conn.commit()
            win.destroy()
            self.refresh_recommendations()

        tk.Button(win, text="Save", command=save_changes).pack(pady=10)

if __name__ == "__main__":
    root = tk.Tk()
    app = RecommendationApp(root)
    root.mainloop()
