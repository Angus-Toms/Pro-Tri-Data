"""Social-media card rendering and posting pipeline.

Importing config loads the project-root .env, so scripts run from anywhere
pick up R2 credentials and Meta API tokens without a shell `source`.
"""
from __future__ import annotations

from pathlib import Path

import config  # noqa: F401  (loads .env)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
