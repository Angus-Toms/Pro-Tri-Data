import re
from datetime import date
from functools import lru_cache
from urllib.parse import urlencode

from fastapi import HTTPException, Request, APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import queries
from app.routers.router_utils import format_rating, format_rating_change, format_time, format_time_behind, ordinal

templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.filters["ordinal"]       = ordinal
router = APIRouter()

_GENDERS = ("male", "female")
# (key, tab label, category, course)
_PROGRAMS = [("short", "Short course", "elite", "short"),
             ("long",  "Long course",  "elite", "long"),
             ("ag",    "Age group",    "ag",    "short")]
_CONTINENT_ORDER = ["Europe", "Americas", "Asia", "Oceania", "Africa", "Other"]
# Championship medals. WTCS podiums are at single rounds of the series, so
# they are shown apart and never added in.
_MEDAL_LABELS = {"olympic-games": "Olympic Games",
                 "championship":  "World Championships",
                 "im-worlds":     "Ironman Worlds",
                 "im-703-worlds": "Ironman 70.3 Worlds"}

# Rows on wide screens; narrower layouts show fewer (CSS)
_RANK_ROWS   = 10
_RESULT_ROWS = 14
_RACING_ROWS = 3
_HOSTED_ROWS = 6
_NATION_ROWS = 10
_MEDAL_ROWS  = 10
_RELAY_ROWS  = 10   # relay results before "Show all"
_RESULT_DAYS = 90
_RACING_DAYS = 14

# Relay program labels, keyed on races.sub_category.
_RELAY_PROGRAM_LABELS = {
    "elite":  "Elite MTR",
    "u23":    "U23 MTR",
    "junior": "Junior MTR",
    "youth":  "Youth MTR",
    "ag":     "Age Group MTR",
}


def _strip_year(name):
    return re.sub(r"^\d{4}\s+", "", name)


@lru_cache(maxsize=1)
def _daily(day):
    """What /countries and every country page share, built once a day per
    process (`day` is the cache key): six full leaderboard queries (about
    0.6s), every completed event with its winners and championship medals by
    nation. Ratings only move with the nightly rebuild.

    Each list holds every active athlete in a programme, best first, and list
    position is the world rank: the stored rank is a snapshot from each
    athlete's last race, so it ties and runs out of order."""
    lists = {}
    for g in _GENDERS:
        for key, _, category, course in _PROGRAMS:
            rows = queries.get_leaderboard(g, "overall", "top", None, None, None, True, 0, 100_000,
                                           category=category, course=course)
            lists[(g, key)] = [{"athlete_id": a["athlete_id"], "name": a["name"],
                                "country_alpha3": a["country_alpha3"], "profile_img": a["profile_img"],
                                "world": i + 1, "rating": format_rating(a["overall_rating"]),
                                "chg": format_rating_change(a["overall_change"])}
                               for i, a in enumerate(rows)]
    return {"lists": lists,
            "events": queries.get_calendar_results(date(1979, 1, 1)),
            "medals": queries.get_championship_medals_by_country()}


@router.get("/countries", response_class=HTMLResponse)
def countries_index(request: Request):
    d = _daily(date.today())
    countries = queries.get_country_index()
    names = {c["alpha3"]: c["country_full"] for c in countries}

    # --- Strongest nations: places held in each world top 100. Ties go to
    # the nation with the better placed best athlete ---
    nations = []
    for key, label, _, _ in _PROGRAMS[:2]:
        pair = {}
        for g in _GENDERS:
            agg = {}
            for a in d["lists"][(g, key)][:100]:
                n = agg.setdefault(a["country_alpha3"], {"alpha3": a["country_alpha3"],
                                                         "name": names[a["country_alpha3"]],
                                                         "places": 0, "best": a["world"]})
                n["places"] += 1
            pair[g] = sorted(agg.values(), key=lambda n: (-n["places"], n["best"]))[:_NATION_ROWS]
        # Bars on one scale across the men's and women's lists
        top = max(n["places"] for g in _GENDERS for n in pair[g])
        for n in pair["male"] + pair["female"]:
            n["bar"] = round(100 * n["places"] / top)
        nations.append({"key": key, "label": label, **pair})

    # --- Championship medals, Olympic-table order ---
    medals = []
    for alpha3, tiers in d["medals"].items():
        gold, silver, bronze = (sum(tiers.get(t, (0, 0, 0))[i] for t in _MEDAL_LABELS) for i in range(3))
        if gold + silver + bronze:
            medals.append({"alpha3": alpha3, "name": names[alpha3],
                           "gold": gold, "silver": silver, "bronze": bronze})
    medals.sort(key=lambda m: (-m["gold"], -m["silver"], -m["bronze"], m["name"]))

    # --- Every country, by continent ---
    groups = {c: [] for c in _CONTINENT_ORDER}
    for c in countries:
        groups[c["continent"]].append(c)

    return templates.TemplateResponse("countries_index.html", {
        "request":     request,
        "active_page": "countries",
        "nations":     nations,
        "medals":      medals[:_MEDAL_ROWS],
        "groups":      [(cont, groups[cont]) for cont in _CONTINENT_ORDER if groups[cont]],
        # Neutral and unknown banners are listed, not counted as nations
        "n_nations":   sum(c["continent"] != "Other" for c in countries),
    })


def _relay(country_full):
    """The mixed relay section: rating, world rank by list position among
    active relay nations, elite record, results with leg splits and rating
    history. None if the nation has never raced one."""
    s = queries.get_country_relay_summary(country_full)
    if not s:
        return None
    extremes = queries.get_country_relay_rating_extremes(country_full)
    ratings = []
    for disc in ("overall", "swim", "bike", "run", "transition"):
        board = queries.get_relay_leaderboard(disc, "top", True, 0, limit=1000)
        ratings.append({
            "disc":         disc,
            "label":        disc.title(),
            "rating":       format_rating(s[f"{disc}_rating"]),
            "rank":         next((i + 1 for i, r in enumerate(board) if r["country_full"] == country_full), None),
            "peak":         format_rating(extremes[f"{disc}_peak"]),
            "peak_race":    extremes[f"{disc}_peak_race"],
            "peak_race_id": extremes[f"{disc}_peak_race_id"],
            "best_race":    extremes[f"{disc}_best_race"],
            "best_race_id": extremes[f"{disc}_best_race_id"],
            "best_change":  format_rating_change(extremes[f"{disc}_best_change"]),
        })

    legs_by_team = queries.get_country_relay_legs(country_full)
    results = []
    for r in queries.get_country_relay_results(country_full):
        r["total"] = format_time(r["total_s"]) if r["total_s"] else ""
        r["behind"] = (format_time_behind(r["total_s"] - r["winner_total_s"])
                       if r["total_s"] and r["winner_total_s"] else "")
        r["program"] = _RELAY_PROGRAM_LABELS[r["sub_category"]]
        r["legs"] = legs_by_team.get((r["race_id"], r["team_id"]), [])
        for l in r["legs"]:
            l["leg"] = format_time(l["leg_s"]) if l["leg_s"] else ""
            l["leg_behind"] = (format_time_behind(l["leg_s"] - l["leg_best_s"])
                               if l["leg_best_s"] and (l["leg_s"] or 0) > l["leg_best_s"]
                               else "")
            l["leg_fastest"] = bool(l["leg_best_s"] and l["leg_s"] == l["leg_best_s"])
            # Gaps are to the fastest split on the same leg of the same
            # race, matching the relay race page's panel.
            for d in ("swim", "t1", "bike", "t2", "run"):
                l[d] = format_time(l[f"{d}_s"]) if l[f"{d}_s"] else ""
                raw, fast = l[f"{d}_s"] or 0, l[f"{d}_best_s"]
                l[f"{d}_fastest"] = bool(fast and raw == fast)
                l[f"{d}_behind"] = (format_time_behind(raw - fast)
                                    if fast and raw > fast else "")
        results.append(r)

    history = []
    for h in queries.get_country_relay_rating_history(country_full):
        h["program"] = _RELAY_PROGRAM_LABELS[h["sub_category"]]
        for d in ("overall", "swim", "bike", "run", "transition"):
            h[f"{d}_change"] = format_rating_change(h[f"{d}_change"])
            h[f"{d}_rating"] = format_rating(h[f"{d}_rating"])
        history.append(h)

    return {"rating": ratings[0]["rating"], "rank": ratings[0]["rank"],
            "starts": s["race_count"], "wins": s["wins"], "podiums": s["podiums"],
            "ratings": ratings, "results": results, "history": history}


@router.get("/country/{alpha3}", response_class=HTMLResponse)
def country_detail(request: Request, alpha3: str):
    country = queries.get_country_by_alpha3(alpha3.upper())
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")
    a3, name = country["alpha3"], country["country_full"]
    d = _daily(date.today())

    # --- National rankings: everyone who has raced for the nation, with
    # their world rank ---
    members = queries.get_country_member_ids(a3)
    rankings = []
    for key, label, category, course in _PROGRAMS:
        lists = {g: [a for a in d["lists"][(g, key)] if a["athlete_id"] in members][:_RANK_ROWS]
                 for g in _GENDERS}
        if lists["male"] or lists["female"]:
            rankings.append({"key": key, "label": label, **lists,
                             "href": "/athlete-leaderboard?" + urlencode(
                                 {"gender": "male", "country": name, "category": category, "course": course})})
    # The leaderboard filters on current nationality, so a home nation whose
    # athletes now race for Great Britain gets no link to an empty list
    rank_link = any(a["country_alpha3"] == a3 for p in rankings for g in _GENDERS for a in p[g])

    # --- Recent results and who races next ---
    results = {g: [] for g in _GENDERS}
    for r in queries.get_country_recent_results(a3, _RESULT_DAYS):
        if len(results[r["gender"]]) < _RESULT_ROWS:
            results[r["gender"]].append({**r, "race": _strip_year(r["race_title"])})
    racing = {g: [] for g in _GENDERS}
    for a in queries.get_country_upcoming_starters(a3, _RACING_DAYS):
        if len(racing[a["gender"]]) < _RACING_ROWS:
            racing[a["gender"]].append({**a, "race": _strip_year(a["race_title"])})

    # --- Championship medals; WTCS round podiums apart ---
    tiers = d["medals"].get(a3, {})
    medals = [{"label": label, "gold": tiers[t][0], "silver": tiers[t][1], "bronze": tiers[t][2]}
              for t, label in _MEDAL_LABELS.items() if t in tiers]
    wtcs = tiers.get("wtcs")

    # --- Events hosted, under any of the nation's spellings ---
    spellings = set(country["spellings"])
    hosted_recent = [{**e, "short_name": _strip_year(e["name"])}
                     for e in d["events"] if e["country"] in spellings][:_HOSTED_ROWS]
    hosted_upcoming = [{**e, "short_name": _strip_year(e["name"]),
                        "entries": sum(r["entry_count"] for r in e["races"])}
                       for e in queries.get_upcoming_events() if e["country"] in spellings][:_HOSTED_ROWS]
    locations = [loc for s in spellings for loc in queries.get_country_hosted_race_locations(s)]
    map_locations = [{"lat": loc["latitude"], "lng": loc["longitude"], "label": loc["event_name"],
                      "year": loc["start_date"].year if loc["start_date"] else None}
                     for loc in _filter_map_outliers(locations)]

    n, m = country["athlete_count"], country["race_host_count"]
    subtitle = f"{n:,} athlete{'s have' if n != 1 else ' has'} raced for {name}"
    if m:
        subtitle += f" and {m:,} event{'s have' if m != 1 else ' has'} been held there"
    leader = next((p["male"][0] if p["male"] else p["female"][0] for p in rankings), None)
    meta_description = (f"Triathlon in {name}: national rankings, recent results and championship medals. "
                        + (f"{leader['name']} leads the national rankings." if leader else ""))

    return templates.TemplateResponse("country.html", {
        "request":          request,
        "active_page":      "countries",
        "country":          country,
        "subtitle":         subtitle + ".",
        "meta_description": meta_description.strip(),
        "rankings":         rankings,
        "rank_link":        rank_link,
        "results":          results,
        "result_days":      _RESULT_DAYS,
        "racing":           racing,
        "medals":           medals,
        "wtcs":             wtcs,
        "relay":            _relay(name),
        "relay_rows":       _RELAY_ROWS,
        "hosted_recent":    hosted_recent,
        "hosted_upcoming":  hosted_upcoming,
        "map_locations":    map_locations,
    })


def _filter_map_outliers(locs, lat_thresh=15.0, lng_thresh=25.0):
    """Drop locations far from the median - catches obvious geocoding mistakes.

    Uses the median as a robust centre (unaffected by the outliers we're trying
    to remove). Thresholds are generous enough to retain legitimate spread for
    mid-to-large countries while clearly rejecting points on the wrong continent.
    """
    if len(locs) < 4:
        return locs
    lats = sorted(l["latitude"] for l in locs)
    lngs = sorted(l["longitude"] for l in locs)
    mid_lat = lats[len(lats) // 2]
    mid_lng = lngs[len(lngs) // 2]
    return [l for l in locs
            if abs(l["latitude"]  - mid_lat) <= lat_thresh
            and abs(l["longitude"] - mid_lng) <= lng_thresh]
