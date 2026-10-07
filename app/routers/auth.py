from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from config import ASSET_VERSION, SITE_BASE_URL, STATIC_BASE_URL, flag
from ptd_users import emails
from ptd_users import queries as uq
from ptd_users.auth import (
    SESSION_COOKIE, clear_session_cookie, current_user, hash_token, new_token,
    remembered_tokens, set_remembered_cookie, set_session_cookie,
)
from app.routers.router_utils import user_avatar

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["user_avatar"]   = user_avatar

MAX_LINKS_PER_HOUR = 3


def safe_next(next_url):
    # Only same-site relative paths; anything else falls back to home.
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


def mask_email(email):
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}"


async def remembered_accounts(request):
    """Accounts this browser can continue as, for the login page."""
    accounts = await uq.get_remembered([hash_token(t) for t in remembered_tokens(request)])
    for a in accounts:
        a["masked_email"] = mask_email(a["email"])
    return accounts


async def render_login(request, next, sent=False, error=None, status_code=200):
    return templates.TemplateResponse("login.html", {
        "request": request, "active_page": None, "next": next,
        "sent": sent, "error": error,
        "accounts": [] if sent else await remembered_accounts(request),
    }, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = Query("/")):
    user = await current_user(request)
    if user:
        return RedirectResponse(safe_next(next), status_code=303)
    return await render_login(request, safe_next(next))


@router.post("/auth/request-link", response_class=HTMLResponse)
async def request_link(request: Request,
                       email: str = Form(""),
                       next: str = Form("/"),
                       website: str = Form("")):
    next = safe_next(next)

    # Honeypot: bots that fill the hidden field get a fake success page.
    if website:
        return await render_login(request, next, sent=True)

    email = email.strip()
    if "@" not in email or len(email) > 255:
        return await render_login(request, next, error="Enter a valid email address.")

    if await uq.count_recent_login_tokens(email) >= MAX_LINKS_PER_HOUR:
        return await render_login(request, next, status_code=429,
            error="Too many login links requested for this address. Try again in an hour.")

    token = new_token()
    await uq.insert_login_token(hash_token(token), email)
    url = f"{SITE_BASE_URL}/auth/verify?token={token}&next={quote(next, safe='')}"
    await run_in_threadpool(emails.send_login_email, email, url)

    return await render_login(request, next, sent=True)


@router.get("/auth/verify", response_class=HTMLResponse)
async def verify_page(request: Request, token: str = Query(...), next: str = Query("/")):
    """The emailed link lands here. It only shows a button: email security
    scanners open links but don't submit forms, so they can't use up the
    single-use token before the person clicks."""
    email = await uq.peek_login_token(hash_token(token))
    if email is None:
        raise HTTPException(status_code=400, detail="This login link is invalid or has expired. Request a new one from the login page.")
    return templates.TemplateResponse("login_confirm.html", {
        "request": request, "active_page": None, "token": token, "next": safe_next(next),
        "masked_email": mask_email(email),
        "is_new": await uq.get_user_by_email(email) is None,
    }, headers={"Cache-Control": "no-store"})


@router.post("/auth/verify")
async def verify(request: Request, token: str = Form(...), next: str = Form("/")):
    next = safe_next(next)
    email = await uq.take_login_token(hash_token(token))
    if email is None:
        raise HTTPException(status_code=400, detail="This login link is invalid or has expired. Request a new one from the login page.")

    user = await uq.get_user_by_email(email)
    is_new = user is None
    if is_new:
        # Placeholder name from the email local part; the pick-name step that
        # follows replaces it before the user lands anywhere else.
        user = await uq.create_user(email, email.split("@")[0][:40])

    session_token = new_token()
    await uq.create_session(hash_token(session_token), user["user_id"])

    if is_new:
        response = templates.TemplateResponse("pick_name.html", {
            "request": request, "active_page": None, "next": next,
            "display_name": user["display_name"], "error": None,
        })
    else:
        response = RedirectResponse(next, status_code=303)
    set_session_cookie(response, session_token)
    return response


@router.post("/auth/display-name")
async def pick_display_name(request: Request,
                            display_name: str = Form(""),
                            next: str = Form("/")):
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    next = safe_next(next)
    display_name = display_name.strip()
    if not 2 <= len(display_name) <= 40:
        return templates.TemplateResponse("pick_name.html", {
            "request": request, "active_page": None, "next": next,
            "display_name": display_name,
            "error": "Display name must be 2 to 40 characters.",
        })
    await uq.set_display_name(user["user_id"], display_name)
    return RedirectResponse(next, status_code=303)


@router.post("/auth/logout")
async def logout(request: Request):
    user = await current_user(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await uq.delete_session(hash_token(token))
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    if user:
        # Remember this account on this browser so the login page can offer
        # "continue as". Any older token for the same account is replaced.
        tokens, live = await _live_tokens(request)
        stale = [t for t in tokens if live.get(hash_token(t)) == user["user_id"]]
        await uq.delete_remembered([hash_token(t) for t in stale])
        fresh = new_token()
        await uq.create_remembered(hash_token(fresh), user["user_id"])
        set_remembered_cookie(response, [fresh] + [t for t in tokens if hash_token(t) in live and t not in stale])
    return response


async def _live_tokens(request):
    """(the browser's remembered tokens, {token hash: user_id} for the live ones)."""
    tokens = remembered_tokens(request)
    accounts = await uq.get_remembered([hash_token(t) for t in tokens])
    return tokens, {bytes(a["token_hash"]): a["user_id"] for a in accounts}


def _token_for(tokens, live, user_id):
    return next((t for t in tokens if live.get(hash_token(t)) == user_id), None)


@router.post("/auth/resume")
async def resume(request: Request, user_id: int = Form(...), next: str = Form("/")):
    """Continue as a remembered account: consume its token and start a session."""
    tokens, live = await _live_tokens(request)
    token = _token_for(tokens, live, user_id)
    if token is None or await uq.take_remembered(hash_token(token)) != user_id:
        return await render_login(request, safe_next(next), status_code=400,
            error="That saved login has expired. Enter your email for a new link.")
    session_token = new_token()
    await uq.create_session(hash_token(session_token), user_id)
    response = RedirectResponse(safe_next(next), status_code=303)
    set_session_cookie(response, session_token)
    set_remembered_cookie(response, [t for t in tokens if t != token and hash_token(t) in live])
    return response


@router.post("/auth/forget")
async def forget(request: Request, user_id: int = Form(...), next: str = Form("/")):
    """Remove a remembered account from this browser."""
    tokens, live = await _live_tokens(request)
    token = _token_for(tokens, live, user_id)
    if token:
        await uq.delete_remembered([hash_token(token)])
    response = RedirectResponse(f"/login?next={quote(safe_next(next), safe='')}", status_code=303)
    set_remembered_cookie(response, [t for t in tokens if t != token and hash_token(t) in live])
    return response


@router.get("/me")
async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "Not logged in"}, status_code=401,
                            headers={"Cache-Control": "no-store"})
    follows = await uq.get_follows(user["user_id"])
    return JSONResponse({
        "user_id":      user["user_id"],
        "display_name": user["display_name"],
        "country":      user["country"],
        "is_admin":     user["is_admin"],
        "follows":      follows,
        "unread":       await uq.unread_notification_count(user["user_id"]),
    }, headers={"Cache-Control": "no-store"})
