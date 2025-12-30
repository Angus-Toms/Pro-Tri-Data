from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from config import STATIC_BASE_URL

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL

@router.get("/")
async def index(request: Request):
    """
    Basic landing page
    """

    context = {
        "request": request,
        "active_page": "home",
        "total_athletes": 60016,
        "total_races": 9519,
        "total_results": 196287,
    }

    return templates.TemplateResponse("index.html", context)
