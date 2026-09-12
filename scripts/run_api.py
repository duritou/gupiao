"""Start Adaptive's API with the shared workspace runtime configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_PYTHON = PROJECT_ROOT.parent / "shared" / "python"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SHARED_PYTHON) not in sys.path:
    sys.path.insert(0, str(SHARED_PYTHON))

from investment_common import load_runtime_env  # noqa: E402

load_runtime_env(PROJECT_ROOT)
from config.settings import settings  # noqa: E402, I001
from src.infrastructure.runtime_identity import (  # noqa: E402
    RuntimeIdentityError,
    validate_startup_if_managed,
)

import uvicorn  # noqa: E402, I001


if __name__ == "__main__":
    reload_requested = os.environ.get("ADAPTIVE_API_RELOAD", "false").lower() == "true"
    if settings.APP_ENV == "production" and reload_requested:
        raise SystemExit("ADAPTIVE_API_RELOAD is forbidden in production")
    try:
        validate_startup_if_managed()
    except RuntimeIdentityError as exc:
        raise SystemExit(f"runtime release validation failed: {exc}") from exc
    uvicorn.run(
        "src.api.app:app",
        host=os.environ.get("ADAPTIVE_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("ADAPTIVE_API_PORT", "8888")),
        reload=reload_requested if settings.APP_ENV != "production" else False,
    )
