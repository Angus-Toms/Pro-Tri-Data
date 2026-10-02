#!/bin/bash
# deploy.sh - commit/push, upload static assets to R2, copy DB + code to the
# Hetzner box, restart the service
#
# Usage:
#   ./deploy.sh                   # run all steps
#   ./deploy.sh --no-git          # skip git commit/push AND the remote git pull
#   ./deploy.sh --no-static       # skip Cloudflare R2 upload
#   ./deploy.sh --no-db           # skip DB copy
#   ./deploy.sh --no-restart      # skip service restart
#
# Requires:
#   - wrangler (npm i -g wrangler) logged in
#   - ssh access to PROD_SSH (config.py) with the local ed25519 key

set -euo pipefail

# ── Config (values pulled from config.py) ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATIC_DIR="$PROJECT_ROOT/static"
DB_LOCAL="$PROJECT_ROOT/ptd_data/ptd.duckdb"
_py() { python3 -c "import sys; sys.path.insert(0,'$PROJECT_ROOT'); from config import $1; print($1)"; }
BUCKET=$(      _py CF_BUCKET)
PROD_SSH=$(    _py PROD_SSH)
DB_REMOTE=$(   _py PROD_DB)
APP_REMOTE=$(  _py PROD_APP_DIR)
# ─────────────────────────────────────────────────────────────────────────────

DO_GIT=true; DO_STATIC=true; DO_DB=true; DO_RESTART=true
for arg in "$@"; do
    case $arg in
        --no-git)     DO_GIT=false ;;
        --no-static)  DO_STATIC=false ;;
        --no-db)      DO_DB=false ;;
        --no-restart) DO_RESTART=false ;;
    esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
step() { echo -e "\n${GREEN}==> $*${RESET}"; }
note() { echo -e "${YELLOW}    $*${RESET}"; }

cd "$PROJECT_ROOT"

# ── 1. Git commit + push ──────────────────────────────────────────────────────
if $DO_GIT; then
    step "Git"
    git add -A
    if git diff --cached --quiet; then
        note "Nothing staged - skipping commit."
    else
        git diff --cached --stat
        echo ""
        read -rp "  Commit message: " msg
        git commit -m "$msg"
    fi

    # Push if there are unpushed commits
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "@{u}" 2>/dev/null || echo "")
    if [ "$LOCAL" != "$REMOTE" ]; then
        git push
        echo "  Pushed."
    else
        note "Already up to date with remote."
    fi
fi

# ── 2. Static assets → Cloudflare R2 ─────────────────────────────────────────
if $DO_STATIC; then
    step "Cloudflare R2: uploading static assets"
    # Content-Type matters: without it, Cloudflare won't apply Brotli (which
    # is gated on compressible MIME types) and won't cache via the default
    # static-asset rules. Wrangler doesn't auto-detect, so we map by extension.
    # Content-Type matters: without it, Cloudflare won't apply Brotli (which
    # is gated on compressible MIME types) and won't cache via the default
    # static-asset rules. Wrangler doesn't auto-detect, so we map by extension.
    content_type_for() {
        case "$1" in
            *.css)             echo "text/css; charset=utf-8" ;;
            *.js)              echo "application/javascript; charset=utf-8" ;;
            *.json)            echo "application/json; charset=utf-8" ;;
            *.svg)             echo "image/svg+xml" ;;
            *.webp)            echo "image/webp" ;;
            *.png)             echo "image/png" ;;
            *.jpg|*.jpeg)      echo "image/jpeg" ;;
            *.gif)             echo "image/gif" ;;
            *.ico)             echo "image/x-icon" ;;
            *.woff2)           echo "font/woff2" ;;
            *.woff)            echo "font/woff" ;;
            *.ttf)             echo "font/ttf" ;;
            *.txt)             echo "text/plain; charset=utf-8" ;;
            *.xml)             echo "application/xml; charset=utf-8" ;;
            *)                 echo "application/octet-stream" ;;
        esac
    }
    # Cache-Control tells Cloudflare (and browsers) how long to cache the
    # asset. Fonts + images have content-hashed or otherwise-stable URLs so
    # they get the long-lived immutable header. CSS/JS are still served from
    # plain /css/base.css etc. so we use a 1-hour max-age to avoid serving
    # stale styles for too long after a deploy + cache purge.
    cache_control_for() {
        case "$1" in
            *.woff2|*.woff|*.ttf|*.webp|*.png|*.jpg|*.jpeg|*.gif|*.ico|*.svg)
                echo "public, max-age=31536000, immutable" ;;
            *)
                echo "public, max-age=3600" ;;
        esac
    }
    for dir in css js imgs flags fonts/plus-jakarta-sans; do
        echo "  $dir/"
        for f in "$STATIC_DIR/$dir"/*; do
            [ -f "$f" ] || continue
            key="$dir/$(basename "$f")"
            ct=$(content_type_for "$f")
            cc=$(cache_control_for "$f")
            printf "    %-60s" "$key"
            # env -u: scripts/.env exports CF_API_TOKEN / CF_ACCOUNT_ID, which
            # wrangler reads as its deprecated auth aliases. That token has no
            # R2 write scope, so every upload 403s; unset for this call and
            # wrangler falls back to the OAuth login, which does. Keep the log
            # on failure - silencing it turned a 403 into a bare "FAILED".
            if env -u CF_API_TOKEN -u CF_ACCOUNT_ID \
                wrangler r2 object put "$BUCKET/$key" --file "$f" \
                --content-type "$ct" --cache-control "$cc" --remote > /tmp/wrangler-put.log 2>&1; then
                echo "ok"
            else
                echo "FAILED"
                grep -m1 "ERROR" /tmp/wrangler-put.log | sed 's/^/      /' || true
            fi
        done
    done
    note "If assets look stale, purge the Cloudflare cache for static.protridata.com."
fi

# ── 3. DB → server (atomic swap via tmp file) ────────────────────────────────
if $DO_DB; then
    DB_SIZE=$(du -sh "$DB_LOCAL" | cut -f1)
    step "Server: copying DB ($DB_SIZE)"
    # Upload to a temp path first, then mv - avoids a window where the app
    # could open a half-written file.
    scp "$DB_LOCAL" "$PROD_SSH:${DB_REMOTE}.new"
    ssh "$PROD_SSH" "mv '${DB_REMOTE}.new' '${DB_REMOTE}'"
    echo "  Copied."
fi

# ── 4. Code → server (git pull + pip) ────────────────────────────────────────
# Render used to rebuild from GitHub on push; now we pull explicitly.
if $DO_GIT; then
    step "Server: pulling code"
    ssh "$PROD_SSH" "cd '$APP_REMOTE' && git pull --ff-only && .venv/bin/pip install -q -r requirements.txt"
    echo "  Pulled $(ssh "$PROD_SSH" "cd '$APP_REMOTE' && git rev-parse --short HEAD")."
fi

# ── 5. Restart service (picks up new DB and/or code) ─────────────────────────
if $DO_RESTART; then
    step "Server: restarting ptd"
    ssh "$PROD_SSH" "sudo systemctl restart ptd"
    echo "  Restarted."
fi

# ── 6. Prediction-code drift check (data-only deploys) ───────────────────────
# A --no-git deploy ships the DB but not the app code, so the live site can run
# prediction logic older than the local tree - and the social-post generator
# renders from the local tree, so the two silently disagree (Edmonton: local
# had Pye 1st, the month-behind live site had him 6th). Compare the server's
# checked-out commit to local HEAD across the prediction-model core and warn
# loudly if they diverge. Read-only; never fails the deploy.
if ! $DO_GIT; then
    step "Server: checking deployed code vs local"
    # The prediction-model core. Deliberately narrow (not queries.py, which
    # churns for unrelated page/leaderboard work) so the warning stays signal.
    PRED_FILES="app/routers/race_page.py ptd_data/ratings.py ptd_data/form.py"
    LIVE_SHA=$(ssh "$PROD_SSH" "cd '$APP_REMOTE' && git rev-parse HEAD" 2>/dev/null || true)
    if [ -z "$LIVE_SHA" ]; then
        echo "  [WARN] CODE DRIFT: could not read the server's commit (ssh issue)."
    elif ! git cat-file -e "${LIVE_SHA}^{commit}" 2>/dev/null; then
        echo "  [WARN] CODE DRIFT: server commit ${LIVE_SHA:0:8} not in local history - run 'git fetch' to compare."
    elif git diff --quiet "$LIVE_SHA" HEAD -- $PRED_FILES; then
        echo "  Prediction code in sync with server (live ${LIVE_SHA:0:8})."
    else
        DRIFTED=$(git diff --name-only "$LIVE_SHA" HEAD -- $PRED_FILES | tr '\n' ' ')
        echo "  [WARN] CODE DRIFT: server runs ${LIVE_SHA:0:8}, local HEAD $(git rev-parse --short HEAD) - prediction code differs: ${DRIFTED}"
        echo "  [WARN] Live-site predictions may not match freshly-generated social posts. Run ./deploy.sh (with git) to ship it."
    fi
fi

step "Done"
