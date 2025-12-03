import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
import math
import os
from collections import defaultdict
from ast import literal_eval
import pickle
from tqdm import tqdm

from pathlib import Path

from athlete import Athlete
from race import Race

from stats.cache import make_athlete_lookup, make_race_lookup

from config import (
    FEMALE_SHORT_EVENTS,
    MALE_SHORT_EVENTS,
    FEMALE_SHORT_LEADERBOARD,
    MALE_SHORT_LEADERBOARD,
    ATHLETES_DIR,
    RACES_DIR,
    FEMALE_SHORT_DIR,
    MALE_SHORT_DIR,
    CORRECTIONS,
    ATHLETE_LOOKUP,
    RACE_LOOKUP,
    WARNINGS,
    IGNORED_RACES
)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

"""
After full reloads, remember the following need manual changes:
TODO: Manual change for park: 675869
307376.csv - Later athletes missing hour in overall times
"""

class TriathlonELOSystem:
    """
    ELO rating system for triathlon athletes using Athlete objects.
    """
    def __init__(self, 
                 k_factor: float, 
                 race_guide_file: Path, 
                 race_dir: Path,
                 corrections_file: Path = CORRECTIONS,
                 ignored_file: Path = IGNORED_RACES
        ):
        """
        Initialize the ELO system.
        
        Args:
            k_factor: ELO K-factor for rating adjustment magnitude
            race_guide_file: Path to CSV file with key race info 
            race_dir: Directory containing race CSVs
            corrections_file: Path to csv containing manual race corrections
            ignored_file: Path to csv containing races to be ignored from calculations
        """
        self.scale: float = 46175.8
        self.k_factor: float = k_factor
        self.athletes: Dict[int, Athlete] = {}  
        self.races: Dict[int, Race] = {}
        self.progs: pd.DataFrame = pd.read_csv(race_guide_file)
        self.race_dir: Path = race_dir
        
        # Load manual corrections from file
        self.corrections_df = pd.read_csv(corrections_file, header = 0)
        self.correction_race_ids = set(self.corrections_df['race_id'])
        
        # Load races to be ignored from file
        self.ignored_df = pd.read_csv(ignored_file, header = 0)
        self.ignored_race_ids = set(self.ignored_df['race_id'])
        
    def process_all_races(self) -> None:
        race_count = len(self.progs)
        print(f"Found {race_count} races to process.")
                
        race_count = len(self.progs)
        for _, row in tqdm(enumerate(self.progs.itertuples()), total = race_count, desc = "Processing races", unit = "race"):
            if row.prog_id in self.ignored_race_ids:
                tqdm.write(f"Skipping ignored race ID: {row.prog_id}")
                continue
            
            fname: Path = self.race_dir / f"{row.prog_id}.csv"
            
            if fname.exists():
                race: Race = Race(
                    race_id = row.prog_id,
                    race_title = row.race_title,
                    prog_name = row.prog_name,
                    date = datetime.strptime(row.prog_date, '%Y-%m-%d'),
                    location = str(row.race_venue),
                    country = str(row.race_country)
                )
                self.races[row.prog_id] = race
                self.process_single_race(fname, row)
            else:
                tqdm.write(f"Warning: {fname} does not exist, skipping")
                
    def process_single_race(self, file_path: str, prog_row) -> None:
        try:
            race_id = prog_row.prog_id
            
            race_df = self.load_race_data(file_path)
            race_df = self.prepare_race_data(race_df)
            
            race: Race = self.races[race_id] # TODO: Move race init to here, populate in make_race as usual but pass race to corrections method so we can store 
            
            if race_id in self.correction_race_ids:
                # Find corrections to be applied to this race
                corrections = self.corrections_df[self.corrections_df['race_id'] == race_id]
                race_df = self.make_corrections(race, race_df, corrections)
            
            if len(race_df) < 2:
                tqdm.write(f"<2 results in {file_path}, skipping.")
                return
            
            race_date = datetime.strptime(prog_row.prog_date, '%Y-%m-%d')
            
            # Store race results and get athlete data
            prog_name = str(prog_row.prog_name) # Pass prog name so we can initialise AG vs. Elites correctly
            athlete_data = self.make_race_and_athletes(race_df, race_id, race_date, prog_name)
            
            # Calculate ELO changes
            elo_changes = self.calculate_elo_changes(athlete_data)
            
            # Store rating changes in Race
            self.store_race_ratings(race_id, athlete_data, elo_changes)
            
            # Update Athlete ratings
            self.update_athlete_ratings(elo_changes, race_id, race_date)
            
        except Exception as e:
            print(f"Error processing file {file_path}: {str(e)}")
            
    def load_race_data(self, file_path: str) -> pd.DataFrame:
        """ Load and do initial cleaning from CSV """
        race_df = pd.read_csv(
            file_path,
            keep_default_na = False,
            na_values = [],
            low_memory = False
        )
        
        # Set data types 
        race_df["athlete_id"] = race_df["athlete_id"].astype(int)
        race_df['athlete_yob'] = (
            pd.to_numeric(race_df['athlete_yob'], errors = "coerce")
            .fillna(0)
            .astype(int)
        )
        race_df["start_num"] = (
            pd.to_numeric(race_df["start_num"], errors = "coerce")
            .fillna(0)
            .astype(int)
        )
        
        return race_df
    
    def prepare_race_data(self, race_df: pd.DataFrame) -> pd.DataFrame:
        """ Time conversion, DNS/DNF/DQ handling """
        # Remove quotation marks from names
        race_df['athlete_title'] = race_df['athlete_title'].str.replace('"', '').str.replace("'", "")
        
        # Expand splits list and convert to seconds
        race_df['split'] = race_df['splits'].apply(literal_eval)
        
        race_df[['swim_s', 't1_s', 'bike_s', 't2_s', 'run_s']] = (
            race_df['split']
            .apply(lambda lst: [self.time_to_seconds(x) for x in lst])
            .apply(pd.Series)
        )
        race_df['overall_s'] = race_df['total_time'].apply(self.time_to_seconds)
        
        # Remove all splits in case of DNF/DQ/LAP
        dnf_mask = race_df['overall_s'] == 0
        split_cols = ['swim_s', 't1_s', 'bike_s', 't2_s', 'run_s']
        race_df.loc[dnf_mask, split_cols] = 0
        
        # Combine transition times (skip if either is missing)
        race_df['transition_s'] = (race_df['t1_s'] + race_df['t2_s']).where(
            (race_df['t1_s'] != 0) & (race_df['t2_s'] != 0), 
            0
        )
        
        # Remove any with invalid time conversions
        race_df = race_df[
            (race_df['overall_s'] != float('inf')) &
            (race_df['swim_s'] != float('inf')) &
            (race_df['bike_s'] != float('inf')) &
            (race_df['run_s'] != float('inf')) &
            (race_df['transition_s'] != float('inf'))
        ]
        
        return race_df
    
    def make_corrections(self, race_df: pd.DataFrame, corrections: pd.DataFrame) -> pd.DataFrame:
        """ 
        Apply corrections from the argument corrections df to the race df
        
        corrections has cols (race_id, athlete_id, swim, t1, bike, t2, run, overall, notes)
        All times in HH:MM:SS
        """
        for _, row in corrections.iterrows(): 
            mask = race_df['athlete_id'] == row.athlete_id
            
            race_df.loc[mask, 'overall_s'] = self.time_to_seconds(row['overall'])
            race_df.loc[mask, 'swim_s'] = self.time_to_seconds(row['swim'])
            race_df.loc[mask, 'bike_s'] = self.time_to_seconds(row['bike'])
            race_df.loc[mask, 'run_s'] = self.time_to_seconds(row['run'])
            
            # Only set transition if both splits are available
            t1_s, t2_s = self.time_to_seconds(row['t1']), self.time_to_seconds(row['t2'])
            race_df.loc[mask, 'transition_s'] = t1_s + t2_s if t1_s != 0 and t2_s != 0 else 0
            
            tqdm.write(f"Applied corrections to athlete {row.athlete_id} in race {row.race_id}")
        
        return race_df
    
    def make_race_and_athletes(self, race_df: pd.DataFrame, race_id: int, race_date: datetime, prog_name: str) -> Dict:
        """
        Store race results and athlete data, return data needed for ELO calculations.

        Args:
            race_df: DataFrame of results including athletes, splits, positions and overall times
            race_id: int ID
            race_date: datetime of the race
            prog_name: Name of the program (e.g., "AG" or "Elites") to initialise athletes correctly

        Returns:
            athlete_data: Dict mapping athlete_id to (ratings, times) tuples
        """
        race: Race = self.races[race_id]
        athlete_data = {}
        
        fastest_splits = self.get_fastest_splits(race_df)
        
        for _,row in race_df.iterrows():
            athlete_id = row['athlete_id']
            
            athlete = self.get_or_create_athlete(row)
            # Set initial ratings for new athletes based on program
            if athlete.overall_rating == float('-inf'):
                athlete.initialise_ratings(prog_name)

            # Save to Race
            race.add_result(
                athlete_id = athlete_id,
                position = row['position'],
                overall_s = row['overall_s'],
                swim_s = row['swim_s'],
                bike_s = row['bike_s'],
                run_s = row['run_s'],
                t1_s = row['t1_s'],
                t2_s = row['t2_s'],
                **fastest_splits
            )
            
            # Save to Athlete
            athlete.add_result(
                race_id = race_id,
                race_date = race_date,
                position = row['position'],
                overall_s = row['overall_s'],
                swim_s = row['swim_s'],
                bike_s = row['bike_s'],
                run_s = row['run_s'],
                t1_s = row['t1_s'],
                t2_s = row['t2_s'],
                **fastest_splits
            )
            
            # Store times/ratings for ELO calculations
            ratings = [
                athlete.overall_rating,
                athlete.swim_rating,
                athlete.bike_rating,
                athlete.run_rating,
                athlete.transition_rating
            ]
            times = row[['overall_s', 'swim_s', 'bike_s', 'run_s', 'transition_s']].values
            athlete_data[athlete_id] = (ratings, times)
        
        return athlete_data
    
    def get_fastest_splits(self, race_df: pd.DataFrame) -> Dict[str, float]:
        """ Get fastest splits for % behind leader calculations, ignore 0s """
        return {
            "fastest_overall_s": race_df[race_df['overall_s'] > 0]['overall_s'].min(),
            "fastest_swim_s": race_df[race_df['swim_s'] > 0]['swim_s'].min(),
            "fastest_bike_s": race_df[race_df['bike_s'] > 0]['bike_s'].min(),
            "fastest_run_s": race_df[race_df['run_s'] > 0]['run_s'].min(),
            "fastest_t1_s": race_df[race_df['t1_s'] > 0]['t1_s'].min(),
            "fastest_t2_s": race_df[race_df['t2_s'] > 0]['t2_s'].min()
        }
        
    def get_or_create_athlete(self, row) -> Athlete:
        """
        Get existing Athlete object or create a new one from single result row.
        """
        athlete_id = row['athlete_id']
        if athlete_id not in self.athletes:
            self.athletes[athlete_id] = Athlete(
                athlete_id = athlete_id,
                name = row['athlete_title'],
                country = row['athlete_country_name'],
                year_of_birth = row['athlete_yob'],
                profile_img = row['athlete_profile_image']
            )
        return self.athletes[athlete_id]
    
    def calculate_elo_changes(self, athlete_data: Dict) -> Dict[int, List[float]]:
        """
        Calculate pairwise ELO changes for all athletes in race.
        
        Args:
            athlete_data: Dict mapping athlete_id to (ratings, times) tuples
            Ratings and times correspond to [overall, swim, bike, run, transition]
        Returns:
            Dict mapping athlete_id to list of ELO changes
        """
        athlete_ids = list(athlete_data.keys())
        elo_changes = {athlete_id: [0.0] * 5 for athlete_id in athlete_ids}
        num_athletes = len(athlete_ids)
        
        for i in range(num_athletes):
            id1 = athlete_ids[i]
            ratings1, times1 = athlete_data[id1]
            
            # Test for dangerously short times
            for disc in range(4):
                discs = ["overall", "swim","bike", "run"]
                if times1[disc] != 0 and times1[disc] < 180:
                    warnings_df = pd.read_csv(WARNINGS, header = 0)
                    warnings_df.loc[len(warnings_df)] = {
                        "athlete_id": id1,
                        "discipline": discs[disc]
                    }
                    warnings_df.to_csv(WARNINGS, index = False)
            
            for j in range(i + 1, num_athletes):
                id2 = athlete_ids[j]
                ratings2, times2 = athlete_data[id2]
                
                # Iterate through disciplines
                for k in range(5):
                    time1, time2 = times1[k], times2[k]
                    
                    # Skip if either time is invalid
                    if time1 in set([float('inf'), 0]) or time2 in set([float('inf'), 0]):
                        continue
                    
                    change = self.get_logtime_elo(ratings1[k], ratings2[k], time1, time2)
                    elo_changes[id1][k] += change
                    elo_changes[id2][k] -= change
                    
        return elo_changes
    
    def store_race_ratings(self, race_id: int, athlete_data: Dict, elo_changes: Dict[int, List[float]]) -> None:
        """
        Store ratings (post-race) and changes in Race object.
        
        Args:
            race_id: ID
            athlete_data: Dict mapping athlete_id to (ratings, times) tuples
            elo_changes: Dict mapping athlete_id to list of ELO changes
        """
        race = self.races[race_id]
        
        for athlete_id, changes in elo_changes.items():
            original_ratings = athlete_data[athlete_id][0]
            race.add_rating(athlete_id, *original_ratings, *changes, self.k_factor)
  
    def get_logtime_elo(self, rating1: float, rating2: float, time1: int, time2: int) -> float:
        """
        Compute Elo change using log time-ratio.
        
        Args:
            rating1, rating2: Elo ratings before race
            time1, time2: Finish times in seconds
            scale: Scale for particular discipline

        Returns:
            Elo rating change for athlete 1
        """
        # Expected log-time difference
        rating_diff = rating1 - rating2
        expected_log_ratio = (rating_diff / self.scale) * math.log(10) 

        # Actual log-time difference (positive means athlete1 is faster)
        try:
            actual_log_ratio = math.log(time2 / time1)
        except (ValueError, ZeroDivisionError):
            actual_log_ratio = 0.0

        # Measure surprise in log-ratio space
        return actual_log_ratio - expected_log_ratio
        
    def update_athlete_ratings(self, elo_changes: Dict[int, List[float]], race_prog_id: int, race_date: datetime):
        """
        Update athlete ratings based on calculated ELO changes using Athlete objects.
        """
        for athlete_id, changes in elo_changes.items():
            athlete = self.athletes[athlete_id]
            athlete.update_rating(race_prog_id, race_date, changes, self.k_factor)
    
    def get_leaderboard(self, top_n: int = 50) -> pd.DataFrame:
        """
        Get current ELO leaderboard using Athlete objects.
        """
        leaderboard_data = []
        for athlete in self.athletes.values():
            leaderboard_data.append({
                'Athlete ID': athlete.athlete_id,
                'Name': athlete.name,
                'Country': athlete.country_full,
                'Overall Rating': round(athlete.overall_rating, 2),
                'Swim Rating': round(athlete.swim_rating, 2),
                'Bike Rating': round(athlete.bike_rating, 2),
                'Run Rating': round(athlete.run_rating, 2),
                'Transition Rating': round(athlete.transition_rating, 2),
                'Races Starts': athlete.race_starts
            })
            
        leaderboard_df = pd.DataFrame(leaderboard_data)
        leaderboard_df = leaderboard_df.sort_values('Overall Rating', ascending=False)
        return leaderboard_df.head(top_n)

    def save_athlete_data(self, dir_path: Path):
        """ Save all athletes' data as separate pkl files """
        for athlete_id, athlete in self.athletes.items():
            fname = dir_path / f"{athlete_id}.pkl"
            
            if os.path.exists(fname):
                os.remove(fname)
            
            with open(fname, 'wb') as f:
                pickle.dump(athlete, f)
                
        print(f"Saved athlete data to {dir_path}")
        
    def save_race_data(self, dir_path: Path):
        """ Save all races' data as separate pkl files """
        for race_id, race in self.races.items():
            fname = dir_path / f"{race_id}.pkl"
            
            if os.path.exists(fname):
                os.remove(fname)
                
            with open(fname, 'wb') as f:
                pickle.dump(race, f)
                
        print(f"Saved race data to {dir_path}")

    def time_to_seconds(self, time_str: str) -> float:
        """
        Convert various time string formats to seconds.
        Returns 0 for DNF/DNS/DQ/LAP, float('inf') for invalid/missing times.
        """
        try:
            # Older events include empty string splits, treat as 0 and they won't
            # be included in later ELO calculations
            # For DNF/DNS/DQ/LAP/NC, also return 0 to ignore from later calcs
            if time_str in set(['None', '', 'DNF', 'DQ', 'LAP', 'NC']):
                return 0
            
            if pd.isna(time_str):
                return float('inf')
            
            parts = time_str.strip().split(':')
            if len(parts) == 3: # HH:MM:SS format
                hours, minutes, seconds = map(float, parts)
                return hours * 3600 + minutes * 60 + seconds
            elif len(parts) == 2: # MM:SS format
                minutes, seconds = map(float, parts)
                return minutes * 60 + seconds
            elif len(parts) == 1: # SS format
                return float(parts[0])
            else:   
                return float('inf')
        except:
            return float('inf')

    def perform_athlete_postprocessing(self) -> None:
        self.set_athlete_active_status()
        self.set_1yr_change()

    def set_athlete_active_status(self) -> None:
        for _, athlete in self.athletes.items():
            # Athletes are active by default
            if athlete.rating_history == []:
                athlete.active = False
                continue
            
            last_race_date = athlete.rating_history[-1].race_date
            diff = datetime.now() - last_race_date
            athlete.active = diff < timedelta(days = 365 * 2)

    def set_1yr_change(self) -> None:
        for _, athlete in self.athletes.items():
            athlete.get_1yr_changes()
      
    def perform_race_postprocessing(self) -> None:
        for _, race in self.races.items():
            race.get_discipline_standards()  
            
    def make_leaderboard(self, leaderboard_path: str) -> None:
        """ 
        Create leaderboard dict and save to pickle.
        Also save ranks directly to Athlete for fast access 
        
        Args:
            leaderboard_path: Path to save leaderboard pickle
        """
        leaderboard_data = {}
        
        for athlete_id, athlete in self.athletes.items():
            leaderboard_data[athlete.athlete_id] = {
                "athlete_id": athlete.athlete_id,
                "profile_img_exists": athlete.profile_img != '',
                "name": athlete.name,
                "country_full": athlete.country_full,
                "country_alpha3": athlete.country_alpha3,
                "country_emoji": athlete.country_emoji,
                "year_of_birth": athlete.year_of_birth,
                "overall_rating": round(athlete.overall_rating),
                "swim_rating": round(athlete.swim_rating),
                "bike_rating": round(athlete.bike_rating),
                "run_rating": round(athlete.run_rating),
                "transition_rating": round(athlete.transition_rating),
                "race_starts": athlete.race_starts,
                "win_count": athlete.win_count,
                "active": athlete.active
            }
            
        # Find leaderboard postitions for each discipline
        rankings_by_discipline = {
            "overall": [],
            "swim": [],
            "bike": [],
            "run": [],
            "transition": []
        }
        
        for athlete_id, athlete in self.athletes.items():
            rankings_by_discipline["overall"].append((athlete_id, athlete.overall_rating))
            rankings_by_discipline["swim"].append((athlete_id, athlete.swim_rating))
            rankings_by_discipline["bike"].append((athlete_id, athlete.bike_rating))
            rankings_by_discipline["run"].append((athlete_id, athlete.run_rating))
            rankings_by_discipline["transition"].append((athlete_id, athlete.transition_rating))
            
        ranks = defaultdict(dict)
        for discipline, rankings in rankings_by_discipline.items():
            for rank, (athlete_id, _) in enumerate(sorted(rankings, key = lambda x: x[1], reverse = True), 1):
                ranks[athlete_id][f"{discipline}_rank"] = rank 
            
        with open(leaderboard_path, 'wb') as f:
            pickle.dump(leaderboard_data, f)
            
        print(f"Saved leaderboard to {leaderboard_path}")

        # Save ranks to Athlete objects
        self.save_ranks_to_athletes(ranks)

    def save_ranks_to_athletes(self, ranks: Dict[int, Dict[str, int]]) -> None:
        """ 
        Save rankings directly to Athlete objects for fast access 
        
        Args:
            ranks: Dict mapping athlete_id to dict of rankings per discipline. Example format:
            {
                athlete_id: {
                    "overall_rank": int,
                    "swim_rank": int,
                    "bike_rank": int,
                    "run_rank": int,
                    "transition_rank": int
                },
                ...
        """
        for athlete_id, athlete_ranks in ranks.items():
            athlete = self.athletes.get(athlete_id, None)
            if athlete is not None:
                athlete.overall_rank = athlete_ranks.get("overall_rank", -1)
                athlete.swim_rank = athlete_ranks.get("swim_rank", -1)
                athlete.bike_rank = athlete_ranks.get("bike_rank", -1)
                athlete.run_rank = athlete_ranks.get("run_rank", -1)
                athlete.transition_rank = athlete_ranks.get("transition_rank", -1)

def main():
    female_short_elo = TriathlonELOSystem(k_factor = 16, race_guide_fname = FEMALE_SHORT_EVENTS, race_dir = FEMALE_SHORT_DIR)
    female_short_elo.process_all_races()
    female_short_elo.perform_athlete_postprocessing()
    female_short_elo.make_leaderboard(FEMALE_SHORT_LEADERBOARD)
    female_short_elo.save_athlete_data(ATHLETES_DIR)
    female_short_elo.save_race_data(RACES_DIR)
    
    male_short_elo = TriathlonELOSystem(k_factor = 16, race_guide_fname = MALE_SHORT_EVENTS, race_dir = MALE_SHORT_DIR)
    male_short_elo.process_all_races()
    male_short_elo.perform_athlete_postprocessing()
    male_short_elo.make_leaderboard(MALE_SHORT_LEADERBOARD)
    male_short_elo.save_athlete_data(ATHLETES_DIR)
    male_short_elo.save_race_data(RACES_DIR)
    
    # athlete_count = len(female_short_elo.athletes) + len(male_short_elo.athletes)
    # print(f"Total athletes processed: {athlete_count}")
    
    # race_count = len(female_short_elo.races) + len(male_short_elo.races)
    # print(f"Total races processed: {race_count}")
    
    # # # Rebuild athlete lookup after all athletes have been updated
    # make_athlete_lookup()
    # # Rebuild race lookups
    # make_race_lookup(
    #     event_guides = [FEMALE_SHORT_EVENTS, MALE_SHORT_EVENTS],
    #     output_path = RACE_LOOKUP
    # )

if __name__ == "__main__":
    main()
