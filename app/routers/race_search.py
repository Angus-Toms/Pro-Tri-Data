from datetime import datetime

from fastapi import APIRouter, Query, Request, logger
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from config import STATIC_BASE_URL
import stats.cache as cache

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
RACE_PAGE_SIZE = 30


def _get_sorted_races():
    """Return races sorted by most recent program date."""
    race_lookup = cache.get_race_lookup()
    races = []

    for race_id, race_data in race_lookup.items():
        prog_date, race_title, race_handle, race_country, prog_name = race_data
        race_date = (
            prog_date.to_pydatetime()
            if hasattr(prog_date, "to_pydatetime")
            else prog_date
        )

        races.append(
            {
                "race_id": race_id,
                "race_title": race_title,
                "race_handle": race_handle,
                "race_country": race_country,
                "prog_name": prog_name,
                "race_date": race_date,
                "race_year": race_date.year if hasattr(race_date, "year") else "",
            }
        )

    races.sort(key=lambda r: r["race_date"], reverse=True)
    return races

@router.get("/races", response_class=HTMLResponse)
async def races_landing(request: Request):
    """Landing page for race search"""
    races = _get_sorted_races()
    initial_chunk = races[:RACE_PAGE_SIZE]

    return templates.TemplateResponse(
        "race_search.html", 
        {
            "request": request,
            "active_page": "races",
            "races": initial_chunk,
            "has_more_races": len(races) > len(initial_chunk),
            "initial_offset": len(initial_chunk),
            "total_races": len(races),
        }
    )

@router.get("/races/more", response_class=HTMLResponse)
async def races_more(request: Request, offset: int = Query(0, ge=0)):
    """Return the next set of races for infinite scroll style loading."""
    races = _get_sorted_races()
    chunk = races[offset:offset + RACE_PAGE_SIZE]

    return templates.TemplateResponse(
        "partials/more_races.html",
        {
            "request": request,
            "races": chunk,
        }
    )

@router.get("/races/search")
async def search_races(q: str = ""):
    """API endpoint for race search"""
    try:
        if not q or len(q.strip()) < 2:
            return JSONResponse([])
        
        query = q.strip().lower()
        
        # Get race lookup
        race_lookup = cache.get_race_lookup()
        
        # Search through races
        results = []
        for race_id, race_data in race_lookup.items():
            prog_date, race_title, race_handle, race_country, prog_name = race_data
            
            # Search in race title and program name
            if query in race_title.lower() or query in prog_name.lower() or query in race_country.lower():
                results.append({
                    'race_id': race_id,
                    'race_title': race_title,
                    'prog_name': prog_name,
                    'race_country': race_country,
                    'prog_date': datetime.strftime(prog_date, "%d %B %Y"), # Convert to string for JSON serialization
                    'date_sort': datetime.strftime(prog_date, "%Y%m%d"), # For sorting before return
                    'race_handle': race_handle
                })
                
                # Limit to 20 results
                if len(results) >= 20:
                    break
        
        # Sort by date (most recent first)
        results.sort(key=lambda x: x['date_sort'], reverse=True)
        
        # Remove date_sort from results
        for r in results:
            r.pop('date_sort', None)

        return JSONResponse(results)
        
    except Exception as e:
        print(f"Error when race searching: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
