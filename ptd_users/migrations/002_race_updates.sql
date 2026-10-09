-- Race likes double as "keep me posted": every start-list change for a liked
-- upcoming race, and its results once, land in the bell. The update email
-- reads the same rows, so the bell and the inbox never disagree.
alter table notifications alter column comment_id drop not null;
alter table notifications add column race_id bigint;   -- DuckDB race id, race notifications only
alter table notifications add column detail jsonb;     -- startlist: {entries, added, removed, first}
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check
    check (kind in ('reply', 'mention', 'startlist', 'results'));
alter table notifications add constraint notifications_target check (
    (kind in ('reply', 'mention')) = (comment_id is not null)
    and (kind in ('startlist', 'results')) = (race_id is not null));
-- Results are announced once per race.
create unique index notifications_results_once on notifications (user_id, race_id) where kind = 'results';

-- The start list every upcoming race had at the last update run, so the next
-- run can tell what changed. Rows go once a race has left the upcoming list.
create table race_startlists (
    race_id     bigint primary key,
    athlete_ids bigint[] not null,
    seen_at     timestamptz not null default now()
);
