"""Unified Market Data Models — v7.5.

AI only sees these models. Never raw provider dicts.
Every provider's output is normalized into these standard types.

Design principle: AI code imports from here, not from source_manager.
The Capability Router + Normalizer absorb all provider differences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MarketQuote:
    """Unified real-time/daily quote — any provider normalizes to this."""
    code: str = ""                   # "000725.SZ"
    name: str = ""                   # "京东方A"
    price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0
    change_pct: float = 0.0
    change_amount: float = 0.0
    volume: float = 0.0
    amount: float = 0.0              # 成交额(元)
    amount_yi: float = 0.0           # 成交额(亿元)
    turnover: float = 0.0            # 换手率(%)
    pe: float = 0.0                  # 市盈率
    pb: float = 0.0                  # 市净率
    total_market_cap: float = 0.0    # 总市值

    # Provenance
    source: str = ""                 # "tushare" / "baostock"
    source_name: str = ""            # "Tushare Pro"
    fetched_at: str = ""
    data_date: str = ""              # Which trading day this data is from
    is_realtime: bool = False        # True = intraday, False = EOD
    trust_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name,
            "price": self.price, "open": self.open,
            "high": self.high, "low": self.low,
            "pre_close": self.pre_close,
            "change_pct": round(self.change_pct, 2),
            "change_amount": round(self.change_amount, 2),
            "volume": self.volume, "amount": self.amount,
            "amount_yi": self.amount_yi,
            "turnover": round(self.turnover, 2),
            "pe": round(self.pe, 2), "pb": round(self.pb, 2),
            "total_market_cap": self.total_market_cap,
            "source": self.source, "source_name": self.source_name,
            "fetched_at": self.fetched_at[:19] if self.fetched_at else "",
            "data_date": self.data_date,
            "is_realtime": self.is_realtime,
            "trust_score": round(self.trust_score, 4),
        }


@dataclass
class KlineBar:
    """Unified daily K-line bar — any provider normalizes to this."""
    date: str = ""                   # "2026-07-04"
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "open": self.open, "high": self.high,
            "low": self.low, "close": self.close,
            "volume": self.volume, "amount": self.amount,
        }


@dataclass
class KlineSeries:
    """A series of K-line bars with provenance."""
    code: str = ""
    bars: list[KlineBar] = field(default_factory=list)
    source: str = ""
    source_name: str = ""
    trust_score: float = 0.0
    fetched_at: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "bars": [b.to_dict() for b in self.bars],
            "source": self.source, "source_name": self.source_name,
            "trust_score": round(self.trust_score, 4),
            "fetched_at": self.fetched_at[:19] if self.fetched_at else "",
            "count": len(self.bars),
        }

    def to_ohlcv_lists(self) -> dict[str, list[float]]:
        """Convert to lists for signal computation."""
        return {
            "dates": [b.date for b in self.bars],
            "opens": [b.open for b in self.bars],
            "highs": [b.high for b in self.bars],
            "lows": [b.low for b in self.bars],
            "closes": [b.close for b in self.bars],
            "volumes": [b.volume for b in self.bars],
        }


# ================================================================
# Provider Capability Declaration
# ================================================================

@dataclass
class ProviderCapability:
    """What a provider CAN do. Declared once at registration time."""
    provider: str = ""

    # Market coverage
    markets: list[str] = field(default_factory=list)  # ["CN", "US", "HK"]

    # Data types
    realtime_quote: bool = False    # Intraday quotes
    daily_kline: bool = False       # Daily OHLCV
    minute_kline: bool = False      # 1min/5min/15min/60min bars
    weekly_kline: bool = False
    monthly_kline: bool = False

    # Fundamental data
    financial_statements: bool = False  # Income/Balance/Cash Flow
    financial_indicators: bool = False  # PE/PB/ROE/...
    dividend_data: bool = False
    shareholder_data: bool = False

    # Other
    index_data: bool = False
    sector_data: bool = False
    news: bool = False
    announcements: bool = False
    macro_data: bool = False
    fund_flow: bool = False
    block_trade: bool = False

    # Quality flags
    requires_auth: bool = False
    rate_limited: bool = False
    data_quality: str = "basic"     # excellent / good / basic

    def has(self, capability: str) -> bool:
        """Check if provider supports a named capability."""
        return getattr(self, capability, False)

    def supports_market(self, market: str) -> bool:
        """Check if provider covers a specific market."""
        return market in self.markets


# ================================================================
# Provider Capability Registry
# ================================================================

# Central registry of what each provider CAN do.
# Used by the Capability Router to match requests to providers.
# New providers just add an entry here — no code changes needed.

PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "ifind": ProviderCapability(
        provider="ifind",
        markets=["CN"],
        realtime_quote=True,
        daily_kline=True,
        minute_kline=True,
        financial_statements=True,
        financial_indicators=True,
        news=True,
        announcements=True,
        index_data=True,
        sector_data=True,
        requires_auth=True,
        rate_limited=True,
        data_quality="excellent",
    ),
    "mootdx": ProviderCapability(
        provider="mootdx",
        markets=["CN"],
        realtime_quote=True,
        daily_kline=True,
        minute_kline=True,
        index_data=True,
        data_quality="excellent",
    ),
    "tushare": ProviderCapability(
        provider="tushare",
        markets=["CN"],
        daily_kline=True,
        financial_indicators=True,
        financial_statements=True,
        dividend_data=True,
        shareholder_data=True,
        index_data=True,
        sector_data=True,
        requires_auth=True,
        rate_limited=True,
        data_quality="excellent",
    ),
    "akshare": ProviderCapability(
        provider="akshare",
        markets=["CN"],
        realtime_quote=True,
        daily_kline=True,
        minute_kline=True,
        financial_indicators=True,
        index_data=True,
        sector_data=True,
        fund_flow=True,
        block_trade=True,
        news=False,
        data_quality="good",
    ),
    "baostock": ProviderCapability(
        provider="baostock",
        markets=["CN"],
        daily_kline=True,
        weekly_kline=True,
        monthly_kline=True,
        financial_indicators=True,  # Basic only
        index_data=True,
        data_quality="good",
    ),
    "polygon": ProviderCapability(
        provider="polygon",
        markets=["US"],
        realtime_quote=True,
        daily_kline=True,
        minute_kline=True,
        financial_statements=True,
        index_data=True,
        news=True,
        requires_auth=True,
        rate_limited=True,
        data_quality="excellent",
    ),
    "finnhub": ProviderCapability(
        provider="finnhub",
        markets=["US"],
        realtime_quote=True,
        daily_kline=True,
        minute_kline=True,
        financial_statements=True,
        news=True,
        requires_auth=True,
        data_quality="excellent",
    ),
    "fmp": ProviderCapability(
        provider="fmp",
        markets=["US"],
        realtime_quote=True,
        daily_kline=True,
        financial_statements=True,
        financial_indicators=True,
        requires_auth=True,
        rate_limited=True,
        data_quality="excellent",
    ),
    "twelvedata": ProviderCapability(
        provider="twelvedata",
        markets=["US"],
        realtime_quote=True,
        daily_kline=True,
        minute_kline=True,
        requires_auth=True,
        rate_limited=True,
        data_quality="good",
    ),
    "alphavantage": ProviderCapability(
        provider="alphavantage",
        markets=["US"],
        realtime_quote=True,
        daily_kline=True,
        financial_statements=True,
        requires_auth=True,
        rate_limited=True,
        data_quality="good",
    ),
}
