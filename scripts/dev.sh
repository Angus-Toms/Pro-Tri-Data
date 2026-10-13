#!/bin/bash
# dev.sh - run the site locally with auto-reload on http://localhost:8000.
#
#   ./scripts/dev.sh          against the local DB (ptd_data/ptd.duckdb)
#   ./scripts/dev.sh --pull   first replace the local DB with the live one
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate

case "${1:-}" in
    "")     ;;
    --pull)
        # The box's DB is the master copy: the nightly workflow builds from it
        PROD_SSH=$(python -c "from config import PROD_SSH; print(PROD_SSH)")
        PROD_DB=$(python -c "from config import PROD_DB; print(PROD_DB)")
        scp "$PROD_SSH:$PROD_DB" ptd_data/ptd.duckdb ;;
    *) echo "Usage: $0 [--pull]" >&2; exit 2 ;;
esac

uvicorn app.main:app --reload --port 8000
