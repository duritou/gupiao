"""Alert Intelligence domain model — P0-P4 alerts with lifecycle, evidence, action tracking.

Alert is not just a notification. It's an AI-driven decision support unit that:
- Has severity levels (P0 emergency → P4 informational)
- Carries structured evidence (why this alert matters)
- Tracks lifecycle (NEW → READ → ACTED → VERIFIED → ARCHIVED)
- Links to actions and outcomes (closed-loop learning)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AlertLevel(str, Enum):
    """Alert severity — determines delivery channel and urgency."""
    P0 = "P0"  # Emergency: stop-loss triggered, crash, circuit breaker → 🔴 push notification
    P1 = "P1"  # Strong opportunity/risk: score change >=5, breakout → 🟢 push notification
    P2 = "P2"  # Portfolio change: AI upgrade/downgrade, position alert → Dashboard
    P3 = "P3"  # Market event: sector rotation, macro event → Morning Brief
    P4 = "P4"  # Informational: news, earnings, minor signal → Timeline / Alert Center


class AlertStatus(str, Enum):
    """Alert lifecycle states."""
    NEW = "new"           # Just generated, not yet seen
    READ = "read"         # User has seen it
    ACTED = "acted"       # User took action (buy/sell/hold based on alert)
    VERIFIED = "verified" # Outcome is known (win/loss/neutral)
    ARCHIVED = "archived" # No longer relevant
    DISMISSED = "dismissed"  # User explicitly dismissed


class AlertCategory(str, Enum):
    """What triggered this alert."""
    SIGNAL = "signal"           # Technical signal (MACD cross, RSI, etc.)
    PORTFOLIO = "portfolio"     # Position change, risk threshold
    MARKET = "market"           # Market-wide event, sentiment shift
    KNOWLEDGE = "knowledge"     # Industry/sector intelligence
    RISK = "risk"               # Risk threshold breach
    OPPORTUNITY = "opportunity" # AI-discovered opportunity


@dataclass
class AlertEvidence:
    """Structured evidence backing an alert — why this alert matters."""
    type: str = ""              # signal / market / knowledge / risk
    title: str = ""             # Human-readable evidence title
    description: str = ""       # One-line explanation
    confidence: float = 0.0     # 0-1 confidence in this evidence
    source: str = ""            # Which engine produced this (MACDSignal, ExplainEngine, etc.)
    impact: float = 0.0         # Score contribution (+/- points)
    detail: dict[str, Any] = field(default_factory=dict)  # Optional structured data

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "confidence": round(self.confidence, 2),
            "source": self.source,
            "impact": round(self.impact, 1),
            "detail": self.detail,
        }


@dataclass
class AlertAction:
    """User action taken in response to an alert."""
    action_type: str = ""       # buy / sell / hold / add_watch / dismiss
    timestamp: str = ""
    stock_code: str = ""
    quantity: int = 0
    price: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "timestamp": self.timestamp,
            "stock_code": self.stock_code,
            "quantity": self.quantity,
            "price": self.price,
            "notes": self.notes,
        }


@dataclass
class AlertOutcome:
    """Verified outcome of an acted-upon alert."""
    outcome_type: str = ""      # win / loss / neutral / expired
    realized_pl_pct: float = 0.0
    holding_days: int = 0
    was_correct: bool = False   # Was the AI's direction correct?
    verified_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "outcome_type": self.outcome_type,
            "realized_pl_pct": round(self.realized_pl_pct, 2),
            "holding_days": self.holding_days,
            "was_correct": self.was_correct,
            "verified_at": self.verified_at,
            "notes": self.notes,
        }


@dataclass
class Alert:
    """An intelligent alert — AI's proactive decision support unit."""

    id: str = ""
    level: AlertLevel = AlertLevel.P4
    category: AlertCategory = AlertCategory.SIGNAL
    status: AlertStatus = AlertStatus.NEW

    # Target
    stock_code: str = ""
    stock_name: str = ""

    # Content
    title: str = ""             # One-line summary, e.g. "寒武纪 AI评分 +6 → 强烈买入"
    body: str = ""              # Rich description with reasoning
    direction: str = "neutral"  # buy / sell / neutral
    score: float = 50.0         # Current AI score
    score_change: float = 0.0   # Score change that triggered this alert

    # Timing
    created_at: str = ""
    read_at: str = ""
    acted_at: str = ""

    # Evidence chain — why this alert exists
    evidence: list[AlertEvidence] = field(default_factory=list)

    # Confidence & accuracy
    ai_confidence: float = 0.0          # 0-1, how confident the AI is
    historical_accuracy: float = 0.0    # 0-1, past accuracy for similar signals

    # Lifecycle tracking
    action: AlertAction | None = None
    outcome: AlertOutcome | None = None

    # Metadata
    tags: list[str] = field(default_factory=list)
    related_alert_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "level": self.level.value,
            "category": self.category.value,
            "status": self.status.value,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "title": self.title,
            "body": self.body,
            "direction": self.direction,
            "score": round(self.score, 1),
            "score_change": round(self.score_change, 1),
            "created_at": self.created_at,
            "read_at": self.read_at,
            "acted_at": self.acted_at,
            "evidence": [e.to_dict() for e in self.evidence],
            "ai_confidence": round(self.ai_confidence, 2),
            "historical_accuracy": round(self.historical_accuracy, 2),
            "action": self.action.to_dict() if self.action else None,
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "tags": self.tags,
            "related_alert_ids": self.related_alert_ids,
        }
        return result


@dataclass
class AlertFeed:
    """A collection of alerts with metadata."""
    alerts: list[Alert] = field(default_factory=list)
    total_today: int = 0
    unread_count: int = 0
    p0_count: int = 0
    p1_count: int = 0
    last_updated: str = ""

    @property
    def urgent_count(self) -> int:
        return self.p0_count + self.p1_count

    def to_dict(self) -> dict:
        return {
            "alerts": [a.to_dict() for a in self.alerts],
            "total_today": self.total_today,
            "unread_count": self.unread_count,
            "p0_count": self.p0_count,
            "p1_count": self.p1_count,
            "urgent_count": self.urgent_count,
            "last_updated": self.last_updated,
        }


@dataclass
class AlertStats:
    """Aggregate alert statistics for the user."""
    total_alerts: int = 0
    alerts_today: int = 0
    acted_count: int = 0
    verified_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_holding_days: float = 0.0
    total_realized_pl_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_alerts": self.total_alerts,
            "alerts_today": self.alerts_today,
            "acted_count": self.acted_count,
            "verified_count": self.verified_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(self.win_rate, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "total_realized_pl_pct": round(self.total_realized_pl_pct, 2),
        }
