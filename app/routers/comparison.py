from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from stats import cache
from stats.athlete import Athlete, RaceResult
from app.routers import router_utils

from config import ATHLETES_DIR

import pickle
from functools import lru_cache
from typing import Dict, List

router = APIRouter()
templates = Jinja2Templates(directory="templates")

class RenameUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        # Redirect old module references to the correct one
        if module == 'athlete':
            module = 'stats.athlete'
        return super().find_class(module, name)
    
def load_athlete(athlete_id: int) -> Athlete:
    """ Load athlete data from pickle file """
    file_path = ATHLETES_DIR / f"{athlete_id}.pkl"
    
    if not file_path.exists():
        raise HTTPException(status_code = 404, detail = f"Athlete {athlete_id} not found")
    
    try:
        with open(file_path, 'rb') as f:
            return RenameUnpickler(f).load()
            
    except Exception as e:
        raise HTTPException(status_code = 500, detail = f"Error loading athlete data: {str(e)}")

@lru_cache(maxsize=32)
def load_athlete_cached(athlete_id: int) -> Athlete:
    return load_athlete(athlete_id)

def format_h2h_times(time1_s: int, time2_s: int) -> List[Dict]:
    """ Determine CSS classes for head-to-head times """
    times = [{}, {}]
    if time1_s == 0:
        times[0] = {
            "formatted-str": "",
            "css-class": "h2h-dnf"
        }
        if time2_s != 0:
            times[1] = {
                "formatted-str": router_utils.format_time(time2_s),
                "css-class": "h2h-winner"
            }

    if time2_s == 0:
        times[1] = {
            "formatted-str": "",
            "css-class": "h2h-dnf"
        }
        if time1_s != 0:
            times[0] = {
                "formatted-str": router_utils.format_time(time1_s),
                "css-class": "h2h-winner"
            }

    if time1_s != 0 and time2_s != 0:
        times = [{
            "formatted-str": router_utils.format_time(time1_s),
            "css-class": ""
        }, {
            "formatted-str": router_utils.format_time(time2_s),
            "css-class": ""
        }]
        if time1_s < time2_s:
            times[0]["css-class"] = "h2h-winner"
        elif time2_s < time1_s:
            times[1]["css-class"] = "h2h-winner"

    return times

def get_time_behind(time1_s: int, time2_s: int) -> List[str]:
    """ 
    Calculate time behind for the two times, accounting for DNFs (0s) 
    Plus format for string display
    """
    if time1_s == 0 or time2_s == 0:
        return ["", ""]
    
    if time1_s < time2_s:
        return ["", router_utils.format_time_behind(time2_s - time1_s)]
    
    return [router_utils.format_time_behind(time1_s - time2_s), ""]

@router.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request):
    """ Render the athlete comparison page """
    return templates.TemplateResponse(
        "comparison.html", 
        {
            "request": request,
            "active_page": "athlete"
        }
    )

@router.get("/compare/search")
async def search_athletes_for_compare(q: str = ""):
    """ API endpoint for athlete search in comparison page """
    try:
        if not q or len(q.strip()) < 2:
            return JSONResponse([])
        
        query: str = q.strip().lower()

        # Get athlete lookup
        athlete_lookup: dict = cache.get_athlete_lookup()

        # Search through athletes
        results = []
        for athlete_id, athlete_data in athlete_lookup.items():
            if query in athlete_data["name"].lower() or query in str(athlete_id):
                results.append({
                    'athlete_id': athlete_id,
                    'name': athlete_data["name"],
                    'country': athlete_data["country_emoji"],
                    'country_alpha3': athlete_data["country_alpha3"],
                    'year_of_birth': athlete_data.get("year_of_birth", "")
                })
                
                # Limit to 20 results
                if len(results) >= 20:
                    break
        
        # Sort by name
        results.sort(key = lambda x: x['name'])
        
        return JSONResponse(results)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/compare/{athlete1_id}/{athlete2_id}", response_class=HTMLResponse)
async def get_comparison_html(request: Request, athlete1_id: int, athlete2_id: int):
    """
    Get comparison HTML for two athletes.
    Returns rendered template with comparison data.
    """
    try:
        # Load athlete data from pickle files
        athlete1: Athlete = load_athlete_cached(athlete1_id)
        athlete2: Athlete = load_athlete_cached(athlete2_id)
        
        # Get current ratings for both athletes
        athlete1_data = {
            "id": athlete1.athlete_id,
            "name": athlete1.name,
            "country": athlete1.country_emoji,
            "country_alpha3": athlete1.country_alpha3,
            "year_of_birth": athlete1.year_of_birth,
            "ratings": {
                "overall": athlete1.overall_rating,
                "swim": athlete1.swim_rating,
                "bike": athlete1.bike_rating,
                "run": athlete1.run_rating,
                "transition": athlete1.transition_rating
            },
            "stats": {
                "total_races": athlete1.race_starts,
                "podiums": athlete1.podium_count,
                "wins": athlete1.win_count,
                "h2h_wins": 0 # Calculated later
            }
        }
        
        athlete2_data = {
            "id": athlete2.athlete_id,
            "name": athlete2.name,
            "country": athlete2.country_emoji,
            "country_alpha3": athlete2.country_alpha3,
            "year_of_birth": athlete2.year_of_birth,
            "ratings": {
                "overall": athlete2.overall_rating,
                "swim": athlete2.swim_rating,
                "bike": athlete2.bike_rating,
                "run": athlete2.run_rating,
                "transition": athlete2.transition_rating
            },
            "stats": {
                "total_races": athlete2.race_starts,
                "podiums": athlete2.podium_count,
                "wins": athlete2.win_count,
                "h2h_wins": 0  # Calculated after
            }
        }
        
        # Get race results for both
        athlete1_results: List[RaceResult] = athlete1.race_results
        athlete2_results: List[RaceResult] = athlete2.race_results
        
        # Find head-to-head races (races where both competed)
        athlete1_race_ids = {r.race_id for r in athlete1_results}
        athlete2_race_ids = {r.race_id for r in athlete2_results}
        common_race_ids = athlete1_race_ids & athlete2_race_ids
        
        head_to_head = []
        race_lookup: dict = cache.get_race_lookup()
        
        for race_id in common_race_ids:
            r1 = next((r for r in athlete1_results if r.race_id == race_id), None)
            r2 = next((r for r in athlete2_results if r.race_id == race_id), None)
            
            if r1 and r2:
                athlete1_time, athlete2_time = format_h2h_times(r1.overall_s, r2.overall_s)
                
                if athlete1_time["css-class"] == "h2h-winner":
                    athlete1_data["stats"]["h2h_wins"] += 1
                elif athlete2_time["css-class"] == "h2h-winner":
                    athlete2_data["stats"]["h2h_wins"] += 1

                # Format time diffs as strings
                athlete1_behind, athlete2_behind = get_time_behind(r1.overall_s, r2.overall_s)

                head_to_head.append({
                    "race_id": r1.race_id,
                    "race_name": race_lookup.get(race_id, ["", ""])[1],
                    "race_date": r1.race_date,
                    "athlete1_position": r1.position,
                    "athlete1_time": athlete1_time,
                    "athlete1_behind": athlete1_behind,
                    "athlete2_position": r2.position,
                    "athlete2_time": athlete2_time,
                    "athlete2_behind": athlete2_behind
                })
        
        # Sort head-to-head by date (most recent first)
        head_to_head.sort(key = lambda x: x["race_date"], reverse = True)
        
        # Render the comparison results template
        return templates.TemplateResponse(
            "comparison_results.html",
            {
                "request": request,
                "athlete1": athlete1_data,
                "athlete2": athlete2_data,
                "head_to_head": head_to_head
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code = 500, detail = str(e))