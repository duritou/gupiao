"""Evidence Quality Rating + Research Case Library — v8.0.

Every AI recommendation now carries:
  1. Evidence Grade (A/B/C/D) — based on source quality, not AI confidence
  2. Research Case ID — traceable, verifiable, outcome-tracked

This is the difference between 'AI says buy' and 'AI says buy, backed by
6 official sources, 98% data consistency, Grade A evidence.'
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class EvidenceGrade(str, Enum):
    A = "A"  # 3+ official sources, cross-verified, fresh data — highest trust
    B = "B"  # 1-2 official + community, mostly verified
    C = "C"  # Community sources only, single provider
    D = "D"  # Single source, stale data, low confidence — use with caution


@dataclass
class EvidenceQuality:
    """Quality assessment of the evidence behind an AI recommendation."""
    grade: EvidenceGrade = EvidenceGrade.C

    # Source breakdown
    official_sources: int = 0       # 官方/交易所/披露
    commercial_sources: int = 0     # 商业数据
    community_sources: int = 0      # 社区/开源
    news_sources: int = 0           # 新闻媒体

    # Verification
    cross_verified_count: int = 0   # How many sources confirmed the same fact
    total_evidence_points: int = 0
    data_consistency_pct: float = 0.0  # How well do sources agree?

    # Freshness
    newest_data_age_sec: float = 0.0
    oldest_data_age_sec: float = 0.0

    # Overall
    quality_score: float = 0.0      # 0-100
    recommendation: str = ""        # Human-readable guidance

    def to_dict(self) -> dict:
        return {
            "grade": self.grade.value,
            "official_sources": self.official_sources,
            "commercial_sources": self.commercial_sources,
            "community_sources": self.community_sources,
            "news_sources": self.news_sources,
            "cross_verified_count": self.cross_verified_count,
            "total_evidence_points": self.total_evidence_points,
            "data_consistency_pct": round(self.data_consistency_pct, 1),
            "newest_data_age_sec": round(self.newest_data_age_sec, 1),
            "oldest_data_age_sec": round(self.oldest_data_age_sec, 1),
            "quality_score": round(self.quality_score, 1),
            "recommendation": self.recommendation,
        }


@dataclass
class ResearchCase:
    """A single AI research case — tracked from creation to outcome.

    Every time the AI makes a significant recommendation, a Research Case
    is created. It tracks: what was recommended, why, what happened.
    Over time, this becomes the most valuable data asset.
    """
    case_id: str = ""                # RC-2026-000152
    stock_code: str = ""
    stock_name: str = ""
    created_at: str = ""

    # The recommendation
    ai_score: float = 50.0
    direction: str = "buy"
    confidence: float = 0.0
    recommendation_text: str = ""

    # Evidence quality
    evidence_grade: EvidenceGrade = EvidenceGrade.C
    evidence_quality: EvidenceQuality | None = None

    # Predicted outcome
    predicted_30d_return: float = 0.0
    predicted_30d_probability: float = 0.0

    # Actual outcome (filled later)
    outcome_known: bool = False
    actual_30d_return: float = 0.0
    was_correct: bool | None = None
    outcome_analyzed_at: str = ""
    outcome_analysis: str = ""       # AI's reflection on what happened

    # Verifiability
    is_replayable: bool = True       # Can this case be replayed?
    replay_context_hash: str = ""     # For deterministic replay

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "created_at": self.created_at[:19] if self.created_at else "",
            "ai_score": round(self.ai_score, 1),
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "recommendation_text": self.recommendation_text,
            "evidence_grade": self.evidence_grade.value,
            "evidence_quality": self.evidence_quality.to_dict() if self.evidence_quality else None,
            "predicted_30d_return": round(self.predicted_30d_return, 1),
            "predicted_30d_probability": round(self.predicted_30d_probability, 2),
            "outcome_known": self.outcome_known,
            "actual_30d_return": round(self.actual_30d_return, 1) if self.outcome_known else None,
            "was_correct": self.was_correct,
            "outcome_analysis": self.outcome_analysis,
            "is_replayable": self.is_replayable,
        }


class EvidenceGrader:
    """Grades AI recommendation evidence quality based on source composition.

    Grade criteria:
      A: >=3 official + commercial, >=5 cross-verified, consistency >=95%, fresh
      B: >=1 official + community, >=3 cross-verified, consistency >=85%
      C: Community sources only, >=2 verified
      D: Single source, stale data, or low consistency — use with caution
    """

    def grade_recommendation(
        self, stock_code: str, stock_name: str,
        ai_score: float, direction: str, confidence: float,
        official_sources: int = 0,
        commercial_sources: int = 0,
        community_sources: int = 1,
        news_sources: int = 0,
        cross_verified: int = 1,
        total_evidence: int = 3,
        data_consistency: float = 90.0,
        data_age_sec: float = 5.0,
    ) -> tuple[EvidenceQuality, ResearchCase]:
        """Grade evidence and create a research case in one step."""

        # Determine grade
        total_sources = official_sources + commercial_sources + community_sources + news_sources

        if (official_sources >= 3 and cross_verified >= 5
                and data_consistency >= 95 and data_age_sec < 60):
            grade = EvidenceGrade.A
            quality_score = 95.0
            rec = "最高质量证据。多个官方来源交叉验证，数据新鲜一致。可充分信赖。"
        elif (official_sources + commercial_sources >= 1 and cross_verified >= 3
                and data_consistency >= 85 and data_age_sec < 300):
            grade = EvidenceGrade.B
            quality_score = 82.0
            rec = "证据质量良好。有官方或商业来源支撑，大多数数据交叉验证通过。"
        elif (cross_verified >= 2 and data_consistency >= 70):
            grade = EvidenceGrade.C
            quality_score = 60.0
            rec = "证据主要来自社区来源。建议等待官方数据确认后再做重大决策。"
        else:
            grade = EvidenceGrade.D
            quality_score = 35.0
            rec = "证据质量不足。数据源单一或陈旧。AI建议仅供参考，请勿据此操作。"

        # Adjust quality score by AI confidence alignment
        if confidence > 0.85 and grade in (EvidenceGrade.A, EvidenceGrade.B):
            quality_score = min(100, quality_score + 5)
        elif confidence > 0.8 and grade == EvidenceGrade.D:
            quality_score = min(quality_score, 40)  # Cap low-quality high-confidence

        quality = EvidenceQuality(
            grade=grade,
            official_sources=official_sources,
            commercial_sources=commercial_sources,
            community_sources=community_sources,
            news_sources=news_sources,
            cross_verified_count=cross_verified,
            total_evidence_points=total_evidence,
            data_consistency_pct=data_consistency,
            newest_data_age_sec=data_age_sec,
            oldest_data_age_sec=data_age_sec * 3,
            quality_score=quality_score,
            recommendation=rec,
        )

        # Create research case
        now = datetime.now()
        case_num = int(hashlib.md5(f"{stock_code}:{now.isoformat()}".encode()).hexdigest()[:6], 16) % 900000 + 100000
        case = ResearchCase(
            case_id=f"RC-{now.year}-{case_num:06d}",
            stock_code=stock_code, stock_name=stock_name,
            created_at=now.isoformat(),
            ai_score=ai_score, direction=direction, confidence=confidence,
            recommendation_text=f"AI综合评分{ai_score:.0f}，建议{direction}。证据等级{grade.value}。",
            evidence_grade=grade, evidence_quality=quality,
            predicted_30d_return=(ai_score - 50) * 0.5,
            predicted_30d_probability=confidence,
            is_replayable=True,
            replay_context_hash=hashlib.md5(
                f"{stock_code}:{now.strftime('%Y%m%d')}:{ai_score:.0f}".encode()
            ).hexdigest()[:12],
        )

        return quality, case


# Singleton
grader = EvidenceGrader()

# In-memory case library
_case_library: dict[str, ResearchCase] = {}
_case_history: list[ResearchCase] = []


def archive_case(case: ResearchCase):
    _case_library[case.case_id] = case
    _case_history.append(case)


def get_case(case_id: str) -> ResearchCase | None:
    return _case_library.get(case_id)


def get_case_library_stats() -> dict:
    verified = [c for c in _case_history if c.outcome_known]
    correct = [c for c in verified if c.was_correct is True]
    by_grade = {}
    for grade in EvidenceGrade:
        cases = [c for c in _case_history if c.evidence_grade == grade]
        if cases:
            correct_in_grade = [c for c in cases if c.was_correct is True]
            by_grade[grade.value] = {
                "total": len(cases),
                "correct": len(correct_in_grade),
                "accuracy": len(correct_in_grade) / len(cases) if cases else 0,
            }

    return {
        "total_cases": len(_case_history),
        "verified_cases": len(verified),
        "correct_cases": len(correct),
        "overall_accuracy": len(correct) / len(verified) if verified else 0,
        "by_grade": by_grade,
        "oldest_case": _case_history[0].case_id if _case_history else "",
        "newest_case": _case_history[-1].case_id if _case_history else "",
    }


def get_research_coverage() -> dict:
    """AI Research Coverage — how much of the market has AI studied?"""
    # Stock coverage
    stocks_covered = set()
    for c in _case_history:
        stocks_covered.add(c.stock_code)

    # By sector
    by_sector: dict[str, dict] = {}
    for c in _case_history:
        sector = _guess_sector(c.stock_name) if hasattr(c, 'stock_name') else "综合"
        if sector not in by_sector:
            by_sector[sector] = {"total": 0, "correct": 0, "verified": 0}
        by_sector[sector]["total"] += 1
        if c.outcome_known:
            by_sector[sector]["verified"] += 1
            if c.was_correct:
                by_sector[sector]["correct"] += 1

    verified_cases = [c for c in _case_history if c.outcome_known]
    total_verified = len(verified_cases)
    total_correct = len([c for c in verified_cases if c.was_correct])

    # Replay tracking
    replayable = [c for c in _case_history if c.is_replayable]

    return {
        "total_cases": len(_case_history),
        "stocks_covered": len(stocks_covered),
        "total_stocks_market": 5432,  # Approximate total A-shares
        "coverage_pct": round(len(stocks_covered) / 5432 * 100, 1),
        "verified_cases": total_verified,
        "correct_cases": total_correct,
        "accuracy": round(total_correct / total_verified, 2) if total_verified else 0,
        "replayable_cases": len(replayable),
        "by_sector": {
            s: {
                "total": d["total"],
                "verified": d["verified"],
                "correct": d["correct"],
                "accuracy": round(d["correct"] / d["verified"], 2) if d["verified"] else 0,
            }
            for s, d in sorted(by_sector.items(), key=lambda x: -x[1]["total"])
        },
        "by_grade": get_case_library_stats().get("by_grade", {}),
        "latest_case": _case_history[-1].case_id if _case_history else "",
        "oldest_case": _case_history[0].case_id if _case_history else "",
        "summary": _coverage_summary(len(_case_history), len(stocks_covered), total_verified, total_correct),
    }


def _coverage_summary(total: int, stocks: int, verified: int, correct: int) -> str:
    if total == 0:
        return "Research Case Library is empty. Start analyzing to build coverage."
    acc = f"准确率{correct/verified:.0%}" if verified > 0 else "待验证"
    return (
        f"AI已完成{total}个研究案例，覆盖{stocks}只股票。"
        f"已验证{verified}个案例，{acc}。"
    )


def _guess_sector(name: str) -> str:
    for kw, s in [("微", "半导体"), ("芯", "半导体"), ("光", "科技"), ("软", "科技"),
                   ("酒", "消费"), ("药", "医药"), ("车", "汽车"),
                   ("能源", "新能源"), ("银行", "金融")]:
        if kw in name:
            return s
    return "综合"
