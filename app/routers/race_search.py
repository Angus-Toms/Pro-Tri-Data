from datetime import datetime

from fastapi import APIRouter, Request, logger
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import stats.cache as cache

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/races", response_class=HTMLResponse)
async def races_landing(request: Request):
    """Landing page for race search"""
    return templates.TemplateResponse(
        "race_search.html", 
        {
            "request": request,
            "active_page": "races"
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