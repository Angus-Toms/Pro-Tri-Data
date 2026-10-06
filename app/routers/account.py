import io

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError

from config import ASSET_VERSION, STATIC_BASE_URL, flag
from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import clear_session_cookie, current_user, require_user
from app.routers.router_utils import user_avatar

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["user_avatar"]   = user_avatar

DELETE_PHRASE = "delete my account"
MAX_AVATAR_UPLOAD = 8 * 1024 * 1024
AVATAR_SIZE = 128
NO_STORE = {"Cache-Control": "no-store"}


async def _render_account(request, user, saved=False, error=None, status_code=200):
    follows = await uq.get_follows(user["user_id"])
    athletes_by_id = queries.get_athletes_brief_bulk(follows["athletes"])
    races_by_id    = queries.get_races_brief_bulk(follows["races"])
    return templates.TemplateResponse("account.html", {
        "request":     request,
        "active_page": "account",
        "user":        user,
        "followed_athletes": [athletes_by_id[a] for a in follows["athletes"] if a in athletes_by_id],
        "followed_races":    [races_by_id[r] for r in follows["races"] if r in races_by_id],
        "countries":   queries.get_nationality_options(),
        "saved":       saved,
        "error":       error,
        "delete_phrase": DELETE_PHRASE,
    }, status_code=status_code, headers=NO_STORE)


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, saved: bool = False):
    user = await current_user(request)
    if user is None:
        return RedirectResponse("/login?next=/account", status_code=303)
    return await _render_account(request, user, saved=saved)


@router.post("/account/update")
async def account_update(request: Request,
                         display_name: str = Form(""),
                         country: str = Form(""),
                         email_digest: bool = Form(False)):
    user = await require_user(request)
    display_name = display_name.strip()
    if not 2 <= len(display_name) <= 40:
        return await _render_account(request, user, error="Display name must be 2 to 40 characters.", status_code=400)
    country = country.strip().upper() or None
    if country is not None and country not in {a3 for _, a3 in queries.get_nationality_options()}:
        return await _render_account(request, user, error="Unknown country.", status_code=400)
    await uq.update_user(user["user_id"], display_name, country, email_digest)
    return RedirectResponse("/account?saved=1", status_code=303)


@router.post("/account/unfollow")
async def account_unfollow(request: Request,
                           kind: str = Form(...),
                           ref_id: int = Form(...)):
    user = await require_user(request)
    if kind not in ("athlete", "race"):
        raise HTTPException(status_code=400, detail="Invalid follow kind")
    # Toggle is safe here: the account page only lists existing follows.
    await uq.toggle_follow(user["user_id"], kind, ref_id)
    return RedirectResponse("/account", status_code=303)


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
    return RedirectResponse("/account?saved=1", status_code=303)


@router.post("/account/avatar/remove")
async def account_avatar_remove(request: Request):
    user = await require_user(request)
    await uq.set_avatar(user["user_id"], None)
    return RedirectResponse("/account?saved=1", status_code=303)


@router.get("/avatar/{user_id}.webp")
async def avatar(user_id: int):
    data = await uq.get_avatar(user_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No photo")
    # The URL carries ?v=avatar_version, so a new upload is a new URL.
    return Response(data, media_type="image/webp",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
