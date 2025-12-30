#!/usr/bin/env python3
from pathlib import Path
import boto3
from botocore.config import Config

# ========= CONFIG =========

ACCOUNT_ID = "f61c89ac113621bb9826f323f757966b"
BUCKET_NAME = "ptd-static-assets"
ENDPOINT_URL = f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"

CACHE_CONTROL = "public, max-age=31536000, immutable"
CONTENT_TYPE = "image/webp"

UPLOADS = [
    {
        "local_dir": Path("./data/athlete_imgs/64").resolve(),
        "remote_prefix": "athlete_imgs/64",
    },
    {
        "local_dir": Path("./data/athlete_imgs/128").resolve(),
        "remote_prefix": "athlete_imgs/128",
    },
]

# ==========================


def make_s3_client():
    config = Config(
        region_name="auto",
        retries={"max_attempts": 10, "mode": "standard"},
        max_pool_connections=32,
    )
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        config=config,
    )


def iter_webp_files(root: Path):
    for p in root.rglob("*.webp"):
        if p.is_file():
            yield p


def make_key(root: Path, file_path: Path, remote_prefix: str) -> str:
    rel = file_path.relative_to(root).as_posix()
    return f"{remote_prefix.rstrip('/')}/{rel}"


# -------- NEW: CLEAR REMOTE PREFIX --------

def clear_remote_prefix(s3, bucket: str, prefix: str):
    print(f"Clearing s3://{bucket}/{prefix}/")

    paginator = s3.get_paginator("list_objects_v2")
    to_delete = []

    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix.rstrip('/')}/"):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})

            # Delete in batches of 1000
            if len(to_delete) == 1000:
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": to_delete},
                )
                to_delete.clear()

    if to_delete:
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": to_delete},
        )

    print(f"✔ Cleared prefix: {prefix}")


def upload_dir(s3, local_dir: Path, remote_prefix: str):
    if not local_dir.exists():
        raise RuntimeError(f"Local dir does not exist: {local_dir}")

    uploaded = 0

    for file_path in iter_webp_files(local_dir):
        key = make_key(local_dir, file_path, remote_prefix)

        s3.upload_file(
            Filename=str(file_path),
            Bucket=BUCKET_NAME,
            Key=key,
            ExtraArgs={
                "CacheControl": CACHE_CONTROL,
                "ContentType": CONTENT_TYPE,
            },
        )

        uploaded += 1
        if uploaded % 200 == 0:
            print(f"[{remote_prefix}] Uploaded {uploaded} files...")

    print(f"[{remote_prefix}] Done. Uploaded {uploaded} files.")


def main():
    s3 = make_s3_client()

    for job in UPLOADS:
        clear_remote_prefix(
            s3,
            BUCKET_NAME,
            job["remote_prefix"],
        )
        upload_dir(
            s3,
            job["local_dir"],
            job["remote_prefix"],
        )


if __name__ == "__main__":
    main()
