from datetime import date
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag

from ptd_data import queries
from app.routers.router_utils import format_rating, format_rating_change

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag

_PAGE  = 50
_DISCS = ("overall", "swim", "bike", "run", "transition")
# Gain lists leave out thin records, which swing hardest (as on /athletes)
_HOT_MIN_STARTS = 5
# Every filter at its default. Gender is always written into links, so a link
# says which list it opens rather than leaning on the women's default.
_DEFAULTS = {"gender": "female", "disc": "overall", "order": "top", "country": "all",
             "yob_start": 1930, "yob_end": 2010, "active_only": True,
             "category": "elite", "course": "short"}
# (switch label, phone label, category, course)
_PROGRAMS = [("Short course", "Short", "elite", "short"), ("Long course", "Long", "elite", "long"),
             ("Age group", "Age group", "ag", "short"), ("Mixed relay", "Relay", "elite", "relay")]


def _url(state, path="/athlete-leaderboard", **changes):
    s = {**state, **changes}
    params = {k: v for k, v in s.items() if k == "gender" or v != _DEFAULTS[k]}
    if "active_only" in params:
        params["active_only"] = "false"
    return f"{path}?{urlencode(params)}"


def _rows(state, offset):
    """One page of the list and whether another follows. Rank is list
    position: the stored rank is a snapshot from each athlete's last race, so
    it ties and runs out of order."""
    disc, order = state["disc"], state["order"]
    if state["course"] == "relay":
        rows = queries.get_relay_leaderboard(disc, order, state["active_only"], offset, limit=_PAGE + 1)
    else:
        rows = queries.get_leaderboard(
            state["gender"], disc, order, state["country"], state["yob_start"], state["yob_end"],
            state["active_only"], offset, limit=_PAGE + 1, category=state["category"],
            course=state["course"], min_starts=_HOT_MIN_STARTS if order == "hot" else 0,
        )
    for i, a in enumerate(rows):
        a["rank"] = offset + i + 1
        a["ratings"] = {d: format_rating(a[f"{d}_rating"]) for d in _DISCS}
        a["chg"] = format_rating_change(a[f"{disc}_change"])
    return rows[:_PAGE], len(rows) > _PAGE


def _subtitle(s):
    """What the list is, in one line."""
    if s["course"] == "relay":
        out = "National mixed relay teams"
    else:
        out = f"{'Age-group' if s['category'] == 'ag' else 'Elite'} {'men' if s['gender'] == 'male' else 'women'}"
        if s["country"] != "all":
            out += f" from {s['country']}"
        if s["category"] == "elite":
            out += f" on {s['course']} course"
        lo, hi = s["yob_start"] != _DEFAULTS["yob_start"], s["yob_end"] != _DEFAULTS["yob_end"]
        if lo or hi:
            born = (f"{s['yob_start']} to {s['yob_end']}" if lo and hi
                    else f"{s['yob_start']} or later" if lo else f"{s['yob_end']} or earlier")
            # The filter keeps athletes with no recorded birth year
            out += f", born {born} (or unknown)"
    disc = f"{s['disc']} "
    out += (f", by {disc}rating change over the last 12 months" if s["order"] == "hot"
            else f", by current {disc}rating")
    out += ". " + ("Raced in the last 18 months" if s["active_only"]
                   else "Includes retired athletes at their last rating")
    if s["order"] == "hot" and s["course"] != "relay":
        out += f", {_HOT_MIN_STARTS} or more starts"
    return out + "."


def _state(gender, disc, order, country, yob_start, yob_end, active_only, category, course):
    # Relay ratings belong to nations: no gender, age group, country or age
    if course == "relay":
        category, country, yob_start, yob_end = "elite", "all", 1930, 2010
    # Age group racing has short course ratings only
    if category == "ag":
        course = "short"
    return {"gender": gender, "disc": disc, "order": order, "country": country,
            "yob_start": yob_start, "yob_end": yob_end, "active_only": active_only,
            "category": category, "course": course}


@router.get("/athlete-leaderboard")
def leaderboard(
    request: Request,
    gender:      str           = Query("female", regex="^(male|female)$"),
    disc:        str           = Query("overall", regex="^(overall|swim|bike|run|transition)$"),
    order:       str           = Query("top", regex="^(top|hot)$"),
    country:     str           = Query("all"),
    yob_start:   Optional[int] = Query(1930, ge=1930, le=2010),
    yob_end:     Optional[int] = Query(2010, ge=1930, le=2010),
    active_only: bool          = Query(True),
    category:    str           = Query("elite", regex="^(elite|ag)$"),
    course:      str           = Query("short", regex="^(short|long|relay)$"),
):
    s = _state(gender, disc, order, country, yob_start, yob_end, active_only, category, course)
    athletes, has_more = _rows(s, 0)
    is_relay = s["course"] == "relay"
    title = f"{s['country']} rankings" if s["country"] != "all" else "World rankings"
    programs = [{"label": label, "short": short, "href": _url(s, category=cat, course=crs),
                 "active": (s["category"], s["course"]) == (cat, crs)}
                for label, short, cat, crs in _PROGRAMS]
    genders = [{"label": label, "href": _url(s, gender=g), "active": s["gender"] == g}
               for g, label in (("male", "Men"), ("female", "Women"))]
    # The Filters button carries how many of its panel's filters are set, as
    # the panel starts closed
    n_filters = (sum(s[k] != _DEFAULTS[k] for k in ("country", "active_only"))
                 + (s["yob_start"] != _DEFAULTS["yob_start"] or s["yob_end"] != _DEFAULTS["yob_end"]))
    return templates.TemplateResponse("leaderboard.html", {
        "request":       request,
        "active_page":   "athletes",
        "athletes":      athletes,
        "has_more":      has_more,
        "all_countries": queries.get_country_list(),
        **s,
        "is_relay":      is_relay,
        "title":         title,
        "subtitle":      _subtitle(s),
        "programs":      programs,
        "genders":       genders,
        "n_filters":     n_filters,
        "year":          date.today().year,
        "rank_links":    {o: _url(s, order=o) for o in ("top", "hot")},
        "more_url":      _url(s, path="/athlete-leaderboard/more"),
        "download_url":  _url(s, path="/download/leaderboard"),
        "reset_url":     _url({**_DEFAULTS, "gender": s["gender"], "category": s["category"], "course": s["course"]}),
    })


@router.get("/athlete-leaderboard/more")
def leaderboard_more(
    request: Request,
    gender:      str           = Query("female", regex="^(male|female)$"),
    disc:        str           = Query("overall", regex="^(overall|swim|bike|run|transition)$"),
    order:       str           = Query("top", regex="^(top|hot)$"),
    country:     str           = Query("all"),
    yob_start:   int           = Query(1930),
    yob_end:     int           = Query(2010),
    active_only: bool          = Query(True),
    offset:      int           = Query(0),
    category:    str           = Query("elite", regex="^(elite|ag)$"),
    course:      str           = Query("short", regex="^(short|long|relay)$"),
):
    s = _state(gender, disc, order, country, yob_start, yob_end, active_only, category, course)
    athletes, has_more = _rows(s, offset)
    response = templates.TemplateResponse("partials/more_athlete_leaderboard.html", {
        "request":  request,
        "athletes": athletes,
        "disc":     s["disc"],
        "order":    s["order"],
        "is_relay": s["course"] == "relay",
    })
    response.headers["X-Has-More"] = "1" if has_more else "0"
    return response
