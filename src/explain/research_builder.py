"""Research Snapshot Builder — v11.1 Architecture Stabilization.

Single entry point for assembling a complete research snapshot.
Every consumer (Research page, Replay, Case Library, Decision Center)
calls this builder — one canonical implementation, one contract.

ResearchSnapshot V1 fields (versioned — never remove, only add in V2):
  Metadata:   stock_code, stock_name, snapshot_version, generated_at
  Market:     price, open, high, low, pre_close, change_pct, volume, amount_yi
  Technical:  indicators (MA + signal states), klines
  AI:         ai_score, direction, confidence, scores, recommendation
  Evidence:   source, data_days, data_quality
  Provenance: _data (quote/kline source info)

Future V2 additions (Committee, Governance, Similar Cases, Pre-mortem)
will add new top-level keys without modifying V1 fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ================================================================
# Research Snapshot V1 — Versioned DTO
# ================================================================

@dataclass
class ResearchSnapshotV1:
    """Complete research snapshot for a single stock. Versioned contract.

    Frontend consumers depend on this exact field set.
    Contract tests enforce that every field is present.
    """
    # Metadata
    stock_code: str = ""
    stock_name: str = ""
    snapshot_version: str = "V1"
    generated_at: str = ""

    # Market data
    latest_price: float = 0.0
    price_change_pct: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0
    volume: float = 0.0
    amount_yi: float = 0.0
    turnover: float = 0.0
    pe: float = 0.0
    total_market_cap: float = 0.0

    # Technical indicators
    indicators: dict = field(default_factory=dict)
    klines: list[dict] = field(default_factory=list)

    # AI analysis
    ai_score: float = 50.0
    direction: str = "neutral"
    confidence: float = 0.0
    scores: dict = field(default_factory=dict)
    recommendation: str = ""
    buy_signals: int = 0
    sell_signals: int = 0
    stars: int = 3

    # Evidence
    evidence: list[dict] = field(default_factory=list)

    # Provenance
    _data: dict = field(default_factory=dict)
    data_error: str = ""

    # ------ V2 reserved (not populated yet) ------
    # committee: dict      — Investment Committee result
    # governance: dict     — Governance audit result
    # similar_cases: dict  — Case retrieval result
    # pre_mortem: dict     — Pre-mortem analysis

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "snapshot_version": self.snapshot_version,
            "generated_at": self.generated_at[:19] if self.generated_at else "",
            # Market
            "latest_price": self.latest_price,
            "price_change_pct": round(self.price_change_pct, 2),
            "open": self.open, "high": self.high, "low": self.low,
            "pre_close": self.pre_close,
            "volume": self.volume,
            "amount_yi": self.amount_yi,
            "turnover": round(self.turnover, 2),
            "pe": round(self.pe, 2),
            "total_market_cap": self.total_market_cap,
            # Technical
            "indicators": self.indicators,
            "klines": self.klines,
            # AI
            "ai_score": round(self.ai_score, 1),
            "direction": self.direction,
            "confidence": round(self.confidence, 3),
            "scores": {k: round(v, 1) for k, v in self.scores.items()},
            "recommendation": self.recommendation,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "stars": self.stars,
            # Evidence
            "evidence": self.evidence,
            # Provenance
            "_data": self._data,
            "data_error": self.data_error,
        }

    # Contract: required top-level keys (for contract testing)
    CONTRACT_FIELDS = [
        "stock_code", "stock_name", "snapshot_version", "generated_at",
        "latest_price", "price_change_pct", "open", "high", "low",
        "pre_close", "volume", "amount_yi", "turnover", "pe", "total_market_cap",
        "indicators", "klines",
        "ai_score", "direction", "confidence", "scores", "recommendation",
        "buy_signals", "sell_signals", "stars",
        "evidence", "_data",
    ]


# ================================================================
# Research Snapshot Builder
# ================================================================

class ResearchSnapshotBuilder:
    """Assembles a ResearchSnapshotV1 from real market data.

    Single canonical implementation. All consumers use this.
    """

    async def build(self, code: str) -> ResearchSnapshotV1:
        """Build a complete research snapshot for a stock.

        Flow: Quote → K-line → Indicators → Signals → Evidence → Snapshot
        """
        from src.api.routes.journal_utils import stock_name_from_journal
        from src.infrastructure.market_data.source_manager import source_manager
        from src.infrastructure.market_data.real_data_provider import real_data

        name = stock_name_from_journal(code)
        snap = ResearchSnapshotV1(
            stock_code=code,
            stock_name=name,
            generated_at=datetime.now().isoformat(),
        )

        # 1. Quote
        quote, quote_prov = await source_manager.get_realtime_quote(code)
        if quote is not None:
            snap.latest_price = quote.get("price", 0)
            snap.stock_name = quote.get("stock_name", name)
            snap.price_change_pct = quote.get("change_pct", 0)
            snap.open = quote.get("open", 0)
            snap.high = quote.get("high", 0)
            snap.low = quote.get("low", 0)
            snap.pre_close = quote.get("pre_close", 0)
            snap.volume = quote.get("volume", 0)
            snap.amount_yi = quote.get("amount_yi", 0)
            snap.turnover = quote.get("turnover", 0)
            snap.pe = quote.get("pe", 0)
            snap.total_market_cap = quote.get("total_market_cap", 0)
        else:
            snap.data_error = quote_prov.error_message

        # 2. K-line + Indicators + Signals
        klines, kline_prov = await source_manager.get_kline(code, count=250)
        if klines is not None:
            snap.klines = klines

            if len(klines) >= 20:
                closes = [k["close"] for k in klines]
                ma5 = sum(closes[-5:]) / 5
                ma10 = sum(closes[-10:]) / 10
                ma20 = sum(closes[-20:]) / 20

                try:
                    sig = real_data.compute_signals(code, name, klines)
                except Exception:
                    sig = None

                if sig is not None:
                    snap.indicators = {
                        "ma5": round(ma5, 2), "ma10": round(ma10, 2),
                        "ma20": round(ma20, 2), "data_points": len(klines),
                        "macd_signal": (
                            "金叉" if sig.macd_score >= 65 else
                            "死叉" if sig.macd_score <= 35 else "中性"
                        ),
                        "rsi_value": round(sig.rsi_score, 1),
                        "rsi_status": (
                            "超买" if sig.rsi_score <= 35 else
                            "超卖" if sig.rsi_score >= 65 else "中性"
                        ),
                        "ma_trend": (
                            "多头" if sig.ma_score >= 65 else
                            "空头" if sig.ma_score <= 35 else "震荡"
                        ),
                    }
                    snap.ai_score = sig.fusion_score
                    snap.direction = sig.direction
                    snap.confidence = sig.confidence
                    snap.scores = {
                        "macd": sig.macd_score, "rsi": sig.rsi_score,
                        "kdj": sig.kdj_score, "ma": sig.ma_score,
                        "volume": sig.volume_score,
                    }
                    fm = sig.fusion_score
                    snap.recommendation = (
                        "强烈买入" if fm >= 80 else "买入" if fm >= 65
                        else "观望" if fm >= 50 else "减仓" if fm >= 35
                        else "卖出"
                    )
                    sl = [sig.macd_score, sig.rsi_score, sig.kdj_score,
                          sig.ma_score, sig.volume_score]
                    snap.buy_signals = sum(1 for s in sl if s >= 65)
                    snap.sell_signals = sum(1 for s in sl if s <= 35)
                    snap.stars = (
                        5 if fm >= 85 else 4 if fm >= 70
                        else 3 if fm >= 55 else 2 if fm >= 40 else 1
                    )
                    snap.evidence = [{
                        "type": "technical",
                        "source": sig.data_source,
                        "description": (
                            f"MACD/RSI/KDJ/MA/Volume 信号从 "
                            f"{sig.data_days} 根真实日线计算"
                        ),
                        "confidence": sig.confidence,
                    }]
                else:
                    snap.indicators = {
                        "ma5": round(ma5, 2), "ma10": round(ma10, 2),
                        "ma20": round(ma20, 2), "data_points": len(klines),
                    }

        # 3. Provenance
        snap._data = {
            "quote": quote_prov.to_dict() if quote_prov else {"available": False},
            "kline": kline_prov.to_dict() if kline_prov else {"available": False},
            "is_live": quote_prov.is_live if quote_prov else False,
            "data_available": quote is not None or klines is not None,
            "recommendation": (
                "Data ready for AI analysis" if quote is not None
                else "数据不可用 — 请检查网络或等待行情恢复"
            ),
        }

        return snap


# Singleton
research_builder = ResearchSnapshotBuilder()
