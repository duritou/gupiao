"""Archive and rebuild the paper account with verified remote market data."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ai_os.paper_ledger_rebuild import (  # noqa: E402
    closing_quotes_for_date,
    fetch_verified_histories,
    replay_legacy_trade_intents,
)
from src.infrastructure.storage.market_database import market_db  # noqa: E402


async def main(apply_changes: bool) -> dict:
    state = market_db.get_paper_ledger_state()
    account = state["account"]
    if account.get("ledger_quality") == "verified_real_prices":
        return {
            "status": "already_verified",
            "portfolio": market_db.get_paper_portfolio(),
        }
    legacy_trades = state["paper_trade"]
    codes = sorted({str(trade["stock_code"]) for trade in legacy_trades})
    histories, providers = await fetch_verified_histories(codes)
    rebuilt = replay_legacy_trade_intents(
        legacy_trades,
        histories,
        providers,
        initial_capital=float(account["initial_capital"]),
    )
    valuation_date, quotes = closing_quotes_for_date(
        rebuilt["positions"], histories, providers
    )
    result = {
        "status": "dry_run",
        "valuation_date": valuation_date,
        "rebuilt": rebuilt,
        "providers": providers,
    }
    if not apply_changes:
        return result

    replacement = market_db.archive_and_replace_paper_ledger(
        rebuilt,
        reason=(
            "legacy paper fills used stale market_daily prices; rebuilt from "
            "verified remote executable OHLC with cash/position constraints"
        ),
    )
    mark = market_db.mark_paper_portfolio(valuation_date, quotes)
    result.update({
        "status": "applied",
        "replacement": replacement,
        "portfolio_mark": mark,
        "portfolio": market_db.get_paper_portfolio(valuation_date),
    })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="archive the current ledger and install the verified replay",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(args.apply)), ensure_ascii=False, indent=2))
