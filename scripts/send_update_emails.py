"""Email each opted-in user what's new for the athletes they follow and the
races they like: results from the last two weeks, new start lists with a
predicted finish, and for each liked race every start-list change and then its
results. One email per user per run; items already emailed are skipped, so
reruns are safe.

Liked-race updates go to the bell first, for everyone who liked the race
whether or not they take emails, and the email then picks up the ones it
hasn't sent, so the bell and the inbox always agree.

Run after the weekly build, against the production DATABASE_URL:
    .venv/bin/python -m scripts.send_update_emails
"""

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

from app.routers.router_utils import format_time, format_time_behind, startlist_change
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


async def notify_race_likes():
    """Bell notifications for liked races: each start-list change since the
    last run (the first list out, or entries in or out), and results once.
    A race this script has never seen is only recorded, so the first run
    doesn't announce every list that was already out when it was liked."""
    startlists = queries.get_upcoming_startlists()
    seen = await uq.race_startlists()
    likes = await uq.race_likes()

    startlist_notes = []
    for like in likes:
        rid = like["race_id"]
        if rid not in startlists or rid not in seen:
            continue
        now, before = set(startlists[rid]), seen[rid]
        if not now or now == before:
            continue
        startlist_notes.append((like["user_id"], rid, {
            "entries": len(now), "added": len(now - before),
            "removed": len(before - now), "first": not before}))

    cutoff = date.today() - timedelta(days=RESULT_WINDOW_DAYS)
    finished = {rid: r for rid, r in queries.get_races_brief_bulk({l["race_id"] for l in likes}).items()
                if not r["is_upcoming"] and r["race_date"] >= cutoff}
    podiums = queries.get_race_podiums_bulk(sorted(finished))
    # A like placed after the race is a reaction, not a request for news.
    results_notes = [(l["user_id"], l["race_id"]) for l in likes
                     if podiums.get(l["race_id"]) and l["liked_at"].date() <= finished[l["race_id"]]["race_date"]]

    await uq.record_race_updates(startlist_notes, results_notes, startlists)
    print(f"Race updates: {len(startlist_notes)} start-list and {len(results_notes)} results notifications", flush=True)


async def collect_updates(users):
    """[(user, results, starts, races, notification_ids)] with only items not
    yet emailed. races are liked-race cards built from the bell notifications."""
    athlete_ids = sorted({a for u in users for a in u["athletes"]})

    # --- followed athletes: everything new, in bulk ---
    results = queries.get_recent_results_for_athletes(athlete_ids, days=RESULT_WINDOW_DAYS)
    for r in results:
        r["place"] = ordinal(r["position"]) if r["position"] else None
        r["time"] = format_time(r["overall_s"] or 0)
        r["change"] = round(r["overall_change"]) if r["overall_change"] else 0
        r["date"] = short_date(r["race_date"])

    starts = queries.get_upcoming_races_for_athletes(athlete_ids)
    # Stored predictions: the same rows the race page serves, so the email
    # and the site always agree. Non-elite races have none.
    preds = {rid: queries.get_race_predictions(rid) for rid in {s["race_id"] for s in starts}}
    for s in starts:
        rows = preds[s["race_id"]]
        mine = next((p for p in rows if p["athlete_id"] == s["athlete_id"]), None)
        s["predicted"] = ordinal(mine["predicted_position"]) if mine else None
        s["predicted_gap"] = None
        if mine and mine["overall_s"] and rows[0]["overall_s"]:
            # Leader's predicted time for the leader, otherwise the gap to them.
            s["predicted_gap"] = (format_time(mine["overall_s"]) if mine["predicted_position"] == 1
                                  else format_time_behind(mine["overall_s"] - rows[0]["overall_s"]))
        s["date"] = short_date(s["race_date"])

    # --- liked races: the bell notifications of the last two weeks ---
    since = datetime.now(timezone.utc) - timedelta(days=RESULT_WINDOW_DAYS)
    notes = await uq.race_notifications_since([u["user_id"] for u in users], since)
    all_notes = [n for ns in notes.values() for n in ns]
    briefs = queries.get_races_brief_bulk({n["race_id"] for n in all_notes})
    podiums = queries.get_race_podiums_bulk(sorted({n["race_id"] for n in all_notes if n["kind"] == "results"}))
    for podium in podiums.values():
        # Winner's time in full, then gaps, as the site shows results.
        winner = podium[0]["overall_s"]
        for p in podium:
            p["time"] = format_time(p["overall_s"] or 0) if p is podium[0] else format_time_behind((p["overall_s"] or 0) - (winner or 0))
    # A start-list change also moves the predictions, so the card carries the
    # predicted podium as it stands now.
    predicted = {}
    for rid in {n["race_id"] for n in all_notes if n["kind"] == "startlist"}:
        top = queries.get_race_predictions(rid)[:3]
        predicted[rid] = [{"athlete_id": p["athlete_id"], "position": p["predicted_position"],
                           "time": "" if not p["overall_s"] else
                                   format_time(p["overall_s"]) if p is top[0] else
                                   format_time_behind(p["overall_s"] - top[0]["overall_s"])}
                          for p in top]
    names = queries.get_athletes_brief_bulk({p["athlete_id"] for rows in predicted.values() for p in rows})
    for rows in predicted.values():
        for p in rows:
            p["name"] = names[p["athlete_id"]]["name"]

    photos = queries.get_athletes_brief_bulk(
        {r["athlete_id"] for r in results} | {s["athlete_id"] for s in starts}
        | {p["athlete_id"] for pod in podiums.values() for p in pod})
    photos.update(names)
    for row in (results + starts + [p for pod in podiums.values() for p in pod]
                + [p for rows in predicted.values() for p in rows]):
        a = photos.get(row["athlete_id"])
        row["photo"] = athlete_photo(row["athlete_id"], a and a["profile_img"])

    def race_card(n):
        r = briefs[n["race_id"]]
        card = {"race_id": n["race_id"], "race_title": r["race_title"], "prog_name": r["prog_name"],
                "date": short_date(r["race_date"]), "kind": n["kind"]}
        if n["kind"] == "results":
            return {**card, "summary": None, "rows": podiums[n["race_id"]]}
        change = startlist_change(n["detail"])
        return {**card, "summary": change[0].upper() + change[1:], "rows": predicted[n["race_id"]]}

    out = []
    for u in users:
        follows_a = set(u["athletes"])
        already = await uq.sent_items(u["user_id"])
        mine_results = [r for r in results if r["athlete_id"] in follows_a
                        and f"result:{r['race_id']}:{r['athlete_id']}" not in already]
        mine_starts = [s for s in starts if s["athlete_id"] in follows_a
                       and f"start:{s['race_id']}:{s['athlete_id']}" not in already]
        unsent = [n for n in notes.get(u["user_id"], []) if f"notif:{n['notification_id']}" not in already
                  and n["race_id"] in briefs]
        # Several changes to one start list since the last email collapse to
        # the newest; notes come oldest first, so later ones overwrite.
        latest = {(n["race_id"], n["kind"]): n for n in unsent}
        mine_races = [race_card(n) for n in latest.values()]
        if mine_results or mine_starts or mine_races:
            out.append((u, mine_results, mine_starts, mine_races, [n["notification_id"] for n in unsent]))
    return out


async def main():
    await db.init()
    await notify_race_likes()
    users = await uq.users_for_update_emails()
    sent_count = 0
    for u, results, starts, races, note_ids in await collect_updates(users):
        emails.send_updates_email(u["email"], u["user_id"], results, starts, races)
        await uq.record_sent(u["user_id"],
            [f"result:{r['race_id']}:{r['athlete_id']}" for r in results]
            + [f"start:{s['race_id']}:{s['athlete_id']}" for s in starts]
            + [f"notif:{i}" for i in note_ids])
        sent_count += 1
        time.sleep(SEND_GAP_S)

    print(f"Update emails sent: {sent_count} of {len(users)} opted-in users", flush=True)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
