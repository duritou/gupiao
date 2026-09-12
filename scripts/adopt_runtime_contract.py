"""Explicitly adopt the current runtime contract during an off-hours deployment."""

from __future__ import annotations

import argparse
import json
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

from src.ai_os.strategy_version import create_runtime_identity  # noqa: E402
from src.infrastructure.storage.market_database import market_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adopt the current Adaptive runtime identity in the local DB."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm this is an approved off-hours deployment change.",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("以 --confirm 明确确认仅在计划停机/非交易窗口执行")
    identity = market_db.adopt_runtime_contract(create_runtime_identity())
    print(json.dumps(identity, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
