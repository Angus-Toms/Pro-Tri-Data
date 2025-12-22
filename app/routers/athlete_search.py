from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import stats.cache as cache

import pandas as pd

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def _get_podium(df: pd.DataFrame):
    if "overall_rank" in df.columns:
        df = df.sort_values("overall_rank")
    podium = df.head(3).reset_index()
    return podium.to_dict(orient="records")

@router.get("/athletes", response_class=HTMLResponse)
async def athletes_landing(request: Request):
    """ Landing page for athlete search """
    athlete_lookup = cache.get_athlete_lookup()
    female_podium = _get_podium(cache.get_female_short_leaderboard())
    male_podium = _get_podium(cache.get_male_short_leaderboard())

    return templates.TemplateResponse(
        "athlete_search.html", 
        {
            "request": request,
            "active_page": "athletes",
            "total_athletes": len(athlete_lookup),
            "total_countries": len(cache.get_country_list()),
            "female_podium": female_podium,
            "male_podium": male_podium,
        }
    )

@router.get("/athletes/search")
async def search_athletes(q: str = ""):
    """ API endpoint for athlete search """
    try:
        if not q or len(q.strip()) < 3:
            return JSONResponse([])
        
        query = q.strip().lower()

        # Get athlete lookup, lookup is pre-sorted by overall rating
        athlete_lookup: pd.DataFrame = cache.get_athlete_lookup()
        matches = athlete_lookup[athlete_lookup["name"].str.contains(query, case = False)]

        results = [
            {
                "athlete_id": row.Index,
                "name": row.name,
                "rating": row.rating,
                "country": row.country_emoji,
                "country_alpha3": row.country_alpha3,
                "year_of_birth": row.year_of_birth or ""
            }
            for row in matches.itertuples()
        ]
        
        return JSONResponse(results)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
