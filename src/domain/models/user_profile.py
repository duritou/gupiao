"""User model domain — v6.0 Adaptive Intelligence.

The UserBehaviorProfile is NOT a configuration form. It is a LEARNED model.
Every field is derived from the user's actual behavior — what they bought, sold,
ignored, held — not what they said they'd do.

Sources:
  - Decision Journal (AI recommendation → user action → outcome)
  - Portfolio history (positions, holding periods, sector allocation)
  - Alert interactions (which alerts did they act on?)
  - Trust data (Snapshot → Outcome tracking)

The AI uses this profile to ADAPT its recommendations to each individual user.
Same stock, different users → different recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ================================================================
# Learned Traits (all derived from behavior, never configured)
# ================================================================

@dataclass
class InvestmentStyle:
    """Learned investment style from holding patterns."""
    primary_style: str = ""          # growth / value / momentum / swing / index
    confidence: float = 0.0          # How confident the model is in this label
    avg_holding_days: float = 0.0
    holding_consistency: float = 0.0  # StdDev of holding days (lower = more consistent)
    turnover_rate: float = 0.0        # How often positions change

    def to_dict(self) -> dict:
        return {
            "primary_style": self.primary_style,
            "confidence": round(self.confidence, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "holding_consistency": round(self.holding_consistency, 1),
            "turnover_rate": round(self.turnover_rate, 2),
        }


@dataclass
class RiskProfile:
    """Learned risk tolerance from actual behavior."""
    level: str = ""                   # conservative / moderate / aggressive
    confidence: float = 0.0
    max_position_size_pct: float = 0.0  # Largest single position ever taken
    avg_position_size_pct: float = 0.0
    max_drawdown_tolerated_pct: float = 0.0
    stop_loss_adherence: float = 0.0    # How often they actually cut losses
    avg_leverage: float = 0.0

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "confidence": round(self.confidence, 2),
            "max_position_size_pct": round(self.max_position_size_pct, 1),
            "avg_position_size_pct": round(self.avg_position_size_pct, 1),
            "max_drawdown_tolerated_pct": round(self.max_drawdown_tolerated_pct, 1),
            "stop_loss_adherence": round(self.stop_loss_adherence, 2),
            "avg_leverage": round(self.avg_leverage, 2),
        }


@dataclass
class SectorAffinity:
    """Learned sector preferences and performance."""
    sector: str = ""
    trade_count: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    affinity_score: float = 0.0       # 0-1, how much they gravitate toward this sector
    is_strength: bool = False         # Is this a strength area?

    def to_dict(self) -> dict:
        return {
            "sector": self.sector,
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate, 2),
            "avg_return": round(self.avg_return, 2),
            "affinity_score": round(self.affinity_score, 2),
            "is_strength": self.is_strength,
        }


@dataclass
class StrategyStrength:
    """Learned strategy effectiveness per user."""
    strategy_name: str = ""           # e.g. "MACD金叉", "放量突破"
    times_used: int = 0
    times_correct: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    is_best: bool = False

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "times_used": self.times_used,
            "times_correct": self.times_correct,
            "win_rate": round(self.win_rate, 2),
            "avg_return": round(self.avg_return, 2),
            "is_best": self.is_best,
        }


@dataclass
class BehaviorPattern:
    """Discovered behavioral patterns — strengths and weaknesses."""
    pattern_type: str = ""            # strength / weakness
    pattern_name: str = ""            # e.g. "追高买入", "止盈过早", "善于持有龙头"
    description: str = ""
    frequency: float = 0.0            # How often this pattern occurs
    avg_impact_pct: float = 0.0       # Average P&L impact when this pattern fires
    evidence_count: int = 0           # Number of times observed

    def to_dict(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "pattern_name": self.pattern_name,
            "description": self.description,
            "frequency": round(self.frequency, 2),
            "avg_impact_pct": round(self.avg_impact_pct, 2),
            "evidence_count": self.evidence_count,
        }


@dataclass
class AIAlignment:
    """How well does the user align with AI recommendations?"""
    overall_follow_rate: float = 0.0
    follow_rate_high_confidence: float = 0.0   # Follow rate when AI confidence > 80%
    follow_rate_low_confidence: float = 0.0    # Follow rate when AI confidence < 60%
    trust_trend: str = ""                      # growing / stable / declining
    trust_score: float = 0.0                   # 0-1 composite trust level
    trust_gap_pct: float = 0.0                 # % of profitable recs user ignored

    def to_dict(self) -> dict:
        return {
            "overall_follow_rate": round(self.overall_follow_rate, 2),
            "follow_rate_high_confidence": round(self.follow_rate_high_confidence, 2),
            "follow_rate_low_confidence": round(self.follow_rate_low_confidence, 2),
            "trust_trend": self.trust_trend,
            "trust_score": round(self.trust_score, 2),
            "trust_gap_pct": round(self.trust_gap_pct, 2),
        }


# ================================================================
# Master Profile
# ================================================================

@dataclass
class UserBehaviorProfile:
    """Complete learned user profile — zero configuration, 100% behavioral."""

    # Meta
    profile_version: str = "v6.0"
    generated_at: str = ""
    data_period_days: int = 0
    total_decisions_analyzed: int = 0

    # Learned dimensions
    investment_style: InvestmentStyle | None = None
    risk_profile: RiskProfile | None = None
    sector_affinities: list[SectorAffinity] = field(default_factory=list)
    strategy_strengths: list[StrategyStrength] = field(default_factory=list)
    behavior_patterns: list[BehaviorPattern] = field(default_factory=list)
    ai_alignment: AIAlignment | None = None

    # Adaptive recommendation modifiers (applied to base AI scores)
    sector_boost: dict[str, float] = field(default_factory=dict)     # sector → score modifier
    strategy_boost: dict[str, float] = field(default_factory=dict)   # strategy → score modifier
    risk_override: dict[str, float] = field(default_factory=dict)    # risk parameter overrides

    # AI's understanding of the user (natural language, shown in UI)
    user_summary: str = ""            # One-paragraph behavioral summary
    personalized_greeting: str = ""   # Shown on Dashboard

    def to_dict(self) -> dict:
        return {
            "profile_version": self.profile_version,
            "generated_at": self.generated_at,
            "data_period_days": self.data_period_days,
            "total_decisions_analyzed": self.total_decisions_analyzed,
            "investment_style": self.investment_style.to_dict() if self.investment_style else None,
            "risk_profile": self.risk_profile.to_dict() if self.risk_profile else None,
            "sector_affinities": [s.to_dict() for s in self.sector_affinities],
            "strategy_strengths": [s.to_dict() for s in self.strategy_strengths],
            "behavior_patterns": [p.to_dict() for p in self.behavior_patterns],
            "ai_alignment": self.ai_alignment.to_dict() if self.ai_alignment else None,
            "sector_boost": {k: round(v, 2) for k, v in self.sector_boost.items()},
            "strategy_boost": {k: round(v, 2) for k, v in self.strategy_boost.items()},
            "risk_override": {k: round(v, 2) for k, v in self.risk_override.items()},
            "user_summary": self.user_summary,
            "personalized_greeting": self.personalized_greeting,
        }


# ================================================================
# Adaptive Recommendation (AI output modified by user profile)
# ================================================================

@dataclass
class AdaptiveRecommendation:
    """A base AI recommendation adjusted by user profile.

    Same stock, different users → different output.
    """

    stock_code: str = ""
    stock_name: str = ""
    base_score: float = 50.0
    adjusted_score: float = 50.0

    # Why the adjustment?
    adjustments: list[dict] = field(default_factory=list)
    # e.g. [{"reason": "你最擅长的MACD金叉策略 +3", "impact": 3},
    #        {"reason": "半导体是你历史胜率最高的行业 +2", "impact": 2}]

    base_direction: str = "neutral"
    adjusted_direction: str = "neutral"

    personalized_reason: str = ""     # e.g. "寒武纪符合你成功率最高的模式..."

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "base_score": round(self.base_score, 1),
            "adjusted_score": round(self.adjusted_score, 1),
            "adjustments": self.adjustments,
            "base_direction": self.base_direction,
            "adjusted_direction": self.adjusted_direction,
            "personalized_reason": self.personalized_reason,
        }
