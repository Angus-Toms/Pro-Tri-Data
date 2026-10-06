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
    set_session_cookie,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag

MAX_LINKS_PER_HOUR = 3


def safe_next(next_url):
    # Only same-site relative paths; anything else falls back to home.
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = Query("/")):
    user = await current_user(request)
    if user:
        return RedirectResponse(safe_next(next), status_code=303)
    return templates.TemplateResponse("login.html", {
        "request": request, "active_page": None, "next": safe_next(next),
        "sent": False, "error": None,
    })


@router.post("/auth/request-link", response_class=HTMLResponse)
async def request_link(request: Request,
                       email: str = Form(""),
                       next: str = Form("/"),
                       website: str = Form("")):
    next = safe_next(next)
    ctx = {"request": request, "active_page": None, "next": next}

    # Honeypot: bots that fill the hidden field get a fake success page.
    if website:
        return templates.TemplateResponse("login.html", {**ctx, "sent": True, "error": None})

    email = email.strip()
    if "@" not in email or len(email) > 255:
        return templates.TemplateResponse("login.html",
            {**ctx, "sent": False, "error": "Enter a valid email address."})

    if await uq.count_recent_login_tokens(email) >= MAX_LINKS_PER_HOUR:
        return templates.TemplateResponse("login.html",
            {**ctx, "sent": False,
             "error": "Too many login links requested for this address. Try again in an hour."},
            status_code=429)

    token = new_token()
    await uq.insert_login_token(hash_token(token), email)
    url = f"{SITE_BASE_URL}/auth/verify?token={token}&next={quote(next, safe='')}"
    await run_in_threadpool(emails.send_login_email, email, url)

    return templates.TemplateResponse("login.html", {**ctx, "sent": True, "error": None})


@router.get("/auth/verify")
async def verify(request: Request, token: str = Query(...), next: str = Query("/")):
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
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await uq.delete_session(hash_token(token))
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
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
