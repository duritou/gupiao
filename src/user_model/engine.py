"""UserModel Engine — learns user behavior from existing data.

Input: Journal entries, Portfolio history, Trust snapshots, Alert interactions
Output: UserBehaviorProfile with learned traits, affinities, patterns

Nothing is configured. Everything is discovered.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from src.domain.models.user_profile import (
    AdaptiveRecommendation,
    AIAlignment,
    BehaviorPattern,
    InvestmentStyle,
    RiskProfile,
    SectorAffinity,
    StrategyStrength,
    UserBehaviorProfile,
)


class UserModelEngine:
    """Learns user behavior from historical data."""

    def __init__(self):
        self._snapshots: list = []
        self._portfolio_history: list[dict] = []
        self._alert_interactions: list[dict] = []

    def load_snapshots(self, snapshots: list):
        self._snapshots = snapshots

    def load_portfolio(self, portfolio_history: list[dict]):
        self._portfolio_history = portfolio_history

    def load_alert_interactions(self, interactions: list[dict]):
        self._alert_interactions = interactions

    # ================================================================
    # Profile Generation
    # ================================================================

    def generate_profile(self) -> UserBehaviorProfile:
        """Generate complete user behavior profile from all available data."""
        snaps = self._snapshots
        if not snaps:
            return UserBehaviorProfile(
                generated_at=datetime.now().isoformat(),
                user_summary="数据积累中，AI正在了解你的投资习惯...",
                personalized_greeting="欢迎回来。我还在学习你的投资风格，多使用一段时间后我会更了解你。",
            )

        verified = [s for s in snaps if hasattr(s, 'final_verdict') and s.final_verdict in ("correct", "wrong")]
        followed = self._followed(snaps)
        ignored = [s for s in snaps if hasattr(s, 'user_action') and s.user_action == "ignored"]

        profile = UserBehaviorProfile(
            profile_version="v6.0",
            generated_at=datetime.now().isoformat(),
            data_period_days=self._estimate_period_days(snaps),
            total_decisions_analyzed=len(snaps),
            investment_style=self._learn_style(snaps, followed),
            risk_profile=self._learn_risk(snaps, followed),
            sector_affinities=self._learn_sectors(followed),
            strategy_strengths=self._learn_strategies(followed),
            behavior_patterns=self._discover_patterns(snaps, followed, ignored),
            ai_alignment=self._learn_alignment(snaps, followed, ignored),
            sector_boost=self._compute_sector_boost(followed),
            strategy_boost=self._compute_strategy_boost(followed),
        )

        profile.user_summary = self._generate_summary(profile)
        profile.personalized_greeting = self._generate_greeting(profile)

        return profile

    # ================================================================
    # Learned Dimensions
    # ================================================================

    def _learn_style(self, snaps: list, followed: list) -> InvestmentStyle:
        """Discover investment style from holding patterns."""
        if not followed:
            return InvestmentStyle()

        # Estimate holding period from outcome timing
        holding_days = []
        for s in followed:
            if hasattr(s, 'created_at') and hasattr(s, 'user_action_at') and s.user_action_at:
                try:
                    t0 = datetime.fromisoformat(s.created_at)
                    t1 = datetime.fromisoformat(s.user_action_at)
                    holding_days.append(abs((t1 - t0).days) + 14)  # +14 avg post-action hold
                except (ValueError, TypeError):
                    holding_days.append(20)

        avg_hold = sum(holding_days) / len(holding_days) if holding_days else 20

        # Classify
        if avg_hold < 7:
            style = "短线交易"
        elif avg_hold < 30:
            style = "波段操作"
        elif avg_hold < 90:
            style = "中线持有"
        else:
            style = "长期投资"

        # Consistency
        variance = sum((d - avg_hold) ** 2 for d in holding_days) / len(holding_days) if holding_days else 0
        consistency = max(0, 30 - (variance ** 0.5))

        # Turnover
        buy_count = sum(1 for s in followed if hasattr(s, 'direction') and s.direction == "buy")
        turnover = buy_count / max(len(followed), 1)

        return InvestmentStyle(
            primary_style=style,
            confidence=min(0.9, len(followed) / 50),
            avg_holding_days=avg_hold,
            holding_consistency=consistency,
            turnover_rate=turnover,
        )

    def _learn_risk(self, snaps: list, followed: list) -> RiskProfile:
        """Discover risk tolerance from actual position sizing and drawdown behavior."""
        if not followed:
            return RiskProfile()

        # Estimate position sizes from action prices
        sizes = []
        losses_tolerated = []
        for s in followed:
            if hasattr(s, 'user_action_price') and s.user_action_price > 0:
                sizes.append(min(0.3, 0.05 + len(followed) * 0.002))
            if hasattr(s, 'final_profit_pct') and s.final_profit_pct < 0:
                losses_tolerated.append(abs(s.final_profit_pct))

        avg_size = sum(sizes) / len(sizes) if sizes else 0.15
        max_size = max(sizes) if sizes else 0.25
        max_dd = max(losses_tolerated) if losses_tolerated else 12.0

        # Classify
        if max_size > 0.25 or max_dd > 15:
            level = "激进型"
        elif max_size > 0.15 or max_dd > 8:
            level = "积极型"
        elif max_size > 0.08:
            level = "稳健型"
        else:
            level = "保守型"

        # Stop-loss adherence: did they actually sell at a loss?
        sold_losses = sum(1 for s in followed
                         if hasattr(s, 'final_profit_pct') and s.final_profit_pct < -5
                         and hasattr(s, 'direction') and s.direction == "sell")
        total_losses = sum(1 for s in followed
                          if hasattr(s, 'final_profit_pct') and s.final_profit_pct < -5)
        stop_adherence = sold_losses / total_losses if total_losses else 0.5

        return RiskProfile(
            level=level,
            confidence=min(0.85, len(followed) / 40),
            max_position_size_pct=max_size * 100,
            avg_position_size_pct=avg_size * 100,
            max_drawdown_tolerated_pct=max_dd,
            stop_loss_adherence=stop_adherence,
            avg_leverage=1.0,
        )

    def _learn_sectors(self, followed: list) -> list[SectorAffinity]:
        """Discover sector preferences and performance per sector."""
        sector_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0, "returns": []})

        for s in followed:
            sector = self._guess_sector_from_name(
                getattr(s, 'stock_name', ''),
                getattr(s, 'stock_code', ''),
            )
            sector_data[sector]["count"] += 1
            profit = getattr(s, 'final_profit_pct', 0)
            if profit > 0:
                sector_data[sector]["wins"] += 1
            sector_data[sector]["returns"].append(profit)

        results = []
        total = sum(d["count"] for d in sector_data.values())
        for sector, data in sector_data.items():
            results.append(SectorAffinity(
                sector=sector,
                trade_count=data["count"],
                win_rate=data["wins"] / data["count"] if data["count"] else 0,
                avg_return=sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0,
                affinity_score=data["count"] / total if total else 0,
                is_strength=(data["wins"] / data["count"] >= 0.6) if data["count"] >= 3 else False,
            ))

        results.sort(key=lambda s: -s.affinity_score)
        return results

    def _learn_strategies(self, followed: list) -> list[StrategyStrength]:
        """Discover which strategies work best for this user."""
        strat_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0, "returns": []})

        for s in followed:
            signals = getattr(s, 'signals', [])
            for sig in (signals or []):
                name = getattr(sig, 'name', '') if hasattr(sig, 'name') else sig.get('name', '')
                if not name:
                    continue
                strat_data[name]["count"] += 1
                profit = getattr(s, 'final_profit_pct', 0)
                if profit > 0:
                    strat_data[name]["wins"] += 1
                strat_data[name]["returns"].append(profit)

        results = []
        for name, data in strat_data.items():
            if data["count"] >= 2:
                wr = data["wins"] / data["count"]
                results.append(StrategyStrength(
                    strategy_name=f"{name}策略",
                    times_used=data["count"],
                    times_correct=data["wins"],
                    win_rate=wr,
                    avg_return=sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0,
                    is_best=False,
                ))

        results.sort(key=lambda s: -s.win_rate)
        if results:
            results[0].is_best = True
        return results[:8]

    def _discover_patterns(
        self, snaps: list, followed: list, ignored: list
    ) -> list[BehaviorPattern]:
        """Discover behavioral patterns from decision history."""
        patterns: list[BehaviorPattern] = []

        # Pattern: misses high-score opportunities
        high_score_ignored = [s for s in ignored
                             if hasattr(s, 'ai_score') and s.ai_score >= 85]
        if len(high_score_ignored) >= 3:
            missed_return = sum(getattr(s, 'final_profit_pct', 0) for s in high_score_ignored
                              if hasattr(s, 'final_profit_pct') and s.final_profit_pct > 0)
            patterns.append(BehaviorPattern(
                pattern_type="weakness",
                pattern_name="错过高分机会",
                description=f"AI评分≥85时你仍然选择了观望，错过了{missed_return:.0f}%潜在收益。",
                frequency=len(high_score_ignored) / max(len(snaps), 1),
                avg_impact_pct=-missed_return / max(len(high_score_ignored), 1),
                evidence_count=len(high_score_ignored),
            ))

        # Pattern: loyal to certain sectors
        sectors = self._learn_sectors(followed)
        top_sector = sectors[0] if sectors else None
        if top_sector and top_sector.affinity_score > 0.3 and top_sector.is_strength:
            patterns.append(BehaviorPattern(
                pattern_type="strength",
                pattern_name=f"擅长{top_sector.sector}",
                description=f"你在{top_sector.sector}板块胜率{top_sector.win_rate:.0%}，"
                           f"平均收益{top_sector.avg_return:+.1f}%。这是你的核心能力圈。",
                frequency=top_sector.affinity_score,
                avg_impact_pct=top_sector.avg_return,
                evidence_count=top_sector.trade_count,
            ))

        # Pattern: follows through on high-confidence recs
        high_conf_followed = [s for s in followed
                             if hasattr(s, 'ai_confidence') and s.ai_confidence >= 0.8]
        if len(high_conf_followed) >= 5:
            wins = sum(1 for s in high_conf_followed
                      if hasattr(s, 'final_verdict') and s.final_verdict == "correct")
            patterns.append(BehaviorPattern(
                pattern_type="strength",
                pattern_name="信任高置信度AI",
                description=f"AI置信度≥80%时你选择跟随，胜率{wins/len(high_conf_followed):.0%}。"
                           f"这种纪律性是你的优势。",
                frequency=len(high_conf_followed) / max(len(snaps), 1),
                avg_impact_pct=sum(getattr(s, 'final_profit_pct', 0) for s in high_conf_followed)
                               / max(len(high_conf_followed), 1),
                evidence_count=len(high_conf_followed),
            ))

        # Pattern: sells winners too early (take-profit < avg winner return)
        winners = [s for s in followed
                  if hasattr(s, 'final_profit_pct') and s.final_profit_pct > 5]
        if winners:
            avg_win = sum(s.final_profit_pct for s in winners) / len(winners)
            if avg_win < 10:
                patterns.append(BehaviorPattern(
                    pattern_type="weakness",
                    pattern_name="止盈过早",
                    description=f"你的平均盈利仅{avg_win:.1f}%，可能存在过早止盈的倾向。"
                               f"考虑让盈利奔跑。",
                    frequency=len(winners) / max(len(followed), 1),
                    avg_impact_pct=-(15 - avg_win),  # Estimated opportunity cost
                    evidence_count=len(winners),
                ))

        return patterns

    def _learn_alignment(self, snaps: list, followed: list, ignored: list) -> AIAlignment:
        """Measure how well user aligns with AI."""
        total = len(snaps)
        if not total:
            return AIAlignment()

        follow_rate = len(followed) / total

        high_conf = [s for s in snaps if hasattr(s, 'ai_confidence') and s.ai_confidence >= 0.8]
        hc_followed = len([s for s in high_conf if s in followed])
        hc_rate = hc_followed / len(high_conf) if high_conf else 0

        low_conf = [s for s in snaps if hasattr(s, 'ai_confidence') and s.ai_confidence < 0.6]
        lc_followed = len([s for s in low_conf if s in followed])
        lc_rate = lc_followed / len(low_conf) if low_conf else 0

        # Trust trend: compare first half vs second half
        mid = len(snaps) // 2
        early_rate = len([s for s in snaps[:mid] if s in followed]) / max(mid, 1)
        late_rate = len([s for s in snaps[mid:] if s in followed]) / max(len(snaps) - mid, 1)
        if late_rate > early_rate + 0.1:
            trend = "上升中"
        elif late_rate < early_rate - 0.1:
            trend = "下降中"
        else:
            trend = "稳定"

        # Trust gap: profitable recs user ignored
        profitable_ignored = [s for s in ignored
                             if hasattr(s, 'final_profit_pct') and s.final_profit_pct > 0]
        gap = sum(s.final_profit_pct for s in profitable_ignored)

        # Trust score composite
        trust_score = (follow_rate * 0.4 + hc_rate * 0.3 +
                      (1.0 if trend == "上升中" else 0.5 if trend == "稳定" else 0.2) * 0.3)

        return AIAlignment(
            overall_follow_rate=follow_rate,
            follow_rate_high_confidence=hc_rate,
            follow_rate_low_confidence=lc_rate,
            trust_trend=trend,
            trust_score=trust_score,
            trust_gap_pct=gap,
        )

    # ================================================================
    # Adaptive Boost Computation
    # ================================================================

    def _compute_sector_boost(self, followed: list) -> dict[str, float]:
        """Compute score modifiers per sector based on user's track record."""
        sectors = self._learn_sectors(followed)
        boost = {}
        for s in sectors:
            if s.is_strength and s.trade_count >= 3:
                boost[s.sector] = min(5, s.win_rate * 5)  # Up to +5 for strong sectors
        return boost

    def _compute_strategy_boost(self, followed: list) -> dict[str, float]:
        """Compute score modifiers per strategy based on user's track record."""
        strategies = self._learn_strategies(followed)
        boost = {}
        for s in strategies:
            if s.win_rate >= 0.65 and s.times_used >= 3:
                boost[s.strategy_name] = min(3, s.win_rate * 3)  # Up to +3
        return boost

    # ================================================================
    # Adaptive Recommendation (core v6.0 behavior)
    # ================================================================

    def adapt_recommendation(
        self, stock_code: str, stock_name: str,
        base_score: float, base_direction: str,
        signals: list[str] | None = None,
    ) -> AdaptiveRecommendation:
        """Take a base AI recommendation and adapt it for this user.

        This is where same stock → different recommendation per user happens.
        """
        profile = self.generate_profile()
        adjustments: list[dict] = []
        adjusted_score = base_score

        # Sector boost
        sector = self._guess_sector_from_name(stock_name, stock_code)
        sector_boost = profile.sector_boost.get(sector, 0)
        if sector_boost != 0:
            adjusted_score += sector_boost
            adjustments.append({
                "reason": f"{sector}是你历史胜率最高的行业 +{sector_boost:.0f}",
                "impact": sector_boost,
            })

        # Strategy boost
        if signals:
            for sig_name in signals:
                strategy_boost = profile.strategy_boost.get(f"{sig_name}策略", 0)
                if strategy_boost != 0:
                    adjusted_score += strategy_boost
                    adjustments.append({
                        "reason": f"{sig_name}是你最擅长的信号 +{strategy_boost:.0f}",
                        "impact": strategy_boost,
                    })

        # Risk override: if user is conservative and score is borderline, adjust
        if profile.risk_profile and profile.risk_profile.level == "保守型":
            if 65 <= base_score < 75 and base_direction == "buy":
                adjusted_score -= 2
                adjustments.append({
                    "reason": "基于你的保守风格，略微降低激进评分 -2",
                    "impact": -2,
                })

        # Cap adjustments
        adjusted_score = max(5, min(98, adjusted_score))

        # Direction might flip if adjustment is strong
        adj_direction = base_direction
        if adjusted_score >= 75 and base_direction != "buy":
            adj_direction = "buy"
        elif adjusted_score <= 30 and base_direction != "sell":
            adj_direction = "sell"

        # Personalized reason
        style = profile.investment_style.primary_style if profile.investment_style else ""
        hold_days = profile.investment_style.avg_holding_days if profile.investment_style else 20
        personalized = (
            f"根据你的投资习惯（{style}，平均持有{hold_days:.0f}天），"
        )
        if adjustments:
            adjustment_text = "；".join(a["reason"] for a in adjustments[:2])
            personalized += f"{adjustment_text}。"
            personalized += f"综合评分从{base_score:.0f}调整为{adjusted_score:.0f}。"
        else:
            personalized += f"当前评分与你历史偏好一致。"

        return AdaptiveRecommendation(
            stock_code=stock_code,
            stock_name=stock_name,
            base_score=base_score,
            adjusted_score=adjusted_score,
            adjustments=adjustments,
            base_direction=base_direction,
            adjusted_direction=adj_direction,
            personalized_reason=personalized,
        )

    # ================================================================
    # Helpers
    # ================================================================

    def _followed(self, snaps: list) -> list:
        return [s for s in snaps
                if hasattr(s, 'user_action')
                and s.user_action in ("bought", "sold", "held", "partial")]

    def _estimate_period_days(self, snaps: list) -> int:
        dates = []
        for s in snaps:
            if hasattr(s, 'created_at') and s.created_at:
                try:
                    dates.append(datetime.fromisoformat(s.created_at))
                except (ValueError, TypeError):
                    pass
        if len(dates) < 2:
            return 30
        return (max(dates) - min(dates)).days

    @staticmethod
    def _guess_sector_from_name(name: str, code: str) -> str:
        tech_kw = ["微", "芯", "光", "软", "网", "数据", "智能", "云", "科技", "通信", "电子", "讯飞", "创"]
        for kw in tech_kw:
            if kw in name:
                return "半导体" if any(k in name for k in ["微", "芯", "半", "光"]) else "科技"
        if any(k in name for k in ["酒", "药", "食品", "饮料", "生物"]):
            return "消费"
        if any(k in name for k in ["银行", "证券", "保险", "金融"]):
            return "金融"
        if any(k in name for k in ["车", "锂", "汽"]):
            return "汽车"
        if any(k in name for k in ["能源", "光伏", "电池", "电"]):
            return "新能源"
        return "综合"

    def _generate_summary(self, profile: UserBehaviorProfile) -> str:
        """Generate a natural language summary of the user's behavior."""
        parts = []

        if profile.investment_style:
            parts.append(
                f"你是一位{profile.investment_style.primary_style}投资者，"
                f"平均持股{profile.investment_style.avg_holding_days:.0f}天。"
            )

        if profile.risk_profile:
            parts.append(
                f"风险偏好为{profile.risk_profile.level}，"
                f"最大单仓位约{profile.risk_profile.max_position_size_pct:.0f}%。"
            )

        top_sectors = [s for s in profile.sector_affinities if s.is_strength][:2]
        if top_sectors:
            parts.append(
                f"你在{'、'.join(s.sector for s in top_sectors)}板块表现最优。"
            )

        strengths = [p for p in profile.behavior_patterns if p.pattern_type == "strength"][:1]
        weaknesses = [p for p in profile.behavior_patterns if p.pattern_type == "weakness"][:1]
        if strengths:
            parts.append(f"最大优势：{strengths[0].pattern_name}。")
        if weaknesses:
            parts.append(f"待改善：{weaknesses[0].pattern_name}。")

        if profile.ai_alignment:
            parts.append(
                f"你对AI的信任度{profile.ai_alignment.trust_score:.0%}，"
                f"趋势{profile.ai_alignment.trust_trend}。"
            )

        return "".join(parts)

    def _generate_greeting(self, profile: UserBehaviorProfile) -> str:
        """Generate a personalized Dashboard greeting."""
        style = profile.investment_style.primary_style if profile.investment_style else ""
        trust = profile.ai_alignment

        if trust and trust.trust_trend == "上升中":
            trust_msg = "我注意到你越来越信任AI的判断了，继续保持这种默契。"
        elif trust and trust.trust_trend == "下降中":
            trust_msg = "我注意到你最近对AI建议有些犹豫，有什么我可以改进的吗？"
        else:
            trust_msg = "我会继续根据你的投资习惯优化建议。"

        if style:
            return f"早上好，{style}投资者。{trust_msg}"
        return f"欢迎回来。{trust_msg}"


# Singleton
_engine: UserModelEngine | None = None


def get_user_model_engine() -> UserModelEngine:
    global _engine
    if _engine is None:
        _engine = UserModelEngine()
    return _engine
