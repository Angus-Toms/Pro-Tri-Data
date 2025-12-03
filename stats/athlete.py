from datetime import datetime
from pathlib import Path
import sys
from typing import List, Tuple
from dataclasses import dataclass, asdict

import pandas as pd
import pycountry
import requests

# Add the project root to Python path so local config can be imported
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from config import (
    ATHLETE_IMG_DIR,
    ELITE_START_RATING,
    AG_START_RATING
)

def get_short_country_and_emoji(full_name: str) -> Tuple[str, str]:
    special_cases = {
        "Individual Neutral Athlete": ("INA", "🇺🇳"),
        "Great Britain": ("GBR", "🇬🇧"),
        "Republic of Korea": ("KOR", "🇰🇷"),
        "Czech Republic": ("CZE", "🇨🇿"),
        "Hong Kong, China": ("HKG", "🇭🇰"),
        "Russia": ("RUS", "🇷🇺"),
        "Syria": ("SYR", "🇸🇾"),
        "Macau, China": ("MAC", "🇲🇴"),
        "Venezuela": ("VEN", "🇻🇪"),
        "Chinese Taipei": ("TPE", "🇹🇼"),
        "Virgin Islands": ("ISV", "🇻🇮")
    }
    
    if full_name in special_cases.keys():
        return special_cases[full_name]
    
    country = pycountry.countries.get(name = full_name)
    if country is None:
        return ("UNK", "🏳️")
    return (country.alpha_3, country.flag)

@dataclass(slots=True)
class RaceResult:
    """
    Overall, Swim, bike, run, t1, t2 splits for a particular race
    All times measured in seconds.
    """
    race_id: int
    race_date: datetime
    position: str # Position can be 'DNF', 'DQ', 'LAP', or an integer as string
    
    # All splits potentially None if DNF/DQ/LAP
    overall_s: int 
    swim_s: int 
    bike_s: int
    run_s: int
    t1_s: int
    t2_s: int
    
    # Time behind leaders 
    # None if DNF/DQ/LAP
    overall_behind_s: int
    swim_behind_s: int
    bike_behind_s: int
    run_behind_s: int
    t1_behind_s: int
    t2_behind_s: int
    
    # Pct behind leaders
    # None if DNF/DQ/LAP
    overall_pct_behind: float
    swim_pct_behind: float
    bike_pct_behind: float
    run_pct_behind: float
    t1_pct_behind: float
    t2_pct_behind: float

@dataclass(slots=True)
class AthleteRating:
    """
    Represents the ratings of an athlete after a specific race.
    """
    race_id: int
    race_date: datetime
    overall_rating: float
    swim_rating: float
    bike_rating: float
    run_rating: float
    transition_rating: float
    
    # Changes
    overall_change: float = 0.0
    swim_change: float = 0.0
    bike_change: float = 0.0
    run_change: float = 0.0
    transition_change: float = 0.0

class Athlete:
    def __init__(self, athlete_id: int, name: str, country: str, year_of_birth: int, profile_img: str):        
        self.athlete_id: int = athlete_id
        self.name: str = name
        self.country_full: str = country
        short = get_short_country_and_emoji(country)
        self.country_alpha3: str = short[0]
        self.country_emoji: str = short[1]
        self.year_of_birth: int = int(year_of_birth) # YOB is 0 of not provided
        self.profile_img: str = profile_img # URL to profile image, empty string if no image available
        self.active: bool = True
        
        # Race stats
        self.race_starts: int = 0
        self.win_count: int = 0
        self.win_pct: float = 0.0
        self.podium_count: int = 0
        self.podium_pct: float = 0.0
        self.dnf_count: int = 0
        self.dnf_pct: float = 0.0
        self.dq_count: int = 0
        self.dq_pct: float = 0.0
        self.lap_count: int = 0   
        self.lap_pct: float = 0.0

        # Ratings
        self.overall_rating: float = float('-inf')
        self.swim_rating: float = float('-inf')
        self.bike_rating: float = float('-inf')
        self.run_rating: float = float('-inf')
        self.transition_rating: float = float('-inf')
        
        # Peaks 
        self.max_overall: float = self.overall_rating
        self.max_overall_race_id: int = float('-inf')
        self.max_swim: float = self.swim_rating
        self.max_swim_race_id: int = float('-inf')
        self.max_bike: float = self.bike_rating
        self.max_bike_race_id: int = float('-inf')
        self.max_run: float = self.run_rating
        self.max_run_race_id: int = float('-inf')
        self.max_transition: float = self.transition_rating
        self.max_transition_race_id: int = float('-inf')
        
        # Largest improvements
        self.overall_increase: float = float('-inf')
        self.overall_increase_race_id: int = 0
        self.swim_increase: float = float('-inf')
        self.swim_increase_race_id: int = 0
        self.bike_increase: float = float('-inf')
        self.bike_increase_race_id: int = 0
        self.run_increase: float = float('-inf')
        self.run_increase_race_id: int = 0
        self.transition_increase: float = float('-inf')
        self.transition_increase_race_id: int = 0

        # Changes in last year
        # 0 if no races in the last year
        self.overall_change_1yr: float = 0.0
        self.swim_change_1yr: float = 0.0
        self.bike_change_1yr: float = 0.0
        self.run_change_1yr: float = 0.0
        self.transition_change_1yr: float = 0.0

        # Rankings 
        self.overall_rank: int = -1
        self.swim_rank: int = -1
        self.bike_rank: int = -1
        self.run_rank: int = -1
        self.transition_rank: int = -1

        # Rating history
        self.rating_history: List[AthleteRating] = []
        
        # Times 
        self.race_results: List[RaceResult] = []

        self.try_get_profile_img()
        
    def try_get_profile_img(self) -> None:
        """
        Attempt to access and save athlete's profile image URL.
        """
        if self.profile_img:
            path = ATHLETE_IMG_DIR / f"{self.athlete_id}.jpg"
            if path.exists():
                return # Image already saved
            
            # Try to access the image URL
            try:
                response = requests.get(self.profile_img)
                if response.status_code == 200:
                    # Save the image or process it as needed
                    with open(path, 'wb') as f:
                        f.write(response.content)
                        
            except Exception as e:
                print(f"Error accessing profile image: {e}")

    def initialise_ratings(self, prog_name: str) -> None:
        """
        Initialise athlete ratings based on program name. Elites have higher starting ratings
        """
        prog_words = prog_name.lower().split() 
        if 'ag' in set(prog_words):
            self.overall_rating = AG_START_RATING
            self.swim_rating = AG_START_RATING
            self.bike_rating = AG_START_RATING
            self.run_rating = AG_START_RATING
            self.transition_rating = AG_START_RATING
        else:
            self.overall_rating = ELITE_START_RATING
            self.swim_rating = ELITE_START_RATING
            self.bike_rating = ELITE_START_RATING
            self.run_rating = ELITE_START_RATING
            self.transition_rating = ELITE_START_RATING

    def add_result(
        self,
        race_id: int,
        race_date: datetime,
        position: str,
        overall_s: int,
        swim_s: int,
        bike_s: int,
        run_s: int,
        t1_s: int,
        t2_s: int,
        fastest_overall_s: int,
        fastest_swim_s: int,
        fastest_bike_s: int,
        fastest_run_s: int,
        fastest_t1_s: int,
        fastest_t2_s: int,
    ) -> None:
        self.race_starts += 1
        
        # Update notable results                
        try:
            pos_int = int(position)
            if pos_int == 1:
                self.win_count += 1
            if pos_int <= 3:
                self.podium_count += 1
        except:
            pass

        try:
            if position.strip().upper() == "DNF":
                self.dnf_count += 1
            if position.strip().upper() == "DQ":
                self.dq_count += 1
            if position.strip().upper() == "LAP":
                self.lap_count += 1
        except:
            pass

        # Update percentages
        self.win_pct = self.win_count / self.race_starts
        self.podium_pct = self.podium_count / self.race_starts
        self.dnf_pct = self.dnf_count / self.race_starts
        self.dq_pct = self.dq_count / self.race_starts
        self.lap_pct = self.lap_count / self.race_starts
        
        # Calculate pct behind leaders
        self.race_results.append(
            RaceResult(
                race_id = race_id, 
                race_date = race_date, 
                position = position, 
                overall_s = overall_s,
                swim_s = swim_s,
                bike_s = bike_s,
                run_s = run_s,
                t1_s = t1_s,
                t2_s = t2_s,
                # Time behind leaders + checks in case of missing splits
                overall_behind_s = (overall_s - fastest_overall_s) if overall_s and fastest_overall_s else None,
                swim_behind_s = (swim_s - fastest_swim_s) if swim_s and fastest_swim_s else None,
                bike_behind_s = (bike_s - fastest_bike_s) if bike_s and fastest_bike_s else None,
                run_behind_s = (run_s - fastest_run_s) if run_s and fastest_run_s else None,
                t1_behind_s = (t1_s - fastest_t1_s) if t1_s and fastest_t1_s else None,
                t2_behind_s = (t2_s - fastest_t2_s) if t2_s and fastest_t2_s else None,
                # Pct behind leaders + checks in case of missing splits
                overall_pct_behind = ((overall_s - fastest_overall_s) / fastest_overall_s) if overall_s else None,
                swim_pct_behind = ((swim_s - fastest_swim_s) / fastest_swim_s) if swim_s else None,
                bike_pct_behind = ((bike_s - fastest_bike_s) / fastest_bike_s) if bike_s else None,
                run_pct_behind = ((run_s - fastest_run_s) / fastest_run_s) if run_s else None,
                t1_pct_behind = ((t1_s - fastest_t1_s) / fastest_t1_s) if t1_s else None,
                t2_pct_behind = ((t2_s - fastest_t2_s) / fastest_t2_s) if t2_s else None,
            )
        )

    def get_times_df(self) -> pd.DataFrame:
        """
        Convert race results to a DataFrame.
        """
        data = [asdict(result) for result in self.race_results]
        data = sorted(data, key = lambda x: x["race_date"], reverse = True) # Most recent events first
        return pd.DataFrame(data)
    
    def get_ratings_df(self) -> pd.DataFrame:
        """
        Convert rating history to a DataFrame.
        """
        data = [asdict(rating) for rating in self.rating_history[::-1]] # Reverse so most recent events first
        return pd.DataFrame(data)

    def update_rating(self, race_id: int, race_date: datetime, rating_changes: List[float], k_factor: float) -> None:
        """
        Apply rating changes (overall, swim, bike, run, transition) scaled by k_factor,
        update peaks, increment race_starts, and record the new rating entry.
        """
        if len(rating_changes) != 5:
            raise ValueError("rating_changes must contain exactly 5 elements for overall, swim, bike, run, and transition ratings.")

        # Compute scaled deltas once
        overall_delta, swim_delta, bike_delta, run_delta, transition_delta = (
            k_factor * rc for rc in rating_changes
        )

        # Compute new ratings
        new_overall = self.overall_rating + overall_delta
        new_swim = self.swim_rating + swim_delta
        new_bike = self.bike_rating + bike_delta
        new_run = self.run_rating + run_delta
        new_transition = self.transition_rating + transition_delta

        # Update peaks
        if new_overall > self.max_overall:
            self.max_overall = new_overall
            self.max_overall_race_id = race_id

        if new_swim > self.max_swim:
            self.max_swim = new_swim
            self.max_swim_race_id = race_id
        if new_bike > self.max_bike:
            self.max_bike = new_bike
            self.max_bike_race_id = race_id

        if new_run > self.max_run:
            self.max_run = new_run
            self.max_run_race_id = race_id
        if new_transition > self.max_transition:
            self.max_transition = new_transition
            self.max_transition_race_id = race_id

        # Update largest improvements (as long as their is some change)
        if overall_delta != 0 and overall_delta > self.overall_increase:
            self.overall_increase = overall_delta
            self.overall_increase_race_id = race_id
            
        if swim_delta != 0 and swim_delta > self.swim_increase:
            self.swim_increase = swim_delta
            self.swim_increase_race_id = race_id
            
        if bike_delta != 0 and bike_delta > self.bike_increase:
            self.bike_increase = bike_delta
            self.bike_increase_race_id = race_id
            
        if run_delta != 0 and run_delta > self.run_increase:  
            self.run_increase = run_delta
            self.run_increase_race_id = race_id
            
        if transition_delta != 0 and transition_delta > self.transition_increase:
            self.transition_increase = transition_delta
            self.transition_increase_race_id = race_id
            
        # Assign new ratings
        self.overall_rating = new_overall
        self.swim_rating = new_swim
        self.bike_rating = new_bike
        self.run_rating = new_run
        self.transition_rating = new_transition

        self.rating_history.append(
            AthleteRating(
                race_id = race_id,
                race_date = race_date,
                overall_rating = self.overall_rating,
                swim_rating = self.swim_rating,
                bike_rating = self.bike_rating,
                run_rating = self.run_rating,
                transition_rating = self.transition_rating,
                overall_change = overall_delta,
                swim_change = swim_delta,
                bike_change = bike_delta,
                run_change = run_delta,
                transition_change = transition_delta,
            )
        )

    def get_1yr_changes(self) -> None:
        """
        Calculate rating changes over the last year
        """
        if not self.rating_history:
            return
        
        today = datetime.now()
        yr_ago = today.replace(year = today.year - 1)

        # Find the oldest race in the last year
        # 0 change if no races completed in last year
        past_overall = 0.0
        past_swim = 0.0
        past_bike = 0.0
        past_run = 0.0
        past_transition = 0.0
        for rating in reversed(self.rating_history):
            if rating.race_date < yr_ago:
                break 

            past_overall = rating.overall_rating
            past_swim = rating.swim_rating
            past_bike = rating.bike_rating
            past_run = rating.run_rating
            past_transition = rating.transition_rating

        self.overall_change_1yr = self.overall_rating - past_overall
        self.swim_change_1yr = self.swim_rating - past_swim
        self.bike_change_1yr = self.bike_rating - past_bike
        self.run_change_1yr = self.run_rating - past_run
        self.transition_change_1yr = self.transition_rating - past_transition