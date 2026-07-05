"""Research Pipeline — 融合 Gateway/Scanner/Signals/Knowledge → 结构化研究报告

流程:
  1. 获取股票池 (MarketGateway)
  2. Scanner 筛选 (Coarse → Technical → Score)
  3. 对候选标的加载 Knowledge 上下文
  4. 提取证据链 (Signal + Knowledge + Market Data)
  5. 生成结构化 ResearchReport
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from src.domain.models.research_candidate import ResearchCandidate
from src.domain.models.research_report import (
    ResearchReport, CandidateAnalysis, EvidenceItem,
)
from src.scanner.engine import ScannerEngine, ScannerConfig
from src.signals.fusion import SignalFusion
from src.signals.builtin.technical import MACDSignal, RSISignal, MASignal, VolumeSignal
from src.infrastructure.knowledge.knowledge_base import KnowledgeBase


class ResearchPipeline:
    """研究管线 — 端到端研究报告生成"""

    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        scanner_config: ScannerConfig | None = None,
    ):
        self.knowledge = knowledge_base
        self.scanner = ScannerEngine(scanner_config)
        self._fusion = SignalFusion([
            MACDSignal(), RSISignal(), MASignal(), VolumeSignal(),
        ])

    async def run(
        self,
        stock_pool: list[dict],
        kline_data: dict[str, list[dict]] | None = None,
        title: str = "",
    ) -> ResearchReport:
        """执行完整研究流程 → 生成报告"""
        start = time.perf_counter()
        report_id = f"rpt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Step 1: Scanner
        scanner_result = await self.scanner.scan(stock_pool, kline_data or {})

        # Step 2: 构建候选分析
        candidates = []
        for c in scanner_result.candidates:
            analysis = await self._analyze_candidate(c, kline_data or {})
            candidates.append(analysis)

        # Step 3: 确定首选
        top_pick = candidates[0] if candidates else None

        # Step 4: 生成摘要
        summary = self._generate_summary(candidates, scanner_result)

        elapsed = (time.perf_counter() - start) * 1000

        return ResearchReport(
            report_id=report_id,
            title=title or f"研究日报 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            market_overview=self._market_overview(stock_pool),
            candidates=candidates,
            top_pick=top_pick,
            knowledge_entries_used=self._get_knowledge_used(candidates),
            total_scanned=scanner_result.total_scanned,
            candidates_found=len(candidates),
            pipeline_duration_ms=round(elapsed, 1),
        )

    async def _analyze_candidate(
        self,
        candidate: ResearchCandidate,
        kline_data: dict[str, list[dict]],
    ) -> CandidateAnalysis:
        """对单个候选标的进行深度分析 — 融合 Knowledge + Signals + Evidence"""
        code = candidate.stock_code
        klines = kline_data.get(code, [])

        analysis = CandidateAnalysis(
            stock_code=code,
            stock_name=candidate.stock_name,
            fusion_score=candidate.fusion_score,
            score_breakdown=candidate.score_breakdown,
            direction=candidate.direction,
            confidence=candidate.confidence,
            rank=candidate.rank,
            key_tags=list(candidate.tags),
        )

        # 1. 信号证据
        evidence = self._extract_signal_evidence(candidate)

        # 2. Knowledge 背景
        if self.knowledge and self.knowledge.is_loaded:
            knowledge_context = self._find_relevant_knowledge(candidate)
            analysis.knowledge_context = knowledge_context
            analysis.industry = self._infer_industry(candidate, knowledge_context)

            # 3. 知识证据
            for kc in knowledge_context:
                evidence.append(EvidenceItem(
                    source=f"knowledge:{kc}",
                    description=f"相关知识: {kc}",
                    score_contribution=2.0,
                ))

            # 4. 量价证据
            if klines and len(klines) >= 20:
                price_evidence = self._extract_market_evidence(klines)
                evidence.extend(price_evidence)

        analysis.evidence = evidence
        return analysis

    # ===== Evidence Extraction =====

    def _extract_signal_evidence(self, candidate: ResearchCandidate) -> list[EvidenceItem]:
        """从信号评分中提取证据"""
        evidence = []
        for sig_name, score in candidate.score_breakdown.items():
            if score >= 80:
                evidence.append(EvidenceItem(
                    source=f"signal:{sig_name}",
                    description=f"{sig_name.upper()}信号强(评分{score:.0f})",
                    score_contribution=score - 50,
                ))
            elif score >= 60:
                evidence.append(EvidenceItem(
                    source=f"signal:{sig_name}",
                    description=f"{sig_name.upper()}信号偏多(评分{score:.0f})",
                    score_contribution=score - 50,
                ))
            elif score <= 30:
                evidence.append(EvidenceItem(
                    source=f"signal:{sig_name}",
                    description=f"{sig_name.upper()}信号弱(评分{score:.0f})",
                    score_contribution=score - 50,
                ))
        return evidence

    def _extract_market_evidence(self, klines: list[dict]) -> list[EvidenceItem]:
        """从行情数据中提取证据"""
        evidence = []
        if len(klines) < 20:
            return evidence

        closes = [k["close"] for k in klines]
        volumes = [k.get("volume", 0) for k in klines]
        current = closes[-1]

        # 趋势
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
            if current > ma20:
                evidence.append(EvidenceItem(
                    source="market_data",
                    description=f"价格{current:.2f}站上MA20({ma20:.2f})",
                    score_contribution=5.0,
                ))
            change_5d = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
            if abs(change_5d) > 2:
                direction = "上涨" if change_5d > 0 else "下跌"
                evidence.append(EvidenceItem(
                    source="market_data",
                    description=f"近5日{direction}{abs(change_5d):.1f}%",
                    score_contribution=3.0 if change_5d > 0 else -3.0,
                ))

        # 量能
        if len(volumes) >= 21:
            avg_vol = sum(volumes[-21:-1]) / 20
            if avg_vol > 0 and volumes[-1] > avg_vol * 1.5:
                evidence.append(EvidenceItem(
                    source="market_data",
                    description=f"放量{volumes[-1]/avg_vol:.1f}倍",
                    score_contribution=3.0,
                ))

        return evidence

    # ===== Knowledge =====

    def _find_relevant_knowledge(self, candidate: ResearchCandidate) -> list[str]:
        """查找与候选标的相关的知识条目"""
        if not self.knowledge or not self.knowledge.is_loaded:
            return []

        relevant = []
        # 按标签搜索
        for tag in candidate.tags:
            results = self.knowledge.search(tag, top_k=2)
            for r in results:
                if r.id not in relevant:
                    relevant.append(r.id)

        # 按行业搜索（从 tags 推断）
        industry_results = self.knowledge.search_by_category("industry")
        for entry in industry_results:
            for tag in candidate.tags:
                if tag in entry.tags or tag in entry.title:
                    if entry.id not in relevant:
                        relevant.append(entry.id)

        return relevant[:5]

    def _infer_industry(self, candidate: ResearchCandidate, knowledge_ids: list[str]) -> str:
        """从知识条目推断行业"""
        for kid in knowledge_ids:
            entry = self.knowledge.get(kid)
            if entry and entry.category == "industry":
                return entry.title
        return ""

    # ===== Summary =====

    def _generate_summary(
        self,
        candidates: list[CandidateAnalysis],
        scanner_result,
    ) -> str:
        """生成研究摘要"""
        if not candidates:
            return "今日扫描未发现符合条件的候选标的。"

        buy_count = sum(1 for c in candidates if c.direction == "buy")
        top = candidates[0]

        lines = [
            f"今日共扫描{scanner_result.total_scanned}只标的，"
            f"筛选出{len(candidates)}只候选，"
            f"其中{buy_count}只看多。",
            "",
            f"首选: {top.stock_name}({top.stock_code}) "
            f"综合评分{top.fusion_score:.1f}分，"
            f"方向: {top.direction}，置信度: {top.confidence:.0%}。",
        ]

        if top.evidence:
            lines.append("")
            lines.append("关键证据:")
            for ev in top.evidence[:5]:
                lines.append(f"  · {ev.description}")

        if top.knowledge_context:
            lines.append(f"行业背景: {top.industry or '综合'}")

        return "\n".join(lines)

    def _market_overview(self, stock_pool: list[dict]) -> str:
        """市场概况"""
        total = len(stock_pool)
        if total == 0:
            return ""
        up = sum(1 for s in stock_pool if s.get("change_pct", 0) > 0)
        return f"全市场{total}只标的，上涨{up}只({up/max(total,1)*100:.1f}%)"

    def _get_knowledge_used(self, candidates: list[CandidateAnalysis]) -> list[str]:
        """收集所有使用的知识条目"""
        used = set()
        for c in candidates:
            for kc in c.knowledge_context:
                used.add(kc)
        return list(used)
