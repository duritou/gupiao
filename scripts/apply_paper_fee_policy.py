"""Archive and migrate the active paper ledger to the configured fee policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.storage.market_database import market_db  # noqa: E402

if __name__ == "__main__":
    result = market_db.apply_paper_fee_policy()
    portfolio = market_db.get_paper_portfolio()
    print(json.dumps({
        "migration": result,
        "portfolio": {
            "cash": portfolio["cash"],
            "total_value": portfolio["total_value"],
            "total_pl": portfolio["total_pl"],
            "total_commission": portfolio["total_commission"],
            "total_stamp_tax": portfolio["total_stamp_tax"],
            "total_fees": portfolio["total_fees"],
            "fee_policy": portfolio["fee_policy"],
        },
        "trades": portfolio["trades"],
    }, ensure_ascii=False, indent=2))
