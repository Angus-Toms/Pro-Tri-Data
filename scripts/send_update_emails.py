"""Email each opted-in user what's new for the athletes and races they follow:
results from the last two weeks, new start lists with a predicted finish, and
results of followed races. One email per user per run; items already emailed
are skipped, so reruns are safe.

Run after the weekly build, against the production DATABASE_URL:
    .venv/bin/python -m scripts.send_update_emails
"""

import asyncio
import time
from datetime import date, timedelta

from app.routers.router_utils import format_time, format_time_behind
from app.routers.upcoming_page import _build_podium
from ptd_data import queries
from ptd_users import db, emails
from ptd_users import queries as uq

RESULT_WINDOW_DAYS = 14
# Email apps can't reach localhost, so images always come from the live CDN.
EMAIL_STATIC = "https://www.static.protridata.com/"
SEND_GAP_S = 0.6  # Resend allows 2 requests a second


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def athlete_photo(athlete_id, profile_img):
    if profile_img:
        return f"{EMAIL_STATIC}athlete_imgs/128/{athlete_id}.webp"
    return f"{EMAIL_STATIC}imgs/default_user_64.webp"


def short_date(d):
    return f"{d.day} {d:%b}"


async def collect_updates(users):
    """[(user, results, starts, races)] with only items not yet emailed."""
    athlete_ids = sorted({a for u in users for a in u["athletes"]})
    race_ids = sorted({r for u in users for r in u["races"]})

    # --- everything new across all follows, in bulk ---
    results = queries.get_recent_results_for_athletes(athlete_ids, days=RESULT_WINDOW_DAYS)
    for r in results:
        r["place"] = ordinal(r["position"]) if r["position"] else None
        r["time"] = format_time(r["overall_s"] or 0)
        r["change"] = round(r["overall_change"]) if r["overall_change"] else 0
        r["date"] = short_date(r["race_date"])

    starts = queries.get_upcoming_races_for_athletes(athlete_ids)
    entries = queries.get_upcoming_race_entries_bulk(sorted({s["race_id"] for s in starts}))
    models = queries.get_prediction_models()
    for s in starts:
        # Same ordering and time model as the site's predicted podium.
        field = sorted(entries.get(s["race_id"], []), key=lambda e: e["overall_rating"] or 0, reverse=True)
        rank = next((i + 1 for i, e in enumerate(field) if e["athlete_id"] == s["athlete_id"]), None)
        rated = rank and field[rank - 1]["overall_rating"]
        s["predicted"] = ordinal(rank) if rated else None
        s["predicted_gap"] = None
        if rated:
            # Leader's predicted time for the leader, otherwise the gap to them.
            pair = [field[0]] if rank == 1 else [field[0], field[rank - 1]]
            pred = _build_podium(pair, s["gender"], s["event_spec_ids"], models)[-1]
            s["predicted_gap"] = pred["time"] if rank == 1 else pred["gap"]
        s["date"] = short_date(s["race_date"])

    cutoff = date.today() - timedelta(days=RESULT_WINDOW_DAYS)
    finished = {rid: r for rid, r in queries.get_races_brief_bulk(race_ids).items()
                if not r["is_upcoming"] and r["race_date"] >= cutoff}
    podiums = queries.get_race_podiums_bulk(sorted(finished))
    for podium in podiums.values():
        # Winner's time in full, then gaps, as the site shows results.
        winner = podium[0]["overall_s"]
        for p in podium:
            p["time"] = format_time(p["overall_s"] or 0) if p is podium[0] else format_time_behind((p["overall_s"] or 0) - (winner or 0))
    races = {rid: {**r, "date": short_date(r["race_date"]), "podium": podiums[rid]}
             for rid, r in finished.items() if podiums.get(rid)}

    photos = queries.get_athletes_brief_bulk(
        {r["athlete_id"] for r in results} | {s["athlete_id"] for s in starts}
        | {p["athlete_id"] for pod in podiums.values() for p in pod})
    for row in results + starts + [p for pod in podiums.values() for p in pod]:
        a = photos.get(row["athlete_id"])
        row["photo"] = athlete_photo(row["athlete_id"], a and a["profile_img"])

    out = []
    for u in users:
        follows_a, follows_r = set(u["athletes"]), set(u["races"])
        already = await uq.sent_items(u["user_id"])
        mine_results = [r for r in results if r["athlete_id"] in follows_a
                        and f"result:{r['race_id']}:{r['athlete_id']}" not in already]
        mine_starts = [s for s in starts if s["athlete_id"] in follows_a
                       and f"start:{s['race_id']}:{s['athlete_id']}" not in already]
        mine_races = [races[rid] for rid in sorted(follows_r & races.keys())
                      if f"race:{rid}" not in already]
        if mine_results or mine_starts or mine_races:
            out.append((u, mine_results, mine_starts, mine_races))
    return out


async def main():
    await db.init()
    users = await uq.users_for_update_emails()
    sent_count = 0
    for u, results, starts, races in await collect_updates(users):
        emails.send_updates_email(u["email"], u["user_id"], results, starts, races)
        await uq.record_sent(u["user_id"],
            [f"result:{r['race_id']}:{r['athlete_id']}" for r in results]
            + [f"start:{s['race_id']}:{s['athlete_id']}" for s in starts]
            + [f"race:{r['race_id']}" for r in races])
        sent_count += 1
        time.sleep(SEND_GAP_S)

    print(f"Update emails sent: {sent_count} of {len(users)} opted-in users with follows", flush=True)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
