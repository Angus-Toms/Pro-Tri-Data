from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import queries
from ptd_users import queries as uq
from app.routers.comments import render_comment_body, tag_refs
from app.routers.account import PB_FIELDS, following_rows
from app.routers.router_utils import format_time, rel_time, user_avatar

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["user_avatar"]   = user_avatar
templates.env.globals["render_comment_body"] = render_comment_body
templates.env.globals["format_time"]   = format_time

PAGE_SIZE = 30
# Reactions shown as badges in the profile header, in this order.
RECEIVED_ORDER = [("up", "Thumbs up"), ("rapid", "Rapid"), ("paincave", "Pain cave"), ("podium", "Podium")]


@router.get("/user/{user_id}", response_class=HTMLResponse)
async def profile(request: Request, user_id: int, offset: int = Query(0, ge=0)):
    profile = await uq.get_public_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    comments, has_more = await uq.list_user_comments(user_id, offset, PAGE_SIZE)
    received = await uq.reactions_received(user_id)
    country = queries.get_country_by_alpha3(profile["country"]) if profile["country"] else None

    # --- comments grouped by race, newest race first, replies with their parent ---
    races = queries.get_races_brief_bulk({c["race_id"] for c in comments})
    groups = {}
    for c in comments:
        c["when"] = rel_time(c["created_at"])
        if c["race_id"] not in groups:
            race = races.get(c["race_id"])
            groups[c["race_id"]] = {
                "race_id":   c["race_id"],
                "title":     race["race_title"] if race else f"Race {c['race_id']}",
                "prog_name": race["prog_name"] if race else None,
                "race_date": race["race_date"] if race else None,
                "comments":  [],
            }
        groups[c["race_id"]]["comments"].append(c)

    return templates.TemplateResponse("user_profile.html", {
        "request":      request,
        "active_page":  None,
        "profile":      profile,
        "country_name": country["country_full"] if country else None,
        "groups":       list(groups.values()),
        "following":    await following_rows(user_id),
        "offset":       offset,
        "has_more":     has_more,
        "page_size":    PAGE_SIZE,
        "mention_refs": await tag_refs([c["body"] for c in comments] + [c["parent_body"] or "" for c in comments]),
        "pbs":          [(label, profile[col]) for col, label, _, _ in PB_FIELDS if profile[col]],
        "received":     [(kind, label, n) for kind, label in RECEIVED_ORDER
                         if (n := received.get(kind))],
    })


@router.get("/user/{user_id}/card", response_class=HTMLResponse)
async def profile_card(request: Request, user_id: int):
    """Hover card for comment authors: a compact profile summary."""
    profile = await uq.get_public_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    received = await uq.reactions_received(user_id)
    return templates.TemplateResponse("partials/user_card.html", {
        "request":  request,
        "profile":  profile,
        "received": [(kind, label, n) for kind, label in RECEIVED_ORDER if (n := received.get(kind))],
    }, headers={"Cache-Control": "public, max-age=300"})
