"""Event Feed — v7.4. Normalize all data sources into structured events.

Instead of raw news/articles flowing directly to the LLM, everything is
normalized into Event objects. Multiple sources reporting the same event
are merged (News Fusion). The AI sees Events, not raw text.

Event Types:
  earnings     — 财报发布 (营收/利润/ROE)
  announcement — 公司公告 (分红/回购/定增/减持)
  policy       — 行业政策 (工信部/发改委/能源局)
  macro        — 宏观数据 (PMI/CPI/GDP/利率)
  product      — 产品发布/中标/合作
  market       — 市场事件 (涨跌停/异常波动/北向异动)
  signal       — 技术信号 (MACD交叉/突破/放量)
  news         — 新闻 (其他未分类)

Importance scoring: 0-100
  ≥90: 必须关注 (重大政策/财报超预期/公司重大事件)
  ≥70: 重要 (行业政策/业绩变化/北向异动)
  ≥50: 一般 (常规新闻/小范围影响)
  <50: 参考 (日常信息)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class EventType(str, Enum):
    EARNINGS = "earnings"
    ANNOUNCEMENT = "announcement"
    POLICY = "policy"
    MACRO = "macro"
    PRODUCT = "product"
    MARKET = "market"
    SIGNAL = "signal"
    NEWS = "news"


@dataclass
class Event:
    """A single structured event — the atom of the knowledge system."""
    id: str = ""
    event_type: EventType = EventType.NEWS
    title: str = ""                     # One-line summary
    summary: str = ""                   # 2-3 sentence description
    timestamp: str = ""

    # What is this about?
    stock_codes: list[str] = field(default_factory=list)    # Directly affected stocks
    sectors: list[str] = field(default_factory=list)        # Affected sectors
    tags: list[str] = field(default_factory=list)           # macd金叉/政策利好/业绩超预期

    # Where did it come from?
    primary_source: str = ""            # "巨潮资讯"
    primary_source_url: str = ""
    merged_sources: list[str] = field(default_factory=list)  # Other sources confirming

    # How important is it?
    importance: int = 50                # 0-100
    confidence: float = 0.7            # 0-1, how certain we are
    is_verified: bool = False           # Multiple sources confirm

    # Impact assessment
    direction: str = "neutral"          # positive / negative / neutral
    impact_score: float = 0.0           # -10 to +10, estimated price impact

    # AI enrichment
    ai_analysis: str = ""               # AI-generated one-paragraph analysis
    related_event_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "title": self.title,
            "summary": self.summary,
            "timestamp": self.timestamp[:19] if self.timestamp else "",
            "stock_codes": self.stock_codes,
            "sectors": self.sectors,
            "tags": self.tags,
            "primary_source": self.primary_source,
            "primary_source_url": self.primary_source_url,
            "merged_sources": self.merged_sources,
            "importance": self.importance,
            "confidence": round(self.confidence, 2),
            "is_verified": self.is_verified,
            "direction": self.direction,
            "impact_score": round(self.impact_score, 1),
            "ai_analysis": self.ai_analysis,
            "related_event_ids": self.related_event_ids,
        }


class EventFeed:
    """Normalizes all data sources into a structured event stream.

    Key behaviors:
    - News Fusion: if 3 sources report the same event, merge into one Event
      with confidence boosted
    - Importance scoring: calculated from source trust tier + event type
    - Source verification: official source → higher confidence than news
    """

    def __init__(self):
        self._events: list[Event] = []
        self._event_index: dict[str, int] = {}  # id → list index
        self._stock_index: dict[str, list[int]] = defaultdict(list)  # stock → event indices
        self._sector_index: dict[str, list[int]] = defaultdict(list)  # sector → event indices

    # ================================================================
    # Event Creation
    # ================================================================

    def add_event(
        self, event_type: EventType, title: str, summary: str = "",
        stock_codes: list[str] | None = None, sectors: list[str] | None = None,
        tags: list[str] | None = None, primary_source: str = "",
        importance: int = 50, direction: str = "neutral",
        impact_score: float = 0.0,
    ) -> Event:
        """Add a single event to the feed."""
        now = datetime.now()
        event_id = f"evt_{now.strftime('%Y%m%d%H%M%S')}_{len(self._events):04d}"

        # Auto-adjust importance from source trust tier
        from src.infrastructure.market_data.registry import DATA_SOURCE_REGISTRY
        source_info = DATA_SOURCE_REGISTRY.get(primary_source)
        if source_info and source_info.tier in ("official", "disclosure"):
            importance = min(100, importance + 15)  # Official source → boost
            confidence = 0.95
        elif source_info and source_info.tier == "news":
            confidence = 0.75
        else:
            confidence = 0.70

        event = Event(
            id=event_id, event_type=event_type, title=title, summary=summary,
            timestamp=now.isoformat(),
            stock_codes=stock_codes or [], sectors=sectors or [],
            tags=tags or [],
            primary_source=primary_source,
            importance=importance, confidence=confidence,
            is_verified=source_info.tier in ("official", "disclosure") if source_info else False,
            direction=direction, impact_score=impact_score,
        )

        self._events.append(event)
        idx = len(self._events) - 1
        self._event_index[event_id] = idx

        # Index by stock and sector
        for code in event.stock_codes:
            self._stock_index[code].append(idx)
        for sector in event.sectors:
            self._sector_index[sector].append(idx)

        return event

    def add_earnings_event(
        self, stock_code: str, stock_name: str, period: str,
        revenue: float, net_profit: float, revenue_growth: float,
        profit_growth: float, roe: float, source: str = "cninfo",
    ) -> Event:
        """Create a structured earnings event. Source: 巨潮资讯."""
        direction = "positive" if profit_growth > 20 else "negative" if profit_growth < -10 else "neutral"
        importance = 85 if abs(profit_growth) > 50 else 70 if abs(profit_growth) > 15 else 55

        title = f"{stock_name} {period}财报: 净利润{profit_growth:+.0f}%"
        summary = (
            f"{stock_name}({stock_code})发布{period}财报。"
            f"营收{revenue:.1f}亿({revenue_growth:+.1f}%)，"
            f"净利润{net_profit:.1f}亿({profit_growth:+.1f}%)，ROE {roe:.1f}%。"
        )

        return self.add_event(
            event_type=EventType.EARNINGS,
            title=title, summary=summary,
            stock_codes=[stock_code], sectors=[_guess_sector(stock_name)],
            tags=["财报", f"利润增长{profit_growth:+.0f}%" if profit_growth > 0 else "利润下滑"],
            primary_source=source, importance=importance,
            direction=direction, impact_score=profit_growth / 10,
        )

    def add_policy_event(
        self, title: str, summary: str, sectors: list[str],
        issuing_body: str, importance: int = 80, direction: str = "positive",
    ) -> Event:
        """Create a policy event. Source: 工信部/发改委/能源局 etc."""
        return self.add_event(
            event_type=EventType.POLICY,
            title=title, summary=summary, sectors=sectors,
            tags=["产业政策"] + sectors,
            primary_source=issuing_body,
            importance=importance, direction=direction,
            impact_score=8 if direction == "positive" else -5,
        )

    def add_macro_event(
        self, indicator: str, value: str, previous: str,
        source: str = "nbs", importance: int = 75,
    ) -> Event:
        """Create a macro data event. Source: 统计局/人民银行."""
        direction = "positive" if "增长" in value or "上升" in value else "neutral"
        title = f"{indicator}: {value} (前值: {previous})"
        summary = f"最新宏观数据: {indicator} = {value}，前值 = {previous}。来源: {source}。"

        return self.add_event(
            event_type=EventType.MACRO,
            title=title, summary=summary, sectors=["宏观经济"],
            tags=["宏观", indicator],
            primary_source=source, importance=importance,
            direction=direction, impact_score=5 if direction == "positive" else -3,
        )

    # ================================================================
    # News Fusion — merge duplicate reports
    # ================================================================

    def try_merge_with_existing(
        self, title: str, source: str,
        similarity_threshold: float = 0.7,
    ) -> Event | None:
        """Check if this event is already reported by another source.
        If yes, merge (boost confidence, add source to merged_sources).
        Returns the existing event if merged, None if new.
        """
        if not self._events:
            return None

        # Simple title keyword overlap check
        keywords = set(title.replace("：", " ").replace("，", " ").split())
        if len(keywords) < 3:
            return None

        for event in self._events[-20:]:  # Check recent events
            existing_kw = set(event.title.replace("：", " ").replace("，", " ").split())
            if len(existing_kw) < 3:
                continue
            overlap = len(keywords & existing_kw) / max(len(keywords | existing_kw), 1)
            if overlap >= similarity_threshold:
                # Merge!
                if source not in event.merged_sources and source != event.primary_source:
                    event.merged_sources.append(source)
                    event.confidence = min(1.0, event.confidence + 0.1)
                    if len(event.merged_sources) >= 2:
                        event.is_verified = True
                        event.importance = min(100, event.importance + 5)
                return event

        return None

    # ================================================================
    # Query
    # ================================================================

    def get_events(
        self, limit: int = 50, event_type: str = "",
        stock_code: str = "", sector: str = "",
        min_importance: int = 0, since_hours: float = 0,
    ) -> list[Event]:
        """Query events with filters."""
        results = self._events

        if event_type:
            results = [e for e in results if e.event_type.value == event_type]
        if stock_code:
            indices = self._stock_index.get(stock_code, [])
            results = [self._events[i] for i in indices]
        if sector:
            indices = self._sector_index.get(sector, [])
            results = [self._events[i] for i in indices]
        if min_importance > 0:
            results = [e for e in results if e.importance >= min_importance]
        if since_hours > 0:
            cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()
            results = [e for e in results if e.timestamp >= cutoff]

        results.sort(key=lambda e: (-e.importance, e.timestamp), reverse=True)
        return results[:limit]

    def get_events_for_stock(self, stock_code: str, days: int = 7) -> list[Event]:
        """Get all events related to a stock."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        indices = self._stock_index.get(stock_code, [])
        events = [
            self._events[i] for i in indices
            if self._events[i].timestamp >= cutoff
        ]
        events.sort(key=lambda e: (-e.importance, e.timestamp), reverse=True)
        return events

    def get_events_for_sector(self, sector: str, days: int = 7) -> list[Event]:
        """Get all events for a sector."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        indices = self._sector_index.get(sector, [])
        events = [
            self._events[i] for i in indices
            if self._events[i].timestamp >= cutoff
        ]
        events.sort(key=lambda e: (-e.importance, e.timestamp), reverse=True)
        return events

    def get_important_events(self, limit: int = 10) -> list[Event]:
        """Get the most important events right now."""
        return self.get_events(limit=limit, min_importance=70)

    def get_timeline(self, hours: int = 24, limit: int = 50) -> list[Event]:
        """Get a chronological timeline of recent events."""
        return self.get_events(limit=limit, since_hours=hours)

    # ================================================================
    # Stats
    # ================================================================

    def get_stats(self) -> dict:
        """Get event feed statistics."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        today_events = [e for e in self._events if e.timestamp.startswith(today)]

        by_type = defaultdict(int)
        by_source = defaultdict(int)
        for e in self._events:
            by_type[e.event_type.value] += 1
            by_source[e.primary_source] += 1

        return {
            "total_events": len(self._events),
            "today_events": len(today_events),
            "verified_events": sum(1 for e in self._events if e.is_verified),
            "by_type": dict(by_type),
            "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])[:10]),
            "stocks_indexed": len(self._stock_index),
            "sectors_indexed": len(self._sector_index),
        }


def _guess_sector(name: str) -> str:
    for kw, sector in [("微", "半导体"), ("芯", "半导体"), ("光", "科技"),
                        ("酒", "消费"), ("药", "医药"), ("医", "医药"),
                        ("车", "汽车"), ("锂", "新能源"), ("银行", "金融")]:
        if kw in name:
            return sector
    return "综合"


# Singleton
event_feed = EventFeed()
