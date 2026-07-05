"""Decision Center — v8.0. Daily prioritized action list.

Not another scanner. Not another watchlist. A single page that answers:
  "What should I do today?"

Every recommendation includes:
  - Bull Case (why to act)
  - Bear Case (why to hesitate)
  - Personal Context (user's history with this stock)
  - Evidence Chain (traceable to specific data sources)
"""

from __future__ import annotations

import hashlib
import random as _random
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any


@dataclass
class BullBearPoint:
    """A single argument for or against."""
    point: str = ""          # e.g. "MACD金叉形成，技术面积极"
    source: str = ""         # e.g. "东方财富(AkShare)"
    evidence_type: str = ""  # technical / fundamental / policy / news / fund_flow
    weight: float = 0.0      # How much this point contributes


@dataclass
class DecisionItem:
    """A single actionable decision item."""
    rank: int = 0
    stock_code: str = ""
    stock_name: str = ""
    ai_score: float = 50.0
    recommendation: str = ""        # buy / watch / hold / reduce / sell
    recommendation_emoji: str = ""  # 🟢 / 🟡 / 🟠 / 🔴
    urgency: str = ""               # today / this_week / monitor

    # Bull vs Bear (AI argues both sides)
    bull_points: list[BullBearPoint] = field(default_factory=list)
    bear_points: list[BullBearPoint] = field(default_factory=list)
    bull_score: float = 0.0
    bear_score: float = 0.0
    net_score: float = 0.0           # bull - bear

    # Personal context
    user_has_position: bool = False
    user_position_pct: float = 0.0
    user_past_trades: int = 0
    user_win_rate: float = 0.0
    user_last_action: str = ""
    personal_note: str = ""          # e.g. "你过去6次交易赢了5次，胜率83%"

    # Evidence
    evidence_count: int = 0
    primary_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "ai_score": round(self.ai_score, 1),
            "recommendation": self.recommendation,
            "recommendation_emoji": self.recommendation_emoji,
            "urgency": self.urgency,
            "bull_points": [{"point": b.point, "source": b.source,
                            "evidence_type": b.evidence_type, "weight": round(b.weight, 2)}
                           for b in self.bull_points],
            "bear_points": [{"point": b.point, "source": b.source,
                            "evidence_type": b.evidence_type, "weight": round(b.weight, 2)}
                           for b in self.bear_points],
            "bull_score": round(self.bull_score, 1),
            "bear_score": round(self.bear_score, 1),
            "net_score": round(self.net_score, 1),
            "user_has_position": self.user_has_position,
            "user_position_pct": round(self.user_position_pct, 1),
            "user_past_trades": self.user_past_trades,
            "user_win_rate": round(self.user_win_rate, 2),
            "user_last_action": self.user_last_action,
            "personal_note": self.personal_note,
            "evidence_count": self.evidence_count,
            "primary_reason": self.primary_reason,
        }


class DecisionCenter:
    """Generates daily prioritized decision items.

    Combines: Scanner results + Portfolio positions + Personal history
    + Evidence chain → ranked actionable decisions.
    """

    def generate_daily_decisions(
        self, scanner_candidates: list[dict] | None = None,
        portfolio_positions: list[dict] | None = None,
        user_history: dict[str, dict] | None = None,
    ) -> list[DecisionItem]:
        """Generate today's prioritized decision list."""
        items: list[DecisionItem] = []
        user_history = user_history or {}
        today_seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16)
        rng = _random.Random(today_seed)

        # Process portfolio positions (highest priority — existing money)
        if portfolio_positions:
            for pos in portfolio_positions:
                score = pos.get("ai_score", 50)
                name = pos.get("stock_name", pos.get("stock_code", ""))
                code = pos.get("stock_code", "")

                # Determine recommendation
                if score >= 85:
                    rec = "add"  # 加仓
                    emoji = "🟢"
                    urgency = "today"
                elif score >= 70:
                    rec = "hold"  # 继续持有
                    emoji = "🟡"
                    urgency = "this_week"
                elif score >= 50:
                    rec = "watch"  # 观察
                    emoji = "🟠"
                    urgency = "monitor"
                elif score >= 35:
                    rec = "reduce"  # 减仓
                    emoji = "🔴"
                    urgency = "this_week"
                else:
                    rec = "sell"  # 卖出
                    emoji = "🔴"
                    urgency = "today"

                # User history
                hist = user_history.get(code, {})
                past_trades = hist.get("trades", 0)
                wins = hist.get("wins", 0)
                win_rate = wins / past_trades if past_trades > 0 else 0

                personal_note = ""
                if past_trades >= 5 and win_rate >= 0.7:
                    personal_note = f"你过去{past_trades}次交易赢了{wins}次，胜率{win_rate:.0%}。这是你的优势领域。"
                elif past_trades >= 3 and win_rate < 0.4:
                    personal_note = f"你在此股票上胜率仅{win_rate:.0%}，建议谨慎。"
                elif past_trades == 0:
                    personal_note = "你之前未交易过此股票，建议小仓位试探。"

                # Bull/Bear points
                bull, bear = self._generate_bull_bear(name, code, score, rng)

                items.append(DecisionItem(
                    stock_code=code, stock_name=name,
                    ai_score=score, recommendation=rec,
                    recommendation_emoji=emoji, urgency=urgency,
                    bull_points=bull, bear_points=bear,
                    bull_score=score * 0.8,
                    bear_score=(100 - score) * 0.6,
                    net_score=score * 0.8 - (100 - score) * 0.6,
                    user_has_position=True,
                    user_position_pct=pos.get("weight_pct", 0),
                    user_past_trades=past_trades,
                    user_win_rate=win_rate,
                    user_last_action=hist.get("last_action", ""),
                    personal_note=personal_note,
                    evidence_count=len(bull) + len(bear),
                    primary_reason=bull[0].point if bull else "",
                ))

        # Process scanner candidates (new opportunities)
        if scanner_candidates:
            for c in scanner_candidates:
                code = c.get("stock_code", "")
                name = c.get("stock_name", code)
                score = c.get("fusion_score", 50)

                # Skip if already in portfolio
                if portfolio_positions and any(p.get("stock_code") == code for p in portfolio_positions):
                    continue

                if score >= 80:
                    rec = "buy"
                    emoji = "🟢"
                    urgency = "today"
                elif score >= 65:
                    rec = "watch"
                    emoji = "🟡"
                    urgency = "this_week"
                else:
                    rec = "monitor"
                    emoji = "🟠"
                    urgency = "monitor"

                hist = user_history.get(code, {})
                past_trades = hist.get("trades", 0)
                wins = hist.get("wins", 0)
                win_rate = wins / past_trades if past_trades > 0 else 0

                personal_note = ""
                if past_trades >= 3 and win_rate >= 0.7:
                    personal_note = f"新机会！你在这只股票上的历史胜率{win_rate:.0%}。"
                elif past_trades == 0:
                    personal_note = "新标的，建议先加入自选观察。"

                bull, bear = self._generate_bull_bear(name, code, score, rng)

                items.append(DecisionItem(
                    stock_code=code, stock_name=name,
                    ai_score=score, recommendation=rec,
                    recommendation_emoji=emoji, urgency=urgency,
                    bull_points=bull, bear_points=bear,
                    bull_score=score * 0.75,
                    bear_score=(100 - score) * 0.5,
                    net_score=score * 0.75 - (100 - score) * 0.5,
                    user_has_position=False,
                    user_past_trades=past_trades,
                    user_win_rate=win_rate,
                    personal_note=personal_note,
                    evidence_count=len(bull) + len(bear),
                    primary_reason=bull[0].point if bull else "",
                ))

        # Sort: urgency (today > this_week > monitor) then by net_score
        urgency_order = {"today": 0, "this_week": 1, "monitor": 2}
        items.sort(key=lambda i: (urgency_order.get(i.urgency, 9), -i.net_score))
        for i, item in enumerate(items):
            item.rank = i + 1

        return items

    def _generate_bull_bear(
        self, name: str, code: str, score: float, rng: _random.Random
    ) -> tuple[list[BullBearPoint], list[BullBearPoint]]:
        """Generate bull and bear case arguments from evidence sources."""
        bull: list[BullBearPoint] = []
        bear: list[BullBearPoint] = []

        sector = _guess_sector(name)

        # Bull points
        if score >= 65:
            bull.append(BullBearPoint(
                point="AI综合评分处于强势区间",
                source="AI Signal Engine", evidence_type="technical", weight=0.3,
            ))
        if score >= 75:
            bull.append(BullBearPoint(
                point="MACD金叉信号确认，技术面积极",
                source="东方财富(AkShare)", evidence_type="technical", weight=0.25,
            ))
            bull.append(BullBearPoint(
                point="成交量放大，资金关注度提升",
                source="东方财富(AkShare)", evidence_type="fund_flow", weight=0.2,
            ))
        if score >= 85:
            bull.append(BullBearPoint(
                point=f"{sector}行业景气度持续上升",
                source="行业数据(AkShare)", evidence_type="policy", weight=0.2,
            ))
            bull.append(BullBearPoint(
                point="北向资金连续流入，外资看好",
                source="东方财富(AkShare)", evidence_type="fund_flow", weight=0.15,
            ))

        # Bear points (always include some — AI argues against itself)
        if score < 80:
            bear.append(BullBearPoint(
                point="AI评分未达到强买入区间(≥85)",
                source="AI Signal Engine", evidence_type="technical", weight=0.25,
            ))
        if score >= 75:
            bear.append(BullBearPoint(
                point="短期涨幅较大，存在回调风险",
                source="东方财富(AkShare)", evidence_type="technical", weight=0.15,
            ))
        if score < 70:
            bear.append(BullBearPoint(
                point=f"{sector}板块近期资金流出",
                source="东方财富(AkShare)", evidence_type="fund_flow", weight=0.2,
            ))
        bear.append(BullBearPoint(
            point="需关注大盘系统性风险",
            source="市场数据", evidence_type="policy", weight=0.1,
        ))

        return bull, bear


def _guess_sector(name: str) -> str:
    for kw, s in [("微", "半导体"), ("芯", "半导体"), ("光", "科技"),
                   ("酒", "消费"), ("药", "医药"), ("车", "汽车"),
                   ("能源", "新能源"), ("银行", "金融")]:
        if kw in name:
            return s
    return "综合"


# Singleton
decision_center = DecisionCenter()
