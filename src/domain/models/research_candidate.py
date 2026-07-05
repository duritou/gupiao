"""ResearchCandidate — Scanner 输出的标准化候选标的

不是 "Top 20 列表"，而是 "值得研究的候选标的集合"。
不同策略/市场可以共用同一接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchCandidate:
    """研究候选标的"""

    stock_code: str
    stock_name: str = ""
    fusion_score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    direction: str = "neutral"               # buy / sell / neutral
    confidence: float = 0.0

    # 分类
    candidate_type: str = "scanner"          # scanner / watchlist / manual / event

    # 通过哪些筛选
    passed_coarse: bool = False
    passed_technical: bool = False

    # 关键指标
    market_cap: float = 0.0                  # 市值（亿）
    pe_ratio: float = 0.0
    turnover_rate: float = 0.0
    change_pct: float = 0.0

    # 排名
    rank: int = 0
    tags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class ScannerResult:
    """Scanner 运行结果"""

    scan_date: str = ""
    total_scanned: int = 0
    after_coarse: int = 0
    after_technical: int = 0
    after_scoring: int = 0
    candidates: list[ResearchCandidate] = field(default_factory=list)
    duration_ms: float = 0.0
