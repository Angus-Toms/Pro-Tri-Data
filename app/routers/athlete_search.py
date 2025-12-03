from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import stats.cache as cache

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/athletes", response_class=HTMLResponse)
async def athletes_landing(request: Request):
    """ Landing page for athlete search """
    return templates.TemplateResponse(
        "athlete_search.html", 
        {
            "request": request,
            "active_page": "athletes"
        }
    )

@router.get("/athletes/search")
async def search_athletes(q: str = ""):
    """API endpoint for athlete search"""

    try:
        if not q or len(q.strip()) < 2:
            return JSONResponse([])
        
        query = q.strip().lower()

        # Get athlete lookup
        athlete_lookup = cache.get_athlete_lookup()

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
                
                # Limit to 10 results
                if len(results) >= 10:
                    break
        
        
        # Sort by name
        results.sort(key=lambda x: x['name'])
        
        return JSONResponse(results)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)