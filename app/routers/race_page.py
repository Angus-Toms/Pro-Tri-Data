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

@router.get("/race/{race_id}", response_class = HTMLResponse)
async def get_race(request: Request, race_id: int):
    """
    Prepare race information for display as HTML.
    """
    start = time.time()
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
        
    end = time.time()
    print(f"Formatted race in {end - start:.2f} seconds")
        
    return templates.TemplateResponse(
        "race.html",
        {
            "request": request,
            "active_page": "races",
            "race": race,
            "splits_data": splits_data,
            "ratings_data": ratings_data
        }
    )
    