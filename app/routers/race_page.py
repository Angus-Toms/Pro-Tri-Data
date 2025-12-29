import pickle
from functools import lru_cache

import pandas as pd

from config import SITE_RACES_DIR

from app.routers.router_utils import format_time, format_time_behind, format_rating, format_rating_change

from stats.athlete import Athlete
from stats.race import Race
from stats.cache import get_athlete_lookup, get_athlete_name

from fastapi import HTTPException, Request, APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
router = APIRouter()
    
class RenameUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        # Redirect old module references to the correct one
        if module == 'race':
            module = 'stats.race'
        return super().find_class(module, name)    
    
def load_race(race_id: int) -> Race:
    """ Load Race from pickle file """
    file_path = SITE_RACES_DIR / f"{race_id}.pkl"
    
    if not file_path.exists():
        # TODO: Add 404 page
        raise HTTPException(status_code = 404, detail = f"Race {race_id} not found")
    
    try:
        with open(file_path, "rb") as f:
            return RenameUnpickler(f).load()
            
    except Exception as e:
        raise HTTPException(status_code = 500, detail = f"Error loading race data: {str(e)}")
    
@lru_cache(maxsize=32)
def load_race_cached(race_id: int) -> Race:
    return load_race(race_id)

def get_race_standards(race: Race) -> dict:
    """ Format race standards """
    return {
        "overall": format_rating(race.overall_standard),
        "swim": format_rating(race.swim_standard),
        "bike": format_rating(race.bike_standard),
        "run": format_rating(race.run_standard),
        "transition": format_rating(race.transition_standard)
    }

def get_best_performances(race: Race) -> dict:
    """ Format best individual performances (changes) plus athlete names """
    return {
        "overall_change": format_rating_change(race.overall_increase),
        "overall_athlete_name": get_athlete_name(race.overall_increase_athlete_id),
        "swim_change": format_rating_change(race.swim_increase),
        "swim_athlete_name": get_athlete_name(race.swim_increase_athlete_id),
        "bike_change": format_rating_change(race.bike_increase),
        "bike_athlete_name": get_athlete_name(race.bike_increase_athlete_id),
        "run_change": format_rating_change(race.run_increase),
        "run_athlete_name": get_athlete_name(race.run_increase_athlete_id),
        "transition_change": format_rating_change(race.transition_increase),
        "transition_athlete_name": get_athlete_name(race.transition_increase_athlete_id)
    }
    
def get_time_histograms(race: Race) -> dict:
    """
    Prepare histogram data for Chart.js visualization.
    Returns separate datasets for each discipline with labels and counts.
    """
    discipline_details = {
        "overall": {"background": "#357ABD", "display_name": "Overall"},
        "swim": {"background": "#4CAF50", "display_name": "Swim"},
        "bike": {"background": "#FF9800", "display_name": "Bike"},
        "run": {"background": "#E91E63", "display_name": "Run"},
        "t1": {"background": "#9C27B0", "display_name": "Transition 1"},
        "t2": {"background": "#673AB7", "display_name": "Transition 2"}
    }
    
    histograms: dict = race.get_time_histograms(20) # histograms has format returned by np.histogram
    chart_data = {}
    
    for discipline, (counts, bin_edges) in histograms.items():
        if len(counts) == 0:
            chart_data[discipline] = {}
            continue
        
        # Calculate bin centers (midpoints)
        bin_centers = [(bin_edges[i] + bin_edges[i+1]) / 2 for i in range(len(counts))]
        bin_labels = []
        for i in range(len(bin_edges) - 1):
            if round(bin_edges[i+1]) - round(bin_edges[i]) <= 1:
                bin_labels.append(f"{format_time(round(bin_edges[i]))}")
            else:
                start_label = format_time(int(bin_edges[i]))
                end_label = format_time(int(bin_edges[i+1]))
                bin_labels.append(f"{start_label} - {end_label}")
        
        chart_data[discipline] = {
            "labels": bin_centers,
            "datasets": [
                {
                    "label": discipline_details[discipline]["display_name"],
                    "data": [
                        {"x": center, "y": int(count), "label": label}
                        for center, count, label in zip(bin_centers, counts, bin_labels)
                    ],
                    "backgroundColor": discipline_details[discipline]["background"],
                    "borderWidth": 0,
                    "barPercentage": 1.0
                }
            ]
        }
    
    return chart_data

def get_rating_histograms(race: Race) -> dict:
    """
    Prepare histogram data for Chart.js visualization.
    Return seperate datasets for each discipline with labels and counts.
    """
    discipline_details = {
        "overall": {"background": "#357ABD"},
        "swim": {"background": "#4CAF50"},
        "bike": {"background": "#FF9800"},
        "run": {"background": "#E91E63"},
        "transition": {"background": "#9C27B0"},
    }

    histograms: dict = race.get_rating_histograms(20)
    chart_data = {}

    for discipline, (counts, bin_edges) in histograms.items():
        bin_centers = [(bin_edges[i] + bin_edges[i+1]) / 2 for i in range(len(counts))]
        bin_labels = []
        for i in range(len(bin_edges) - 1):
            bin_labels.append(
                f"{int(bin_edges[i])} - {int(bin_edges[i+1])}"
            )
        
        chart_data[discipline] = {
            "labels": bin_centers,
            "datasets": [
                {
                    "label": discipline.capitalize(),
                    "data": [
                        {"x": center, "y": int(count), "label": label}
                        for center, count, label in zip(bin_centers, counts, bin_labels)
                    ],
                    "backgroundColor": discipline_details[discipline]["background"],
                    "borderWidth": 0,
                    "barPercentage": 1.0
                }
            ]
        }
    
    return chart_data

@router.get("/race/{race_id}", response_class = HTMLResponse)
async def get_race(request: Request, race_id: int):
    """
    Prepare race information for display as HTML.
    """
    race: Race = load_race_cached(race_id)
    
    # Build athlete data
    athlete_lookup: pd.DataFrame = get_athlete_lookup()
    athlete_data = {}
    for result in race.results:
        athlete_id = result.athlete_id
        athlete_info = athlete_lookup.loc[athlete_id]
        athlete_data[athlete_id] = {
            "athlete_id": athlete_id,
            "name": athlete_info["name"],
            "country_alpha3": athlete_info["country_alpha3"],
            "country_emoji": athlete_info["country_emoji"],
            "year_of_birth": athlete_info["year_of_birth"],
            "age": race.date.year - athlete_info["year_of_birth"]
        }
        
    # Build splits data
    splits_data = []
    positions = []
    for result in race.results:
        positions.append(result.position)
        athlete_id = result.athlete_id
        splits_data.append({
            **athlete_data[athlete_id],
            "position": result.position,
            "overall_s": format_time(result.overall_s),
            "overall_behind_s": format_time_behind(result.overall_behind_s),
            "swim_s": format_time(result.swim_s),
            "swim_behind_s": format_time_behind(result.swim_behind_s),
            "bike_s": format_time(result.bike_s),
            "bike_behind_s": format_time_behind(result.bike_behind_s),
            "run_s": format_time(result.run_s),
            "run_behind_s": format_time_behind(result.run_behind_s),
            "t1_s": format_time(result.t1_s),
            "t1_behind_s": format_time_behind(result.t1_behind_s),
            "t2_s": format_time(result.t2_s),
            "t2_behind_s": format_time_behind(result.t2_behind_s)
        })
            
    DNF_POSITIONS = set(['dnf', 'dns', 'dq', 'lap', 'nc'])
    dnf_count = len([r for r in positions if r.strip().lower() in DNF_POSITIONS])
    finish_count = len(positions) - dnf_count

    # Build ratings data
    ratings_data = []
    for pos, rating in zip(positions, race.ratings):
        athlete_id = rating.athlete_id
        ratings_data.append({
            **athlete_data[athlete_id],
            "position": pos,
            "overall_rating": format_rating(rating.overall_rating),
            "swim_rating": format_rating(rating.swim_rating),
            "bike_rating": format_rating(rating.bike_rating),
            "run_rating": format_rating(rating.run_rating),
            "transition_rating": format_rating(rating.transition_rating),
            "overall_change": format_rating_change(rating.overall_change),
            "swim_change": format_rating_change(rating.swim_change),
            "bike_change": format_rating_change(rating.bike_change),
            "run_change": format_rating_change(rating.run_change),
            "transition_change": format_rating_change(rating.transition_change),
        })
        
    race_standards: dict = get_race_standards(race)
    best_performances: dict = get_best_performances(race)
    
    time_histograms: dict = get_time_histograms(race)
    rating_histograms: dict = get_rating_histograms(race)
        
    # Format race location and country properly - some formatting errors get through the API formatting 
    race_location = race.location.replace('"', '').replace("'", "")
    race_country = race.country.replace('"', '').replace("'", "")

    return templates.TemplateResponse(
        "race.html",
        {
            "request": request,
            "active_page": "races",
            "race": race,
            "race_location": race_location,
            "race_country": race_country,
            "finish_count": finish_count,
            "dnf_count": dnf_count,
            "race_standards": race_standards,
            "best_performances": best_performances,
            "splits_data": splits_data,
            "ratings_data": ratings_data,
            "overall_time_hist": time_histograms["overall"],
            "swim_time_hist": time_histograms["swim"],
            "bike_time_hist": time_histograms["bike"],
            "run_time_hist": time_histograms["run"],
            "t1_time_hist": time_histograms["t1"],
            "t2_time_hist": time_histograms["t2"],
            "overall_rating_hist": rating_histograms["overall"],
            "swim_rating_hist": rating_histograms["swim"],
            "bike_rating_hist": rating_histograms["bike"],
            "run_rating_hist": rating_histograms["run"],
            "transition_rating_hist": rating_histograms["transition"]
        }
    )
    
