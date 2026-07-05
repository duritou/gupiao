"""Portfolio domain model — Position tracking + AI rescoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Position:
    """A single holding in the portfolio."""
    stock_code: str
    stock_name: str
    shares: int              # 持仓数量
    cost_price: float        # 成本价
    current_price: float = 0.0
    market_value: float = 0.0       # 市值 = shares * current_price
    cost_value: float = 0.0         # 成本 = shares * cost_price
    profit_loss: float = 0.0        # 盈亏金额
    profit_loss_pct: float = 0.0    # 盈亏比例
    weight_pct: float = 0.0         # 占总仓比例
    ai_score: float = 50.0          # 当前 AI 评分
    ai_direction: str = "neutral"
    ai_signal: str = ""             # 最强信号名称
    risk_level: str = "中"
    added_date: str = ""            # 建仓日期
    last_score_change: float = 0.0  # 最近评分变化


@dataclass
class Portfolio:
    """Complete portfolio snapshot."""
    date: str = ""
    total_value: float = 0.0
    total_cost: float = 0.0
    total_pl: float = 0.0
    total_pl_pct: float = 0.0
    daily_pl: float = 0.0
    daily_pl_pct: float = 0.0
    cash: float = 0.0
    positions: list[Position] = field(default_factory=list)
    ai_summary: str = ""            # AI-generated portfolio summary
    risk_summary: str = ""          # Portfolio risk assessment
    top_performer: str = ""         # Best performing holding
    worst_performer: str = ""       # Worst performing holding

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def avg_ai_score(self) -> float:
        if not self.positions:
            return 50.0
        return sum(p.ai_score * p.weight_pct for p in self.positions) / 100

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "total_value": round(self.total_value, 2),
            "total_cost": round(self.total_cost, 2),
            "total_pl": round(self.total_pl, 2),
            "total_pl_pct": round(self.total_pl_pct, 2),
            "daily_pl": round(self.daily_pl, 2),
            "daily_pl_pct": round(self.daily_pl_pct, 2),
            "cash": round(self.cash, 2),
            "position_count": self.position_count,
            "avg_ai_score": round(self.avg_ai_score, 1),
            "ai_summary": self.ai_summary,
            "risk_summary": self.risk_summary,
            "top_performer": self.top_performer,
            "worst_performer": self.worst_performer,
            "positions": [
                {
                    "stock_code": p.stock_code,
                    "stock_name": p.stock_name,
                    "shares": p.shares,
                    "cost_price": round(p.cost_price, 2),
                    "current_price": round(p.current_price, 2),
                    "market_value": round(p.market_value, 2),
                    "cost_value": round(p.cost_value, 2),
                    "profit_loss": round(p.profit_loss, 2),
                    "profit_loss_pct": round(p.profit_loss_pct, 2),
                    "weight_pct": round(p.weight_pct, 2),
                    "ai_score": round(p.ai_score, 1),
                    "ai_direction": p.ai_direction,
                    "ai_signal": p.ai_signal,
                    "risk_level": p.risk_level,
                    "added_date": p.added_date,
                    "last_score_change": round(p.last_score_change, 1),
                }
                for p in self.positions
            ],
        }
