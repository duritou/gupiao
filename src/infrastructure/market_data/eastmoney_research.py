"""Compatibility exports for native Eastmoney research adapters."""

from src.infrastructure.market_data.eastmoney_billboard import (
    fetch_eastmoney_dragon_tiger,
    parse_dragon_tiger_records,
    parse_dragon_tiger_seats,
)
from src.infrastructure.market_data.eastmoney_reports import (
    fetch_eastmoney_reports,
    parse_eastmoney_reports,
)

__all__ = [
    "fetch_eastmoney_dragon_tiger",
    "fetch_eastmoney_reports",
    "parse_dragon_tiger_records",
    "parse_dragon_tiger_seats",
    "parse_eastmoney_reports",
]
