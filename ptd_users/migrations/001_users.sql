create extension if not exists citext;

create table users (
    user_id      bigint generated always as identity primary key,
    email        citext unique not null,
    display_name text not null,
    country      char(3),                  -- optional, alpha-3, shown next to comments
    is_admin     boolean not null default false,
    is_banned    boolean not null default false,
    email_digest boolean not null default true,
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
    user_id    bigint not null references users on delete cascade,
    body       text not null check (char_length(body) between 1 and 2000),
    created_at timestamptz not null default now(),
    hidden_at  timestamptz                 -- set by auto-hide or moderator
);
create index comments_by_race on comments (race_id, created_at desc);

create table comment_reports (
    comment_id bigint not null references comments on delete cascade,
    user_id    bigint not null references users on delete cascade,
    created_at timestamptz not null default now(),
    primary key (comment_id, user_id)
);
