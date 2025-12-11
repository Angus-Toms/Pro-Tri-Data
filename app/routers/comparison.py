from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from stats import cache
from stats.athlete import Athlete, RaceResult
from app.routers import router_utils

from config import ATHLETES_DIR

from app.routers.router_utils import format_1yr_rating_change, format_rating

import pickle
from functools import lru_cache
from typing import Dict, List
import pandas as pd

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
    """ Determine CSS classes for head-to-head times 
    
    Note: dict keys contain underscored e.g. css_class to allow for Jinja
    dot accessing while css classes e.g. "h2h-winner" use hyphens
    """
    times = [{}, {}]
    if time1_s == 0:
        times[0] = {
            "formatted_str": "",
            "css_class": "h2h-dnf"
        }
        if time2_s != 0:
            times[1] = {
                "formatted-str": router_utils.format_time(time2_s),
                "css_class": "h2h-winner"
            }

    if time2_s == 0:
        times[1] = {
            "formatted_str": "",
            "css_class": "h2h-dnf"
        }
        if time1_s != 0:
            times[0] = {
                "formatted_str": router_utils.format_time(time1_s),
                "css_class": "h2h-winner"
            }

    if time1_s != 0 and time2_s != 0:
        times = [{
            "formatted_str": router_utils.format_time(time1_s),
            "css_class": ""
        }, {
            "formatted_str": router_utils.format_time(time2_s),
            "css_class": ""
        }]
        if time1_s < time2_s:
            times[0]["css_class"] = "h2h-winner"
        elif time2_s < time1_s:
            times[1]["css_class"] = "h2h-winner"

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
            "active_page": "athletes"
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

def get_basic_h2h_data(athlete: Athlete) -> Dict:
    """ Get and format basic data for athlete in h2h comparison """
    return {
        "id": athlete.athlete_id,
        "name": athlete.name,
        "country": athlete.country_emoji,
        "country_alpha3": athlete.country_alpha3,
        "year_of_birth": athlete.year_of_birth,
        "ratings": {
            "overall": format_rating(athlete.overall_rating),
            "overall_change_1yr": format_1yr_rating_change(athlete.overall_change_1yr),
            "swim": format_rating(athlete.swim_rating),
            "swim_change_1yr": format_1yr_rating_change(athlete.swim_change_1yr),
            "bike": format_rating(athlete.bike_rating),
            "bike_change_1yr": format_1yr_rating_change(athlete.bike_change_1yr),
            "run": format_rating(athlete.run_rating),
            "run_change_1yr": format_1yr_rating_change(athlete.run_change_1yr),
            "transition": format_rating(athlete.transition_rating),
            "transition_change_1yr": format_1yr_rating_change(athlete.transition_change_1yr)
        },
        "stats": {
            "total_races": athlete.race_starts,
            "podiums": athlete.podium_count,
            "wins": athlete.win_count,
            "h2h_wins": 0 # Calculated later
        }
    }

def get_h2h_race_results(athlete1: Athlete, athlete2: Athlete) -> List[Dict]:
    """ Format head-to-head info for two athletes """
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

    return head_to_head

def get_h2h_rating_chart(athlete1: Athlete, athlete2: Athlete, race_lookup: Dict) -> Dict:
    """ Generate h2h rating chart.js graph data for two athletes. """
    colors = {
        "overall": ("#4CAF50", "#357ABD"),
        "swim": ("#357ABD", "#FF9800"),
        "bike": ("#FF9800", "#E91E63"),
        "run": ("#E91E63", "#9C27B0"),
        "transition": ("#9C27B0", "#4CAF50"), 
    }

    # --- Load athlete 1 data ---
    df1 = athlete1.get_ratings_df()
    if not pd.api.types.is_datetime64_any_dtype(df1["race_date"]):
        df1["race_date"] = pd.to_datetime(df1["race_date"], errors="coerce")
    race_dates_1 = df1["race_date"].dt.strftime("%Y-%m-%d").tolist()
    race_names_1 = [race_lookup.get(rid, ["", ""])[1] for rid in df1["race_id"].tolist()]

    # --- Load athlete 2 data ---
    df2 = athlete2.get_ratings_df()
    if not pd.api.types.is_datetime64_any_dtype(df2["race_date"]):
        df2["race_date"] = pd.to_datetime(df2["race_date"], errors="coerce")
    race_dates_2 = df2["race_date"].dt.strftime("%Y-%m-%d").tolist()
    race_names_2 = [race_lookup.get(rid, ["", ""])[1] for rid in df2["race_id"].tolist()]


    output = {}
    for discipline, colors in colors.items():
        color1, color2 = colors

        output[discipline] = {
            "datasets": [
                {
                    "label": athlete1.name,
                    "data": [
                        {"x": d, "y": int(y), "race_name": rn}
                        for d, y, rn in zip(
                            race_dates_1,
                            df1[f"{discipline}_rating"].fillna(0).astype(int),
                            race_names_1
                        )
                    ],
                    "borderColor": color1,
                    "backgroundColor": color1 + "20",
                    "borderWidth": 2,
                    "pointRadius": 3,
                },
                {
                    "label": athlete2.name,
                    "data": [
                        {"x": d, "y": int(y), "race_name": rn}
                        for d, y, rn in zip(
                            race_dates_2,
                            df2[f"{discipline}_rating"].fillna(0).astype(int),
                            race_names_2
                        )
                    ],
                    "borderColor": color2,
                    "backgroundColor": color2 + "20",
                    "borderWidth": 2,
                    "pointRadius": 3,
                }
            ]
        }

    return output


@router.get("/compare/{athlete1_id}/{athlete2_id}", response_class = HTMLResponse)
async def get_comparison_html(request: Request, athlete1_id: int, athlete2_id: int):
    """
    Get comparison HTML for two athletes.
    Returns rendered template with comparison data.
    """
    try:
        # Load athlete data from pickle files
        athlete1: Athlete = load_athlete_cached(athlete1_id)
        athlete2: Athlete = load_athlete_cached(athlete2_id)
        
        # Get formatted data + ratings for both athletes
        athlete1_data = get_basic_h2h_data(athlete1)
        athlete2_data = get_basic_h2h_data(athlete2)

        # Get head-to-head race results and calculate H2H wins
        head_to_head = get_h2h_race_results(athlete1, athlete2)

        for race in head_to_head:
            if race["athlete1_time"]["css_class"] == "h2h-winner":
                athlete1_data["stats"]["h2h_wins"] += 1
            elif race["athlete2_time"]["css_class"] == "h2h-winner":
                athlete2_data["stats"]["h2h_wins"] += 1

        race_lookup = cache.get_race_lookup()
        h2h_ratings_chart = get_h2h_rating_chart(athlete1, athlete2, race_lookup)

        # Render the comparison results template
        return templates.TemplateResponse(
            "comparison_results.html",
            {
                "request": request,
                "athlete1": athlete1_data,
                "athlete2": athlete2_data,
                "head_to_head": head_to_head,
                "overall_ratings_chart": h2h_ratings_chart["overall"],
                "swim_ratings_chart": h2h_ratings_chart["swim"],
                "bike_ratings_chart": h2h_ratings_chart["bike"],
                "run_ratings_chart": h2h_ratings_chart["run"],
                "transition_ratings_chart": h2h_ratings_chart["transition"]
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code = 500, detail = str(e))