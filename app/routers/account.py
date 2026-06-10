from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL, flag
from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import clear_session_cookie, current_user, require_user

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag

DELETE_PHRASE = "delete my account"
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
