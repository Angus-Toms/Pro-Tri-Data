"""Scan for races that should have been posted and publish them.

Run by the nightly workflow after the build, before the DB ships, since
social_posts lives in the DB.
Idempotent: already-posted races are skipped via the social_posts table.

Two windows: upcoming elite races starting in the next 3 days (pre-race)
and finished elite races from the last 7 days (post-race). Elite-only
filter applied at the SQL level so we don't post Junior/U23/Youth/AG.
"""
from __future__ import annotations

from datetime import date, timedelta

from ptd_data import db
from social.runner import post_race_pack, pre_race_pack

PRE_DAYS  = 3
POST_DAYS = 7

_ELITE_PROG_NAMES_SQL = "('Elite Men','Elite Women','Pro Men','Pro Women')"


def _upcoming_eligible(conn) -> list[tuple[int, str, date]]:
    today  = date.today()
    cutoff = today + timedelta(days=PRE_DAYS)
    # Only races still genuinely ahead of us get a "predicted podium" post.
    # If a run is missed and a race has since been run + ingested into
    # `races`, it must NOT get a stale pre-race prediction - it should fall
    # through to the post-race recap only. The date lower bound drops races
    # whose date has passed; the NOT IN guard drops any that already have
    # results (covers a same-day race that finished, or an upcoming row that
    # wasn't purged for some reason).
    return conn.execute(f"""
        SELECT race_id, race_title, race_date
        FROM upcoming_races
        WHERE race_date BETWEEN ? AND ?
          AND category = 'elite'
          AND prog_name IN {_ELITE_PROG_NAMES_SQL}
          AND race_id NOT IN (SELECT race_id FROM races)
        ORDER BY race_date, race_id
    """, [today, cutoff]).fetchall()


def _recently_finished_eligible(conn) -> list[tuple[int, str, date]]:
    """Races finished in the last POST_DAYS days. A race only shows up here
    after ingest has imported it - we don't try to post until results +
    ratings are in DB."""
    today  = date.today()
    cutoff = today - timedelta(days=POST_DAYS)
    return conn.execute(f"""
        SELECT race_id, race_title, race_date
        FROM races
        WHERE race_date BETWEEN ? AND ?
          AND sub_category = 'elite'
          AND prog_name IN {_ELITE_PROG_NAMES_SQL}
        ORDER BY race_date DESC, race_id
    """, [cutoff, today]).fetchall()


def _with_rw_conn(fn):
    """Run `fn(conn)` against a short-lived writable DB connection. Closes
    any cached read-only conn first - DuckDB refuses to keep both a RO and
    a RW handle to the same file open at once."""
    db.close_read_conn()
    conn = db.get_conn()
    try:
        return fn(conn)
    finally:
        conn.close()


def _run_window(races, post_type, pack_fn) -> None:
    label = post_type.replace("_", "-")
    for race_id, race_title, race_date in races:
        if _with_rw_conn(lambda c, rid=race_id: db.social_already_posted(c, rid, post_type)):
            continue
        print(f"\n[{label}] {race_date}  {race_id}  {race_title}")
        result = pack_fn(race_id)
        if result is None:
            print("  -> not posted (data unavailable, will retry next run)")
            continue
        _with_rw_conn(lambda c, rid=race_id, r=result:
                      db.mark_social_posted(c, rid, post_type, r.ig_post_id, r.fb_post_ids))


def main() -> None:
    upcoming = _with_rw_conn(_upcoming_eligible)
    recent   = _with_rw_conn(_recently_finished_eligible)

    print(f"Scheduler check at {date.today()}")
    print(f"  upcoming window ({PRE_DAYS}d):  {len(upcoming)} candidate races")
    print(f"  recent window   ({POST_DAYS}d): {len(recent)} candidate races")

    _run_window(upcoming, "pre_race",  pre_race_pack)
    _run_window(recent,   "post_race", post_race_pack)


if __name__ == "__main__":
    main()
