# All user-system SQL. Raw asyncpg against db.pool, no ORM.

from datetime import datetime, timedelta, timezone

from ptd_users import db

SESSION_LIFETIME = timedelta(days=90)
LOGIN_TOKEN_LIFETIME = timedelta(minutes=15)


# --- login tokens -----------------------------------------------------------

async def count_recent_login_tokens(email):
    # Tokens live 15 minutes, so rows whose expiry falls inside the last 45
    # minutes were created within the last hour. Used rows are kept (expiry
    # zeroed back to creation time at the earliest) so they still count.
    return await db.pool.fetchval("""
        select count(*) from login_tokens
        where email = $1 and expires_at > now() - interval '45 minutes'
    """, email)


async def insert_login_token(token_hash, email):
    await db.pool.execute(
        "delete from login_tokens where expires_at < now() - interval '2 hours'"
    )
    await db.pool.execute("""
        insert into login_tokens (token_hash, email, expires_at)
        values ($1, $2, now() + $3)
    """, token_hash, email, LOGIN_TOKEN_LIFETIME)


async def peek_login_token(token_hash):
    """Email for a live login token without using it up, or None."""
    return await db.pool.fetchval("""
        select email from login_tokens where token_hash = $1 and expires_at > now()
    """, token_hash)


async def take_login_token(token_hash):
    """Single use: atomically expire the token and return its email, or None.
    The row is kept (not deleted) so the per-address rate limit still sees it."""
    return await db.pool.fetchval("""
        update login_tokens set expires_at = now() - interval '1 minute'
        where token_hash = $1 and expires_at > now()
        returning email
    """, token_hash)


# --- users ------------------------------------------------------------------

async def get_user_by_email(email):
    row = await db.pool.fetchrow("select * from users where email = $1", email)
    return dict(row) if row else None


async def create_user(email, display_name):
    row = await db.pool.fetchrow("""
        insert into users (email, display_name) values ($1, $2) returning *
    """, email, display_name)
    return dict(row)


async def update_user(user_id, fields):
    """fields: validated column -> value dict from the account form."""
    cols = list(fields)
    sets = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cols))
    await db.pool.execute(f"update users set {sets} where user_id = $1",
                          user_id, *[fields[c] for c in cols])


async def set_display_name(user_id, display_name):
    await db.pool.execute(
        "update users set display_name = $2 where user_id = $1", user_id, display_name
    )


async def set_avatar(user_id, webp):
    """webp bytes, or None to remove the photo. The version always increases so
    every upload gets a fresh image URL; queries report 0 when there is no photo."""
    await db.pool.execute("""
        update users set avatar = $2, avatar_version = avatar_version + 1 where user_id = $1
    """, user_id, webp)


async def get_avatar(user_id):
    return await db.pool.fetchval("select avatar from users where user_id = $1", user_id)


async def delete_user(user_id):
    # Comments with replies become anonymous placeholders so other people's
    # replies survive; everything else goes via on delete cascade.
    async with db.pool.acquire() as conn, conn.transaction():
        await conn.execute("""
            update comments c set body = '', user_id = null, deleted_at = now()
            where c.user_id = $1
              and exists (select 1 from comments r where r.parent_id = c.comment_id)
        """, user_id)
        await conn.execute("delete from users where user_id = $1", user_id)


# --- sessions ---------------------------------------------------------------

async def create_session(token_hash, user_id):
    await db.pool.execute("""
        insert into sessions (token_hash, user_id, expires_at)
        values ($1, $2, now() + $3)
    """, token_hash, user_id, SESSION_LIFETIME)


async def get_session_user(token_hash):
    """User dict for a live session token hash, or None. Rolling expiry is
    bumped at most once a day to avoid a write on every request."""
    row = await db.pool.fetchrow("""
        -- Explicit columns: u.* would drag the avatar bytes into every request.
        select u.user_id, u.email, u.display_name, u.country, u.is_admin,
               u.is_banned, u.email_updates, u.created_at, case when u.avatar is null then 0 else u.avatar_version end as avatar_version,
               u.bio, u.club, u.pb_sprint, u.pb_olympic, u.pb_703, u.pb_1406, u.instagram, u.strava,
               s.last_seen_at
        from sessions s join users u using (user_id)
        where s.token_hash = $1 and s.expires_at > now()
    """, token_hash)
    if row is None:
        return None
    user = dict(row)
    if user.pop("last_seen_at") < datetime.now(timezone.utc) - timedelta(days=1):
        await db.pool.execute("""
            update sessions set last_seen_at = now(), expires_at = now() + $2
            where token_hash = $1
        """, token_hash, SESSION_LIFETIME)
    return user


async def delete_session(token_hash):
    await db.pool.execute("delete from sessions where token_hash = $1", token_hash)


# --- follows ----------------------------------------------------------------

async def get_follows(user_id):
    """{'athletes': [ids], 'races': [ids], 'users': [ids]} oldest-follow first."""
    rows = await db.pool.fetch("""
        select kind, ref_id from follows where user_id = $1 order by created_at
    """, user_id)
    return {
        "athletes": [r["ref_id"] for r in rows if r["kind"] == "athlete"],
        "races":    [r["ref_id"] for r in rows if r["kind"] == "race"],
        "users":    [r["ref_id"] for r in rows if r["kind"] == "user"],
    }


async def follower_count(kind, ref_id):
    return await db.pool.fetchval(
        "select count(*) from follows where kind = $1 and ref_id = $2", kind, ref_id)


async def toggle_follow(user_id, kind, ref_id):
    """Returns True if now following, False if the toggle removed the follow."""
    deleted = await db.pool.fetchval("""
        delete from follows where user_id = $1 and kind = $2 and ref_id = $3
        returning true
    """, user_id, kind, ref_id)
    if deleted:
        return False
    await db.pool.execute("""
        insert into follows (user_id, kind, ref_id) values ($1, $2, $3)
    """, user_id, kind, ref_id)
    return True


# --- comments ---------------------------------------------------------------

COMMENTS_PAGE_SIZE = 50
AUTO_HIDE_REPORTS = 3


async def list_comments(race_id, offset, viewer_id):
    """Comment threads for a race, YouTube-style: top-level comments newest
    first, each with every reply beneath it (at any depth) in one flat list,
    oldest first. The whole race is loaded and grouped here; a race has
    hundreds of comments at most. A removed top-level comment stays as a
    placeholder while its thread has visible replies; removed replies vanish.
    Each comment carries {kind: {'n', 'mine'}} reactions. Returns (threads, has_more)."""
    rows = [dict(r) for r in await db.pool.fetch("""
        select c.comment_id, c.parent_id, c.user_id, c.body, c.created_at,
               (c.hidden_at is not null or c.deleted_at is not null) as removed,
               u.display_name, u.country,
               case when u.avatar is null then 0 else u.avatar_version end as avatar_version
        from comments c left join users u using (user_id)
        where c.race_id = $1
        order by c.created_at, c.comment_id
    """, race_id)]
    by_id = {c["comment_id"]: c for c in rows}

    def root_of(c):
        while c["parent_id"] is not None:
            c = by_id[c["parent_id"]]
        return c

    for c in rows:
        c["replies"], c["reactions"] = [], {}
    for c in rows:
        if c["parent_id"] is not None and not c["removed"]:
            root_of(c)["replies"].append(c)

    roots = [c for c in reversed(rows)
             if c["parent_id"] is None and (not c["removed"] or c["replies"])]
    page = roots[offset:offset + COMMENTS_PAGE_SIZE]

    shown = [c["comment_id"] for c in page] + [r["comment_id"] for c in page for r in c["replies"]]
    for r in await db.pool.fetch("""
        select comment_id, kind, count(*) as n,
               coalesce(bool_or(user_id = $2), false) as mine
        from comment_reactions where comment_id = any($1)
        group by comment_id, kind
    """, shown, viewer_id):
        by_id[r["comment_id"]]["reactions"][r["kind"]] = {"n": r["n"], "mine": r["mine"]}
    return page, len(roots) > offset + COMMENTS_PAGE_SIZE


async def insert_comment(race_id, user_id, body, parent, mentioned_user_ids):
    """Insert a comment and its notifications. parent is the replied-to comment
    dict or None. Its author gets a 'reply'; tagged users get a 'mention'.
    Nobody is notified about their own comment, and a parent author who is
    also tagged gets just the reply."""
    notes = []
    if parent is not None and parent["user_id"] not in (None, user_id):
        notes.append((parent["user_id"], "reply"))
    notified = {user_id} | {uid for uid, _ in notes}
    notes += [(uid, "mention") for uid in mentioned_user_ids if uid not in notified]
    async with db.pool.acquire() as conn, conn.transaction():
        comment_id = await conn.fetchval("""
            insert into comments (race_id, user_id, body, parent_id) values ($1, $2, $3, $4)
            returning comment_id
        """, race_id, user_id, body, parent["comment_id"] if parent else None)
        await conn.executemany("""
            insert into notifications (user_id, comment_id, kind) values ($1, $2, $3)
        """, [(uid, comment_id, kind) for uid, kind in notes])


async def toggle_reaction(comment_id, user_id, kind):
    """One reaction per person per comment: picking the current one clears it,
    picking another replaces it. Returns the comment's {kind: {'n', 'mine'}}."""
    async with db.pool.acquire() as conn, conn.transaction():
        current = await conn.fetchval("""
            select kind from comment_reactions where comment_id = $1 and user_id = $2
        """, comment_id, user_id)
        if current == kind:
            await conn.execute("""
                delete from comment_reactions where comment_id = $1 and user_id = $2
            """, comment_id, user_id)
        else:
            await conn.execute("""
                insert into comment_reactions (comment_id, user_id, kind) values ($1, $2, $3)
                on conflict (comment_id, user_id)
                do update set kind = excluded.kind, created_at = now()
            """, comment_id, user_id, kind)
        rows = await conn.fetch("""
            select kind, count(*) as n, bool_or(user_id = $2) as mine
            from comment_reactions where comment_id = $1 group by kind
        """, comment_id, user_id)
    return {r["kind"]: {"n": r["n"], "mine": r["mine"]} for r in rows}


async def get_comment(comment_id):
    row = await db.pool.fetchrow(
        "select * from comments where comment_id = $1", comment_id
    )
    return dict(row) if row else None


async def delete_comment(comment_id):
    """Delete outright, or blank to a placeholder if anything replies to it."""
    async with db.pool.acquire() as conn, conn.transaction():
        has_replies = await conn.fetchval(
            "select exists (select 1 from comments where parent_id = $1)", comment_id)
        if not has_replies:
            await conn.execute("delete from comments where comment_id = $1", comment_id)
            return
        await conn.execute("""
            update comments set body = '', user_id = null, deleted_at = now()
            where comment_id = $1
        """, comment_id)
        await conn.execute("delete from comment_reactions where comment_id = $1", comment_id)
        await conn.execute("delete from notifications where comment_id = $1", comment_id)


async def comment_rate_state(user_id):
    """(last_comment_at or None, comments in the last 24h) for rate limiting."""
    row = await db.pool.fetchrow("""
        select max(created_at) as last_at,
               count(*) filter (where created_at > now() - interval '1 day') as day_count
        from comments where user_id = $1
    """, user_id)
    return row["last_at"], row["day_count"]


async def report_comment(comment_id, user_id):
    """Record a report (unique per user); auto-hide at AUTO_HIDE_REPORTS distinct
    reporters. Returns the current report count."""
    await db.pool.execute("""
        insert into comment_reports (comment_id, user_id) values ($1, $2)
        on conflict do nothing
    """, comment_id, user_id)
    count = await db.pool.fetchval(
        "select count(*) from comment_reports where comment_id = $1", comment_id
    )
    if count >= AUTO_HIDE_REPORTS:
        await db.pool.execute("""
            update comments set hidden_at = now()
            where comment_id = $1 and hidden_at is null
        """, comment_id)
    return count


async def unhide_comment(comment_id):
    # Clearing the reports as well, otherwise the very next report re-hides
    # a comment a moderator just cleared.
    await db.pool.execute(
        "delete from comment_reports where comment_id = $1", comment_id
    )
    await db.pool.execute(
        "update comments set hidden_at = null where comment_id = $1", comment_id
    )


async def moderation_queue():
    """Reported or hidden comments with report counts, hidden first."""
    rows = await db.pool.fetch("""
        select c.comment_id, c.race_id, c.body, c.created_at, c.hidden_at,
               c.user_id, u.display_name, u.email, case when u.avatar is null then 0 else u.avatar_version end as avatar_version,
               count(cr.user_id) as report_count
        from comments c
        join users u using (user_id)
        left join comment_reports cr using (comment_id)
        where c.deleted_at is null
        group by c.comment_id, u.user_id
        having c.hidden_at is not null or count(cr.user_id) > 0
        order by (c.hidden_at is null), c.created_at desc
    """)
    return [dict(r) for r in rows]


async def get_recent_comments_for_feed(race_ids, user_ids, limit=20):
    """Latest visible comments on followed races or by followed people."""
    rows = await db.pool.fetch("""
        select c.comment_id, c.race_id, c.user_id, c.body, c.created_at,
               u.display_name, u.country, case when u.avatar is null then 0 else u.avatar_version end as avatar_version
        from comments c join users u using (user_id)
        where (c.race_id = any($1) or c.user_id = any($2))
          and c.hidden_at is null and c.deleted_at is null
        order by c.created_at desc
        limit $3
    """, race_ids, user_ids, limit)
    return [dict(r) for r in rows]


# --- user tags and notifications ---------------------------------------------

async def search_race_commenters(race_id, q, limit=5):
    """People who have commented on a race, for the @ picker. Limited to the
    race's own participants so the site never exposes a user directory."""
    rows = await db.pool.fetch("""
        select distinct u.user_id, u.display_name, u.country,
               case when u.avatar is null then 0 else u.avatar_version end as avatar_version
        from comments c join users u using (user_id)
        where c.race_id = $1 and u.display_name ilike '%' || $2 || '%'
          and not u.is_banned
        order by u.display_name
        limit $3
    """, race_id, q, limit)
    return [dict(r) for r in rows]


async def get_users_brief(user_ids):
    """{user_id: {display_name, country}} for tag validation and chips."""
    rows = await db.pool.fetch("""
        select user_id, display_name, country,
               case when avatar is null then 0 else avatar_version end as avatar_version
        from users where user_id = any($1)
    """, list(user_ids))
    return {r["user_id"]: dict(r) for r in rows}


async def unread_notification_count(user_id):
    return await db.pool.fetchval("""
        select count(*) from notifications where user_id = $1 and read_at is null
    """, user_id)


async def list_notifications(user_id, limit=20):
    """Latest notifications, newest first, with who acted and where. A comment
    removed since keeps its notification out of the list."""
    rows = await db.pool.fetch("""
        select n.notification_id, n.kind, n.created_at, n.read_at,
               c.comment_id, c.race_id, u.display_name
        from notifications n
        join comments c using (comment_id)
        join users u on u.user_id = c.user_id
        where n.user_id = $1 and c.hidden_at is null and c.deleted_at is null
        order by n.created_at desc
        limit $2
    """, user_id, limit)
    return [dict(r) for r in rows]


async def mark_notifications_read(user_id):
    await db.pool.execute("""
        update notifications set read_at = now() where user_id = $1 and read_at is null
    """, user_id)


# --- public profiles -----------------------------------------------------------
# Only what is already public on race pages: name, flag, photo, join date and
# visible comments. Email and follows stay private.

async def get_public_profile(user_id):
    row = await db.pool.fetchrow("""
        select u.user_id, u.display_name, u.country, u.created_at,
               case when u.avatar is null then 0 else u.avatar_version end as avatar_version,
               u.bio, u.club, u.pb_sprint, u.pb_olympic, u.pb_703, u.pb_1406, u.instagram, u.strava,
               (select count(*) from comments c
                where c.user_id = u.user_id and c.hidden_at is null and c.deleted_at is null) as comment_count,
               (select count(*) from follows f where f.kind = 'user' and f.ref_id = u.user_id) as follower_count,
               (select count(*) from follows f where f.kind = 'user' and f.user_id = u.user_id) as following_count
        from users u where u.user_id = $1 and not u.is_banned
    """, user_id)
    return dict(row) if row else None


async def list_user_comments(user_id, offset, limit=30):
    """A user's visible comments, newest first, with positive reaction counts.
    Returns (comments, has_more)."""
    rows = await db.pool.fetch("""
        select c.comment_id, c.race_id, c.parent_id, c.body, c.created_at,
               (select count(*) from comment_reactions r
                where r.comment_id = c.comment_id and r.kind <> 'down') as reactions
        from comments c
        where c.user_id = $1 and c.hidden_at is null and c.deleted_at is null
        order by c.created_at desc, c.comment_id desc
        limit $2 offset $3
    """, user_id, limit + 1, offset)
    return [dict(r) for r in rows[:limit]], len(rows) > limit


async def reactions_received(user_id):
    """{kind: count} of reactions on a user's visible comments, thumbs down excluded."""
    rows = await db.pool.fetch("""
        select r.kind, count(*) as n
        from comment_reactions r join comments c using (comment_id)
        where c.user_id = $1 and r.kind <> 'down'
          and c.hidden_at is null and c.deleted_at is null
        group by r.kind
    """, user_id)
    return {r["kind"]: r["n"] for r in rows}


# --- remembered logins ("continue as" after logout) ---------------------------

REMEMBER_LIFETIME = timedelta(days=30)


async def create_remembered(token_hash, user_id):
    await db.pool.execute("""
        insert into remembered_logins (token_hash, user_id, expires_at) values ($1, $2, now() + $3)
    """, token_hash, user_id, REMEMBER_LIFETIME)


async def get_remembered(token_hashes):
    """Live remembered accounts for a browser's tokens: [{token_hash, user_id,
    display_name, email, avatar_version}], in cookie order."""
    rows = await db.pool.fetch("""
        select r.token_hash, u.user_id, u.display_name, u.email,
               case when u.avatar is null then 0 else u.avatar_version end as avatar_version
        from remembered_logins r join users u using (user_id)
        where r.token_hash = any($1) and r.expires_at > now() and not u.is_banned
    """, token_hashes)
    by_hash = {bytes(r["token_hash"]): dict(r) for r in rows}
    return [by_hash[h] for h in token_hashes if h in by_hash]


async def take_remembered(token_hash):
    """Single use: delete the token and return its user_id, or None."""
    return await db.pool.fetchval("""
        delete from remembered_logins where token_hash = $1 and expires_at > now()
        returning user_id
    """, token_hash)


async def delete_remembered(token_hashes):
    await db.pool.execute(
        "delete from remembered_logins where token_hash = any($1)", token_hashes)


# --- follow-update emails -------------------------------------------------------

async def users_for_update_emails():
    """Opted-in users with follows: [{user_id, email, athletes, races}]."""
    rows = await db.pool.fetch("""
        select u.user_id, u.email,
               coalesce(array_agg(f.ref_id) filter (where f.kind = 'athlete'), '{}') as athletes,
               coalesce(array_agg(f.ref_id) filter (where f.kind = 'race'), '{}') as races
        from users u join follows f using (user_id)
        where u.email_updates and not u.is_banned
        group by u.user_id
    """)
    return [dict(r) for r in rows]


async def sent_items(user_id):
    return {r["item"] for r in await db.pool.fetch(
        "select item from email_sent where user_id = $1", user_id)}


async def record_sent(user_id, items):
    await db.pool.executemany("""
        insert into email_sent (user_id, item) values ($1, $2) on conflict do nothing
    """, [(user_id, i) for i in items])
