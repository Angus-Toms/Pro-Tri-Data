"""Share-card PNGs for the race page share dialog.

GET  /share/card  cacheable: solid and transparent cards (JPEG, or PNG when transparent).
POST /share/card  multipart with the user's photo for photo mode; the
                      image never leaves the request.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response

from app.share import cards

router = APIRouter()

MAX_PHOTO_BYTES = 30 * 1024 * 1024   # phone photos run 5-15MB; leave headroom


def _card(race: int, design: str, mode: str, ink: str, athlete: int | None, photo: str | None) -> Response:
    if design not in cards.DESIGNS or mode not in cards.MODES or ink not in cards.INKS:
        raise HTTPException(400, "unknown design, mode or ink")
    if mode == "photo" and photo is None:
        raise HTTPException(400, "photo mode needs a photo")
    subject = cards.DESIGNS[design][2]
    rc = cards.race_context(race)
    if subject == "athlete":
        if athlete is None:
            raise HTTPException(400, "athlete required")
        if not any(f["athlete_id"] == athlete for f in rc["_finishers"]):
            raise HTTPException(404, "athlete did not finish this race")
        ctx = cards.athlete_context(rc, athlete)
        if design == "p4_rating" and ctx["rating"] is None:
            raise HTTPException(404, "no ratings for this race")
    else:
        ctx = {k: v for k, v in rc.items() if not k.startswith("_")}
        if design == "r4_best_perf" and not ctx["best"]:
            raise HTTPException(404, "no ratings for this race")
    data, media_type = cards.render_card(design, ctx, mode, ink, photo)
    return Response(data, media_type=media_type,
                    headers={"Cache-Control": "no-store" if mode == "photo" else "public, max-age=0, s-maxage=86400"})


@router.get("/share/card")
def share_card(race: int, design: str, mode: str = "solid", ink: str = "light", athlete: int | None = None):
    if mode == "photo":
        raise HTTPException(400, "photo mode is POST only")
    return _card(race, design, mode, ink, athlete, None)


# Sync on purpose: Playwright's sync API must stay off the event loop, and
# sync handlers run on the threadpool.
@router.post("/share/card")
def share_card_photo(race: int, design: str, photo: UploadFile, ink: str = "light", athlete: int | None = None):
    raw = photo.file.read()
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo too large")
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(400, "photo must be an image")
    uri = f"data:{photo.content_type};base64," + base64.b64encode(raw).decode()
    return _card(race, design, "photo", ink, athlete, uri)
