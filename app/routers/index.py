from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/")
async def index(request: Request):
    """
    Basic landing page
    """
    
    context = {
        "request": request,
        "active_page": "home",
        "total_athletes": 60016,
        "total_races": 9510,     
        "total_results": 196287
    }
    
    return templates.TemplateResponse("index.html", context)