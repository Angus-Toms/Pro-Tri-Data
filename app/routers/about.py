from pathlib import Path
import json

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BASE_DIR = Path(__file__).resolve().parents[2]
QA_PATH = BASE_DIR / "static" / "about" / "qa.json"
BLOG_DIR = BASE_DIR / "static" / "about" / "blogs"

DEFAULT_QA = [
    {
        "question": "What is Pro Tri Data?",
        "answer": "A data-first home for pro triathlon results, ratings, and race context.",
    },
    {
        "question": "How often is the data updated?",
        "answer": "After each World Triathlon race weekend, with periodic historical refreshes.",
    },
    {
        "question": "Can I compare athletes across eras?",
        "answer": "Yes. The comparison view lines up ratings and head-to-heads across seasons.",
    },
]

DEFAULT_BLOGS = [
    {
        "slug": "ratings-methodology",
        "title": "Ratings methodology, in brief",
        "body": "How the model blends finishing position, field strength, and recent form.",
    },
    {
        "slug": "data-updates",
        "title": "Data updates and what's next",
        "body": "Short notes on the latest refreshes and the roadmap for new features.",
    },
]


def load_qa_items() -> list[dict]:
    if not QA_PATH.exists():
        return DEFAULT_QA

    try:
        raw = json.loads(QA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_QA

    items = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            if question and answer:
                items.append({"question": question, "answer": answer})
    return items or DEFAULT_QA


def parse_blog_file(path: Path) -> dict | None:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    lines = [line.strip() for line in content.splitlines()]
    title = ""
    body_lines = []
    found_title = False

    for line in lines:
        if not line:
            continue
        if not found_title:
            title = line
            found_title = True
        else:
            body_lines.append(line)

    body = " ".join(body_lines).strip()
    if not title:
        title = path.stem.replace("-", " ").title()
    if not body:
        body = "More on this soon."

    teaser = body.split(".")[0].strip()
    if teaser:
        teaser = f"{teaser}."
    else:
        teaser = "More on this soon."

    return {
        "slug": path.stem,
        "title": title,
        "body": body,
        "teaser": teaser,
    }


def load_blogs() -> list[dict]:
    if not BLOG_DIR.exists():
        return [
            {**post, "teaser": post["body"]} for post in DEFAULT_BLOGS
        ]

    posts = []
    for path in sorted(BLOG_DIR.glob("*.txt")):
        post = parse_blog_file(path)
        if post:
            posts.append(post)

    if posts:
        return posts

    return [
        {**post, "teaser": post["body"]} for post in DEFAULT_BLOGS
    ]


def load_blog_by_slug(slug: str) -> dict | None:
    if BLOG_DIR.exists():
        path = BLOG_DIR / f"{slug}.txt"
        if path.exists():
            return parse_blog_file(path)

    for post in DEFAULT_BLOGS:
        if post["slug"] == slug:
            return {
                **post,
                "teaser": post["body"],
            }

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
    if not post:
        return templates.TemplateResponse(
            "404.html",
            {
                "request": request,
                "detail": "Blog post not found",
                "active_page": "about",
            },
            status_code=404,
        )

    context = {
        "request": request,
        "active_page": "about",
        "post": post,
    }
    return templates.TemplateResponse("blog_detail.html", context)
