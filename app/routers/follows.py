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
    else:
        raise HTTPException(status_code=400, detail="kind must be 'athlete' or 'race'")
    if not exists:
        raise HTTPException(status_code=404, detail=f"{body.kind} {body.ref_id} not found")
    following = await uq.toggle_follow(user["user_id"], body.kind, body.ref_id)
    return JSONResponse({"following": following}, headers={"Cache-Control": "no-store"})
