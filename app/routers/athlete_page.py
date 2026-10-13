import math
import re
from datetime import date, timedelta
from functools import lru_cache

from fastapi import HTTPException, Query, Request, APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag

from ptd_data import db, queries
from ptd_data.predictions import LOW_CONF_STARTS
from app.routers.router_utils import (
    format_time, format_time_behind, format_rating_change, format_1yr_rating_change,
)

templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
router = APIRouter()

_merge_redirects = lru_cache(maxsize=1)(db.athlete_merge_redirects)

# Palmares scoring. Every finish is worth the tier's winner value scaled by
# _POS_DECAY per place behind the winner, so all tiers sit on one scale and
# e.g. an Olympic 20th (~110) no longer outranks a world title (1000). Values
# only matter relative to the other tiers in the same stream (short / AG /
# long), since each stream is a separate palmares.
_TIER_POINTS = {
    "olympic":               1250,
    "world_champs":          1000,
    "grand_final":           1000,
    "sprint_world_champs":    900,
    "wtcs":                   800,
    "u23_world_champs":       750,
    "world_cup":              500,
    "junior_world_champs":    300,
    "continental_cup":        200,
    "french_grand_prix":      150,
    "ag_world_champs":       1000,
    "ag_continental_champs":  500,
    # Long-course tiers
    "im_world_champs":       1500,
    "im_703_world_champs":   1000,
    "t100":                   800,
    "im":                     700,
    "im_703":                 400,
    "challenge":              300,
}
_POS_DECAY = 0.88
# A finish worth fewer points than this never makes the palmares (roughly a
# top-31 at worlds, top-26 at a World Cup, top-18 at a Continental Cup).
_MIN_POINTS = 20
# Hide anything worth less than this fraction of the athlete's best result, so
# a world champion's early Continental Cup placings drop off.
_REL_THRESHOLD = 0.2

# (title, medal prefix, event name) for championship-style tiers; everything
# else reads "{label} Win" / "{label} Silver" / "{label}, 5th".
_CHAMPIONSHIP_LABELS = {
    "olympic":               ("Olympic Champion",          "Olympic",                    "Olympic Games"),
    "world_champs":          ("World Champion",            "World Championship",         "World Championships"),
    "u23_world_champs":      ("U23 World Champion",        "U23 World Championship",     "U23 World Championships"),
    "junior_world_champs":   ("Junior World Champion",     "Junior World Championship",  "Junior World Championships"),
    "sprint_world_champs":   ("Sprint World Champion",     "Sprint World Championship",  "Sprint World Championships"),
    "grand_final":           ("Grand Final Win",           "Grand Final",                "Grand Final"),
    "ag_world_champs":       ("AG World Champion",         "AG World Championship",      "AG World Championships"),
    "ag_continental_champs": ("AG Continental Champion",   "AG Continental",             "AG Continental Championships"),
    "im_world_champs":       ("Ironman World Champion",    "Ironman World Championship", "Ironman World Championships"),
    "im_703_world_champs":   ("Ironman 70.3 World Champion", "Ironman 70.3 World Championship", "Ironman 70.3 World Championships"),
}
_TIER_LABELS = {
    "wtcs":              "WTCS",
    "world_cup":         "World Cup",
    "continental_cup":   "Continental Cup",
    "french_grand_prix": "French Grand Prix",
    "im":                "Ironman",
    "t100":              "T100",
    "im_703":            "Ironman 70.3",
    "challenge":         "Challenge",
}


# Distance names for the Races table's meta line and its distance filter.
_DISTANCE_LABELS = {"sprint": "Sprint", "standard": "Standard", "relay": "Relay",
                    "middle": "70.3", "t100": "T100", "long": "Full distance"}


# --- Formatting helpers that previously lived on the Athlete object ---

def format_ranking(rank):
    return f"#{rank} all time" if rank and rank > 0 else "No Ranking"


def format_ordinal(n):
    try:
        n = int(n)
    except Exception:
        return "***"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n:,}{suffix}"


templates.env.filters["ordinal"] = format_ordinal


_GENDER_WORD = {"male": "Men", "female": "Women", "mixed": "Mixed"}

DISCS = ["overall", "swim", "bike", "run", "transition"]
DISC_LABELS = {"overall": "Overall", "swim": "Swim", "bike": "Bike", "run": "Run", "transition": "Transition"}


def _display_program(prog_name, gender=None):
    """Results-table program label. Division-tagged programs (French Grand Prix
    'Elite Men (D1)') render as "{Division} {Gender}" ("D1 Men"), matching the
    series-page tabs, while everything else shows its prog_name unchanged. The
    stored prog_name keeps "Elite" so sub_category derivation is unaffected.
    Gender falls back to the word already in the prog_name when not supplied."""
    div = queries.program_division(prog_name)
    if not div:
        return prog_name
    word = _GENDER_WORD.get(gender)
    if not word:
        word = next((w for w in ("Women", "Men", "Mixed") if w in (prog_name or "")), "")
    return f"{div} {word}".strip()


def _mtr_program(prog_name, leg_num=None):
    """Mixed-relay program label for the results/ratings tables:
    'Mixed Elite Relay' -> 'Elite MTR', 'Mixed Relay' -> 'MTR', with an
    optional leg suffix."""
    cat = prog_name.removeprefix("Mixed").removesuffix("Relay").strip()
    label = f"{cat} MTR".strip()
    if leg_num:
        label += f" · Leg {leg_num}"
    return label


def _format_position(tier, pos):
    if tier in _CHAMPIONSHIP_LABELS:
        title, medal, event = _CHAMPIONSHIP_LABELS[tier]
        if pos == 1: return title
        if pos == 2: return f"{medal} Silver"
        if pos == 3: return f"{medal} Bronze"
        return f"{event}, {format_ordinal(pos)}"
    label = _TIER_LABELS[tier]
    if pos == 1: return f"{label} Win"
    if pos == 2: return f"{label} Silver"
    if pos == 3: return f"{label} Bronze"
    return f"{label}, {format_ordinal(pos)}"


# Words a palmares tier row already says, stripped from race handles so the
# races read as places: "IM 70.3 Oceanside 26" -> "Oceanside 26".
_HANDLE_NOISE = re.compile(
    r"\b(?:IM 70\.3|IM|Challenge|T100|AG|Junior|U23|WTCS|WC|BG|CC|FGP|Olympics|Grand Final"
    r"|World Champs|World Championships?|Conti Champs)\b|\s-\s|\s\d{2}$")


def _build_palmares_tiers(notable_raw):
    """Palmares as one row per tier with gold / silver / bronze counts.

    Each tier is scored by its best finish on the shared _TIER_POINTS scale.
    Tiers below _MIN_POINTS or below _REL_THRESHOLD of the athlete's best
    tier are dropped, and the rest are listed best first. A tier with a
    podium lists its podium races (an Olympic champion's 12th at the next
    Games is noise); one without lists its best placing. Races get short
    names, since the row already names the series: what is left of the
    handle once the series words go, or the event venue when nothing is
    left ("IM 70.3 World Championship 26" -> "Nice 26").
    """
    by_tier = {}
    for r in notable_raw:
        by_tier.setdefault(r["tier"], []).append(r)

    rows = []
    for tier, races in by_tier.items():
        best = min(r["position"] for r in races)
        points = _TIER_POINTS[tier] * _POS_DECAY ** (best - 1)
        if points < _MIN_POINTS:
            continue
        shown = [r for r in races if r["position"] <= 3] or [r for r in races if r["position"] == best]
        shown.sort(key=lambda r: (r["position"], -r["race_date"].toordinal()))
        rows.append({
            "points": points,
            "tier":   tier,
            "name":   _CHAMPIONSHIP_LABELS[tier][2] if tier in _CHAMPIONSHIP_LABELS else _TIER_LABELS[tier],
            "medals": [sum(r["position"] == p for r in races) for p in (1, 2, 3)] if best <= 3 else None,
            "best":   best,
            "races":  [{"race_id": r["race_id"], "position": r["position"],
                        "handle": r["race_handle"], "year": r["race_date"].year,
                        "name": f'{" ".join(_HANDLE_NOISE.sub(" ", r["race_handle"]).split()) or r["venue"].split(",")[0]} {r["race_date"]:%y}'}
                       for r in shown],
        })
    if not rows:
        return []
    top = max(r["points"] for r in rows)
    rows = [r for r in rows if r["points"] >= top * _REL_THRESHOLD]
    rows.sort(key=lambda r: (-r["points"], -len(r["races"])))
    return rows


def _build_ratings_chart(ratings_data):
    """Build per-discipline rating history data for the athlete ratings chart."""
    disciplines = ["overall", "swim", "bike", "run", "transition"]
    result = {}
    for disc in disciplines:
        prev_wr = None
        points = []
        for r in ratings_data:
            wr = r.get(f"world_{disc}")
            # World rank change: positive = moved up (lower number is better)
            wr_chg = (prev_wr - wr) if (wr is not None and prev_wr is not None) else None
            prev_wr = wr
            points.append({
                "x":          str(r["race_date"])[:10],
                "y":          round(r[f"{disc}_rating"]),  # round, as the tables do
                "change":     round(r[f"{disc}_change"]) if r[f"{disc}_change"] is not None else None,
                "race_name":  r["race_title"],
                "race_id":    r["race_id"],
                "status":     r.get("status"),
                "time_s":     r.get(f"{disc}_s"),   # None for transition
                "diff_s":     r.get(f"{disc}_diff"), # None for transition
                "t1_s":       r.get("t1_s"),
                "t2_s":       r.get("t2_s"),
                "t1_diff":    r.get("t1_diff"),
                "t2_diff":    r.get("t2_diff"),
                "world_rank": wr,
                "world_rank_chg": wr_chg,
            })
        result[disc] = points
    return result


def _build_pct_behind_chart(times_data):
    """Build flat per-discipline % behind leader data for the new ratings-style chart."""
    result = {}
    for disc in ["overall", "swim", "bike", "run"]:
        result[disc] = [
            {
                "x":         str(r["race_date"])[:10],
                "y":         round(r[f"{disc}_pct_behind"] * 100, 2),
                "race_name": r["race_title"],
                "race_id":   r["race_id"],
            }
            for r in times_data
            if r[f"{disc}_pct_behind"] is not None
        ]
    return result


def _build_rankings_charts(rankings_data):
    """Build per-discipline ranking history for world and national charts."""
    world    = {}
    national = {}
    for disc in ["overall", "swim", "bike", "run", "transition"]:
        prev_world = prev_nat = None
        world_pts  = []
        nat_pts    = []
        for r in rankings_data:
            wr  = r.get(f"world_{disc}")
            nat = r.get(f"national_{disc}")
            wr_chg  = (prev_world - wr)  if (wr  is not None and prev_world is not None) else None
            nat_chg = (prev_nat   - nat) if (nat is not None and prev_nat   is not None) else None
            prev_world = wr
            prev_nat   = nat
            base = {
                "x":        str(r["race_date"])[:10],
                "race_name": r["race_title"],
                "race_id":   r["race_id"],
                "status":    r.get("status"),
                "time_s":    r.get(f"{disc}_s"),   # None for transition
                "diff_s":    r.get(f"{disc}_diff"), # None for transition
                "t1_s":      r.get("t1_s"),
                "t2_s":      r.get("t2_s"),
                "t1_diff":   r.get("t1_diff"),
                "t2_diff":   r.get("t2_diff"),
            }
            if wr  is not None:
                world_pts.append({**base, "y": wr,  "rank_chg": wr_chg})
            if nat is not None:
                nat_pts.append(  {**base, "y": nat, "rank_chg": nat_chg})
        world[disc]    = world_pts
        national[disc] = nat_pts
    return world, national



@router.get("/athlete/{athlete_id}", response_class=HTMLResponse)
def get_athlete(request: Request, athlete_id: int,
                      category: str = Query('elite'),
                      course:   str | None = Query(None)):
    info = queries.get_athlete_info(athlete_id)
    if not info:
        # Manually merged athletes: 301 the retired ID to the survivor so
        # indexed URLs and backlinks follow the merge instead of 404ing.
        merged_into = _merge_redirects().get(athlete_id)
        if merged_into:
            return RedirectResponse(f"/athlete/{merged_into}", status_code=301)
        raise HTTPException(status_code=404, detail=f"Athlete {athlete_id} not found")

    # Resolve course (short vs long).
    # - Explicit `course=` from the user wins, with a fallback if the athlete
    #   has no data for that course.
    # - Otherwise pick the athlete's most recently active course: whichever has
    #   a race within 18 months wins; ties broken by most-recent-race date.
    #   Falls through to the first available course or 'short' if no data.
    available_courses = queries.get_athlete_courses(athlete_id)
    if course is not None:
        if available_courses and course not in available_courses:
            course = available_courses[0]
        elif not available_courses:
            course = 'short'
    else:
        last_per = queries.get_athlete_last_race_per_course(athlete_id)
        cutoff = date.today() - timedelta(days=int(18 * 30.44))
        active = {c: d for c, d in last_per.items() if d and d >= cutoff}
        candidates = active or last_per
        if candidates:
            course = max(candidates, key=lambda c: candidates[c])
        elif available_courses:
            course = available_courses[0]
        else:
            course = 'short'

    # Detect available categories *within the chosen course* and resolve the requested one
    available_categories = queries.get_athlete_categories(athlete_id, course=course)
    has_ratings = bool(available_categories)
    if has_ratings:
        if category not in available_categories:
            category = 'elite' if 'elite' in available_categories else available_categories[0]
    else:
        category = 'elite'  # default for race history query; no ratings will be shown

    current  = queries.get_athlete_current_ratings(athlete_id, category, course=course) if has_ratings else None
    changes  = queries.get_athlete_1yr_changes(athlete_id, category, course=course)     if has_ratings else None
    peaks    = queries.get_athlete_peak_ratings(athlete_id, category, course=course)    if has_ratings else None
    stats    = queries.get_athlete_stats(athlete_id, category, course=course)
    notable_raw        = queries.get_athlete_notable_results(athlete_id)
    ag_notable_raw     = queries.get_athlete_ag_notable_results(athlete_id)
    long_notable_raw   = queries.get_athlete_long_course_notable_results(athlete_id)
    race_hist    = queries.get_athlete_race_history(athlete_id, category, course=course)
    # Mixed relay legs appear in the short-course elite history alongside
    # individual races (they update the same ratings, damped).
    if category == 'elite' and course == 'short':
        relay_hist = queries.get_athlete_relay_history(athlete_id)
        for r in relay_hist:
            r["is_relay"] = True
            r["distance"] = "relay"
        if relay_hist:
            race_hist = sorted(race_hist + relay_hist,
                               key=lambda r: (r["race_date"], r["race_id"]), reverse=True)
    rating_hist  = queries.get_athlete_rating_history(athlete_id, category, course=course) if has_ratings else []
    times_data    = queries.get_athlete_times_data(athlete_id, category, course=course)    if has_ratings else []
    ratings_data  = queries.get_athlete_ratings_data(athlete_id, category, course=course)  if has_ratings else []
    rankings_data = queries.get_athlete_rankings_data(athlete_id, category, course=course) if has_ratings else []

    # --- current ratings card ---
    current_ratings = {}
    if current:
        for disc in ["overall", "swim", "bike", "run", "transition"]:
            current_ratings[f"{disc}_rating"] = round(current[f"{disc}_rating"])

    # --- current rankings card (active athletes only) ---
    def _make_ranking(rank):
        if not rank or rank <= 0:
            return None
        n = int(rank)
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return {"n": n, "suffix": suffix}

    # Compute active using category-filtered race_hist (already fetched above).
    # stats["last_race_date"] is category-agnostic so would incorrectly show rankings
    # for e.g. a retired elite who still races AG.
    _cat_last = race_hist[0]["race_date"] if race_hist else None
    _active   = bool(has_ratings and _cat_last and _cat_last >= (date.today() - timedelta(days=int(18 * 30.44))))

    # A current career ranks among athletes active in the last 18 months; a
    # finished one shows the best world rank it held in that pool.
    active_ranks = queries.get_athlete_active_rankings(athlete_id, category, course=course) if _active else None
    peak_ranks   = queries.get_athlete_peak_rankings(athlete_id, category, course=course) if has_ratings and not _active else None
    current_rankings = {f"world_{d}": _make_ranking(active_ranks[f"world_{d}"]) for d in DISCS} if active_ranks else {}

    # --- current form card ---
    # Equivalent race-day splits from the form model (ptd_data/form.py): the
    # athlete's blended form mapped through the typical recent split for each
    # distance. Elite only, and only disciplines where the athlete is both
    # established (>= FORM_MIN_STARTS observed splits) and current (raced the
    # course within 18 months) - e.g. Blummenfelt gets long-course form but
    # his dormant short-course profile shows none.
    FORM_MIN_STARTS = 5
    current_form = None
    if category == 'elite':
        form = queries.get_athlete_form(athlete_id, course)
        refs = queries.get_form_reference_times(course)
        form_cutoff = date.today() - timedelta(days=int(18 * 30.44))
        if course == 'short':
            form_cols = [('Sprint', 'sprint'), ('Standard', 'standard')]
            form_discs = ('swim', 'run')
            legs = {('sprint', 'swim'): '750m', ('standard', 'swim'): '1500m',
                    ('sprint', 'run'): '5km', ('standard', 'run'): '10km'}
        else:
            form_cols = [('70.3', 'middle'), ('140.6', 'long')]
            form_discs = ('swim', 'bike', 'run')
            legs = {('middle', 'swim'): '1.9km', ('long', 'swim'): '3.8km',
                    ('middle', 'bike'): '90km', ('long', 'bike'): '180km',
                    ('middle', 'run'): '21.1km', ('long', 'run'): '42.2km'}
        form_rows = []
        for disc in form_discs:
            f = form.get(disc)
            if not f or f['n_obs'] < FORM_MIN_STARTS or f['last_race_date'] < form_cutoff:
                continue
            cells = []
            for _, dist in form_cols:
                ref = refs.get((info['gender'], dist, disc))
                cells.append({
                    'leg':  legs[(dist, disc)],
                    'time': format_time(round(ref * math.exp(f['form_rel']))) if ref else '-',
                })
            form_rows.append({'label': disc.capitalize(), 'cells': cells})
        if form_rows:
            current_form = {'cols': [label for label, _ in form_cols], 'rows': form_rows}


    # --- Ratings table: one row per discipline ---
    # World rank leads because it compares across disciplines, which raw
    # ratings don't. A finished career shows its best world rank instead,
    # with no national rank or 1-year change.
    # The 1-year sparkline starts at the same race the 1-year change does
    # (the latest race at least 365 days old), so line and number agree.
    # Points are normalised into a 100x28 viewBox.
    sparks = {}
    if has_ratings and changes and _active:
        cutoff = date.today() - timedelta(days=365)
        window = []
        for r in rating_hist:            # newest first
            window.append(r)
            if r["race_date"] <= cutoff:
                break
        if len(window) >= 2:
            window.reverse()
            W, H, PAD = 100.0, 28.0, 3.0
            for disc in DISCS:
                vals = [r[f"{disc}_rating"] for r in window]
                lo, span = min(vals), (max(vals) - min(vals)) or 1.0
                sparks[disc] = " ".join(f"{i / (len(vals) - 1) * W:.1f},{PAD + (1 - (v - lo) / span) * (H - 2 * PAD):.1f}"
                                        for i, v in enumerate(vals))
    ratings_rows = []
    if has_ratings:
        for disc in DISCS:
            rating = current_ratings[f"{disc}_rating"]
            peak = round(peaks[f"max_{disc}"])
            ranks = active_ranks or peak_ranks or {}
            ratings_rows.append({
                "label":        DISC_LABELS[disc],
                "rating":       rating,
                "world":        ranks.get(f"world_{disc}"),
                "national":     active_ranks[f"national_{disc}"] if active_ranks else None,
                "change":       format_1yr_rating_change(changes[f"{disc}_change_1yr"]) if changes and _active else None,
                "spark":        sparks.get(disc),
                "peak":         peak,
                "at_peak":      peak == rating,
                "peak_race":    peaks[f"max_{disc}_race"],
                "peak_race_id": peaks[f"max_{disc}_race_id"],
                "peak_date":    peaks[f"max_{disc}_date"],
            })

    # --- athlete dict: merge info + stats + computed fields expected by template ---
    race_starts = stats["race_starts"]
    wins        = stats["wins"]
    podiums     = stats["podiums"]
    # The person header's Retired chip and greyed photo describe the athlete,
    # not one career: anyone who raced anything in the last 18 months is
    # active. Each career card says when that career last raced. No results
    # yet (only entries) means no chip either.
    last_any = max(queries.get_athlete_last_race_per_course(athlete_id).values(), default=None)
    active = last_any is None or last_any >= date.today() - timedelta(days=int(18 * 30.44))
    no_relays = {"starts": 0, "wins": 0, "seconds": 0, "thirds": 0, "podiums": 0, "dnfs": 0}
    relay = queries.get_athlete_relay_stats(athlete_id) if category == 'elite' and course == 'short' else no_relays
    athlete_dict = {
        **info,
        "race_starts":   race_starts,
        "wins":          wins,
        "podiums":       podiums,
        "win_count":     wins + relay["wins"],
        "podium_count":  podiums + relay["podiums"],
        "win_pct":       wins   / max(race_starts, 1),
        "podium_pct":    podiums / max(race_starts, 1),
        "active":        active,
        "is_low_confidence": race_starts < LOW_CONF_STARTS,
        "dnfs":          stats["dnfs"] + relay["dnfs"],
        "seconds":       stats["seconds"] + relay["seconds"],
        # Relays count on screen, scored on the team's result (the Races table
        # lists them); race_starts stays individual for the provisional gate.
        "relay_starts":  relay["starts"],
        "thirds":        stats["thirds"] + relay["thirds"],
        "first_year":    stats["first_race_date"].year if stats["first_race_date"] else None,
        "last_year":     stats["last_race_date"].year if stats["last_race_date"] else None,
    }

    # --- crawlable intro sentence ---
    # Athlete pages are otherwise near-identical tables; a unique line of real
    # prose per athlete gives search engines text to match name queries against.
    # Phrased as clauses rather than sentences to stay inside the ~155 characters
    # Google shows, and with no pronouns: the gender column is the race category
    # the athlete competed in, which is not a claim about the person.
    tier_label = "age-group" if category == "ag" else "professional"
    course_label = "long-course" if course == "long" else "short-course"
    from_str = f" from {info['country_full']}" if info.get("country_full") else ""
    seo_intro = f"{info['name']}, {tier_label} {course_label} triathlete{from_str}."
    if race_starts:
        first_year = min(r["race_date"].year for r in race_hist) if race_hist else None
        since = "" if not first_year else (f" in {first_year}" if race_starts == 1 else f" since {first_year}")
        seo_intro += (f" {race_starts} race start{'s' if race_starts != 1 else ''}{since},"
                      f" {wins} win{'s' if wins != 1 else ''},"
                      f" {podiums} podium{'s' if podiums != 1 else ''}.")
    world_rank = current_rankings.get("world_overall")
    if world_rank:
        seo_intro += f" Ranked {world_rank['n']}{world_rank['suffix']} in the world."

    # --- Palmares: one per career (short-course elite, long-course elite, AG) ---
    palmares_by_key = {'elite-short': _build_palmares_tiers(notable_raw),
                       'elite-long':  _build_palmares_tiers(long_notable_raw),
                       'ag':          _build_palmares_tiers(ag_notable_raw)}

    # --- race history table ---
    # Fetch percentile thresholds once for this athlete's gender (cached per process).
    _gender = next((r["gender"] for r in race_hist if r.get("gender") in ("male", "female")), "male")
    _thresholds = queries.get_race_standard_thresholds(_gender, course=course)

    def _std_class(std, disc="overall"):
        # No standard (relay legs, unrated rollups) means no pill, not Beginner.
        if std is None:
            return None
        t = _thresholds[disc]
        if std >= t["p95"]: return "expert"
        if std >= t["p85"]: return "advanced"
        if std >= t["p60"]: return "intermediate"
        if std >= t["p30"]: return "novice"
        return "beginner"

    def _fmt_race(r):
        return {
            "race_id":        r["race_id"],
            "event_id":       r["event_id"],
            "is_multi_stage": bool(r.get("is_multi_stage")),
            "is_relay":       bool(r.get("is_relay")),
            "leg_num":        r.get("leg_num"),
            "race_title":     r["race_title"],
            "race_date":      r["race_date"],
            "distance":       _DISTANCE_LABELS[r["distance"]],
            "program":        (_mtr_program(r["program"], r.get("leg_num")) if r.get("is_relay")
                               else _display_program(r["program"], r.get("gender"))),
            "position":       r["position"],
            "status":         r["status"],
            # Relays have no race_rankings standard; suppress the pill rather
            # than defaulting to "beginner".
            "standard_class": None if r.get("is_relay") else _std_class(r.get("overall_std")),
            "overall":        format_time(r["overall_s"]),
            "overall_behind": format_time_behind(r["overall_behind_s"]),
            "swim":           format_time(r["swim_s"]),
            "swim_behind":    format_time_behind(r["swim_behind_s"]),
            "swim_fastest":   r["swim_behind_s"] == 0 and (r["swim_s"] or 0) > 0,
            "t1":             format_time(r["t1_s"]),
            "t1_behind":      format_time_behind(r["t1_behind_s"]),
            "t1_fastest":     r["t1_behind_s"] == 0 and (r["t1_s"] or 0) > 0,
            "bike":           format_time(r["bike_s"]),
            "bike_behind":    format_time_behind(r["bike_behind_s"]),
            "bike_fastest":   r["bike_behind_s"] == 0 and (r["bike_s"] or 0) > 0,
            "t2":             format_time(r["t2_s"]),
            "t2_behind":      format_time_behind(r["t2_behind_s"]),
            "t2_fastest":     r["t2_behind_s"] == 0 and (r["t2_s"] or 0) > 0,
            "run":            format_time(r["run_s"]),
            "run_behind":     format_time_behind(r["run_behind_s"]),
            "run_fastest":    r["run_behind_s"] == 0 and (r["run_s"] or 0) > 0,
        }

    # Group ignored sub-races under their parent row.
    # Build sub-race map keyed by parent_race_id, then stitch together.
    _sub_map: dict = {}
    _main: list = []
    for r in race_hist:
        if r.get("is_ignored") and r.get("parent_race_id"):
            _sub_map.setdefault(r["parent_race_id"], []).append(_fmt_race(r))
        else:
            _main.append(r)

    # Patch standard_class on sub-races: ignored races have no ratings rows so
    # overall_std is NULL from the main query; fetch via one bulk query.
    _sub_ids = [sub["race_id"] for subs in _sub_map.values() for sub in subs]
    _sub_standards = queries.get_race_standards_bulk(_sub_ids) if _sub_ids else {}
    for subs in _sub_map.values():
        for sub in subs:
            std = _sub_standards.get(sub["race_id"], {}).get("overall")
            sub["standard_class"] = _std_class(std)

    race_history = []
    for r in _main:
        entry = _fmt_race(r)
        subs = list(reversed(_sub_map.get(r["race_id"], [])))
        # A sub-race is a true stage (semifinal/final/heat/...) only when its
        # parent is a multi-stage rollup row. Subset sub-events bundled in
        # under a parent (e.g. national champs results extracted from a
        # continental cup, or AG results pulled from a combined elite+AG
        # field) shouldn't be numbered "Stage N".
        stage_counter = 0
        parent_is_multi_stage = bool(entry.get("is_multi_stage"))
        for sub in subs:
            is_stage = parent_is_multi_stage
            sub["is_stage"] = is_stage
            if is_stage:
                stage_counter += 1
                sub["stage_num"] = stage_counter
        entry["sub_races"] = subs
        race_history.append(entry)

    # --- Races table: each row's rating and stored prediction ---
    # One table with Times, Ratings and Predictions views over the same rows,
    # so each race carries its post-race ratings (rated races only) and the
    # prediction stored before it (when there was one).
    ratings_by_race = {r["race_id"]: r for r in rating_hist}
    preds = queries.get_athlete_race_predictions(athlete_id)
    rows_with_subs = race_history + [sub for e in race_history for sub in e["sub_races"]]
    raw_overall = {r["race_id"]: r["overall_s"] for r in race_hist}
    for e in rows_with_subs:
        rt = ratings_by_race.get(e["race_id"])
        e["rating"] = {
            disc: {"value": round(rt[f"{disc}_rating"]), "change": format_rating_change(rt[f"{disc}_change"])}
            for disc in DISCS
        } if rt else None
        p = preds.get(e["race_id"])
        e["pred"] = None
        if p and p["predicted_position"]:
            actual_s = raw_overall.get(e["race_id"])
            gap = actual_s - p["overall_s"] if actual_s and p["overall_s"] else None
            e["pred"] = {
                "pos":    p["predicted_position"],
                "time":   format_time(p["overall_s"]) if p["overall_s"] else None,
                # Places gained on the prediction: positive beat it.
                "places": p["predicted_position"] - e["position"] if e["position"] and e["status"] == "Finished" else None,
                "gap":    (("-" if gap < 0 else "+") + format_time(abs(round(gap)))) if gap else None,
                "gap_s":  gap,
                "win_pct": p["win_pct"],
                "low_conf": p["is_low_confidence"],
            }

    # --- upcoming races with predictions ---
    upcoming_raw = queries.get_athlete_upcoming_races(athlete_id)
    upcoming_races = []
    if upcoming_raw:
        # Grade each race on its own course, as the race page does: the field is
        # scored on ratings from the race's course (short-course ratings
        # understate a Kona field), and the thresholds come from that course's
        # bucket, with AG races in their own bucket.
        _upcoming_ids = [r['race_id'] for r in upcoming_raw]
        _distances = {rid: queries.get_upcoming_race_distance_type(rid) for rid in _upcoming_ids}
        _rating_course = {rid: queries.course_for_distance(d) or 'short' for rid, d in _distances.items()}
        _standards_by_race = {}
        for c in set(_rating_course.values()):
            _standards_by_race.update(queries.get_upcoming_race_standards_bulk(
                [rid for rid in _upcoming_ids if _rating_course[rid] == c], course=c))
        for race in upcoming_raw:
            # Standard pill classification
            std_class = None
            standards = _standards_by_race.get(race['race_id'], {})
            if standards and standards.get('overall'):
                bucket = 'ag' if race['category'] == 'ag' else _rating_course[race['race_id']]
                t = queries.get_race_standard_thresholds(race['gender'], course=bucket)['overall']
                v = standards['overall']
                if   v >= t['p95']: std_class = 'expert'
                elif v >= t['p85']: std_class = 'advanced'
                elif v >= t['p60']: std_class = 'intermediate'
                elif v >= t['p30']: std_class = 'novice'
                else:               std_class = 'beginner'

            # Predictions are precomputed at build time and shared with the
            # race page (ptd_data/predictions.py), so the two always agree.
            pred_pos, win_pct, podium_pct, splits, behinds = None, None, None, {}, {}
            stored = queries.get_race_predictions(race['race_id'])
            mine   = next((r for r in stored if r['athlete_id'] == athlete_id), None)
            if mine:
                pred_pos = mine['predicted_position']
                win_pct  = mine['win_pct']
                podium_pct = mine['podium_pct']
                for disc in ['overall', 'swim', 'bike', 'run']:
                    raw = mine[f'{disc}_s']
                    if not raw:
                        continue
                    leader = min(r[f'{disc}_s'] for r in stored if r[f'{disc}_s'])
                    splits[disc]  = format_time(raw)
                    diff = raw - leader
                    behinds[disc] = 'fastest' if diff == 0 else format_time_behind(diff)

            upcoming_races.append({
                'race_id':    race['race_id'],
                'event_name': race['event_name'],
                'race_handle': race['race_handle'] or race['event_name'],
                'event_id':   race['event_id'],
                'prog_name':  race['prog_name'],
                'race_date':  race['race_date'],
                'country':    race['country'],
                'pred_pos':   pred_pos,
                'win_pct':    win_pct,
                'podium_pct': podium_pct,
                'pred_overall':        splits.get('overall'),
                'pred_overall_behind': behinds.get('overall'),
                'pred_swim':           splits.get('swim'),
                'pred_swim_behind':    behinds.get('swim'),
                'pred_bike':           splits.get('bike'),
                'pred_bike_behind':    behinds.get('bike'),
                'pred_run':            splits.get('run'),
                'pred_run_behind':     behinds.get('run'),
                'has_pred':     bool(splits),
                'std_class':    std_class,
            })

    # --- charts ---
    pct_behind      = _build_pct_behind_chart(times_data) if has_ratings else None
    ratings_chart   = _build_ratings_chart(ratings_data)  if has_ratings else None
    world_rankings_charts, national_rankings_charts = (
        _build_rankings_charts(rankings_data) if has_ratings else ({}, {})
    )

    # --- careers: elite-short | elite-long | ag ----------------------------
    # The page has two layers: the person header (never swapped) and one
    # career at a time below the career cards. A career is a (course,
    # category) the athlete has ratings in; AG lives in whichever course has
    # AG results. Each card names the career's headline result and its world
    # rank, so the careers not on screen are still visible.
    cutoff_active = date.today() - timedelta(days=int(18 * 30.44))

    def _headline(key, c, cat):
        # The top Palmares tier's best finish, with its year when it is a
        # single race; otherwise the career's best podium. Placings outside
        # the podium are not worth a headline, so those cards get none.
        top = palmares_by_key[key][:1]
        if top and top[0]["best"] <= 3:
            t = top[0]
            races = [r for r in t["races"] if r["position"] == t["best"]]
            desc = _format_position(t["tier"], t["best"])
            if len(races) > 1:                                  # "7 x WTCS Wins"
                return f'{len(races)} x {desc}{"s" if desc.endswith("Win") else ""}'
            return f'{desc} {races[0]["year"]}'                 # "Olympic Champion 2021"
        best_finish = queries.get_athlete_best_finish(athlete_id, cat, course=c)
        if best_finish and best_finish["position"] <= 3:
            return f'Best: {format_ordinal(best_finish["position"])}, {best_finish["race_handle"]}'
        return None

    def _headline_pos(key, c, cat):
        # Finishing place behind the headline, for its medal dot.
        top = palmares_by_key[key][:1]
        if top and top[0]["best"] <= 3:
            return top[0]["best"]
        best_finish = queries.get_athlete_best_finish(athlete_id, cat, course=c)
        return best_finish["position"] if best_finish else None

    def _career(c, cat, label, key):
        st = queries.get_athlete_stats(athlete_id, cat, course=c)
        if not st["race_starts"]:
            return None
        rl = queries.get_athlete_relay_stats(athlete_id) if key == 'elite-short' else no_relays
        world = "AG world" if cat == 'ag' else "World"
        last = st["last_race_date"]
        current = last >= cutoff_active
        ranks = (queries.get_athlete_active_rankings if current else queries.get_athlete_peak_rankings)(athlete_id, cat, course=c)
        rank = int(ranks["world_overall"]) if ranks and ranks.get("world_overall") else None
        y0, y1 = st["first_race_date"].year, last.year
        return {
            "key":       key,
            "label":     label,
            "course":    c,
            "category":  cat,
            "headline":  _headline(key, c, cat),
            "span":      str(y0) if y0 == y1 else f"{y0}-{y1}",
            "starts":    st["race_starts"] + rl["starts"],
            "wins":      st["wins"] + rl["wins"],
            "podiums":   st["podiums"] + rl["podiums"],
            "rank":      rank,
            "rank_label": world if current else f'Best {world.lower()}',
            "medal":     _headline_pos(key, c, cat),
            "current":   current,
            "last":      last,
        }

    careers = []
    for c, lbl in (('short', 'Short course'), ('long', 'Long course')):
        if c in available_courses and 'elite' in queries.get_athlete_categories(athlete_id, course=c):
            careers.append(_career(c, 'elite', lbl, f'elite-{c}'))
    ag_course = next((c for c in (course, 'short', 'long')
                      if c in available_courses and 'ag' in queries.get_athlete_categories(athlete_id, course=c)), None)
    if ag_course:
        careers.append(_career(ag_course, 'ag', 'Age group', 'ag'))
    careers = sorted([cr for cr in careers if cr], key=lambda cr: cr["last"], reverse=True)
    active_key = 'ag' if category == 'ag' else f'elite-{course}'


    # --- Versus prediction: places gained on the prediction, race by race ---
    # Individual races with a confident stored prediction (relay legs and
    # low-confidence predictions left out). Shown from 5 such finishes.
    vp_rows = [e for e in race_history if e["pred"] and not e["pred"]["low_conf"] and not e["is_relay"]]
    vp_fin = [e for e in vp_rows if e["status"] == "Finished" and e["position"]]
    vs_prediction = None
    if len(vp_fin) >= 5:
        change = lambda e: e["rating"]["overall"]["change"] if e["rating"] else None
        by_gain = sorted(vp_fin, key=lambda e: e["pred"]["pos"] - e["position"])
        pred_wins = [e for e in vp_fin if e["pred"]["pos"] == 1]
        wins = [e for e in vp_fin if e["position"] == 1]
        swing = lambda e: {"race": e["race_title"], "race_id": e["race_id"],
                           "pred": e["pred"]["pos"], "pos": e["position"], "change": change(e)}
        point = lambda e: {"x": str(e["race_date"]), "race": e["race_title"], "race_id": e["race_id"],
                           "date": e["race_date"].strftime("%d %b %Y"), "pred": e["pred"]["pos"],
                           "win_pct": e["pred"]["win_pct"],
                           "chg": round(change(e)["raw"]) if change(e) and change(e)["raw"] is not None else None}
        vs_prediction = {
            "points":     [{**point(e), "y": e["pred"]["pos"] - e["position"], "pos": e["position"]} for e in vp_fin],
            "dnf":        [{**point(e), "status": e["status"]} for e in vp_rows if e not in vp_fin],
            "finished":   len(vp_fin),
            "beat":       sum(e["position"] < e["pred"]["pos"] for e in vp_fin),
            "matched":    sum(e["position"] == e["pred"]["pos"] for e in vp_fin),
            "missed":     sum(e["position"] > e["pred"]["pos"] for e in vp_fin),
            "dnf_count":  len(vp_rows) - len(vp_fin),
            "starts":     len(vp_rows),
            "pred_wins":  len(pred_wins),
            "pred_wins_won": sum(e["position"] == 1 for e in pred_wins),
            "wins":       len(wins),
            # The model's expected wins: the pre-race win chances added up.
            "expected_wins": sum(e["pred"]["win_pct"] or 0 for e in vp_fin),
            "wins_change": format_rating_change(sum(change(e)["raw"] or 0 for e in wins if change(e))) if wins else None,
            "best":       swing(by_gain[-1]),
            "worst":      swing(by_gain[0]),
        }

    # --- Head-to-head: record plus the median gap per leg in shared finishes ---
    rivals = queries.get_athlete_rivals(athlete_id, category, course, limit=5) if has_ratings else []
    gaps = queries.get_rival_leg_gaps(athlete_id, [r["athlete_id"] for r in rivals], category, course)
    for r in rivals:
        r["legs"] = []
        for disc in ("swim", "bike", "run"):
            g = gaps.get(r["athlete_id"], {}).get(disc)
            if not g:
                r["legs"].append({"label": disc.capitalize(), "text": "-", "word": "", "cls": ""})
                continue
            v = round(g["med_s"])
            text = f'{abs(v)}s' if abs(v) < 60 else format_time(abs(v)).lstrip("0").lstrip(":")
            r["legs"].append({
                "label": disc.capitalize(),
                "text":  text if v else "Level",
                # Negative is the athlete faster.
                "word":  "faster" if v < 0 else "slower" if v > 0 else "",
                "cls":   "ahead" if v < 0 else "behind" if v > 0 else "",
                "title": f'Faster in {g["faster"]} of {g["n"]} shared races',
            })

    return templates.TemplateResponse("athlete.html", {
        "request":        request,
        "active_page":    "athletes",
        "noindex":        not queries.athlete_is_indexable(athlete_id),
        "seo_intro":      seo_intro,
        "athlete":        athlete_dict,
        "has_ratings":          has_ratings,
        "show_charts":          has_ratings and race_starts > 1,
        "is_active_athlete":    _active,
        "low_conf_starts":      LOW_CONF_STARTS,
        "category":             category,
        "course":               course,
        "available_courses":    available_courses,
        "careers":              careers,
        "active_key":           active_key,
        "has_elite":            'elite' in available_categories,
        "has_ag":               'ag' in available_categories,
        "palmares":            palmares_by_key[active_key],
        "current_form":        current_form,
        "current_ratings":     current_ratings,
        "ratings_rows":        ratings_rows,
        # Today's live ranks (the Ratings table's), so the rank chart's line
        # ends where the table does even when the pool has changed since the
        # last race. None for a career not ranked now.
        "ranks_now":           {kind: {d: active_ranks[f"{kind}_{d}"] for d in DISCS} for kind in ("world", "national")}
                               if active_ranks else None,
        "ranked_now":          active_ranks is not None,
        "doping_ban":          queries.get_athlete_doping_ban(athlete_id),
        "nationality_history": queries.get_athlete_nationality_history(athlete_id),
        "upcoming_races":      upcoming_races,
        "rivals":              rivals,
        "race_history":        race_history,
        "has_preds":           any(e["pred"] for e in race_history),
        "vs_prediction":       vs_prediction,
        "ratings_chart":           ratings_chart,
        "pct_behind_chart":        pct_behind,
        "world_rankings_chart":    world_rankings_charts,
        "national_rankings_chart": national_rankings_charts,
    })
