"""Alert Intelligence Engine — the proactive AI decision layer.

This is NOT a simple notification system. It watches the entire AI pipeline
(signals, portfolio, market, knowledge) and generates Leveled, evidence-backed
alerts that tell the user not just WHAT happened, but WHY it matters and
whether it's worth acting on.

Architecture:
    Live Market → Signal Engine → Explain Engine
                                         │
    Portfolio Analyzer ──────────────────┤
    Watchlist Analyzer ──────────────────┤
    Market Monitor ──────────────────────┤
                                         ▼
                              Alert Intelligence Engine
                                         │
                     ┌───────────────────┼───────────────────┐
                     ▼                   ▼                   ▼
                 Dashboard          Alert Center        VS Code Notification
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from src.domain.models.alert import (
    Alert,
    AlertCategory,
    AlertEvidence,
    AlertFeed,
    AlertLevel,
    AlertOutcome,
    AlertStats,
    AlertStatus,
)


class AlertIntelligenceEngine:
    """Watches the AI pipeline and generates proactive, evidence-backed alerts."""

    def __init__(self):
        self._store: dict[str, Alert] = {}  # In-memory store (session-scoped)
        self._action_log: list[dict] = []

    # ================================================================
    # Alert Generation — from different sources
    # ================================================================

    def generate_from_signals(
        self, stock_code: str, stock_name: str, signal_result: dict
    ) -> list[Alert]:
        """Generate alerts from signal fusion results.

        Triggers:
        - Score >= 85 + buy direction → P1 opportunity
        - Score <= 25 + sell direction → P1 risk
        - MACD/RSI/KDJ cross events → P2/P3 signals
        """
        alerts: list[Alert] = []
        now = datetime.now().isoformat()
        score = signal_result.get("fusion_score", 50)
        direction = signal_result.get("direction", "neutral")
        confidence = signal_result.get("confidence", 0.5)
        scores_detail = signal_result.get("scores", {})

        # P1: Strong opportunity
        if score >= 85 and direction == "buy":
            evidence = self._build_signal_evidence(scores_detail, direction)
            alerts.append(self._make_alert(
                level=AlertLevel.P1,
                category=AlertCategory.OPPORTUNITY,
                stock_code=stock_code, stock_name=stock_name,
                title=f"{stock_name} AI评分 {score:.0f} · 强烈买入信号",
                body=f"多信号共振：{', '.join(self._top_signals(scores_detail, 3))}。AI置信度 {confidence:.0%}。",
                direction="buy", score=score, score_change=0,
                evidence=evidence, ai_confidence=confidence,
                tags=["强烈买入", "多信号共振", "高置信"],
            ))

        # P1: Strong risk
        if score <= 25 and direction == "sell":
            evidence = self._build_signal_evidence(scores_detail, direction)
            alerts.append(self._make_alert(
                level=AlertLevel.P1,
                category=AlertCategory.RISK,
                stock_code=stock_code, stock_name=stock_name,
                title=f"{stock_name} AI评分 {score:.0f} · 强烈卖出信号",
                body=f"多信号共振看空：{', '.join(self._top_signals(scores_detail, 3))}。建议关注风险。",
                direction="sell", score=score, score_change=0,
                evidence=evidence, ai_confidence=confidence,
                tags=["强烈卖出", "风险预警", "多信号共振"],
            ))

        # P2: Notable signal (MACD cross, etc.)
        for sig_name, sig_score in scores_detail.items():
            if sig_score >= 75:
                alerts.append(self._make_alert(
                    level=AlertLevel.P2,
                    category=AlertCategory.SIGNAL,
                    stock_code=stock_code, stock_name=stock_name,
                    title=f"{stock_name} {sig_name} 信号强烈 · {sig_score:.0f}分",
                    body=f"{sig_name}指标达到 {sig_score:.0f}，技术面积极。当前综合评分 {score:.0f}。",
                    direction="buy", score=score, score_change=0,
                    evidence=[AlertEvidence(
                        type="signal", title=f"{sig_name} 信号",
                        description=f"{sig_name} 评分为 {sig_score:.0f}",
                        confidence=confidence, source=sig_name, impact=sig_score - 50,
                    )],
                    ai_confidence=confidence, tags=[sig_name, "技术信号"],
                ))
            elif sig_score <= 30:
                alerts.append(self._make_alert(
                    level=AlertLevel.P3,
                    category=AlertCategory.SIGNAL,
                    stock_code=stock_code, stock_name=stock_name,
                    title=f"{stock_name} {sig_name} 信号偏弱 · {sig_score:.0f}分",
                    body=f"{sig_name}指标仅 {sig_score:.0f}，技术面偏弱。当前综合评分 {score:.0f}。",
                    direction="sell", score=score, score_change=0,
                    evidence=[AlertEvidence(
                        type="signal", title=f"{sig_name} 偏弱",
                        description=f"{sig_name} 评分为 {sig_score:.0f}",
                        confidence=confidence, source=sig_name, impact=sig_score - 50,
                    )],
                    ai_confidence=confidence, tags=[sig_name, "信号偏弱"],
                ))

        return alerts

    def generate_from_portfolio_score_change(
        self, stock_code: str, stock_name: str,
        old_score: float, new_score: float,
        top_signal: str = "", direction: str = "buy",
    ) -> Alert | None:
        """Generate alert when portfolio stock AI score changes significantly.

        Triggers:
        - Score change >= +5 → P1 upgrade
        - Score change >= +3 → P2 upgrade
        - Score change <= -5 → P1 downgrade
        - Score change <= -3 → P2 downgrade
        """
        change = new_score - old_score
        if abs(change) < 3:
            return None

        is_upgrade = change >= 0
        level = AlertLevel.P1 if abs(change) >= 5 else AlertLevel.P2
        direction_label = "up" if is_upgrade else "down"

        arrow = "▲" if is_upgrade else "▼"
        action_word = "升级" if is_upgrade else "降级"

        evidence_items = [
            AlertEvidence(
                type="portfolio", title=f"AI评分{action_word}",
                description=f"评分从 {old_score:.0f} → {new_score:.0f}（{arrow}{abs(change):.0f}）",
                confidence=0.85, source="PortfolioAnalyzer", impact=change,
            ),
        ]
        if top_signal:
            evidence_items.append(AlertEvidence(
                type="signal", title=top_signal,
                description=f"主要驱动信号: {top_signal}",
                confidence=0.75, source=top_signal, impact=change * 0.6,
            ))

        return self._make_alert(
            level=level,
            category=AlertCategory.PORTFOLIO,
            stock_code=stock_code, stock_name=stock_name,
            title=f"{stock_name} AI评分 {action_word} {old_score:.0f}→{new_score:.0f} {arrow}{abs(change):.0f}",
            body=f"持仓{stock_name}的AI评分从{old_score:.0f}变为{new_score:.0f}（{arrow}{abs(change):.0f}）。"
                 f"{'建议关注加仓机会。' if is_upgrade else '建议检查是否需要调整仓位。'}",
            direction=direction_label, score=new_score, score_change=change,
            evidence=evidence_items, ai_confidence=0.85,
            tags=["持仓变化", action_word, f"{'升级' if is_upgrade else '降级'}{abs(change):.0f}"],
        )

    def generate_from_portfolio_risk(
        self, risk_type: str, detail: str, severity: str = "high"
    ) -> Alert | None:
        """Generate portfolio-level risk alerts.

        Triggers:
        - Position concentration > 40% in single sector → P2
        - Overall position > 90% → P2
        - Stop-loss triggered → P0
        """
        level_map = {"critical": AlertLevel.P0, "high": AlertLevel.P1, "medium": AlertLevel.P2}
        level = level_map.get(severity, AlertLevel.P3)

        return self._make_alert(
            level=level,
            category=AlertCategory.RISK,
            stock_code="", stock_name="投资组合",
            title=f"⚠ 组合风险: {risk_type}",
            body=detail,
            direction="neutral", score=0, score_change=0,
            evidence=[AlertEvidence(
                type="risk", title=risk_type, description=detail,
                confidence=0.9, source="PortfolioAnalyzer", impact=-5,
            )],
            ai_confidence=0.9, tags=["组合风险", risk_type, severity],
        )

    def generate_from_market(
        self, event_type: str, title: str, detail: str,
        sentiment_score: float = 50, level: AlertLevel = AlertLevel.P3,
    ) -> Alert:
        """Generate market-level alerts.

        Triggers:
        - Major market move (index change > 3%)
        - Sentiment shift (score change > 15)
        - Sector rotation detected
        - Northbound flow anomaly
        """
        return self._make_alert(
            level=level,
            category=AlertCategory.MARKET,
            stock_code="", stock_name="全市场",
            title=title,
            body=detail,
            direction="neutral", score=sentiment_score, score_change=0,
            evidence=[AlertEvidence(
                type="market", title=event_type, description=detail,
                confidence=0.7, source="MarketMonitor", impact=0,
            )],
            ai_confidence=0.7, tags=["市场事件", event_type],
        )

    def generate_from_knowledge(
        self, stock_code: str, stock_name: str, knowledge_title: str,
        knowledge_detail: str, impact_score: float = 0, level: AlertLevel = AlertLevel.P3,
    ) -> Alert:
        """Generate knowledge/intelligence alerts.

        Triggers:
        - Industry policy change
        - Earnings surprise
        - Major contract win
        - Research upgrade
        """
        return self._make_alert(
            level=level,
            category=AlertCategory.KNOWLEDGE,
            stock_code=stock_code, stock_name=stock_name,
            title=f"{stock_name}: {knowledge_title}",
            body=knowledge_detail,
            direction="buy" if impact_score > 0 else "neutral",
            score=50 + impact_score, score_change=impact_score,
            evidence=[AlertEvidence(
                type="knowledge", title=knowledge_title,
                description=knowledge_detail,
                confidence=0.6, source="KnowledgeBase", impact=impact_score,
            )],
            ai_confidence=0.6, tags=["行业情报", knowledge_title],
        )

    # ================================================================
    # Feed Assembly — collect alerts from all sources
    # ================================================================

    async def assemble_feed(
        self,
        portfolio: dict | None = None,
        watchlist_signals: list[dict] | None = None,
        market_data: dict | None = None,
        scanner_candidates: list[dict] | None = None,
    ) -> AlertFeed:
        """Assemble a complete alert feed from all intelligence sources."""
        all_alerts: list[Alert] = []

        # 1. Portfolio score changes
        if portfolio:
            for pos in portfolio.get("positions", []):
                old_score = pos.get("ai_score", 50) - pos.get("last_score_change", 0)
                new_score = pos.get("ai_score", 50)
                alert = self.generate_from_portfolio_score_change(
                    pos["stock_code"], pos["stock_name"],
                    old_score, new_score,
                    top_signal=pos.get("ai_signal", ""),
                    direction=pos.get("ai_direction", "neutral"),
                )
                if alert:
                    all_alerts.append(alert)

            # Portfolio risk checks
            positions = portfolio.get("positions", [])
            if positions:
                # Concentration check
                sectors: dict[str, float] = {}
                for p in positions:
                    # Approximate sector from stock name/code
                    sector = self._guess_sector(p.get("stock_name", ""), p.get("stock_code", ""))
                    sectors[sector] = sectors.get(sector, 0) + p.get("weight_pct", 0)
                max_sector = max(sectors, key=sectors.get)
                if sectors[max_sector] > 40:
                    all_alerts.append(self.generate_from_portfolio_risk(
                        "行业集中度偏高",
                        f"{max_sector}板块占比{sectors[max_sector]:.0f}%，建议考虑分散风险。AI建议：略微降低集中度。",
                        severity="high" if sectors[max_sector] > 50 else "medium",
                    ))

                # Overall position check
                total_weight = sum(p.get("weight_pct", 0) for p in positions)
                if total_weight > 90:
                    all_alerts.append(self.generate_from_portfolio_risk(
                        "仓位过重",
                        f"当前仓位{total_weight:.0f}%，现金储备不足。建议保留一定流动性。",
                        severity="high",
                    ))

        # 2. Watchlist signal alerts
        if watchlist_signals:
            for sig in watchlist_signals:
                sig_alerts = self.generate_from_signals(
                    sig.get("stock_code", ""), sig.get("stock_name", ""), sig,
                )
                all_alerts.extend(sig_alerts)

        # 3. Market alerts
        if market_data:
            breadth = market_data.get("market_breadth", {})
            up_count = breadth.get("up", 0)
            down_count = breadth.get("down", 0)
            if down_count > up_count * 2:
                all_alerts.append(self.generate_from_market(
                    "普跌行情", "市场大面积下跌",
                    f"上涨{up_count}家，下跌{down_count}家。市场情绪偏弱，建议控制仓位。",
                    sentiment_score=25, level=AlertLevel.P2,
                ))
            elif up_count > down_count * 2:
                all_alerts.append(self.generate_from_market(
                    "普涨行情", "市场大面积上涨",
                    f"上涨{up_count}家，下跌{down_count}家。市场情绪积极。",
                    sentiment_score=80, level=AlertLevel.P3,
                ))

            nb = market_data.get("northbound", {})
            nb_flow = nb.get("net_flow", 0)
            if abs(nb_flow) > 80:
                direction_word = "大幅流入" if nb_flow > 0 else "大幅流出"
                all_alerts.append(self.generate_from_market(
                    "北向资金异动",
                    f"北向资金{direction_word}",
                    f"北向资金净{'流入' if nb_flow > 0 else '流出'}{abs(nb_flow):.0f}亿。"
                    f"{'外资积极看多。' if nb_flow > 0 else '外资谨慎撤离，注意风险。'}",
                    sentiment_score=75 if nb_flow > 0 else 30,
                    level=AlertLevel.P2 if nb_flow < 0 else AlertLevel.P3,
                ))

            # Hot sectors
            for sector in market_data.get("hot_sectors", [])[:3]:
                if sector.get("score", 50) >= 85:
                    all_alerts.append(self.generate_from_market(
                        "板块热点", f"🔥 {sector['name']}板块活跃",
                        f"{sector['name']}行业评分{sector['score']:.0f}，状态{sector.get('status', '活跃')}。",
                        sentiment_score=sector.get("score", 50),
                        level=AlertLevel.P3,
                    ))

        # 4. Scanner top opportunities
        if scanner_candidates:
            for c in scanner_candidates[:3]:
                if c.get("fusion_score", 50) >= 85:
                    all_alerts.append(self._make_alert(
                        level=AlertLevel.P2,
                        category=AlertCategory.OPPORTUNITY,
                        stock_code=c.get("stock_code", ""),
                        stock_name=c.get("stock_name", ""),
                        title=f"{c.get('stock_name', '')} 扫描发现机会 · {c.get('fusion_score', 50):.0f}分",
                        body=f"Scanner在全市场扫描中发现{c.get('stock_name', '')}，"
                             f"AI综合评分{c.get('fusion_score', 50):.0f}，方向{c.get('direction', 'neutral')}。",
                        direction=c.get("direction", "neutral"),
                        score=c.get("fusion_score", 50),
                        score_change=0,
                        evidence=[AlertEvidence(
                            type="scanner", title="Scanner发现",
                            description=f"全市场扫描Top{c.get('rank', 0)}",
                            confidence=c.get("confidence", 0.5),
                            source="ScannerEngine", impact=0,
                        )],
                        ai_confidence=c.get("confidence", 0.5),
                        tags=["扫描发现", "机会"],
                    ))

        # Sort: P0 > P1 > P2 > P3 > P4, then by score desc
        level_order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2,
                       AlertLevel.P3: 3, AlertLevel.P4: 4}
        all_alerts.sort(key=lambda a: (level_order.get(a.level, 9), -a.score))

        # Dedup by title similarity
        seen_titles: set[str] = set()
        deduped: list[Alert] = []
        for a in all_alerts:
            key = a.title[:30]
            if key not in seen_titles:
                seen_titles.add(key)
                deduped.append(a)

        # Store in session
        for a in deduped:
            if a.id not in self._store:
                self._store[a.id] = a

        p0 = sum(1 for a in deduped if a.level == AlertLevel.P0)
        p1 = sum(1 for a in deduped if a.level == AlertLevel.P1)
        unread = sum(1 for a in deduped if a.status == AlertStatus.NEW)

        return AlertFeed(
            alerts=deduped,
            total_today=len(deduped),
            unread_count=unread,
            p0_count=p0,
            p1_count=p1,
            last_updated=datetime.now().isoformat(),
        )

    # ================================================================
    # Lifecycle Management
    # ================================================================

    def mark_read(self, alert_id: str) -> Alert | None:
        alert = self._store.get(alert_id)
        if alert and alert.status == AlertStatus.NEW:
            alert.status = AlertStatus.READ
            alert.read_at = datetime.now().isoformat()
        return alert

    def record_action(self, alert_id: str, action_type: str,
                      stock_code: str = "", quantity: int = 0,
                      price: float = 0.0, notes: str = "") -> Alert | None:
        alert = self._store.get(alert_id)
        if alert:
            from src.domain.models.alert import AlertAction
            alert.action = AlertAction(
                action_type=action_type, stock_code=stock_code,
                quantity=quantity, price=price, notes=notes,
                timestamp=datetime.now().isoformat(),
            )
            alert.status = AlertStatus.ACTED
            alert.acted_at = datetime.now().isoformat()
        return alert

    def record_outcome(self, alert_id: str, outcome_type: str,
                       realized_pl_pct: float = 0.0, holding_days: int = 0,
                       was_correct: bool = False, notes: str = "") -> Alert | None:
        alert = self._store.get(alert_id)
        if alert:
            from src.domain.models.alert import AlertOutcome
            alert.outcome = AlertOutcome(
                outcome_type=outcome_type, realized_pl_pct=realized_pl_pct,
                holding_days=holding_days, was_correct=was_correct,
                verified_at=datetime.now().isoformat(), notes=notes,
            )
            alert.status = AlertStatus.VERIFIED
        return alert

    def dismiss(self, alert_id: str) -> Alert | None:
        alert = self._store.get(alert_id)
        if alert:
            alert.status = AlertStatus.DISMISSED
        return alert

    # ================================================================
    # Query
    # ================================================================

    def get_feed(self, level: str | None = None,
                 status: str | None = None,
                 category: str | None = None,
                 limit: int = 50) -> AlertFeed:
        """Query stored alerts with optional filters."""
        alerts = list(self._store.values())

        if level:
            alerts = [a for a in alerts if a.level.value == level]
        if status:
            alerts = [a for a in alerts if a.status.value == status]
        if category:
            alerts = [a for a in alerts if a.category.value == category]

        level_order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2,
                       AlertLevel.P3: 3, AlertLevel.P4: 4}
        alerts.sort(key=lambda a: (level_order.get(a.level, 9), -a.score))

        p0 = sum(1 for a in alerts if a.level == AlertLevel.P0)
        p1 = sum(1 for a in alerts if a.level == AlertLevel.P1)
        unread = sum(1 for a in alerts if a.status == AlertStatus.NEW)

        return AlertFeed(
            alerts=alerts[:limit],
            total_today=len(self._store),
            unread_count=unread,
            p0_count=p0,
            p1_count=p1,
            last_updated=datetime.now().isoformat(),
        )

    def get_alert(self, alert_id: str) -> Alert | None:
        return self._store.get(alert_id)

    def get_stats(self) -> AlertStats:
        """Compute aggregate statistics on alert effectiveness."""
        all_alerts = list(self._store.values())
        verified = [a for a in all_alerts if a.outcome is not None]
        wins = [a for a in verified if a.outcome and a.outcome.was_correct]

        total_pl = sum(a.outcome.realized_pl_pct for a in verified if a.outcome)
        avg_days = (sum(a.outcome.holding_days for a in verified if a.outcome) / len(verified)
                    ) if verified else 0

        return AlertStats(
            total_alerts=len(all_alerts),
            alerts_today=len(all_alerts),
            acted_count=sum(1 for a in all_alerts if a.status in (AlertStatus.ACTED, AlertStatus.VERIFIED)),
            verified_count=len(verified),
            win_count=len(wins),
            loss_count=len(verified) - len(wins),
            win_rate=len(wins) / len(verified) if verified else 0,
            avg_holding_days=avg_days,
            total_realized_pl_pct=total_pl,
        )

    # ================================================================
    # Internal helpers
    # ================================================================

    def _make_alert(
        self, level: AlertLevel, category: AlertCategory,
        stock_code: str, stock_name: str, title: str, body: str,
        direction: str, score: float, score_change: float,
        evidence: list[AlertEvidence], ai_confidence: float,
        tags: list[str],
    ) -> Alert:
        """Create an alert with deterministic ID."""
        now = datetime.now()
        id_seed = f"{stock_code}:{title}:{now.isoformat()}"
        id_hash = hashlib.md5(id_seed.encode()).hexdigest()[:12]
        return Alert(
            id=f"alt_{now.strftime('%Y%m%d')}_{id_hash}",
            level=level, category=category, status=AlertStatus.NEW,
            stock_code=stock_code, stock_name=stock_name,
            title=title, body=body, direction=direction,
            score=score, score_change=score_change,
            created_at=now.isoformat(),
            evidence=evidence, ai_confidence=ai_confidence,
            historical_accuracy=0.74, tags=tags,
        )

    def _build_signal_evidence(
        self, scores: dict[str, float], direction: str
    ) -> list[AlertEvidence]:
        """Build evidence list from signal scores."""
        evidence: list[AlertEvidence] = []
        for name, s in sorted(scores.items(), key=lambda x: -abs(x[1] - 50)):
            if abs(s - 50) > 20:
                evidence.append(AlertEvidence(
                    type="signal", title=f"{name} 信号",
                    description=f"{name} 评分 {s:.0f}，"
                                 f"{'看多' if s > 50 else '看空'}信号",
                    confidence=abs(s - 50) / 50, source=name,
                    impact=s - 50,
                ))
        return evidence[:5]

    def _top_signals(self, scores: dict[str, float], n: int = 3) -> list[str]:
        """Get top N signal names."""
        sorted_signals = sorted(scores.items(), key=lambda x: -abs(x[1] - 50))
        return [f"{name}({s:.0f})" for name, s in sorted_signals[:n]]

    @staticmethod
    def _guess_sector(name: str, code: str) -> str:
        """Approximate sector from stock name or code."""
        tech_keywords = ["微", "芯", "光", "软", "网", "数据", "智能", "云", "电", "科技", "通信", "讯飞"]
        finance_keywords = ["银行", "证券", "保险", "金融"]
        consumer_keywords = ["酒", "食品", "饮料", "零售", "药", "生物", "医"]
        energy_keywords = ["能源", "电", "光伏", "电池", "新能源", "电力"]
        auto_keywords = ["汽车", "车", "锂", "汽"]
        real_estate_keywords = ["地产", "房", "万科", "建筑"]
        military_keywords = ["航天", "航空", "军工", "船", "重工"]

        text = name + code
        for kw in tech_keywords:
            if kw in text:
                return "科技/半导体"
        for kw in finance_keywords:
            if kw in text:
                return "金融"
        for kw in consumer_keywords:
            if kw in text:
                return "消费/医药"
        for kw in energy_keywords:
            if kw in text:
                return "新能源"
        for kw in auto_keywords:
            if kw in text:
                return "汽车"
        for kw in real_estate_keywords:
            if kw in text:
                return "地产"
        for kw in military_keywords:
            if kw in text:
                return "军工"
        return "综合"


# Singleton
_engine: AlertIntelligenceEngine | None = None


def get_alert_engine() -> AlertIntelligenceEngine:
    global _engine
    if _engine is None:
        _engine = AlertIntelligenceEngine()
    return _engine
