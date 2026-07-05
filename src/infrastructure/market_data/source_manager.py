"""Data Source Manager — v7.4. The truth layer before AI.

Answers: "Where did this data come from, and can I trust it?"

Architecture:
  AkShare ───┐
  Tushare ───┤
  BaoStock ──┤
              ├── SourceManager ──→ Provenance + Data → AI Pipeline
  Cache ──────┤                    (source, ts, trust_score)
              │
  Fallback: NONE. If no live source, tell the user. Never use mock.

Every data point carries DataProvenance — the user ALWAYS knows
where the data came from and how fresh it is.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

from src.infrastructure.market_data.fusion import (
    fusion as data_fusion,
    STANDARD_FEEDS,
    SourceReading,
)


# ================================================================
# Data Provenance — the truth label on every data point
# ================================================================

class SourceProvider(str, Enum):
    AKSHARE = "akshare"
    TUSHARE = "tushare"
    BAOSTOCK = "baostock"
    CACHE = "cache"
    NONE = "none"  # No data available — DO NOT ANALYZE


@dataclass
class DataProvenance:
    """Every data point carries this. Users always know the source."""
    provider: str = ""               # "akshare", "tushare", etc.
    source_name: str = ""            # Human-readable: "东方财富(AkShare)"
    fetched_at: str = ""             # ISO timestamp
    data_age_seconds: float = 0.0
    is_live: bool = False            # True = real market data
    is_cached: bool = False          # True = from cache (still real, just not live)
    cache_age_seconds: float = 0.0
    trust_score: float = 0.0         # 0-1 composite trust
    error_message: str = ""          # Non-empty = data unavailable, DO NOT USE

    @property
    def is_available(self) -> bool:
        return self.provider != "none" and not self.error_message

    @property
    def status_icon(self) -> str:
        if not self.is_available:
            return "🔴"
        if self.is_cached:
            return "🟡"
        if self.data_age_seconds > 120:
            return "🟡"
        return "🟢"

    @property
    def status_label(self) -> str:
        if not self.is_available:
            return "Data Unavailable"
        if self.is_cached:
            age_str = f"{self.cache_age_seconds:.0f}s" if self.cache_age_seconds < 120 else f"{self.cache_age_seconds/60:.1f}min"
            return f"Cached ({age_str} ago)"
        if self.data_age_seconds < 5:
            return "Live"
        return f"Live ({self.data_age_seconds:.0f}s ago)"

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "source_name": self.source_name,
            "fetched_at": self.fetched_at[:19] if self.fetched_at else "",
            "data_age_seconds": round(self.data_age_seconds, 1),
            "is_live": self.is_live,
            "is_cached": self.is_cached,
            "cache_age_seconds": round(self.cache_age_seconds, 1),
            "trust_score": round(self.trust_score, 2),
            "status": self.status_label,
            "available": self.is_available,
            "error": self.error_message,
        }


# ================================================================
# Data Source Protocol
# ================================================================

@dataclass
class SourceCapability:
    """What a data source can provide."""
    realtime_quotes: bool = True
    kline_history: bool = True
    indices: bool = True
    sectors: bool = True
    market_breadth: bool = True
    max_kline_days: int = 365
    rate_limited: bool = False
    requires_auth: bool = False


@dataclass
class SourceStatus:
    """Current health status of a data source."""
    name: str = ""
    is_available: bool = False
    last_check_at: str = ""
    last_success_at: str = ""
    last_error: str = ""
    latency_ms: float = 0.0
    consecutive_failures: int = 0
    total_calls: int = 0
    success_count: int = 0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_calls if self.total_calls else 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.is_available,
            "last_check": self.last_check_at[:19] if self.last_check_at else "",
            "last_success": self.last_success_at[:19] if self.last_success_at else "",
            "last_error": self.last_error[:80],
            "latency_ms": round(self.latency_ms, 1),
            "consecutive_failures": self.consecutive_failures,
            "success_rate": round(self.success_rate, 2),
            "total_calls": self.total_calls,
        }


# ================================================================
# Cache Store (in-memory, swap to Redis later)
# ================================================================

class DataCache:
    """Simple TTL cache for market data. Prevents redundant API calls."""

    def __init__(self):
        self._store: dict[str, tuple[Any, datetime]] = {}
        self._ttl: dict[str, float] = {
            "spot": 30,      # Spot quotes: 30s
            "kline_daily": 300,  # Daily K-line: 5min
            "index": 30,
            "sector": 120,
        }

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        data, ts = entry
        ttl_key = key.split(":")[0] if ":" in key else "default"
        ttl = self._ttl.get(ttl_key, 60)
        if (datetime.now() - ts).total_seconds() > ttl:
            del self._store[key]
            return None
        return data

    def set(self, key: str, data: Any):
        self._store[key] = (data, datetime.now())

    def get_age(self, key: str) -> float:
        entry = self._store.get(key)
        if entry is None:
            return 999999
        return (datetime.now() - entry[1]).total_seconds()

    def clear(self):
        self._store.clear()


# ================================================================
# Source Manager — the truth authority
# ================================================================

class SourceManager:
    """Manages all data sources. Decides WHO to ask and records provenance.

    Priority order:
      1. Cache (if fresh enough)
      2. AkShare (primary, free, comprehensive)
      3. Tushare (backup, requires token)
      4. BaoStock (backup)

    If ALL sources fail → return DataProvenance with error.
    NEVER generate mock data.
    """

    def __init__(self):
        self.cache = DataCache()
        self._sources: dict[str, SourceStatus] = {}
        self._capabilities: dict[str, SourceCapability] = {}
        self._fetch_functions: dict[str, dict[str, Callable]] = {}
        self._init_sources()

    def _init_sources(self):
        """Register available data sources with their capabilities."""
        self._sources["akshare"] = SourceStatus(
            name="akshare",
            is_available=False,  # Will be set on first successful call
        )
        self._capabilities["akshare"] = SourceCapability(
            max_kline_days=365 * 5,
            rate_limited=True,
        )

        self._sources["cache"] = SourceStatus(
            name="cache",
            is_available=True,
        )

    # ================================================================
    # Public API — the only way data enters the system
    # ================================================================

    async def get_realtime_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Get real-time quote with provenance. NEVER returns mock."""
        cache_key = f"spot:quote:{code}"

        # 1. Try cache first
        cached = self.cache.get(cache_key)
        if cached is not None:
            age = self.cache.get_age(cache_key)
            return cached, DataProvenance(
                provider="cache",
                source_name="本地缓存",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age,
                is_live=True,
                is_cached=True,
                cache_age_seconds=age,
                trust_score=0.95 if age < 60 else 0.8,
            )

        # 2. Try akshare
        result, prov = await self._try_akshare_quote(code)
        if result is not None:
            self.cache.set(cache_key, result)
            return result, prov

        # 3. All sources failed
        return None, DataProvenance(
            provider="none",
            source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            data_age_seconds=999999,
            is_live=False,
            trust_score=0.0,
            error_message="所有数据源不可用。请检查网络连接或等待行情恢复。",
        )

    async def get_kline(self, code: str, count: int = 250) -> tuple[list[dict] | None, DataProvenance]:
        """Get K-line data with provenance."""
        cache_key = f"kline_daily:{code}:{count}"

        cached = self.cache.get(cache_key)
        if cached is not None:
            age = self.cache.get_age(cache_key)
            return cached, DataProvenance(
                provider="cache", source_name="本地缓存(K线)",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age if age < 3600 else age,
                is_live=True, is_cached=True, cache_age_seconds=age,
                trust_score=0.9,
            )

        result, prov = await self._try_akshare_kline(code, count)
        if result is not None:
            self.cache.set(cache_key, result)
            return result, prov

        return None, DataProvenance(
            provider="none", source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            is_live=False, trust_score=0.0,
            error_message="无法获取K线数据。",
        )

    async def get_index_quotes(self) -> tuple[list[dict] | None, DataProvenance]:
        """Get major index quotes."""
        cache_key = "index:major"

        cached = self.cache.get(cache_key)
        if cached is not None:
            age = self.cache.get_age(cache_key)
            return cached, DataProvenance(
                provider="cache", source_name="本地缓存(指数)",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age, is_live=True, is_cached=True,
                cache_age_seconds=age, trust_score=0.95,
            )

        result, prov = await self._try_akshare_indices()
        if result is not None:
            self.cache.set(cache_key, result)
            return result, prov

        return None, DataProvenance(
            provider="none", source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            is_live=False, trust_score=0.0,
            error_message="无法获取指数数据。",
        )

    async def get_market_breadth(self) -> tuple[dict | None, DataProvenance]:
        """Get market breadth (up/down counts)."""
        cache_key = "spot:breadth"

        cached = self.cache.get(cache_key)
        if cached is not None:
            age = self.cache.get_age(cache_key)
            return cached, DataProvenance(
                provider="cache", source_name="本地缓存(涨跌)",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age, is_live=True, is_cached=True,
                cache_age_seconds=age, trust_score=0.95,
            )

        result, prov = await self._try_akshare_breadth()
        if result is not None:
            self.cache.set(cache_key, result)
            return result, prov

        return None, DataProvenance(
            provider="none", source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            is_live=False, trust_score=0.0,
            error_message="无法获取涨跌统计。",
        )

    # ================================================================
    # Status & Diagnostics
    # ================================================================

    def get_all_sources_status(self) -> list[dict]:
        return [s.to_dict() for s in self._sources.values()]

    def get_data_freshness(self) -> dict:
        """Get freshness of all cached data keys."""
        freshness = {}
        for key in list(self.cache._store.keys()):
            age = self.cache.get_age(key)
            freshness[key] = {
                "age_seconds": round(age, 1),
                "fresh": age < 60,
                "stale": age > 300,
            }
        return freshness

    def check_health(self) -> dict:
        """Quick health check — can we get live data?"""
        sources_status = self.get_all_sources_status()
        any_available = any(
            s["available"] for s in sources_status if s["name"] != "cache"
        )
        return {
            "live_data_available": any_available,
            "cache_entries": len(self.cache._store),
            "sources": sources_status,
            "recommendation": (
                "Data pipeline healthy" if any_available
                else "No live data source available. AI analysis may be paused."
            ),
        }

    # ================================================================
    # Internal — Provider implementations
    # ================================================================

    async def _try_akshare_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from akshare."""
        source = self._sources["akshare"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import akshare as ak
            raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)

            if df is None or df.empty:
                raise ValueError("Empty response from akshare")

            row = df[df["代码"] == raw_code]
            if row.empty:
                raise ValueError(f"Code {raw_code} not found")

            r = row.iloc[0]
            latency = (datetime.now() - t0).total_seconds() * 1000

            quote = {
                "stock_code": code,
                "stock_name": str(r.get("名称", "")),
                "price": float(r.get("最新价", 0)),
                "change_pct": float(r.get("涨跌幅", 0)),
                "change_amount": float(r.get("涨跌额", 0)),
                "volume": float(r.get("成交量", 0)),
                "amount": float(r.get("成交额", 0)),
                "amount_yi": round(float(r.get("成交额", 0)) / 1e8, 2),
                "high": float(r.get("最高", 0)),
                "low": float(r.get("最低", 0)),
                "open": float(r.get("今开", 0)),
                "pre_close": float(r.get("昨收", 0)),
                "turnover": float(r.get("换手率", 0)),
                "pe": float(r.get("市盈率-动态", 0) if "市盈率-动态" in r else 0),
                "total_market_cap": float(r.get("总市值", 0)),
            }

            # Validate
            from src.infrastructure.market_data.validator import validator
            v = validator.validate_quote(quote, code)
            if v.has_errors:
                raise ValueError(f"Validation failed: {v.errors}")

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return quote, DataProvenance(
                provider="akshare",
                source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.95,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1

            return None, DataProvenance(
                provider="akshare",
                source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"AkShare 获取失败: {str(e)[:100]}",
            )

    async def _try_akshare_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line from akshare."""
        source = self._sources["akshare"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import akshare as ak
            from datetime import date as dt_date

            raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            df = await asyncio.to_thread(
                ak.stock_zh_a_hist,
                symbol=raw_code, period="daily",
                start_date="20200101",
                end_date=dt_date.today().strftime("%Y%m%d"),
                adjust="qfq",
            )

            if df is None or df.empty:
                raise ValueError("Empty K-line response")

            klines = []
            for _, row in df.tail(count).iterrows():
                klines.append({
                    "date": str(row.get("日期", "")),
                    "open": float(row.get("开盘", 0)),
                    "high": float(row.get("最高", 0)),
                    "low": float(row.get("最低", 0)),
                    "close": float(row.get("收盘", 0)),
                    "volume": float(row.get("成交量", 0)),
                    "amount": float(row.get("成交额", 0)),
                    "amount_yi": round(float(row.get("成交额", 0)) / 1e8, 2),
                    "change_pct": float(row.get("涨跌幅", 0)) if "涨跌幅" in row else 0,
                })

            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return klines, DataProvenance(
                provider="akshare",
                source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.95,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1

            return None, DataProvenance(
                provider="akshare",
                source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"AkShare K线获取失败: {str(e)[:100]}",
            )

    async def _try_akshare_indices(self) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting indices from akshare."""
        source = self._sources["akshare"]
        source.total_calls += 1

        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_zh_index_spot_em)

            if df is None or df.empty:
                raise ValueError("Empty index response")

            major = ["上证指数", "深证成指", "创业板指", "科创50"]
            result = []
            for _, row in df.iterrows():
                name = str(row.get("名称", ""))
                if name in major:
                    result.append({
                        "name": name,
                        "code": str(row.get("代码", "")),
                        "value": float(row.get("最新价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                    })

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.success_count += 1
            source.consecutive_failures = 0

            return result, DataProvenance(
                provider="akshare", source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=0.95,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="akshare", source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"AkShare 指数获取失败: {str(e)[:100]}",
            )

    async def _try_akshare_breadth(self) -> tuple[dict | None, DataProvenance]:
        """Try getting market breadth from akshare."""
        source = self._sources["akshare"]
        source.total_calls += 1

        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)

            if df is None or df.empty:
                raise ValueError("Empty spot response")

            up = int((df["涨跌幅"] > 0).sum())
            down = int((df["涨跌幅"] < 0).sum())
            flat = int((df["涨跌幅"] == 0).sum())
            limit_up = int((df["涨跌幅"] >= 9.9).sum())
            limit_down = int((df["涨跌幅"] <= -9.9).sum())
            total_vol = round(df["成交额"].sum() / 1e12, 2)

            source.is_available = True
            source.success_count += 1
            source.consecutive_failures = 0

            return {
                "up": up, "down": down, "flat": flat,
                "limit_up": limit_up, "limit_down": limit_down,
                "total_volume": total_vol,
            }, DataProvenance(
                provider="akshare", source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=0.95,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="akshare", source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"AkShare 涨跌统计获取失败: {str(e)[:100]}",
            )


    # ================================================================
    # Data Feed Management
    # ================================================================

    def get_feeds(self) -> list[dict]:
        """Return all registered data feed definitions."""
        return [
            {
                "name": f.name, "category": f.category,
                "frequency": f.frequency,
                "primary_source": f.primary_source,
                "backup_sources": f.backup_sources,
                "fields": f.fields,
                "cache_ttl_seconds": f.cache_ttl_seconds,
            }
            for f in STANDARD_FEEDS.values()
        ]

    async def fuse_price(self, symbol: str, akshare_price: float | None) -> dict:
        """Fuse price from multiple sources with disagreement detection.

        Currently uses AkShare as primary. When Tushare/BaoStock are
        configured, they will be included for cross-verification.
        """
        readings = [
            SourceReading(
                source_name="akshare", field_name="price",
                value=akshare_price if akshare_price is not None else 0,
                is_available=akshare_price is not None,
            )
        ]

        # If other providers are configured, add their readings
        # (placeholder for Tushare/BaoStock integration)
        result = data_fusion.fuse("price", symbol, readings)
        return result.to_dict()


# Singleton
source_manager = SourceManager()
