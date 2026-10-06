create extension if not exists citext;

create table users (
    user_id      bigint generated always as identity primary key,
    email        citext unique not null,
    display_name text not null,
    country      char(3),                  -- optional, alpha-3, shown next to comments
    is_admin     boolean not null default false,
    is_banned    boolean not null default false,
    email_digest boolean not null default true,
    avatar       bytea,                    -- 128px square webp, resized on upload
    avatar_version integer not null default 0,  -- bumped per upload; cache-busts the image URL
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
