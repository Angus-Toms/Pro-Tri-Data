import os
import time
from pathlib import Path

PROJECT_ROOT_FOR_ENV = Path(__file__).resolve().parent


def load_dotenv(path: Path = PROJECT_ROOT_FOR_ENV / ".env") -> None:
    """Load KEY=VALUE lines from the project-root .env into the environment
    (existing variables win). Holds the R2 token and Meta API keys, so any
    script that imports config can talk to Cloudflare without a shell source."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent

# Local dev reads secrets from the git-ignored .env; real environment
# variables (Render in prod) always win.
_ENV_FILE = PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _key, _sep, _value = _line.partition("=")
        if _sep and not _line.lstrip().startswith("#"):
            os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_IMG_DIR = STATIC_DIR / "imgs"
RUNTIME_DATA_DIR = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "ptd_data"))
ENV = os.getenv("PTD_ENV", "local").lower()
STATIC_BASE_URL = (
    "https://www.static.protridata.com/"
    if ENV in {"prod", "production"}
    else "/static/"
)
SITE_BASE_URL = (
    "https://protridata.com"
    if ENV in {"prod", "production"}
    else "http://localhost:8000"
)

# User-system Postgres. Local dev defaults to the Homebrew instance; prod must
# set DATABASE_URL explicitly - crash at import rather than run without it.
# The role is taken from the real uid rather than left to libpq's USER/LOGNAME
# lookup, which app launchers sometimes leave unset or wrong.
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
    if ENV in {"prod", "production"}:
        raise RuntimeError("DATABASE_URL must be set in production")
    import pwd
    DATABASE_URL = f"postgresql://{pwd.getpwuid(os.getuid()).pw_name}@localhost:5432/ptd_users"

# Resend email API key. Unset means dev mode: magic links are printed to stdout.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
# Sender address. Must be on a domain verified in Resend; until protridata.com
# is verified, "Pro Tri Data <onboarding@resend.dev>" works but only delivers to
# the Resend account owner's own address.
EMAIL_FROM = os.getenv("EMAIL_FROM", "Pro Tri Data <login@protridata.com>")

# Signs unsubscribe links in emails. Prod must set it; changing it breaks links
# in emails already sent.
SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    if ENV in {"prod", "production"}:
        raise RuntimeError("SECRET_KEY must be set in production")
    SECRET_KEY = "local-dev-secret"


def _compute_asset_version() -> str:
    """Max mtime across static/css + static/js. Appended as ?v=... so
    browsers and CDNs refetch when any css/js changes."""
    files = list((STATIC_DIR / "css").glob("*.css")) + list((STATIC_DIR / "js").glob("*.js"))
    latest = max((p.stat().st_mtime for p in files), default=time.time())
    return str(int(latest))


# Computed once at import; pinned for the process lifetime so all routers
# share the same value.
ASSET_VERSION = _compute_asset_version()

# Runtime data (local: ./ptd_data, prod: /var/lib/ptd via DATA_ROOT)
RUNTIME_ATHLETE_IMAGES_DIR = RUNTIME_DATA_DIR / "athlete_imgs"

# DuckDB
DB_PATH = RUNTIME_DATA_DIR / "ptd.duckdb"

# WorldTriathlon API
WORLD_TRIATHLON_API_KEY = "aac0df989cb613114241670ca2f5ff75"

# Admin tool (/admin/*). Long random secret from .env; visiting
# /admin/login?token=<ADMIN_TOKEN> once sets the cookie. Unset = admin
# routes 404 like any unknown page.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# IndexNow. Bing verifies ownership by fetching this key back from the domain
# root, so /<key>.txt must stay publicly reachable (served by routers/robots.py)
# and must match the key sent when pinging the IndexNow API.
INDEXNOW_KEY = "41a7559f57e14a1a8e3cbf17dc8146c5"

# Deployment (Hetzner CX23, see deploy/hetzner/)
CF_BUCKET    = "ptd-static-assets"
PROD_SSH     = "ptd@77.42.41.185"
PROD_DB      = "/var/lib/ptd/ptd.duckdb"
PROD_APP_DIR = "/opt/ptd"

