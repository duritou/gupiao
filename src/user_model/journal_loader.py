"""Load the adaptive user model from persisted decisions and paper actions."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from typing import Any

from src.domain.models.trust import RecommendationSnapshot, SignalSnapshot
from src.infrastructure.storage.market_database import market_db
from src.user_model.engine import UserModelEngine, get_user_model_engine


def _signal(name: str, score: Any) -> SignalSnapshot:
    value = float(score or 50)
    direction = "buy" if value >= 60 else "sell" if value <= 40 else "neutral"
    return SignalSnapshot(name=name, score=value, direction=direction)


def _calendar_days(start: str, end: str) -> int | None:
    """Return calendar holding days for ISO dates, or None when malformed."""
    try:
        return max(0, (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days)
    except (TypeError, ValueError):
        return None


def _trade_holding_days(trades: list[dict[str, Any]]) -> dict[int, tuple[int, bool]]:
    """Match paper fills FIFO and return (days, completed_round_trip)."""
    lots: dict[str, deque[tuple[str, int, int]]] = defaultdict(deque)
    result: dict[int, tuple[int, bool]] = {}
    ordered = sorted(
        trades,
        key=lambda row: (str(row.get("trade_date") or ""), str(row.get("created_at") or ""), int(row.get("id") or 0)),
    )
    for trade in ordered:
        code = str(trade.get("stock_code") or "")
        if not code:
            continue
        if str(trade.get("action") or "").upper() == "BUY":
            lots[code].append((
                str(trade.get("trade_date") or ""),
                int(trade.get("id") or 0),
                int(trade.get("shares") or 0),
            ))
            continue
        if str(trade.get("action") or "").upper() != "SELL":
            continue
        remaining = int(trade.get("shares") or 0)
        durations: list[int] = []
        while remaining > 0 and lots[code]:
            entry_date, entry_id, lot_shares = lots[code].popleft()
            held = _calendar_days(entry_date, str(trade.get("trade_date") or ""))
            if held is not None:
                durations.append(held)
            consumed = min(remaining, lot_shares)
            remaining -= consumed
            if consumed < lot_shares:
                lots[code].appendleft((entry_date, entry_id, lot_shares - consumed))
            result[entry_id] = (durations[-1] if durations else 0, True)
        if durations:
            result[int(trade.get("id") or 0)] = (round(sum(durations) / len(durations)), True)
    return result


def load_user_model_from_journal(limit: int = 20000) -> tuple[UserModelEngine, dict[str, Any]]:
    """Refresh the singleton model with auditable journal and paper-trade evidence."""
    decisions = market_db.get_recent_decisions(limit=limit)
    trades = market_db.get_paper_trades(limit=500)
    holding_days = _trade_holding_days(trades)
    ledger_reader = getattr(market_db, "get_paper_ledger_state", None)
    ledger_state = ledger_reader() if callable(ledger_reader) else {}
    ledger_account = (ledger_state or {}).get("account") or {}
    initial_capital = float(ledger_account.get("initial_capital") or 0)
    trade_by_decision: dict[int, dict[str, Any]] = {}
    for trade in reversed(trades):
        decision_id = trade.get("decision_id")
        if decision_id is not None:
            trade_by_decision[int(decision_id)] = trade

    snapshots = []
    decisive_verified_count = 0
    neutral_observed_count = 0
    for decision in decisions:
        trade = trade_by_decision.get(int(decision.get("id") or 0))
        action = str((trade or {}).get("action") or "").upper()
        user_action = "bought" if action == "BUY" else "sold" if action == "SELL" else ""
        outcome_known = bool(decision.get("outcome_known"))
        was_correct = decision.get("was_correct")
        direction = str(decision.get("direction") or "neutral").strip().lower()
        is_decisive = direction in {"buy", "sell"}
        decisive_verified_count += int(outcome_known and is_decisive)
        neutral_observed_count += int(outcome_known and not is_decisive)
        final_verdict = (
            "correct" if outcome_known and is_decisive and bool(was_correct)
            else "wrong" if outcome_known and is_decisive
            else "pending"
        )
        actual_return = float(decision.get("actual_return") or 0) * 100
        snapshot = RecommendationSnapshot(
            id=str(decision.get("id") or ""),
            created_at=str(decision.get("created_at") or ""),
            stock_code=str(decision.get("stock_code") or ""),
            stock_name=str(decision.get("stock_name") or ""),
            direction=direction,
            price_at_rec=float((trade or {}).get("price") or 0),
            ai_score=float(decision.get("ai_score") or 50),
            ai_confidence=float(decision.get("confidence") or 0),
            signals=[
                _signal("MACD", decision.get("macd_score")),
                _signal("RSI", decision.get("rsi_score")),
                _signal("KDJ", decision.get("kdj_score")),
                _signal("MA", decision.get("ma_score")),
                _signal("Volume", decision.get("volume_score")),
            ],
            recommendation_text=str(decision.get("recommendation") or ""),
            source="adaptive_pipeline",
            ai_version="adaptive-paper-v2",
            user_action=user_action,
            user_action_at=str((trade or {}).get("created_at") or ""),
            user_action_price=float((trade or {}).get("price") or 0),
            final_verdict=final_verdict,
            final_profit_pct=actual_return,
        )
        if trade:
            trade_id = int(trade.get("id") or 0)
            held = holding_days.get(trade_id)
            if held is not None:
                setattr(snapshot, "paper_holding_days", held[0])
                setattr(snapshot, "paper_holding_complete", held[1])
            if initial_capital > 0:
                setattr(
                    snapshot,
                    "paper_position_size_pct",
                    float(trade.get("value") or 0) / initial_capital * 100,
                )
        metadata_reader = getattr(market_db, "get_stock_metadata", None)
        metadata = (
            metadata_reader(
                str(decision.get("stock_code") or ""),
                str(decision.get("date") or ""),
            )
            if callable(metadata_reader)
            else None
        )
        if metadata and metadata.get("industry"):
            setattr(snapshot, "paper_sector", str(metadata["industry"]))
        snapshots.append(snapshot)

    engine = get_user_model_engine()
    engine.load_snapshots(snapshots)
    engine.load_portfolio([market_db.get_paper_portfolio()])
    engine.load_alert_interactions([])
    return engine, {
        "decision_count": len(decisions),
        "paper_action_count": sum(1 for trade in trades if trade.get("decision_id") is not None),
        "paper_trade_count": len(trades),
        "verified_count": decisive_verified_count,
        "observed_count": decisive_verified_count + neutral_observed_count,
        "neutral_observed_count": neutral_observed_count,
        "data_basis": "decision_journal + paper_trade",
    }
