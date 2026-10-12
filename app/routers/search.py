from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ptd_data import queries

router = APIRouter()

_EMPTY = {"athletes": [], "athletes_total": 0, "groups": [], "groups_total": 0,
          "events": [], "events_total": 0, "series": []}


@router.get("/search")
def global_search(q: str = Query("")):
    """JSON behind the header search modal (static/js/header.js)."""
    q = q.strip()
    if len(q) < 2:
        return JSONResponse(_EMPTY)
    res = queries.global_search(q)
    today = date.today()

    for a in res["athletes"]:
        yob = a.pop("year_of_birth")
        a["age"] = today.year - yob if yob else None
    for e in res["events"] + [e for g in res["groups"] for e in g["editions_list"]]:
        e["upcoming"] = e["date"] > today
        e["date"] = e["date"].strftime("%-d %b %Y")
    for x in res["groups"] + res["series"]:
        x["next_date"] = x["next_date"].strftime("%-d %b %Y") if x["next_date"] else None
    # Edge-cached like every page, but without the default
    # stale-while-revalidate: browsers honour it, and a day-old response
    # shape would break the freshly deployed header.js.
    return JSONResponse(res, headers={"Cache-Control": "public, max-age=0, s-maxage=3600"})
