#!/bin/bash
# build.sh - bring the DuckDB file up to date from every source.
#
#   ./scripts/build.sh          nightly: WT and PTO results from the last 30 days,
#                               ratings extended from the earliest new race
#   ./scripts/build.sh --full   every race in history re-walked, ratings, rankings
#                               and predictions recomputed from scratch
#
# Runs against config.DB_PATH (ptd_data/ptd.duckdb, or $DATA_ROOT/ptd.duckdb).
# Start lists always cover every upcoming WT race. The nightly GitHub workflow
# (.github/workflows/nightly.yml) runs this against a copy of the live DB.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Locally the project venv; CI installs straight into its Python
[ -d .venv ] && source .venv/bin/activate

FULL=false
case "${1:-}" in
    "")     ;;
    --full) FULL=true ;;
    *)      echo "Usage: $0 [--full]" >&2; exit 2 ;;
esac

step() { echo; echo "==> $*"; }
db()   { python -c "from ptd_data import db; conn = db.get_conn(); db.$1(conn); conn.close()"; }

# Word-split on purpose: empty for --full
if $FULL; then WINDOW=""; else WINDOW="--days 30"; fi

# Sources. FGP and Bundesliga match against the fresh WT roster, and PTO
# matching needs the athletes they mint, so the order matters.
step "World Triathlon results";       python -m ptd_data.ingest $WINDOW
step "World Triathlon start lists";   python -m ptd_data.ingest --start-lists
step "Manual start lists";            db load_manual_startlists
step "French Grand Prix";             python -m ptd_data.fgp_ingest
step "Bundesliga";                    python -m ptd_data.bundesliga_ingest
step "PTO long-course results";       python -m ptd_data.pto_ingest $WINDOW

# Hand-kept CSVs in ptd_data/data/. Merges run after every source so new
# entries land before the derived passes; stages run after ignored because
# they add stage rows to ignored_races.
step "Athlete merges";                db apply_athlete_merges
step "Rejected auto-links";           db apply_athlete_no_merge
step "Doping bans";                   db load_doping_bans
step "Instagram handles";             db load_instagram_csv
step "Ignored races";                 python -m ptd_data.ignored
step "Multi-stage events";            python -m ptd_data.stages
step "Series";                        python -m ptd_data.series_rules
step "Recurring events";              python -m ptd_data.recurring_events
step "Auto corrections";              python -m ptd_data.auto_corrections

# Derived tables
if $FULL; then
    step "Ratings and rankings (full)"; python -m ptd_data.ratings
else
    step "Ratings and rankings";        python -m ptd_data.ratings --extend
fi
step "Predictions";                   python -m ptd_data.predictions $WINDOW
# Ratings, rankings and form are rewritten every run and DuckDB never shrinks
# the file in place.
step "Compact";                       python -m ptd_data.compact
