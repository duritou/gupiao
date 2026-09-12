"""Data Source Manager — v7.5. The truth layer before AI.

Answers: "Where did this data come from, and can I trust it?"

Architecture (multi-provider with auto-failover):
  TickFlow ──────┐
  Tencent ───────┤
  Sina ──────────┤
  AkShare ───────┤
  Finnhub ───────┤
  FMP ───────────┤
  Twelve Data ───┤
  Alpha Vantage ─┤
  BaoStock ──────┤
                  ├── SourceManager ──→ Provenance + Data
  Cache ─────────┤
                  │
  CN fallback: Cache → TickFlow → Tencent → Sina → AkShare/BaoStock → Error

Every data point carries DataProvenance — the user ALWAYS knows
where the data came from and how fresh it is.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from enum import Enum
from typing import Any, Callable

from src.infrastructure.market_data.fusion import (
    fusion as data_fusion,
    STANDARD_FEEDS,
    SourceReading,
)
from src.infrastructure.market_data.provider_metrics import reliability_engine
from src.infrastructure.market_data.hithink_provider import hithink_provider
from src.infrastructure.market_data.tushare_provider import tushare_provider

# P0 止血: akshare 实时接口对部分住宅 IP 有连接级风控(hang / RemoteDisconnected),
# 裸 asyncio.to_thread 无超时会阻塞事件循环、拖垮整个 FastAPI 服务(连 /docs 都 hang)。
# 所有 akshare 调用必须经此超时,失败立即返回 degraded 数据,绝不 hang。
_AKSHARE_TIMEOUT: float = 8.0

# API 凭据从环境变量读取(见 .env / .env.example),禁止硬编码入库
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Alpha Vantage — free tier: 25 requests/day
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"

# Finnhub — free tier: 60 requests/min
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# Financial Modeling Prep — free tier: 250 req/day
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"

# Twelve Data — free tier: 800 req/day
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TWELVEDATA_BASE_URL = "https://api.twelvedata.com"

# Polygon.io — free tier limited
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_BASE_URL = "https://api.polygon.io/v2"

# Tushare — A-share financial data
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
RESEARCH_QUOTE_ATTEMPT_TIMEOUT_SECONDS = 8.0


def _exception_detail(exc: BaseException, limit: int = 160) -> str:
    """Preserve exception type when providers return an empty message."""
    detail = str(exc).strip() or repr(exc)
    detail = re.sub(
        r"(?i)(token|access_token|api[_-]?key|password)\s*=\s*[^&\s,;]+",
        r"\1=[REDACTED]",
        detail,
    )
    detail = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", detail)
    return f"{type(exc).__name__}: {detail[:limit]}"


def _normalize_market_code(value: str) -> str:
    """Normalize six-digit A-share input before provider routing."""
    text = str(value or "").strip().upper()
    if "." in text or not text.isdigit() or len(text) != 6:
        return text
    if text.startswith(("6", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "2", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8")):
        return f"{text}.BJ"
    return text


def _number(value: Any, default: float | None = None) -> float | None:
    """Parse optional provider numerics without turning bad data into zero."""
    if value in (None, "", "-") or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return default if parsed != parsed else parsed

# mootdx server pool (通达信 TCP 7709) — probed on first use
_TDX_SERVERS = [
    ("119.97.185.59", 7709), ("124.70.133.119", 7709),
    ("116.205.183.150", 7709), ("123.60.73.44", 7709),
    ("116.205.163.254", 7709), ("121.36.225.169", 7709),
    ("123.60.70.228", 7709), ("124.71.9.153", 7709),
    ("110.41.147.114", 7709), ("124.71.187.122", 7709),
]


# ================================================================
# Data Provenance — the truth label on every data point
# ================================================================

class SourceProvider(str, Enum):
    AKSHARE = "akshare"
    SINA = "sina"
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
    data_date: str = ""              # Trading/report date represented by data
    endpoint: str = ""               # Provider endpoint(s) used
    coverage_ratio: float | None = None
    fallback_reason: str = ""

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
            "data_date": self.data_date,
            "endpoint": self.endpoint,
            "coverage_ratio": (
                round(self.coverage_ratio, 4)
                if self.coverage_ratio is not None else None
            ),
            "fallback_reason": self.fallback_reason,
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
        self._cache_provenance: dict[str, DataProvenance] = {}
        self._sources: dict[str, SourceStatus] = {}
        self._capabilities: dict[str, SourceCapability] = {}
        self._fetch_functions: dict[str, dict[str, Callable]] = {}
        self._last_probe: dict = {}
        self._init_sources()

    def _init_sources(self):
        """Register available data sources with their capabilities."""
        # Primary: iFind (同花顺 QuantAPI) — production-grade, all data types
        self._sources["ifind"] = SourceStatus(
            name="ifind",
            is_available=False,
        )
        self._capabilities["ifind"] = SourceCapability(
            realtime_quotes=True,
            kline_history=True,
            max_kline_days=365 * 10,
            rate_limited=True,
            requires_auth=True,
        )

        # Fallback 1: mootdx (通达信 TCP) — real-time quotes, no IP blocking
        self._sources["mootdx"] = SourceStatus(
            name="mootdx",
            is_available=False,
        )
        self._capabilities["mootdx"] = SourceCapability(
            realtime_quotes=True,
            kline_history=True,
            max_kline_days=365 * 5,
            rate_limited=False,  # TCP protocol, no rate limiting
        )

        # Primary: tushare — most reliable A-share data, financials + daily K-line
        self._sources["tushare"] = SourceStatus(
            name="tushare",
            is_available=False,
        )
        self._capabilities["tushare"] = SourceCapability(
            realtime_quotes=False,
            max_kline_days=365 * 10,
            indices=True,
            sectors=True,
            market_breadth=True,
            rate_limited=True,
            requires_auth=True,
        )

        # Optional authenticated HiThink Financial API.  It is a dated
        # daily-data fallback only; realtime quotes remain on the existing
        # TickFlow/Tencent/Sina chain until their canary gate passes.
        self._sources["hithink"] = SourceStatus(
            name="hithink",
            is_available=hithink_provider.configured,
        )
        self._capabilities["hithink"] = SourceCapability(
            max_kline_days=365 * 20,
            kline_history=True,
            rate_limited=True,
            requires_auth=True,
        )

        # Fallback: akshare (东方财富) — fast, comprehensive, but may be blocked
        self._sources["akshare"] = SourceStatus(
            name="akshare",
            is_available=False,  # Will be set on first successful call
        )
        self._capabilities["akshare"] = SourceCapability(
            max_kline_days=365 * 5,
            rate_limited=True,
        )

        # P1: 腾讯财经(qt.gtimg.cn) — 指数实时, 不封IP, akshare 被东财风控时 fallback
        self._sources["tencent"] = SourceStatus(
            name="tencent",
            is_available=False,
        )
        self._capabilities["tencent"] = SourceCapability(
            max_kline_days=365 * 5,
            rate_limited=False,
        )

        # Optional authenticated API: primary quote/K-line provider when a
        # TICKFLOW_API_KEY is configured. It is skipped entirely otherwise.
        self._sources["tickflow"] = SourceStatus(
            name="tickflow",
            is_available=False,
        )
        self._capabilities["tickflow"] = SourceCapability(
            realtime_quotes=True,
            kline_history=True,
            max_kline_days=365 * 20,
            rate_limited=True,
            requires_auth=True,
        )

        # 新浪财经 — 独立于东方财富的免费实时行情与未复权日线。
        # hq.sinajs.cn 会校验 Referer，所以必须通过专用适配器访问。
        self._sources["sina"] = SourceStatus(
            name="sina",
            is_available=False,
        )
        self._capabilities["sina"] = SourceCapability(
            max_kline_days=1023,
            rate_limited=True,
        )

        # Fallback 1: Finnhub — official API, 60 req/min, news + financials + ETF
        self._sources["finnhub"] = SourceStatus(
            name="finnhub",
            is_available=False,
        )
        self._capabilities["finnhub"] = SourceCapability(
            max_kline_days=365 * 10,
            rate_limited=True,         # 60 req/min (generous free tier)
            requires_auth=True,
        )

        # Fallback 2: FMP — 250 req/day, financial statements, PE, ROE, DCF
        self._sources["fmp"] = SourceStatus(
            name="fmp",
            is_available=False,
        )
        self._capabilities["fmp"] = SourceCapability(
            max_kline_days=365 * 10,
            rate_limited=True,         # 250 req/day
            requires_auth=True,
        )

        # Fallback 3: Twelve Data — 800 req/day, K-line + MACD/RSI/EMA indicators
        self._sources["twelvedata"] = SourceStatus(
            name="twelvedata",
            is_available=False,
        )
        self._capabilities["twelvedata"] = SourceCapability(
            max_kline_days=365 * 10,
            rate_limited=True,         # 800 req/day (generous free tier)
            requires_auth=True,
        )

        # Fallback 4: Polygon.io — professional-grade, stocks/forex/crypto
        self._sources["polygon"] = SourceStatus(
            name="polygon",
            is_available=False,
        )
        self._capabilities["polygon"] = SourceCapability(
            max_kline_days=365 * 10,
            rate_limited=True,
            requires_auth=True,
        )

        # Fallback 5: Alpha Vantage — official API, 25 req/day, global coverage
        self._sources["alphavantage"] = SourceStatus(
            name="alphavantage",
            is_available=False,
        )
        self._capabilities["alphavantage"] = SourceCapability(
            max_kline_days=365 * 20,  # 20 years of daily data
            rate_limited=True,         # 25 req/day free tier
            requires_auth=True,
        )

        # Fallback 2: baostock — free, no auth, reliable for A-shares
        self._sources["baostock"] = SourceStatus(
            name="baostock",
            is_available=False,
        )
        self._capabilities["baostock"] = SourceCapability(
            max_kline_days=365 * 10,
            rate_limited=False,
        )

        self._sources["cache"] = SourceStatus(
            name="cache",
            is_available=True,
        )

    # ================================================================
    # Capability-based routing — providers declare what they CAN do
    # ================================================================

    @staticmethod
    def _detect_market(code: str) -> str:
        """Detect market from stock code suffix."""
        if any(s in code for s in (".SH", ".SZ", ".BJ")):
            return "CN"
        if ".HK" in code:
            return "HK"
        return "US"

    def _get_ranked_providers(
        self, code: str, capability: str
    ) -> list[str]:
        """Get providers ranked by: market match + capability + trust.

        Used by the fallback chain. Providers are auto-ranked by:
          1. Market coverage (must support this market)
          2. Capability support (must have this data type)
          3. Dynamic trust score (higher = better)
          4. Not degraded
        """
        from src.domain.models.market_data import PROVIDER_CAPABILITIES

        market = self._detect_market(code)
        candidates = []

        for name, caps in PROVIDER_CAPABILITIES.items():
            if name == "tickflow":
                from src.infrastructure.market_data.tickflow_provider import is_configured
                if not is_configured():
                    continue
            if name == "hithink" and not hithink_provider.configured:
                continue
            if name == "hithink":
                from config.settings import settings
                if str(getattr(settings, "HITHINK_DAILY_MODE", "disabled")) in {
                    "disabled",
                    "shadow",
                }:
                    continue
            if not caps.supports_market(market):
                continue
            if not caps.has(capability):
                continue
            if not reliability_engine.should_attempt(name):
                continue
            trust = reliability_engine.get_trust(name, "24h")
            quality_bonus = {"excellent": 0.05, "good": 0.02, "basic": 0.0}
            score = trust + quality_bonus.get(caps.data_quality, 0)
            # A configured TickFlow account is the intentional primary for
            # quote/K-line traffic; observed health still removes it after
            # repeated failures, allowing the normal fallback chain.
            priority = 0 if name == "tickflow" else 1
            candidates.append((priority, -score, name))

        candidates.sort()
        return [name for _, _, name in candidates]

    # ================================================================
    # Provider metrics recording — feeds dynamic trust scores
    # ================================================================

    def _record_call(
        self, provider: str, operation: str, success: bool,
        latency_ms: float, error_msg: str = "",
        completeness: float = 1.0, validation_passed: bool = True,
    ) -> float:
        """Record a provider call and return dynamic trust score."""
        reliability_engine.record_call(
            provider=provider, operation=operation,
            success=success, latency_ms=latency_ms,
            error_message=error_msg,
            completeness=completeness,
            validation_passed=validation_passed,
        )
        return reliability_engine.get_trust(provider, "24h")

    def _is_provider_degraded(self, provider: str) -> bool:
        """Check if a provider has been auto-degraded."""
        return reliability_engine.is_degraded(provider)

    async def _dispatch_quote(
        self, provider: str, code: str
    ) -> tuple[dict | None, DataProvenance]:
        """Dispatch quote request to the right provider implementation."""
        dispatcher = {
            "tickflow": self._try_tickflow_quote,
            "ifind": self._try_ifind_quote,
            "mootdx": self._try_mootdx_quote,
            "tushare": self._try_tushare_quote,
            "akshare": self._try_akshare_quote,
            "tencent": self._try_tencent_quote,
            "sina": self._try_sina_quote,
            "baostock": self._try_baostock_quote,
            "finnhub": self._try_finnhub_quote,
            "fmp": self._try_fmp_quote,
            "twelvedata": self._try_twelvedata_quote,
            "polygon": self._try_polygon_quote,
            "alphavantage": self._try_alphavantage_quote,
        }
        handler = dispatcher.get(provider)
        if handler is None:
            return None, DataProvenance(
                provider="none", source_name="未知",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"未知Provider: {provider}",
            )
        return await handler(code)

    async def _dispatch_kline(
        self, provider: str, code: str, count: int
    ) -> tuple[list[dict] | None, DataProvenance]:
        """Dispatch K-line request to the right provider implementation."""
        dispatcher = {
            "tickflow": lambda c, n: self._try_tickflow_kline(c, n),
            "ifind": lambda c, n: self._try_ifind_kline(c, n),
            "mootdx": lambda c, n: self._try_mootdx_kline(c, n),
            "tushare": lambda c, n: self._try_tushare_kline(c, n),
            "akshare": lambda c, n: self._try_akshare_kline(c, n),
            "tencent": lambda c, n: self._try_tencent_kline(c, n),
            "sina": lambda c, n: self._try_sina_kline(c, n),
            "baostock": lambda c, n: self._try_baostock_kline(c, n),
            "finnhub": lambda c, n: self._try_finnhub_kline(c, n),
            "fmp": lambda c, n: self._try_fmp_kline(c, n),
            "twelvedata": lambda c, n: self._try_twelvedata_kline(c, n),
            "polygon": lambda c, n: self._try_polygon_kline(c, n),
            "alphavantage": lambda c, n: self._try_alphavantage_kline(c, n),
            "hithink": lambda c, n: self._try_hithink_kline(c, n),
        }
        handler = dispatcher.get(provider)
        if handler is None:
            return None, DataProvenance(
                provider="none", source_name="未知",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"未知Provider: {provider}",
            )
        return await handler(code, count)

    # ================================================================
    # Public API — the only way data enters the system
    # ================================================================

    async def get_realtime_quote(
        self,
        code: str,
        *,
        excluded_providers: set[str] | None = None,
    ) -> tuple[dict | None, DataProvenance]:
        """Get real-time quote with provenance. NEVER returns mock."""
        code = _normalize_market_code(code)
        excluded = {
            str(provider).strip().lower()
            for provider in (excluded_providers or set())
            if str(provider).strip()
        }
        cache_key = f"spot:quote:{code}"
        from src.infrastructure.market_data.tickflow_provider import is_configured
        tickflow_configured = is_configured()

        # 1. Try cache first
        cached = self.cache.get(cache_key)
        # Startup probes may have cached Tencent/Sina. Once TickFlow is
        # configured, an older non-TickFlow cache must not hide the selected
        # primary; it remains available through the normal fallback chain.
        cached_source = str((cached or {}).get("source") or "").lower()
        cache_is_tickflow = "tickflow" in cached_source
        cache_is_realtime = (cached or {}).get("is_realtime") is not False
        if cached is not None and any(
            provider in cached_source for provider in excluded
        ):
            cached = None
        if cached is not None and (not tickflow_configured or cache_is_tickflow):
            if not cache_is_realtime:
                cached = None
        if cached is not None and (not tickflow_configured or cache_is_tickflow):
            age = self.cache.get_age(cache_key)
            return cached, DataProvenance(
                provider="cache",
                source_name="本地缓存",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age,
                is_live=cache_is_realtime,
                is_cached=True,
                cache_age_seconds=age,
                trust_score=0.95 if age < 60 else 0.8,
                data_date=str(cached.get("data_date") or ""),
                endpoint=str(cached.get("endpoint") or ""),
            )

        # 2. Capability-based routing — auto-rank providers by market + trust
        providers = self._get_ranked_providers(code, "realtime_quote")
        providers += [
            p for p in self._get_ranked_providers(code, "daily_kline")
            if p not in providers and p not in excluded
        ]
        providers = [p for p in providers if p not in excluded]

        for p in providers:
            result, prov = await self._dispatch_quote(p, code)
            if result is not None:
                self.cache.set(cache_key, result)
                return result, prov

        # 3. All sources failed — use Tushare only when the caller has not
        # already attempted it. Research enrichment passes this exclusion so
        # its primary/retry budget cannot be bypassed by this last resort.
        if "tushare" not in excluded:
            result, prov = await self._try_tushare_quote(code)
            if result is not None:
                self.cache.set(cache_key, result)
                return result, prov

        # 4. 全部失败:返回 (None, 不可用 provenance),避免调用方解包 None 崩溃(/detail 500)
        return None, DataProvenance(
            provider="none",
            source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            is_live=False,
            trust_score=0.0,
            error_message="所有数据源均不可用",
        )

    async def get_eod_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Get Tushare's dated close first, then use live quote fallbacks."""
        code = _normalize_market_code(code)
        quote, provenance = await self._try_tushare_quote(code)
        if quote is not None:
            return quote, provenance
        return await self.get_realtime_quote(code)

    async def probe_live_sources(self, code: str = "600000.SH") -> dict:
        """Run a bounded startup probe against configured and fallback feeds."""
        checked_at = datetime.now().isoformat(timespec="seconds")
        quote = None
        provenance = DataProvenance(
            provider="none",
            source_name="实时行情启动探测",
            fetched_at=checked_at,
            is_live=False,
            trust_score=0.0,
            error_message="已配置实时行情源均不可用",
        )
        probe_results = []
        probes = []
        from src.infrastructure.market_data.tickflow_provider import is_configured
        if is_configured():
            probes.append(("tickflow", self._try_tickflow_quote))
        probes.extend((
            ("tushare", self._try_tushare_quote),
            ("tencent", self._try_tencent_quote),
            ("sina", self._try_sina_quote),
        ))
        for provider, fetch in probes:
            try:
                candidate_quote, candidate_provenance = await asyncio.wait_for(
                    fetch(code), timeout=10,
                )
            except Exception as exc:
                candidate_quote = None
                candidate_provenance = DataProvenance(
                    provider=provider,
                    source_name=f"{provider} 启动探测",
                    fetched_at=checked_at,
                    is_live=False,
                    trust_score=0.0,
                    error_message=f"启动探测失败: {str(exc)[:120]}",
                )
            probe_results.append({
                "provider": provider,
                "available": candidate_quote is not None,
                "price": float((candidate_quote or {}).get("price") or 0),
                "data_date": str((candidate_quote or {}).get("data_date") or ""),
                "error": candidate_provenance.error_message,
            })
            if quote is None and candidate_quote is not None:
                quote = candidate_quote
                provenance = candidate_provenance
        if quote is not None:
            self.cache.set(f"spot:quote:{code}", quote)
        self._last_probe = {
            "checked_at": checked_at,
            "code": code,
            "available": quote is not None,
            "provider": provenance.provider,
            "price": float((quote or {}).get("price") or 0),
            "data_date": str((quote or {}).get("data_date") or ""),
            "error": provenance.error_message,
            "providers": probe_results,
        }
        return dict(self._last_probe)

    async def get_kline(
        self, code: str, count: int = 250, adjustment_mode: str | None = None,
    ) -> tuple[list[dict] | None, DataProvenance]:
        """Get K-line data with provenance and an optional adjustment contract."""
        code = _normalize_market_code(code)
        normalized_adjustment = str(adjustment_mode or "any").strip().lower()
        cache_key = f"kline_daily:{code}:{count}:{normalized_adjustment}"

        cached = self.cache.get(cache_key)
        from src.infrastructure.market_data.tickflow_provider import is_configured
        tickflow_configured = is_configured()
        cached_source = str(
            (cached[0].get("source") if isinstance(cached, list) and cached else "")
            if cached is not None else ""
        ).lower()
        cache_is_tickflow = "tickflow" in cached_source
        # Once TickFlow is configured, a pre-existing Sina/Tencent K-line
        # cache must not hide the selected primary provider.  It remains a
        # fallback only after the live provider chain has been attempted.
        if cached is not None and (not tickflow_configured or cache_is_tickflow):
            age = self.cache.get_age(cache_key)
            return cached, DataProvenance(
                provider="cache", source_name="本地缓存(K线)",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age if age < 3600 else age,
                is_live=True, is_cached=True, cache_age_seconds=age,
                trust_score=0.9,
            )

        # Capability-based routing for K-line
        providers = self._get_ranked_providers(code, "daily_kline")
        if normalized_adjustment == "qfq" and self._is_a_share(code):
            qfq_providers = {"akshare", "tencent", "baostock"}
            providers = [provider for provider in providers if provider in qfq_providers]
        elif self._is_a_share(code) and tushare_provider.configured:
            # Tushare is the dated EOD truth source.  Keep adjusted-K-line
            # providers as fallbacks because Tushare's daily endpoint is raw.
            providers = ["tushare", *[provider for provider in providers if provider != "tushare"]]

        for p in providers:
            result, prov = await self._dispatch_kline(p, code, count)
            if result is not None:
                for bar in result:
                    bar.setdefault(
                        "adjustment_mode",
                        "qfq" if p in {"akshare", "tencent", "baostock"} else "raw",
                    )
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
            cached_provenance = self._cache_provenance.get(cache_key)
            return cached, DataProvenance(
                provider="cache", source_name="本地缓存(指数)",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age,
                is_live=bool(cached_provenance and cached_provenance.is_live),
                is_cached=True,
                cache_age_seconds=age,
                trust_score=cached_provenance.trust_score if cached_provenance else 0.0,
                data_date=cached_provenance.data_date if cached_provenance else "",
                endpoint=cached_provenance.endpoint if cached_provenance else "",
            )

        # Tushare is the authenticated daily truth source when available.
        # Tencent/AkShare remain fallbacks for intraday or permission gaps.
        for fetch in (
            self._try_tushare_indices,
            self._try_tencent_indices,
            self._try_akshare_indices,
        ):
            result, prov = await fetch()
            if result is not None:
                self.cache.set(cache_key, result)
                self._cache_provenance[cache_key] = prov
                return result, prov

        return None, DataProvenance(
            provider="none", source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            is_live=False, trust_score=0.0,
            error_message="无法获取指数数据。",
        )

    async def get_intraday_index_quotes(self) -> tuple[list[dict] | None, DataProvenance]:
        """Get current-session indices without falling back to dated closes."""
        failures: list[str] = []
        for fetch in (self._try_tencent_indices, self._try_akshare_indices):
            result, provenance = await fetch()
            if result and provenance.is_live:
                return result, provenance
            if provenance.error_message:
                failures.append(provenance.error_message)
        return None, DataProvenance(
            provider="none",
            source_name="今日盘中指数行情",
            fetched_at=datetime.now().isoformat(),
            is_live=False,
            trust_score=0.0,
            error_message="; ".join(failures)[:240] or "今日盘中指数行情不可用",
        )

    async def get_market_breadth(self) -> tuple[dict | None, DataProvenance]:
        """Get market breadth (up/down counts)."""
        cache_key = "spot:breadth"

        cached = self.cache.get(cache_key)
        if cached is not None:
            age = self.cache.get_age(cache_key)
            cached_provenance = self._cache_provenance.get(cache_key)
            cached_data_date = (
                str(cached.get("data_date") or "")
                if isinstance(cached, dict) else ""
            )
            return cached, DataProvenance(
                provider="cache", source_name="本地缓存(涨跌)",
                fetched_at=(datetime.now() - timedelta(seconds=age)).isoformat(),
                data_age_seconds=age,
                is_live=bool(cached_provenance and cached_provenance.is_live),
                is_cached=True,
                cache_age_seconds=age,
                trust_score=cached_provenance.trust_score if cached_provenance else 0.0,
                data_date=(cached_provenance.data_date if cached_provenance else "")
                or cached_data_date,
                endpoint=cached_provenance.endpoint if cached_provenance else "",
            )

        # Prefer the complete Tushare close snapshot. Local breadth is a
        # fallback because it may lag or contain a partial historical batch.
        result, prov = await self._try_tushare_breadth()
        if result is not None:
            self.cache.set(cache_key, result)
            self._cache_provenance[cache_key] = prov
            return result, prov

        result, prov = await self._try_local_market_breadth()
        if result is not None:
            self.cache.set(cache_key, result)
            self._cache_provenance[cache_key] = prov
            return result, prov

        result, prov = await self._try_akshare_breadth()
        if result is not None:
            self.cache.set(cache_key, result)
            self._cache_provenance[cache_key] = prov
            return result, prov

        return None, DataProvenance(
            provider="none", source_name="无可用数据源",
            fetched_at=datetime.now().isoformat(),
            is_live=False, trust_score=0.0,
            error_message="无法获取涨跌统计。",
        )

    async def get_intraday_market_breadth(self) -> tuple[dict | None, DataProvenance]:
        """Get today's live breadth or return unavailable; never use a close snapshot."""
        result, provenance = await self._try_akshare_breadth()
        today = datetime.now().date().isoformat()
        data_date = str(
            provenance.data_date or (result or {}).get("data_date") or ""
        )[:10]
        if result is not None and provenance.is_live and data_date == today:
            return result, provenance
        return None, DataProvenance(
            provider="none",
            source_name="今日盘中涨跌统计",
            fetched_at=datetime.now().isoformat(),
            is_live=False,
            trust_score=0.0,
            data_date=data_date,
            error_message=(
                provenance.error_message
                or f"今日盘中涨跌统计不可用（data_date={data_date or 'unknown'}）"
            )[:240],
        )

    async def _try_tushare_indices(
        self,
    ) -> tuple[list[dict] | None, DataProvenance]:
        """Fetch the close-only index snapshot from Tushare first."""
        started = datetime.now()
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_indices(), timeout=30.0
            )
            if not payload.data:
                raise ValueError("empty_tushare_indices")
            latency = (datetime.now() - started).total_seconds() * 1000
            source = self._sources["tushare"]
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.total_calls += payload.row_count
            source.success_count += payload.row_count
            source.consecutive_failures = 0
            trust = self._record_call("tushare", "indices", True, latency)
            return payload.data, DataProvenance(
                provider="tushare", source_name="Tushare Pro (指数日线)",
                fetched_at=datetime.now().isoformat(), data_age_seconds=0,
                is_live=False, trust_score=trust, data_date=payload.data_date,
                endpoint=payload.endpoint,
            )
        except Exception as exc:
            self._record_tushare_failure("indices", exc, started)
            return None, DataProvenance(
                provider="tushare", source_name="Tushare Pro (指数日线)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=0.0, endpoint="index_daily",
                error_message=f"Tushare 指数获取失败: {str(exc)[:120]}",
            )

    async def _try_tushare_breadth(
        self,
    ) -> tuple[dict | None, DataProvenance]:
        """Build breadth from one complete Tushare daily snapshot."""
        started = datetime.now()
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_breadth(), timeout=45.0
            )
            data = dict(payload.data or {})
            coverage = payload.coverage_ratio
            # A partial snapshot must never replace the last complete market
            # environment.  80% is the existing local completion threshold.
            if not data.get("data_date") or not data.get("covered_stocks"):
                raise ValueError("empty_tushare_breadth")
            if coverage is not None and coverage < 0.80:
                raise ValueError(f"tushare_breadth_incomplete:{coverage:.3f}")
            latency = (datetime.now() - started).total_seconds() * 1000
            source = self._sources["tushare"]
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.total_calls += 1
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call("tushare", "breadth", True, latency)
            return data, DataProvenance(
                provider="tushare", source_name="Tushare Pro (全市场收盘统计)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust, data_date=str(data.get("data_date") or ""),
                endpoint=payload.endpoint, coverage_ratio=coverage,
            )
        except Exception as exc:
            self._record_tushare_failure("breadth", exc, started)
            return None, DataProvenance(
                provider="tushare", source_name="Tushare Pro (全市场收盘统计)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=0.0, endpoint="daily+daily_basic+stk_limit",
                error_message=f"Tushare 市场宽度获取失败: {str(exc)[:120]}",
            )

    def _record_tushare_failure(
        self, endpoint: str, error: Exception, started: datetime
    ) -> None:
        source = self._sources["tushare"]
        source.last_error = str(error)[:200]
        source.consecutive_failures += 1
        source.total_calls += 1
        latency = (datetime.now() - started).total_seconds() * 1000
        source.latency_ms = latency
        self._record_call("tushare", endpoint, False, latency, str(error)[:100])

    async def _try_local_market_breadth(
        self,
    ) -> tuple[dict | None, DataProvenance]:
        """Use the latest completed local close when the live full-market feed is risky."""
        try:
            from src.infrastructure.storage.market_database import market_db

            result = await asyncio.to_thread(market_db.get_latest_market_breadth)
            data_date = str(result.get("data_date") or "")
            if not data_date or not (result.get("up") or result.get("down")):
                raise ValueError("local market breadth is empty")
            try:
                data_age = max(
                    0.0,
                    (datetime.now() - datetime.fromisoformat(data_date)).total_seconds(),
                )
            except ValueError:
                data_age = 0.0
            return result, DataProvenance(
                provider="local_market_db",
                source_name=f"本地全市场收盘行情 ({data_date})",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=data_age,
                is_live=False,
                is_cached=True,
                cache_age_seconds=data_age,
                trust_score=0.86,
                data_date=data_date,
            )
        except Exception as exc:
            return None, DataProvenance(
                provider="none",
                source_name="本地全市场行情",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"本地涨跌统计不可用: {str(exc)[:100]}",
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
        tested = any(int(s.get("total_calls") or 0) > 0 for s in sources_status)
        return {
            "live_data_available": any_available,
            "cache_entries": len(self.cache._store),
            "sources": sources_status,
            "tested": tested,
            "last_probe": dict(self._last_probe),
            "recommendation": (
                "Data pipeline healthy" if any_available
                else "Providers not tested yet. Startup probe is pending."
                if not tested else
                "No live data source available. AI analysis may be paused."
            ),
        }

    # ================================================================
    # Internal — Provider implementations
    # ================================================================

    # ================================================================
    # iFind (QuantAPI) provider — production-grade, paid
    # ================================================================

    async def _try_ifind_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        source = self._sources["ifind"]
        source.total_calls += 1
        t0 = datetime.now()
        try:
            from src.infrastructure.market_data.ifind_provider import ifind
            result = await asyncio.to_thread(ifind.get_quote, code)
            if result is None or result.price == 0:
                raise ValueError(f"No quote data for {code}")
            latency = (datetime.now() - t0).total_seconds() * 1000
            quote = {
                "stock_code": code, "stock_name": result.name,
                "price": result.price, "change_pct": result.change_pct,
                "change_amount": round(result.price - result.pre_close, 2),
                "volume": result.volume, "amount": result.amount,
                "amount_yi": round(result.amount / 1e8, 2) if result.amount else 0,
                "high": result.high, "low": result.low,
                "open": result.open, "pre_close": result.pre_close,
                "turnover": result.turnover, "pe": result.pe,
                "pb": result.pb, "total_market_cap": result.total_market_cap,
            }
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            dyn_trust = self._record_call("ifind", "quote", True, latency)
            return quote, DataProvenance(
                provider="ifind", source_name="iFind QuantAPI",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=dyn_trust,
            )
        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            latency = (datetime.now() - t0).total_seconds() * 1000
            dyn_trust = self._record_call("ifind", "quote", False, latency, str(e)[:100])
            return None, DataProvenance(
                provider="ifind", source_name="iFind QuantAPI",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=dyn_trust,
                error_message=f"iFind: {str(e)[:100]}",
            )

    async def _try_ifind_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        source = self._sources["ifind"]
        source.total_calls += 1
        t0 = datetime.now()
        try:
            from src.infrastructure.market_data.ifind_provider import ifind
            klines = await asyncio.to_thread(ifind.get_kline, code, "day", count)
            if not klines:
                raise ValueError(f"No K-line data for {code}")
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            dyn_trust = self._record_call("ifind", "kline", True, latency)
            return klines, DataProvenance(
                provider="ifind", source_name="iFind QuantAPI (K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=dyn_trust,
            )
        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            latency = (datetime.now() - t0).total_seconds() * 1000
            dyn_trust = self._record_call("ifind", "kline", False, latency, str(e)[:100])
            return None, DataProvenance(
                provider="ifind", source_name="iFind QuantAPI",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=dyn_trust,
                error_message=f"iFind K线: {str(e)[:100]}",
            )

    # ================================================================
    # mootdx provider — 通达信 TCP 7709, real-time, no IP blocking
    # ================================================================

    _mootdx_client = None
    _mootdx_server = None

    def _get_mootdx_client(self):
        """Get or create mootdx client with server probing.

        Follows a-stock-data skill pattern: probe server pool, use first
        reachable server. Avoids mootdx 0.11.x BESTIP empty-string bug.
        """
        import socket as _socket
        from mootdx.quotes import Quotes

        if self._mootdx_client is not None:
            return self._mootdx_client

        for ip, port in _TDX_SERVERS:
            try:
                with _socket.create_connection((ip, port), timeout=2.0):
                    client = Quotes.factory(
                        market="std", server=(ip, port),
                    )
                    self._mootdx_client = client
                    self._mootdx_server = (ip, port)
                    return client
            except Exception:
                continue

        # Fallback: let mootdx find best IP
        try:
            client = Quotes.factory(market="std", bestip=True)
            self._mootdx_client = client
            return client
        except Exception:
            pass

        raise RuntimeError("mootdx: 所有通达信服务器不可达")

    async def _try_mootdx_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Get real-time quote from mootdx (通达信 TCP 7709).

        Returns 46 fields including 5-level depth. No IP blocking.
        Primary real-time A-share quote provider.
        """
        source = self._sources["mootdx"]
        source.total_calls += 1
        t0 = datetime.now()

        raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

        try:
            client = await asyncio.to_thread(self._get_mootdx_client)
            df = await asyncio.to_thread(client.quotes, symbol=[raw_code])

            if df is None or (hasattr(df, 'empty') and df.empty):
                raise ValueError(f"No data for {raw_code}")

            # Convert DataFrame to dict
            if hasattr(df, 'to_dict'):
                rows = df.to_dict(orient="records")
            elif isinstance(df, list):
                rows = df
            else:
                rows = [df]

            if not rows:
                raise ValueError(f"No data for {raw_code}")

            r = rows[0]
            price = float(r.get("price", 0))
            if price == 0:
                raise ValueError(f"Zero price for {raw_code} (market may be closed)")

            pre_close = float(r.get("last_close", price))
            change_pct = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0

            latency = (datetime.now() - t0).total_seconds() * 1000

            # 46 fields from mootdx quotes
            quote = {
                "stock_code": code,
                "stock_name": str(r.get("code", raw_code)),
                "price": price,
                "change_pct": round(change_pct, 2),
                "change_amount": round(price - pre_close, 2),
                "volume": float(r.get("vol", 0)),
                "amount": float(r.get("amount", 0)),
                "amount_yi": round(float(r.get("amount", 0)) / 1e8, 2),
                "high": float(r.get("high", price)),
                "low": float(r.get("low", price)),
                "open": float(r.get("open", price)),
                "pre_close": pre_close,
                "turnover": 0,
                "pe": 0,
                "total_market_cap": 0,
            }

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            dyn_trust = self._record_call("mootdx", "quote", True, latency)
            return quote, DataProvenance(
                provider="mootdx",
                source_name="通达信 (mootdx TCP)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=dyn_trust,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            latency = (datetime.now() - t0).total_seconds() * 1000
            dyn_trust = self._record_call("mootdx", "quote", False, latency, str(e)[:100])
            return None, DataProvenance(
                provider="mootdx",
                source_name="通达信 (mootdx TCP)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=dyn_trust,
                error_message=f"mootdx 获取失败: {str(e)[:100]}",
            )

    async def _try_mootdx_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Get K-line data from mootdx (通达信 TCP 7709).

        Uses bars() with frequency=9 (日线). Parameter is `frequency`,
        NOT `category` — mootdx silently swallows wrong param names.
        """
        source = self._sources["mootdx"]
        source.total_calls += 1
        t0 = datetime.now()

        raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

        try:
            client = await asyncio.to_thread(self._get_mootdx_client)
            # frequency=9 is 日线, frequency=4 is 日线 (alternate)
            df = await asyncio.to_thread(
                client.bars, symbol=raw_code, frequency=9, offset=count,
            )

            if df is None or (hasattr(df, 'empty') and df.empty):
                raise ValueError(f"No K-line data for {raw_code}")

            if hasattr(df, 'to_dict'):
                rows = df.to_dict(orient="records")
            elif isinstance(df, list):
                rows = df
            else:
                rows = [df]

            if not rows:
                raise ValueError(f"No K-line data for {raw_code}")

            klines = []
            for r in rows:
                klines.append({
                    "date": str(r.get("datetime", r.get("date", ""))),
                    "open": float(r.get("open", 0)),
                    "high": float(r.get("high", 0)),
                    "low": float(r.get("low", 0)),
                    "close": float(r.get("close", 0)),
                    "volume": float(r.get("vol", r.get("volume", 0))),
                    "amount": float(r.get("amount", 0)),
                })

            # mootdx returns newest first — reverse to chronological
            klines.reverse()
            klines = klines[-count:]

            latency = (datetime.now() - t0).total_seconds() * 1000

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            dyn_trust = self._record_call("mootdx", "kline", True, latency)
            return klines, DataProvenance(
                provider="mootdx",
                source_name="通达信 (mootdx K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=dyn_trust,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            latency = (datetime.now() - t0).total_seconds() * 1000
            dyn_trust = self._record_call("mootdx", "kline", False, latency, str(e)[:100])
            return None, DataProvenance(
                provider="mootdx",
                source_name="通达信 (mootdx K线)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=dyn_trust,
                error_message=f"mootdx K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # Tushare provider — A-share fundamental + daily basic data
    # ================================================================

    def _is_a_share(self, code: str) -> bool:
        """Check if a stock code is an A-share (vs US/HK/etc)."""
        return any(suffix in code for suffix in (".SH", ".SZ", ".BJ"))

    def _should_try_international(self, code: str) -> bool:
        """International APIs only make sense for non-A-share codes."""
        return not self._is_a_share(code)

    async def get_stock_evidence(self, code: str, flow_days: int = 5) -> dict[str, Any]:
        """Return Tushare-first quote, fundamental and flow evidence."""
        code = _normalize_market_code(code)
        async def fetch_fundamental() -> tuple[dict[str, Any], DataProvenance]:
            started = datetime.now()
            try:
                payload = await asyncio.wait_for(
                    tushare_provider.fetch_fundamental(code), timeout=25.0
                )
                fundamental = dict(payload.data or {})
                latency = (datetime.now() - started).total_seconds() * 1000
                self._record_call("tushare", "fundamental", True, latency)
                return fundamental, DataProvenance(
                    provider="tushare", source_name="Tushare Pro (财务指标)",
                    fetched_at=datetime.now().isoformat(), data_date=payload.data_date,
                    endpoint=payload.endpoint, is_live=False, trust_score=0.95,
                )
            except Exception as exc:
                latency = (datetime.now() - started).total_seconds() * 1000
                self._record_call(
                    "tushare", "fundamental", False, latency, _exception_detail(exc, 100)
                )
                return {}, DataProvenance(
                    provider="tushare", source_name="Tushare Pro (财务指标)",
                    fetched_at=datetime.now().isoformat(), is_live=False,
                    trust_score=0.0,
                    error_message=f"Tushare 财务指标获取失败: {_exception_detail(exc, 100)}",
                )

        async def fetch_flow() -> tuple[dict[str, Any], DataProvenance]:
            from src.infrastructure.market_data.research_flow import get_research_flow

            started = datetime.now()
            try:
                flow = await asyncio.wait_for(
                    get_research_flow(code, flow_days), timeout=25.0
                )
                latency = (datetime.now() - started).total_seconds() * 1000
                self._record_call("tushare", "moneyflow", True, latency)
                return flow, DataProvenance(
                    provider="tushare", source_name="Tushare Pro (个股资金流)",
                    fetched_at=str(flow.get("fetched_at") or ""), data_date=flow["data_date"],
                    endpoint=flow["endpoint"], is_live=False, trust_score=0.95,
                )
            except Exception as exc:
                latency = (datetime.now() - started).total_seconds() * 1000
                self._record_call(
                    "tushare", "moneyflow", False, latency, _exception_detail(exc, 100)
                )
                return {}, DataProvenance(
                    provider="tushare", source_name="Tushare Pro (个股资金流)",
                    fetched_at=datetime.now().isoformat(), is_live=False,
                    trust_score=0.0,
                    error_message=f"Tushare 资金流获取失败: {_exception_detail(exc, 100)}",
                )

        # These are independent evidence components.  One permission,
        # timeout or empty-response failure must not discard the others.
        async def fetch_quote():
            return await self._bounded_research_quote(code)

        (quote, quote_prov), (fundamental, fundamental_prov), (flow, flow_prov) = await asyncio.gather(
            fetch_quote(), fetch_fundamental(), fetch_flow()
        )

        sources = [quote_prov.provider] if quote is not None else []
        if fundamental:
            sources.append("tushare.fundamental")
        if flow:
            sources.append("tushare.moneyflow")
        return {
            "quote": quote or {},
            "fundamental": fundamental,
            "fund_flow": flow,
            "sources": sources,
            "provenance": {
                "quote": quote_prov.to_dict(),
                "fundamental": fundamental_prov.to_dict(),
                "fund_flow": flow_prov.to_dict(),
            },
        }

    async def _bounded_research_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Reserve fallback time without overlapping a timed-out request."""
        failures = []
        tasks = getattr(self, "_research_quote_tasks", None)
        if tasks is None:
            tasks = set()
            self._research_quote_tasks = tasks

        def retain(task: asyncio.Task) -> None:
            tasks.add(task)

            def finish(done: asyncio.Task) -> None:
                tasks.discard(done)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finish)

        async def attempt(fetch, *, preserve_on_timeout: bool):
            task = asyncio.create_task(fetch(code))
            retain(task)
            try:
                awaited = asyncio.shield(task) if preserve_on_timeout else task
                value = await asyncio.wait_for(
                    awaited, timeout=RESEARCH_QUOTE_ATTEMPT_TIMEOUT_SECONDS
                )
                return value, False, task
            except asyncio.TimeoutError:
                return None, True, task
            except Exception as exc:
                return exc, False, task

        def completed_value(task: asyncio.Task):
            try:
                return task.result()
            except Exception as exc:
                return exc

        primary, timed_out, primary_task = await attempt(
            self._try_tushare_quote, preserve_on_timeout=True
        )
        if timed_out:
            failures.append("tushare_primary:TimeoutError")
            if not primary_task.done():
                # asyncio.to_thread cannot stop an already-running SDK call.
                # Do not launch a second Tushare request while that call is live.
                failures.append("tushare_retry:skipped_inflight")
                primary = None
            else:
                timed_out = False
                primary = completed_value(primary_task)
        if isinstance(primary, Exception):
            failures.append(f"tushare_primary:{type(primary).__name__}")
            primary = None
        if primary is not None and not isinstance(primary, Exception):
            quote, provenance = primary
            if quote and float(quote.get("price") or 0) > 0:
                provenance.fallback_reason = ";".join(failures)
                return quote, provenance
            failures.append(
                "tushare_primary:"
                f"{provenance.error_message or 'empty_or_invalid_quote'}"
            )

        if "tushare_retry:skipped_inflight" not in failures:
            retry, retry_timed_out, retry_task = await attempt(
                self._try_tushare_quote, preserve_on_timeout=True
            )
            if retry_timed_out:
                failures.append("tushare_retry:TimeoutError")
                if retry_task.done() and not retry_task.cancelled():
                    retry = completed_value(retry_task)
                else:
                    retry = None
            if isinstance(retry, Exception):
                failures.append(f"tushare_retry:{type(retry).__name__}")
                retry = None
            if retry is not None and not isinstance(retry, Exception):
                quote, provenance = retry
                if quote and float(quote.get("price") or 0) > 0:
                    provenance.fallback_reason = ";".join(failures)
                    return quote, provenance
                failures.append(
                    "tushare_retry:"
                    f"{provenance.error_message or 'empty_or_invalid_quote'}"
                )

        failures.append("tushare_fallback:skipped_already_attempted")
        fallback, fallback_timed_out, fallback_task = await attempt(
            lambda current_code: self.get_realtime_quote(
                current_code, excluded_providers={"tushare"}
            ),
            preserve_on_timeout=False,
        )
        if fallback_timed_out:
            failures.append("fallback:TimeoutError")
            if fallback_task.done() and not fallback_task.cancelled():
                fallback = completed_value(fallback_task)
            else:
                fallback = None
        if isinstance(fallback, Exception):
            failures.append(f"fallback:{type(fallback).__name__}")
            fallback = None
        if fallback is not None and not isinstance(fallback, Exception):
            quote, provenance = fallback
            if quote and float(quote.get("price") or 0) > 0:
                provenance.fallback_reason = ";".join(failures)
                return quote, provenance
            failures.append(
                "fallback:"
                f"{provenance.error_message or 'empty_or_invalid_quote'}"
            )
        return None, DataProvenance(
            provider="none", source_name="research_quote", is_live=False,
            trust_score=0.0, error_message=";".join(failures),
        )

    async def get_financial_statements(self, code: str) -> tuple[dict, DataProvenance]:
        """Return the latest Tushare three-statement packet when available."""
        code = _normalize_market_code(code)
        started = datetime.now()
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_financial_statements(code), timeout=30.0
            )
            latency = (datetime.now() - started).total_seconds() * 1000
            trust = self._record_call("tushare", "financial_statements", True, latency)
            return dict(payload.data), DataProvenance(
                provider="tushare", source_name="Tushare Pro (三大财务报表)",
                fetched_at=datetime.now().isoformat(), data_date=payload.data_date,
                endpoint=payload.endpoint, is_live=False, trust_score=trust,
            )
        except Exception as exc:
            latency = (datetime.now() - started).total_seconds() * 1000
            self._record_call("tushare", "financial_statements", False, latency, str(exc)[:100])
            return {}, DataProvenance(
                provider="tushare", source_name="Tushare Pro (三大财务报表)",
                fetched_at=datetime.now().isoformat(), endpoint="income+balancesheet+cashflow",
                error_message=f"Tushare 财务三表获取失败: {str(exc)[:100]}",
            )

    async def get_financial_history(
        self, code: str, periods: int = 8
    ) -> tuple[dict[str, Any], DataProvenance]:
        """Return persisted multi-period Tushare statements, filling gaps once.

        The local warehouse is preferred so repeated research does not spend
        points.  A partial local packet is still returned if the provider is
        unavailable; its coverage is explicit in ``period_counts`` and never
        promoted to a complete report.
        """
        code = _normalize_market_code(code)
        target_periods = max(1, min(int(periods), 12))
        from src.infrastructure.storage import market_database as database_module

        local = await asyncio.to_thread(
            database_module.market_db.get_financial_history, code, target_periods
        )
        expected = ("income", "balancesheet", "cashflow", "fina_indicator")
        local_counts = {name: len(local.get(name) or []) for name in expected}
        local_complete = all(count >= target_periods for count in local_counts.values())
        if local_complete:
            dates = [
                str(row.get("ann_date") or row.get("end_date") or "")[:10]
                for rows in local.values() for row in rows
            ]
            data_date = max((item for item in dates if item), default="")
            return {
                "available": True,
                "source": "tushare",
                "endpoint": "local.financial_statement_history",
                "statements": local,
                "period_counts": local_counts,
                "requested_periods": target_periods,
                "history_complete": True,
                "data_date": data_date,
                "fetched_at": datetime.now().isoformat(),
            }, DataProvenance(
                provider="tushare", source_name="本地缓存(Tushare多期财报)",
                fetched_at=datetime.now().isoformat(), data_date=data_date,
                endpoint="local.financial_statement_history", is_live=False,
                is_cached=True, trust_score=0.95,
            )

        started = datetime.now()
        provider_error = ""
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_financial_history(code, target_periods),
                timeout=30.0,
            )
            fetched = dict(payload.data or {})
            await asyncio.to_thread(
                database_module.market_db.upsert_financial_history,
                code,
                fetched.get("statements") or {},
                source="tushare",
                fetched_at=str(fetched.get("fetched_at") or datetime.now().isoformat()),
            )
            local = await asyncio.to_thread(
                database_module.market_db.get_financial_history, code, target_periods
            )
            local_counts = {name: len(local.get(name) or []) for name in expected}
            provider_error = ";".join(str(item) for item in (fetched.get("errors") or []))
            data_date = str(fetched.get("data_date") or "")[:10]
            trust = self._record_call(
                "tushare", "financial_history", True,
                (datetime.now() - started).total_seconds() * 1000,
            )
            return {
                "available": any(local.values()),
                "source": "tushare",
                "endpoint": "income+balancesheet+cashflow+fina_indicator",
                "statements": local,
                "period_counts": local_counts,
                "requested_periods": target_periods,
                "history_complete": all(
                    count >= target_periods for count in local_counts.values()
                ),
                "provider_errors": provider_error,
                "data_date": data_date,
                "fetched_at": str(fetched.get("fetched_at") or datetime.now().isoformat()),
            }, DataProvenance(
                provider="tushare", source_name="Tushare Pro (多期财报)",
                fetched_at=datetime.now().isoformat(), data_date=data_date,
                endpoint="income+balancesheet+cashflow+fina_indicator", is_live=False,
                trust_score=trust,
            )
        except Exception as exc:
            provider_error = _exception_detail(exc, 120)
            self._record_call(
                "tushare", "financial_history", False,
                (datetime.now() - started).total_seconds() * 1000, provider_error,
            )

        if local:
            dates = [
                str(row.get("ann_date") or row.get("end_date") or "")[:10]
                for rows in local.values() for row in rows
            ]
            data_date = max((item for item in dates if item), default="")
            return {
                "available": True,
                "source": "tushare",
                "endpoint": "local.financial_statement_history",
                "statements": local,
                "period_counts": local_counts,
                "requested_periods": target_periods,
                "history_complete": False,
                "provider_errors": provider_error,
                "data_date": data_date,
                "fetched_at": datetime.now().isoformat(),
            }, DataProvenance(
                provider="tushare", source_name="本地缓存(Tushare多期财报，部分)",
                fetched_at=datetime.now().isoformat(), data_date=data_date,
                endpoint="local.financial_statement_history", is_live=False,
                is_cached=True, trust_score=0.8, fallback_reason=provider_error,
            )
        return {
            "available": False,
            "source": "tushare",
            "endpoint": "income+balancesheet+cashflow+fina_indicator",
            "statements": {},
            "period_counts": local_counts,
            "requested_periods": target_periods,
            "history_complete": False,
            "provider_errors": provider_error,
            "data_date": "",
            "fetched_at": datetime.now().isoformat(),
        }, DataProvenance(
            provider="tushare", source_name="Tushare Pro (多期财报)",
            fetched_at=datetime.now().isoformat(), is_live=False,
            trust_score=0.0, endpoint="income+balancesheet+cashflow+fina_indicator",
            error_message=provider_error or "tushare_financial_history_unavailable",
        )

    async def get_fund_flow_history(
        self, code: str, days: int = 20
    ) -> tuple[dict[str, Any], DataProvenance]:
        """Return dated money-flow history from the local Tushare cache first."""
        code = _normalize_market_code(code)
        target_days = max(1, min(int(days), 120))
        from src.infrastructure.storage import market_database as database_module

        local = await asyncio.to_thread(
            database_module.market_db.get_fund_flow_history, code, target_days
        )
        if len(local) >= target_days:
            return {
                "available": True, "source": "tushare",
                "endpoint": "local.fund_flow_history", "rows": local,
                "row_count": len(local), "requested_days": target_days,
                "data_date": str(local[0].get("trade_date") or "")[:10],
                "fetched_at": datetime.now().isoformat(),
            }, DataProvenance(
                provider="tushare", source_name="本地缓存(Tushare资金流历史)",
                fetched_at=datetime.now().isoformat(), data_date=str(local[0].get("trade_date") or "")[:10],
                endpoint="local.fund_flow_history", is_live=False,
                is_cached=True, trust_score=0.95,
            )

        started = datetime.now()
        provider_error = ""
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_moneyflow_history(code, target_days),
                timeout=30.0,
            )
            fetched_rows = list(payload.data or [])
            await asyncio.to_thread(
                database_module.market_db.upsert_fund_flow_history, fetched_rows
            )
            local = await asyncio.to_thread(
                database_module.market_db.get_fund_flow_history, code, target_days
            )
            trust = self._record_call(
                "tushare", "moneyflow_history", True,
                (datetime.now() - started).total_seconds() * 1000,
            )
            return {
                "available": bool(local), "source": "tushare",
                "endpoint": "moneyflow", "rows": local,
                "row_count": len(local), "requested_days": target_days,
                "history_complete": len(local) >= target_days,
                "data_date": str(payload.data_date or (local[0].get("trade_date") if local else ""))[:10],
                "fetched_at": datetime.now().isoformat(),
            }, DataProvenance(
                provider="tushare", source_name="Tushare Pro (资金流历史)",
                fetched_at=datetime.now().isoformat(), data_date=str(payload.data_date or "")[:10],
                endpoint="moneyflow", is_live=False, trust_score=trust,
            )
        except Exception as exc:
            provider_error = _exception_detail(exc, 120)
            self._record_call(
                "tushare", "moneyflow_history", False,
                (datetime.now() - started).total_seconds() * 1000, provider_error,
            )
        if local:
            return {
                "available": True, "source": "tushare",
                "endpoint": "local.fund_flow_history", "rows": local,
                "row_count": len(local), "requested_days": target_days,
                "history_complete": False, "provider_errors": provider_error,
                "data_date": str(local[0].get("trade_date") or "")[:10],
                "fetched_at": datetime.now().isoformat(),
            }, DataProvenance(
                provider="tushare", source_name="本地缓存(Tushare资金流历史，部分)",
                fetched_at=datetime.now().isoformat(), data_date=str(local[0].get("trade_date") or "")[:10],
                endpoint="local.fund_flow_history", is_live=False,
                is_cached=True, trust_score=0.8, fallback_reason=provider_error,
            )
        return {
            "available": False, "source": "tushare", "endpoint": "moneyflow",
            "rows": [], "row_count": 0, "requested_days": target_days,
            "history_complete": False, "provider_errors": provider_error,
            "data_date": "", "fetched_at": datetime.now().isoformat(),
        }, DataProvenance(
            provider="tushare", source_name="Tushare Pro (资金流历史)",
            fetched_at=datetime.now().isoformat(), is_live=False, trust_score=0.0,
            endpoint="moneyflow", error_message=provider_error or "tushare_moneyflow_history_unavailable",
        )

    async def get_dragon_tiger(
        self, code: str, trade_date: str = ""
    ) -> tuple[dict, DataProvenance]:
        """Return Tushare's dated billboard summary when a row exists."""
        code = _normalize_market_code(code)
        started = datetime.now()
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_top_list(code, trade_date), timeout=30.0
            )
            records = [
                {
                    "date": str(row.get("trade_date") or "")[:10],
                    "reason": row.get("reason") or "",
                    "net_buy": _number(row.get("net_amount")),
                    "turnover": _number(row.get("turnover_rate")),
                    "close": _number(row.get("close")),
                    "pct_chg": _number(row.get("pct_chg")),
                }
                for row in payload.data
            ]
            data = {
                "records": records,
                "seats": {"buy": [], "sell": []},
                "institution": {},
            }
            latency = (datetime.now() - started).total_seconds() * 1000
            trust = self._record_call("tushare", "top_list", True, latency)
            return data, DataProvenance(
                provider="tushare", source_name="Tushare Pro (龙虎榜摘要)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust, data_date=payload.data_date,
                endpoint=payload.endpoint,
            )
        except Exception as exc:
            latency = (datetime.now() - started).total_seconds() * 1000
            self._record_call("tushare", "top_list", False, latency, str(exc)[:100])
            return {}, DataProvenance(
                provider="tushare", source_name="Tushare Pro (龙虎榜摘要)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=0.0, endpoint="top_list",
                error_message=f"Tushare 龙虎榜获取失败: {str(exc)[:100]}",
            )

    async def _try_tushare_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Get Tushare realtime minutes in-session, otherwise an audited close."""
        started = datetime.now()
        try:
            realtime_error = ""
            try:
                realtime = await asyncio.wait_for(
                    tushare_provider.fetch_realtime_quote(code), timeout=10.0
                )
                quote = dict(realtime.data or {})
                exchange_at = datetime.fromisoformat(
                    str(quote.get("exchange_at") or "").replace(" ", "T")
                )
                now = datetime.now().astimezone()
                if exchange_at.tzinfo is None:
                    exchange_at = exchange_at.replace(tzinfo=now.tzinfo)
                else:
                    exchange_at = exchange_at.astimezone(now.tzinfo)
                age_seconds = (now - exchange_at).total_seconds()
                local_time = now.time().replace(tzinfo=None)
                in_session = (
                    dt_time(9, 30) <= local_time <= dt_time(11, 30)
                    or dt_time(13, 0) <= local_time <= dt_time(15, 0)
                )
                if not in_session or age_seconds < -5 or age_seconds > 180:
                    raise ValueError("tushare_rt_min_stale_or_outside_session")
                payload = realtime
            except Exception as exc:
                realtime_error = f"{type(exc).__name__}:{str(exc)[:80]}"
                payload = await asyncio.wait_for(
                    tushare_provider.fetch_daily_quote(code), timeout=30.0
                )
            quote = dict(payload.data or {})
            source = self._sources["tushare"]
            latency = (datetime.now() - started).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.total_calls += 1
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call("tushare", "quote", True, latency)
            is_live = bool(quote.get("is_realtime"))
            return quote, DataProvenance(
                provider="tushare",
                source_name=(
                    "Tushare Pro (实时分钟)" if is_live
                    else "Tushare Pro (盘后日线)"
                ),
                fetched_at=str(quote.get("fetched_at") or datetime.now().isoformat()),
                is_live=is_live, trust_score=trust, data_date=payload.data_date,
                endpoint=payload.endpoint,
                error_message="" if is_live else realtime_error,
            )
        except Exception as exc:
            self._record_tushare_failure("quote", exc, started)
            return None, DataProvenance(
                provider="tushare", source_name="Tushare Pro (盘后日线)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=0.0, endpoint="daily+daily_basic",
                error_message=f"Tushare 获取失败: {str(exc)[:100]}",
            )

    async def _try_tushare_kline(
        self, code: str, count: int
    ) -> tuple[list[dict] | None, DataProvenance]:
        """Get K-line data from tushare."""
        started = datetime.now()
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_kline(code, count), timeout=30.0
            )
            source = self._sources["tushare"]
            latency = (datetime.now() - started).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.total_calls += 1
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call("tushare", "kline", True, latency)
            return payload.data, DataProvenance(
                provider="tushare", source_name="Tushare Pro (未复权日K)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust, data_date=payload.data_date,
                endpoint=payload.endpoint,
            )
        except Exception as exc:
            self._record_tushare_failure("kline", exc, started)
            return None, DataProvenance(
                provider="tushare", source_name="Tushare Pro (未复权日K)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=0.0, endpoint="daily",
                error_message=f"Tushare K线获取失败: {str(exc)[:100]}",
            )

    async def _try_hithink_kline(
        self, code: str, count: int
    ) -> tuple[list[dict] | None, DataProvenance]:
        """Fetch dated daily bars from HiThink as a bounded fallback."""
        started = datetime.now()
        source = self._sources["hithink"]
        source.total_calls += 1
        target_count = max(1, min(int(count), 2000))
        if not hithink_provider.configured:
            return None, DataProvenance(
                provider="hithink",
                source_name="同花顺金融数据服务(日K)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message="HiThink API 未配置",
            )

        try:
            window_days = max(45, target_count * 3)
            end = datetime.now().date().isoformat()
            start = (datetime.now() - timedelta(days=window_days)).date().isoformat()
            from config.settings import settings

            payload = await asyncio.wait_for(
                hithink_provider.fetch_daily_history(
                    code,
                    start,
                    end,
                    adjust="none",
                ),
                timeout=float(settings.HITHINK_TIMEOUT_SECONDS),
            )
            bars = [row for row in (payload.data or []) if isinstance(row, dict)]
            bars.sort(key=lambda row: str(row.get("date") or ""))
            bars = bars[-target_count:]
            if not bars:
                raise ValueError("HiThink 日K返回空数据")
            latency = (datetime.now() - started).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            completeness = min(1.0, len(bars) / target_count)
            trust = self._record_call(
                "hithink",
                "daily_kline",
                True,
                latency,
                completeness=completeness,
            )
            return bars, DataProvenance(
                provider="hithink",
                source_name="同花顺金融数据服务(日K)",
                fetched_at=payload.fetched_at or datetime.now().isoformat(),
                is_live=False,
                trust_score=trust,
                data_date=payload.data_date,
                endpoint=payload.endpoint,
                coverage_ratio=completeness,
            )
        except Exception as exc:
            latency = (datetime.now() - started).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(exc)[:200]
            source.consecutive_failures += 1
            self._record_call(
                "hithink",
                "daily_kline",
                False,
                latency,
                _exception_detail(exc, 100),
            )
            return None, DataProvenance(
                provider="hithink",
                source_name="同花顺金融数据服务(日K)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                endpoint="/api/a-share/prices/historical",
                error_message=f"HiThink 日K获取失败: {_exception_detail(exc, 100)}",
            )

    async def _try_akshare_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from akshare."""
        source = self._sources["akshare"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import akshare as ak
            raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            df = await asyncio.wait_for(asyncio.to_thread(ak.stock_zh_a_spot_em), timeout=_AKSHARE_TIMEOUT)

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
            df = await asyncio.wait_for(asyncio.to_thread(
                ak.stock_zh_a_hist,
                symbol=raw_code, period="daily",
                start_date="20200101",
                end_date=dt_date.today().strftime("%Y%m%d"),
                adjust="qfq",
            ), timeout=_AKSHARE_TIMEOUT)

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
            df = await asyncio.wait_for(asyncio.to_thread(ak.stock_zh_index_spot_em), timeout=_AKSHARE_TIMEOUT)

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
                data_age_seconds=0,
                is_live=True,
                trust_score=0.95,
                data_date=datetime.now().date().isoformat(),
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

    async def _try_tencent_indices(self) -> tuple[list[dict] | None, DataProvenance]:
        """Get major indices from Tencent (qt.gtimg.cn). 不封IP, akshare 风控时 fallback。"""
        source = self._sources["tencent"]
        source.total_calls += 1

        try:
            import urllib.request
            # 上证sh000001 深成指sz399001 创业板sz399006 科创50 sh000688
            url = "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = await asyncio.wait_for(
                asyncio.to_thread(urllib.request.urlopen, req, None, 8),
                timeout=_AKSHARE_TIMEOUT,
            )
            data = resp.read().decode("gbk")

            wanted = {"上证指数", "深证成指", "创业板指", "科创50"}
            result = []
            for line in data.strip().split(";"):
                if "=" not in line or '"' not in line:
                    continue
                vals = line.split('"')[1].split("~")
                if len(vals) <= 32:
                    continue
                name = vals[1]
                if name in wanted:
                    result.append({
                        "name": name,
                        "code": "",
                        "value": float(vals[3]) if vals[3] else 0,
                        "change_pct": float(vals[32]) if vals[32] else 0,
                    })

            if not result:
                raise ValueError("Tencent returned no indices")

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.success_count += 1
            source.consecutive_failures = 0

            return result, DataProvenance(
                provider="tencent", source_name="腾讯财经 (qt.gtimg.cn)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.9,
                data_date=datetime.now().date().isoformat(),
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="tencent", source_name="腾讯财经 (qt.gtimg.cn)",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"腾讯指数获取失败: {str(e)[:100]}",
            )

    async def _try_tencent_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """单股实时报价 from 腾讯(qt.gtimg.cn). 不封IP, akshare 风控时 fallback。
        字段单位对齐 akshare: amount→元, volume→手, 总市值→元。"""
        source = self._sources["tencent"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import urllib.request
            raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            prefix = "sh" if raw.startswith(("6", "9")) else ("bj" if raw.startswith("8") else "sz")
            url = f"https://qt.gtimg.cn/q={prefix}{raw}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = await asyncio.wait_for(
                asyncio.to_thread(urllib.request.urlopen, req, None, 8),
                timeout=_AKSHARE_TIMEOUT,
            )
            vals = resp.read().decode("gbk").split('"')[1].split("~")
            if len(vals) < 53:
                raise ValueError("Tencent quote truncated")

            def _f(i):
                try:
                    return float(vals[i])
                except (ValueError, IndexError):
                    return 0.0

            price = _f(3)
            if price <= 0:
                raise ValueError(f"Zero price for {raw}")

            amt_wan = _f(37)  # 成交额, 单位万
            exchange_timestamp = vals[30].strip() if len(vals) > 30 else ""
            data_date = (
                f"{exchange_timestamp[:4]}-{exchange_timestamp[4:6]}-"
                f"{exchange_timestamp[6:8]}"
                if len(exchange_timestamp) >= 8 and exchange_timestamp[:8].isdigit()
                else ""
            )
            quote = {
                "stock_code": code,
                "stock_name": vals[1],
                "price": price,
                "change_pct": _f(32),
                "change_amount": _f(31),
                "volume": _f(6),                    # 手
                "amount": amt_wan * 1e4,            # 万→元
                "amount_yi": round(amt_wan / 1e4, 2),
                "high": _f(33) or price,
                "low": _f(34) or price,
                "open": _f(5) or price,
                "pre_close": _f(4) or price,
                "turnover": _f(38),
                "pe": _f(39),
                "pb": _f(46),
                "total_market_cap": _f(44) * 1e8,   # 亿→元
                "data_date": data_date,
                "exchange_timestamp": exchange_timestamp,
                "source": "tencent",
            }

            from src.infrastructure.market_data.validator import validator
            v = validator.validate_quote(quote, code)
            if v.has_errors:
                raise ValueError(f"Validation failed: {v.errors}")

            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call(
                "tencent", "quote", True, latency,
                completeness=0.95,
                validation_passed=True,
            )
            return quote, DataProvenance(
                provider="tencent", source_name="腾讯财经 (qt.gtimg.cn)",
                fetched_at=datetime.now().isoformat(), data_age_seconds=0,
                is_live=True, trust_score=trust,
            )

        except Exception as e:
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            trust = self._record_call(
                "tencent", "quote", False, latency, str(e)[:100],
                completeness=0.0,
                validation_passed=False,
            )
            return None, DataProvenance(
                provider="tencent", source_name="腾讯财经 (qt.gtimg.cn)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust,
                error_message=f"腾讯报价获取失败: {str(e)[:100]}",
            )

    async def _try_tencent_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """前复权日K线 from 腾讯(web.ifzq.gtimg.cn fqkline). 不封IP。
        腾讯K线无成交额字段(amount=0), change_pct 由 close/prev_close 本地算。"""
        source = self._sources["tencent"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import urllib.request, json
            raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            prefix = "sh" if raw.startswith(("6", "9")) else ("bj" if raw.startswith("8") else "sz")
            n = max(count, 640)
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{raw},day,2020-01-01,,{n},qfq"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = await asyncio.wait_for(
                asyncio.to_thread(urllib.request.urlopen, req, None, 8),
                timeout=_AKSHARE_TIMEOUT,
            )
            d = json.loads(resp.read().decode("utf-8"))
            inner = d.get("data", {}).get(f"{prefix}{raw}", {})
            kdata = inner.get("qfqday") or inner.get("day") or []
            if not kdata:
                raise ValueError("Empty kline response")

            klines = []
            prev_close = None
            for bar in kdata[-count:]:
                close = float(bar[2])
                change_pct = round((close / prev_close - 1) * 100, 2) if prev_close else 0.0
                klines.append({
                    "date": bar[0],
                    "open": float(bar[1]),
                    "high": float(bar[3]),
                    "low": float(bar[4]),
                    "close": close,
                    "volume": float(bar[5]) if len(bar) > 5 else 0.0,  # 手
                    "amount": 0.0,  # 腾讯K线无成交额
                    "change_pct": change_pct,
                })
                prev_close = close

            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call(
                "tencent", "kline", True, latency,
                completeness=0.85,
                validation_passed=True,
            )
            return klines, DataProvenance(
                provider="tencent", source_name="腾讯财经 (K线 qfq)",
                fetched_at=datetime.now().isoformat(), data_age_seconds=0,
                is_live=True, trust_score=trust,
            )

        except Exception as e:
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            trust = self._record_call(
                "tencent", "kline", False, latency, str(e)[:100],
                completeness=0.0,
                validation_passed=False,
            )
            return None, DataProvenance(
                provider="tencent", source_name="腾讯财经 (K线 qfq)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust,
                error_message=f"腾讯K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # TickFlow provider — authenticated API for real-time quote/K-line
    # ================================================================

    async def _try_tickflow_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        source = self._sources["tickflow"]
        source.total_calls += 1
        t0 = datetime.now()
        try:
            from src.infrastructure.market_data.tickflow_provider import fetch_quote

            quote = await asyncio.to_thread(fetch_quote, code)
            if float(quote.get("price") or 0) <= 0:
                raise ValueError(f"TickFlow returned zero price for {code}")
            from src.infrastructure.market_data.validator import validator
            validation = validator.validate_quote(quote, code)
            if validation.has_errors:
                raise ValueError(f"Validation failed: {validation.errors}")

            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call(
                "tickflow", "quote", True, latency,
                completeness=0.95, validation_passed=True,
            )
            return quote, DataProvenance(
                provider="tickflow", source_name="TickFlow API",
                fetched_at=datetime.now().isoformat(), data_age_seconds=0,
                is_live=True, trust_score=trust,
            )
        except Exception as exc:
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(exc)[:200]
            source.consecutive_failures += 1
            trust = self._record_call(
                "tickflow", "quote", False, latency, str(exc)[:100],
                completeness=0.0, validation_passed=False,
            )
            return None, DataProvenance(
                provider="tickflow", source_name="TickFlow API",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust,
                error_message=f"TickFlow 报价获取失败: {str(exc)[:100]}",
            )

    async def _try_tickflow_kline(
        self, code: str, count: int
    ) -> tuple[list[dict] | None, DataProvenance]:
        source = self._sources["tickflow"]
        source.total_calls += 1
        t0 = datetime.now()
        try:
            from src.infrastructure.market_data.tickflow_provider import fetch_klines

            klines = await asyncio.to_thread(
                fetch_klines, code, count,
            )
            if not klines:
                raise ValueError(f"TickFlow returned no K-lines for {code}")
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.last_error = ""
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call(
                "tickflow", "kline", True, latency,
                completeness=0.95, validation_passed=True,
            )
            return klines, DataProvenance(
                provider="tickflow", source_name="TickFlow API (日K)",
                fetched_at=datetime.now().isoformat(), data_age_seconds=0,
                is_live=True, trust_score=trust,
            )
        except Exception as exc:
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(exc)[:200]
            source.consecutive_failures += 1
            trust = self._record_call(
                "tickflow", "kline", False, latency, str(exc)[:100],
                completeness=0.0, validation_passed=False,
            )
            return None, DataProvenance(
                provider="tickflow", source_name="TickFlow API (日K)",
                fetched_at=datetime.now().isoformat(), is_live=False,
                trust_score=trust,
                error_message=f"TickFlow K线获取失败: {str(exc)[:100]}",
            )

    # ================================================================
    # Sina provider — independent HTTP fallback for A-share quote/K-line
    # ================================================================

    @staticmethod
    def _sina_symbol(code: str) -> str:
        raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        prefix = (
            "sh"
            if raw.startswith(("5", "6", "9"))
            else "bj"
            if raw.startswith(("4", "8"))
            else "sz"
        )
        return f"{prefix}{raw}"

    async def _try_sina_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Fetch a real quote from Sina; volume is normalized from shares to lots."""
        source = self._sources["sina"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import urllib.request

            symbol = self._sina_symbol(code)
            url = f"https://hq.sinajs.cn/list={symbol}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            resp = await asyncio.wait_for(
                asyncio.to_thread(urllib.request.urlopen, req, None, 8),
                timeout=_AKSHARE_TIMEOUT,
            )
            text = resp.read().decode("gb18030", errors="replace")
            if '="' not in text:
                raise ValueError("Sina quote response is malformed")
            values = text.split('="', 1)[1].rsplit('"', 1)[0].split(",")
            if len(values) < 32:
                raise ValueError("Sina quote response is truncated")

            def _f(index: int) -> float:
                try:
                    return float(values[index])
                except (IndexError, TypeError, ValueError):
                    return 0.0

            price = _f(3)
            pre_close = _f(2)
            if price <= 0:
                raise ValueError(f"Zero price for {symbol}")
            change_amount = price - pre_close if pre_close > 0 else 0.0
            change_pct = change_amount / pre_close * 100 if pre_close > 0 else 0.0
            data_date = values[30].strip()
            quote_time = values[31].strip()
            exchange_timestamp = "".join(
                character for character in f"{data_date}{quote_time}" if character.isdigit()
            )
            amount = _f(9)
            quote = {
                "stock_code": code,
                "stock_name": values[0].strip(),
                "price": price,
                "change_pct": round(change_pct, 4),
                "change_amount": round(change_amount, 4),
                "volume": _f(8) / 100,  # 股 -> 手
                "amount": amount,
                "amount_yi": round(amount / 1e8, 2),
                "high": _f(4) or price,
                "low": _f(5) or price,
                "open": _f(1) or price,
                "pre_close": pre_close or price,
                "turnover": 0.0,
                "pe": 0.0,
                "pb": 0.0,
                "total_market_cap": 0.0,
                "data_date": data_date,
                "exchange_timestamp": exchange_timestamp,
                "source": "sina",
            }

            from src.infrastructure.market_data.validator import validator

            validation = validator.validate_quote(quote, code)
            if validation.has_errors:
                raise ValueError(f"Validation failed: {validation.errors}")

            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call(
                "sina", "quote", True, latency,
                completeness=0.8,
                validation_passed=True,
            )
            return quote, DataProvenance(
                provider="sina",
                source_name="新浪财经 (hq.sinajs.cn)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=trust,
            )
        except Exception as exc:
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(exc)[:200]
            source.consecutive_failures += 1
            trust = self._record_call(
                "sina", "quote", False, latency, str(exc)[:100],
                completeness=0.0,
                validation_passed=False,
            )
            return None, DataProvenance(
                provider="sina",
                source_name="新浪财经 (hq.sinajs.cn)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=trust,
                error_message=f"新浪报价获取失败: {str(exc)[:100]}",
            )

    async def _try_sina_kline(
        self, code: str, count: int,
    ) -> tuple[list[dict] | None, DataProvenance]:
        """Fetch unadjusted daily bars from Sina as a last-resort real source."""
        source = self._sources["sina"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import json
            import urllib.parse
            import urllib.request

            symbol = self._sina_symbol(code)
            params = urllib.parse.urlencode({
                "symbol": symbol,
                "scale": "240",
                "ma": "no",
                "datalen": str(max(1, min(int(count), 1023))),
            })
            url = (
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"CN_MarketData.getKLineData?{params}"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            resp = await asyncio.wait_for(
                asyncio.to_thread(urllib.request.urlopen, req, None, 8),
                timeout=_AKSHARE_TIMEOUT,
            )
            rows = json.loads(resp.read().decode("utf-8"))
            if not isinstance(rows, list) or not rows:
                raise ValueError("Sina returned no K-line rows")

            klines = []
            previous_close = None
            for row in rows[-count:]:
                close = float(row.get("close") or 0)
                if close <= 0:
                    continue
                change_pct = (
                    round((close / previous_close - 1) * 100, 4)
                    if previous_close
                    else 0.0
                )
                klines.append({
                    "date": str(row.get("day") or "")[:10],
                    "open": float(row.get("open") or 0),
                    "high": float(row.get("high") or 0),
                    "low": float(row.get("low") or 0),
                    "close": close,
                    "volume": float(row.get("volume") or 0) / 100,  # 股 -> 手
                    "amount": 0.0,
                    "change_pct": change_pct,
                })
                previous_close = close
            if not klines:
                raise ValueError("Sina K-line rows contain no valid prices")

            from src.infrastructure.market_data.validator import validator

            validation = validator.validate_klines(klines, code)
            if validation.has_errors:
                raise ValueError(f"Validation failed: {validation.errors}")

            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0
            trust = self._record_call(
                "sina", "kline", True, latency,
                completeness=0.75,
                validation_passed=True,
            )
            return klines, DataProvenance(
                provider="sina",
                source_name="新浪财经 (未复权日K)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=trust,
            )
        except Exception as exc:
            latency = (datetime.now() - t0).total_seconds() * 1000
            source.is_available = False
            source.last_error = str(exc)[:200]
            source.consecutive_failures += 1
            trust = self._record_call(
                "sina", "kline", False, latency, str(exc)[:100],
                completeness=0.0,
                validation_passed=False,
            )
            return None, DataProvenance(
                provider="sina",
                source_name="新浪财经 (未复权日K)",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=trust,
                error_message=f"新浪K线获取失败: {str(exc)[:100]}",
            )

    async def _try_akshare_breadth(self) -> tuple[dict | None, DataProvenance]:
        """Try getting market breadth from akshare."""
        source = self._sources["akshare"]
        source.total_calls += 1

        try:
            import akshare as ak
            df = await asyncio.wait_for(asyncio.to_thread(ak.stock_zh_a_spot_em), timeout=_AKSHARE_TIMEOUT)

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

            data_date = datetime.now().date().isoformat()
            return {
                "up": up, "down": down, "flat": flat,
                "limit_up": limit_up, "limit_down": limit_down,
                "total_volume": total_vol,
                "data_date": data_date,
            }, DataProvenance(
                provider="akshare", source_name="东方财富(AkShare)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=0.95,
                data_date=data_date,
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
    # Baostock provider — fallback when akshare is blocked
    # ================================================================

    async def _try_baostock_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote via baostock (K-line based, not real-time).

        Baostock doesn't have spot quotes, but we can use the latest
        trading day's K-line as the current price. Trust score is lower
        than akshare because this is end-of-day data, not intraday.
        """
        # 后台全量同步进行中时跳过 baostock(避免与 sync 长 session 互踢),改走其他 provider
        from src.infrastructure.market_data.baostock_lock import is_sync_in_progress
        if is_sync_in_progress():
            return None, DataProvenance(
                provider="baostock",
                source_name="BaoStock",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message="数据同步进行中,baostock 暂时跳过",
            )
        source = self._sources["baostock"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import baostock as bs
            from datetime import date as dt_date, timedelta

                # Map code to baostock format.
            if ".SH" in code:
                bs_code = f"sh.{code.replace('.SH', '')}"
            elif ".SZ" in code:
                bs_code = f"sz.{code.replace('.SZ', '')}"
            elif ".BJ" in code:
                bs_code = f"bj.{code.replace('.BJ', '')}"
            else:
                bs_code = f"sz.{code}"

            # Login
            lg = await asyncio.to_thread(bs.login)
            if lg.error_code != '0':
                raise ValueError(f"Baostock login failed: {lg.error_msg}")

            try:
                today = dt_date.today()
                start = (today - timedelta(days=10)).strftime('%Y-%m-%d')
                end = today.strftime('%Y-%m-%d')

                rs = await asyncio.to_thread(
                    bs.query_history_k_data_plus,
                    bs_code,
                    'date,open,high,low,close,preclose,volume,amount,turn,peTTM',
                    start_date=start, end_date=end,
                    frequency='d', adjustflag='3',
                )

                if rs.error_code != '0':
                    raise ValueError(f"Baostock query failed: {rs.error_msg}")

                rows = []
                while (rs.error_code == '0') & rs.next():
                    rows.append(rs.get_row_data())

                if not rows:
                    raise ValueError(f"No data for {bs_code}")

                # Use latest row as current quote
                latest = rows[-1]
                prev = rows[-2] if len(rows) >= 2 else latest

                price = float(latest[4]) if latest[4] else 0  # close
                pre_close = float(latest[5]) if latest[5] else float(prev[4]) if len(rows) >= 2 else price  # preclose
                change_pct = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0

                # Get stock name
                rs_name = await asyncio.to_thread(
                    bs.query_stock_basic, code=bs_code
                )
                stock_name = code
                if rs_name.error_code == '0':
                    name_rows = []
                    while rs_name.next():
                        name_rows.append(rs_name.get_row_data())
                    if name_rows and len(name_rows[0]) > 1:
                        stock_name = name_rows[0][1]

                latency = (datetime.now() - t0).total_seconds() * 1000

                quote = {
                    "stock_code": code,
                    "stock_name": stock_name,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "change_amount": round(price - pre_close, 2),
                    "volume": float(latest[6]) if latest[6] else 0,
                    "amount": float(latest[7]) if latest[7] else 0,
                    "amount_yi": round(float(latest[7]) / 1e8, 2) if latest[7] else 0,
                    "high": float(latest[2]) if latest[2] else 0,
                    "low": float(latest[3]) if latest[3] else 0,
                    "open": float(latest[1]) if latest[1] else 0,
                    "pre_close": pre_close,
                    "turnover": float(latest[8]) if len(latest) > 8 and latest[8] else 0,
                    "pe": float(latest[9]) if len(latest) > 9 and latest[9] else 0,
                    "total_market_cap": 0,  # baostock doesn't provide this in K-line
                }

                source.is_available = True
                source.last_success_at = datetime.now().isoformat()
                source.latency_ms = latency
                source.success_count += 1
                source.consecutive_failures = 0

                # Note: baostock data is EOD — dynamic trust reflects actual reliability
                dyn_trust = self._record_call("baostock", "quote", True, latency)
                return quote, DataProvenance(
                    provider="baostock",
                    source_name="BaoStock (日线/EOD)",
                    fetched_at=datetime.now().isoformat(),
                    data_age_seconds=0,
                    is_live=False,
                    trust_score=dyn_trust,
                )

            finally:
                await asyncio.to_thread(bs.logout)

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            try:
                import baostock as bs
                bs.logout()
            except Exception:
                pass

            return None, DataProvenance(
                provider="baostock",
                source_name="BaoStock",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"BaoStock 获取失败: {str(e)[:100]}",
            )

    async def _try_baostock_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line data from baostock."""
        # 后台全量同步进行中时跳过 baostock(避免与 sync 长 session 互踢),改走其他 provider
        from src.infrastructure.market_data.baostock_lock import is_sync_in_progress
        if is_sync_in_progress():
            return None, DataProvenance(
                provider="baostock",
                source_name="BaoStock",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message="数据同步进行中,baostock 暂时跳过",
            )
        source = self._sources["baostock"]
        source.total_calls += 1
        t0 = datetime.now()

        try:
            import baostock as bs
            from datetime import date as dt_date, timedelta

            if ".SH" in code:
                bs_code = f"sh.{code.replace('.SH', '')}"
            elif ".SZ" in code:
                bs_code = f"sz.{code.replace('.SZ', '')}"
            elif ".BJ" in code:
                bs_code = f"bj.{code.replace('.BJ', '')}"
            else:
                bs_code = f"sz.{code}"

            lg = await asyncio.to_thread(bs.login)
            if lg.error_code != '0':
                raise ValueError(f"Baostock login failed: {lg.error_msg}")

            try:
                today = dt_date.today()
                # Go back far enough to get 'count' trading days (~count * 1.5 calendar days)
                start = (today - timedelta(days=int(count * 1.8))).strftime('%Y-%m-%d')
                end = today.strftime('%Y-%m-%d')

                rs = await asyncio.to_thread(
                    bs.query_history_k_data_plus,
                    bs_code,
                    (
                        'date,open,high,low,close,preclose,volume,amount,turn,'
                        'tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST'
                    ),
                    start_date=start, end_date=end,
                    frequency='d', adjustflag='2',
                )

                if rs.error_code != '0':
                    raise ValueError(f"Baostock query failed: {rs.error_msg}")

                rows = []
                while (rs.error_code == '0') & rs.next():
                    rows.append(rs.get_row_data())

                if not rows:
                    raise ValueError(f"No K-line data for {bs_code}")

                # Take last 'count' rows
                rows = rows[-count:]

                klines = []
                for r in rows:
                    klines.append({
                        "date": r[0],
                        "open": float(r[1]) if r[1] else 0,
                        "high": float(r[2]) if r[2] else 0,
                        "low": float(r[3]) if r[3] else 0,
                        "close": float(r[4]) if r[4] else 0,
                        "pre_close": float(r[5]) if r[5] else 0,
                        "volume": float(r[6]) if r[6] else 0,
                        "amount": float(r[7]) if r[7] else 0,
                        "turnover": float(r[8]) if r[8] else 0,
                        "trade_status": "trading" if r[9] == "1" else "suspended",
                        "change_pct": float(r[10]) if r[10] else 0,
                        "pe_ttm": float(r[11]) if r[11] else None,
                        "pb_mrq": float(r[12]) if r[12] else None,
                        "ps_ttm": float(r[13]) if r[13] else None,
                        "pcf_ncf_ttm": float(r[14]) if r[14] else None,
                        "is_st": r[15] == "1",
                        "adjustment_mode": "qfq",
                    })

                latency = (datetime.now() - t0).total_seconds() * 1000

                source.is_available = True
                source.last_success_at = datetime.now().isoformat()
                source.latency_ms = latency
                source.success_count += 1
                source.consecutive_failures = 0

                return klines, DataProvenance(
                    provider="baostock",
                    source_name="BaoStock (历史K线)",
                    fetched_at=datetime.now().isoformat(),
                    data_age_seconds=0,
                    is_live=True,
                    trust_score=0.88,
                )

            finally:
                await asyncio.to_thread(bs.logout)

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            try:
                import baostock as bs
                bs.logout()
            except Exception:
                pass

            return None, DataProvenance(
                provider="baostock",
                source_name="BaoStock",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"BaoStock K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # Finnhub provider — official API, 60 req/min, news + financials
    # ================================================================

    def _code_to_finnhub_symbol(self, code: str) -> str | None:
        """Convert Chinese stock code to Finnhub symbol format.

        Finnhub uses standard exchange suffixes for global stocks.
        A-share support may be limited — primarily useful for US/HK stocks.
        """
        raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if ".SH" in code:
            return f"{raw}.SS"    # Shanghai
        elif ".SZ" in code:
            return f"{raw}.SZ"    # Shenzhen
        elif ".BJ" in code:
            return f"{raw}.BJ"
        return None

    async def _try_finnhub_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from Finnhub.

        Uses /quote endpoint. Free tier: 60 requests/min.
        Also fetches company profile for stock name.
        """
        source = self._sources["finnhub"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_finnhub_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="finnhub", source_name="Finnhub",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Finnhub: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            # Fetch quote
            quote_url = (
                f"{FINNHUB_BASE_URL}/quote"
                f"?symbol={symbol}&token={FINNHUB_API_KEY}"
            )
            req = urllib.request.Request(quote_url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            q = _json.loads(resp.read().decode())

            if q.get("error"):
                raise ValueError(f"Finnhub API error: {q.get('error')}")

            price = float(q.get("c", 0))  # current price
            if price == 0:
                raise ValueError(f"No price data for {symbol}")

            pre_close = float(q.get("pc", price))
            change_pct = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0
            high = float(q.get("h", price))
            low = float(q.get("l", price))
            open_p = float(q.get("o", price))

            # Fetch company name
            stock_name = symbol
            try:
                profile_url = (
                    f"{FINNHUB_BASE_URL}/stock/profile2"
                    f"?symbol={symbol}&token={FINNHUB_API_KEY}"
                )
                req2 = urllib.request.Request(profile_url)
                req2.add_header("User-Agent", "QuantAI/1.0")
                resp2 = await asyncio.to_thread(urllib.request.urlopen, req2, None, 10)
                profile = _json.loads(resp2.read().decode())
                if profile.get("name"):
                    stock_name = profile["name"]
            except Exception:
                pass  # Name fetch is best-effort

            latency = (datetime.now() - t0).total_seconds() * 1000

            quote = {
                "stock_code": code,
                "stock_name": stock_name,
                "price": price,
                "change_pct": round(change_pct, 2),
                "change_amount": round(price - pre_close, 2),
                "volume": 0,
                "amount": 0,
                "amount_yi": 0,
                "high": high,
                "low": low,
                "open": open_p,
                "pre_close": pre_close,
                "turnover": 0,
                "pe": 0,
                "total_market_cap": 0,
            }

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return quote, DataProvenance(
                provider="finnhub",
                source_name="Finnhub (官方API)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.94,  # Official API, high rate limit, real-time
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="finnhub", source_name="Finnhub",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"Finnhub 获取失败: {str(e)[:100]}",
            )

    async def _try_finnhub_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line data from Finnhub.

        Uses /stock/candle endpoint. Resolution: D (daily).
        """
        source = self._sources["finnhub"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_finnhub_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="finnhub", source_name="Finnhub",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Finnhub: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json
            import time as _time

            now_ts = int(_time.time())
            # Finnhub free tier: up to 1 year of daily data
            from_ts = now_ts - (count * 2 * 86400)  # ~count * 2 days to cover weekends

            url = (
                f"{FINNHUB_BASE_URL}/stock/candle"
                f"?symbol={symbol}&resolution=D"
                f"&from={from_ts}&to={now_ts}"
                f"&token={FINNHUB_API_KEY}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            data = _json.loads(resp.read().decode())

            if data.get("s") == "no_data":
                raise ValueError(f"No candle data for {symbol}")
            if data.get("error"):
                raise ValueError(f"Finnhub API error: {data.get('error')}")

            t = data.get("t", [])  # timestamps
            o = data.get("o", [])  # open
            h = data.get("h", [])  # high
            l = data.get("l", [])  # low
            c = data.get("c", [])  # close
            v = data.get("v", [])  # volume

            if not t:
                raise ValueError(f"Empty candle data for {symbol}")

            from datetime import datetime as dt

            klines = []
            for i in range(len(t)):
                klines.append({
                    "date": dt.fromtimestamp(t[i]).strftime("%Y-%m-%d"),
                    "open": float(o[i]),
                    "high": float(h[i]),
                    "low": float(l[i]),
                    "close": float(c[i]),
                    "volume": int(v[i]),
                    "amount": 0,
                })

            klines = klines[-count:]

            latency = (datetime.now() - t0).total_seconds() * 1000

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return klines, DataProvenance(
                provider="finnhub",
                source_name="Finnhub (官方K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.94,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="finnhub", source_name="Finnhub",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"Finnhub K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # FMP (Financial Modeling Prep) provider — financials focus
    # ================================================================

    def _code_to_fmp_symbol(self, code: str) -> str | None:
        """Convert Chinese stock code to FMP symbol format."""
        raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if ".SH" in code:
            return f"{raw}.SS"
        elif ".SZ" in code:
            return f"{raw}.SZ"
        elif ".BJ" in code:
            return f"{raw}.BJ"
        return None

    async def _try_fmp_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from Financial Modeling Prep.

        Uses /quote endpoint. Free tier: 250 req/day.
        Also fetches company profile for name + sector + PE.
        """
        source = self._sources["fmp"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_fmp_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="fmp", source_name="FMP",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="FMP: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            # Fetch quote
            quote_url = f"{FMP_BASE_URL}/quote/{symbol}?apikey={FMP_API_KEY}"
            req = urllib.request.Request(quote_url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            quotes = _json.loads(resp.read().decode())

            if not quotes or not isinstance(quotes, list) or len(quotes) == 0:
                raise ValueError(f"No quote data for {symbol}")

            q = quotes[0]
            price = float(q.get("price", 0))
            if price == 0:
                raise ValueError(f"No price for {symbol}")

            change_pct = float(q.get("changesPercentage", 0))
            change_amount = float(q.get("change", 0))
            pre_close = price - change_amount if change_amount else price

            stock_name = q.get("name", symbol)
            pe_val = float(q.get("pe", 0)) if q.get("pe") else 0
            market_cap = float(q.get("marketCap", 0)) if q.get("marketCap") else 0
            volume = int(q.get("volume", 0))
            high = float(q.get("dayHigh", price))
            low = float(q.get("dayLow", price))
            open_p = float(q.get("open", price))
            prev_close = float(q.get("previousClose", price))

            latency = (datetime.now() - t0).total_seconds() * 1000

            quote = {
                "stock_code": code,
                "stock_name": stock_name,
                "price": price,
                "change_pct": round(change_pct, 2),
                "change_amount": round(change_amount, 2),
                "volume": volume,
                "amount": 0,
                "amount_yi": 0,
                "high": high,
                "low": low,
                "open": open_p,
                "pre_close": prev_close,
                "turnover": 0,
                "pe": round(pe_val, 2),
                "total_market_cap": market_cap,
            }

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return quote, DataProvenance(
                provider="fmp",
                source_name="FMP (财报+估值)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.93,  # Strong for fundamental data
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="fmp", source_name="FMP",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"FMP 获取失败: {str(e)[:100]}",
            )

    async def _try_fmp_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line data from FMP.

        Uses /historical-price-full endpoint. Up to 10 years daily.
        """
        source = self._sources["fmp"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_fmp_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="fmp", source_name="FMP",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="FMP: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            url = (
                f"{FMP_BASE_URL}/historical-price-full/{symbol}"
                f"?timeseries={count}"
                f"&apikey={FMP_API_KEY}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            data = _json.loads(resp.read().decode())

            if not data or "historical" not in data:
                raise ValueError(f"No historical data for {symbol}")

            historical = data["historical"][-count:]  # Take last 'count' entries

            klines = []
            for entry in reversed(historical):  # FMP returns newest first
                klines.append({
                    "date": entry.get("date", ""),
                    "open": float(entry.get("open", 0)),
                    "high": float(entry.get("high", 0)),
                    "low": float(entry.get("low", 0)),
                    "close": float(entry.get("close", 0)),
                    "volume": int(entry.get("volume", 0)),
                    "amount": 0,
                })

            klines = list(reversed(klines))  # Back to chronological order
            klines = klines[-count:]

            latency = (datetime.now() - t0).total_seconds() * 1000

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return klines, DataProvenance(
                provider="fmp",
                source_name="FMP (历史K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.93,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="fmp", source_name="FMP",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"FMP K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # Twelve Data provider — 800 req/day, K-line + MACD/RSI/EMA
    # ================================================================

    def _code_to_twelvedata_symbol(self, code: str) -> str | None:
        """Convert Chinese stock code to Twelve Data symbol format."""
        raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if ".SH" in code:
            return f"{raw}.SS"
        elif ".SZ" in code:
            return f"{raw}.SZ"
        elif ".BJ" in code:
            return f"{raw}.BJ"
        return None

    async def _try_twelvedata_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from Twelve Data.

        Uses /quote endpoint. Free tier: 800 req/day. Clean API.
        """
        source = self._sources["twelvedata"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_twelvedata_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="twelvedata", source_name="Twelve Data",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Twelve Data: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            url = (
                f"{TWELVEDATA_BASE_URL}/quote"
                f"?symbol={symbol}&apikey={TWELVEDATA_API_KEY}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            q = _json.loads(resp.read().decode())

            if q.get("code") and q.get("code") != 200:
                raise ValueError(f"Twelve Data error: {q.get('message', q)}")

            price = float(q.get("close", 0))
            if price == 0:
                raise ValueError(f"No price for {symbol}")

            pre_close = float(q.get("previous_close", price))
            change_pct = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0
            change_amount = price - pre_close

            quote = {
                "stock_code": code,
                "stock_name": q.get("name", symbol),
                "price": price,
                "change_pct": round(change_pct, 2),
                "change_amount": round(change_amount, 2),
                "volume": int(q.get("volume", 0)),
                "amount": 0,
                "amount_yi": 0,
                "high": float(q.get("high", price)),
                "low": float(q.get("low", price)),
                "open": float(q.get("open", price)),
                "pre_close": pre_close,
                "turnover": 0,
                "pe": 0,
                "total_market_cap": 0,
            }

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = (datetime.now() - t0).total_seconds() * 1000
            source.success_count += 1
            source.consecutive_failures = 0

            return quote, DataProvenance(
                provider="twelvedata",
                source_name="Twelve Data (官方API)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.93,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="twelvedata", source_name="Twelve Data",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"Twelve Data 获取失败: {str(e)[:100]}",
            )

    async def _try_twelvedata_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line data from Twelve Data.

        Uses /time_series endpoint. Supports MACD/RSI/EMA as add-ons.
        """
        source = self._sources["twelvedata"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_twelvedata_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="twelvedata", source_name="Twelve Data",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Twelve Data: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            url = (
                f"{TWELVEDATA_BASE_URL}/time_series"
                f"?symbol={symbol}&interval=1day"
                f"&outputsize={min(count, 500)}"
                f"&apikey={TWELVEDATA_API_KEY}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            data = _json.loads(resp.read().decode())

            if data.get("code") and data.get("code") != 200:
                raise ValueError(f"Twelve Data error: {data.get('message', data)}")

            values = data.get("values", [])
            if not values:
                raise ValueError(f"No time series data for {symbol}")

            klines = []
            for entry in reversed(values):
                klines.append({
                    "date": entry.get("datetime", ""),
                    "open": float(entry.get("open", 0)),
                    "high": float(entry.get("high", 0)),
                    "low": float(entry.get("low", 0)),
                    "close": float(entry.get("close", 0)),
                    "volume": int(entry.get("volume", 0)),
                    "amount": 0,
                })

            klines = klines[-count:]

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = (datetime.now() - t0).total_seconds() * 1000
            source.success_count += 1
            source.consecutive_failures = 0

            return klines, DataProvenance(
                provider="twelvedata",
                source_name="Twelve Data (官方K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.93,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="twelvedata", source_name="Twelve Data",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"Twelve Data K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # Polygon.io provider — professional-grade, stocks/forex/crypto
    # ================================================================

    def _code_to_polygon_symbol(self, code: str) -> str | None:
        """Convert Chinese stock code to Polygon.io symbol format."""
        raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if ".SH" in code:
            return f"{raw}.SS"
        elif ".SZ" in code:
            return f"{raw}.SZ"
        elif ".BJ" in code:
            return f"{raw}.BJ"
        return None

    async def _try_polygon_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from Polygon.io.

        Uses /v2/aggs/ticker/{symbol}/prev endpoint. Professional data quality.
        """
        source = self._sources["polygon"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_polygon_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="polygon", source_name="Polygon.io",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Polygon.io: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            url = (
                f"{POLYGON_BASE_URL}/aggs/ticker/{symbol}/prev"
                f"?apikey={POLYGON_API_KEY}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            data = _json.loads(resp.read().decode())

            if data.get("status") == "ERROR":
                raise ValueError(f"Polygon.io error: {data.get('error', 'unknown')}")

            results = data.get("results", [])
            if not results:
                raise ValueError(f"No data for {symbol}")

            r = results[0]
            price = float(r.get("c", 0))  # close
            if price == 0:
                raise ValueError(f"No price for {symbol}")

            open_p = float(r.get("o", price))
            high = float(r.get("h", price))
            low = float(r.get("l", price))
            volume = int(r.get("v", 0))
            # Estimate previous close from open and change
            pre_close = open_p  # Approximate with open as prior close

            quote = {
                "stock_code": code,
                "stock_name": symbol,
                "price": price,
                "change_pct": round((price - pre_close) / pre_close * 100, 2) if pre_close else 0,
                "change_amount": round(price - pre_close, 2),
                "volume": volume,
                "amount": 0, "amount_yi": 0,
                "high": high, "low": low, "open": open_p,
                "pre_close": pre_close, "turnover": 0, "pe": 0, "total_market_cap": 0,
            }

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = (datetime.now() - t0).total_seconds() * 1000
            source.success_count += 1
            source.consecutive_failures = 0

            return quote, DataProvenance(
                provider="polygon",
                source_name="Polygon.io (专业级)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=0.95,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="polygon", source_name="Polygon.io",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"Polygon.io 获取失败: {str(e)[:100]}",
            )

    async def _try_polygon_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line data from Polygon.io.

        Uses /v2/aggs/ticker/{symbol}/range/1/day endpoint.
        """
        source = self._sources["polygon"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_polygon_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="polygon", source_name="Polygon.io",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Polygon.io: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json
            from datetime import date as dt_date, timedelta

            today = dt_date.today()
            start = (today - timedelta(days=count * 2)).strftime("%Y-%m-%d")
            end = today.strftime("%Y-%m-%d")

            url = (
                f"{POLYGON_BASE_URL}/aggs/ticker/{symbol}/range/1/day"
                f"/{start}/{end}"
                f"?limit={count}&apikey={POLYGON_API_KEY}"
            )
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
            data = _json.loads(resp.read().decode())

            if data.get("status") == "ERROR":
                raise ValueError(f"Polygon.io error: {data.get('error', 'unknown')}")

            results = data.get("results", [])
            if not results:
                raise ValueError(f"No historical data for {symbol}")

            from datetime import datetime as dt

            klines = []
            for r in results[-count:]:
                ts = r.get("t", 0) / 1000  # Polygon returns ms timestamps
                klines.append({
                    "date": dt.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "open": float(r.get("o", 0)),
                    "high": float(r.get("h", 0)),
                    "low": float(r.get("l", 0)),
                    "close": float(r.get("c", 0)),
                    "volume": int(r.get("v", 0)),
                    "amount": 0,
                })

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = (datetime.now() - t0).total_seconds() * 1000
            source.success_count += 1
            source.consecutive_failures = 0

            return klines, DataProvenance(
                provider="polygon",
                source_name="Polygon.io (专业K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0, is_live=True, trust_score=0.95,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="polygon", source_name="Polygon.io",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message=f"Polygon.io K线获取失败: {str(e)[:100]}",
            )

    # ================================================================
    # Alpha Vantage provider — official API, global coverage
    # ================================================================

    def _code_to_alphavantage_symbol(self, code: str) -> str | None:
        """Convert Chinese stock code to Alpha Vantage symbol format.

        Alpha Vantage primarily supports US stocks. For Chinese stocks,
        we try SSE/SZSE prefix formats. Returns None if unsupported.
        """
        raw = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if ".SH" in code:
            return f"{raw}.SS"
        elif ".SZ" in code:
            return f"{raw}.SZ"   # Shenzhen: 000725.SZ
        elif ".BJ" in code:
            return f"{raw}.BJ"
        return None

    async def _try_alphavantage_quote(self, code: str) -> tuple[dict | None, DataProvenance]:
        """Try getting a quote from Alpha Vantage.

        Uses GLOBAL_QUOTE endpoint. Free tier: 25 requests/day.
        Primarily supports US stocks — A-share coverage is limited.
        """
        source = self._sources["alphavantage"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_alphavantage_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="alphavantage",
                source_name="Alpha Vantage",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Alpha Vantage: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            url = (
                f"{ALPHA_VANTAGE_BASE_URL}"
                f"?function=GLOBAL_QUOTE"
                f"&symbol={symbol}"
                f"&apikey={ALPHA_VANTAGE_API_KEY}"
            )

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(
                urllib.request.urlopen, req, None, 10
            )
            data = _json.loads(resp.read().decode())

            # Check for rate limit / error
            if "Note" in data:
                raise ValueError("Alpha Vantage rate limit: thank you for using Alpha Vantage")
            if "Error Message" in data:
                raise ValueError(f"Alpha Vantage API error: {data['Error Message']}")

            quote_data = data.get("Global Quote", {})
            if not quote_data or not quote_data.get("05. price"):
                raise ValueError(f"No quote data for {symbol}")

            price = float(quote_data.get("05. price", 0))
            change_pct = float(quote_data.get("10. change percent", "0%").replace("%", ""))
            change_amount = float(quote_data.get("09. change", 0))
            pre_close = price - change_amount if change_amount else price
            volume = int(quote_data.get("06. volume", 0))

            latency = (datetime.now() - t0).total_seconds() * 1000

            quote = {
                "stock_code": code,
                "stock_name": symbol,
                "price": price,
                "change_pct": round(change_pct, 2),
                "change_amount": round(change_amount, 2),
                "volume": volume,
                "amount": 0,
                "amount_yi": 0,
                "high": float(quote_data.get("03. high", price)),
                "low": float(quote_data.get("04. low", price)),
                "open": float(quote_data.get("02. open", price)),
                "pre_close": pre_close,
                "turnover": 0,
                "pe": 0,
                "total_market_cap": 0,
            }

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return quote, DataProvenance(
                provider="alphavantage",
                source_name="Alpha Vantage (官方API)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.93,  # Official API, high trust
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="alphavantage",
                source_name="Alpha Vantage",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"Alpha Vantage 获取失败: {str(e)[:100]}",
            )

    async def _try_alphavantage_kline(self, code: str, count: int) -> tuple[list[dict] | None, DataProvenance]:
        """Try getting K-line data from Alpha Vantage.

        Uses TIME_SERIES_DAILY endpoint. Returns up to 'count' daily candles.
        """
        source = self._sources["alphavantage"]
        source.total_calls += 1
        t0 = datetime.now()

        symbol = self._code_to_alphavantage_symbol(code)
        if symbol is None:
            return None, DataProvenance(
                provider="alphavantage",
                source_name="Alpha Vantage",
                fetched_at=datetime.now().isoformat(),
                is_live=False, trust_score=0.0,
                error_message="Alpha Vantage: 不支持的股票代码格式",
            )

        try:
            import urllib.request
            import json as _json

            url = (
                f"{ALPHA_VANTAGE_BASE_URL}"
                f"?function=TIME_SERIES_DAILY"
                f"&symbol={symbol}"
                f"&outputsize={'compact' if count <= 100 else 'full'}"
                f"&apikey={ALPHA_VANTAGE_API_KEY}"
            )

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "QuantAI/1.0")
            resp = await asyncio.to_thread(
                urllib.request.urlopen, req, None, 10
            )
            data = _json.loads(resp.read().decode())

            if "Note" in data:
                raise ValueError("Alpha Vantage rate limit: thank you for using Alpha Vantage")
            if "Error Message" in data:
                raise ValueError(f"Alpha Vantage API error: {data['Error Message']}")

            ts = data.get("Time Series (Daily)", {})
            if not ts:
                raise ValueError(f"No time series data for {symbol}")

            # Convert to list of {date, open, high, low, close, volume}
            rows = []
            for date_str, values in sorted(ts.items()):
                rows.append({
                    "date": date_str,
                    "open": float(values.get("1. open", 0)),
                    "high": float(values.get("2. high", 0)),
                    "low": float(values.get("3. low", 0)),
                    "close": float(values.get("4. close", 0)),
                    "volume": int(values.get("5. volume", 0)),
                    "amount": 0,  # AV doesn't provide amount
                })

            rows = rows[-count:]

            latency = (datetime.now() - t0).total_seconds() * 1000

            source.is_available = True
            source.last_success_at = datetime.now().isoformat()
            source.latency_ms = latency
            source.success_count += 1
            source.consecutive_failures = 0

            return rows, DataProvenance(
                provider="alphavantage",
                source_name="Alpha Vantage (官方K线)",
                fetched_at=datetime.now().isoformat(),
                data_age_seconds=0,
                is_live=True,
                trust_score=0.93,
            )

        except Exception as e:
            source.is_available = False
            source.last_error = str(e)[:200]
            source.consecutive_failures += 1
            return None, DataProvenance(
                provider="alphavantage",
                source_name="Alpha Vantage",
                fetched_at=datetime.now().isoformat(),
                is_live=False,
                trust_score=0.0,
                error_message=f"Alpha Vantage K线获取失败: {str(e)[:100]}",
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
        """Fuse price from multiple sources with disagreement detection."""
        readings = [
            SourceReading(
                source_name="akshare", field_name="price",
                value=akshare_price if akshare_price is not None else 0,
                is_available=akshare_price is not None,
            )
        ]
        result = data_fusion.fuse("price", symbol, readings)
        return result.to_dict()

    # ================================================================
    # Provider Ranking — dynamic failover ordering
    # ================================================================

    def get_provider_ranking(self) -> list[dict]:
        """Auto-rank providers by reliability × latency score. Not hardcoded."""
        ranked = []
        for name, status in self._sources.items():
            if name == "cache":
                continue
            # Composite score: reliability (70%) + latency bonus (30%)
            reliability = status.success_rate if status.total_calls > 0 else 0
            latency_score = max(0, 1.0 - status.latency_ms / 5000) if status.latency_ms > 0 else 0.5
            composite = reliability * 0.7 + latency_score * 0.3

            ranked.append({
                "name": name,
                "rank": 0,  # Will be set after sort
                "reliability": round(reliability, 3),
                "avg_latency_ms": round(status.latency_ms, 1),
                "composite_score": round(composite, 3),
                "total_calls": status.total_calls,
                "consecutive_failures": status.consecutive_failures,
                "status": status.is_available,
                "state": (
                    "untested"
                    if status.total_calls == 0
                    else "up"
                    if status.is_available
                    else "down"
                ),
            })

        ranked.sort(key=lambda p: (
            p["state"] == "untested",
            -p["composite_score"],
            p["consecutive_failures"],
        ))
        for i, r in enumerate(ranked):
            r["rank"] = i + 1
        return ranked

    def get_data_status(self, code: str = "") -> dict:
        """Full data status — transparent to the user.

        Returns everything the user needs to know about data quality:
        source, timestamp, freshness, latency, backup status, provider rankings.
        """
        ranking = self.get_provider_ranking()
        route_code = code.strip().upper() if code else "600000.SH"
        route = self._get_ranked_providers(route_code, "realtime_quote")
        primary_name = route[0] if route else (ranking[0]["name"] if ranking else "")
        primary = next(
            (provider for provider in ranking if provider["name"] == primary_name),
            ranking[0] if ranking else None,
        )
        backups_available = [
            provider for provider in ranking
            if provider["name"] != primary_name and provider["status"]
        ]
        tested = [p for p in ranking if p["state"] != "untested"]
        pipeline_status = (
            "live"
            if primary and primary["state"] == "up"
            else "degraded"
            if backups_available
            else "unknown"
            if not tested
            else "down"
        )

        # Freshness check
        spot_age = self.cache.get_age(f"spot:quote:{code}") if code else None
        freshness_level = (
            "unknown"
            if spot_age is None or spot_age >= 999999
            else "fresh"
            if spot_age < 5
            else "recent"
            if spot_age < 60
            else "stale"
            if spot_age < 300
            else "expired"
        )
        freshness_color = (
            "#6B7280"
            if freshness_level == "unknown"
            else "#22C55E"
            if freshness_level in ("fresh", "recent")
            else "#F59E0B"
            if freshness_level == "stale"
            else "#EF4444"
        )

        return {
            "primary_provider": primary["name"] if primary else "unknown",
            "primary_display": self._provider_display_name(primary["name"] if primary else ""),
            "status": pipeline_status,
            "status_icon": (
                "🟢"
                if pipeline_status == "live"
                else "🟡"
                if pipeline_status == "degraded"
                else "⚪"
                if pipeline_status == "unknown"
                else "🔴"
            ),
            "data_age_seconds": round(spot_age, 1) if spot_age is not None and spot_age < 999999 else None,
            "freshness": freshness_level,
            "freshness_color": freshness_color,
            "latency_ms": primary["avg_latency_ms"] if primary else 0,
            "provider_ranking": ranking,
            "backups_available": [p["name"] for p in backups_available],
            "backups_available_count": len(backups_available),
            "cache_entries": len(self.cache._store),
            "recent_reliability": {
                p["name"]: f"{p['reliability']:.1%}" for p in ranking[:5]
            },
            "recommendation": (
                "Data pipeline healthy, multiple sources available"
                if primary and primary["status"] and backups_available
                else "Single source only — consider adding backup providers"
                if primary and primary["status"]
                else "Providers not tested yet — request a quote to run a live check"
                if not tested
                else "No live data available — AI analysis paused"
            ),
        }

    @staticmethod
    def _provider_display_name(name: str) -> str:
        names = {
            "ifind": "同花顺 iFind (QuantAPI)",
            "mootdx": "通达信 (mootdx TCP)",
            "tushare": "Tushare Pro",
            "akshare": "东方财富 (AkShare)",
            "finnhub": "Finnhub (官方API)",
            "fmp": "FMP (财报+估值)",
            "twelvedata": "Twelve Data (官方API)",
            "polygon": "Polygon.io (专业级)",
            "alphavantage": "Alpha Vantage (官方API)",
            "tushare": "Tushare Pro",
            "baostock": "BaoStock",
            "sina": "新浪财经",
            "tencent": "腾讯财经",
        }
        return names.get(name, name)


# Singleton
source_manager = SourceManager()
