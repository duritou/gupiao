"""HiThink request validation, code normalization and field mappings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_A_SHARE_RE = re.compile(r"^(?P<ticker>\d{6})\.(?P<exchange>SH|SZ|BJ)$")
SUPPORTED_ADJUSTMENTS = {"none", "forward", "backward"}
FINANCIAL_PATHS = {
    "income": "/api/a-share/financials/income-statements",
    "balance": "/api/a-share/financials/balance-sheets",
    "cashflow": "/api/a-share/financials/cash-flow-statements",
}
LIMIT_POOL_PATHS = {
    "up": "/api/a-share/special-data/limit-up-pool",
    "limit_up": "/api/a-share/special-data/limit-up-pool",
    "down": "/api/a-share/special-data/limit-down-pool",
    "limit_down": "/api/a-share/special-data/limit-down-pool",
    "break": "/api/a-share/special-data/limit-break-pool",
    "limit_break": "/api/a-share/special-data/limit-break-pool",
}


@dataclass(frozen=True)
class HiThinkPayload:
    data: Any
    capability: str
    endpoint: str
    request_id: str = ""
    data_timestamp_ms: int | None = None
    data_date: str = ""
    is_live: bool = False
    row_count: int = 0
    fetched_at: str = ""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_iso(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=_SHANGHAI).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def date_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=_SHANGHAI)
        return current.astimezone(_SHANGHAI).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return f"{text[:4]}-{text[4:6]}-{text[6:]}" if len(text) == 8 and text.isdigit() else text[:10]


def to_ms(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid_date")
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=_SHANGHAI)
        return int(current.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=_SHANGHAI).timestamp() * 1000)
    text = str(value or "").strip()
    if not text:
        raise ValueError("invalid_date")
    try:
        return to_ms(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"invalid_date:{text[:32]}") from exc


def normalize_thscode(value: str) -> str:
    text = str(value or "").strip().upper()
    if text.isdigit() and len(text) == 6:
        if text.startswith(("6", "9")):
            return f"{text}.SH"
        if text.startswith(("0", "2", "3")):
            return f"{text}.SZ"
        if text.startswith(("4", "8")):
            return f"{text}.BJ"
    match = _A_SHARE_RE.fullmatch(text)
    if match:
        return f"{match.group('ticker')}.{match.group('exchange')}"
    raise ValueError("invalid_thscode")


def normalize_codes(codes: str | list[str] | tuple[str, ...], max_items: int = 100) -> list[str]:
    raw = codes.split(",") if isinstance(codes, str) else list(codes)
    if not raw or len(raw) > max_items:
        raise ValueError("invalid_thscodes_count")
    normalized: list[str] = []
    for item in raw:
        if not str(item or "").strip():
            raise ValueError("invalid_thscode")
        code = normalize_thscode(str(item))
        if code not in normalized:
            normalized.append(code)
    return normalized


def map_symbol(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("thscode", "ticker", "name", "exchange", "asset_type", "list_date", "end_date", "last_trade_date", "currency")}


def map_snapshot(row: dict[str, Any], timestamp_ms: Any) -> dict[str, Any]:
    return {"thscode": row.get("thscode"), "ticker": row.get("ticker"), "last_price": row.get("last_price", row.get("price")), "price_change": row.get("price_change"), "price_change_ratio_pct": row.get("price_change_ratio_pct"), "open_price": row.get("open_price"), "high_price": row.get("high_price"), "low_price": row.get("low_price"), "prev_price": row.get("prev_price"), "volume": row.get("volume"), "turnover": row.get("turnover"), "data_timestamp_ms": timestamp_ms}


def map_bar(row: dict[str, Any]) -> dict[str, Any]:
    return {"date_ms": row.get("date_ms"), "date": timestamp_iso(row.get("date_ms"))[:10], "open": row.get("open_price"), "high": row.get("high_price"), "low": row.get("low_price"), "close": row.get("close_price"), "volume": row.get("volume"), "amount": row.get("turnover")}


def map_financial_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("thscode", "ticker", "period", "period_end_ms", "report_date_ms", "fiscal_year", "fiscal_period", "currency", "basic_eps", "operating_income", "operating_costs", "operating_expenses", "operating_profit", "profit_total", "net_profit", "parent_holder_net_profit", "income_tax_expense", "interest_expenses", "manage_fee", "sales_fee", "research_and_development_expenses", "total_current_assets", "non_current_nets_total", "assets_total", "total_debt", "holder_equity_total", "cash", "accounts_receivable", "act_cash_flow_net", "invest_cash_flow_net", "financing_cash_flow_net", "cash_equivalents_net_addition", "pay_dividends_profits_interest_cash", "pay_fixed_assets_etc_cash")
    return {key: row.get(key) for key in keys}


def map_valuation(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("thscode", "ticker", "name", "pe_ttm", "pe_mrq", "pb_mrq", "ps_ttm", "pcf_ttm")}


def map_pool_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("thscode", "ticker", "name", "is_st", "is_new", "last_price", "price_change_ratio_pct", "limit_up_time", "first_limit_time", "last_limit_time", "limit_up_reason", "continue_day_text", "continue_day_cnt", "seal_money", "max_seal_money", "open_times", "turnover_ratio_pct", "turnover", "concept_list", "change", "buy_value", "sell_value", "net_value", "net_rate", "org_net_value", "hot_money_net_value", "hot_rank", "range_days")
    return {key: row.get(key) for key in keys if key in row}
