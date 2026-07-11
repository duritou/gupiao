"""Knowledge Graph — v7.4. Connects events, stocks, sectors into evidence chains.

Not a full graph database. A lightweight link graph that answers:
  "Show me the evidence chain for this AI recommendation."
  "What's happening in the 半导体 sector right now?"
  "Connect this earnings event to the AI signal that triggered."

Structure:
  Stock ──has──→ Event (earnings/policy/news/product)
  Sector ──contains──→ Stock
  Event ──triggers──→ Signal (MACD/alert/recommendation)
  Event ──correlates──→ Event (related events)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.knowledge.event_feed import Event, EventType, event_feed


@dataclass
class EvidenceLink:
    """A single link in an evidence chain."""
    source_type: str = ""        # event / signal / knowledge / market
    source_name: str = ""        # Human-readable: "巨潮资讯"
    source_id: str = ""          # Event ID or signal ID
    description: str = ""        # What this evidence says
    confidence: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "description": self.description,
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp[:19] if self.timestamp else "",
        }


@dataclass
class EvidenceChain:
    """Complete evidence chain for a recommendation or analysis."""
    subject: str = ""            # Stock code or sector
    subject_name: str = ""
    recommendation: str = ""     # "Buy", "Sell", "Hold"
    score: float = 50.0
    generated_at: str = ""

    evidence: list[EvidenceLink] = field(default_factory=list)
    total_confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "subject_name": self.subject_name,
            "recommendation": self.recommendation,
            "score": round(self.score, 1),
            "generated_at": self.generated_at[:19] if self.generated_at else "",
            "evidence": [e.to_dict() for e in self.evidence],
            "total_confidence": round(self.total_confidence, 2),
        }


class KnowledgeGraph:
    """Lightweight graph connecting events → stocks → sectors → signals.

    Provides structured evidence chains for AI recommendations.
    """

    def __init__(self):
        self._stock_sectors: dict[str, list[str]] = defaultdict(list)
        self._sector_stocks: dict[str, list[str]] = defaultdict(list)
        self._event_links: dict[str, list[str]] = defaultdict(list)  # event_id → related event_ids

    # ================================================================
    # Index
    # ================================================================

    def index_stock(self, code: str, name: str, sector: str = ""):
        if sector:
            self._stock_sectors[code].append(sector)
            self._sector_stocks[sector].append(code)

    def link_events(self, event_id_a: str, event_id_b: str):
        self._event_links[event_id_a].append(event_id_b)
        self._event_links[event_id_b].append(event_id_a)

    # ================================================================
    # Evidence Chain Generation
    # ================================================================

    def build_evidence_chain(
        self, stock_code: str, stock_name: str = "",
        recommendation: str = "buy", score: float = 50.0,
    ) -> EvidenceChain:
        """Build a complete evidence chain for a stock recommendation.

        Gathers: related events, sector events, and signal context.
        """
        chain = EvidenceChain(
            subject=stock_code, subject_name=stock_name,
            recommendation=recommendation, score=score,
            generated_at=datetime.now().isoformat(),
        )

        # 1. Stock-specific events
        stock_events = event_feed.get_events_for_stock(stock_code, days=30)
        for e in stock_events[:5]:
            chain.evidence.append(EvidenceLink(
                source_type="event", source_name=e.primary_source,
                source_id=e.id, description=e.title,
                confidence=e.confidence, timestamp=e.timestamp,
            ))

        # 2. Sector-level events
        sector = _guess_sector_from_name(stock_name)
        sector_events = event_feed.get_events_for_sector(sector, days=14)
        for e in sector_events[:3]:
            chain.evidence.append(EvidenceLink(
                source_type="event", source_name=e.primary_source,
                source_id=e.id,
                description=f"[{sector}板块] {e.title}",
                confidence=e.confidence * 0.8,  # Sector events less direct
                timestamp=e.timestamp,
            ))

        # 3. Compute aggregate confidence
        if chain.evidence:
            chain.total_confidence = sum(e.confidence for e in chain.evidence) / len(chain.evidence)

        return chain

    def get_sector_context(self, sector: str) -> dict:
        """Get rich context about a sector: stocks, events, signals."""
        stocks = self._sector_stocks.get(sector, [])
        events = event_feed.get_events_for_sector(sector, days=7)
        important = [e for e in events if e.importance >= 70]

        return {
            "sector": sector,
            "stocks_count": len(stocks),
            "stocks": stocks[:20],
            "recent_events": len(events),
            "important_events": [e.to_dict() for e in important[:5]],
            "sentiment": _compute_sector_sentiment(events),
        }

    def get_stock_knowledge(self, stock_code: str) -> dict:
        """All knowledge the system has about a stock."""
        events = event_feed.get_events_for_stock(stock_code, days=90)
        sectors = self._stock_sectors.get(stock_code, [])

        earnings = [e for e in events if e.event_type == EventType.EARNINGS]
        announcements = [e for e in events if e.event_type == EventType.ANNOUNCEMENT]
        policy_events = [e for e in events if e.event_type == EventType.POLICY]

        return {
            "stock_code": stock_code,
            "sectors": sectors,
            "total_events_90d": len(events),
            "latest_earnings": earnings[0].to_dict() if earnings else None,
            "recent_announcements": [e.to_dict() for e in announcements[:5]],
            "relevant_policies": [e.to_dict() for e in policy_events[:3]],
            "evidence_chain": self.build_evidence_chain(stock_code).to_dict(),
        }


def _guess_sector_from_name(name: str) -> str:
    for kw, sector in [("微", "半导体"), ("芯", "半导体"), ("光", "科技"), ("软", "科技"),
                        ("酒", "消费"), ("药", "医药"), ("医", "医药"), ("生物", "医药"),
                        ("车", "汽车"), ("锂", "新能源"), ("能源", "新能源"), ("光伏", "新能源"),
                        ("银行", "金融"), ("证券", "金融"), ("保险", "金融"),
                        ("地产", "地产"), ("房", "地产")]:
        if kw in name:
            return sector
    return "综合"


def _compute_sector_sentiment(events: list[Event]) -> dict:
    positive = sum(1 for e in events if e.direction == "positive")
    negative = sum(1 for e in events if e.direction == "negative")
    total = len(events)
    score = (positive - negative) / max(total, 1) * 100
    return {
        "positive_count": positive,
        "negative_count": negative,
        "total": total,
        "sentiment_score": round(score, 1),
        "bias": "bullish" if score > 30 else "bearish" if score < -30 else "neutral",
    }


# Singleton
kg = KnowledgeGraph()
