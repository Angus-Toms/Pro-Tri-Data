from datetime import datetime
from dataclasses import dataclass
from typing import List

@dataclass(slots=True)
class IndividualResult:
    athlete_id: int
    # String position to accommodate DNF/DQ/LAP
    position: str 
    
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
        self.ratings.append(
            IndividualRating(
                athlete_id = athlete_id,
                overall_rating = overall_rating,
                swim_rating = swim_rating,
                bike_rating = bike_rating,
                run_rating = run_rating,
                transition_rating = transition_rating,
                overall_change = overall_change * k_factor,
                swim_change = swim_change * k_factor,
                bike_change = bike_change * k_factor,
                run_change = run_change * k_factor,
                transition_change = transition_change * k_factor
            )
        )
        
        if overall_change != 0 and overall_change > self.overall_increase:
            self.overall_increase = overall_change
            self.overall_increase_athlete_id = athlete_id
            
        if swim_change != 0 and swim_change > self.swim_increase:
            self.swim_increase = swim_change
            self.swim_increase_athlete_id = athlete_id
            
        if bike_change != 0 and bike_change > self.bike_increase:
            self.bike_increase = bike_change
            self.bike_increase_athlete_id = athlete_id 
            
        if run_change != 0 and run_change > self.run_increase:
            self.run_increase = run_change
            self.run_increase_athlete_id = athlete_id
        
        if transition_change != 0 and transition_change > self.transition_increase:
            self.transition_increase = transition_change
            self.transition_increase_athlete_id = athlete_id    