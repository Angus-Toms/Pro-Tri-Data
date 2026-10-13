"""Upload generated social-card PNGs to Cloudflare R2 so they're publicly
fetchable URLs — required by Meta's Graph API (it pulls the image by URL
when publishing posts).

Reuses the same bucket and credential conventions as ptd_data/sync_images.py.
"""
from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config

ACCOUNT_ID  = "f61c89ac113621bb9826f323f757966b"
BUCKET      = "ptd-static-assets"
ENDPOINT    = f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
PUBLIC_BASE = "https://www.static.protridata.com"

# Cards rarely change once published; cache aggressively. Use a 7-day TTL
# so manual re-uploads after a fix surface within a week without needing
# a cache purge.
CACHE_CTRL = "public, max-age=604800"


def _make_s3():
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        config=Config(
            region_name="auto",
            retries={"max_attempts": 10, "mode": "standard"},
        ),
    )


def upload_card(local_path: Path, key: str) -> str:
    """Upload `local_path` to R2 at `key` and return the public URL.

    `key` is the R2 object key (no leading slash). Convention used here:
        "social/posts/<race_id>/<card_name>.png"
    """
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    s3 = _make_s3()
    s3.upload_file(
        Filename=str(local_path),
        Bucket=BUCKET,
        Key=key,
        ExtraArgs={"CacheControl": CACHE_CTRL, "ContentType": "image/png"},
    )
    return f"{PUBLIC_BASE}/{key}"
