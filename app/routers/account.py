import hmac
import io
import re

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError

from config import ASSET_VERSION, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import queries
from ptd_users import emails
from ptd_users import queries as uq
from ptd_users.auth import clear_session_cookie, current_user, require_user
from app.routers.router_utils import format_time, user_avatar

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["user_avatar"]   = user_avatar
templates.env.globals["format_time"]   = format_time

DELETE_PHRASE = "delete my account"
MAX_AVATAR_UPLOAD = 8 * 1024 * 1024
AVATAR_SIZE = 128
NO_STORE = {"Cache-Control": "no-store"}


def _form_values(user):
    """Display strings for the profile form, from the saved account."""
    values = {
        "display_name": user["display_name"],
        "country":      user["country"] or "",
        "email_updates": user["email_updates"],
        "bio":          user["bio"] or "",
        "club":         user["club"] or "",
        "instagram":    f"@{user['instagram']}" if user["instagram"] else "",
        "strava":       f"strava.com/athletes/{user['strava']}" if user["strava"] else "",
    }
    for col, *_ in PB_FIELDS:
        values[col] = format_time(user[col]) if user[col] else ""
    return values


async def following_rows(user_id):
    """The athletes and people a user follows, newest first, as one list of
    display rows tagged with their kind. Shared with the public profile."""
    following = await uq.get_following(user_id)
    athletes = queries.get_athletes_brief_bulk([i for k, i in following if k == "athlete"])
    people = await uq.get_users_brief([i for k, i in following if k == "user"])
    rows = []
    for kind, ref_id in following:
        brief = (athletes if kind == "athlete" else people).get(ref_id)
        if brief:  # ids can drop out of DuckDB when a rebuild merges athletes
            rows.append({"kind": kind, **brief})
    return rows


async def _render_account(request, user, saved=False, error=None, status_code=200, draft=None):
    """draft: the submitted form values, so a rejected save keeps what was typed."""
    # Only upcoming liked races are listed: a like on a finished race is a
    # reaction with nothing left to manage.
    liked = queries.get_races_brief_bulk((await uq.get_follows(user["user_id"]))["races"])
    return templates.TemplateResponse("settings.html", {
        "request":     request,
        "active_page": None,
        "user":        user,
        "following":   await following_rows(user["user_id"]),
        "liked_races": sorted((r for r in liked.values() if r["is_upcoming"]), key=lambda r: r["race_date"]),
        "countries":   queries.get_nationality_options(),
        "saved":       saved,
        "error":       error,
        "delete_phrase": DELETE_PHRASE,
        "pb_fields":   PB_FIELDS,
        "form":        draft or _form_values(user),
    }, status_code=status_code, headers=NO_STORE)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    user = await current_user(request)
    if user is None:
        return RedirectResponse("/login?next=/settings", status_code=303)
    return await _render_account(request, user, saved=saved)


@router.get("/account")
async def account_redirect():
    return RedirectResponse("/settings", status_code=301)


# Self-reported PBs: (column, label, fastest, slowest) in seconds. The bounds
# only catch typos and jokes (a 30 minute Ironman), not honest optimism.
PB_FIELDS = [
    ("pb_sprint",  "Sprint",  40 * 60,  4 * 3600),
    ("pb_olympic", "Olympic", 80 * 60,  6 * 3600),
    ("pb_703",     "70.3",    195 * 60, 10 * 3600),
    ("pb_1406",    "140.6",   7 * 3600, 17 * 3600),
]
INSTAGRAM_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:instagram\.com/)?@?([A-Za-z0-9._]{1,30})/?(?:\?.*)?$")
STRAVA_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:strava\.com/athletes/)?(\d{1,12})/?(?:\?.*)?$")


def parse_duration(text):
    """'h:mm:ss' or 'mm:ss' -> seconds, or None if the format is wrong."""
    parts = text.split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    *rest, mins, secs = [int(p) for p in parts]
    if mins >= 60 and rest or secs >= 60:
        return None
    return (rest[0] if rest else 0) * 3600 + mins * 60 + secs


@router.post("/account/update")
async def account_update(request: Request,
                         display_name: str = Form(""),
                         country: str = Form(""),
                         email_updates: bool = Form(False),
                         bio: str = Form(""),
                         club: str = Form(""),
                         pb_sprint: str = Form(""),
                         pb_olympic: str = Form(""),
                         pb_703: str = Form(""),
                         pb_1406: str = Form(""),
                         instagram: str = Form(""),
                         strava: str = Form("")):
    user = await require_user(request)
    draft = {"display_name": display_name, "country": country, "email_updates": email_updates,
             "bio": bio, "club": club, "instagram": instagram, "strava": strava,
             "pb_sprint": pb_sprint, "pb_olympic": pb_olympic, "pb_703": pb_703, "pb_1406": pb_1406}

    async def fail(msg):
        return await _render_account(request, user, error=msg, status_code=400, draft=draft)

    display_name = display_name.strip()
    if not 2 <= len(display_name) <= 40:
        return await fail("Display name must be 2 to 40 characters.")
    country = country.strip().upper() or None
    if country is not None and country not in {a3 for _, a3 in queries.get_nationality_options()}:
        return await fail("Unknown country.")
    bio = bio.strip() or None
    if bio and len(bio) > 280:
        return await fail("Bio must be 280 characters or fewer.")
    club = club.strip() or None
    if club and len(club) > 60:
        return await fail("Club must be 60 characters or fewer.")

    fields = {"display_name": display_name, "country": country, "email_updates": email_updates,
              "bio": bio, "club": club}

    raw_pbs = {"pb_sprint": pb_sprint, "pb_olympic": pb_olympic, "pb_703": pb_703, "pb_1406": pb_1406}
    for col, label, fastest, slowest in PB_FIELDS:
        text = raw_pbs[col].strip()
        if not text:
            fields[col] = None
            continue
        secs = parse_duration(text)
        if secs is None:
            return await fail(f"{label} PB must look like 1:05:30 (h:mm:ss) or 58:12 (mm:ss).")
        if not fastest <= secs <= slowest:
            return await fail(f"{label} PB of {text} is outside the plausible range.")
        fields[col] = secs

    instagram = instagram.strip()
    m = INSTAGRAM_RE.match(instagram) if instagram else None
    if instagram and not m:
        return await fail("Instagram must be a handle like @name or a profile link.")
    fields["instagram"] = m.group(1) if m else None

    strava = strava.strip()
    m = STRAVA_RE.match(strava) if strava else None
    if strava and not m:
        return await fail("Strava must be your athlete profile link, like strava.com/athletes/12345.")
    fields["strava"] = int(m.group(1)) if m else None

    await uq.update_user(user["user_id"], fields)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/account/unfollow")
async def account_unfollow(request: Request,
                           kind: str = Form(...),
                           ref_id: int = Form(...)):
    user = await require_user(request)
    if kind not in ("athlete", "race", "user"):
        raise HTTPException(status_code=400, detail="Invalid follow kind")
    # Toggle is safe here: the account page only lists existing follows.
    await uq.toggle_follow(user["user_id"], kind, ref_id)
    return RedirectResponse("/settings#following", status_code=303)


@router.post("/account/delete")
async def account_delete(request: Request, confirm: str = Form("")):
    user = await require_user(request)
    if confirm.strip().lower() != DELETE_PHRASE:
        return await _render_account(request, user,
            error=f'Type "{DELETE_PHRASE}" to confirm deletion.', status_code=400)
    await uq.delete_user(user["user_id"])
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    return response


@router.post("/account/avatar")
async def account_avatar(request: Request, photo: UploadFile = File(...)):
    user = await require_user(request)
    data = await photo.read()
    if len(data) > MAX_AVATAR_UPLOAD:
        return await _render_account(request, user, error="Photos must be under 8 MB.", status_code=400)
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    except (UnidentifiedImageError, Image.DecompressionBombError):
        return await _render_account(request, user, error="That file is not a usable image.", status_code=400)
    # Centre-crop to a square and store small; comments show it at 24-40px.
    img = ImageOps.fit(img.convert("RGB"), (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=85)
    await uq.set_avatar(user["user_id"], buf.getvalue())
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/account/avatar/remove")
async def account_avatar_remove(request: Request):
    user = await require_user(request)
    await uq.set_avatar(user["user_id"], None)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.get("/avatar/{user_id}.webp")
async def avatar(user_id: int):
    data = await uq.get_avatar(user_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No photo")
    # The URL carries ?v=avatar_version, so a new upload is a new URL.
    return Response(data, media_type="image/webp",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


def _check_unsubscribe(u, t):
    if not hmac.compare_digest(t, emails.unsubscribe_sig(u)):
        raise HTTPException(status_code=400, detail="This unsubscribe link is invalid.")


@router.get("/email/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_page(request: Request, u: int = Query(...), t: str = Query(...)):
    # A button, not an instant unsubscribe: link scanners open every URL.
    _check_unsubscribe(u, t)
    return templates.TemplateResponse("unsubscribe.html", {
        "request": request, "active_page": None, "u": u, "t": t, "done": False,
    }, headers=NO_STORE)


@router.post("/email/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(request: Request, u: int = Query(...), t: str = Query(...)):
    """The page's button, and mail apps' one-click unsubscribe, both post here."""
    _check_unsubscribe(u, t)
    await uq.update_user(u, {"email_updates": False})
    return templates.TemplateResponse("unsubscribe.html", {
        "request": request, "active_page": None, "u": u, "t": t, "done": True,
    }, headers=NO_STORE)
