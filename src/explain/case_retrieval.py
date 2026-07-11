"""Similar Case Retrieval — v11.0. Evidence Based Investing.

Queries the Research Case Library to find historically similar patterns.
When AI recommends a stock, this engine answers:
  "What happened the last 127 times we saw a pattern like this?"

This turns the Case Library from a passive archive into active decision support.
Not AI guessing — historical evidence.

Similarity dimensions (multi-dimensional weighted scoring):
  1. Sector match (25%) — same sector, related, or different
  2. Score proximity (25%) — how close are the AI scores?
  3. Signal overlap (25%) — Jaccard similarity of signal names
  4. Direction match (15%) — same recommendation direction?
  5. Evidence grade (10%) — same quality tier?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.explain.evidence_quality import _case_history, _guess_sector


# ================================================================
# Data Models
# ================================================================

@dataclass
class SimilarCaseMatch:
    """A single matched case from history with its similarity breakdown."""
    case_id: str = ""                # RC-2026-000152
    stock_code: str = ""
    stock_name: str = ""
    created_at: str = ""
    ai_score: float = 50.0
    direction: str = "buy"
    evidence_grade: str = "C"
    confidence: float = 0.0

    # Similarity
    similarity_score: float = 0.0    # 0-100 overall weighted composite
    match_dimensions: dict[str, float] = field(default_factory=dict)
    # e.g. {"sector": 95, "score": 88, "signals": 72, "direction": 100, "evidence": 60}

    # Outcome (if known)
    outcome_known: bool = False
    was_correct: bool | None = None
    actual_return: float | None = None
    outcome_analysis: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "created_at": self.created_at[:19] if self.created_at else "",
            "ai_score": round(self.ai_score, 1),
            "direction": self.direction,
            "evidence_grade": self.evidence_grade,
            "similarity_score": round(self.similarity_score, 1),
            "match_dimensions": {k: round(v, 1) for k, v in self.match_dimensions.items()},
            "outcome_known": self.outcome_known,
            "was_correct": self.was_correct,
            "actual_return": round(self.actual_return, 1) if self.actual_return is not None else None,
            "outcome_analysis": self.outcome_analysis,
        }


@dataclass
class CaseRetrievalReport:
    """Complete similar case retrieval result."""
    stock_code: str = ""
    stock_name: str = ""
    query_score: float = 50.0
    query_direction: str = "buy"
    generated_at: str = ""

    # Results
    total_cases_searched: int = 0
    total_similar: int = 0            # Cases with similarity >= threshold
    matches: list[SimilarCaseMatch] = field(default_factory=list)  # Top 10

    # Aggregate stats from similar cases
    aggregate_win_rate: float = 0.0
    aggregate_avg_return: float = 0.0
    aggregate_best_return: float = 0.0
    aggregate_worst_return: float = 0.0

    # By outcome
    cases_up: int = 0
    cases_down: int = 0
    cases_correct: int = 0
    cases_wrong: int = 0

    # Insight
    insight: str = ""

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "query_score": round(self.query_score, 1),
            "query_direction": self.query_direction,
            "generated_at": self.generated_at[:19] if self.generated_at else "",
            "total_cases_searched": self.total_cases_searched,
            "total_similar": self.total_similar,
            "matches": [m.to_dict() for m in self.matches],
            "aggregate_win_rate": round(self.aggregate_win_rate, 3),
            "aggregate_avg_return": round(self.aggregate_avg_return, 2),
            "aggregate_best_return": round(self.aggregate_best_return, 2),
            "aggregate_worst_return": round(self.aggregate_worst_return, 2),
            "cases_up": self.cases_up,
            "cases_down": self.cases_down,
            "cases_correct": self.cases_correct,
            "cases_wrong": self.cases_wrong,
            "insight": self.insight,
        }


# ================================================================
# Case Retriever Engine
# ================================================================

class CaseRetriever:
    """Finds historically similar cases from the Research Case Library.

    Multi-dimensional similarity scoring across sector, score, signals,
    direction, and evidence quality. Not vector search — transparent,
    explainable dimension-by-dimension comparison.
    """

    # Dimension weights (sum to 1.0)
    WEIGHTS = {
        "sector": 0.25,
        "score": 0.25,
        "signals": 0.25,
        "direction": 0.15,
        "evidence": 0.10,
    }

    SIMILARITY_THRESHOLD = 40.0  # Minimum similarity score to include in report

    def find_similar(
        self,
        stock_code: str,
        stock_name: str,
        ai_score: float = 50.0,
        direction: str = "buy",
        signals: list[str] | None = None,
        evidence_grade: str = "C",
        min_similarity: float = 40.0,
        limit: int = 10,
    ) -> CaseRetrievalReport:
        """Find historically similar cases from the case library.

        Args:
            stock_code: The stock being evaluated
            stock_name: Human-readable name
            ai_score: Current AI fusion score (0-100)
            direction: buy / sell / hold
            signals: Signal names active for this recommendation
            evidence_grade: A / B / C / D
            min_similarity: Minimum similarity score to include (0-100)
            limit: Max matches to return

        Returns:
            CaseRetrievalReport with top matches and aggregate stats
        """
        signals = signals or ["MACD", "RSI", "MA"]
        query_sector = _guess_sector(stock_name)

        # Case history is populated by route handler before calling this.
        # If empty, return an honest empty report rather than fabricating data.

        # Compute similarity for every case
        scored: list[tuple[float, SimilarCaseMatch]] = []
        for case in _case_history:
            if case.stock_code == stock_code:
                continue  # Skip same stock (we want cross-stock patterns)

            sim, dims = self._compute_similarity(
                case, query_sector, ai_score, direction, signals, evidence_grade
            )

            if sim >= min_similarity:
                match = SimilarCaseMatch(
                    case_id=case.case_id,
                    stock_code=case.stock_code,
                    stock_name=case.stock_name,
                    created_at=case.created_at,
                    ai_score=case.ai_score,
                    direction=case.direction,
                    evidence_grade=case.evidence_grade.value if hasattr(case.evidence_grade, 'value') else str(case.evidence_grade),
                    confidence=case.confidence,
                    similarity_score=sim,
                    match_dimensions=dims,
                    outcome_known=case.outcome_known,
                    was_correct=case.was_correct,
                    actual_return=case.actual_30d_return if case.outcome_known else None,
                    outcome_analysis=case.outcome_analysis if case.outcome_known else "",
                )
                scored.append((sim, match))

        # Sort by similarity descending, take top N
        scored.sort(key=lambda x: -x[0])
        top_matches = [m for _, m in scored[:limit]]

        # Aggregate stats
        verified_matches = [m for m in top_matches if m.outcome_known]
        correct = [m for m in verified_matches if m.was_correct is True]
        wrong = [m for m in verified_matches if m.was_correct is False]
        up_matches = [m for m in verified_matches if m.actual_return and m.actual_return > 0]
        down_matches = [m for m in verified_matches if m.actual_return and m.actual_return <= 0]

        win_rate = len(correct) / len(verified_matches) if verified_matches else 0
        returns = [m.actual_return for m in verified_matches if m.actual_return is not None]
        avg_return = sum(returns) / len(returns) if returns else 0
        best_return = max(returns) if returns else 0
        worst_return = min(returns) if returns else 0

        # Generate insight
        insight = self._generate_insight(
            len(scored), win_rate, avg_return, best_return, worst_return,
            direction, ai_score,
        )

        return CaseRetrievalReport(
            stock_code=stock_code,
            stock_name=stock_name,
            query_score=ai_score,
            query_direction=direction,
            generated_at=datetime.now().isoformat(),
            total_cases_searched=len(_case_history),
            total_similar=len(scored),
            matches=top_matches,
            aggregate_win_rate=win_rate,
            aggregate_avg_return=avg_return,
            aggregate_best_return=best_return,
            aggregate_worst_return=worst_return,
            cases_up=len(up_matches),
            cases_down=len(down_matches),
            cases_correct=len(correct),
            cases_wrong=len(wrong),
            insight=insight,
        )

    # ================================================================
    # Similarity Computation
    # ================================================================

    def _compute_similarity(
        self,
        case,
        query_sector: str,
        query_score: float,
        query_direction: str,
        query_signals: list[str],
        query_grade: str,
    ) -> tuple[float, dict[str, float]]:
        """Compute multi-dimensional similarity between a case and query.

        Returns:
            (overall_similarity_0_100, dimension_scores_dict)
        """
        dims = {}

        # 1. Sector match (25%)
        case_sector = _guess_sector(case.stock_name)
        dims["sector"] = self._sector_similarity(query_sector, case_sector)

        # 2. Score proximity (25%)
        dims["score"] = self._score_similarity(query_score, case.ai_score)

        # 3. Signal overlap — Jaccard similarity (25%)
        # We approximate signals from score thresholds since cases don't store raw signal names
        case_signals = self._infer_signals(case)
        dims["signals"] = self._jaccard_similarity(set(query_signals), case_signals)

        # 4. Direction match (15%)
        dims["direction"] = 100.0 if case.direction == query_direction else (
            50.0 if _related_direction(case.direction, query_direction) else 0.0
        )

        # 5. Evidence grade match (10%)
        case_grade = case.evidence_grade.value if hasattr(case.evidence_grade, 'value') else str(case.evidence_grade)
        dims["evidence"] = self._grade_similarity(query_grade, case_grade)

        # Weighted composite
        overall = sum(
            dims[dim] * weight
            for dim, weight in self.WEIGHTS.items()
            if dim in dims
        )

        return overall, dims

    def _sector_similarity(self, sector_a: str, sector_b: str) -> float:
        """Sector similarity: same=100, related=60, different=20."""
        if sector_a == sector_b:
            return 100.0

        # Related sectors
        related_pairs = [
            ({"半导体", "科技"}, 60.0),
            ({"消费", "医药"}, 50.0),
            ({"金融", "综合"}, 50.0),
            ({"新能源", "汽车"}, 60.0),
            ({"科技", "新能源"}, 40.0),
        ]
        for pair, score in related_pairs:
            if sector_a in pair and sector_b in pair:
                return score

        return 20.0  # Completely different

    def _score_similarity(self, score_a: float, score_b: float) -> float:
        """Score proximity: 100 at 0 difference, 0 at 50+ difference."""
        diff = abs(score_a - score_b)
        return max(0.0, 100.0 - diff * 2.0)

    def _jaccard_similarity(self, set_a: set, set_b: set) -> float:
        """Jaccard coefficient: |intersection| / |union|."""
        if not set_a and not set_b:
            return 100.0
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return (intersection / union) * 100.0 if union > 0 else 0.0

    def _grade_similarity(self, grade_a: str, grade_b: str) -> float:
        """Evidence grade similarity: same=100, one-off=60, two-off=30, three-off=0."""
        grades = ["A", "B", "C", "D"]
        try:
            idx_a = grades.index(grade_a[0].upper())
            idx_b = grades.index(grade_b[0].upper())
        except (ValueError, IndexError):
            return 50.0

        diff = abs(idx_a - idx_b)
        mapping = {0: 100.0, 1: 60.0, 2: 30.0, 3: 0.0}
        return mapping.get(diff, 0.0)

    def _infer_signals(self, case) -> set[str]:
        """Infer likely signal names from case score and direction.

        Since ResearchCase doesn't store raw signal names, we approximate
        from the score level and direction. This is a heuristic — when
        real signal data is stored on cases, replace this.
        """
        signals = set()
        score = case.ai_score

        if score >= 70:
            signals.add("MACD")
        if score >= 65:
            signals.add("MA")
        if 40 <= score <= 75:
            signals.add("RSI")
        elif score > 75:
            signals.add("RSI")
        if score >= 60:
            signals.add("Volume")
        if score >= 80:
            signals.add("KDJ")

        # If it's a sell, add different signals
        if case.direction == "sell":
            if score <= 40:
                signals.add("MACD")  # Death cross

        return signals

    # ================================================================
    # Insight Generation
    # ================================================================

    def _generate_insight(
        self, total_similar: int, win_rate: float,
        avg_return: float, best_return: float, worst_return: float,
        direction: str, ai_score: float,
    ) -> str:
        """Generate a human-readable insight from the retrieval results."""
        if total_similar == 0:
            return (
                f"在{len(_case_history)}个历史案例中未找到高度相似的模式。"
                f"这是一个相对独特的信号组合，建议额外谨慎。"
            )

        direction_cn = {"buy": "看涨", "sell": "看跌", "hold": "观望"}.get(direction, "操作")

        if total_similar >= 20 and win_rate >= 0.65:
            return (
                f"共找到{total_similar}个历史相似案例。"
                f"其中{win_rate:.0%}实现了{direction_cn}预期，"
                f"平均收益{avg_return:+.1f}%。"
                f"最佳案例收益{best_return:+.1f}%，最差{worst_return:+.1f}%。"
                f"历史证据支持当前{direction_cn}判断。"
            )
        elif total_similar >= 10 and win_rate >= 0.50:
            return (
                f"找到{total_similar}个相似案例，胜率{win_rate:.0%}，"
                f"平均收益{avg_return:+.1f}%。"
                f"历史证据温和支持当前判断，但不确定性较高。"
            )
        elif total_similar >= 5:
            return (
                f"仅有{total_similar}个相似案例，样本量较小。"
                f"胜率{win_rate:.0%}，平均收益{avg_return:+.1f}%。"
                f"建议参考但不要过度依赖历史模式。"
            )
        else:
            return (
                f"仅找到{total_similar}个低相似度案例，不足以形成统计学结论。"
                f"建议依靠当前证据质量做判断。"
            )


def _related_direction(dir_a: str, dir_b: str) -> bool:
    """Are two directions related (e.g., buy and hold)?"""
    related = [
        {"buy", "hold"},
        {"sell", "hold"},
    ]
    for pair in related:
        if dir_a in pair and dir_b in pair:
            return True
    return False


# Singleton
case_retriever = CaseRetriever()
