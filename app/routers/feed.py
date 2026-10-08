from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import current_user
from app.routers.router_utils import format_rating_change, format_time, format_time_behind

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag


@router.get("/feed")
async def feed_redirect():
    """The feed lives on the home page now."""
    return RedirectResponse("/", status_code=301)


@router.get("/home/mine", response_class=HTMLResponse)
async def home_mine(request: Request):
    """The logged-in layer of the home page: followed athletes' next starts
    with the model's predicted finish, then their results since the user was
    last here. Injected client-side so the home page stays cacheable."""
    user = await current_user(request)
    if user is None:
        return Response(status_code=401)
    follows = await uq.get_follows(user["user_id"])
    athletes = follows["athletes"]
    today = date.today()

    # --- coming up: predicted position and gap to the predicted winner ---
    coming = queries.get_upcoming_races_for_athletes(athletes)
    preds = {rid: queries.get_race_predictions(rid) for rid in {s["race_id"] for s in coming}}
    entries = queries.get_upcoming_race_entries_bulk(list(preds))
    for s in coming:
        rows = preds[s["race_id"]]
        mine = next((p for p in rows if p["athlete_id"] == s["athlete_id"]), None)
        s["entries"]  = len(entries.get(s["race_id"], []))
        s["pred_pos"] = mine["predicted_position"] if mine else None
        s["pred_gap"] = None
        if mine and mine["overall_s"] and rows[0]["overall_s"]:
            s["pred_gap"] = (format_time(mine["overall_s"]) if mine["predicted_position"] == 1
                             else format_time_behind(mine["overall_s"] - rows[0]["overall_s"]))

    # --- since you were last here: floored at two weeks so a weekly visitor
    # always sees last weekend, capped at the query's 90 days ---
    since = min(user["last_seen_at"].date(), today - timedelta(days=14))
    all_results = queries.get_recent_results_for_athletes(athletes)
    results = [r for r in all_results if r["race_date"] >= since]
    results_heading = "Since you were last here"
    if not results:
        results, results_heading = all_results[:3], "Latest results"
    for r in results:
        r["change"] = format_rating_change(r["overall_change"])
        if r["position"] == 1:
            r["time"] = format_time(r["overall_s"] or 0)
        elif r["position"] and r["overall_s"] and r["winner_s"]:
            r["time"] = format_time_behind(r["overall_s"] - r["winner_s"])
        else:
            r["time"] = None

    photos = queries.get_athletes_brief_bulk(
        {s["athlete_id"] for s in coming} | {r["athlete_id"] for r in results})
    for row in coming + results:
        row["profile_img"] = photos.get(row["athlete_id"], {}).get("profile_img", "")

    suggestions, country_name = [], None
    if user["country"]:
        country = queries.get_country_by_alpha3(user["country"])
        if country:
            country_name = country["country_full"]
            suggestions = queries.get_upcoming_starters_by_country(user["country"], exclude=athletes)

    return templates.TemplateResponse("partials/home_mine.html", {
        "request":         request,
        "coming":          coming,
        "results":         results,
        "results_heading": results_heading,
        "suggestions":     suggestions,
        "country_name":    country_name,
    }, headers={"Cache-Control": "no-store"})
