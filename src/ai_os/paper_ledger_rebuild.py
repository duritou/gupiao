"""Rebuild a contaminated paper ledger from verified historical market data."""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, time
from typing import Any

from src.ai_os.trading_costs import calculate_trade_costs, quantize_price
from src.ai_os.trading_policy import PAPER_MAX_POSITION_PCT

_SCORE_PATTERN = re.compile(r"(?:ai_)?score=([0-9.]+)")


def _score(trade: dict[str, Any]) -> float:
    match = _SCORE_PATTERN.search(str(trade.get("reason") or ""))
    return float(match.group(1)) if match else 50.0


def _bar_map(bars: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(bar.get("date") or ""): bar
        for bar in bars
        if bar.get("date") and float(bar.get("open") or 0) > 0
    }


def _execution_bar(
    trade: dict[str, Any],
    bars: dict[str, dict[str, Any]],
) -> tuple[str, str, dict[str, Any]]:
    submitted_at = datetime.fromisoformat(str(trade["created_at"]).replace("Z", "+00:00"))
    submitted_date = submitted_at.date().isoformat()
    submitted_time = submitted_at.time().replace(tzinfo=None)
    available_dates = sorted(bars)
    if submitted_time < time(9, 30):
        candidates = [day for day in available_dates if day >= submitted_date]
        mode = "same_day_open_after_pre_market_signal"
    elif submitted_time <= time(15, 0):
        candidates = [day for day in available_dates if day >= submitted_date]
        mode = "same_day_close_proxy_for_intraday_signal"
    else:
        candidates = [day for day in available_dates if day > submitted_date]
        mode = "next_trading_day_open_after_close_signal"
    if not candidates:
        error_context = f"{trade['stock_code']} after {submitted_at.isoformat()}"
        raise ValueError(
            f"no executable historical bar for {error_context}"
        )
    execution_date = candidates[0]
    price_field = "close" if "close_proxy" in mode else "open"
    return execution_date, mode, {**bars[execution_date], "price_field": price_field}


def replay_legacy_trade_intents(
    legacy_trades: list[dict[str, Any]],
    histories: dict[str, list[dict[str, Any]]],
    providers: dict[str, str],
    initial_capital: float = 100_000.0,
) -> dict[str, Any]:
    """Replay original BUY intents with real executable bars and cash limits.

    Cash-reserve SELL rows are not replayed because they were generated from
    the contaminated cash state. The reserve rule is recalculated after every
    real-price fill instead.
    """
    bars_by_code = {code: _bar_map(bars) for code, bars in histories.items()}
    intents: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for trade in sorted(legacy_trades, key=lambda item: (item["created_at"], item["id"])):
        action = str(trade.get("action") or "").upper()
        if action == "SELL" and "restore_min_cash_reserve" in str(trade.get("reason") or ""):
            skipped.append({
                "legacy_trade_id": trade.get("id"),
                "reason": "recomputed_cash_reserve_did_not_require_legacy_sell",
            })
            continue
        if action != "BUY":
            skipped.append({
                "legacy_trade_id": trade.get("id"),
                "reason": f"unsupported_legacy_action:{action}",
            })
            continue
        code = str(trade["stock_code"])
        execution_date, execution_mode, bar = _execution_bar(trade, bars_by_code[code])
        intents.append({
            "legacy": trade,
            "execution_date": execution_date,
            "execution_mode": execution_mode,
            "bar": bar,
            "score": _score(trade),
        })

    cash = float(initial_capital)
    positions: dict[str, dict[str, Any]] = {}
    rebuilt_trades: list[dict[str, Any]] = []
    execution_dates = sorted({intent["execution_date"] for intent in intents})
    for execution_date in execution_dates:
        day_intents = [
            intent for intent in intents if intent["execution_date"] == execution_date
        ]
        mark_field = (
            "close"
            if any("close_proxy" in intent["execution_mode"] for intent in day_intents)
            else "open"
        )
        marked_value = cash
        for code, position in positions.items():
            bar = bars_by_code[code].get(execution_date)
            if not bar or float(bar.get(mark_field) or 0) <= 0:
                raise ValueError(f"missing {mark_field} mark for {code} on {execution_date}")
            marked_value += int(position["shares"]) * float(bar[mark_field])
        min_cash_reserve = marked_value * 0.10

        for intent in sorted(day_intents, key=lambda item: -item["score"]):
            legacy = intent["legacy"]
            code = str(legacy["stock_code"])
            if code in positions or len(positions) >= 5:
                skipped.append({
                    "legacy_trade_id": legacy.get("id"),
                    "reason": "duplicate_or_position_limit",
                })
                continue
            price_field = str(intent["bar"]["price_field"])
            reference_price = float(intent["bar"][price_field])
            buy_price = quantize_price(reference_price * 1.001)
            available_cash = max(0.0, cash - min_cash_reserve)
            budget = min(available_cash, marked_value * PAPER_MAX_POSITION_PCT)
            shares = int(budget // buy_price // 100) * 100
            value = shares * buy_price
            costs = calculate_trade_costs(value, "BUY")
            fee = costs["total_fees"]
            while shares > 0 and value + fee > available_cash:
                shares -= 100
                value = shares * buy_price
                costs = calculate_trade_costs(value, "BUY")
                fee = costs["total_fees"]
            if shares <= 0:
                skipped.append({
                    "legacy_trade_id": legacy.get("id"),
                    "reason": "insufficient_verified_cash",
                })
                continue
            cash -= value + fee
            provider = providers[code]
            execution_mode = str(intent["execution_mode"])
            positions[code] = {
                "stock_code": code,
                "stock_name": legacy.get("stock_name") or code,
                "shares": shares,
                "avg_cost": buy_price,
                "entry_date": intent["execution_date"],
                "eligible_sell_date": intent["execution_date"],
                "entry_price_date": intent["execution_date"],
                "entry_price_source": provider,
                "execution_mode": execution_mode,
                "execution_tier": str(legacy.get("execution_tier") or "normal"),
                "entry_flow_state": str(legacy.get("flow_state") or ""),
                "entry_fallback_status": str(legacy.get("fallback_status") or ""),
                "entry_gate_reasons": legacy.get("gate_reasons") or "[]",
                "probe_expiry_date": str(legacy.get("probe_expiry_date") or ""),
                "promotion_status": str(legacy.get("promotion_status") or "none"),
            }
            rebuilt_trades.append({
                "trade_date": intent["execution_date"],
                "signal_date": legacy.get("trade_date") or "",
                "action": "BUY",
                "stock_code": code,
                "stock_name": legacy.get("stock_name") or code,
                "shares": shares,
                "price": buy_price,
                "value": value,
                "fee": fee,
                "commission": costs["commission"],
                "stamp_tax": costs["stamp_tax"],
                "slippage": shares * (buy_price - reference_price),
                "reason": (
                    f"verified_replay; legacy_trade_id={legacy.get('id')}; "
                    f"score={intent['score']:.1f}; max_position={PAPER_MAX_POSITION_PCT:.0%}; min_cash=10%"
                ),
                "created_at": f"{intent['execution_date']}T"
                f"{'15:00:00' if price_field == 'close' else '09:30:00'}+08:00",
                "signal_at": legacy.get("created_at") or "",
                "price_date": intent["execution_date"],
                "price_source": provider,
                "execution_mode": execution_mode,
                "quote_fetched_at": "historical_rebuild",
                "legacy_trade_id": legacy.get("id"),
                "execution_tier": str(legacy.get("execution_tier") or "normal"),
                "flow_state": str(legacy.get("flow_state") or ""),
                "fallback_status": str(legacy.get("fallback_status") or ""),
                "gate_reasons": legacy.get("gate_reasons") or "[]",
                "promotion_status": str(legacy.get("promotion_status") or ""),
            })

    if cash < -0.005:
        raise ValueError(f"verified replay produced negative cash: {cash}")
    if any(position["shares"] % 100 for position in positions.values()):
        raise ValueError("verified replay produced a non-round-lot position")
    return {
        "cash": cash,
        "positions": list(positions.values()),
        "trades": rebuilt_trades,
        "summary": {
            "initial_capital": initial_capital,
            "cash": cash,
            "position_count": len(positions),
            "trade_count": len(rebuilt_trades),
            "skipped_legacy_trades": skipped,
            "execution_dates": execution_dates,
            "price_sources": sorted(set(providers.values())),
        },
    }


async def fetch_verified_histories(
    codes: list[str],
    count: int = 30,
    quote_source: Any | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Fetch remote histories and reject any local-cache provenance."""
    if quote_source is None:
        from src.infrastructure.market_data.source_manager import source_manager

        quote_source = source_manager
    fetched = await asyncio.gather(
        *(quote_source.get_kline(code, count=count) for code in codes)
    )
    histories: dict[str, list[dict[str, Any]]] = {}
    providers: dict[str, str] = {}
    blocked = ("local", "sqlite", "fallback", "cache", "none", "unknown")
    for code, (bars, provenance) in zip(codes, fetched, strict=True):
        provider = str(provenance.provider or "")
        if (
            not bars
            or not provenance.is_live
            or not provider
            or any(token in provider.lower() for token in blocked)
        ):
            raise RuntimeError(
                f"verified remote history unavailable for {code}: "
                f"provider={provider or 'none'} error={provenance.error_message}"
            )
        histories[code] = bars
        providers[code] = provider
    return histories, providers


def closing_quotes_for_date(
    positions: list[dict[str, Any]],
    histories: dict[str, list[dict[str, Any]]],
    providers: dict[str, str],
    valuation_date: str | None = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Build close/pre-close marks from the same verified remote histories."""
    target = valuation_date or date.today().isoformat()
    quotes: dict[str, dict[str, Any]] = {}
    for position in positions:
        code = str(position["stock_code"])
        eligible = sorted(
            (bar for bar in histories[code] if str(bar.get("date") or "") <= target),
            key=lambda bar: str(bar["date"]),
        )
        if not eligible or str(eligible[-1]["date"]) != target:
            raise ValueError(f"no verified closing bar for {code} on {target}")
        latest = eligible[-1]
        previous = eligible[-2] if len(eligible) > 1 else latest
        quotes[code] = {
            "price": float(latest["close"]),
            "pre_close": float(previous["close"]),
            "data_date": target,
            "source": providers[code],
            "fetched_at": "historical_rebuild",
        }
    return target, quotes
