from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag

from ptd_data import queries
from app.routers import router_utils
from app.routers.router_utils import format_1yr_rating_change, format_rating

# Consistent athlete colours used across all charts and tables, by slot.
# Mirrored in comparison.js (ATHLETE_COLORS) for the selection cards.
ATHLETE_COLORS = ["#357ABD", "#E91E63", "#059669", "#F59E0B", "#7E57C2"]
MAX_ATHLETES = len(ATHLETE_COLORS)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag


# Program -> (course, category). AG is always short-course.
_PROGRAMS = {
    'elite-short': ('short', 'elite'),
    'elite-long':  ('long',  'elite'),
    'ag':          ('short', 'ag'),
}


def _parse_program(program: str):
    return _PROGRAMS.get(program, _PROGRAMS['elite-short'])


@router.get("/athlete-compare", response_class=HTMLResponse)
def compare_page(request: Request):
    return templates.TemplateResponse("comparison.html", {
        "request": request, "active_page": "athletes",
    })


@router.get("/athlete-compare/search")
def search_athletes_for_compare(q: str = "", gender: str = "", programs: str = ""):
    if not q or len(q.strip()) < 2:
        return JSONResponse([])
    require_programs = [p for p in programs.split(",") if p in _PROGRAMS] or None
    results = queries.search_athletes(
        q.strip(), gender=gender or None, require_programs=require_programs
    )
    for r in results:
        r["country_name"] = r.pop("country_full")
    return JSONResponse(results)


@router.get("/athlete-compare/athlete/{athlete_id}")
def get_athlete_for_compare(athlete_id: int, program: str | None = None):
    info = queries.get_athlete_info(athlete_id)
    if not info:
        return JSONResponse({"error": "Not found"}, status_code=404)
    programs = queries.get_athlete_programs(athlete_id)
    # If caller passed ?program=, honour it (falling back if the athlete doesn't
    # have that program). Otherwise pick the first available — favours
    # elite-short, then elite-long, then ag per get_athlete_programs ordering.
    if program in _PROGRAMS and program in programs:
        active_program = program
    elif programs:
        active_program = programs[0]
    else:
        active_program = 'elite-short'
    course, category = _parse_program(active_program)
    ratings = queries.get_athlete_current_ratings(athlete_id, category=category, course=course)
    stats   = queries.get_athlete_stats(athlete_id, category=category, course=course)

    # World rank: mirror the athlete page (where users arrive from) rather than
    # the raw all-time snapshot in get_athlete_current_ratings. Active athletes
    # (raced within 18 months) show their rank among active peers; retired ones
    # show their best-ever rank instead of a rank against a list they've dropped
    # out of. get_athlete_active_rankings returns None when the athlete isn't
    # active, which is the signal to fall back to peak.
    world_rank = None
    world_rank_is_peak = False
    if ratings:
        active_ranks = queries.get_athlete_active_rankings(athlete_id, category=category, course=course)
        if active_ranks and active_ranks.get("world_overall"):
            world_rank = active_ranks["world_overall"]
        else:
            peak_ranks = queries.get_athlete_peak_rankings(athlete_id, category=category, course=course)
            world_rank = peak_ranks.get("world_overall") if peak_ranks else None
            world_rank_is_peak = world_rank is not None
    return JSONResponse({
        "athlete_id":     info["athlete_id"],
        "name":           info["name"],
        "gender":         info["gender"],
        "country_name":   info["country_full"],
        "country_alpha3": info["country_alpha3"],
        "year_of_birth":  info["year_of_birth"] or "",
        "overall_rating": format_rating(ratings["overall_rating"]) if ratings else None,
        "swim_rating":    int(round(ratings["swim_rating"])) if ratings and ratings.get("swim_rating") else None,
        "bike_rating":    int(round(ratings["bike_rating"])) if ratings and ratings.get("bike_rating") else None,
        "run_rating":     int(round(ratings["run_rating"]))  if ratings and ratings.get("run_rating")  else None,
        "world_rank":     world_rank,
        "world_rank_is_peak": world_rank_is_peak,
        "wins":           stats["wins"] if stats else None,
        "programs":       programs,
        "active_program": active_program,
    })


def _parse_ids(a: str):
    """Comma-separated athlete ids -> de-duplicated int list, order preserved."""
    ids = []
    for part in a.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Bad athlete id: {part!r}")
        if n not in ids:
            ids.append(n)
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Pick at least two athletes")
    if len(ids) > MAX_ATHLETES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_ATHLETES} athletes can be compared")
    return ids


@router.get("/athlete-compare/{athlete1_id}/{athlete2_id}")
def compare_pair_redirect(athlete1_id: int, athlete2_id: int, program: str = "elite-short"):
    # Legacy pairwise URL (linked from the home page and athlete pages).
    if program not in _PROGRAMS:
        program = "elite-short"
    return RedirectResponse(
        url=f"/athlete-compare?a={athlete1_id},{athlete2_id}&program={program}",
        status_code=302,
    )


@router.get("/athlete-compare/results", response_class=HTMLResponse)
def get_comparison_html(request: Request, a: str, program: str = "elite-short"):
    if program not in _PROGRAMS:
        program = "elite-short"
    course, category = _parse_program(program)
    ids = _parse_ids(a)
    # Direct navigation - redirect to the full compare page which auto-loads via JS
    if not request.headers.get("X-Partial"):
        return RedirectResponse(
            url=f"/athlete-compare?a={','.join(map(str, ids))}&program={program}",
            status_code=302,
        )

    discs = ["overall", "swim", "bike", "run", "transition"]
    h2h_discs = ["overall", "swim", "bike", "run"]

    athletes = []
    for i, athlete_id in enumerate(ids):
        info = queries.get_athlete_info(athlete_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Athlete {athlete_id} not found")
        stats   = queries.get_athlete_stats(athlete_id, category=category, course=course)
        ratings = queries.get_athlete_current_ratings(athlete_id, category=category, course=course)
        changes = queries.get_athlete_1yr_changes(athlete_id, category=category, course=course)
        athletes.append({
            "id":             info["athlete_id"],
            "name":           info["name"],
            "short_name":     info["name"].split()[-1] if len(info["name"].split()) > 1 else info["name"],
            "country_alpha3": info["country_alpha3"],
            "year_of_birth":  info["year_of_birth"],
            "color":          ATHLETE_COLORS[i],
            "stats": {
                "total_races": stats["race_starts"],
                "podiums":     stats["podiums"],
                "wins":        stats["wins"],
            },
            "ratings": {d: format_rating(ratings[f"{d}_rating"]) if ratings else 0 for d in discs},
            "changes": {d: format_1yr_rating_change(changes[f"{d}_change_1yr"]) if changes else None for d in discs},
        })

    # Stats card rows: one row per discipline rating, then career counts. Each
    # row carries per-athlete values in slot order plus the best value so the
    # template can highlight the leader(s).
    def _stat_row(label, values, deltas=None):
        present = [v for v in values if v is not None]
        best = max(present) if present else None
        return {"label": label, "vals": values, "deltas": deltas or [None] * len(values),
                "best": best if len(present) > 1 else None}

    rating_rows = [
        _stat_row(d.capitalize(), [ath["ratings"][d] for ath in athletes],
                  [ath["changes"][d] for ath in athletes])
        for d in discs
    ]
    career_rows = [
        _stat_row("Total Races", [ath["stats"]["total_races"] for ath in athletes]),
        _stat_row("Wins",        [ath["stats"]["wins"]        for ath in athletes]),
        _stat_row("Podiums",     [ath["stats"]["podiums"]     for ath in athletes]),
    ]

    # Head-to-head race list. Rows are races with >=2 of the athletes present;
    # each row has one cell per athlete (slot order) per discipline. The
    # fastest finisher among those present wins the discipline for that race.
    common = queries.get_common_races(ids, course=course, category=category)
    head_to_head = []
    disc_wins = {d: [0] * len(ids) for d in h2h_discs}
    all_present_count = 0
    for race in common:
        present = [ath["id"] in race["results"] for ath in athletes]
        n_present = sum(present)
        if n_present == len(ids):
            all_present_count += 1
        cells = {}
        for disc in h2h_discs:
            times = [race["results"][ath["id"]][f"{disc}_s"] if race["results"].get(ath["id"]) else None
                     for ath in athletes]
            finished = [t for t in times if t]
            fastest = min(finished) if finished else None
            row_cells = []
            for i, t in enumerate(times):
                if t is None:
                    row_cells.append({"formatted_str": "", "behind": "", "css_class": "h2h-absent"})
                elif t == 0:
                    row_cells.append({"formatted_str": "", "behind": "", "css_class": "h2h-dnf"})
                elif t == fastest:
                    # A tie leaves nobody with the win.
                    is_sole = finished.count(fastest) == 1
                    if is_sole:
                        disc_wins[disc][i] += 1
                    row_cells.append({"formatted_str": router_utils.format_time(t), "behind": "",
                                      "css_class": "h2h-winner" if is_sole else ""})
                else:
                    row_cells.append({"formatted_str": router_utils.format_time(t),
                                      "behind": router_utils.format_time_behind(t - fastest),
                                      "css_class": ""})
            cells[disc] = row_cells
        head_to_head.append({
            "race_id":   race["race_id"],
            "race_name": race["race_title"],
            "race_date": race["race_date"],
            "n_present": n_present,
            "all_present": n_present == len(ids),
            "positions": [
                (race["results"][ath["id"]]["position"], race["results"][ath["id"]]["status"])
                if race["results"].get(ath["id"]) else (None, None)
                for ath in athletes
            ],
            "cells": cells,
        })

    # Rating and ranking charts: one dataset per athlete, chronological.
    def _with_rank_changes(rows, col):
        """Annotate each ranking row with the change from the previous ranked race."""
        points = [r for r in rows if r[col] is not None]
        result = []
        for i, r in enumerate(points):
            prev = points[i - 1][col] if i > 0 else None
            # Positive rank_chg = improved (moved up, lower number)
            rank_chg = (prev - r[col]) if prev is not None else None
            result.append({"x": str(r["race_date"])[:10], "y": r[col],
                           "race_name": r["race_title"], "race_id": r["race_id"],
                           "rank_chg": rank_chg})
        return result

    ratings_charts  = {d: {"datasets": []} for d in discs}
    rankings_charts = {d: {"datasets": []} for d in discs}
    for ath in athletes:
        color = ath["color"]
        style = {"borderColor": color, "backgroundColor": color + "20",
                 "pointBackgroundColor": color, "borderWidth": 2, "pointRadius": 3}
        ratings_data  = queries.get_athlete_ratings_data(ath["id"], category=category, course=course)
        rankings_data = queries.get_athlete_rankings_data(ath["id"], category=category, course=course)
        for disc in discs:
            ratings_charts[disc]["datasets"].append({
                "label": ath["name"],
                "data": [
                    {"x": str(r["race_date"])[:10], "y": int(r[f"{disc}_rating"]),
                     "race_name": r["race_title"], "race_id": r["race_id"],
                     "change": r[f"{disc}_change"]}
                    for r in ratings_data
                ],
                **style,
            })
            rankings_charts[disc]["datasets"].append({
                "label": ath["name"],
                "data": _with_rank_changes(rankings_data, f"world_{disc}"),
                **style,
            })

    return templates.TemplateResponse("partials/comparison_results.html", {
        "request":          request,
        "athletes":         athletes,
        "rating_rows":      rating_rows,
        "career_rows":      career_rows,
        "head_to_head":     head_to_head,
        "all_present_count": all_present_count,
        "h2h_disc_wins":    disc_wins,
        "ratings_charts":   ratings_charts,
        "rankings_charts":  rankings_charts,
    })
