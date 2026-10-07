import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from pydantic import BaseModel

from config import ASSET_VERSION, ENV, STATIC_BASE_URL
from app.display_helpers import flag
from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import current_user, require_admin, require_user
from app.routers.router_utils import athlete_img_url, rel_time, user_avatar

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL
templates.env.globals["ASSET_VERSION"] = ASSET_VERSION
templates.env.globals["flag"]          = flag
templates.env.globals["rel_time"]      = rel_time
templates.env.globals["user_avatar"]   = user_avatar

MIN_ACCOUNT_AGE = timedelta(hours=1)
MIN_COMMENT_GAP = timedelta(seconds=30)
MAX_COMMENTS_PER_DAY = 20
MAX_TAGS = 10
# One reaction per person per comment. Thumbs up/down are always shown; the tri
# reactions appear once used and are added from a picker. Keys must match the comment_reactions check constraint.
TRI_REACTIONS = [("rapid", "Rapid"), ("paincave", "Pain cave"), ("podium", "Podium")]
REACTION_KINDS = {"up", "down"} | {k for k, _ in TRI_REACTIONS}
NO_STORE = {"Cache-Control": "no-store"}

# --- tags -------------------------------------------------------------------
# Tagged athletes, races and users are stored inline as @[Label](kind:id). The
# label is rewritten to the canonical name at write time, so a stored token is
# always a real id. User chips show the user's current name at render time.
TAG_RE = re.compile(r"@\[([^\]\n]{1,120})\]\((athlete|race|user):(\d+)\)")


def race_tag_label(race):
    return f"{race['race_title']} ({race['prog_name']})"


async def canonicalise_tags(body):
    """Validate every tag against its store and rewrite its label. Returns
    (body, tagged user ids). Unknown ids are a 400."""
    found = TAG_RE.findall(body)
    ids = {kind: {int(i) for _, k, i in found if k == kind} for kind in ("athlete", "race", "user")}
    if sum(len(v) for v in ids.values()) > MAX_TAGS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_TAGS} tags per comment")
    refs = {
        "athlete": queries.get_athletes_brief_bulk(ids["athlete"]),
        "race":    queries.get_races_brief_bulk(ids["race"]),
        "user":    await uq.get_users_brief(ids["user"]),
    }

    def repl(m):
        kind, ref_id = m.group(2), int(m.group(3))
        ref = refs[kind].get(ref_id)
        if ref is None:
            raise HTTPException(status_code=400, detail=f"Tagged {kind} {ref_id} not found")
        label = {"athlete": lambda: ref["name"], "race": lambda: race_tag_label(ref),
                 "user": lambda: ref["display_name"]}[kind]()
        return f"@[{label}]({kind}:{ref_id})"

    return TAG_RE.sub(repl, body), sorted(ids["user"])


AT_ICON = Markup(
    '<svg class="mention-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/></svg>'
)

RACE_ICON = Markup(
    '<svg class="mention-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M4 21V4"/><path d="M4 4h12l-2 4 2 4H4"/></svg>'
)


async def tag_refs(bodies):
    """Athlete flags and current user names for every tag across a set of
    bodies. One bulk query per store per render."""
    found = [(k, int(i)) for b in bodies for _, k, i in TAG_RE.findall(b)]
    return {
        "athlete": queries.get_athletes_brief_bulk({i for k, i in found if k == "athlete"}),
        "user":    await uq.get_users_brief({i for k, i in found if k == "user"}),
    }


def render_comment_body(body, refs):
    """Escaped HTML with tags turned into chips that link to the athlete, race
    or user profile. A tag of a deleted account stays as plain text."""
    out, pos = [], 0
    for m in TAG_RE.finditer(body):
        label, kind, ref_id = m.groups()
        out.append(escape(body[pos:m.start()]))
        if kind == "user":
            # Current name, so renames and deleted accounts are reflected.
            u = refs["user"].get(int(ref_id))
            if u:
                out.append(Markup(f'<a class="mention mention-user" href="/user/{ref_id}">{AT_ICON}'
                                  f'<span>{escape(u["display_name"])}</span></a>'))
            else:
                out.append(Markup(f'<span class="mention mention-user">{AT_ICON}<span>deleted user</span></span>'))
        elif kind == "athlete":
            # An athlete can vanish from a weekly rebuild; the chip then shows
            # the default photo and no flag.
            a = refs["athlete"].get(int(ref_id))
            photo = athlete_img_url(ref_id, a and a["profile_img"])
            tail = flag(a["country_alpha3"], a["country_full"], "mention-flag") if a else ""
            out.append(Markup(f'<a class="mention mention-athlete" href="/athlete/{ref_id}">'
                              f'<img class="mention-photo" src="{photo}" alt="" loading="lazy">'
                              f'<span>{escape(label)}</span>{tail}</a>'))
        else:
            out.append(Markup(f'<a class="mention mention-race" href="/race/{ref_id}">'
                              f'{RACE_ICON}<span>{escape(label)}</span></a>'))
        pos = m.end()
    out.append(escape(body[pos:]))
    return Markup("".join(out))


templates.env.globals["render_comment_body"] = render_comment_body


async def _render_comments(request, race_id, offset=0, error=None, status_code=200):
    user = await current_user(request)
    threads, has_more = await uq.list_comments(race_id, offset, user["user_id"] if user else None)
    bodies = [c["body"] for c in threads] + [r["body"] for c in threads for r in c["replies"]]
    return templates.TemplateResponse("partials/comments.html", {
        "request":  request,
        "race_id":  race_id,
        "comments": threads,
        "offset":   offset,
        "has_more": has_more,
        "page_size": uq.COMMENTS_PAGE_SIZE,
        "error":    error,
        "tri_reactions": TRI_REACTIONS,
        "mention_refs": await tag_refs(bodies),
    }, status_code=status_code, headers=NO_STORE)


def _require_past_race(race_id):
    # Comments live on completed races only; upcoming races have no race row.
    if queries.get_race_info(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race {race_id} not found")


async def _live_comment(comment_id):
    """A comment that can still be replied to, reacted to or reported."""
    comment = await uq.get_comment(comment_id)
    if comment is None or comment["hidden_at"] is not None or comment["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("/race/{race_id}/comments", response_class=HTMLResponse)
async def comments_partial(request: Request, race_id: int, offset: int = Query(0, ge=0)):
    _require_past_race(race_id)
    return await _render_comments(request, race_id, offset)


@router.post("/race/{race_id}/comments", response_class=HTMLResponse)
async def post_comment(request: Request, race_id: int, body: str = Form(""),
                       parent_id: int | None = Form(None)):
    user = await require_user(request)
    _require_past_race(race_id)
    parent = None
    if parent_id is not None:
        parent = await _live_comment(parent_id)
        if parent["race_id"] != race_id:
            raise HTTPException(status_code=400, detail="Reply must be on the same race")

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
    # Rate limits are off in local dev so threads can be built quickly; prod keeps them.
    if ENV == "local":
        last_at, day_count = None, 0
    if last_at is not None and datetime.now(timezone.utc) - last_at < MIN_COMMENT_GAP:
        return await _render_comments(request, race_id,
            error="You are commenting too quickly. Wait 30 seconds.", status_code=429)
    if day_count >= MAX_COMMENTS_PER_DAY:
        return await _render_comments(request, race_id,
            error="Daily comment limit reached.", status_code=429)

    body, tagged_users = await canonicalise_tags(body)
    await uq.insert_comment(race_id, user["user_id"], body, parent, tagged_users)
    return await _render_comments(request, race_id)


@router.get("/comments/mention-search")
async def mention_search(q: str = Query(""), race_id: int = Query(...)):
    """Suggestions for the @ picker: athletes, races, and people who have
    commented on this race."""
    q = q.strip()
    if len(q) < 2:
        return JSONResponse({"users": [], "athletes": [], "races": []})
    users    = await uq.search_race_commenters(race_id, q)
    athletes = queries.search_athletes(q)[:5]
    races    = queries.search_races_for_mention(q)
    return JSONResponse({
        "users":    [{"id": u["user_id"], "label": u["display_name"],
                      "country": u["country"], "sub": "Commenter",
                      "avatar": str(user_avatar(u["user_id"], u["display_name"], u["avatar_version"], "xs"))}
                     for u in users],
        "athletes": [{"id": a["athlete_id"], "label": a["name"],
                      "country": a["country_alpha3"], "sub": a["country_full"],
                      "img": athlete_img_url(a["athlete_id"], a["profile_img"])}
                     for a in athletes],
        "races":    [{"id": r["race_id"], "label": race_tag_label(r),
                      "sub": r["race_date"].strftime("%d %b %Y")}
                     for r in races],
    }, headers={"Cache-Control": "private, max-age=60"})


@router.post("/comments/{comment_id}/delete")
async def delete_comment(request: Request, comment_id: int, next: str = Form(None)):
    user = await require_user(request)
    comment = await uq.get_comment(comment_id)
    if comment is None or comment["deleted_at"] is not None:
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
    await _live_comment(comment_id)
    count = await uq.report_comment(comment_id, user["user_id"])
    return JSONResponse({"ok": True, "reports": count}, headers=NO_STORE)


class ReactBody(BaseModel):
    kind: str


@router.post("/comments/{comment_id}/react")
async def react(request: Request, comment_id: int, body: ReactBody):
    user = await require_user(request)
    if body.kind not in REACTION_KINDS:
        raise HTTPException(status_code=400, detail="Unknown reaction")
    if user["is_banned"]:
        raise HTTPException(status_code=403, detail="Your account cannot react")
    await _live_comment(comment_id)
    state = await uq.toggle_reaction(comment_id, user["user_id"], body.kind)
    return JSONResponse(state, headers=NO_STORE)


# --- notifications ------------------------------------------------------------

@router.get("/notifications")
async def notifications(request: Request):
    user = await require_user(request)
    notes = await uq.list_notifications(user["user_id"])
    races = queries.get_races_brief_bulk({n["race_id"] for n in notes})
    return JSONResponse([{
        "kind":   n["kind"],
        "actor":  n["display_name"],
        "race":   races[n["race_id"]]["race_title"] if n["race_id"] in races else None,
        "url":    f"/race/{n['race_id']}#comment-{n['comment_id']}",
        "when":   rel_time(n["created_at"]),
        "unread": n["read_at"] is None,
    } for n in notes], headers=NO_STORE)


@router.post("/notifications/read")
async def notifications_read(request: Request):
    user = await require_user(request)
    await uq.mark_notifications_read(user["user_id"])
    return JSONResponse({"ok": True}, headers=NO_STORE)


# --- moderation -----------------------------------------------------------------

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
        "mention_refs": await tag_refs([c["body"] for c in queue]),
    }, headers=NO_STORE)
