import sys
from pathlib import Path

# Add parent directory to Python path
# parent_dir = Path(__file__).parent.parent
# sys.path.insert(0, str(parent_dir))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import index, athlete_search, race_search, athlete_page, race_page, leaderboard, comparison

BASE_DIR = Path(__file__).resolve().parent.parent # Project root

app = FastAPI()
app.mount("/static", StaticFiles(directory = BASE_DIR / "static"), name = "static")

# Include page routers
app.include_router(index.router)
app.include_router(athlete_search.router)
app.include_router(race_search.router)
app.include_router(athlete_page.router)
app.include_router(race_page.router)
app.include_router(leaderboard.router)
app.include_router(comparison.router)

# TODO: Startup script for athlete and race lookups?

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host = "0.0.0.0", port = 8000)