"""Live Market Data Service — Real data via akshare.

Provides real market data with automatic mock fallback.
Chart Runtime's DataFeed abstraction means none of this
complexity leaks into the frontend.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime
from functools import lru_cache

from loguru import logger

from src.infrastructure.market_data.validator import validator as data_validator
from src.infrastructure.market_data.trust import trust_engine as data_trust_engine


class LiveMarketService:
    """Real-time market data service. Uses akshare for A-share data.

    All methods are async. Internal akshare calls run in thread pool
    since akshare is synchronous.
    """

    def __init__(self):
        self._spot_cache: dict | None = None
        self._spot_cache_time: datetime | None = None
        self._cache_ttl = 30  # seconds

    # ============================================================
    # Stock Quotes
    # ============================================================

    async def get_realtime_quote(self, code: str) -> dict | None:
        """Get real-time quote for a single stock."""
        try:
            spot = await self._get_spot_data()
            if spot is None:
                return None
            # akshare uses 6-digit codes without suffix
            raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            row = spot[spot["代码"] == raw_code]
            if row.empty:
                return None
            r = row.iloc[0]
            raw_quote = {
                "stock_code": code,
                "stock_name": str(r.get("名称", "")),
                "price": float(r.get("最新价", 0)),
                "change_pct": float(r.get("涨跌幅", 0)),
                "change_amount": float(r.get("涨跌额", 0)),
                "volume": float(r.get("成交量", 0)),
                "amount": float(r.get("成交额", 0)),
                "high": float(r.get("最高", 0)),
                "low": float(r.get("最低", 0)),
                "open": float(r.get("今开", 0)),
                "pre_close": float(r.get("昨收", 0)),
                "turnover": float(r.get("换手率", 0)),
                "pe": float(r.get("市盈率-动态", 0) if "市盈率-动态" in r else 0),
                "pb": float(r.get("市净率", 0) if "市净率" in r else 0),
                "total_market_cap": float(r.get("总市值", 0)),
                "circ_market_cap": float(r.get("流通市值", 0)),
            }

            # Validate + normalize
            validation = data_validator.validate_quote(raw_quote, code)
            if validation.has_errors:
                logger.warning(f"Data validation errors for {code}: {validation.errors}")
            if validation.has_warnings:
                logger.debug(f"Data validation warnings for {code}: {validation.warnings}")

            # Merge normalized fields
            result = {**raw_quote, **validation.normalized_data}
            result["_quality_score"] = validation.quality_score
            result["_quality_warnings"] = validation.warnings

            # Compute Data Trust Score (v7.3)
            data_trust_engine.mark_data_updated(f"quote:{code}", datetime.now())
            trust = data_trust_engine.compute_trust_score(
                data_key=f"quote:{code}",
                validation_score=validation.quality_score,
                provider_name="akshare",
                max_age=60,
            )
            result["_trust_score"] = trust.to_dict()
            return result
        except Exception as e:
            logger.debug(f"Live quote failed for {code}: {e}")
            return None

    async def get_batch_quotes(self, codes: list[str]) -> list[dict]:
        """Get quotes for multiple stocks."""
        results = []
        for code in codes:
            q = await self.get_realtime_quote(code)
            if q:
                results.append(q)
        return results

    # ============================================================
    # K-Line (Historical)
    # ============================================================

    async def get_kline(
        self, code: str, period: str = "daily", count: int = 250
    ) -> list[dict]:
        """Get historical K-line data.

        Args:
            code: Stock code like '000001.SZ'
            period: 'daily', 'weekly', 'monthly'
            count: Number of bars to return
        """
        try:
            import akshare as ak

            raw_code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            symbol = raw_code

            period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
            ak_period = period_map.get(period, "daily")

            df = await asyncio.to_thread(
                ak.stock_zh_a_hist,
                symbol=symbol,
                period=ak_period,
                start_date="20200101",
                end_date=date.today().strftime("%Y%m%d"),
                adjust="qfq",
            )

            if df is None or df.empty:
                return []

            result = []
            for _, row in df.tail(count).iterrows():
                result.append({
                    "date": str(row.get("日期", "")),
                    "open": float(row.get("开盘", 0)),
                    "high": float(row.get("最高", 0)),
                    "low": float(row.get("最低", 0)),
                    "close": float(row.get("收盘", 0)),
                    "volume": float(row.get("成交量", 0)),
                    "amount": float(row.get("成交额", 0)),
                    "change_pct": float(row.get("涨跌幅", 0)) if "涨跌幅" in row else 0,
                    "turnover": float(row.get("换手率", 0)) if "换手率" in row else 0,
                })

            return result
        except Exception as e:
            logger.warning(f"Live kline failed for {code}: {e}")
            return []

    # ============================================================
    # Market Overview (Indices)
    # ============================================================

    async def get_index_quotes(self) -> list[dict]:
        """Get major index quotes."""
        try:
            import akshare as ak

            df = await asyncio.to_thread(ak.stock_zh_index_spot_em)
            if df is None or df.empty:
                return []

            major_indices = ["上证指数", "深证成指", "创业板指", "科创50"]
            result = []
            for _, row in df.iterrows():
                name = str(row.get("名称", ""))
                if name in major_indices:
                    result.append({
                        "name": name,
                        "code": str(row.get("代码", "")),
                        "value": float(row.get("最新价", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "change_amount": float(row.get("涨跌额", 0)),
                        "volume": float(row.get("成交量", 0)),
                        "amount": float(row.get("成交额", 0)),
                    })
            return result
        except Exception as e:
            logger.warning(f"Live index failed: {e}")
            return []

    async def get_market_breadth(self) -> dict | None:
        """Get up/down counts."""
        try:
            spot = await self._get_spot_data()
            if spot is None:
                return None
            up = int((spot["涨跌幅"] > 0).sum())
            down = int((spot["涨跌幅"] < 0).sum())
            flat = int((spot["涨跌幅"] == 0).sum())
            limit_up = int((spot["涨跌幅"] >= 9.9).sum())
            limit_down = int((spot["涨跌幅"] <= -9.9).sum())

            total_volume = spot["成交额"].sum() / 1e12  # 万亿

            return {
                "up": up,
                "down": down,
                "flat": flat,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "total_volume": round(total_volume, 2),
            }
        except Exception as e:
            logger.warning(f"Live breadth failed: {e}")
            return None

    # ============================================================
    # Sector Data
    # ============================================================

    async def get_sectors(self) -> list[dict]:
        """Get sector/concept board performance."""
        try:
            import akshare as ak

            df = await asyncio.to_thread(ak.stock_board_concept_name_em)
            if df is None or df.empty:
                return []

            result = []
            for _, row in df.head(30).iterrows():
                score = max(10, min(99, 50 + float(row.get("涨跌幅", 0)) * 10))
                stars = 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 45 else 2 if score >= 25 else 1
                status = "强势" if score >= 70 else "震荡" if score >= 40 else "弱势"

                result.append({
                    "name": str(row.get("板块名称", "")),
                    "score": score,
                    "change_pct": float(row.get("涨跌幅", 0)),
                    "stars": stars,
                    "status": status,
                })

            result.sort(key=lambda s: s["score"], reverse=True)
            return result[:12]
        except Exception as e:
            logger.warning(f"Live sectors failed: {e}")
            return []

    # ============================================================
    # Internal Cache
    # ============================================================

    async def _get_spot_data(self):
        """Get full A-share spot data with caching."""
        now = datetime.now()
        if (
            self._spot_cache is not None
            and self._spot_cache_time is not None
            and (now - self._spot_cache_time).seconds < self._cache_ttl
        ):
            return self._spot_cache

        try:
            import akshare as ak

            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            self._spot_cache = df
            self._spot_cache_time = now
            return df
        except Exception as e:
            logger.warning(f"Live spot data failed: {e}")
            return self._spot_cache  # Return stale cache if available


# ============================================================
# Singleton
# ============================================================

live_service = LiveMarketService()
