"""End-to-end social pipeline.

Two modes:
  - pre-race  : the same 3 cards built from the precomputed predictions
  - post-race : 4-card carousel from the race-page share designs (podium,
                top ten with splits, fastest splits, best performances), all at 4:5 so Instagram
                accepts them as one carousel

Each card is rendered locally, uploaded to R2 for a public URL, then the
whole set posts as a single carousel on Instagram and as five/four
separate photo posts on Facebook (FB's organic API doesn't support
carousels for Pages, only albums - left as a future improvement).

Eligibility (production): we only post elite/pro programs - no AG, no
junior/U23/youth. Enforced at the runner level so any caller (scheduler,
manual CLI, ad-hoc script) gets the same gate.

Usage:
    python -m social.runner post-race <race_id> [--dry-run] [--no-fb] [--no-ig]
    python -m social.runner pre-race  <race_id> [--dry-run] [--no-fb] [--no-ig]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import re

import pycountry

from ptd_data import queries
from social.post import (
    PostError,
    post_to_facebook, post_carousel_to_instagram,
)
from social.uploader import upload_card
from app.share import cards as share_cards

RACE_URL_BASE = "https://www.protridata.com/race"

# Prog-name allow-list. upcoming_races has no sub_category column, so we
# fall back to matching the program label. For finished races we'd ideally
# check sub_category='elite', but the same allow-list works as a uniform
# filter and keeps both code paths in sync.
ELITE_PROG_NAMES = {"Elite Men", "Elite Women", "Pro Men", "Pro Women"}

MEDALS  = ("\U0001f947", "\U0001f948", "\U0001f949")  # gold/silver/bronze medal
DISC_EMOJI = {"swim": "\U0001f3ca", "bike": "\U0001f6b4", "run": "\U0001f3c3"}
DISC_LABEL = {"swim": "swim", "bike": "bike", "run": "run"}

# DB stores ISO alpha-3 for most countries (DEU, CHE, NLD ...). The handful
# that don't round-trip cleanly through pycountry either map to a current
# code that does (TPE -> TWN, ISV -> VIR, UNK -> XK) or have no living flag
# (dissolved states, World Triathlon team entry, Individual Neutral) and
# should render as no-flag in captions.
_ALPHA3_OVERRIDE = {
    "TPE": "TW",  # Chinese Taipei -> Taiwan
    "ISV": "VI",  # US Virgin Islands
    "UNK": "XK",  # Kosovo (no ISO code, but emoji exists)
}
_NO_FLAG = {"ANT", "CSK", "FRG", "GDR", "INA", "URS", "WTR", "YUG"}


def _country_flag(alpha3: str | None) -> str:
    """Return the country's flag emoji for an alpha-3 code, or '' if unknown.

    Builds the flag from regional-indicator letters: the alpha-2 ISO code
    mapped one-to-one onto the U+1F1E6..U+1F1FF block (so 'US' -> 🇺🇸).
    """
    if not alpha3:
        return ""
    a3 = alpha3.upper()
    if a3 in _NO_FLAG:
        return ""
    alpha2 = _ALPHA3_OVERRIDE.get(a3)
    if alpha2 is None:
        country = pycountry.countries.get(alpha_3=a3)
        if not country:
            return ""
        alpha2 = country.alpha_2
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in alpha2.upper())


def _name_with_flag(athlete: dict) -> str:
    """'Hayden Wilde 🇳🇿', or '@haydenwilde 🇳🇿' when we know their handle
    so the post tags them."""
    name = f"@{athlete['instagram']}" if athlete.get("instagram") else athlete.get("name", "?")
    flag = _country_flag(athlete.get("country_alpha3") or athlete.get("alpha3"))
    return f"{name} {flag}".rstrip()


# Standing brand + sport tags. The third tag is race-specific (built from
# race_handle); we keep this list short so the caption doesn't read like
# a hashtag farm.
STANDING_HASHTAGS = ("#ProTriData", "#Triathlon", "#Tri")


def _race_hashtag(race_handle: str | None) -> str | None:
    """Convert e.g. 'SOKIN T100 San Francisco 26' -> '#SOKINT100SanFrancisco26'.

    Strips everything except alphanumerics so the hashtag is valid on both
    Instagram and Facebook (they ignore tags with punctuation in the body).
    Returns None for empty/whitespace handles so the caption can omit the
    tag rather than emit a bare '#'.
    """
    if not race_handle:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", race_handle)
    return f"#{cleaned}" if cleaned else None


def _hashtag_line(race_handle: str | None) -> str:
    tags = list(STANDING_HASHTAGS)
    rt = _race_hashtag(race_handle)
    if rt:
        tags.append(rt)
    return " ".join(tags)


def _footer(race_id: int, race_handle: str | None) -> list[str]:
    """The 'Full breakdown at ...' link + hashtag line that every caption
    closes with. Returned as a list of lines so callers can slot it into
    their own line layout without thinking about trailing newlines."""
    return [
        f"Full breakdown at {RACE_URL_BASE}/{race_id}",
        "",
        _hashtag_line(race_handle),
    ]


def _race_handle(race_id: int, mode: str) -> str | None:
    """Look up the short race handle ('SOKIN T100 San Francisco 26') for the
    race-specific hashtag. Trying upcoming first for pre-race and races
    first for post-race matches where the row actually lives."""
    if mode == "pre_race":
        info = queries.get_upcoming_race_info(race_id)
    else:
        info = queries.get_race_info(race_id)
    return info.get("race_handle") if info else None


# ─── Card definitions ─────────────────────────────────────────────────────────

@dataclass
class CardSpec:
    name:   str                 # short identifier used in R2 keys
    design: str                 # app.share design key
    fetch:  Callable[[int], dict | None]
    optional: bool = False      # no data skips just this card, not the post


def _share_cards(context_fn) -> list[CardSpec]:
    # One context feeds all three cards; the fetch returns it so the caption
    # builders get podium/legs/top10 in the share-card shape.
    ctx: dict = {}
    def fetch(rid):
        if not ctx:
            rc = context_fn(rid)
            if not rc["podium"]:
                return None
            ctx.update({k: v for k, v in rc.items() if not k.startswith("_")})
            rows = ctx["podium"] + [r for leg in ctx["legs"] for r in leg["rows"]]
            handles = queries.get_instagram_handles({r["athlete_id"] for r in rows})
            for r in rows:
                r["instagram"] = handles.get(r["athlete_id"], "")
        return ctx
    return [
        CardSpec("podium",       "r1_podium",       fetch),
        CardSpec("top10",        "r2b_top10_dense", fetch),
        CardSpec("fastest_legs", "r3_fastest_legs", fetch),
    ]


def _post_race_cards() -> list[CardSpec]:
    specs = _share_cards(share_cards.race_context)
    fetch = specs[0].fetch
    # Ignored races have no ratings; post the rest without this card.
    specs.append(CardSpec("best_perf", "r4_best_perf",
                          lambda rid: (ctx := fetch(rid)) and ctx["best"] and ctx, optional=True))
    return specs


def _pre_race_cards() -> list[CardSpec]:
    return _share_cards(share_cards.predicted_race_context)


# ─── Eligibility ──────────────────────────────────────────────────────────────

def _race_is_elite(race_id: int, mode: str) -> tuple[bool, str]:
    """Return (eligible, reason) for the elite/pro gate.

    For finished races we check `sub_category='elite'` (the strict elite-pro
    cut, excludes Junior/U23/Youth). For upcoming we check `category='elite'`
    (the only category column on upcoming_races) plus the prog_name allow-
    list to drop Junior/U23/Youth. This is the single source of truth so
    manual `python -m social.runner ...` invocations can't bypass it.
    """
    if mode == "pre_race":
        info = queries.get_upcoming_race_info(race_id)
        if not info:
            return False, "race not found"
        if info.get("category") != "elite":
            return False, f"category={info.get('category')!r} (AG)"
    else:
        info = queries.get_race_info(race_id)
        if not info:
            return False, "race not found"
        if info.get("sub_category") != "elite":
            return False, f"sub_category={info.get('sub_category')!r}"
    prog = (info.get("prog_name") or "").strip()
    if prog not in ELITE_PROG_NAMES:
        return False, f"prog_name={prog!r} (not Elite/Pro)"
    return True, ""


# ─── Carousel helpers ─────────────────────────────────────────────────────────

@dataclass
class CarouselOutput:
    image_urls: list[str]
    captions:   list[str]      # caption-per-card (FB single-post mode)
    carousel_caption: str      # combined caption used for the IG carousel
    fb_post_ids: list[str]
    ig_post_id:  str | None


def _render_and_upload(race_id: int, mode: str, specs: list[CardSpec],
                       out_dir: Path
                       ) -> tuple[list[str], dict[str, dict], str | None]:
    """Render + upload each card into `out_dir`. Returns (image_urls,
    payload_by_name, race_title). Returns ([], {}, None) if any card has no
    data. `out_dir` is the caller's responsibility to create + clean up."""
    image_urls = []
    payloads: dict[str, dict] = {}
    race_title = None

    for spec in specs:
        payload = spec.fetch(race_id)
        if not payload:
            print(f"  skip {spec.name}: no data")
            if spec.optional:
                continue
            return [], {}, None
        png_path = out_dir / f"{spec.name}.png"
        png_path.write_bytes(share_cards.render_png(
            spec.design, payload, "solid", "light", size=share_cards.PORTRAIT))
        key = f"social/posts/{race_id}/{mode}/{spec.name}.png"
        image_urls.append(upload_card(png_path, key))
        payloads[spec.name] = payload
        race_title = payload["race_title"]

    return image_urls, payloads, race_title


def _race_label(payload: dict) -> str:
    """Combined 'Race Title - Prog' string used in headings."""
    title = payload["race_title"]
    prog  = (payload.get("prog_name") or payload.get("prog") or "").strip()
    return f"{title} - {prog}" if prog else title


def _format_podium_lines(podium: list[dict]) -> list[str]:
    """3 medal-emoji lines: '🥇 Hayden Wilde 🇳🇿 - 3:11:12'. Gap shown for 2/3."""
    lines = []
    for i, a in enumerate(podium[:3]):
        line = f"{MEDALS[i]} {_name_with_flag(a)} - {a.get('time', '')}"
        behind = a.get("behind", "")
        if behind and i > 0:
            line += f" ({behind})"
        lines.append(line)
    return lines


def _leaders(payload: dict) -> dict[str, dict]:
    return {leg["label"].lower(): leg["rows"][0] for leg in payload["legs"] if leg["rows"]}


def _build_pre_race_caption(race_id: int, payload: dict) -> str:
    """'Yee the favourite to win ... ahead of Wilde and Bergere' headline,
    the predicted podium with medals + flags, then the predicted fastest
    split per discipline."""
    podium = payload["podium"]
    race_label = _race_label(payload)
    if len(podium) >= 3:
        headline = (f"{podium[0]['last']} the favourite to win {race_label} "
                    f"ahead of {podium[1]['last']} and {podium[2]['last']}.")
    else:
        headline = f"{race_label} predictions."
    leaders = _leaders(payload)
    fastest_lines = [f"{DISC_EMOJI[d]} {_name_with_flag(leaders[d])} - {leaders[d]['time']}"
                     for d in ("swim", "bike", "run") if d in leaders]
    parts = [
        headline,
        "",
        "Predicted podium",
        *_format_podium_lines(podium),
        "",
        "Predicted fastest split",
        *fastest_lines,
        "",
        *_footer(race_id, _race_handle(race_id, "pre_race")),
    ]
    return "\n".join(parts)


def _build_post_race_caption(race_id: int, payload: dict) -> str:
    """'Yee wins the ... Fastest splits from Crociani, Lehmann and Yee.'
    headline, the podium with medals + flags, then the fastest leg per
    discipline with discipline emojis."""
    podium = payload["podium"]
    race_label = _race_label(payload)
    leaders = _leaders(payload)

    # Dedupe surnames preserving S/B/R order: one athlete can take two legs.
    seen: set[str] = set()
    ordered = []
    for d in ("swim", "bike", "run"):
        if d in leaders and leaders[d]["last"] not in seen:
            seen.add(leaders[d]["last"])
            ordered.append(leaders[d]["last"])
    headline = f"{podium[0]['name']} wins the {race_label}."
    if len(ordered) > 1:
        headline += f" Fastest splits from {', '.join(ordered[:-1])} and {ordered[-1]}."
    elif ordered:
        headline += f" Fastest splits from {ordered[0]}."

    fastest_lines = [f"{DISC_EMOJI[d]} {_name_with_flag(leaders[d])} - {leaders[d]['time']}"
                     for d in ("swim", "bike", "run") if d in leaders]

    # Biggest rating increase per discipline.
    ratings = queries.get_race_ratings(race_id)
    handles = queries.get_instagram_handles({r["athlete_id"] for r in ratings})
    best_lines = []
    for d in ("swim", "bike", "run"):
        best = max(ratings, key=lambda r: r[f"{d}_change"] or 0)
        if (best[f"{d}_change"] or 0) > 0:
            best_lines.append(f"{DISC_EMOJI[d]} "
                              f"{_name_with_flag({**best, 'instagram': handles.get(best['athlete_id'])})}"
                              f" (+{round(best[f'{d}_change'])})")

    parts = [
        headline,
        "",
        "Podium",
        *_format_podium_lines(podium),
        "",
        "Fastest splits",
        *fastest_lines,
        "",
        *(["Best performances", *best_lines, ""] if best_lines else []),
        *_footer(race_id, _race_handle(race_id, "post_race")),
    ]
    return "\n".join(parts)


def _carousel_caption(mode: str, race_id: int, payloads: dict) -> str:
    if mode == "pre_race":
        return _build_pre_race_caption(race_id, payloads["podium"])
    if mode == "post_race":
        return _build_post_race_caption(race_id, payloads["podium"])
    return ""


def _podium_card_post_caption(payload: dict, race_id: int,
                               race_handle: str | None) -> str | None:
    """Post-race FB caption for the actual_podium card. Mirrors the
    pre-race podium narrative: name the winner and the 2nd/3rd contenders
    in one line. We deliberately don't pull the per-discipline best
    performers in here - those have their own dedicated FB posts and
    repeating them dilutes the podium-card focus."""
    podium = payload.get("podium") or []
    if len(podium) < 3:
        return None
    body = (f"{podium[0]['name']} wins {_race_label(payload)} ahead of "
            f"{podium[1]['last']} and {podium[2]['last']}.")
    return "\n".join([body, "", *_footer(race_id, race_handle)])


def _podium_card_pre_caption(payload: dict, race_id: int,
                              race_handle: str | None) -> str | None:
    """Pre-race FB caption for the predicted_podium card. Mirrors the
    single-sentence narrative style of the discipline cards: name the
    favourite and the silver/bronze contenders in one line, then the
    standard breakdown link + hashtags."""
    podium = payload.get("podium") or []
    if len(podium) < 3:
        return None
    body = (f"{podium[0]['name']} is the favourite to win "
            f"{_race_label(payload)} ahead of "
            f"{podium[1]['last']} and {podium[2]['last']}.")
    return "\n".join([body, "", *_footer(race_id, race_handle)])


def _per_card_caption(mode: str, race_id: int, spec_name: str, payload: dict,
                      race_handle: str | None) -> str:
    """Facebook photo caption for a single card. Discipline cards get the
    fastest/best-performance shape requested by the user; the podium /
    overall cards fall back to a short race+kicker shell so they still
    have the link."""
    if mode == "post_race":
        custom = _podium_card_post_caption(payload, race_id, race_handle)
        if custom:
            return custom
    if mode == "pre_race":
        custom = _podium_card_pre_caption(payload, race_id, race_handle)
        if custom:
            return custom
    head   = _race_label(payload)
    kicker = payload.get("kicker", "")
    body   = f"{head}\n{kicker}"
    return "\n".join([body, "", *_footer(race_id, race_handle)])


# ─── Public entry points ──────────────────────────────────────────────────────

def post_race_pack(race_id: int, *, dry_run=False, fb=True, ig=True) -> CarouselOutput | None:
    return _run(race_id, "post_race", _post_race_cards(), dry_run=dry_run, fb=fb, ig=ig)


def pre_race_pack(race_id: int, *, dry_run=False, fb=True, ig=True) -> CarouselOutput | None:
    return _run(race_id, "pre_race", _pre_race_cards(), dry_run=dry_run, fb=fb, ig=ig)


def _run(race_id: int, mode: str, specs: list[CardSpec], *,
         dry_run: bool, fb: bool, ig: bool) -> CarouselOutput | None:
    ok, reason = _race_is_elite(race_id, mode)
    if not ok:
        print(f"  SKIP {mode} {race_id}: not elite/pro ({reason})")
        return None

    # Render cards into a scratch dir - once they're uploaded to R2 (and the
    # post is published from those URLs), the local PNG/HTML pair is dead
    # weight, so we wipe the dir on exit.
    out_dir = Path(tempfile.mkdtemp(prefix=f"social-{mode}-{race_id}-"))
    try:
        image_urls, payloads, race_title = _render_and_upload(
            race_id, mode, specs, out_dir,
        )
        if not image_urls:
            print(f"  ABORT {mode} {race_id}: no cards rendered.")
            return None
        return _publish(race_id, mode, specs, image_urls, payloads,
                        dry_run=dry_run, fb=fb, ig=ig)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def _publish(race_id: int, mode: str, specs: list[CardSpec],
             image_urls: list[str], payloads: dict[str, dict], *,
             dry_run: bool, fb: bool, ig: bool) -> CarouselOutput:
    race_handle = _race_handle(race_id, mode)
    carousel_caption = _carousel_caption(mode, race_id, payloads)
    captions = [_per_card_caption(mode, race_id, s.name, payloads[s.name], race_handle)
                for s in specs if s.name in payloads]
    fb_ids: list[str] = []
    ig_id: str | None = None

    if dry_run:
        print(f"  [dry-run] {mode} {race_id} ({len(image_urls)} cards):")
        for url in image_urls:
            print(f"     {url}")
        print(f"     --- carousel caption ---")
        print(carousel_caption)
        print(f"     ------------------------")
        return CarouselOutput(image_urls, captions, carousel_caption, fb_ids, ig_id)

    # Instagram: one carousel. If it still fails after post.py's retries, we
    # do NOT return None: the scheduler will mark the race complete and move
    # on. Re-posting a stale prediction weeks later is worse than skipping
    # it, and the retry/backoff in post.py already covers transient blips.
    if ig:
        try:
            res = post_carousel_to_instagram(image_urls, carousel_caption)
            ig_id = res.post_id
            print(f"  posted {mode} -> instagram carousel {ig_id}")
        except PostError as e:
            print(f"  FAIL {mode} -> instagram (marking complete, will not retry): {e}", file=sys.stderr)

    # Facebook: one photo post per card (carousels via API are paid/advanced).
    # Temporarily disabled - re-enable by uncommenting the block.
    # if fb:
    #     for url, cap in zip(image_urls, captions):
    #         try:
    #             res = post_to_facebook(url, caption=cap)
    #             fb_ids.append(res.post_id)
    #             print(f"  posted {mode} card -> facebook {res.post_id}")
    #         except PostError as e:
    #             print(f"  FAIL {mode} fb card: {e}", file=sys.stderr)

    return CarouselOutput(image_urls, captions, carousel_caption, fb_ids, ig_id)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Render + publish a race's social post pack.")
    p.add_argument("mode", choices=["post-race", "pre-race"],
                   help="post-race -> 3-card recap. pre-race -> 3-card predictions.")
    p.add_argument("race_id", type=int)
    p.add_argument("--dry-run", action="store_true",
                   help="Render + upload to R2, but don't actually post.")
    p.add_argument("--no-fb", dest="fb", action="store_false")
    p.add_argument("--no-ig", dest="ig", action="store_false")
    args = p.parse_args()

    fn = post_race_pack if args.mode == "post-race" else pre_race_pack
    fn(args.race_id, dry_run=args.dry_run, fb=args.fb, ig=args.ig)


if __name__ == "__main__":
    main()
