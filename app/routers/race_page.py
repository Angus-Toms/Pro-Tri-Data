import pickle
import time
from functools import lru_cache

from config import RACES_DIR

from app.routers.router_utils import format_time, format_time_behind, format_rating, format_rating_change

from stats.athlete import Athlete
from stats.race import Race
from stats.cache import get_athlete_lookup

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
    file_path = RACES_DIR / f"{race_id}.pkl"
    
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
        "overall": 123, # format_rating(race.overall_standard),
        "swim": 123, # format_rating(race.swim_standard),
        "bike": 123, # format_rating(race.bike_standard),
        "run": 123, # format_rating(race.run_standard),
        "transition": 123, #format_rating(race.transition_standard)
    }

def get_best_performances(race: Race) -> dict:
    """ Format best individual performances (changes) plus athlete names """
    athlete_lookup: dict = get_athlete_lookup()
    return {
        "overall_change": format_rating_change(race.overall_increase),
        "overall_athlete_name": athlete_lookup.get(race.overall_increase_athlete_id, {}).get("name", ""),
        "swim_change": format_rating_change(race.swim_increase),
        "swim_athlete_name": athlete_lookup.get(race.swim_increase_athlete_id, {}).get("name", ""),
        "bike_change": format_rating_change(race.bike_increase),
        "bike_athlete_name": athlete_lookup.get(race.bike_increase_athlete_id, {}).get("name", ""),
        "run_change": format_rating_change(race.run_increase),
        "run_athlete_name": athlete_lookup.get(race.run_increase_athlete_id, {}).get("name", ""),
        "transition_change": format_rating_change(race.transition_increase),
        "transition_athlete_name": athlete_lookup.get(race.transition_increase_athlete_id, {}).get("name", "")
    }
    
def get_histogram_chart(race: Race) -> dict:
    """
    Prepare histogram data for Chart.js visualization.
    Returns separate datasets for each discipline with labels and counts.
    """
    # Define colors for each discipline
    discipline_colors = {
        "overall": {"background": "#357ABD"},
        "swim": {"background": "#4CAF50"},
        "bike": {"background": "#FF9800"},
        "run": {"background": "#E91E63"},
        "t1": {"background": "#9C27B0"},
        "t2": {"background": "#673AB7"}
    }
    
    # Define display names
    discipline_names = {
        "overall": "Overall",
        "swim": "Swim",
        "bike": "Bike",
        "run": "Run",
        "t1": "Transition 1",
        "t2": "Transition 2"
    }
    
    histograms: dict = race.get_time_histograms(20) # histograms has format returned by np.histogram
    chart_data = {}
    
    for discipline, (counts, bin_edges) in histograms.items():
        # Calculate bin centers (midpoints) as numeric values
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
                    "label": discipline_names[discipline],
                    "data": [
                        {"x": center, "y": int(count), "label": label}
                        for center, count, label in zip(bin_centers, counts, bin_labels)
                    ],
                    "backgroundColor": discipline_colors[discipline]["background"],
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
    athlete_lookup: dict = get_athlete_lookup()
    athlete_data = {}
    for result in race.results:
        athlete_id = result.athlete_id
        athlete_info = athlete_lookup.get(athlete_id, {})
        athlete_data[athlete_id] = {
            "athlete_id": athlete_id,
            "name": athlete_info.get("name", "Unknown"),
            "country_alpha3": athlete_info.get("country_alpha3", "UNK"),
            "country_emoji": athlete_info.get("country_emoji", "🏳️"),
            "year_of_birth": athlete_info.get("year_of_birth", None),
            "age": race.date.year - athlete_info.get("year_of_birth", race.date.year) if athlete_info.get("year_of_birth") else None,
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
    
    histogram_charts: dict = get_histogram_chart(race)
        
    return templates.TemplateResponse(
        "race.html",
        {
            "request": request,
            "active_page": "races",
            "race": race,
            "race_standards": race_standards,
            "best_performances": best_performances,
            "splits_data": splits_data,
            "ratings_data": ratings_data,
            "overall_hist_chart": histogram_charts["overall"],
            "swim_hist_chart": histogram_charts["swim"],
            "bike_hist_chart": histogram_charts["bike"],
            "run_hist_chart": histogram_charts["run"],
            "t1_hist_chart": histogram_charts["t1"],
            "t2_hist_chart": histogram_charts["t2"]
        }
    )
    