from functools import lru_cache, partial
import pickle

from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from pathlib import Path
import sys
import re
from typing import List

# sys.path.append(str(Path(__file__).parent.parent))
from stats.athlete import Athlete

from config import (
    RUNTIME_FEMALE_SHORT_LEADERBOARD_PATH,
    RUNTIME_MALE_SHORT_LEADERBOARD_PATH,
    FEMALE_SHORT_EVENTS_CSV_PATH,
    MALE_SHORT_EVENTS_CSV_PATH,
    RUNTIME_RACE_LOOKUP_PATH,
    RUNTIME_ATHLETES_DIR,
    RUNTIME_ATHLETE_LOOKUP_PATH,
    RUNTIME_COUNTRY_LIST_PATH
)

@lru_cache(maxsize=1)
def get_female_short_leaderboard() -> pd.DataFrame:
    with open(RUNTIME_FEMALE_SHORT_LEADERBOARD_PATH, "rb") as f:
        return pickle.load(f)
    
@lru_cache(maxsize=1)
def get_male_short_leaderboard() -> pd.DataFrame:
    with open(RUNTIME_MALE_SHORT_LEADERBOARD_PATH, "rb") as f:
        return pickle.load(f)
    
@lru_cache(maxsize=1)
def get_race_lookup():
    with open(RUNTIME_RACE_LOOKUP_PATH, "rb") as f:
        return pickle.load(f)
    
@lru_cache(maxsize=1)
def get_athlete_lookup():
    with open(RUNTIME_ATHLETE_LOOKUP_PATH, "rb") as f:
        return pickle.load(f)

@lru_cache(maxsize=1)
def get_country_list():
    with open(RUNTIME_COUNTRY_LIST_PATH, "rb") as f:
        return pickle.load(f)

def get_athlete_name(athlete_id: int):
    lookup: pd.DataFrame = get_athlete_lookup()
    return lookup.loc[athlete_id, "name"] if athlete_id in lookup.index else None

def process_single_athlete(athlete_file):
    """ Process a single athlete file and return the lookup data. """
    with open(athlete_file, "rb") as f:
        athlete_data = pickle.load(f)
        return athlete_data.athlete_id, {
            "name": athlete_data.name,
            "rating": athlete_data.overall_rating, # Save overall rating so results can be filtered
            "country_alpha3": athlete_data.country_alpha3,
            "country_emoji": athlete_data.country_emoji,
            "country_name": athlete_data.country_full,
            "year_of_birth": athlete_data.year_of_birth,
        }
    
def make_athlete_lookup():
    """ Parallel process athlete lookup creation. """
    athlete_files = list(RUNTIME_ATHLETES_DIR.glob("*.pkl"))
    athlete_count = len(athlete_files)
    athlete_lookup = {}
    
    # Use all CPU cores
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_single_athlete, f): f for f in athlete_files}
        
        for i, future in enumerate(as_completed(futures), 1):
            print(f"Processing athlete {i}/{athlete_count}", end="\r")
            athlete_id, data = future.result()
            athlete_lookup[athlete_id] = data
    
    # Convert to DataFrame for easy handling
    lookup_df: pd.DataFrame = pd.DataFrame.from_dict(athlete_lookup, orient = "index")
    lookup_df.index.name = "athlete_id"
    lookup_df.sort_values(by = "rating", ascending = False, inplace = True) # Pre-sort for fast searches

    with open(RUNTIME_ATHLETE_LOOKUP_PATH, "wb") as f:
        pickle.dump(lookup_df, f)
    
    # Make country list from all saved athletes
    make_country_list(athlete_lookup)

    print(f"\nSaved athlete lookup with {len(athlete_lookup)} entries.")
  
def make_country_list(athlete_lookup: dict) -> List[str]:
    """ Returns list of all countries for leaderboard filtering """
    countries = set()

    for _, v in athlete_lookup.items():
        countries.add(v["country_name"])

    with open(RUNTIME_COUNTRY_LIST_PATH, "wb") as f:
        pickle.dump(countries, f)

    print(f"Made country list with {len(countries)} countries")

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
        year_suffix = f"{row.prog_date.year % 100:02}"

        # 1) National championships
        if len(title_words) > 1 and re.match(r"^[A-Z]{3}$", title_words[1]) and title_words[1] != "ITU":
            race_handle = f"{title_words[1]} National Champs {year_suffix}"

        # 2) Short venue
        if race_handle is None and pd.notna(row.get("race_venue")):
            venue_words = (
                str(row.race_venue).replace('"', '').replace("'", '').split()
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
    """ Parallel race lookup creation. """
    race_lookup = {}

    with ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(process_single_race_guide, guide): guide
            for guide in event_guides
        }

        for _, future in enumerate(as_completed(futures), 1):
            partial_lookup = future.result()
            race_lookup.update(partial_lookup)

    with open(output_path, "wb") as f:
        pickle.dump(race_lookup, f)

    print(f"\nSaved race lookup with {len(race_lookup)} entries.")
        
if __name__ == "__main__":
    make_athlete_lookup()
    make_race_lookup(
        event_guides = [FEMALE_SHORT_EVENTS_CSV_PATH, MALE_SHORT_EVENTS_CSV_PATH],
        output_path = RUNTIME_RACE_LOOKUP_PATH
    )
