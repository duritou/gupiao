"""Archive historical replay holdings and start a clean forward paper ledger."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.storage.market_database import market_db  # noqa: E402


def main() -> None:
    current = market_db.get_paper_ledger_state()
    account = current["account"]
    if (
        float(account.get("cash") or 0) == 100_000
        and not current.get("paper_position")
        and not current.get("paper_trade")
        and account.get("ledger_quality") == "forward_only_causal_simulation"
    ):
        result = {"status": "already_forward_only", "cash": 100_000.0}
    else:
        result = market_db.archive_and_replace_paper_ledger(
            {
                "cash": 100_000.0,
                "positions": [],
                "trades": [],
                "ledger_quality": "forward_only_causal_simulation",
                "price_policy": "post_signal_quote_plus_0.1pct_slippage",
                "summary": {
                    "migration": "start_forward_only_causal_simulation",
                    "started_at": datetime.now().astimezone().isoformat(),
                    "initial_capital": 100_000.0,
                    "archived_trade_count": len(current.get("paper_trade") or []),
                    "archived_position_count": len(
                        current.get("paper_position") or []
                    ),
                },
            },
            "archive historical replay; start forward-only causal paper account",
        )
        result["status"] = "started_forward_only"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
