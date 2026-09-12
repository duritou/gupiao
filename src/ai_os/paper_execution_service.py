"""Paper-execution boundary for approved decisions.

The ledger implementation remains behind ``MarketDatabase`` for compatibility
with existing installations. This service owns the caller-facing safety
boundary so shadow-only decisions can never reach that ledger method.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class PaperExecutionService:
    """Guard and delegate a paper-trading cycle without scoring decisions."""

    def __init__(self, database: Any | None = None) -> None:
        self.database = database

    def _database(self) -> Any:
        if self.database is None:
            from src.infrastructure.storage.market_database import market_db

            return market_db
        return self.database

    @staticmethod
    def _shadow_rejection(
        decision: dict[str, Any], trade_date: str, execution_at: str,
    ) -> dict[str, Any]:
        code = str(decision.get("stock_code") or "")
        return {
            "signal_date": str(decision.get("date") or trade_date),
            "stock_code": code,
            "stock_name": str(decision.get("stock_name") or code),
            "direction": str(
                decision.get("executable_direction")
                or decision.get("direction")
                or "neutral"
            ).lower(),
            "reason": "shadow_only_decision_not_executable",
            "quote_date": str(decision.get("market_price_date") or ""),
            "quote_source": str(decision.get("market_price_source") or ""),
            "quote_price": float(decision.get("market_price") or 0),
            "execution_at": execution_at,
            "signal_at": str(decision.get("signal_at") or ""),
            "data_cutoff_at": str(decision.get("data_cutoff_at") or ""),
            "quote_exchange_at": str(
                decision.get("market_price_exchange_at") or ""
            ),
        }

    def execute(
        self,
        decisions: list[dict[str, Any]],
        trade_date: str,
        *,
        initial_capital: float = 100000.0,
        max_position_pct: float | None = None,
        execution_timestamp: str | None = None,
        strict_real_data: bool = True,
        trading_day_verified: bool = False,
        is_trading_day: bool = False,
        trading_calendar_source: str = "",
    ) -> dict[str, Any]:
        """Execute only non-shadow decisions through the compatibility ledger."""
        database = self._database()
        execution_at = str(
            execution_timestamp or datetime.now().astimezone().isoformat()
        )
        shadow_decisions = [
            decision
            for decision in decisions
            if decision.get("paper_execution_enabled") is False
        ]
        if shadow_decisions:
            portfolio = database.get_paper_portfolio(as_of_date=trade_date)
            return {
                "cash": round(float(portfolio.get("cash") or 0), 2),
                "position_count": len(portfolio.get("positions") or []),
                "actions": [],
                "execution_status": "shadow_only_not_executable",
                "execution_at": execution_at,
                "rejections": [
                    self._shadow_rejection(decision, trade_date, execution_at)
                    for decision in shadow_decisions
                ],
                "trading_calendar_source": trading_calendar_source,
            }
        kwargs: dict[str, Any] = {
            "initial_capital": initial_capital,
            "execution_timestamp": execution_at,
            "strict_real_data": strict_real_data,
            "trading_day_verified": trading_day_verified,
            "is_trading_day": is_trading_day,
            "trading_calendar_source": trading_calendar_source,
        }
        if max_position_pct is not None:
            kwargs["max_position_pct"] = max_position_pct
        return database.run_paper_strategy(decisions, trade_date, **kwargs)


paper_execution_service = PaperExecutionService()
