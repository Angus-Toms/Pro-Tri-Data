from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ASSET_VERSION, STATIC_BASE_URL, flag
from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import require_admin, require_user
from app.routers.router_utils import rel_time

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["rel_time"]      = rel_time

MIN_ACCOUNT_AGE = timedelta(hours=1)
MIN_COMMENT_GAP = timedelta(seconds=30)
MAX_COMMENTS_PER_DAY = 20
NO_STORE = {"Cache-Control": "no-store"}


async def _render_comments(request, race_id, offset=0, error=None, status_code=200):
    comments, has_more = await uq.list_comments(race_id, offset)
    return templates.TemplateResponse("partials/comments.html", {
        "request":  request,
        "race_id":  race_id,
        "comments": comments,
        "offset":   offset,
        "has_more": has_more,
        "page_size": uq.COMMENTS_PAGE_SIZE,
        "error":    error,
    }, status_code=status_code, headers=NO_STORE)


def _require_past_race(race_id):
    # Comments live on completed races only; upcoming races have no race row.
    if queries.get_race_info(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race {race_id} not found")


@router.get("/race/{race_id}/comments", response_class=HTMLResponse)
async def comments_partial(request: Request, race_id: int, offset: int = Query(0, ge=0)):
    _require_past_race(race_id)
    return await _render_comments(request, race_id, offset)


@router.post("/race/{race_id}/comments", response_class=HTMLResponse)
async def post_comment(request: Request, race_id: int, body: str = Form("")):
    user = await require_user(request)
    _require_past_race(race_id)

    if user["is_banned"]:
        return await _render_comments(request, race_id, error="Your account cannot comment.", status_code=403)
    if datetime.now(timezone.utc) - user["created_at"] < MIN_ACCOUNT_AGE:
        return await _render_comments(request, race_id,
            error="Accounts must be at least an hour old before commenting.", status_code=403)

    body = body.strip()
    if not 1 <= len(body) <= 2000:
        return await _render_comments(request, race_id,
            error="Comments must be 1 to 2000 characters.", status_code=400)

    last_at, day_count = await uq.comment_rate_state(user["user_id"])
    if last_at is not None and datetime.now(timezone.utc) - last_at < MIN_COMMENT_GAP:
        return await _render_comments(request, race_id,
            error="You are commenting too quickly. Wait 30 seconds.", status_code=429)
    if day_count >= MAX_COMMENTS_PER_DAY:
        return await _render_comments(request, race_id,
            error="Daily comment limit reached.", status_code=429)

    await uq.insert_comment(race_id, user["user_id"], body)
    return await _render_comments(request, race_id)


@router.post("/comments/{comment_id}/delete")
async def delete_comment(request: Request, comment_id: int, next: str = Form(None)):
    user = await require_user(request)
    comment = await uq.get_comment(comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment["user_id"] != user["user_id"] and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Not your comment")
    await uq.delete_comment(comment_id)
    if next == "/admin/moderation":
        return RedirectResponse("/admin/moderation", status_code=303)
    return JSONResponse({"ok": True}, headers=NO_STORE)


@router.post("/comments/{comment_id}/report")
async def report_comment(request: Request, comment_id: int):
    user = await require_user(request)
    if await uq.get_comment(comment_id) is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    count = await uq.report_comment(comment_id, user["user_id"])
    return JSONResponse({"ok": True, "reports": count}, headers=NO_STORE)


@router.post("/comments/{comment_id}/unhide")
async def unhide_comment(request: Request, comment_id: int):
    await require_admin(request)
    await uq.unhide_comment(comment_id)
    return RedirectResponse("/admin/moderation", status_code=303)


@router.get("/admin/moderation", response_class=HTMLResponse)
async def moderation_queue(request: Request):
    await require_admin(request)
    queue = await uq.moderation_queue()
    races = queries.get_races_brief_bulk([c["race_id"] for c in queue])
    for c in queue:
        race = races.get(c["race_id"])
        c["race_title"] = race["race_title"] if race else f"Race {c['race_id']}"
        c["when"] = rel_time(c["created_at"])
    return templates.TemplateResponse("admin_moderation.html", {
        "request":     request,
        "active_page": None,
        "queue":       queue,
    }, headers=NO_STORE)
