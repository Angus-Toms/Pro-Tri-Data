from pathlib import Path
import html
import json
import re

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from config import STATIC_BASE_URL

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals["STATIC_BASE_URL"] = STATIC_BASE_URL

BASE_DIR = Path(__file__).resolve().parents[2]
QA_PATH = BASE_DIR / "static" / "about" / "qa.json"
BLOG_DIR = BASE_DIR / "static" / "about" / "blogs"

def load_qa_items() -> list[dict]:
    try:
        raw = json.loads(QA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    items = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            if question and answer:
                items.append({"question": question, "answer": answer})
    return items


def render_emphasis(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
    return text


def render_inline(text: str) -> str:
    parts = []
    last_index = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        start, end = match.span()
        if start > last_index:
            chunk = html.escape(text[last_index:start])
            parts.append(render_emphasis(chunk))
        link_text = render_emphasis(html.escape(match.group(1)))
        link_url = html.escape(match.group(2), quote=True)
        parts.append(f'<a href="{link_url}" rel="noopener">{link_text}</a>')
        last_index = end

    if last_index < len(text):
        chunk = html.escape(text[last_index:])
        parts.append(render_emphasis(chunk))

    return "".join(parts)


def render_blog_html(lines: list[str]) -> str:
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            formatted = [render_inline(line.strip()) for line in paragraph_lines]
            blocks.append(f"<p>{'<br>'.join(formatted)}</p>")
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items, list_type
        if list_items and list_type:
            items_html = "".join(f"<li>{render_inline(item)}</li>" for item in list_items)
            blocks.append(f"<{list_type}>{items_html}</{list_type}>")
        list_items = []
        list_type = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        unordered = stripped.startswith("- ") or stripped.startswith("* ")
        ordered = re.match(r"^\d+\.\s+", stripped) is not None

        if unordered or ordered:
            flush_paragraph()
            item_text = stripped[2:].strip() if unordered else re.sub(r"^\d+\.\s+", "", stripped)
            next_type = "ul" if unordered else "ol"
            if list_type and list_type != next_type:
                flush_list()
            list_type = next_type
            list_items.append(item_text)
            continue

        flush_list()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()

    return "\n".join(blocks)


def build_blog_teaser(lines: list[str]) -> str:
    cleaned_lines = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        stripped = re.sub(r"(\*\*|__)(.+?)\1", r"\2", stripped)
        stripped = re.sub(r"(\*|_)(.+?)\1", r"\2", stripped)
        cleaned_lines.append(stripped)

    body_text = " ".join(cleaned_lines).strip()
    if not body_text:
        return "More on this soon."

    teaser = body_text.split(".")[0].strip()
    if teaser:
        return f"{teaser}."
    return "More on this soon."


def parse_blog_file(path: Path) -> dict | None:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    raw_lines = content.splitlines()
    title = ""
    body_lines = []
    found_title = False

    for line in raw_lines:
        if not line.strip():
            if found_title:
                body_lines.append(line)
            continue
        if not found_title:
            title = line.strip()
            found_title = True
        else:
            body_lines.append(line)

    if not title:
        title = path.stem.replace("-", " ").title()

    body_html = render_blog_html(body_lines)
    teaser = build_blog_teaser(body_lines)

    if not body_html:
        body_html = "<p>More on this soon.</p>"

    return {
        "slug": path.stem,
        "title": title,
        "body_html": body_html,
        "teaser": teaser,
    }


def load_blogs() -> list[dict]:
    posts = []
    for path in sorted(BLOG_DIR.glob("*.txt")):
        post = parse_blog_file(path)
        if post:
            posts.append(post)

    if posts:
        return posts

    return []


def load_blog_by_slug(slug: str) -> dict | None:
    if BLOG_DIR.exists():
        path = BLOG_DIR / f"{slug}.txt"
        if path.exists():
            return parse_blog_file(path)

    return None


@router.get("/about")
async def about(request: Request):
    context = {
        "request": request,
        "active_page": "about",
        "qa_items": load_qa_items(),
        "blogs": load_blogs(),
    }
    return templates.TemplateResponse("about.html", context)


@router.get("/about/blog/{slug}")
async def blog_detail(request: Request, slug: str):
    post = load_blog_by_slug(slug)

    context = {
        "request": request,
        "active_page": "about",
        "post": post,
    }
    return templates.TemplateResponse("blog_detail.html", context)
