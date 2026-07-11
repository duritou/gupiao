"""iFind (同花顺) QuantAPI Provider — Production-grade A-share data.

Architecture:
  iFind QuantAPI is NOT a REST API. It uses Super Command to generate
  HTTP requests per data function. Each function has a unique generated URL.

  IFindTransport: auth + HTTP dispatch by function name
  FunctionRegistry: maps data types → generated HTTP request templates
  IFindProvider: normalized data access (AI never sees raw iFind format)

Usage:
  provider = IFindProvider()
  quote = provider.get_quote("000725.SZ")  → IFindQuote
  klines = provider.get_kline("000725.SZ", count=250) → list[dict]

To add a new endpoint:
  1. Generate HTTP request in Super Command
  2. Add entry to FUNCTION_TEMPLATES below
  3. Add normalization method if needed
"""

from __future__ import annotations

import os
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

# ================================================================
# Credentials
# ================================================================

# 凭据从环境变量读取(见 .env / .env.example),禁止硬编码入库
# 若安装了 python-dotenv 则加载 .env,否则依赖运行环境已注入的变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

IFIND_REFRESH_TOKEN = os.getenv("IFIND_REFRESH_TOKEN", "")
IFIND_ACCESS_KEY = os.getenv("IFIND_ACCESS_KEY", "")

# ================================================================
# FunctionSpec — describes a provider function completely
# ================================================================
# Provider-agnostic: iFind, Wind, Tushare all use the same spec format.
# Add a new provider: drop a FunctionSpec, AI never changes.

@dataclass
class FunctionSpec:
    """Complete description of a data provider function.

    Tells the Transport HOW to call and HOW to normalize the response.
    Provider-independent — iFind, Wind, MootDX all use this.
    """
    id: str = ""                         # "quote", "kline", "financial"
    capability: str = ""                 # "realtime_quote", "daily_kline", "financial"
    market: str = "CN"                   # "CN", "US", "HK"
    asset: str = "stock"                 # "stock", "index", "etf", "bond"

    # HTTP
    url: str = ""                        # Full URL from Super Command
    method: str = "POST"
    headers: dict = None                 # Extra headers beyond auth
    body_template: dict = None           # {key} placeholders filled from params

    # Response
    response_path: str = ""              # JSON path to data: "data.list" → resp["data"]["list"]

    # Field mapping: standard_name → provider_field_name
    # "price" → "lastPrice", "open" → "openPrice", etc.
    field_mapping: dict = None

    # Quality
    cache_ttl: int = 30                  # seconds
    rate_limit: float = 0                # minimum seconds between calls
    retry: int = 2
    timeout: int = 30

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}
        if self.body_template is None:
            self.body_template = {}
        if self.field_mapping is None:
            self.field_mapping = {}

    def build_body(self, params: dict) -> dict:
        """Fill {key} placeholders in body_template with param values."""
        import json as _json
        body_str = _json.dumps(self.body_template)
        for k, v in params.items():
            body_str = body_str.replace(f"{{{k}}}", str(v))
        return _json.loads(body_str)

    def extract_data(self, response: dict):
        """Walk response_path to extract the data payload."""
        data = response
        if self.response_path:
            for key in self.response_path.split("."):
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return None
        return data

    def map_item(self, item: dict) -> dict:
        """Apply field_mapping to normalize one data item.

        iFind: {"lastPrice": 4.27} → standard: {"price": 4.27}
        MootDX: {"price": 4.27} → standard: {"price": 4.27} (identity)
        """
        if not self.field_mapping:
            return dict(item)
        result = {}
        for std_name, src_name in self.field_mapping.items():
            result[std_name] = item.get(src_name, 0)
        return result


# ================================================================
# Function Registry — all registered provider functions
# ================================================================
# Populated via register() from Super Command generated specs.
# Used by IFindTransport.call() to look up how to call a function.

_FUNCTION_REGISTRY: dict[str, FunctionSpec] = {}
# TO BE FILLED from Super Command — see FunctionSpec docstring


# ================================================================
# Token Manager
# ================================================================

class TokenManager:
    """Manages iFind access token lifecycle: refresh → access → auto-refresh.

    Thread-safe. All API calls share the same token.
    On 401: auto-refreshes and retries once.
    """

    def __init__(self):
        self._access_token: str = IFIND_ACCESS_KEY
        self._expires_at: float = _time.time() + 7200
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "QuantAI-Research/1.0",
        })

    def get_token(self) -> str:
        """Get valid access token. Auto-refreshes when < 5min remaining."""
        with self._lock:
            if _time.time() > self._expires_at - 300:
                self._refresh()
            return self._access_token

    def _refresh(self):
        """Refresh access token using refresh token.

        FILL IN after Super Command generates the token refresh endpoint.
        """
        pass  # Will be implemented when real endpoint is known

    def call(
        self,
        url: str,
        method: str = "POST",
        body: dict = None,
        headers_extra: dict = None,
        timeout: int = 30,
    ) -> tuple[int, dict | None]:
        """Make authenticated HTTP call. Returns (status_code, data_or_None)."""
        token = self.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        if headers_extra:
            headers.update(headers_extra)

        try:
            if method == "POST":
                resp = self._session.post(
                    url, json=body or {}, headers=headers, timeout=timeout,
                )
            else:
                resp = self._session.get(
                    url, params=body or {}, headers=headers, timeout=timeout,
                )

            if resp.status_code == 200:
                try:
                    return (200, resp.json())
                except Exception:
                    return (200, {"_raw": resp.text})

            if resp.status_code == 401:
                # Token expired — refresh and retry once
                with self._lock:
                    self._refresh()
                headers["Authorization"] = f"Bearer {self._access_token}"
                retry = self._session.post(
                    url, json=body or {}, headers=headers, timeout=timeout,
                )
                if retry.status_code == 200:
                    try:
                        return (200, retry.json())
                    except Exception:
                        return (200, {"_raw": retry.text})

            return (resp.status_code, None)

        except requests.Timeout:
            return (0, None)
        except Exception:
            return (0, None)


# ================================================================
# IFind Transport — function name → HTTP request → normalized data
# ================================================================

class IFindTransport:
    """Maps function names to HTTP requests via FunctionSpec.

    The ONLY place that knows about iFind's HTTP format.
    When iFind changes: update FunctionSpec, nothing else.
    """

    def __init__(self, token_mgr: TokenManager = None):
        self._token = token_mgr or TokenManager()

    def call(
        self, function_id: str, params: dict = None, timeout: int = 30,
    ) -> tuple[int, dict | None]:
        """Call a named iFind function via its FunctionSpec.

        1. Look up FunctionSpec by id
        2. Build HTTP request from spec
        3. Call API via TokenManager
        4. Extract data via response_path
        5. Map fields via field_mapping
        6. Return normalized data

        Returns (status_code, normalized_data_or_None).
        """
        spec = _FUNCTION_REGISTRY.get(function_id)
        if spec is None:
            return (0, None)

        body = spec.build_body(params or {})
        timeout_val = spec.timeout or timeout

        status, data = self._token.call(
            spec.url, spec.method, body, spec.headers, timeout_val,
        )

        if status != 200 or data is None:
            return (status, None)

        # Extract data payload
        data = spec.extract_data(data)
        if data is None:
            return (200, None)

        # Map fields if items is a list
        if isinstance(data, list):
            data = [spec.map_item(item) for item in data]
        elif isinstance(data, dict):
            data = spec.map_item(data)

        return (200, data)

    def register(self, spec: FunctionSpec):
        """Register a FunctionSpec (from Super Command or config)."""
        _FUNCTION_REGISTRY[spec.id] = spec

    def list_registered(self) -> list[str]:
        """List all registered function IDs."""
        return list(_FUNCTION_REGISTRY.keys())


# ================================================================
# iFind Provider — clean data access for AI
# ================================================================

@dataclass
class IFindQuote:
    """Normalized quote — AI only sees this, never raw iFind JSON."""
    code: str = ""
    name: str = ""
    price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    turnover: float = 0.0
    pe: float = 0.0
    pb: float = 0.0
    total_market_cap: float = 0.0


class IFindProvider:
    """Clean data access layer. AI code calls this, never the Transport directly.

    Each method:
      1. Calls transport.call("function_name", params)
      2. Normalizes the raw iFind response into standard types
      3. Returns typed objects (never raw dicts from iFind)
    """

    def __init__(self, transport: IFindTransport = None):
        self._t = transport or IFindTransport()

    # ================================================================
    # Quote
    # ================================================================

    def get_quote(self, code: str) -> IFindQuote | None:
        """Get real-time quote. Transport normalizes fields via FunctionSpec.mapping."""
        status, data = self._t.call("quote", {"code": code}, timeout=10)
        if status != 200 or data is None:
            return None

        # Transport already applied field_mapping → standard field names
        item = data[0] if isinstance(data, list) else data

        return IFindQuote(
            code=code,
            name=str(item.get("name", "")),
            price=float(item.get("price", 0)),
            open=float(item.get("open", 0)),
            high=float(item.get("high", 0)),
            low=float(item.get("low", 0)),
            pre_close=float(item.get("pre_close", 0)),
            change_pct=float(item.get("change_pct", 0)),
            volume=float(item.get("volume", 0)),
            amount=float(item.get("amount", 0)),
            turnover=float(item.get("turnover", 0)),
            pe=float(item.get("pe", 0)),
            pb=float(item.get("pb", 0)),
            total_market_cap=float(item.get("total_market_cap", 0)),
        )

    # ================================================================
    # K-line
    # ================================================================

    def get_kline(
        self, code: str, period: str = "day", count: int = 250,
    ) -> list[dict] | None:
        """Get K-line data. Transport normalizes fields via FunctionSpec.mapping."""
        status, data = self._t.call(
            "kline",
            {"code": code, "period": period, "count": str(count)},
            timeout=30,
        )
        if status != 200 or data is None:
            return None
        # Transport already normalized via field_mapping
        return data if isinstance(data, list) else None

    # ================================================================
    # Financial / News — registered when Super Command templates added
    # ================================================================

    def get_financial(self, code: str) -> dict | None:
        """Get financial indicators. Maps to 'financial' function template."""
        status, data = self._t.call("financial", {"code": code}, timeout=10)
        if status != 200 or data is None:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data

    def get_news(self, code: str, limit: int = 20) -> list[dict] | None:
        """Get stock news. Maps to 'news' function template."""
        status, data = self._t.call(
            "news", {"code": code, "limit": str(limit)}, timeout=10,
        )
        if status != 200 or data is None:
            return None
        rows = data if isinstance(data, list) else data.get("list", [])
        if not rows:
            return None
        return [
            {
                "title": str(r.get("title", "")),
                "content": str(r.get("content", r.get("summary", ""))),
                "time": str(r.get("time", r.get("pub_time", ""))),
                "source": str(r.get("source", "")),
            }
            for r in rows[:limit]
        ]

    def register_function(self, spec: FunctionSpec):
        """Register a FunctionSpec (from Super Command or YAML config)."""
        self._t.register(spec)


# Singleton
ifind = IFindProvider()
