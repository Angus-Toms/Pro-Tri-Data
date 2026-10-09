# Email rendering and sending via Resend over plain HTTPS. With no API key
# configured (local dev) nothing is sent; the login link is printed instead.

import hashlib
import hmac

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import EMAIL_FROM, PROJECT_ROOT, RESEND_API_KEY, SECRET_KEY, SITE_BASE_URL

# Emails need an absolute, PNG logo: email apps can't reach localhost and
# several (Outlook) don't show webp.
LOGO_URL = "https://www.static.protridata.com/imgs/favicon-128.png"

env = Environment(loader=FileSystemLoader(PROJECT_ROOT / "templates" / "emails"),
                  autoescape=select_autoescape(["html"]))


def _render(template, subject, preheader, **ctx):
    return env.get_template(template).render(
        subject=subject, preheader=preheader, site=SITE_BASE_URL, logo=LOGO_URL, **ctx)


def _send(to, subject, html, text, headers=None):
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={"from": EMAIL_FROM, "to": [to], "subject": subject,
              "html": html, "text": text, "headers": headers or {}},
        timeout=10,
    )
    if not resp.ok:
        # Resend's JSON body says why (unverified domain, bad key, daily cap ...).
        raise RuntimeError(f"Resend rejected the email ({resp.status_code}): {resp.text}")


# --- login ----------------------------------------------------------------------

def render_login(url):
    subject = "Your login link"
    html = _render("login.html", subject, "Log in to Pro Tri Data. The link works once, for 15 minutes.", url=url)
    text = (f"Log in to Pro Tri Data:\n{url}\n\n"
            "The link works once and expires in 15 minutes. "
            "Didn't ask for this? You can ignore it.")
    return subject, html, text


def send_login_email(to, url):
    if not RESEND_API_KEY:
        print(f"LOGIN LINK: {url}", flush=True)
        return
    _send(to, *render_login(url))


# --- follow updates -------------------------------------------------------------

def unsubscribe_sig(user_id):
    return hmac.new(SECRET_KEY.encode(), f"unsub:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(user_id):
    return f"{SITE_BASE_URL}/email/unsubscribe?u={user_id}&t={unsubscribe_sig(user_id)}"


def updates_subject(results, starts, races):
    """'New results for <athlete>' or 'Start list update for <race>', naming
    the first and counting the rest. Start lists alone say so."""
    def named(first, n):
        return first if n == 1 else f"{first} and {n - 1} other{'s' if n > 2 else ''}"

    athletes = list(dict.fromkeys([r["name"] for r in results] + [s["name"] for s in starts]))
    if athletes:
        noun = "start lists" if not results and not races else "results"
        return f"New {noun} for {named(athletes[0], len(athletes))}"
    titles = list(dict.fromkeys(r["race_title"] for r in races))
    kinds = {r["kind"] for r in races}
    lead = {"results": "New results from", "startlist": "Start list update for"}[kinds.pop()] if len(kinds) == 1 else "Updates on"
    return f"{lead} {named(titles[0], len(titles))}"


def updates_title(results, starts, races):
    """Heading that says what the email is: the one kind of update it holds,
    or a general one when it mixes kinds."""
    kinds = [bool(results), bool(starts), bool(races)]
    if sum(kinds) > 1:
        return "Latest from your follows"
    if races:
        race_kinds = {r["kind"] for r in races}
        if race_kinds == {"results"}:
            return "Results from races you liked"
        if race_kinds == {"startlist"}:
            return "Start lists for races you liked"
        return "Updates on races you liked"
    if results:
        return "New results from athletes you follow"
    return "New start lists for athletes you follow"


def render_updates(user_id, results, starts, races):
    subject = updates_subject(results, starts, races)
    title = updates_title(results, starts, races)
    unsub = unsubscribe_url(user_id)
    html = _render("updates.html", subject, title,
                   title=title, results=results, starts=starts, races=races,
                   show_heads=sum(map(bool, (results, starts, races))) > 1,
                   single_race=len(races) == 1 and not results and not starts,
                   unsubscribe_url=unsub)
    lines = [title, ""]
    if results:
        lines += ["Your athletes"] + [
            f"- {r['name']}: {r['place'] if r['position'] else r['status']}, {r['race_title']} ({r['date']})"
            for r in results] + [""]
    if starts:
        lines += ["Upcoming starts"] + [
            f"- {s['name']}: {s['race_title']} ({s['date']})" + (f", predicted {s['predicted']}" if s["predicted"] else "")
            + (f" ({s['predicted_gap']})" if s["predicted_gap"] else "")
            for s in starts] + [""]
    for race in races:
        lines += [f"{race['race_title']}, {race['prog_name']} ({race['date']})"]
        if race["summary"]:
            lines += [race["summary"]] + (["Predicted podium:"] if race["rows"] else [])
        lines += [f"{p['position']}. {p['name']} {p['time']}" for p in race["rows"]] + [
            f"{'Full results' if race['kind'] == 'results' else 'Start list'}: {SITE_BASE_URL}/race/{race['race_id']}", ""]
    lines += [f"Your athletes: {SITE_BASE_URL}/", f"Unsubscribe: {unsub}"]
    return subject, html, "\n".join(lines), unsub


def send_updates_email(to, user_id, results, starts, races):
    subject, html, text, unsub = render_updates(user_id, results, starts, races)
    if not RESEND_API_KEY:
        print(f"UPDATES EMAIL to {to}: {subject}", flush=True)
        return
    # One-click unsubscribe headers: Gmail and Apple Mail show their own button.
    _send(to, subject, html, text, headers={
        "List-Unsubscribe": f"<{unsub}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    })
