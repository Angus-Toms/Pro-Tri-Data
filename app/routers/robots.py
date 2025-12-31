from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

router = APIRouter()


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"""User-agent: *
Allow: /

# Block common attack / noise paths
Disallow: /wp-admin/
Disallow: /wp-login.php/
Disallow: /wordpress/
Disallow: /xmlrpc.php/

# Sitemap
Sitemap: {base_url}/sitemap.xml
"""

@router.get("/sitemap.xml")
async def sitemap_xml(request: Request) -> Response:
    base_url = str(request.base_url).rstrip("/")
    paths = [
        "/",
        "/athletes",
        "/leaderboard",
        "/races",
        "/compare",
        "/about",
    ]
    urls = "\n".join(f"  <url><loc>{base_url}{path}</loc></url>" for path in paths)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")
