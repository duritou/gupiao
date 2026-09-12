"""Archive prior fills and enable the no-look-ahead execution policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.storage.market_database import market_db  # noqa: E402

if __name__ == "__main__":
    result = market_db.apply_paper_causality_policy()
    portfolio = market_db.get_paper_portfolio()
    print(json.dumps({
        "migration": result,
        "ledger_version": portfolio["ledger_version"],
        "execution_policy": portfolio.get("execution_policy"),
        "trades": portfolio["trades"],
    }, ensure_ascii=False, indent=2))
