"""Share cards: build template contexts for a race / athlete-in-race and
render a design to PNG.

Designs are Jinja templates in app/share/templates/. Each extends _base.html,
which handles size, mode (solid / photo / transparent), ink (light / dark
text) and the PTD footer.
"""
from __future__ import annotations

import base64
import datetime as dt
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from app.routers.router_utils import format_time, format_time_behind
from config import RUNTIME_ATHLETE_IMAGES_DIR, STATIC_BASE_URL
from ptd_data import queries

ROOT       = Path(__file__).resolve().parents[2]
TPL_DIR    = Path(__file__).parent / "templates"
STATIC_URI = (ROOT / "static").as_uri()

STORY    = (1080, 1920)
PORTRAIT = (1080, 1350)

# design -> (template, size, subject, label). Race-level first, then individual.
DESIGNS = {
    "r1_podium":       ("r1_podium.html",       STORY,    "race",    "Podium"),
    "r2_top10":        ("r2_top10.html",        PORTRAIT, "race",    "Top ten"),
    "r2b_top10_dense": ("r2b_top10_dense.html", PORTRAIT, "race",    "Top ten with splits"),
    "r3_fastest_legs": ("r3_fastest_legs.html", PORTRAIT, "race",    "Fastest splits"),
    "p1_result":       ("p1_result.html",       STORY,    "athlete", "Result"),
    "p2_splits_bar":   ("p2_splits_bar.html",   STORY,    "athlete", "Splits"),
    "p4_rating":       ("p4_rating.html",       STORY,    "athlete", "Rating"),
    "p5_milestones":   ("p5_milestones.html",   STORY,    "athlete", "Milestones"),
}
MODES = ("solid", "photo", "transparent")
INKS  = ("light", "dark")

_env = Environment(loader=FileSystemLoader(str(TPL_DIR)), autoescape=select_autoescape(["html"]))
_env.globals["STATIC_URI"] = STATIC_URI
# flag()/face() as globals so child-template blocks can call them.
_env.globals.update({k: v for k, v in vars(_env.get_template("_macros.html").module).items() if not k.startswith("_")})


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def face_uri(athlete_id: int) -> str | None:
    """Local 512px face as a data URI; in prod the images live on the CDN."""
    p = RUNTIME_ATHLETE_IMAGES_DIR / "512" / f"{athlete_id}.webp"
    if p.exists():
        return "data:image/webp;base64," + base64.b64encode(p.read_bytes()).decode()
    if STATIC_BASE_URL.startswith("http"):
        return f"{STATIC_BASE_URL}athlete_imgs/512/{athlete_id}.webp"
    return None


def short_title(race: dict) -> str:
    # "2024 World Triathlon Championship Series Cagliari" is too long for a
    # hero line; strip the series boilerplate, keep year + venue.
    t = race["race_title"]
    for noise in ("World Triathlon Championship Series", "World Triathlon Cup",
                  "World Triathlon", "Championship Series"):
        t = t.replace(noise, "")
    return " ".join(t.split())


# Lower-case particles that belong to the surname: "Pierre Le Corre" -> "Le Corre".
_PARTICLES = {"le", "la", "de", "del", "della", "di", "da", "van", "von", "der", "den", "dos", "du", "mc"}


def split_name(name: str) -> tuple[str, str]:
    parts = name.split()
    if len(parts) < 2:
        return "", name
    cut = len(parts) - 1
    while cut > 1 and parts[cut - 1].lower() in _PARTICLES:
        cut -= 1
    return " ".join(parts[:cut]), " ".join(parts[cut:])


def person(r: dict) -> dict:
    first, last = split_name(r["name"])
    return {
        "athlete_id": r["athlete_id"],
        "name":       r["name"],
        "first":      first,
        "last":       last,
        "alpha3":     r["country_alpha3"],
        "face":       face_uri(r["athlete_id"]),
        "position":   r["position"],
    }


def leg_rank(finishers: list[dict], key: str, t: float) -> int:
    return 1 + sum(1 for f in finishers if (f.get(key) or 0) > 0 and f[key] < t)


def race_context(race_id: int) -> dict:
    race = queries.get_race_info(race_id)
    results = queries.get_race_results(race_id)
    finishers = sorted([r for r in results if r["status"] == "Finished" and r["position"]],
                       key=lambda r: r["position"])

    # Podium and top 10 -----------------------------------------------------
    def row(r):
        return {**person(r),
                "time":   format_time(r["overall_s"]),
                "behind": format_time_behind(r["overall_behind_s"]),
                "swim": format_time(r["swim_s"]), "bike": format_time(r["bike_s"]),
                "run":  format_time(r["run_s"])}
    podium = [row(r) for r in finishers[:3]]
    top10  = [row(r) for r in finishers[:10]]
    # Dense variant flags the race's fastest split when it belongs to a top-10 finisher.
    for a, r in zip(top10, finishers[:10]):
        for k in ("swim", "bike", "run"):
            a[f"{k}_fastest"] = r[f"{k}_behind_s"] == 0

    # Fastest legs --------------------------------------------------------
    legs = []
    for label, key in (("Swim", "swim_s"), ("Bike", "bike_s"), ("Run", "run_s")):
        ranked = sorted([r for r in finishers if (r.get(key) or 0) > 0], key=lambda r: r[key])
        best = ranked[0][key]
        legs.append({
            "label": label,
            "rows": [{**person(r), "time": format_time(r[key]),
                      "behind": format_time_behind(r[key] - best)} for r in ranked[:3]],
        })

    date = race["race_date"]
    return {
        "race_id": race_id,
        "race_title": short_title(race),
        "race_full":  race["race_title"],
        "prog":       race["prog_name"],
        "venue":      race["location"],
        "date":       date.strftime("%-d %B %Y"),
        "year":       date.year,
        "podium": podium, "top10": top10, "legs": legs,
        "_finishers": finishers, "_race": race,
    }


def athlete_context(rc: dict, athlete_id: int) -> dict:
    finishers = rc["_finishers"]
    me = next(r for r in finishers if r["athlete_id"] == athlete_id)

    # Splits bar: proportional segments with leg rank -----------------------
    segs = []
    for label, key, bkey in (("Swim", "swim_s", "swim_behind_s"), ("T1", "t1_s", "t1_behind_s"),
                             ("Bike", "bike_s", "bike_behind_s"), ("T2", "t2_s", "t2_behind_s"),
                             ("Run", "run_s", "run_behind_s")):
        t = me[key] or 0
        segs.append({
            "label": label, "key": key.split("_")[0],
            "time": format_time(t), "frac": t / me["overall_s"],
            "rank": leg_rank(finishers, key, t) if t else None,
            "behind": format_time_behind(me[bkey]),
            "fastest": me[bkey] == 0,
        })

    # Rating + world rank move, this race only -----------------------------
    rating = next(r for r in queries.get_race_ratings(rc["race_id"]) if r["athlete_id"] == athlete_id)
    ranks = queries.get_athlete_rankings_data(athlete_id)
    i = next(i for i, r in enumerate(ranks) if r["race_id"] == rc["race_id"])
    rank_now, rank_prev = ranks[i]["world_overall"], (ranks[i - 1]["world_overall"] if i else None)
    discs = [{"label": d.title(), "rating": round(rating[f"{d}_rating"]), "change": round(rating[f"{d}_change"])}
             for d in ("swim", "bike", "run", "transition")]
    # Twelve months of overall rating ending at this race, for the sparkline.
    race_date = rc["_race"]["race_date"]
    year = [h for h in reversed(queries.get_athlete_rating_history(athlete_id))
            if race_date - dt.timedelta(days=365) <= h["race_date"] <= race_date and not h["is_relay"]]
    vals = [h["overall_rating"] for h in year]
    lo, hi = min(vals), max(vals)
    spark = [{"x": j / max(len(vals) - 1, 1), "y": 1 - (v - lo) / max(hi - lo, 1)} for j, v in enumerate(vals)]
    rating_ctx = {
        "overall": round(rating["overall_rating"]), "change": round(rating["overall_change"]),
        "world_rank": rank_now, "world_rank_prev": rank_prev, "discs": discs,
        "spark": spark, "year_change": round(vals[-1] - vals[0]), "year_races": len(vals),
    }

    # Milestones: career markers this race set ------------------------------
    distance = rc["_race"]["distance"]
    conn = queries._get_conn()
    dist_by_race = dict(conn.execute("SELECT race_id, distance FROM races").fetchall())
    hist_all = [h for h in queries.get_athlete_race_history(athlete_id)
                if h["status"] == "Finished" and h["race_date"] <= rc["_race"]["race_date"]]
    same_dist = [h for h in hist_all if dist_by_race.get(h["race_id"]) == distance and h["overall_s"] > 0]
    milestones = []
    if me["overall_s"] <= min(h["overall_s"] for h in same_dist):
        milestones.append({"icon": "stopwatch", "big": format_time(me["overall_s"]),
                           "text": f"Career-best {distance} distance finish time"})
    for label, key in (("swim", "swim_s"), ("bike", "bike_s"), ("run", "run_s")):
        best = min((h[key] for h in same_dist if h[key]), default=None)
        if best and me[key] <= best:
            milestones.append({"icon": label, "big": format_time(me[key]),
                               "text": f"Career-best {distance} distance {label} split"})
    wins    = sum(1 for h in hist_all if h["position"] == 1)
    podiums = sum(1 for h in hist_all if h["position"] and h["position"] <= 3)
    if me["position"] == 1:
        milestones.append({"icon": "medal", "big": ordinal(wins), "text": "Career win"})
    elif me["position"] <= 3:
        milestones.append({"icon": "medal", "big": ordinal(podiums), "text": "Career podium"})
    if rank_prev and rank_now < rank_prev:
        milestones.append({"icon": "trend", "big": f"#{rank_now}",
                           "text": f"World ranking, up from #{rank_prev}"})
    peak = min(r["world_overall"] for r in ranks[: i + 1])
    if rank_now == peak and (rank_prev is None or rank_now < rank_prev):
        milestones[-1]["text"] = f"World ranking, up from #{rank_prev}. Career high"

    return {
        **{k: v for k, v in rc.items() if not k.startswith("_")},
        "me": {**person(me), "pos_ord": ordinal(me["position"]),
               "time": format_time(me["overall_s"]), "behind": format_time_behind(me["overall_behind_s"]),
               "swim": format_time(me["swim_s"]), "bike": format_time(me["bike_s"]), "run": format_time(me["run_s"])},
        "segs": segs, "rating": rating_ctx, "milestones": milestones[:3],
    }



def render_html(design: str, ctx: dict, mode: str, ink: str, photo: str | None = None) -> tuple[str, int, int]:
    tpl_name, (w, h), _, _ = DESIGNS[design]
    html = _env.get_template(tpl_name).render(**ctx, mode=mode, ink=ink, photo=photo, W=w, H=h, STATIC_URI=STATIC_URI)
    return html, w, h


def render_png(design: str, ctx: dict, mode: str, ink: str, photo: str | None = None, scale: int = 2) -> bytes:
    """Render one card to PNG bytes. `photo` is a data URI for photo mode.

    A fresh browser per call: the sync Playwright API is bound to the thread
    that created it, and FastAPI runs sync handlers on a pool. ~0.5s overhead,
    fine for a share button.
    """
    html, w, h = render_html(design, ctx, mode, ink, photo)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
        # Loaded from a file:// document so the font, flag and logo
        # subresources (also file://) are allowed; set_content blocks them.
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete_on_close=False) as f:
            f.write(html); f.close()
            page.goto(Path(f.name).as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            png = page.locator("#card").screenshot(omit_background=(mode == "transparent"))
        browser.close()
    return png
