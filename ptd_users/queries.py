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


async def update_user(user_id, display_name, country, email_digest):
    await db.pool.execute("""
        update users set display_name = $2, country = $3, email_digest = $4
        where user_id = $1
    """, user_id, display_name, country, email_digest)


async def set_display_name(user_id, display_name):
    await db.pool.execute(
        "update users set display_name = $2 where user_id = $1", user_id, display_name
    )


async def delete_user(user_id):
    # Sessions, follows, comments and reports all go via on delete cascade.
    await db.pool.execute("delete from users where user_id = $1", user_id)


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
        select u.*, s.last_seen_at
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
    """{'athletes': [ids], 'races': [ids]} ordered oldest-follow first."""
    rows = await db.pool.fetch("""
        select kind, ref_id from follows where user_id = $1 order by created_at
    """, user_id)
    return {
        "athletes": [r["ref_id"] for r in rows if r["kind"] == "athlete"],
        "races":    [r["ref_id"] for r in rows if r["kind"] == "race"],
    }


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
