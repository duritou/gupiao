"""Evaluate the live strategy on its own recorded decisions.

Every other evaluation surface in this repository measures something adjacent:
``calibration`` measures confidence honesty, ``market_learning`` fits per-stock
adjustments, and ``algorithm_comparator`` scores replayed proxy models.  None of
them answers "how did the strategy actually do".

This reads back the decisions the pipeline actually made -- the stored packet
carries the score lineage, the gate chain and ``code_hash``/``strategy_version``
-- and scores them against forward returns.  It re-implements nothing: forward
returns come from the local bar table and the benchmark from
``benchmark.equal_weight_return``, the same function the learning label uses.

Segmentation is not optional.  The record spans a configuration whose gates
could never open and whose data coverage sat at 67%, both fixed on 2026-09-19,
so pooled numbers would average a broken system with a working one.  Every
result is split by ``strategy_version`` and by benchmark basis, and callers are
expected to read the segments rather than the total.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date as dt_date
from typing import Any

from src.explain.benchmark import equal_weight_return
from src.explain.outcome_backfiller import _compute_was_correct

logger = logging.getLogger("uvicorn.error")

HORIZON_DAYS = 5

# Fractions of the score distribution; the point is whether the score
# separates outcomes at all, which a single averaged number cannot show.
DECILE_COUNT = 10


@dataclass(frozen=True, slots=True)
class EvaluatedDecision:
    """One recorded decision scored against its forward outcome."""

    decision_date: str
    stock_code: str
    strategy_version: str
    benchmark_basis: str
    ranking_score: float | None
    research_score: float | None
    pre_gate_direction: str
    final_direction: str
    gate_reasons: tuple[str, ...]
    stock_return: float
    benchmark_return: float
    excess_return: float
    was_correct: bool

    @property
    def was_gated(self) -> bool:
        return bool(self.gate_reasons)


@dataclass
class StrategyEvaluation:
    """Aggregated view of a decision sample. Never a single headline number."""

    generated_at: str = ""
    horizon_days: int = HORIZON_DAYS
    start_date: str = ""
    end_date: str = ""
    total_decisions: int = 0
    evaluated: int = 0
    skipped_no_outcome: int = 0
    score_deciles: list[dict[str, Any]] = field(default_factory=list)
    gate_attribution: list[dict[str, Any]] = field(default_factory=list)
    by_strategy_version: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_benchmark_basis: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "horizon_days": self.horizon_days,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_decisions": self.total_decisions,
            "evaluated": self.evaluated,
            "skipped_no_outcome": self.skipped_no_outcome,
            "score_deciles": self.score_deciles,
            "gate_attribution": self.gate_attribution,
            "by_strategy_version": self.by_strategy_version,
            "by_benchmark_basis": self.by_benchmark_basis,
            "notes": self.notes,
        }


def _market_calendar(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT trade_date FROM market_daily
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date""",
        (start_date, end_date),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _forward_return(
    conn: sqlite3.Connection, code: str, start_date: str, end_date: str
) -> float | None:
    rows = conn.execute(
        """SELECT trade_date, close FROM market_daily
            WHERE ts_code=? AND trade_date IN (?, ?) AND close > 0""",
        (code, start_date, end_date),
    ).fetchall()
    closes = {str(r[0]): float(r[1]) for r in rows}
    if start_date not in closes or end_date not in closes:
        return None
    return (closes[end_date] / closes[start_date]) - 1.0


def _decision_rows(
    conn: sqlite3.Connection, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """One row per (decision_date, stock_code), newest write winning."""
    rows = conn.execute(
        """WITH ranked AS (
               SELECT d.id, d.decision_date, d.stock_code, d.direction,
                      s.analysis_json,
                      ROW_NUMBER() OVER (
                          PARTITION BY d.decision_date, d.stock_code
                          ORDER BY d.id DESC
                      ) AS scan_rank
                 FROM decision_journal AS d
                 LEFT JOIN strategy_decision AS s ON s.journal_id = d.id
                WHERE d.decision_date >= ? AND d.decision_date <= ?
           )
           SELECT decision_date, stock_code, direction, analysis_json
             FROM ranked WHERE scan_rank = 1
            ORDER BY decision_date, stock_code""",
        (start_date, end_date),
    ).fetchall()
    return [dict(row) for row in rows]


def _numeric(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _nth_session(calendar: list[str], start_date: str, horizon: int) -> str | None:
    days = [d for d in calendar if d >= start_date]
    if not days:
        return None
    base = days.index(start_date) if start_date in days else 0
    if base + horizon >= len(days):
        return None
    return days[base + horizon]


def evaluate_decisions(
    conn: sqlite3.Connection,
    *,
    start_date: str = "",
    end_date: str = "",
    horizon_days: int = HORIZON_DAYS,
    today: str | None = None,
) -> StrategyEvaluation:
    """Score recorded decisions and aggregate them without pooling eras."""
    today = today or dt_date.today().isoformat()
    rows = _decision_rows(conn, start_date, today)
    calendar = _market_calendar(conn, start_date or "1900-01-01", today)

    result = StrategyEvaluation(
        generated_at=today,
        horizon_days=horizon_days,
        start_date=start_date,
        end_date=end_date or today,
        total_decisions=len(rows),
    )

    # The equal-weight window is per decision date, so memoise it.
    benchmark_cache: dict[tuple[str, str], tuple[float | None, str]] = {}
    samples: list[EvaluatedDecision] = []

    for row in rows:
        decision_date = str(row["decision_date"] or "")
        code = str(row["stock_code"] or "")
        window_end = _nth_session(calendar, decision_date, horizon_days)
        if not window_end:
            result.skipped_no_outcome += 1
            continue
        stock_return = _forward_return(conn, code, decision_date, window_end)
        if stock_return is None:
            result.skipped_no_outcome += 1
            continue
        key = (decision_date, window_end)
        if key not in benchmark_cache:
            value, basis = equal_weight_return(conn, decision_date, window_end)
            benchmark_cache[key] = (value, basis.status)
        benchmark_return, basis_status = benchmark_cache[key]
        if benchmark_return is None:
            result.skipped_no_outcome += 1
            continue

        try:
            packet = json.loads(row["analysis_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            packet = {}
        excess = stock_return - benchmark_return
        direction = str(
            packet.get("final_direction") or row["direction"] or "neutral"
        ).strip().lower()
        samples.append(
            EvaluatedDecision(
                decision_date=decision_date,
                stock_code=code,
                strategy_version=str(packet.get("strategy_version") or ""),
                benchmark_basis=basis_status,
                ranking_score=_numeric(packet.get("ranking_score")),
                research_score=_numeric(packet.get("research_score")),
                pre_gate_direction=str(packet.get("pre_gate_direction") or "").lower(),
                final_direction=direction,
                gate_reasons=tuple(packet.get("score_guard_reasons") or []),
                stock_return=stock_return,
                benchmark_return=benchmark_return,
                excess_return=excess,
                was_correct=_compute_was_correct(direction, excess),
            )
        )

    result.evaluated = len(samples)
    result.score_deciles = _score_deciles(samples)
    result.gate_attribution = _gate_attribution(samples)
    result.by_strategy_version = _segment(samples, lambda s: s.strategy_version or "(unlabelled)")
    result.by_benchmark_basis = _segment(samples, lambda s: s.benchmark_basis or "(unknown)")
    result.notes = _notes(result)
    return result


def _summary(samples: list[EvaluatedDecision]) -> dict[str, Any]:
    if not samples:
        return {"n": 0}
    excesses = [s.excess_return for s in samples]
    return {
        "n": len(samples),
        "hit_rate": round(sum(1 for s in samples if s.was_correct) / len(samples), 4),
        "mean_excess": round(sum(excesses) / len(excesses), 6),
        "median_excess": round(sorted(excesses)[len(excesses) // 2], 6),
        "mean_stock_return": round(
            sum(s.stock_return for s in samples) / len(samples), 6
        ),
    }


def _segment(samples: list[EvaluatedDecision], key) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[EvaluatedDecision]] = {}
    for sample in samples:
        buckets.setdefault(key(sample), []).append(sample)
    return {name: _summary(group) for name, group in sorted(buckets.items())}


def _score_deciles(samples: list[EvaluatedDecision]) -> list[dict[str, Any]]:
    """Does the ranking score separate outcomes at all?

    A single average cannot answer this: a strategy can be right on average
    while its score is noise, and that distinction decides whether the score is
    worth acting on.
    """
    scored = [s for s in samples if s.ranking_score is not None]
    if len(scored) < DECILE_COUNT:
        return []
    scored.sort(key=lambda s: s.ranking_score)
    size = len(scored) / DECILE_COUNT
    deciles = []
    for index in range(DECILE_COUNT):
        low = int(index * size)
        high = int((index + 1) * size) if index < DECILE_COUNT - 1 else len(scored)
        group = scored[low:high]
        if not group:
            continue
        deciles.append({
            "decile": index + 1,
            "score_min": round(group[0].ranking_score, 2),
            "score_max": round(group[-1].ranking_score, 2),
            **_summary(group),
        })
    return deciles


def _gate_attribution(samples: list[EvaluatedDecision]) -> list[dict[str, Any]]:
    """What each gate cost or saved, measured on forward returns.

    A gate that blocks decisions whose forward excess was negative earned its
    keep; one blocking positive excess has a price, and that price is what this
    reports.  It measures opportunity, not execution -- a blocked name could
    still have been rejected downstream.
    """
    buckets: dict[str, list[EvaluatedDecision]] = {}
    for sample in samples:
        for reason in sample.gate_reasons:
            buckets.setdefault(reason, []).append(sample)
    attribution = []
    for reason, group in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        summary = _summary(group)
        summary["reason"] = reason
        summary["mean_excess_if_released"] = summary.pop("mean_excess")
        attribution.append(summary)
    return attribution


def _notes(result: StrategyEvaluation) -> list[str]:
    notes = []
    if result.evaluated == 0:
        notes.append(
            "样本为空:本地行情或基准数据不足以给任何决策算出前瞻收益。"
        )
    if len(result.by_strategy_version) > 1:
        notes.append(
            "记录跨越多个 strategy_version,不得合并阅读 —— 早期版本运行在"
            "闸门永不开、数据覆盖 67% 的配置下。"
        )
    if len(result.by_benchmark_basis) > 1:
        notes.append(
            "记录跨越多个基准口径,不得合并阅读 —— hs300_legacy 与等权不可比。"
        )
    if result.evaluated and result.evaluated < 100:
        notes.append(
            f"样本仅 {result.evaluated} 条,统计上不构成证据;其价值在于可累积、"
            "可比较,而非当前结论。"
        )
    return notes
