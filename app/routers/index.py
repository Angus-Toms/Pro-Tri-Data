import re

import anyio
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import queries
from ptd_users import queries as uq
from app.routers.about import load_blogs
from app.routers.event_page import _predicted_podium
from app.routers.router_utils import format_rating_change

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag

RANKING_TABS = [
    ("short", "Short course", "elite", "short"),
    ("long",  "Long course",  "elite", "long"),
    ("ag",    "Age group",    "ag",    "short"),
]


def sparkline(vals, w=100.0, h=28.0, pad=3.0):
    """Polyline points for a list of ratings, oldest first, in a w x h viewBox."""
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(vals)
    return " ".join(f"{(i / (n - 1)) * w:.1f},{pad + (1 - (v - lo) / span) * (h - 2 * pad):.1f}"
                    for i, v in enumerate(vals))


def _pair(races):
    """The first men's and first women's programme, men left. Falls back to
    the first two when an event only has one gender."""
    men   = next((r for r in races if r["gender"] == "male"), None)
    women = next((r for r in races if r["gender"] == "female"), None)
    return [r for r in (men, women) if r] if men and women else races[:2]


async def _race_counts(race_ids):
    return await uq.follower_counts("race", race_ids), await uq.comment_counts(race_ids)


@router.get("/")
def index(request: Request):

    # --- latest results: the latest weekend's biggest elite events, two
    # programmes each (men first); the template shows the fourth and fifth on wide screens ---
    recent = queries.get_headline_events(5)
    for e in recent:
        e["races"] = _pair(e["races"])

    # --- this weekend: the next three events with their predicted podiums ---
    all_upcoming = queries.get_upcoming_events()
    # Only elite races carry predictions; an event whose first two programmes
    # are age-group start lists would show two empty columns, so prefer events
    # with a predicted podium and fall back to the next three if none have one.
    candidates = all_upcoming[:8]
    entries = queries.get_upcoming_race_entries_bulk(
        [r["race_id"] for e in candidates for r in _pair(e["races"])])
    for e in candidates:
        e["entries"] = sum(r["entry_count"] or 0 for r in e["races"])
        e["races"] = _pair(e["races"])
        for r in e["races"]:
            r["podium"] = _predicted_podium(entries.get(r["race_id"], []), r)
    upcoming = [e for e in candidates if any(r["podium"] for r in e["races"])][:3] or candidates[:3]

    # Like and comment counts live in Postgres; the handler is sync
    # (threadpool-limited, see main.py) so hop to the event loop for them.
    race_ids = [r["race_id"] for e in recent + upcoming for r in e["races"]]
    likes, comments = anyio.from_thread.run(_race_counts, race_ids)
    for e in recent + upcoming:
        for r in e["races"]:
            r["likes"]    = likes.get(r["race_id"], 0)
            r["comments"] = comments.get(r["race_id"], 0)

    # --- schedule strip: the latest weekend's four biggest elite events, then
    # the next six. An upcoming event says what it has: a predicted podium, a
    # start list for its elite races, or neither yet. ---
    def strip_item(e, status):
        return {"href": f"/event/{e['event_id']}", "date": e["start_date"],
                "name": re.sub(r"^\d{4}\s+", "", e["name"]), "status": status}
    def upcoming_status(e):
        if any(r["podium"] for r in e["races"]):
            return "Predictions"
        return "Start list" if any(r["entry_count"] for r in e["races"]) else "Upcoming"
    schedule = ([strip_item(e, "Results") for e in reversed(queries.get_headline_events(4))]
                + [strip_item(e, upcoming_status(e)) for e in all_upcoming[:6]])

    # --- on the rise: biggest gains per course over 30 days, men then women ---
    risers = []
    for course, label in (("short", "Short course"), ("long", "Long course")):
        by_gender = {g: queries.get_rating_risers(g, course) for g in ("male", "female")}
        points = queries.get_recent_rating_points_bulk(
            [r["athlete_id"] for rows in by_gender.values() for r in rows], course)
        for rows in by_gender.values():
            for r in rows:
                r["change"] = format_rating_change(r["overall_change"])
                r["spark"]  = sparkline(points.get(r["athlete_id"], []))
                r["race_short"] = re.sub(r"^\d{4}\s+", "", r["race_title"])
        risers.append({"key": course, "label": label, "men": by_gender["male"], "women": by_gender["female"]})

    rankings = [{"key": key, "label": label,
                 "men":   queries.get_podium("male",   cat, course, limit=5),
                 "women": queries.get_podium("female", cat, course, limit=5)}
                for key, label, cat, course in RANKING_TABS]

    counts = queries.get_counts()
    blogs = load_blogs()
    return templates.TemplateResponse("index.html", {
        "request":        request,
        "active_page":    "home",
        "schedule":       schedule,
        "upcoming":       upcoming,
        "recent":         recent,
        "risers":         risers,
        "rankings":       rankings,
        "blogs":          blogs[:2],
        "total_athletes": counts["athletes"],
        "total_races":    counts["races"],
        "total_results":  counts["results"],
    # The race cards carry like and comment counts, so five minutes at the
    # edge rather than the default hour
    }, headers={"Cache-Control": "public, max-age=0, s-maxage=300"})
