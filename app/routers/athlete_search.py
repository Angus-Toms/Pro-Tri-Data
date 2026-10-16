import re
from datetime import date, timedelta
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag

from ptd_data import queries
from app.routers.router_utils import format_rating, format_rating_change, ordinal
from app.routers.search import format_athlete_results

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.filters["ordinal"]       = ordinal

# (key, tab label, category, course) for the rankings tabs
_PROGRAMS = [("short", "Short course", "elite", "short"),
             ("long",  "Long course",  "elite", "long"),
             ("ag",    "Age group",    "ag",    "short")]
_GENDERS = ("male", "female")
# Breakthrough and next-generation rows on wide screens, where they sit beside
# the rail and fill down to Specialists; narrower layouts show fewer (CSS)
_BT_ROWS  = 7
_GEN_ROWS = 5


def _lb(gender, disc="overall", order="top", limit=10, course="short", category="elite", yob_start=None):
    """Active leaderboard rows, trimmed to what the hub shows."""
    return [{"athlete_id": a["athlete_id"], "name": a["name"], "country_alpha3": a["country_alpha3"],
             "country_full": a["country_full"], "profile_img": a["profile_img"],
             "year_of_birth": a["year_of_birth"], "starts": a["race_starts"], "wins": a["wins"],
             "rating": format_rating(a[f"{disc}_rating"]),
             "change": int(round(a[f"{disc}_change"] or 0)),
             "chg": format_rating_change(a[f"{disc}_change"] or 0)}
            for a in queries.get_leaderboard(gender, disc, order, None, yob_start, None, True, 0, limit,
                                             category=category, course=course)]


@lru_cache(maxsize=1)
def _hub_lists(day):
    """The page's ranking-derived lists. About twenty leaderboard queries at
    ~70ms each, and ratings only move with the weekly rebuild, so they are
    built once a day per process (`day` is the cache key)."""
    year = day.year

    # Elite top 100 per gender and course. The rankings tables show the first
    # ten, and list position is the world rank used everywhere below: the
    # stored rank is a snapshot from each athlete's last race, so it ties and
    # runs out of order.
    top = {(g, c): _lb(g, limit=100, course=c) for g in _GENDERS for c in ("short", "long")}
    pos = {k: {a["athlete_id"]: i + 1 for i, a in enumerate(v)} for k, v in top.items()}

    # --- World rankings ---
    rankings = []
    for key, label, category, course in _PROGRAMS:
        lists = ({g: top[(g, course)][:10] for g in _GENDERS} if category == "elite"
                 else {g: _lb(g, course=course, category=category) for g in _GENDERS})
        rankings.append({"key": key, "label": label, **lists,
                         "href": f"/athlete-leaderboard?gender=male&course={course}&category={category}"})

    # --- Breakthroughs: biggest 12-month gains among today's top 50, five
    # starts or more (thin records swing hardest and aren't breakthroughs) ---
    breakthroughs = []
    for course, label in (("long", "Long course"), ("short", "Short course")):
        lists = {}
        for g in _GENDERS:
            hot = [a for a in _lb(g, order="hot", limit=400, course=course)
                   if pos[(g, course)].get(a["athlete_id"], 999) <= 50 and a["starts"] >= 5][:_BT_ROWS]
            for a in hot:
                a["now"] = pos[(g, course)][a["athlete_id"]]
            lists[g] = hot
        breakthroughs.append({"key": course, "label": label, **lists,
                              "href": f"/athlete-leaderboard?gender=male&course={course}&order=hot"})

    # --- Specialists: the best current discipline rating, short course ---
    specialists = [{"label": d.title(), **{g: _lb(g, disc=d, limit=3) for g in _GENDERS}}
                   for d in ("swim", "bike", "run")]

    # --- Next generation: the top under-23s, short course ---
    next_gen = {g: _lb(g, limit=_GEN_ROWS, yob_start=year - 22) for g in _GENDERS}
    for g in _GENDERS:
        for a in next_gen[g]:
            a["age"] = year - a["year_of_birth"]
            a["now"] = pos[(g, "short")].get(a["athlete_id"])

    # --- Nations: places held in the four world top 100s, and each one's
    # best-placed athlete ---
    nations = {}
    for (g, course), rows in top.items():
        for i, a in enumerate(rows):
            n = nations.setdefault(a["country_full"], {"country": a["country_full"], "places": 0, "best": None})
            n["places"] += 1
            if n["best"] is None or i + 1 < n["best"]["now"]:
                n["best"] = {**a, "now": i + 1, "course": course}
    nations = sorted(nations.values(), key=lambda n: (-n["places"], n["best"]["now"]))[:6]
    for n in nations:
        n["bar"] = round(100 * n["places"] / nations[0]["places"])

    return {"rankings": rankings, "breakthroughs": breakthroughs, "specialists": specialists,
            "next_gen": next_gen, "nations": nations}


def _racing_soon(today):
    """The coming week's most-entered event with predictions, with each
    gender's three favourites. Start lists change daily, so this isn't cached."""
    events = [e for e in queries.get_upcoming_events() if e["start_date"] <= today + timedelta(days=7)]
    for e in events:
        e["entries"] = sum(r["entry_count"] or 0 for r in e["races"])
        # get_upcoming_events puts the elite men's and women's programmes first
        for g in _GENDERS:
            e[g] = next((r for r in e["races"] if r["gender"] == g and r["category"] == "elite"), None)
    top = queries.get_predicted_top([e[g]["race_id"] for e in events for g in _GENDERS if e[g]], 3)
    events = [e for e in events if any(e[g] and top.get(e[g]["race_id"]) for g in _GENDERS)]
    if not events:
        return None
    e = max(events, key=lambda e: e["entries"])
    return {"event_id": e["event_id"], "name": re.sub(r"^\d{4}\s+", "", e["name"]),
            "date": e["start_date"], "entries": e["entries"],
            **{g: top.get(e[g]["race_id"], []) if e[g] else [] for g in _GENDERS}}


@router.get("/athletes", response_class=HTMLResponse)
def athletes_landing(request: Request):
    today = date.today()
    country_list = queries.get_country_list()
    return templates.TemplateResponse("athlete_search.html", {
        "request":         request,
        "active_page":     "athletes",
        "total_athletes":  queries.get_counts()["athletes"],
        "country_list":    country_list,
        "year":            today.year,
        "racing":          _racing_soon(today),
        **_hub_lists(today),
    })


@router.get("/athletes/search")
def search_athletes(
    q: str = "",
    country: str = "",
    yob_start: str = "",
    yob_end: str = "",
    program: str = "",
    active_only: str = "",
):
    """Athletes for the hero search, in the header search's shape so the page
    renders them with header.js's rows."""
    q = q.strip()
    if len(q) < 2:
        return JSONResponse({"athletes": [], "athletes_total": 0})
    res = queries.search_athletes(
        q,
        country=country or None,
        yob_start=int(yob_start) if yob_start.isdigit() else None,
        yob_end=int(yob_end) if yob_end.isdigit() else None,
        program=program if program in ("short", "long", "ag") else None,
        active_only=active_only == "true",
    )
    return JSONResponse(format_athlete_results(res))
