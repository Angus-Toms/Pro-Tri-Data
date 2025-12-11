from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from stats.cache import get_male_short_leaderboard, get_female_short_leaderboard, get_country_list

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/leaderboard/more")
async def leaderboard_more(
    request: Request,
    gender: str = Query("female", regex="^(male|female)$"),
    rating_type: str = Query("overall", regex="^(overall|swim|bike|run|transition)$"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    country: str = Query("all"),
    yob_start: int = Query(1950),
    yob_end: int = Query(2010),
    active_only: bool = Query(False),
    offset: int = Query(0),
    ):
        # Load next 50 results
        if gender == "male":
            leaderboard_data = get_male_short_leaderboard()
        else:
            leaderboard_data = get_female_short_leaderboard()

        athletes = list(leaderboard_data.values())

        if active_only:
            athletes = [a for a in athletes if a["active"]]

        if country != "all":
            athletes = [a for a in athletes if a["country_full"] == country]

        athletes = [
            a for a in athletes if yob_start <= a["year_of_birth"] <= yob_end
        ]

        rating_key = f"{rating_type}_rating"
        athletes.sort(key = lambda x: x[rating_key], reverse = (order == "desc"))

        # Add rank numbers
        for i, athlete in enumerate(athletes, 1):
            athlete["rank"] = i 

        chunk = athletes[offset: offset+50]

        return templates.TemplateResponse(
            "partials/more_athlete_leaderboard.html",
            {
                "request": request,
                "athletes": chunk,
                "rating_type": rating_type
            }
        )        

@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    gender: str = Query("female", regex="^(male|female)$"),
    rating_type: str = Query("overall", regex="^(overall|swim|bike|run|transition)$"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    country: str = Query("all"),
    yob_start: Optional[int] = Query(1950, ge=1950, le=2010),
    yob_end: Optional[int] = Query(2010, ge=1950, le=2010),
    active_only: bool = Query(False)
):
    # Load appropriate leaderboard based on gender
    if gender == "male":
        leaderboard_data = get_male_short_leaderboard()
    else:
        leaderboard_data = get_female_short_leaderboard()
    
    athletes = list(leaderboard_data.values())
    print(athletes[0])
    
    # Filter by active status
    if active_only:
        athletes = [a for a in athletes if a['active']]
    
    # Filter by country, default value for no filtering is 'all'
    if country != "all":
        print(f"Filtering by {country}")
        athletes = [a for a in athletes if a['country_full'] == country]
    
    print(f"After filtering, {len(athletes)} athletes")

    # Filter by year of birth range
    if yob_start:
        athletes = [a for a in athletes if a['year_of_birth'] >= yob_start]
    if yob_end:
        athletes = [a for a in athletes if a['year_of_birth'] <= yob_end]
        
    # Sort by selected rating
    rating_key = f"{rating_type}_rating"
    athletes.sort(key = lambda x: x[rating_key], reverse = (order == "desc"))
    
    # Add rank numbers
    for i, athlete in enumerate(athletes, 1):
        athlete['rank'] = i

    # List of all countries to supply to selection box 
    all_countries = sorted(get_country_list())

    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "active_page": "athletes",
            "athletes": athletes[:50],
            "all_countries": all_countries,
            "gender": gender,
            "rating_type": rating_type,
            "order": order,
            "country": country,
            "yob_start": yob_start,
            "yob_end": yob_end,
            "active_only": active_only
        }
    )