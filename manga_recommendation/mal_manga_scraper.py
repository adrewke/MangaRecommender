import requests
import json
import os
import time
from tqdm import tqdm
from definitions import DEFAULT_OUTPUT_FILE

JIKAN_API_URL = "https://api.jikan.moe/v4/manga"

def load_existing_dataset():
    if not os.path.exists(DEFAULT_OUTPUT_FILE):
        return [], set()
    with open(DEFAULT_OUTPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    existing_ids = {entry["mal_id"] for entry in data}
    return data, existing_ids

def add_user_fields(entry):
    if "user_data" not in entry:
        entry["user_data"] = {
            "score": None,
            "read": False
        }
    return entry

def fetch_manga_page(page):
    url = f"{JIKAN_API_URL}?page={page}&limit=25&order_by=mal_id&sort=asc"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 429:
        print("[RATE LIMIT] Waiting for 2 seconds...")
        time.sleep(2)
        return fetch_manga_page(page)
    else:
        print(f"[ERROR {response.status_code}] {response.text}")
        return None

def scrape_all_manga(existing_ids):
    all_new = []
    page = 1
    pbar = tqdm(desc="Fetching manga from Jikan")

    while True:
        data = fetch_manga_page(page)
        if not data or "data" not in data:
            break

        page_data = data["data"]
        if not page_data:
            break

        for entry in page_data:
            if entry["mal_id"] not in existing_ids:
                entry = add_user_fields(entry)
                all_new.append(entry)

        page += 1
        pbar.update(1)
        time.sleep(0.5)

    pbar.close()
    return all_new

def merge_and_deduplicate(old_data, new_data):
    combined = {entry["mal_id"]: entry for entry in old_data}
    for entry in new_data:
        if entry["mal_id"] in combined and "user_data" in combined[entry["mal_id"]]:
            entry["user_data"] = combined[entry["mal_id"]]["user_data"]
        else:
            entry = add_user_fields(entry)
        combined[entry["mal_id"]] = entry
    return list(combined.values())

def save_to_json(data, filename=DEFAULT_OUTPUT_FILE):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {len(data)} total manga entries to {filename}")

if __name__ == "__main__":
    print("📂 Loading existing manga dataset...")
    existing_data, existing_ids = load_existing_dataset()

    print("🌐 Scraping new manga entries from Jikan...")
    new_entries = scrape_all_manga(existing_ids)

    if new_entries:
        print(f"➕ Found {len(new_entries)} new manga entries. Merging and saving...")
        merged = merge_and_deduplicate(existing_data, new_entries)
        save_to_json(merged)
    else:
        print("✔️ No new entries found. Dataset is up to date.")
