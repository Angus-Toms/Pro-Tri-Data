from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL, flag
from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import current_user
from app.routers.router_utils import format_rating_change, format_time, rel_time, user_avatar
from app.routers.upcoming_page import _build_podium
from app.routers.comments import render_comment_body, tag_refs

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["render_comment_body"] = render_comment_body
templates.env.globals["user_avatar"]   = user_avatar


@router.get("/feed", response_class=HTMLResponse)
async def feed(request: Request):
    user = await current_user(request)
    if user is None:
        return RedirectResponse("/login?next=/feed", status_code=303)
    follows = await uq.get_follows(user["user_id"])
    races_brief = queries.get_races_brief_bulk(follows["races"])

    # --- upcoming races: followed races + followed athletes' startlists ---
    upcoming = {}
    for rid, info in races_brief.items():
        if info["is_upcoming"]:
            upcoming[rid] = {**info, "followed_race": True, "athletes": []}
    for row in queries.get_upcoming_races_for_athletes(follows["athletes"]):
        entry = upcoming.setdefault(row["race_id"], {
            "race_id":    row["race_id"],
            "race_title": row["race_title"],
            "prog_name":  row["prog_name"],
            "race_date":  row["race_date"],
            "gender":     row["gender"],
            "country":    row["country"],
            "event_spec_ids": row["event_spec_ids"],
            "followed_race":  False,
            "athletes":   [],
        })
        entry["athletes"].append(row["name"])

    models = queries.get_prediction_models()
    entries_by_race = queries.get_upcoming_race_entries_bulk(list(upcoming))
    for rid, entry in upcoming.items():
        top3 = sorted(entries_by_race.get(rid, []),
                      key=lambda e: e["overall_rating"] or 0, reverse=True)[:3]
        entry["podium"] = _build_podium(top3, entry["gender"], entry["event_spec_ids"], models)
    upcoming_races = sorted(upcoming.values(), key=lambda e: (e["race_date"], e["race_id"]))

    # --- recent results from followed athletes (last 90 days) ---
    recent_results = queries.get_recent_results_for_athletes(follows["athletes"])
    for r in recent_results:
        r["overall"] = format_time(r["overall_s"] or 0)
        r["change"]  = format_rating_change(r["overall_change"])

    # --- recent comments on followed races ---
    comments = await uq.get_recent_comments_for_races(follows["races"])
    comment_races = queries.get_races_brief_bulk({c["race_id"] for c in comments})
    for c in comments:
        race = comment_races.get(c["race_id"])
        c["race_title"] = race["race_title"] if race else f"Race {c['race_id']}"
        c["when"] = rel_time(c["created_at"])

    return templates.TemplateResponse("feed.html", {
        "request":        request,
        "active_page":    "feed",
        "user":           user,
        "has_follows":    bool(follows["athletes"] or follows["races"]),
        "n_athletes":     len(follows["athletes"]),
        "n_races":        len(follows["races"]),
        "upcoming_races": upcoming_races,
        "recent_results": recent_results,
        "comments":       comments,
        "mention_refs":   await tag_refs([c["body"] for c in comments]),
    }, headers={"Cache-Control": "no-store"})
