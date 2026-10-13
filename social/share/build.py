"""Share-card drafts: render every design in every mode for one race to
debug/share_cards/ plus a contact sheet.

Run:  .venv/bin/python -m social.share.build [race_id] [athlete_id]
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.share.cards import DESIGNS, STATIC_URI, athlete_context, race_context, render_html

ROOT    = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "debug" / "share_cards"

# (mode, ink) combinations rendered for every design.
VARIANTS = [
    ("solid", "light"),        # navy card, white text
    ("solid", "dark"),         # cream card, navy text
    ("photo", "light"),        # user photo + scrim
    ("transparent", "light"),  # alpha PNG, white text with shadow
]


# ─── render ──────────────────────────────────────────────────────────────────

def placeholder_photo(page) -> str:
    """Stand-in for the user's own image: a moody gradient with grain, so the
    scrim and text-shadow treatment can be judged without a real photo."""
    page.set_viewport_size({"width": 1080, "height": 1920})
    page.set_content("""<body style="margin:0"><div style="width:1080px;height:1920px;
      background:
        radial-gradient(ellipse at 30% 25%, #6b7a99 0%, transparent 55%),
        radial-gradient(ellipse at 75% 70%, #c97a3a 0%, transparent 50%),
        linear-gradient(180deg,#2b3550 0%,#141a2a 60%,#0b0e18 100%)"></div>
      <svg style="position:absolute;inset:0;mix-blend-mode:overlay;opacity:.5" width="1080" height="1920">
        <filter id="n"><feTurbulence baseFrequency=".9" numOctaves="2"/></filter>
        <rect width="100%" height="100%" filter="url(#n)"/></svg></body>""")
    png = page.screenshot(full_page=True)
    return "data:image/png;base64," + base64.b64encode(png).decode()


def main(race_id: int = 655047, athlete_id: int = 96742, extra_athlete: int | None = 71738):
    rc = race_context(race_id)
    contexts = {
        "race":    {k: v for k, v in rc.items() if not k.startswith("_")},
        "athlete": athlete_context(rc, athlete_id),
    }
    if extra_athlete:
        contexts["athlete_b"] = athlete_context(rc, extra_athlete)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        photo = placeholder_photo(page)

        for design, (_, (w, h), subject_kind, _) in DESIGNS.items():
            subjects = ["race"] if subject_kind == "race" else ["athlete"] + (["athlete_b"] if extra_athlete else [])
            for subject in subjects:
                for mode, ink in VARIANTS:
                    if subject == "athlete_b" and (mode, ink) != ("solid", "light"):
                        continue
                    name = f"{design}__{subject}__{mode}-{ink}"
                    html, _, _ = render_html(design, contexts[subject], mode, ink, photo)
                    html_path = OUT_DIR / f"{name}.html"
                    html_path.write_text(html)
                    page.set_viewport_size({"width": w, "height": h})
                    page.goto(html_path.as_uri(), wait_until="networkidle")
                    page.evaluate("document.fonts.ready")
                    out = OUT_DIR / f"{name}.png"
                    page.locator("#card").screenshot(path=str(out), omit_background=(mode == "transparent"))
                    manifest.append((design, subject, mode, ink, out.name, w, h))
                    print("rendered", name)
        browser.close()

    # Contact sheet: one row per design, transparent cards shown over a checkerboard
    rows = []
    for design in DESIGNS:
        cells = "".join(
            f'<figure class="{m}"><img src="{fn}" style="aspect-ratio:{w}/{h}"><figcaption>{s} · {m} · {i}</figcaption></figure>'
            for d, s, m, i, fn, w, h in manifest if d == design)
        rows.append(f"<section><h2>{design}</h2><div class=row>{cells}</div></section>")
    (OUT_DIR / "index.html").write_text(f"""<!doctype html><meta charset=utf-8><title>Share card drafts</title>
<style>body{{font-family:-apple-system,sans-serif;background:#ddd;margin:0;padding:24px}}
h2{{margin:32px 0 8px;font-size:15px;font-family:ui-monospace,monospace}}
.row{{display:flex;gap:16px;overflow-x:auto}} figure{{margin:0;flex:0 0 auto}}
img{{width:270px;display:block;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.2)}}
.transparent img{{background:repeating-conic-gradient(#bbb 0 25%,#eee 0 50%) 0 0/24px 24px}}
figcaption{{font-size:11px;color:#555;margin-top:4px;font-family:ui-monospace,monospace}}</style>
{''.join(rows)}""")
    print("contact sheet:", OUT_DIR / "index.html")


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    main(*args)
