"""Share cards: build template contexts for a race / athlete-in-race and
render a design to PNG.

Designs are Jinja templates in app/share/templates/. Each extends _base.html,
which handles size, mode (solid / photo / transparent), ink (light / dark
text) and the PTD footer.
"""
from __future__ import annotations

import base64
import datetime as dt
import queue
import tempfile
import threading
from concurrent.futures import Future
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
    "r1_podium":       ("r1_podium.html",       PORTRAIT, "race",    "Podium"),
    "r2_top10":        ("r2_top10.html",        PORTRAIT, "race",    "Top ten"),
    "r2b_top10_dense": ("r2b_top10_dense.html", PORTRAIT, "race",    "Top ten with splits"),
    "r3_fastest_legs": ("r3_fastest_legs.html", PORTRAIT, "race",    "Fastest splits"),
    "r4_best_perf":    ("r4_best_perf.html",    PORTRAIT, "race",    "Best performances"),
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
    # hero line; shorten the series names but keep year, series and venue.
    t = race["race_title"]
    for noise, short in (("World Triathlon Championship Series", "WTCS"), ("World Triathlon Cup", "World Cup"),
                         ("World Triathlon Para Series", "Para Series"), ("World Triathlon", "")):
        t = t.replace(noise, short)
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

    # Best performances: biggest rating gain per discipline ---------------
    # Same pick as the race page badges. Ignored races have no ratings rows,
    # so the list comes back empty and the card is unavailable.
    ratings = queries.get_race_ratings(race_id)
    best = []
    for d in ("overall", "swim", "bike", "run"):
        top = max(ratings, key=lambda r: r[f"{d}_change"] or 0, default=None)
        if top and (top[f"{d}_change"] or 0) > 0:
            best.append({**person(top), "label": d.title(),
                         "change": round(top[f"{d}_change"]), "rating": round(top[f"{d}_rating"])})

    date = race["race_date"]
    return {
        "race_id": race_id,
        "race_title": short_title(race),
        "race_full":  race["race_title"],
        "prog":       race["prog_name"],
        "venue":      race["location"],
        "date":       date.strftime("%-d %B %Y"),
        "year":       date.year,
        "podium": podium, "top10": top10, "legs": legs, "best": best,
        "_finishers": finishers, "_race": race,
    }


def predicted_race_context(race_id: int) -> dict:
    """Same shape as race_context, built from the precomputed predictions for
    an upcoming race, so the race-level designs render unchanged with
    `predicted` set for the templates to label."""
    race = queries.get_upcoming_race_info(race_id)
    entries = {e["athlete_id"]: e for e in queries.get_upcoming_race_entries(race_id)}
    stored = [r for r in queries.get_race_predictions(race_id) if r["athlete_id"] in entries and r["overall_s"]]
    stored.sort(key=lambda r: r["overall_s"])
    for i, r in enumerate(stored):
        r["position"] = i + 1
        r["name"], r["country_alpha3"] = entries[r["athlete_id"]]["name"], entries[r["athlete_id"]]["country_alpha3"]
    best = {k: min(r[k] for r in stored if r[k]) for k in ("overall_s", "swim_s", "bike_s", "run_s")}

    def row(r):
        return {**person(r),
                "time":   format_time(r["overall_s"]), "behind": format_time_behind(r["overall_s"] - best["overall_s"]),
                "swim": format_time(r["swim_s"]), "bike": format_time(r["bike_s"]), "run": format_time(r["run_s"]),
                **{f"{k}_fastest": r[f"{k}_s"] == best[f"{k}_s"] for k in ("swim", "bike", "run")}}
    legs = []
    for label, key in (("Swim", "swim_s"), ("Bike", "bike_s"), ("Run", "run_s")):
        ranked = sorted([r for r in stored if r[key]], key=lambda r: r[key])
        legs.append({"label": label, "rows": [{**person(r), "time": format_time(r[key]),
                                               "behind": format_time_behind(r[key] - best[key])} for r in ranked[:3]]})
    date = race["race_date"]
    return {
        "race_id": race_id, "predicted": True,
        "race_title": short_title(race), "race_full": race["race_title"],
        "prog": race["prog_name"], "venue": race["location"],
        "date": date.strftime("%-d %B %Y"), "year": date.year,
        "podium": [row(r) for r in stored[:3]], "top10": [row(r) for r in stored[:10]], "legs": legs,
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
    # Ignored races have no ratings rows; rankings are course-scoped, so look
    # the race up in the right bucket. Either can be missing, in which case
    # the rating card is unavailable and the milestones skip the rank marker.
    rating = next((r for r in queries.get_race_ratings(rc["race_id"]) if r["athlete_id"] == athlete_id), None)
    course = queries.course_for_distance(rc["_race"]["distance"]) or "short"
    ranks = queries.get_athlete_rankings_data(athlete_id, course=course)
    i = next((i for i, r in enumerate(ranks) if r["race_id"] == rc["race_id"]), None)
    rank_now = ranks[i]["world_overall"] if i is not None else None
    rank_prev = ranks[i - 1]["world_overall"] if i else None
    rating_ctx = None
    if rating:
        rating_ctx = {
            "overall": round(rating["overall_rating"]), "change": round(rating["overall_change"]),
            "world_rank": rank_now, "world_rank_prev": rank_prev,
            "discs": [{"label": d.title(), "rating": round(rating[f"{d}_rating"]), "change": round(rating[f"{d}_change"])}
                      for d in ("swim", "bike", "run", "transition")],
        }

    # Milestones: career markers this race set ------------------------------
    distance = rc["_race"]["distance"]
    dist_label = {"standard": "Olympic distance", "sprint": "Sprint distance"}.get(distance, f"{distance} distance")
    conn = queries._get_conn()
    dist_by_race = dict(conn.execute("SELECT race_id, distance FROM races").fetchall())
    hist_all = [h for h in queries.get_athlete_race_history(athlete_id, course=course)
                if h["status"] == "Finished" and h["race_date"] <= rc["_race"]["race_date"]]
    same_dist = [h for h in hist_all if dist_by_race.get(h["race_id"]) == distance and h["overall_s"] > 0]
    milestones = []
    if me["overall_s"] <= min(h["overall_s"] for h in same_dist):
        milestones.append({"icon": "stopwatch", "big": format_time(me["overall_s"]),
                           "text": f"{dist_label} PB"})
    for label, key in (("swim", "swim_s"), ("bike", "bike_s"), ("run", "run_s")):
        best = min((h[key] for h in same_dist if h[key]), default=None)
        if best and me[key] <= best:
            milestones.append({"icon": label, "big": format_time(me[key]),
                               "text": f"{dist_label} {label} PB"})
    wins    = sum(1 for h in hist_all if h["position"] == 1)
    podiums = sum(1 for h in hist_all if h["position"] and h["position"] <= 3)
    if me["position"] == 1:
        milestones.append({"icon": "medal", "big": ordinal(wins), "text": "Career win"})
    elif me["position"] <= 3:
        milestones.append({"icon": "medal", "big": ordinal(podiums), "text": "Career podium"})
    if rank_prev and rank_now and rank_now < rank_prev:
        peak = min(r["world_overall"] for r in ranks[: i + 1])
        text = f"{'Career-high world' if rank_now == peak else 'World'} ranking, up from #{rank_prev}"
        milestones.append({"icon": "trend", "big": f"#{rank_now}", "text": text})

    return {
        **{k: v for k, v in rc.items() if not k.startswith("_")},
        "me": {**person(me), "pos_ord": ordinal(me["position"]),
               "time": format_time(me["overall_s"]), "behind": format_time_behind(me["overall_behind_s"]),
               "swim": format_time(me["swim_s"]), "bike": format_time(me["bike_s"]), "run": format_time(me["run_s"])},
        "segs": segs, "rating": rating_ctx, "milestones": milestones[:3],
    }



def render_html(design: str, ctx: dict, mode: str, ink: str, photo: str | None = None,
                size: tuple[int, int] | None = None) -> tuple[str, int, int]:
    """`size` overrides the design's default; the social carousel needs every
    card at the same aspect ratio."""
    tpl_name, default_size, _, _ = DESIGNS[design]
    w, h = size or default_size
    html = _env.get_template(tpl_name).render(**ctx, mode=mode, ink=ink, photo=photo, W=w, H=h, STATIC_URI=STATIC_URI)
    return html, w, h


class _Renderer(threading.Thread):
    """One Chromium kept alive on its own thread, renders serialised through
    a queue. The sync Playwright API is bound to the thread that created it
    and FastAPI runs sync handlers on a pool, so the browser can't be shared
    directly; handlers hand a job over and wait on a Future instead. Launch
    is the expensive part (seconds on the Hetzner box), a page is ~0.3s.
    """

    def __init__(self):
        super().__init__(name="share-renderer", daemon=True)
        self.jobs: queue.Queue = queue.Queue()

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            while (job := self.jobs.get()) is not None:
                fut, html, w, h, scale, fmt, quality = job
                if not browser.is_connected():   # crashed between jobs: relaunch rather than fail forever
                    browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
                try:
                    # Loaded from a file:// document so the font, flag and logo
                    # subresources (also file://) are allowed; set_content blocks them.
                    with tempfile.NamedTemporaryFile("w", suffix=".html", delete_on_close=False) as f:
                        f.write(html); f.close()
                        page.goto(Path(f.name).as_uri(), wait_until="load")
                        page.evaluate("document.fonts.ready")
                        fut.set_result(page.locator("#card").screenshot(
                            type=fmt, quality=quality, omit_background=(fmt == "png")))
                except Exception as e:  # hand the failure to the waiting request; the thread must keep serving
                    fut.set_exception(e)
                finally:
                    page.close()
            browser.close()

    def render(self, html: str, w: int, h: int, scale: float, fmt: str, quality: int | None) -> bytes:
        fut: Future = Future()
        self.jobs.put((fut, html, w, h, scale, fmt, quality))
        return fut.result(timeout=60)


_renderer: _Renderer | None = None
_renderer_lock = threading.Lock()


def _get_renderer() -> _Renderer:
    global _renderer
    with _renderer_lock:
        if _renderer is None or not _renderer.is_alive():
            _renderer = _Renderer()
            _renderer.start()
        return _renderer


def shutdown_renderer() -> None:
    """Close the browser cleanly; called from the app lifespan."""
    if _renderer is not None and _renderer.is_alive():
        _renderer.jobs.put(None)
        _renderer.join(timeout=10)


def render_png(design: str, ctx: dict, mode: str, ink: str, photo: str | None = None, scale: int = 2,
               size: tuple[int, int] | None = None) -> bytes:
    """Full-quality PNG at 2x, for the social poster where time doesn't matter."""
    html, w, h = render_html(design, ctx, mode, ink, photo, size)
    return _get_renderer().render(html, w, h, scale, "png", None)


def render_card(design: str, ctx: dict, mode: str, ink: str, photo: str | None = None) -> tuple[bytes, str]:
    """Card for the share dialog: (bytes, media type).

    Chromium's PNG encoder dominates render time (3s for a 2x card on the
    box against 0.7s for JPEG), so opaque cards ship as JPEG at 2x and only
    transparent ones pay for PNG, at 1.5x to keep it under two seconds.
    """
    html, w, h = render_html(design, ctx, mode, ink, photo)
    if mode == "transparent":
        return _get_renderer().render(html, w, h, 1.5, "png", None), "image/png"
    return _get_renderer().render(html, w, h, 2, "jpeg", 90), "image/jpeg"
