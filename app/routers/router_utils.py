# Formatting functions for FastAPI routers

from datetime import datetime, timezone


def rel_time(dt: datetime) -> str:
    """Coarse relative timestamp for comments and feed entries."""
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:        return "just now"
    if seconds < 3600:      return f"{seconds // 60}m ago"
    if seconds < 86400:     return f"{seconds // 3600}h ago"
    if seconds < 30*86400:  return f"{seconds // 86400}d ago"
    return dt.strftime("%d %b %Y")

# SVG chevron arrows - stroke-based so they scale cleanly with font size
# and align geometrically rather than relying on Unicode glyph metrics.
_SVG_UP   = ('<svg class="chg-arrow" viewBox="0 0 10 8" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true">'
             '<polyline points="1,6.5 5,1.5 9,6.5"/></svg>')
_SVG_DOWN = ('<svg class="chg-arrow" viewBox="0 0 10 8" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true">'
             '<polyline points="1,1.5 5,6.5 9,1.5"/></svg>')
def format_time(seconds: int) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format.""" 
    if seconds == 0: return ""
       
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    else:
        return f"{mins:02d}:{secs:02d}"
 
def format_time_behind(seconds_behind: int) -> str:
    if seconds_behind is None:
        return ""

    if seconds_behind == 0:
        return ""
    
    time_fmt = format_time(seconds_behind)
    return f"+{time_fmt}"
    
def format_rating(rating):
    # Debut athletes (e.g. on an upcoming-race start list) have no rating yet;
    # pass None through so templates render a blank/dash rather than crashing.
    if rating is None:
        return None
    return int(round(rating))

def format_rating_change(change: float) -> dict:
    """
    Format rating change to str and provide css-class based on cardinality.
    `raw` is included so templates can expose the numeric value (e.g. via a
    data attribute) for sorting on change instead of value.
    """
    if change is None or change == float('-inf'):
        return {"formatted_str": "", "css_class": "no-data",     "raw": None}

    if change == 0:
        return {"formatted_str": "",                              "css_class": "rating-neutral",  "raw": 0}

    if change > 0:
        return {"formatted_str": f"{_SVG_UP}{int(round(change))}", "css_class": "rating-increase", "raw": change}

    return     {"formatted_str": f"{_SVG_DOWN}{int(round(-change))}", "css_class": "rating-decrease", "raw": change}

def format_1yr_rating_change(change: float) -> dict:
    """
    Format 1 year rating change, different to standard formatting to catch zero changes
    """
    if change is None:
        return {"formatted_str": "", "css_class": ""}

    if change == 0:
        return {
            "formatted_str": "",
            "css_class": ""
        }

    if change > 0:
        return {
            "formatted_str": f"{_SVG_UP}{int(round(change))}",
            "css_class": "positive"
        }

    return {
        "formatted_str": f"{_SVG_DOWN}{int(round(-change))}",
        "css_class": "negative"
    }

# --- avatars ------------------------------------------------------------------
# Users without a photo get their initial on a tone picked from their id, so a
# person keeps the same colour everywhere. Muted tones keep orange meaning "action".
_AVATAR_TONES = ["#1a1a2e", "#475569", "#0f766e", "#9a3412", "#4338ca", "#7c2d12"]


def avatar_tone(user_id):
    return _AVATAR_TONES[user_id % len(_AVATAR_TONES)]


def user_avatar(user_id, name, version, size="md"):
    from markupsafe import Markup, escape
    if user_id is None:
        # Removed comment: keeps the column shape without pointing at anyone.
        return Markup(f'<span class="avatar avatar-{size} avatar--empty" aria-hidden="true"></span>')
    if version:
        return Markup(f'<img class="avatar avatar-{size}" src="/avatar/{user_id}.webp?v={version}" '
                      f'alt="" loading="lazy">')
    return Markup(f'<span class="avatar avatar-{size}" style="background:{avatar_tone(user_id)}" aria-hidden="true">'
                  f'{escape(name[:1].upper())}</span>')


def athlete_img_url(athlete_id, profile_img):
    from config import STATIC_BASE_URL
    if profile_img:
        return f"{STATIC_BASE_URL}athlete_imgs/128/{athlete_id}.webp"
    return f"{STATIC_BASE_URL}imgs/default_user_64.webp"


def format_course_conditions(raw):
    """Format stored course conditions (queries.get_race_course_conditions)
    for display: disc -> {formatted: ±mm:ss, category}. diff_s is positive
    when the course ran faster than predicted, so it renders with a minus."""
    out = {}
    for disc, v in raw.items():
        sign = '-' if v["diff_s"] >= 0 else '+'
        mins, secs = divmod(abs(round(v["diff_s"])), 60)
        out[disc] = {"formatted": f"{sign}{mins:02d}:{secs:02d}", "category": v["category"]}
    return out


def startlist_change(detail):
    """What changed on a liked race's start list, for the bell and the update
    email: 'start list is out, 52 entries' or 'start list updated, 3 in,
    1 out, 52 entries'."""
    entries = f"{detail['entries']} entr{'y' if detail['entries'] == 1 else 'ies'}"
    if detail["first"]:
        return f"start list is out, {entries}"
    moves = [f"{detail['added']} in"] * bool(detail["added"]) + [f"{detail['removed']} out"] * bool(detail["removed"])
    return f"start list updated, {', '.join(moves + [entries])}"
