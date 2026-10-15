from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.routers.router_utils import avatar_tone
from ptd_data import queries
from ptd_users import queries as uq

router = APIRouter()


def format_race_results(res):
    """Dates as display strings and an upcoming flag on queries.search_races
    output, the shape header.js's race and series rows render."""
    today = date.today()
    for e in res["events"] + [e for g in res["groups"] for e in g["editions_list"]]:
        e["upcoming"] = e["date"] > today
        e["date"] = e["date"].strftime("%-d %b %Y")
    for x in res["groups"] + res["series"]:
        x["next_date"] = x["next_date"].strftime("%-d %b %Y") if x["next_date"] else None
    return res

_EMPTY = {"athletes": [], "athletes_total": 0, "groups": [], "groups_total": 0,
          "events": [], "events_total": 0, "series": [], "users": [], "users_total": 0}


@router.get("/search")
async def global_search(q: str = Query("")):
    """JSON behind the header search modal (static/js/header.js)."""
    q = q.strip()
    if len(q) < 2:
        return JSONResponse(_EMPTY)
    # The race data is DuckDB (blocking), so it runs in a thread; site users
    # come from Postgres.
    res = await run_in_threadpool(queries.global_search, q)
    users, res["users_total"] = await uq.search_users(q)
    res["users"] = [{"user_id": u["user_id"], "name": u["display_name"], "country_alpha3": u["country"],
                     "club": u["club"], "followers": u["followers"], "comments": u["comments"],
                     "avatar_version": u["avatar_version"], "tone": avatar_tone(u["user_id"])} for u in users]
    today = date.today()

    for a in res["athletes"]:
        yob = a.pop("year_of_birth")
        a["age"] = today.year - yob if yob else None
    format_race_results(res)
    # Edge-cached like every page, but without the default
    # stale-while-revalidate: browsers honour it, and a day-old response
    # shape would break the freshly deployed header.js. Ten minutes, not an
    # hour, now that it lists people, who rename themselves and sign up.
    return JSONResponse(res, headers={"Cache-Control": "public, max-age=0, s-maxage=600"})
