"""Real Data Provider 鈥?v7.5 Data Migration Phase.

The single source of truth for ALL real market data in the system.
Every route that needs stock data goes through here. Never synthetic data.

Provides:
  1. Stock universe (A-share list with basic info)
  2. Daily bars (OHLCV from baostock, cached)
  3. Batch quotes (latest close for multiple stocks)
  4. Computed signals (MACD/RSI/KDJ/MA/Volume from real K-lines)

Design principles:
  - T-1 data is acceptable. This is a research system, not HFT.
  - Every data point carries provenance (source, timestamp).
  - Cache aggressively 鈥?baostock is slow for batch operations.
  - If data is unavailable, say so. Never fabricate.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class RealStockInfo:
    """Basic stock information from real data."""
    code: str = ""
    name: str = ""
    latest_close: float = 0.0
    change_pct: float = 0.0     # vs previous close
    volume: int = 0
    pe: float = 0.0
    data_date: str = ""          # The date this data is from
    data_source: str = ""        # "baostock" / "akshare" / etc.


@dataclass
class RealSignalResult:
    """Computed signals from real K-line data."""
    stock_code: str = ""
    stock_name: str = ""
    # Individual signals (0-100 normalized)
    macd_score: float = 50.0
    rsi_score: float = 50.0
    kdj_score: float = 50.0
    ma_score: float = 50.0
    volume_score: float = 50.0
    # Fusion
    fusion_score: float = 50.0
    direction: str = "neutral"   # buy / sell / neutral
    confidence: float = 0.0
    # Metadata
    data_days: int = 0           # How many days of K-line used
    data_source: str = ""
    computed_at: str = ""


class RealDataProvider:
    """Unified real data access layer. All routes use this, not synthetic data."""

    def __init__(self):
        self._universe_cache: list[dict] | None = None
        self._universe_cache_time: datetime | None = None
        self._universe_cache_min_count = 0
        self._kline_cache: dict[str, tuple[list[dict], datetime]] = {}

    # ================================================================
    # Stock Universe
    # ================================================================

    async def get_stock_universe(self, min_count: int = 50) -> list[dict]:
        """Get tradeable A-share stocks from real data sources only."""
        if (self._universe_cache is not None
                and self._universe_cache_time is not None
                and self._universe_cache_min_count >= min_count
                and (datetime.now() - self._universe_cache_time).seconds < 3600):
            return self._universe_cache

        # 同步进行中时跳过 baostock(避免与 sync 长 session 互踢),返回已有缓存
        from src.infrastructure.market_data.baostock_lock import is_sync_in_progress
        if is_sync_in_progress():
            return self._universe_cache or []

        universe: list[dict] = []
        try:
            import baostock as bs
            from datetime import date as dt_date

            lg = await asyncio.to_thread(bs.login)
            if lg.error_code != '0':
                raise RuntimeError(f"baostock login failed: {lg.error_msg}")

            try:
                query_date = dt_date.today().strftime("%Y-%m-%d")
                rs = await asyncio.to_thread(bs.query_all_stock, day=query_date)
                while rs.error_code == '0' and rs.next():
                    item = dict(zip(rs.fields, rs.get_row_data()))
                    raw_code = item.get("code", "")
                    if not raw_code.startswith(("sh.", "sz.")):
                        continue
                    if item.get("tradeStatus") not in ("", "1"):
                        continue
                    normalized = f"{raw_code[3:]}.{'SH' if raw_code.startswith('sh.') else 'SZ'}"
                    universe.append({"code": normalized, "name": item.get("code_name", normalized)})
                    if len(universe) >= min_count:
                        break
            finally:
                await asyncio.to_thread(bs.logout)
        except Exception:
            universe = []

        self._universe_cache = universe
        self._universe_cache_time = datetime.now()
        self._universe_cache_min_count = min_count
        return universe

    def _get_default_universe(self) -> list[dict]:
        """No static fallback universe. Return empty when real sources are unavailable."""
        return []
    # ================================================================
    # K-line Data
    # ================================================================

    async def get_daily_bars(
        self, code: str, days: int = 250
    ) -> list[dict] | None:
        """Get daily OHLCV bars 鈥?local DB first, API as fallback."""
        # 1. Try local DB (instant) — 含新鲜度校验
        local = None
        try:
            from src.infrastructure.storage.market_database import market_db
            local = market_db.get_daily_bars(code, limit=days)
            if local and len(local) >= 20:
                # 新鲜度:最新数据在 3 天内才直接用本地(容忍周末/短假),否则走 API fallback
                from datetime import date as dt_date
                try:
                    latest = dt_date.fromisoformat(local[-1]["date"])
                    if (dt_date.today() - latest).days <= 3:
                        return local
                except Exception:
                    return local  # 日期解析失败,保守沿用本地数据
        except Exception:
            pass

        # 2. Cache check
        cache_key = f"{code}:{days}"
        cached = self._kline_cache.get(cache_key)
        if cached:
            data, ts = cached
            if (datetime.now() - ts).seconds < 300:
                return data

        # 3. API fallback
        from src.infrastructure.market_data.source_manager import source_manager
        klines, prov = await source_manager.get_kline(code, count=days)
        if klines:
            self._kline_cache[cache_key] = (klines, datetime.now())
            return klines
        # API 也失败:有本地旧数据(即便过时)总比无数据好
        return local if local else None

    async def get_batch_daily_bars(
        self, codes: list[str], days: int = 250
    ) -> dict[str, list[dict]]:
        """Get daily bars for multiple stocks in parallel."""
        results = {}
        for code in codes:
            bars = await self.get_daily_bars(code, days)
            if bars:
                results[code] = bars
        return results

    # ================================================================
    # Batch Quotes (latest close)
    # ================================================================

    async def get_batch_quotes(
        self, codes: list[str]
    ) -> list[RealStockInfo]:
        """Get latest close prices for a batch of stocks.

        Uses baostock K-line data (latest day's close) since baostock
        doesn't have a real-time quote endpoint.
        """
        results = []
        for code in codes:
            try:
                bars = await self.get_daily_bars(code, days=5)
                if bars and len(bars) >= 2:
                    latest = bars[-1]
                    prev = bars[-2]
                    close = float(latest.get("close", 0))
                    prev_close = float(prev.get("close", close))
                    change_pct = (
                        (close - prev_close) / prev_close * 100
                        if prev_close > 0 else 0
                    )
                    results.append(RealStockInfo(
                        code=code,
                        name="",  # Will be filled from stock info
                        latest_close=close,
                        change_pct=round(change_pct, 2),
                        volume=int(latest.get("volume", 0)),
                        data_date=latest.get("date", ""),
                        data_source="baostock",
                    ))
                else:
                    # Stock exists but no data
                    results.append(RealStockInfo(
                        code=code, data_source="unavailable",
                    ))
            except Exception:
                results.append(RealStockInfo(
                    code=code, data_source="error",
                ))
        return results

    # ================================================================
    # Signal Computation
    # ================================================================

    def compute_signals(
        self,
        code: str,
        name: str,
        klines: list[dict],
    ) -> RealSignalResult:
        """Compute MACD/RSI/KDJ/MA/Volume signals from real K-line data.

        All signals are computed deterministically from OHLCV data.
        No random numbers. No mock data.
        """
        if not klines or len(klines) < 20:
            return RealSignalResult(
                stock_code=code, stock_name=name,
                data_days=len(klines) if klines else 0,
                data_source="insufficient_data",
            )

        closes = [float(k["close"]) for k in klines]
        highs = [float(k["high"]) for k in klines]
        lows = [float(k["low"]) for k in klines]
        volumes = [float(k.get("volume", 0)) for k in klines]

        macd_score = self._compute_macd_signal(closes)
        rsi_score = self._compute_rsi_signal(closes)
        kdj_score = self._compute_kdj_signal(closes, highs, lows)
        ma_score = self._compute_ma_signal(closes)
        volume_score = self._compute_volume_signal(volumes, closes)

        # Fusion: weighted average
        weights = {"macd": 0.30, "rsi": 0.20, "kdj": 0.15, "ma": 0.20, "volume": 0.15}
        fusion = (
            macd_score * weights["macd"]
            + rsi_score * weights["rsi"]
            + kdj_score * weights["kdj"]
            + ma_score * weights["ma"]
            + volume_score * weights["volume"]
        )

        direction = "buy" if fusion >= 65 else "sell" if fusion < 35 else "neutral"
        confidence = min(0.95, abs(fusion - 50) / 50 * 0.8 + 0.3)

        return RealSignalResult(
            stock_code=code, stock_name=name,
            macd_score=round(macd_score, 1),
            rsi_score=round(rsi_score, 1),
            kdj_score=round(kdj_score, 1),
            ma_score=round(ma_score, 1),
            volume_score=round(volume_score, 1),
            fusion_score=round(fusion, 1),
            direction=direction,
            confidence=round(confidence, 3),
            data_days=len(klines),
            data_source="baostock (T-1 daily close)",
            computed_at=datetime.now().isoformat(),
        )

    # ================================================================
    # Individual Signal Calculators
    # ================================================================

    def _compute_macd_signal(self, closes: list[float]) -> float:
        """Compute MACD score from real close prices.

        Uses EMA(12) - EMA(26) for MACD line, EMA(9) for signal line.
        Score 0-100 based on: MACD > signal (bullish), histogram direction,
        and MACD absolute position.
        """
        n = len(closes)
        if n < 26:
            return 50.0

        ema12 = self._ema(closes, 12)
        ema26 = self._ema(closes, 26)
        common_len = min(len(ema12), len(ema26))
        if common_len < 2:
            return 50.0
        # Align: EMA(26) is shorter, take last N of EMA(12)
        e12 = ema12[-common_len:]
        e26 = ema26[-common_len:]
        macd_line = [e12[i] - e26[i] for i in range(common_len)]
        signal_line = self._ema(macd_line, 9)
        if len(signal_line) < 2:
            return 50.0

        # Latest values
        macd_val = macd_line[-1]
        signal_val = signal_line[-1]
        histogram = macd_val - signal_val
        prev_hist = macd_line[-2] - signal_line[-2]

        # Scoring
        score = 50.0

        # MACD above signal = bullish
        if macd_val > signal_val:
            score += 15
        else:
            score -= 15

        # Histogram expanding = strengthening trend
        if abs(histogram) > abs(prev_hist):
            score += 10 if histogram > 0 else -10

        # MACD position relative to zero
        avg_close = sum(closes[-20:]) / 20
        if avg_close > 0:
            macd_pct = abs(macd_val) / (avg_close * 0.02)  # Normalize
            if macd_val > 0:
                score += min(15, macd_pct * 5)
            else:
                score -= min(15, macd_pct * 5)

        return max(0, min(100, score))

    def _compute_rsi_signal(self, closes: list[float]) -> float:
        """Compute RSI(14) score from real close prices.

        RSI < 30 鈫?oversold (bullish for reversal) 鈫?high score
        RSI 40-60 鈫?neutral
        RSI > 70 鈫?overbought (bearish) 鈫?low score
        """
        n = len(closes)
        if n < 15:
            return 50.0

        period = 14
        gains = []
        losses = []
        for i in range(n - period, n):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(diff))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Map RSI to signal score
        # Oversold (< 30) = potential buy 鈫?high score
        # Overbought (> 70) = potential sell 鈫?low score
        if rsi < 30:
            score = 50 + (30 - rsi) * 1.5  # RSI 20 鈫?score 65
        elif rsi < 45:
            score = 50 + (45 - rsi) * 0.5  # Mild oversold
        elif rsi <= 55:
            score = 50  # Neutral
        elif rsi < 70:
            score = 50 - (rsi - 55) * 0.5  # Mild overbought
        else:
            score = 50 - (rsi - 70) * 1.5  # RSI 80 鈫?score 35

        return max(0, min(100, score))

    def _compute_kdj_signal(
        self, closes: list[float], highs: list[float], lows: list[float]
    ) -> float:
        """Compute KDJ score from real OHLC data.

        Uses stochastic oscillator: %K(9,3), %D(3).
        """
        n = len(closes)
        if n < 9:
            return 50.0

        period = 9
        # Latest period
        highest = max(highs[-period:])
        lowest = min(lows[-period:])

        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (closes[-1] - lowest) / (highest - lowest) * 100

        # Simplified: K 鈮?RSV smoothed, D 鈮?K smoothed
        # For scoring, use the raw RSV
        # High KDJ (> 80) = overbought 鈫?low score
        # Low KDJ (< 20) = oversold 鈫?high score
        if rsv < 20:
            score = 50 + (20 - rsv) * 1.5
        elif rsv < 50:
            score = 50 + (50 - rsv) * 0.3
        elif rsv <= 60:
            score = 50
        elif rsv < 80:
            score = 50 - (rsv - 60) * 0.3
        else:
            score = 50 - (rsv - 80) * 1.5

        return max(0, min(100, score))

    def _compute_ma_signal(self, closes: list[float]) -> float:
        """Compute MA score from real close prices.

        Checks: MA5 > MA10 > MA20 (bullish alignment).
        """
        n = len(closes)
        if n < 20:
            return 50.0

        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        price = closes[-1]

        score = 50.0

        # Price above MA = bullish
        if price > ma5:
            score += 10
        else:
            score -= 10

        # MA alignment
        if ma5 > ma10 > ma20:
            score += 20  # Perfect bullish alignment
        elif ma5 > ma10:
            score += 10
        elif ma5 < ma10 < ma20:
            score -= 15  # Bearish alignment

        # Distance from MA20
        if ma20 > 0:
            pct_from_ma20 = (price - ma20) / ma20 * 100
            if -5 < pct_from_ma20 < 5:
                score += 5  # Near MA = potential support

        return max(0, min(100, score))

    def _compute_volume_signal(
        self, volumes: list[float], closes: list[float]
    ) -> float:
        """Compute volume signal from real volume data.

        Checks if recent volume is expanding (bullish) or contracting.
        """
        n = len(volumes)
        if n < 20:
            return 50.0

        vol_ma5 = sum(volumes[-5:]) / 5
        vol_ma20 = sum(volumes[-20:]) / 20

        score = 50.0

        if vol_ma20 > 0:
            vol_ratio = vol_ma5 / vol_ma20

            if vol_ratio > 1.5:
                # High volume 鈥?check price direction
                if closes[-1] > closes[-5]:
                    score += 20  # Volume confirms uptrend
                else:
                    score -= 10  # High volume selling
            elif vol_ratio > 1.2:
                if closes[-1] > closes[-5]:
                    score += 10
            elif vol_ratio < 0.7:
                score -= 5  # Volume drying up

        return max(0, min(100, score))

    # ================================================================
    # Utilities
    # ================================================================

    @staticmethod
    def _ema(data: list[float], period: int) -> list[float]:
        """Compute Exponential Moving Average."""
        if len(data) < period:
            return []
        multiplier = 2.0 / (period + 1.0)
        result = [sum(data[:period]) / period]  # Start with SMA
        for i in range(period, len(data)):
            result.append(
                (data[i] - result[-1]) * multiplier + result[-1]
            )
        return result


# Singleton
real_data = RealDataProvider()

