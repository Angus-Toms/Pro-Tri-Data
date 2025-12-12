import pandas as pd

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from stats.cache import get_male_short_leaderboard, get_female_short_leaderboard, get_country_list
from app.routers.router_utils import format_rating_change

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/leaderboard/more")
async def leaderboard_more(
    request: Request,
    gender: str = Query("female", regex="^(male|female)$"),
    disc: str = Query("overall", regex="^(overall|swim|bike|run|transition)$"),
    order: str = Query("top", regex="^(top|hot)"),
    country: str = Query("all"),
    yob_start: int = Query(1950),
    yob_end: int = Query(2010),
    active_only: bool = Query(False),
    offset: int = Query(0),
    ):
    """
    Load next 50 results from leaderboard
    """
    # Load appropriate leaderboard based on gender
    if gender == "male":
        leaderboard_df: pd.DataFrame = get_male_short_leaderboard()
    else:
        leaderboard_df: pd.DataFrame = get_female_short_leaderboard()

    # Filter by active status
    if active_only:
        leaderboard_df = leaderboard_df[leaderboard_df["active"]]
    
    # Filter by country, default value for no filtering is 'all'
    if country != "all":
        leaderboard_df = leaderboard_df[leaderboard_df["country_full"] == country]

    # Filter by year of birth range
    if yob_start:
        leaderboard_df = leaderboard_df[leaderboard_df["year_of_birth"] >= yob_start]
    if yob_end:
        leaderboard_df = leaderboard_df[leaderboard_df["year_of_birth"] <= yob_end]

    if order == "top":
        # Order by overall rank
        leaderboard_df.sort_values(f"{disc}_rank", inplace = True)
    if order == "hot":
        # Order by last year increase (for those that had a change last year) 
        leaderboard_df = leaderboard_df[leaderboard_df[f"{disc}_change"] != 0]
        leaderboard_df.sort_values(f"{disc}_change_rank", inplace = True)

    # Add new rank numbers (may be different from global rank if selections applied) to requested chunk
    chunk = leaderboard_df.iloc[offset:offset+50]
    chunk["rank"] = range(offset+1, offset+51)

    # Convert to dict for FastAPI
    chunk = chunk.to_dict(orient = "records")

    if order == "hot":
        # Format rating changes to correct strings for hot leaderboard
        for athlete in chunk:
            for d in ["overall", "swim", "bike", "run", "transition"]:
                athlete[f"{d}_change"] = format_rating_change(athlete[f"{d}_change"])

    print(chunk[0])

    return templates.TemplateResponse(
        "partials/more_athlete_leaderboard.html",
        {
            "request": request,
            "athletes": chunk,
            "disc": disc,
            "order": order
        }
    )        

@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    gender: str = Query("female", regex="^(male|female)$"),
    disc: str = Query("overall", regex="^(overall|swim|bike|run|transition)$"),
    order: str = Query("top", regex="^(top|hot)"),
    country: str = Query("all"),
    yob_start: Optional[int] = Query(1950, ge=1950, le=2010),
    yob_end: Optional[int] = Query(2010, ge=1950, le=2010),
    active_only: bool = Query(False)
    ):
    # Load appropriate leaderboard based on gender
    if gender == "male":
        leaderboard_df: pd.DataFrame = get_male_short_leaderboard()
    else:
        leaderboard_df: pd.DataFrame = get_female_short_leaderboard()

    # Filter by active status
    if active_only:
        leaderboard_df = leaderboard_df[leaderboard_df["active"]]
    
    # Filter by country, default value for no filtering is 'all'
    if country != "all":
        leaderboard_df = leaderboard_df[leaderboard_df["country_full"] == country]

    # Filter by year of birth range
    if yob_start:
        leaderboard_df = leaderboard_df[leaderboard_df["year_of_birth"] >= yob_start]
    if yob_end:
        leaderboard_df = leaderboard_df[leaderboard_df["year_of_birth"] <= yob_end]

    if order == "top":
        # Order by overall rank
        leaderboard_df.sort_values(f"{disc}_rank", inplace = True)
    if order == "hot":
        # Order by last year increase (for those that had a change last year) 
        leaderboard_df = leaderboard_df[leaderboard_df[f"{disc}_change"] != 0]
        leaderboard_df.sort_values(f"{disc}_change_rank", inplace = True)

    # Add new rank numbers (may be different from global rank if selections applied) to returned athletes
    leaderboard_df = leaderboard_df.head(50)
    leaderboard_df["rank"] = range(1, len(leaderboard_df) + 1)

    # Convert to dict for FastAPI
    athletes = leaderboard_df.to_dict(orient = "records")

    if order == "hot":
            # Format rating changes to correct strings for hot leaderboard
            for athlete in athletes:
                for d in ["overall", "swim", "bike", "run", "transition"]:
                    athlete[f"{d}_change"] = format_rating_change(athlete[f"{d}_change"])


    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "active_page": "athletes",
            "athletes": athletes,
            "all_countries": sorted(get_country_list()),
            "gender": gender,
            "disc": disc,
            "order": order,
            "country": country,
            "yob_start": yob_start,
            "yob_end": yob_end,
            "active_only": active_only
        }
    )