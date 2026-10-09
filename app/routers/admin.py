"""Admin-only tools, gated by a token cookie. Unlisted: every miss is a 404
so the routes look like any unknown page, robots.txt disallows /admin/, and
responses are no-store so Cloudflare never caches them.

/admin/instagram: collate athletes' Instagram handles. Suggests the next
athlete in priority order (recent elite starts, then rank), saves a handle
or a skip to an append-only pending CSV in RUNTIME_DATA_DIR. refresh.sh pulls
that file into data/instagram.csv, so entries reach the DB (and athlete
pages) on the next build + deploy.

/admin/startlist: paste pro men's / women's start lists for long-course
races nobody publishes programmatically. Names are matched against the DB
(accent-folded, either name order), unmatched ones can be minted as new
athletes, and the result is one JSON per event in RUNTIME_DATA_DIR/
startlists_pending/. refresh.sh pulls those into data/startlists/ and the
build loads them like WT start lists.
"""
import csv
import hmac
import json
import re
import unicodedata
from datetime import datetime, timezone
from difflib import get_close_matches

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ADMIN_TOKEN, ASSET_VERSION, RUNTIME_DATA_DIR, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import db, queries
from ptd_data.pto_ingest import _fold_key

templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"] = flag

COOKIE = "ptd_admin"
PENDING_PATH = RUNTIME_DATA_DIR / "instagram_pending.csv"
STARTLISTS_PENDING = RUNTIME_DATA_DIR / "startlists_pending"
NO_STORE = {"Cache-Control": "no-store"}


def require_admin(request: Request):
    token = request.cookies.get(COOKIE, "")
    if not ADMIN_TOKEN or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=404, detail="Page not found")


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
login_router = APIRouter(prefix="/admin")


@login_router.get("/login")
def login(token: str = ""):
    if not ADMIN_TOKEN or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=404, detail="Page not found")
    resp = RedirectResponse("/admin/instagram", status_code=303)
    resp.set_cookie(COOKIE, token, max_age=365 * 86400, httponly=True, secure=True, samesite="lax")
    return resp


def _pending():
    """Rows in the local append-only file, oldest first."""
    if not PENDING_PATH.exists():
        return []
    with open(PENDING_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_pending(athlete_id, name, handle):
    new = not PENDING_PATH.exists() or PENDING_PATH.stat().st_size == 0
    with open(PENDING_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=db.INSTAGRAM_CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({"athlete_id": athlete_id, "name": name, "handle": handle,
                    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


@router.get("/instagram", response_class=HTMLResponse)
def instagram_tool(request: Request, error: str = "", q: int | None = None):
    pending = _pending()
    # Later rows win per athlete; an "undo" row has handle='' and name='' so
    # the athlete comes back into the queue.
    latest = {}
    for row in pending:
        latest[int(row["athlete_id"])] = row
    done = {aid: r for aid, r in latest.items() if r["name"]}
    queue = queries.get_instagram_queue(done.keys(), limit=6)
    # ?q= pins a specific athlete: after an undo, or to re-show a failed save.
    if q is not None:
        current = queries.get_athlete_info(q)
        if current is None:
            raise HTTPException(status_code=404, detail="Athlete not found")
        current["recent_elite"] = current["active_world_overall"] = None
    else:
        current = queue[0] if queue else None
    with_handle, skipped, remaining = queries.get_instagram_stats()
    recent = [r for r in reversed(pending) if r["name"]][:12]
    return templates.TemplateResponse("admin_instagram.html", {
        "request":        request,
        "active_page":    None,
        "admin_tool":     "instagram",
        "noindex":        True,
        "current":        current,
        "up_next":        [a for a in queue if current is None or a["athlete_id"] != current["athlete_id"]][:5],
        "recent":         recent,
        "error":          error,
        "stats":          {"handles": with_handle + sum(1 for r in done.values() if r["handle"]),
                           "skipped": skipped + sum(1 for r in done.values() if not r["handle"]),
                           "remaining": max(remaining - len(done), 0),
                           "pending": len(done)},
    }, headers=NO_STORE)


@router.post("/instagram")
def instagram_submit(athlete_id: int = Form(...), name: str = Form(""),
                     action: str = Form(...), handle: str = Form("")):
    if action == "undo":
        _append_pending(athlete_id, "", "")
        return RedirectResponse(f"/admin/instagram?q={athlete_id}", status_code=303, headers=NO_STORE)
    if action == "skip":
        _append_pending(athlete_id, name, "")
        return RedirectResponse("/admin/instagram", status_code=303, headers=NO_STORE)
    if action != "save":
        raise HTTPException(status_code=400, detail=f"unknown action {action!r}")

    clean = db.normalize_instagram_handle(handle)
    if clean is None:
        return RedirectResponse(f"/admin/instagram?q={athlete_id}&error=Not+a+valid+handle", status_code=303, headers=NO_STORE)
    owner = queries.get_instagram_owner(clean)
    if owner is None:
        owner = next(({"athlete_id": int(r["athlete_id"]), "name": r["name"]} for r in _pending()
                      if r["handle"].lower() == clean.lower() and int(r["athlete_id"]) != athlete_id), None)
    if owner and owner["athlete_id"] != athlete_id:
        msg = f"@{clean} already belongs to {owner['name']} ({owner['athlete_id']})".replace(" ", "+")
        return RedirectResponse(f"/admin/instagram?q={athlete_id}&error={msg}", status_code=303, headers=NO_STORE)
    _append_pending(athlete_id, name, clean)
    return RedirectResponse("/admin/instagram", status_code=303, headers=NO_STORE)


# ─── Long-course start lists ─────────────────────────────────────────────────

DISTANCES = ("middle", "t100", "long")
BRANDS = ("ironman", "t100", "challenge", "independent")
# Start lists use IOC codes; nationalities.alpha3 is ISO. Only the ones that
# differ are listed; everything else passes through unchanged.
_IOC_TO_ISO = {
    "GER": "DEU", "DEN": "DNK", "NED": "NLD", "SUI": "CHE", "POR": "PRT", "RSA": "ZAF", "CRO": "HRV",
    "GRE": "GRC", "SLO": "SVN", "LAT": "LVA", "BUL": "BGR", "CHI": "CHL", "URU": "URY", "PAR": "PRY",
    "PHI": "PHL", "INA": "IDN", "MAS": "MYS", "UAE": "ARE", "KSA": "SAU", "IRI": "IRN", "ZIM": "ZWE",
    "NGR": "NGA", "ALG": "DZA", "MRI": "MUS", "GUA": "GTM", "HON": "HND", "NCA": "NIC", "PUR": "PRI",
    "BAH": "BHS", "BAR": "BRB", "TRI": "TTO", "HAI": "HTI", "CRC": "CRI", "ESA": "SLV", "MGL": "MNG",
    "VIE": "VNM", "TPE": "TWN", "KUW": "KWT", "OMA": "OMN", "BRN": "BHR", "LIB": "LBN", "SRI": "LKA",
    "NEP": "NPL", "BAN": "BGD", "MYA": "MMR", "FIJ": "FJI", "SAM": "WSM", "TGA": "TON", "ISV": "VIR",
    "BER": "BMU", "CAY": "CYM", "ARU": "ABW", "LBA": "LBY", "SUD": "SDN", "TAN": "TZA", "ZAM": "ZMB",
    "BOT": "BWA", "ANG": "AGO", "MAD": "MDG", "MAW": "MWI", "MTN": "MRT", "NIG": "NER", "BUR": "BFA",
    "TOG": "TGO", "GAM": "GMB", "GUI": "GIN", "GBS": "GNB", "GEQ": "GNQ", "CGO": "COG", "CHA": "TCD",
    "SOL": "SLB", "VAN": "VUT", "PLE": "PSE", "KOS": "UNK",
}
_HEADER_WORDS = {"bib", "no", "no.", "#", "name", "athlete", "country", "nat", "nation", "nationality",
                 "start", "number", "pos", "rank", "team", "age"}


def _slugify(text):
    """PTO-style slug: 'Léon Chevalier' -> 'leon-chevalier'. Plain accent
    stripping, not _fold_key, which would also collapse 'oe' to 'o'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def parse_startlist(text):
    """One athlete per line in whatever shape got pasted: '12 Kristian Blummenfelt NOR',
    'Blummenfelt, Kristian (NOR)', tab-separated bib/name/country columns.
    Returns [{start_num, name, code}] with code the 3-letter country if found."""
    rows = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line:
            continue
        cells = [c.strip() for c in re.split(r"\t|\||,|\s{2,}", line) if c.strip()]
        if all(c.lower() in _HEADER_WORDS for c in cells):
            continue
        start_num, code, name_parts = 0, "", []
        for c in cells:
            m = re.fullmatch(r"#?(\d{1,4})\.?", c)
            if m and not start_num:
                start_num = int(m.group(1))
                continue
            m = re.search(r"\(?\b([A-Z]{3})\b\)?", c)
            if m and (c == m.group(0) or c.endswith(m.group(0))) and len(c) <= 6:
                code = m.group(1)
                continue
            if m and c.endswith(m.group(0)):
                code = m.group(1)
                c = c[:m.start()].strip()
            name_parts.append(c)
        name = " ".join(name_parts)
        m = re.match(r"^#?(\d{1,4})\.?\s+(.*)$", name)
        if m and not start_num:
            start_num, name = int(m.group(1)), m.group(2)
        name = re.sub(r"\([^)]*\)", "", name).strip(" .,;:-")
        if not name:
            continue
        # 'LASTNAME Firstname' -> 'Lastname Firstname'; matching is order-agnostic.
        name = " ".join(w.title() if w.isupper() and len(w) > 2 else w for w in name.split())
        rows.append({"start_num": start_num, "name": name, "code": _IOC_TO_ISO.get(code, code)})
    return rows


def match_startlist(rows, gender):
    """Attach match candidates to parsed rows. status: exact (one athlete with
    the same folded name), ambiguous (several), fuzzy (close names, or same
    surname + country for the Kat/Katrina, Rudy/Rodolphe cases), none."""
    cands = queries.get_startlist_candidates(gender)
    by_key, by_tokens, by_surname = {}, {}, {}
    for c in cands:
        by_key.setdefault(_fold_key(c["name"]), []).append(c)
        by_tokens.setdefault(" ".join(sorted(_fold_key(w) for w in c["name"].split())), []).append(c)
        by_surname.setdefault(_fold_key(c["name"].split()[-1]), []).append(c)
    keys = list(by_key)
    for r in rows:
        key = _fold_key(r["name"])
        tok = " ".join(sorted(_fold_key(w) for w in r["name"].split()))
        found = by_key.get(key) or by_tokens.get(tok) or []
        if found:
            r["status"] = "exact" if len(found) == 1 else "ambiguous"
        else:
            close = get_close_matches(key, keys, n=3, cutoff=0.86)
            found = [c for k in close for c in by_key[k]]
            if not found and r["code"]:
                found = [c for c in by_surname.get(_fold_key(r["name"].split()[-1]), [])
                         if c["country_alpha3"] == r["code"]]
            r["status"] = "fuzzy" if found else "none"
        # Country match first, then long-course pedigree, then recency.
        found.sort(key=lambda c: (c["country_alpha3"] != r["code"], -c["long_starts"], str(c["last_race"])), reverse=False)
        r["candidates"] = found[:4]
        r["pto_slug"] = _slugify(r["name"])
    return rows


def _saved_startlists():
    files = sorted(STARTLISTS_PENDING.glob("*.json")) if STARTLISTS_PENDING.exists() else []
    out = []
    for f in files:
        d = json.loads(f.read_text())
        out.append({"file": f.name, "name": d["event"]["name"], "date": d["event"]["date"],
                    "men": len(d["races"]["male"]), "women": len(d["races"]["female"])})
    return out


def _event_from_form(form):
    ev = {k: form.get(k, "").strip() for k in ("name", "slug", "venue", "country", "date", "date_female", "distance", "brand", "prize_usd")}
    if not ev["name"] or not ev["date"] or not ev["country"]:
        raise HTTPException(status_code=400, detail="name, date and country are required")
    if ev["distance"] not in DISTANCES or ev["brand"] not in BRANDS:
        raise HTTPException(status_code=400, detail="bad distance or brand")
    datetime.strptime(ev["date"], "%Y-%m-%d")
    ev["slug"] = ev["slug"] or _slugify(ev["name"])
    ev["prize_usd"] = int(ev["prize_usd"] or 0)
    return ev


@router.get("/startlist", response_class=HTMLResponse)
def startlist_form(request: Request, saved: str = ""):
    return templates.TemplateResponse("admin_startlist.html", {
        "request": request, "active_page": None, "admin_tool": "startlist", "noindex": True,
        "nationalities": queries.get_nationalities(), "distances": DISTANCES, "brands": BRANDS,
        "saved_files": _saved_startlists(), "saved": saved,
    }, headers=NO_STORE)


@router.post("/startlist/review", response_class=HTMLResponse)
async def startlist_review(request: Request):
    form = await request.form()
    ev = _event_from_form(form)
    races = {g: match_startlist(parse_startlist(form.get(f"list_{g}", "")), g) for g in ("male", "female")}
    if not races["male"] and not races["female"]:
        raise HTTPException(status_code=400, detail="no athletes parsed from either list")
    # Two names share GBR; nationalities come sorted so "Great Britain" wins.
    alpha3_to_country = {}
    for cf, a3 in queries.get_nationalities():
        alpha3_to_country.setdefault(a3, cf)
    for rows in races.values():
        for r in rows:
            r["country_guess"] = alpha3_to_country.get(r["code"], ev["country"] if not r["code"] else "")
    return templates.TemplateResponse("admin_startlist_review.html", {
        "request": request, "active_page": None, "admin_tool": "startlist", "noindex": True,
        "event": ev, "races": races, "nationalities": queries.get_nationalities(),
    }, headers=NO_STORE)


@router.post("/startlist/save")
async def startlist_save(request: Request):
    form = await request.form()
    if form.get("action") == "delete":
        target = STARTLISTS_PENDING / form["file"]
        if target.parent != STARTLISTS_PENDING or not target.exists():
            raise HTTPException(status_code=404, detail="no such file")
        target.unlink()
        return RedirectResponse("/admin/startlist", status_code=303, headers=NO_STORE)

    ev = json.loads(form["event"])
    races = {"male": [], "female": []}
    for g in races:
        n = int(form.get(f"n_{g}", 0))
        for i in range(n):
            choice = form.get(f"m_{g}_{i}", "drop")
            if choice == "drop":
                continue
            entry = {"start_num": int(form.get(f"num_{g}_{i}") or 0), "name": form.get(f"name_{g}_{i}", "").strip()}
            if choice == "new":
                entry.update(athlete_id=None, country=form.get(f"country_{g}_{i}", "").strip(),
                             yob=int(form.get(f"yob_{g}_{i}") or 0), pto_slug=form.get(f"slug_{g}_{i}", "").strip())
                if not entry["country"] or not entry["pto_slug"]:
                    raise HTTPException(status_code=400, detail=f"new athlete {entry['name']!r} needs a country and slug")
            else:
                entry["athlete_id"] = int(choice)
            races[g].append(entry)
    seen = [e["athlete_id"] or e["pto_slug"] for g in races for e in races[g]]
    if len(seen) != len(set(seen)):
        raise HTTPException(status_code=400, detail="an athlete appears twice")

    STARTLISTS_PENDING.mkdir(parents=True, exist_ok=True)
    path = STARTLISTS_PENDING / f"{ev['slug']}-{ev['date'][:4]}.json"
    path.write_text(json.dumps({"event": ev, "races": races, "saved_at": datetime.now(timezone.utc).isoformat()}, indent=1, ensure_ascii=False))
    return RedirectResponse(f"/admin/startlist?saved={path.name}", status_code=303, headers=NO_STORE)
