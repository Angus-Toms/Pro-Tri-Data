import re
from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag
from app.routers.router_utils import ordinal

from ptd_data import queries

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.filters["ordinal"]       = ordinal

_WEEKS_SHOWN  = 3   # calendar weeks per tab; tablet and phone show two
_PER_WEEK     = 4   # events per week, the rest go in the "Also" line
_SEASON_LIMIT = 8   # rows per season list on desktop; narrower screens hide the tail

_DISTANCE_LABEL = {"sprint": "Sprint", "standard": "Standard", "middle": "Middle distance",
                   "long": "Long distance", "t100": "T100"}


def _strip_year(name):
    return re.sub(r"^\d{4}\s+", "", name)


def _round_name(name):
    """The venue end of an event name, for a series round where the series
    name says the rest: "2026 World Triathlon Cup Beijing" -> "Beijing"."""
    return re.sub(r"^.*\b(?:Series|Cup|Championships?|Finals)\s+", "", _strip_year(name))


def _fmt_margin(s):
    s = int(round(s))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _week_blocks(events, today, newest_first):
    """Monday-start weeks holding events, nearest first. Each shows its four
    strongest events in date order; the rest are named in an "Also" line."""
    monday = today - timedelta(days=today.weekday())
    weeks = {}
    for e in events:
        weeks.setdefault((e["date"] - monday).days // 7, []).append(e)
    blocks = []
    for offset in sorted(weeks, reverse=newest_first)[:_WEEKS_SHOWN]:
        ranked = sorted(weeks[offset], key=lambda e: (e["strength"] is None, e["strength"] or 0))
        # Stable sort, so a shared date keeps the stronger event first
        shown = sorted(ranked[:_PER_WEEK], key=lambda e: e["date"])

        label = {0: "This week", 1: "Next week", -1: "Last week"}.get(
            offset, f"In {offset} weeks" if offset > 0 else f"{-offset} weeks ago")
        lo, hi = shown[0]["date"], shown[-1]["date"]
        if lo == hi:
            span = lo.strftime("%-d %b")
        elif lo.month == hi.month:
            span = f"{lo.day} to {hi.strftime('%-d %b')}"
        else:
            span = f"{lo.strftime('%-d %b')} to {hi.strftime('%-d %b')}"

        blocks.append({"label": label, "span": span, "events": shown, "also": ranked[_PER_WEEK:]})
    return blocks


def _upcoming_calendar(today):
    """Upcoming events with each gender's headline programme, its favourite
    and the event's predicted field strength."""
    events = queries.get_upcoming_events()
    for e in events:
        e["date"] = max(e["start_date"], today)
        e["entries"] = sum(r["entry_count"] or 0 for r in e["races"])
        # get_upcoming_events puts the elite men's and women's programmes first
        for g in ("male", "female"):
            e[g] = next((r for r in e["races"] if r["gender"] == g and r["category"] == "elite"), None)

    progs = [e[g] for e in events for g in ("male", "female") if e[g]]
    favourites = queries.get_race_favourites([r["race_id"] for r in progs])
    # Strength from the elite / pro fields only, as for completed events. The
    # upcoming feed is World Triathlon's, so every field is short course.
    elite = [r for r in progs if r["prog_name"].split()[0].lower() in ("elite", "pro")]
    stds = queries.get_upcoming_race_standards_bulk([r["race_id"] for r in elite])
    shares = queries.standard_rank_shares({
        r["race_id"]: (r["gender"], "short", stds[r["race_id"]]["overall"])
        for r in elite if stds[r["race_id"]]["overall"]})
    for e in events:
        for g in ("male", "female"):
            if e[g]:
                e[g]["favourite"] = favourites.get(e[g]["race_id"])
        own = [shares[e[g]["race_id"]] for g in ("male", "female") if e[g] and e[g]["race_id"] in shares]
        e["strength"] = min(own) if own else None
    return events


@router.get("/races", response_class=HTMLResponse)
def races_landing(request: Request):
    today = date.today()

    # --- calendar ---
    results = queries.get_calendar_results(today - timedelta(weeks=10))
    for e in results:
        for g in ("male", "female"):
            if e[g] and e[g]["margin"] is not None:
                e[g]["margin_fmt"] = _fmt_margin(e[g]["margin"])
    up_blocks  = _week_blocks(_upcoming_calendar(today), today, newest_first=False)
    res_blocks = _week_blocks(results, today, newest_first=True)
    shown = [e for b in up_blocks + res_blocks for e in b["events"] + b["also"]]
    meta = queries.get_events_meta({e["event_id"] for e in shown})
    for e in shown:
        e.update(meta[e["event_id"]])
        e["short_name"] = _strip_year(e["name"])
        e["kind"] = e["series"] or _DISTANCE_LABEL.get(e.get("distance"))

    # Results lead early in the week, while last weekend is the news
    tab = "res" if today.weekday() < 2 else "up"
    if not up_blocks:
        tab = "res"
    if not res_blocks:
        tab = "up"

    # --- the season so far ---
    summary = queries.get_races_summary()
    season_year = summary["last_date"].year
    strongest = queries.get_season_strongest_fields(season_year, _SEASON_LIMIT)
    upsets    = queries.get_season_upsets(season_year, _SEASON_LIMIT)
    closest   = queries.get_season_closest_finishes(season_year, _SEASON_LIMIT)
    for r in strongest + upsets + closest:
        r["short_name"] = _strip_year(r["event_name"])
    for r in closest:
        r["margin_fmt"] = _fmt_margin(r["margin"])

    # --- rail ---
    series = queries.get_series_hub(today.year, 5)
    for s in series:
        s["next_round"] = s["next_name"] and _round_name(s["next_name"])
        s["last_round"] = s["last_name"] and _round_name(s["last_name"])

    # Races with history: the longest-running races with an edition in the
    # month either side of today, topped up with the longest-running overall
    recurring = queries.get_recurring_index()
    near = [r for r in recurring
            if r["last_date"] >= today - timedelta(days=30)
            or (r["next_date"] and r["next_date"] <= today + timedelta(days=30))]
    near_slugs = {r["slug"] for r in near}
    history = (near + [r for r in recurring if r["slug"] not in near_slugs])[:4]
    for h in history:
        h["winners"] = [{"athlete_id": h[f"{g}_winner_id"], "name": h[f"{g}_winner"],
                         "country_alpha3": h[f"{g}_winner_alpha3"], "profile_img": h[f"{g}_winner_img"]}
                        for g in ("male", "female") if h[f"{g}_winner_id"]]

    ag_event = queries.get_latest_series_event("ag-world-champs")
    if ag_event:
        ag_event["short_name"] = _strip_year(ag_event["name"])

    return templates.TemplateResponse("race_search.html", {
        "request":      request,
        "active_page":  "races",
        "summary":      summary,
        "country_list": queries.get_event_countries(),
        "tab":          tab,
        "up_blocks":    up_blocks,
        "res_blocks":   res_blocks,
        "season_year":  season_year,
        "season_open":  season_year == today.year,
        "strongest":    strongest,
        "upsets":       upsets,
        "closest":      closest,
        "series":       series,
        "history":      history,
        "ag_event":     ag_event,
    })


_RECENT_PAGE = 10


@router.get("/recent", response_class=HTMLResponse)
def recent_results(request: Request):
    events = queries.get_recent_events(offset=0, limit=_RECENT_PAGE)
    return templates.TemplateResponse("recent.html", {
        "request":     request,
        "active_page": "recent",
        "events":      events,
        "has_more":    len(events) == _RECENT_PAGE,
    })


@router.get("/recent/more", response_class=HTMLResponse)
def recent_results_more(request: Request, offset: int = Query(0, ge=0)):
    events = queries.get_recent_events(offset=offset, limit=_RECENT_PAGE)
    return templates.TemplateResponse("partials/recent_events.html", {
        "request": request,
        "events":  events,
    })


@router.get("/races/search")
def search_races(
    q:          str = Query(""),
    country:    str = Query(""),
    year_start: str = Query(""),
    year_end:   str = Query(""),
    sort:       str = Query("desc"),
):
    if not q or len(q.strip()) < 2:
        return JSONResponse([])
    results = queries.search_events_full(
        query=q.strip(),
        country=country or None,
        year_start=year_start or None,
        year_end=year_end or None,
        sort=sort if sort in ("asc", "desc") else "desc",
        limit=20,
    )
    for r in results:
        d = r["start_date"]
        r["event_date"] = d.strftime("%-d %b %Y") if hasattr(d, "strftime") else str(d)
        del r["start_date"]
    return JSONResponse(results)
