"""Data Fusion Layer — v7.4. Multi-source aggregation with disagreement detection.

When two sources disagree → lower confidence. When three agree → boost it.
This is the difference between "data is available" and "data is trustworthy."

Architecture:
  AkShare ──┐
  Tushare ──┤
  BaoStock ─┤
             ├── DataFusion ──→ FusedResult { value, confidence, sources_agree }
  Cache ─────┤

A fused result tells the AI: "price is ¥4.27, 3 sources agree, confidence 99%"
or "price is ¥138.37, only 1 source, other 2 disagree — DO NOT USE."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ================================================================
# Feed Architecture — structured data feeds for AI
# ================================================================

@dataclass
class DataFeed:
    """Defines a structured data feed consumed by the AI pipeline."""
    name: str = ""
    category: str = ""           # market / fundamental / money_flow / news / knowledge / macro
    frequency: str = ""          # realtime / daily / weekly / monthly / on_demand
    primary_source: str = "akshare"
    backup_sources: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    cache_ttl_seconds: int = 60


# Standard feed definitions (config, not code)
STANDARD_FEEDS = {
    "market_daily": DataFeed(
        name="日K行情", category="market", frequency="daily",
        primary_source="akshare", backup_sources=["tushare", "baostock"],
        fields=["date", "open", "high", "low", "close", "volume", "amount"],
        cache_ttl_seconds=300,
    ),
    "market_spot": DataFeed(
        name="实时行情", category="market", frequency="realtime",
        primary_source="akshare", backup_sources=["tushare"],
        fields=["price", "change_pct", "volume", "amount", "high", "low", "open", "pre_close"],
        cache_ttl_seconds=30,
    ),
    "market_index": DataFeed(
        name="指数行情", category="market", frequency="realtime",
        primary_source="akshare", backup_sources=["tushare"],
        fields=["name", "value", "change_pct"],
        cache_ttl_seconds=30,
    ),
    "fundamental": DataFeed(
        name="基本面数据", category="fundamental", frequency="daily",
        primary_source="akshare", backup_sources=["tushare"],
        fields=["pe", "pb", "roe", "net_profit", "revenue", "total_market_cap"],
        cache_ttl_seconds=3600,
    ),
    "money_flow": DataFeed(
        name="资金流向", category="money_flow", frequency="daily",
        primary_source="akshare", backup_sources=["tushare"],
        fields=["northbound_flow", "main_force_flow", "lhb"],
        cache_ttl_seconds=300,
    ),
    "news": DataFeed(
        name="新闻资讯", category="news", frequency="on_demand",
        primary_source="akshare", backup_sources=[],
        fields=["title", "content", "source", "timestamp"],
        cache_ttl_seconds=1800,
    ),
    "knowledge_industry": DataFeed(
        name="行业知识", category="knowledge", frequency="on_demand",
        primary_source="akshare", backup_sources=[],
        fields=["sector_name", "change_pct", "leading_stocks"],
        cache_ttl_seconds=600,
    ),
    "macro": DataFeed(
        name="宏观经济", category="macro", frequency="monthly",
        primary_source="akshare", backup_sources=[],
        fields=["cpi", "pmi", "interest_rate", "exchange_rate"],
        cache_ttl_seconds=86400,
    ),
}


# ================================================================
# Data Fusion — multi-source → one truth
# ================================================================

@dataclass
class SourceReading:
    """A single reading from one data source."""
    source_name: str = ""        # "akshare", "tushare"
    field_name: str = ""         # "price", "close"
    value: float = 0.0
    fetched_at: str = ""
    is_available: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source_name,
            "field": self.field_name,
            "value": self.value,
            "available": self.is_available,
        }


@dataclass
class FusedResult:
    """Result of fusing multiple source readings into one trusted value."""
    field_name: str = ""
    symbol: str = ""

    # The fused value
    value: float = 0.0
    confidence: float = 0.0       # 0-1 based on source agreement
    sources_checked: int = 0
    sources_agreed: int = 0
    sources_available: int = 0

    # Individual readings
    readings: list[SourceReading] = field(default_factory=list)

    # Disagreement analysis
    has_disagreement: bool = False
    max_deviation_pct: float = 0.0
    outlier_source: str = ""
    consensus_value: float = 0.0

    # Recommendation
    recommendation: str = ""

    @property
    def is_trustworthy(self) -> bool:
        return self.confidence >= 0.7 and self.sources_agreed >= 1

    @property
    def trust_level(self) -> str:
        if self.confidence >= 0.9:
            return "high"
        elif self.confidence >= 0.7:
            return "medium"
        elif self.confidence >= 0.4:
            return "low"
        return "untrustworthy"

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "symbol": self.symbol,
            "value": round(self.value, 4) if isinstance(self.value, float) else self.value,
            "confidence": round(self.confidence, 3),
            "sources_checked": self.sources_checked,
            "sources_agreed": self.sources_agreed,
            "sources_available": self.sources_available,
            "has_disagreement": self.has_disagreement,
            "max_deviation_pct": round(self.max_deviation_pct, 2),
            "outlier_source": self.outlier_source,
            "consensus_value": round(self.consensus_value, 4),
            "trust_level": self.trust_level,
            "recommendation": self.recommendation,
            "readings": [r.to_dict() for r in self.readings],
        }


class DataFusion:
    """Fuses readings from multiple data sources into one trusted value.

    Rules:
      - 1 source available → confidence = 0.7 (single source, unverified)
      - 2 sources agree (< 5% deviation) → confidence = 0.9
      - 3+ sources agree → confidence = 0.95+
      - Sources disagree (> 5% deviation) → flag outlier, reduce confidence by 0.3
      - Source disagrees by > 20% → outlier rejected, confidence from remaining
    """

    AGREEMENT_THRESHOLD_PCT = 5.0    # Within 5% = agree
    REJECTION_THRESHOLD_PCT = 20.0   # Beyond 20% = reject outlier

    def fuse(self, field_name: str, symbol: str,
             readings: list[SourceReading]) -> FusedResult:
        """Fuse multiple source readings into one trusted value."""
        available = [r for r in readings if r.is_available]

        if not available:
            return FusedResult(
                field_name=field_name, symbol=symbol,
                value=0, confidence=0.0,
                sources_checked=len(readings), sources_available=0,
                readings=readings,
                recommendation="No data available from any source. AI analysis paused.",
            )

        values = [r.value for r in available]
        sources = [r.source_name for r in available]

        # Single source
        if len(available) == 1:
            return FusedResult(
                field_name=field_name, symbol=symbol,
                value=values[0], confidence=0.7,
                sources_checked=len(readings), sources_available=1,
                sources_agreed=1, readings=readings,
                consensus_value=values[0],
                recommendation="Single source only — unverified. Consider adding backup providers for cross-checking.",
            )

        # Multiple sources — compute agreement
        avg = sum(values) / len(values)
        deviations = {}
        max_dev = 0.0
        outlier = ""

        for r in available:
            dev = abs(r.value / avg - 1) * 100 if avg > 0 else 0
            deviations[r.source_name] = dev
            if dev > max_dev:
                max_dev = dev
                outlier = r.source_name

        # Count agreeing sources (within threshold)
        agreeing = [r for r in available
                    if abs(r.value / avg - 1) * 100 <= self.AGREEMENT_THRESHOLD_PCT]

        has_disagreement = max_dev > self.AGREEMENT_THRESHOLD_PCT

        # Compute fused value
        if has_disagreement and max_dev > self.REJECTION_THRESHOLD_PCT:
            # Reject the outlier, use consensus of remaining
            inliers = [r for r in available
                      if abs(r.value / avg - 1) * 100 <= self.REJECTION_THRESHOLD_PCT]
            if inliers:
                fused_value = sum(r.value for r in inliers) / len(inliers)
            else:
                fused_value = avg  # Can't reject, use average with low confidence
        else:
            # Use weighted average (closer to consensus = higher weight)
            weights = []
            for r in available:
                dev = abs(r.value / avg - 1) * 100 if avg > 0 else 0
                weights.append(max(0.1, 1.0 - dev / self.REJECTION_THRESHOLD_PCT))
            total_w = sum(weights)
            fused_value = sum(r.value * w for r, w in zip(available, weights)) / total_w if total_w > 0 else avg

        # Confidence calculation
        agree_count = len(agreeing)
        if agree_count >= 3:
            base_confidence = 0.97
        elif agree_count >= 2:
            base_confidence = 0.90
        else:
            base_confidence = 0.65

        # Penalize disagreement
        if has_disagreement:
            penalty = min(0.4, max_dev / 50)  # Max 40% penalty at 20%+ deviation
            confidence = max(0.1, base_confidence - penalty)
        else:
            confidence = base_confidence

        # Recommendation
        if confidence >= 0.9:
            rec = "Data trustworthy. Multiple sources confirm."
        elif confidence >= 0.7:
            rec = "Data acceptable. Minor source disagreement."
        elif has_disagreement:
            rec = f"Source '{outlier}' disagrees by {max_dev:.1f}%. "
            if max_dev > self.REJECTION_THRESHOLD_PCT:
                rec += f"Recommend rejecting '{outlier}' and using consensus."
            else:
                rec += "Recommend verifying manually before making decisions."
        else:
            rec = "Data quality too low for reliable AI analysis."

        return FusedResult(
            field_name=field_name, symbol=symbol,
            value=round(fused_value, 4),
            confidence=round(confidence, 3),
            sources_checked=len(readings),
            sources_available=len(available),
            sources_agreed=agree_count,
            readings=readings,
            has_disagreement=has_disagreement,
            max_deviation_pct=round(max_dev, 2),
            outlier_source=outlier,
            consensus_value=round(avg, 4),
            recommendation=rec,
        )

    def fuse_price(self, symbol: str, akshare_price: float | None,
                   tushare_price: float | None = None,
                   baostock_price: float | None = None) -> FusedResult:
        """Convenience method for fusing price from common providers."""
        readings = []
        now = datetime.now().isoformat()

        if akshare_price is not None:
            readings.append(SourceReading(
                source_name="akshare", field_name="price",
                value=akshare_price, fetched_at=now,
            ))
        else:
            readings.append(SourceReading(
                source_name="akshare", field_name="price",
                value=0, is_available=False, error="unavailable",
            ))

        if tushare_price is not None:
            readings.append(SourceReading(
                source_name="tushare", field_name="price",
                value=tushare_price, fetched_at=now,
            ))
        if baostock_price is not None:
            readings.append(SourceReading(
                source_name="baostock", field_name="price",
                value=baostock_price, fetched_at=now,
            ))

        return self.fuse("price", symbol, readings)


# Singleton
fusion = DataFusion()
