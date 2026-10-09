from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ptd_data import queries
from ptd_users import queries as uq
from ptd_users.auth import require_user

router = APIRouter()


class FollowBody(BaseModel):
    kind: str
    ref_id: int


@router.post("/follow")
async def follow_toggle(request: Request, body: FollowBody):
    user = await require_user(request)
    if body.kind == "athlete":
        exists = bool(queries.get_athletes_brief_bulk([body.ref_id]))
    elif body.kind == "race":
        exists = bool(queries.get_races_brief_bulk([body.ref_id]))
    elif body.kind == "user":
        if body.ref_id == user["user_id"]:
            raise HTTPException(status_code=400, detail="You can't follow yourself")
        exists = await uq.get_public_profile(body.ref_id) is not None
    else:
        raise HTTPException(status_code=400, detail="kind must be 'athlete', 'race' or 'user'")
    if not exists:
        raise HTTPException(status_code=404, detail=f"{body.kind} {body.ref_id} not found")
    following = await uq.toggle_follow(user["user_id"], body.kind, body.ref_id)
    # The count lets follower figures on the page update without a reload.
    return JSONResponse({"following": following,
                         "followers": await uq.follower_count(body.kind, body.ref_id)},
                        headers={"Cache-Control": "no-store"})


@router.get("/race/{race_id}/counts")
async def race_counts(race_id: int):
    """Like and comment counts for the race hero. Fetched client-side so the
    edge-cached race HTML never holds a stale figure."""
    return JSONResponse({"likes": await uq.follower_count("race", race_id),
                         "comments": (await uq.comment_counts([race_id])).get(race_id, 0)},
                        headers={"Cache-Control": "no-store"})
