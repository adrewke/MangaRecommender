# Manga Recommender
A personal manga recommendation system that allows users to explore, rate, and get intelligent suggestions based on their preferences. Built with Python and Tkinter, it uses data from MyAnimeList and MangaDex, and applies machine learning (Random Forest) for smarter predictions.

## Features

-  **Manga Search Tool** — Filter by genre, type, title, and view detailed metadata and images.
-  **Rating Interface** — Quickly rate series and mark your interest level (read, dropped, not interested).
-  **Recommendation Engine** — Learn your tastes and suggest new manga accordingly.
-  **Genre Filtering** — Avoid unwanted genres.
-  **Customizable Weights** — Fine-tune recommendation criteria (score, chapters, date).
-  **Genre Analysis** — Visualize your genre preferences over time.

## Programs

- **Manga Rating Gui** — Shows random manga inside selected genre. Can switch between genre and manga/manwha/manhua
- **Manga Search Gui** — Basic interface that allows searching and filtering of manga to rate and store
- **Manga Label Vectorization** — Creates labels based on your taste and then trains the Random Forest Algorithm
- **Manga Recommendation Gui** — Shows top 5 recommendations based on Random Forest.
## Setup

```bash
git clone https://github.com/adrewke/MangaRecommender.git
cd MangaRecommender
pip install -r requirements.txt

# Launch GUI for rating
python gui/manga_rating_gui.py

# Launch GUI for full search and editing
python gui/manga_search_gui.

#Once an adequate number of series have been rated (at least 60 positive and 60 negative) 
#run to generate labels and train random forest algorithm
python manga_recommendation/manga_label_vectorization.py

# Launch GUI for recommendations
python gui/manga_recommender_RF.py
```

## License
This project is licensed under the MIT License 


Built by Albert Drewke
