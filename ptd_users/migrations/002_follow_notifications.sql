-- Brings a database created from an earlier 001_users.sql up to the current
-- one. 2fcb95b folded the race-update and follow notifications into 001 on the
-- assumption that no database existed yet, but the live one had already run
-- 001 (and possibly the since-deleted 002_race_updates.sql), so following a
-- person failed: notifications had no actor_id and no 'follow' kind.
-- Every statement is a no-op on a database built from the current 001.
alter table notifications alter column comment_id drop not null;
alter table notifications add column if not exists actor_id bigint references users on delete cascade;
alter table notifications add column if not exists race_id bigint;
alter table notifications add column if not exists detail jsonb;

alter table notifications drop constraint if exists notifications_kind_check;
alter table notifications add constraint notifications_kind_check
    check (kind in ('reply', 'mention', 'follow', 'startlist', 'results'));
alter table notifications drop constraint if exists notifications_target;
alter table notifications add constraint notifications_target check (
    (kind in ('reply', 'mention')) = (comment_id is not null)
    and (kind = 'follow') = (actor_id is not null)
    and (kind in ('startlist', 'results')) = (race_id is not null));

create unique index if not exists notifications_results_once on notifications (user_id, race_id) where kind = 'results';
create unique index if not exists notifications_follow_once on notifications (user_id, actor_id) where kind = 'follow';

create table if not exists race_startlists (
    race_id     bigint primary key,
    athlete_ids bigint[] not null,
    seen_at     timestamptz not null default now()
);
