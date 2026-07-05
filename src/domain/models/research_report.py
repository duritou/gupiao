"""ResearchReport — 结构化研究输出 + 证据链

不是简单的分数，而是:
  - 摘要
  - 候选分析（每个标的: 评分 + 证据 + 知识背景）
  - 知识上下文
  - 证据来源追溯
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvidenceItem:
    """证据条目 — 某个结论的数据支撑"""
    source: str            # "signal:macd" / "knowledge:semiconductor" / "market_data"
    description: str       # "MACD日线金叉，DIF上穿DEA"
    score_contribution: float = 0.0  # 对最终评分的贡献


@dataclass
class CandidateAnalysis:
    """单个候选标的的完整分析"""

    stock_code: str
    stock_name: str = ""

    # 评分
    fusion_score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    direction: str = "neutral"
    confidence: float = 0.0
    rank: int = 0

    # 证据
    evidence: list[EvidenceItem] = field(default_factory=list)

    # 知识背景
    knowledge_context: list[str] = field(default_factory=list)
    industry: str = ""
    key_tags: list[str] = field(default_factory=list)


@dataclass
class ResearchReport:
    """结构化研究报告"""

    report_id: str = ""
    title: str = ""
    generated_at: str = ""

    # 摘要
    summary: str = ""
    market_overview: str = ""

    # 候选分析
    candidates: list[CandidateAnalysis] = field(default_factory=list)
    top_pick: CandidateAnalysis | None = None

    # 知识使用
    knowledge_entries_used: list[str] = field(default_factory=list)

    # 元数据
    total_scanned: int = 0
    candidates_found: int = 0
    pipeline_duration_ms: float = 0.0
