from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import index, athlete_search, race_search, athlete_page, race_page, leaderboard, comparison

BASE_DIR = Path(__file__).resolve().parent.parent # Project root

app = FastAPI()
app.mount("/static", StaticFiles(directory = BASE_DIR / "static"), name = "static")
templates = Jinja2Templates(directory = BASE_DIR / "templates")

# Redirect 404s
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "404.html",
            {
                "request": request,
                "detail": exc.detail,
                "active_page": None,
            },
            status_code = 404,
        )
    return await http_exception_handler(request, exc)

# Include page routers
app.include_router(index.router)
app.include_router(athlete_search.router)
app.include_router(race_search.router)
app.include_router(athlete_page.router)
app.include_router(race_page.router)
app.include_router(leaderboard.router)
app.include_router(comparison.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host = "0.0.0.0", port = 8000)
