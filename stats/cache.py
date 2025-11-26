from functools import lru_cache, partial
import pickle

from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from pathlib import Path
import sys
import re

from typing import List

sys.path.append(str(Path(__file__).parent.parent))

from config import (
    FEMALE_SHORT_LEADERBOARD, 
    MALE_SHORT_LEADERBOARD,
    FEMALE_SHORT_EVENTS,
    MALE_SHORT_EVENTS,
    RACE_LOOKUP,
    ATHLETES_DIR,
    ATHLETE_LOOKUP
)

@lru_cache(maxsize=1)
def get_female_short_leaderboard():
    with open(FEMALE_SHORT_LEADERBOARD, "rb") as f:
        return pickle.load(f)
    
@lru_cache(maxsize=1)
def get_male_short_leaderboard():
    with open(MALE_SHORT_LEADERBOARD, "rb") as f:
        return pickle.load(f)
    
@lru_cache(maxsize=1)
def get_race_lookup():
    with open(RACE_LOOKUP, "rb") as f:
        return pickle.load(f)
    
@lru_cache(maxsize=1)
def get_athlete_lookup():
    import time
    start = time.time()
    with open(ATHLETE_LOOKUP, "rb") as f:
        data = pickle.load(f)
        end = time.time()
        print(f"Loaded athlete lookup in {end - start:.2f} seconds")
        return data
    
def process_single_athlete(athlete_file):
    """ Process a single athlete file and return the lookup data. """
    with open(athlete_file, "rb") as f:
        athlete_data = pickle.load(f)
        return athlete_data.athlete_id, {
            "name": athlete_data.name,
            "country_alpha3": athlete_data.country_alpha3,
            "country_emoji": athlete_data.country_emoji,
            "year_of_birth": athlete_data.year_of_birth,
        }    
    
def make_athlete_lookup():
    """ Parallel process athlete lookup creation. """
    athlete_files = list(ATHLETES_DIR.glob("*.pkl"))
    athlete_count = len(athlete_files)
    athlete_lookup = {}
    
    # Use all CPU cores
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_single_athlete, f): f for f in athlete_files}
        
        for i, future in enumerate(as_completed(futures), 1):
            print(f"Processing athlete {i}/{athlete_count}", end="\r")
            athlete_id, data = future.result()
            athlete_lookup[athlete_id] = data
    
    with open(ATHLETE_LOOKUP, "wb") as f:
        pickle.dump(athlete_lookup, f)
    
    print(f"\nSaved athlete lookup with {len(athlete_lookup)} entries.")
  
def process_single_race_guide(race_guide: Path):
    """Process a single event guide CSV and return partial race lookup."""
    skip_words = {
        'world', 'triathlon', 'championships', 'americas', 'europe', 'africa', 'asia', 'oceania',
        'cup', 'american', 'european', 'asian', 'games', 't100', 'tour', 'winter', 'development',
        'regional', 'african', 'para', 'itu', 'etu', 'atu', 'fisu', 'university', 'junior', 'north',
        'camtri', 'and', 'ntt', 'astc', 'premium'
    }

    guide_df = pd.read_csv(race_guide, parse_dates=["prog_date"], header=0)
    guide_df["prog_date"] = pd.to_datetime(guide_df["prog_date"], errors="coerce")

    partial_lookup = {}

    for _, row in guide_df.iterrows():
        race_handle = None
        title_words = str(row.race_title).split()
        year_suffix = f"{row.prog_date.year % 100:02d}"

        # 1) National championships
        if len(title_words) > 1 and re.match(r"^[A-Z]{3}$", title_words[1]) and title_words[1] != "ITU":
            race_handle = f"{title_words[1]} National Champs {year_suffix}"

        # 2) Short venue
        if race_handle is None and pd.notna(row.get("race_venue")):
            venue_words = (
                str(row.race_venue)
                .replace('"', "")
                .replace("'", "")
                .split()
            )
            if 0 < len(venue_words) <= 3:
                race_handle = f"{' '.join(venue_words)} {year_suffix}"

        # 3) Fallback from title
        if race_handle is None:
            candidates = [
                w for w in title_words[1:]
                if w and w.lower().strip(".,") not in skip_words
            ]
            race_handle = (
                f"{' '.join(candidates[:3])} {year_suffix}"
                if candidates else f"Event {row.prog_id} {year_suffix}"
            )

        partial_lookup[int(row.prog_id)] = (
            row.prog_date,
            row.race_title,
            race_handle,
            row.race_country,
            row.prog_name
        )

    return partial_lookup
  
def make_race_lookup(event_guides: List[Path], output_path: Path):
    """Parallel race lookup creation."""
    race_lookup = {}
    guide_count = len(event_guides)

    with ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(process_single_race_guide, guide): guide
            for guide in event_guides
        }

        for i, future in enumerate(as_completed(futures), 1):
            print(f"Processing race guide {i}/{guide_count}", end="\r")
            partial_lookup = future.result()
            race_lookup.update(partial_lookup)

    with open(output_path, "wb") as f:
        pickle.dump(race_lookup, f)

    print(f"\nSaved race lookup with {len(race_lookup)} entries.")
        
if __name__ == "__main__":
    make_athlete_lookup()
    make_race_lookup(
        event_guides = [FEMALE_SHORT_EVENTS, MALE_SHORT_EVENTS], 
        output_path = RACE_LOOKUP
    )