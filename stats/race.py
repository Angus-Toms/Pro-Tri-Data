from datetime import datetime
from dataclasses import dataclass
from typing import List

import pandas as pd
import numpy as np

@dataclass(slots=True)
class Correction:
    athlete_id: int
    position: str # String position to accomodate DNF/DNS/LAP/NC
    
    # Splits in seconds, 0 if case of DNF/DNS/LAP/NC
    prev_overall_s: int
    prev_swim_s: int 
    prev_bike_s: int 
    prev_run_s: int 
    prev_t1_s: int 
    prev_t2_s: int
    
    # Corrected splits, same format
    overall_s: int 
    swim_s: int
    bike_s: int 
    run_s: int 
    t1_s: int 
    t2_s: int
    
    # Reason / explanation for result correction
    note: str

@dataclass(slots=True)
class IndividualResult:
    athlete_id: int
    position: str # String position to accommodate DNF/DQ/LAP
    
    # Splits in seconds, 0 in case of DNF/DNS/LAP/NC
    overall_s: int
    swim_s: int
    bike_s: int
    run_s: int 
    t1_s: int
    t2_s: int
    
    # None if missing splits or DNF/DQ/LAP
    overall_behind_s: int
    swim_behind_s: int
    bike_behind_s: int 
    run_behind_s: int 
    t1_behind_s: int 
    t2_behind_s: int
    
@dataclass(slots=True)
class IndividualRating:
    athlete_id: int
    
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
    
class Race:
    def __init__(self, race_id: int, race_title: str, prog_name: str, date: datetime, location: str, country: str):
        self.race_id: int = race_id
        self.race_title: str = race_title
        self.prog_name: str = prog_name
        self.date: datetime = date
        self.location: str = location
        self.country: str = country
        self.athlete_count: int = 0
        
        self.results: List[IndividualResult] = []
        self.ratings: List[IndividualRating] = []
        
        # Best individual performances for each discipline
        self.overall_increase: float = float('-inf')
        self.overall_increase_athlete_id: int = -1
        self.swim_increase: float = float('-inf')
        self.swim_increase_athlete_id: int = -1
        self.bike_increase: float = float('-inf')
        self.bike_increase_athlete_id: int = -1
        self.run_increase: float = float('-inf')
        self.run_increase_athlete_id: int = -1
        self.transition_increase: float = float('-inf')
        self.transition_increase_athlete_id: int = -1
        
        # Standards - average rating of top 10 for each discipline
        self.overall_standard: float = 0
        self.swim_standard: float = 0
        self.bike_standard: float = 0
        self.run_standard: float = 0
        self.transition_standard: float = 0
        
        # Corrections
        self.corrections: List[Correction] = []
    
    def add_result(self, athlete_id: int, position: str, overall_s: int, swim_s: int, bike_s: int, run_s: int, t1_s: int, t2_s: int, fastest_overall_s: int, fastest_swim_s: int, fastest_bike_s: int, fastest_run_s: int, fastest_t1_s: int, fastest_t2_s: int):
        self.athlete_count += 1
        
        self.results.append(
            IndividualResult(
                athlete_id = athlete_id,
                position = position,
                overall_s = overall_s,
                swim_s = swim_s,
                bike_s = bike_s,
                run_s = run_s,
                t1_s = t1_s,
                t2_s = t2_s,
                overall_behind_s = (overall_s - fastest_overall_s) if overall_s and fastest_overall_s else None,
                swim_behind_s = (swim_s - fastest_swim_s) if swim_s and fastest_swim_s else None,
                bike_behind_s = (bike_s - fastest_bike_s) if bike_s and fastest_bike_s else None,
                run_behind_s = (run_s - fastest_run_s) if run_s and fastest_run_s else None,
                t1_behind_s = (t1_s - fastest_t1_s) if t1_s and fastest_t1_s else None,
                t2_behind_s = (t2_s - fastest_t2_s) if t2_s and fastest_t2_s else None
            )
        )
        
    def add_rating(self, athlete_id: int, overall_rating: float, swim_rating: float, bike_rating: float, run_rating: float, transition_rating: float, overall_change: float, swim_change: float, bike_change: float, run_change: float, transition_change: float, k_factor: float):
        overall_delta = overall_change * k_factor
        swim_delta = swim_change * k_factor
        bike_delta = bike_change * k_factor
        run_delta = run_change * k_factor
        transition_delta = transition_change * k_factor
        
        self.ratings.append(
            IndividualRating(
                athlete_id = athlete_id,
                overall_rating = overall_rating + overall_delta,
                swim_rating = swim_rating + swim_delta,
                bike_rating = bike_rating + bike_delta,
                run_rating = run_rating + run_delta,
                transition_rating = transition_rating + transition_delta,
                overall_change = overall_delta,
                swim_change = swim_delta,
                bike_change = bike_delta,
                run_change = run_delta,
                transition_change = transition_delta
            )
        )
        
        if overall_delta != 0 and overall_delta > self.overall_increase:
            self.overall_increase = overall_delta
            self.overall_increase_athlete_id = athlete_id
            
        if swim_delta != 0 and swim_delta > self.swim_increase:
            self.swim_increase = swim_delta
            self.swim_increase_athlete_id = athlete_id
            
        if bike_delta != 0 and bike_delta > self.bike_increase:
            self.bike_increase = bike_delta
            self.bike_increase_athlete_id = athlete_id 
            
        if run_delta != 0 and run_delta > self.run_increase:
            self.run_increase = run_delta
            self.run_increase_athlete_id = athlete_id
        
        if transition_delta != 0 and transition_delta > self.transition_increase:
            self.transition_increase = transition_delta
            self.transition_increase_athlete_id = athlete_id    
            
    def get_discipline_standards(self) -> None:
        """Set standards based on top 10 highest-rated athletes per discipline"""
        
        # Get top 10 athletes by overall rating
        top_overall = sorted(self.ratings, key = lambda x: x.overall_rating, reverse = True)[:10]
        self.overall_standard = sum(r.overall_rating for r in top_overall) / len(top_overall)
        
        top_swim = sorted(self.ratings, key = lambda x: x.swim_rating, reverse = True)[:10]
        self.swim_standard = sum(r.swim_rating for r in top_swim) / len(top_swim)
        
        top_bike = sorted(self.ratings, key = lambda x: x.bike_rating, reverse = True)[:10]
        self.bike_standard = sum(r.bike_rating for r in top_bike) / len(top_bike)
        
        top_run = sorted(self.ratings, key = lambda x: x.run_rating, reverse = True)[:10]
        self.run_standard = sum(r.run_rating for r in top_run) / len(top_run)
        
        top_transition = sorted(self.ratings, key = lambda x: x.transition_rating, reverse = True)[:10]
        self.transition_standard = sum(r.transition_rating for r in top_transition) / len(top_transition)
      
    def get_times_df(self) -> pd.DataFrame:
        """ Return splits as dataframe, convert 0s (no split time) to NaNs for processing """
        return pd.DataFrame([
            {
                "athlete_id": r.athlete_id,
                "overall_s": r.overall_s if r.overall_s > 0 else np.nan,
                "swim_s": r.swim_s if r.swim_s > 0 else np.nan,
                "bike_s": r.bike_s if r.bike_s > 0 else np.nan,
                "run_s": r.run_s if r.run_s > 0 else np.nan,
                "t1_s": r.t1_s if r.t1_s > 0 else np.nan,
                "t2_s": r.t2_s if r.t2_s > 0 else np.nan
            }
            for r in self.results
        ])  
        
    def get_mean_times(self) -> dict:
        """ Calculates mean times for each discipline. """
        times_df = self.get_times_df()
        
        return {
            "overall": times_df['overall_s'].dropna().mean(),
            "swim": times_df['swim_s'].dropna().mean(),
            "bike": times_df['bike_s'].dropna().mean(),
            "run": times_df['run_s'].dropna().mean(),
            "t1": times_df['t1_s'].dropna().mean(),
            "t2": times_df['t2_s'].dropna().mean()
        }    
        
    def get_time_histograms(self, bins: int = 10) -> dict:
        """ 
        Prepares time histogram data for each discipline. 
        """
        times_df = self.get_times_df()
        
        return {
            "overall": np.histogram(times_df['overall_s'].dropna(), bins=bins),
            "swim": np.histogram(times_df['swim_s'].dropna(), bins=bins),
            "bike": np.histogram(times_df['bike_s'].dropna(), bins=bins),
            "run": np.histogram(times_df['run_s'].dropna(), bins=bins),
            "t1": np.histogram(times_df['t1_s'].dropna(), bins=bins),
            "t2": np.histogram(times_df['t2_s'].dropna(), bins=bins)
        }
                