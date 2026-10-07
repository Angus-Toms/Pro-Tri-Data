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
    kind       text not null check (kind in ('athlete', 'race', 'user')),
    ref_id     bigint not null,            -- DuckDB athlete/race id, or a user_id
    created_at timestamptz not null default now(),
    primary key (user_id, kind, ref_id)
);
create index follows_by_target on follows (kind, ref_id);   -- follower counts

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
