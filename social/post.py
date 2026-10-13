"""Publish images to social platforms via their APIs.

Currently supports:
  - Facebook Page  (single photo)
  - Instagram      (single photo, or multi-image carousel)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

GRAPH = "https://graph.facebook.com/v21.0"

# Retry policy. Beyond network/5xx hiccups, the scheduler fires many
# carousels back-to-back so the error we actually hit is Meta's app-level
# rate limit (code 4 / subcode 2207051): transient, clears in tens of
# seconds. Media-not-ready (2207027) is the other one - the readiness poll
# below prevents most of it, this is the backstop. Both want a real wait,
# not a 2s tap, so the backoff is long.
_MAX_ATTEMPTS = 5
_BACKOFF_SECS = (10, 30, 60, 120)  # waits between attempts 1->2 ... 4->5

# Graph error codes / subcodes worth retrying. is_transient on the error
# body is also honoured.
_RETRY_CODES    = {1, 2, 4, 17, 32, 613}
_RETRY_SUBCODES = {2207051, 2207027, 2207001}


class PostError(RuntimeError):
    pass


@dataclass
class PostResult:
    platform: str
    post_id:  str | None
    raw:      dict


# ─── Facebook ─────────────────────────────────────────────────────────────────

def post_to_facebook(image_url: str, caption: str = "") -> PostResult:
    """Publish a photo to the configured PTD Facebook Page.

    Requires env: META_PAGE_ID, META_PAGE_ACCESS_TOKEN.
    """
    page_id = os.getenv("META_PAGE_ID")
    token   = os.getenv("META_PAGE_ACCESS_TOKEN")
    if not page_id or not token:
        raise PostError("META_PAGE_ID and META_PAGE_ACCESS_TOKEN must be set in env.")

    body = _post(f"{GRAPH}/{page_id}/photos",
        {"url": image_url, "message": caption, "access_token": token})
    return _result_dict("facebook", body)


# ─── Instagram ────────────────────────────────────────────────────────────────

def post_to_instagram(image_url: str, caption: str = "") -> PostResult:
    """Publish a single photo to the configured PTD Instagram account.

    Requires env: META_IG_USER_ID, META_PAGE_ACCESS_TOKEN.
    Uses IG's two-step container/publish pattern.
    """
    ig_user, token = _ig_credentials()

    # 1. Create the media container
    creation = _post(f"{GRAPH}/{ig_user}/media", {
        "image_url":    image_url,
        "caption":      caption,
        "access_token": token,
    })
    creation_id = creation["id"]

    # 2. Wait for IG to ingest the image, then publish
    _wait_until_ready(creation_id, token)
    return _result_dict("instagram",
        _post(f"{GRAPH}/{ig_user}/media_publish", {
            "creation_id":  creation_id,
            "access_token": token,
        }))


def post_carousel_to_instagram(image_urls: list[str], caption: str = "") -> PostResult:
    """Publish a multi-image carousel (2–10 photos) to Instagram.

    Three-step flow: build one container per child image (marked
    `is_carousel_item`), then a parent CAROUSEL container that references
    them, then publish the parent.
    """
    if not 2 <= len(image_urls) <= 10:
        raise PostError(f"IG carousel needs 2-10 images, got {len(image_urls)}.")

    ig_user, token = _ig_credentials()

    # 1. Child containers
    child_ids = []
    for url in image_urls:
        body = _post(f"{GRAPH}/{ig_user}/media", {
            "image_url":        url,
            "is_carousel_item": "true",
            "access_token":     token,
        })
        child_ids.append(body["id"])

    # Each child must finish ingesting before it can be referenced by the
    # parent, otherwise the publish 400s with media-not-ready.
    for cid in child_ids:
        _wait_until_ready(cid, token)

    # 2. Parent CAROUSEL container
    parent = _post(f"{GRAPH}/{ig_user}/media", {
        "media_type":   "CAROUSEL",
        "children":     ",".join(child_ids),
        "caption":      caption,
        "access_token": token,
    })

    # 3. Wait for the parent, then publish
    _wait_until_ready(parent["id"], token)
    return _result_dict("instagram",
        _post(f"{GRAPH}/{ig_user}/media_publish", {
            "creation_id":  parent["id"],
            "access_token": token,
        }))


# ─── Internals ────────────────────────────────────────────────────────────────

def _ig_credentials() -> tuple[str, str]:
    ig_user = os.getenv("META_IG_USER_ID")
    token   = os.getenv("META_PAGE_ACCESS_TOKEN")
    if not ig_user or not token:
        raise PostError("META_IG_USER_ID and META_PAGE_ACCESS_TOKEN must be set in env.")
    return ig_user, token


def _should_retry(status: int, body: dict) -> bool:
    if status >= 500:
        return True
    err = body.get("error")
    if not err:
        return False
    if err.get("is_transient"):
        return True
    return err.get("code") in _RETRY_CODES or err.get("error_subcode") in _RETRY_SUBCODES


def _request(method: str, url: str, payload: dict) -> dict:
    """Call the Graph API and return parsed JSON, retrying network errors,
    5xx, and transient Graph errors (rate limits, media-not-ready) with
    backoff. Raises PostError on a non-retryable failure or once attempts
    are exhausted. The caller indexes the returned dict (e.g. body["id"]),
    so a malformed-but-200 response fails fast at the call site."""
    last = ""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            if method == "GET":
                resp = requests.get(url, params=payload, timeout=30)
            else:
                resp = requests.post(url, data=payload, timeout=30)
        except requests.RequestException as e:
            last = f"network error ({e})"
        else:
            try:
                body = resp.json()
            except ValueError:
                raise PostError(f"{url}: non-JSON response ({resp.status_code}): {resp.text[:200]}")
            if resp.status_code < 400 and "error" not in body:
                return body
            last = f"{resp.status_code} {body}"
            if not _should_retry(resp.status_code, body):
                raise PostError(f"{url}: {last}")
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_SECS[attempt])
    raise PostError(f"{url}: giving up after {_MAX_ATTEMPTS} attempts ({last})")


def _post(url: str, data: dict) -> dict:
    return _request("POST", url, data)


def _wait_until_ready(creation_id: str, token: str, *,
                      timeout: int = 120, interval: int = 5) -> None:
    """Block until IG finishes ingesting a media container. media_publish
    400s with 'Media ID is not available' (subcode 2207027) if called before
    the container reports FINISHED, so we poll status_code first."""
    waited = 0
    while True:
        body = _request("GET", f"{GRAPH}/{creation_id}",
                        {"fields": "status_code", "access_token": token})
        status = body.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise PostError(f"container {creation_id} processing {status}: {body}")
        if waited >= timeout:
            raise PostError(f"container {creation_id} not ready after {timeout}s (status={status})")
        time.sleep(interval)
        waited += interval


def _result_dict(platform: str, body: dict) -> PostResult:
    return PostResult(platform=platform, post_id=body.get("post_id") or body.get("id"), raw=body)
