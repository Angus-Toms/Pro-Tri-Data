# User System Design Draft

Goal: accounts with email verification, profiles, follows (athletes and races), a personal
feed, comments under races, and account deletion. Constraints: solo-maintained, lean,
fail fast, and it must not interfere with the weekly DuckDB rebuild/sync.

## Architecture principle

The analytics DuckDB is rebuilt on the laptop and rsynced to Render weekly. It is
read-only at runtime and gets replaced wholesale. User data therefore lives in a second,
write-heavy store that survives deploys. The two never join in SQL; user rows reference
athlete/race ids (stable CRC32-of-slug ids, so weekly rebuilds do not break references),
and the app stitches the two sides together in Python exactly like the routers already
stitch query results.

## 1. Database

Recommendation: managed Postgres in Frankfurt (Render Postgres, same region as the app;
Neon free tier is the zero-cost alternative).

Why not the alternatives:
- DuckDB: single-writer, and the file is replaced weekly. Wrong tool for user writes.
- SQLite on the Render disk: workable at small scale (WAL mode), but writes serialize,
  the disk is already the DB-sync target, backups are manual, and it caps out exactly
  when the feature succeeds. Postgres removes the ceiling for one config var.

Access layer: asyncpg connection pool (size ~10), raw SQL, no ORM. New package
`ptd_users/` mirroring `ptd_data/`: `db.py` (pool + migration runner), `queries.py`.
Migrations are numbered .sql files in `ptd_users/migrations/`, applied at startup;
a `schema_migrations` table records what ran. Crash on failure.

## 2. Auth: passwordless magic links

Account creation and email verification collapse into one flow: enter email, receive a
single-use link, click it, session starts. New emails create the account on first
verify; existing emails log in. No passwords stored means no hashing, no reset flow,
no breach surface. Tradeoff: logging in on a new device needs an email round trip,
mitigated by 90-day rolling sessions.

- Session: opaque 32-byte token, SHA-256 hash stored server-side, sent as an
  httpOnly Secure SameSite=Lax cookie. Rolling expiry, bumped at most once a day.
- Login tokens: single use, 15-minute expiry, hashed at rest.
- Email sending: one `send_email(to, subject, html)` function. Recommendation: Resend
  (simple API, 3k emails/month free, DKIM on protridata.com). SES is the cheap-at-scale
  alternative since boto3 is already a dependency, but needs production-access approval.
- Abuse limits: 3 link emails per address per hour, honeypot field plus minimum
  form-fill time on the request form. No CAPTCHA initially.

## 3. Schema

```sql
create extension if not exists citext;

create table users (
    user_id      bigint generated always as identity primary key,
    email        citext unique not null,
    display_name text not null,
    country      char(3),                  -- optional, alpha-3, shown next to comments
    is_admin     boolean not null default false,
    is_banned    boolean not null default false,
    email_updates boolean not null default true,  -- results/start-list emails for follows
    avatar       bytea,                    -- 128px square webp, resized on upload
    avatar_version integer not null default 0,  -- bumped per upload; cache-busts the image URL
    bio          text check (char_length(bio) <= 280),
    club         text check (char_length(club) <= 60),
    pb_sprint    integer,                  -- self-reported PBs, seconds
    pb_olympic   integer,
    pb_703       integer,
    pb_1406      integer,
    instagram    text,                     -- handle, validated in the route
    strava       bigint,                   -- Strava athlete id
    created_at   timestamptz not null default now()
);

create table login_tokens (
    token_hash  bytea primary key,
    email       citext not null,
    expires_at  timestamptz not null
);

create table sessions (
    token_hash   bytea primary key,
    user_id      bigint not null references users on delete cascade,
    created_at   timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    expires_at   timestamptz not null
);

create table follows (
    user_id    bigint not null references users on delete cascade,
    kind       text not null check (kind in ('athlete', 'race')),
    ref_id     bigint not null,            -- id in the analytics DuckDB
    created_at timestamptz not null default now(),
    primary key (user_id, kind, ref_id)
);

create table comments (
    comment_id bigint generated always as identity primary key,
    race_id    bigint not null,            -- validated against DuckDB at write time
    user_id    bigint references users on delete cascade,  -- null once removed
    body       text not null check (char_length(body) <= 2000),  -- '' once removed
    created_at timestamptz not null default now(),
    hidden_at  timestamptz,                -- set by auto-hide or moderator
    deleted_at timestamptz,                -- removed but kept as a placeholder for its replies
    parent_id  bigint references comments on delete cascade  -- any depth of replies
);
create index comments_by_race on comments (race_id, created_at desc);
create index comments_by_parent on comments (parent_id, created_at) where parent_id is not null;

create table comment_reports (
    comment_id bigint not null references comments on delete cascade,
    user_id    bigint not null references users on delete cascade,
    created_at timestamptz not null default now(),
    primary key (comment_id, user_id)
);


create table comment_reactions (
    comment_id bigint not null references comments on delete cascade,
    user_id    bigint not null references users on delete cascade,
    kind       text not null check (kind in ('up', 'down', 'rapid', 'paincave', 'podium')),
    created_at timestamptz not null default now(),
    primary key (comment_id, user_id)         -- one reaction per person per comment
);

create table notifications (
    notification_id bigint generated always as identity primary key,
    user_id    bigint not null references users on delete cascade,     -- recipient
    comment_id bigint not null references comments on delete cascade,  -- the reply or mention
    kind       text not null check (kind in ('reply', 'mention')),
    created_at timestamptz not null default now(),
    read_at    timestamptz,
    unique (user_id, comment_id)
);
create index notifications_by_user on notifications (user_id, created_at desc);

-- "Continue as" on the login page: a one-time token stored in a browser cookie
-- at logout, so that browser can log straight back in without an email link.
create table remembered_logins (
    token_hash bytea primary key,
    user_id    bigint not null references users on delete cascade,
    expires_at timestamptz not null
);

-- Follow-update emails already sent, so each result or start list is emailed
-- once. item is 'result:<race>:<athlete>', 'start:<race>:<athlete>' or 'race:<race>'.
create table email_sent (
    user_id bigint not null references users on delete cascade,
    item    text not null,
    sent_at timestamptz not null default now(),
    primary key (user_id, item)
);
```

`ref_id` and `race_id` get existence-checked against DuckDB in the route before insert.
No cross-database FK is possible; deterministic ids make this safe in practice.

## 4. Anonymous pages, client-side hydration (the key decision)

The in-process page cache has been removed (it was destabilizing Render), but the
principle it enforced stays: HTML pages render identically for everyone, which keeps
them CDN-cacheable and keeps user state out of every existing router. The logged-in
experience is hydrated client-side:

- `GET /me` returns `{display_name, follows: {athletes: [...], races: [...]}}` or 401.
  Fetched once per page load, cached in sessionStorage for a few minutes. Follow
  buttons and the nav account chip render in a neutral state and correct themselves
  from this payload (same pattern as the asset-versioned static JS already in use).
- Comments are loaded as a separate partial (`/race/{id}/comments`), so race HTML
  never contains user state.
- `/account` and `/feed` are session-gated and sent with Cache-Control: no-store.

## 5. Routes and pages

Auth (`app/routers/auth.py`)
- `GET /login` - single page for both signup and login (email box)
- `POST /auth/request-link` - send magic link
- `GET /auth/verify?token=...` - the emailed link: shows a confirm page with a button
  and does not use the token, because email security scanners open links.
- `POST /auth/verify` - the button: uses the token, creates the account if new, starts
  a session; first-time users land on a one-field "pick a display name" step
- `POST /auth/logout` - also remembers the account on this browser: a one-time
  token (hash stored in `remembered_logins`, 30 days) goes into an httpOnly
  `ptd_remember` cookie holding up to 3 accounts.
- `/login` lists remembered accounts ("Welcome back") above the email form.
  `POST /auth/resume` consumes the token and starts a session with no email
  round trip; a fresh token is issued at the next logout. `POST /auth/forget`
  removes an account from the browser. Trade-off: on a remembered browser,
  logging out no longer locks the account, so the page tells shared-computer
  users to remove it. SameSite=Lax keeps cross-site posts from using the cookie.

Account (`app/routers/account.py`)
- `GET /account` - display name, email, country, digest toggle, followed athletes and
  races with unfollow controls, danger zone
- `POST /account/update`
- `POST /account/delete` - hard delete: user row, sessions, follows, comments and
  reports all go (cascades). Re-confirmation via typed phrase. No soft-delete state
  to maintain, nothing retained.

Follows (`app/routers/follows.py`)
- `POST /follow` body `{kind, ref_id}` - toggle, returns new state
- Buttons: athlete hero, race hero, leaderboard cards. Logged-out click routes to /login
  with a `next` redirect.

Feed (`app/routers/feed.py`)
- `GET /feed` - server-rendered, session-gated. Sections in order: upcoming races
  (followed races plus races with followed athletes on the startlist, with predicted
  podiums), recent results from followed athletes (last 90 days, position, time,
  rating change), recent comments on followed races. Reuses existing queries.py
  functions; one bulk query per section.

Comments (`app/routers/comments.py`)
- `GET /race/{id}/comments` - partial, newest first, paginated 50 at a time
- `POST /race/{id}/comments` - session required, account older than 1 hour,
  rate limit 1 per 30s and 20 per day, plain text only (escaped, line breaks kept)
- `POST /comments/{id}/delete` - own comment or admin
- `POST /comments/{id}/report` - 3 unique reports auto-hides pending review
- `GET /admin/moderation` - reported and hidden queue, is_admin only
- Races only, per the decision; athlete pages stay comment-free.
- Replies nest to any depth in the data (`comments.parent_id`) and stay on the
  parent's race. Display is YouTube-style: under each top-level comment, every
  reply in its thread sits in one flat list, oldest first, collapsed behind an
  "N replies" toggle. A reply box opens pre-filled with a tag of the person being
  answered, which is what shows who answers whom. One reply box is open at a time;
  posting keeps the thread open. The partial loads a race's whole comment set and
  groups it in Python; pagination is by top-level thread.
- Every comment shows the author's photo, or their initial on a colour picked
  from their user id. Photos are uploaded on the account page, centre-cropped to
  128px webp with Pillow and stored in `users.avatar` (bytea), so they survive
  deploys and are backed up with the database. Served from `/avatar/{id}.webp?v=`,
  where the version bumps on every upload so the URL can be cached forever.
- Deleting a comment with replies blanks it to a placeholder (body emptied, author
  cleared, reactions and notifications dropped) so the thread survives. Only a
  top-level placeholder is ever shown, as "Comment removed" above its replies;
  removed replies simply drop out of the flat list. Account deletion does the same
  for the user's comments that have replies; the rest cascade away.
- Reactions: thumbs up and thumbs down (mutually exclusive) are always shown with
  their own counts. Three tri reactions, Rapid (stopwatch), Pain cave (flame) and
  Podium (trophy), appear once used and are added from a "+" picker. One row per
  (comment, user, kind) in `comment_reactions`; `POST /comments/{id}/react` toggles
  and returns the comment's full reaction state. Delete and Report sit in a "more"
  menu so each comment's footer is a single row.
- Tagging: typing `@` in the comment box opens a picker of people, athletes and
  races (`GET /comments/mention-search?race_id=&q=`). People are limited to those
  who have commented on that race, so there is no browsable user directory. The
  comment box is contenteditable, so a pick inserts the same chip the posted
  comment shows; chips serialise to `@[Label](kind:id)` tokens. The server
  validates every id, rewrites the label to the canonical name, and renders
  athlete and race tags as links. Athlete chips show the athlete's photo and
  flag. User chips render the user's current name
  ("deleted user" once gone) and do not link, since profiles are not public.
  At most 10 tags per comment.

Profiles (`app/routers/profiles.py`)
- `GET /user/{id}` - public, anonymous page (noindex): photo, name, flag, join date,
  comment and reactions-received counts, and the user's visible comments newest
  first, 30 per page, each linking to the comment on its race. Shows only what is
  already public on race pages; email and follows stay private. Banned users 404.
- Comment author names, avatars and person tags link here.
- Optional public fields, edited on the account page: bio (280 chars), club, an
  Instagram handle and a Strava athlete id (pasted links are reduced to these),
  and self-reported PBs for sprint, Olympic, 70.3 and 140.6, stored as seconds.
  PBs outside a loose plausible range per distance are rejected; the profile
  labels them self-reported. External links use rel="nofollow noopener ugc".

Notifications
- Two kinds, written in the same transaction as the comment: the author of the
  comment directly above a reply gets "X replied to your comment on Y race"; each
  tagged user gets "X mentioned you in a comment". Nobody is notified about their
  own comment, and a parent author who is also tagged gets only the reply.
- Header bell for logged-in users with an unread badge; the count rides on `/me`.
  Opening the panel fetches `GET /notifications` (latest 20) and marks all read
  (`POST /notifications/read`). Each item links to `/race/{id}#comment-{id}`,
  which scrolls to and highlights the comment.

Emails (`ptd_users/emails.py`, templates in `templates/emails/`)
- Table-based HTML with inline styles in the site palette, plus a plain-text part.
  Sent through Resend from `EMAIL_FROM` (default login@protridata.com).
- Login: subject "Your login link", one button to the confirm page.
- Follow updates: `scripts/send_update_emails.py`, run after the weekly build
  against the production database. One email per opted-in user listing new
  results for followed athletes (last 14 days, with rating change), new start-list
  entries with a predicted finish (rank by rating, as the site's predicted podium),
  and podiums of followed races. `email_sent` records each item so nothing is
  emailed twice. Controlled by `users.email_updates`.
- Every update email carries a signed unsubscribe link (HMAC of the user id with
  `SECRET_KEY`) and List-Unsubscribe headers for one-click unsubscribe in mail apps.
- Comment activity (replies, tags, reactions) stays in-app via the bell.

## 6. Extras worth adding

- Podium picks: before a followed upcoming race, the user picks a podium; after the
  weekly build the picks are scored against results and against the model's own
  prediction. One table `podium_picks (user_id, race_id, picks, score)`, a pick widget
  on the upcoming race page, a "your picks" strip on the feed and a per-season user
  leaderboard. Gives a reason to return before and after every race.
- Pre-race threads and a calendar feed: open comments on upcoming races (ids are
  stable across the upcoming/past boundary so the thread carries over to the results
  page) and expose a per-user ICS subscription of followed athletes' starts and
  followed races. The site then surfaces in the user's own calendar on race day.
- Milestones: derive career events at build time (new peak rating, first win, top-10
  debut, first elite start) into a DuckDB table and surface them as feed items and
  digest lines for followed athletes. Keeps the feed alive in weeks with no starts.
- Saved comparisons: trivial later (one table, a Save button on the comparison page).
- Deliberately skipped: OAuth providers (magic link is sufficient and keyless), push
  notifications.

## 7. Build order

1. Infra: Postgres instance, ptd_users package, pool, migrations, session middleware,
   /me endpoint, login/verify flow, email sending. The auth core.
2. Account page and deletion.
3. Follows, buttons, /feed.
4. Comments, rate limiting, reports, moderation queue.
5. Digest email after the rest has settled.

Phases 1-2 ship together as the smallest useful unit; 3 is the retention payoff;
4 is the community bet and the only part with ongoing moderation cost.

## Open questions

- Postgres host: Render ($7/month starter, same private network) vs Neon (free, over
  the public internet with TLS)?
- Email provider: Resend (simplest) vs SES (already have AWS tooling)?
- Display names: enforce uniqueness (handles, needed only if profiles ever go public)
  or freeform with the user_id as the real identity?
