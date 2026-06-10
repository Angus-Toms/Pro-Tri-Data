# Email sending via Resend over plain HTTPS. With no API key configured
# (local dev) nothing is sent; the magic link is printed to stdout instead.

import requests

from config import RESEND_API_KEY

FROM_ADDRESS = "Pro Tri Data <login@protridata.com>"


def send_login_email(to, url):
    if not RESEND_API_KEY:
        print(f"LOGIN LINK: {url}", flush=True)
        return
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={
            "from": FROM_ADDRESS,
            "to": [to],
            "subject": "Your Pro Tri Data login link",
            "html": (
                f'<p>Click to log in to Pro Tri Data:</p>'
                f'<p><a href="{url}">{url}</a></p>'
                f'<p>The link is valid for 15 minutes and can be used once. '
                f'If you did not request it, ignore this email.</p>'
            ),
        },
        timeout=10,
    )
    resp.raise_for_status()
