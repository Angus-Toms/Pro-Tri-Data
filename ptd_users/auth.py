# Session token helpers and FastAPI dependencies. Pages stay anonymous;
# routes opt in via these dependencies rather than a global middleware.

import hashlib
import secrets

from fastapi import HTTPException, Request

from config import ENV
from ptd_users import queries as uq

SESSION_COOKIE = "ptd_session"
SESSION_MAX_AGE = 90 * 24 * 3600
COOKIE_SECURE = ENV in {"prod", "production"}


def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode()).digest()


def set_session_cookie(response, token):
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True,
        secure=COOKIE_SECURE, samesite="lax", path="/",
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/")


# --- remembered accounts --------------------------------------------------------
# Up to MAX_REMEMBERED one-time tokens, newest first, joined with "." (which
# token_urlsafe never produces). The server only stores their hashes.
REMEMBER_COOKIE = "ptd_remember"
REMEMBER_MAX_AGE = 30 * 24 * 3600
MAX_REMEMBERED = 3


def remembered_tokens(request):
    raw = request.cookies.get(REMEMBER_COOKIE, "")
    return [t for t in raw.split(".") if t][:MAX_REMEMBERED]


def set_remembered_cookie(response, tokens):
    if not tokens:
        response.delete_cookie(REMEMBER_COOKIE, path="/")
        return
    response.set_cookie(
        REMEMBER_COOKIE, ".".join(tokens[:MAX_REMEMBERED]), max_age=REMEMBER_MAX_AGE,
        httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/",
    )


async def current_user(request: Request):
    """User dict for the request's session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await uq.get_session_user(hash_token(token))


async def require_user(request: Request):
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


async def require_admin(request: Request):
    # 404 rather than 403 so admin routes are invisible to non-admins.
    user = await current_user(request)
    if user is None or not user["is_admin"]:
        raise HTTPException(status_code=404, detail="Not Found")
    return user
