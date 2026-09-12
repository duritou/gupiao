"""Research routes backed by real scanner output and decision journal."""

import math
import time
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.routes.journal_utils import decision_scores, get_journal_decisions, top_signal
from src.research.factor_validation import (
    neutralize_factor,
    validate_factor_horizons,
    validate_factor_rolling,
)

router = APIRouter(tags=["research"], prefix="/research")


class FactorObservationRequest(BaseModel):
    """One point-in-time factor observation with an explicitly later return date."""

    date: str = Field(min_length=10, max_length=10)
    forward_date: str = Field(min_length=10, max_length=10)
    symbol: str = Field(min_length=1, max_length=40)
    factor: float
    forward_return: float
    horizon: int = Field(default=1, ge=1, le=252)
    industry: str = Field(default="", max_length=80)


class FactorValidationRequest(BaseModel):
    """Bounded request for offline, point-in-time factor diagnostics."""

    factor_name: str = Field(default="factor", min_length=1, max_length=80)
    observations: list[FactorObservationRequest] = Field(min_length=1, max_length=100000)
    horizons: list[int] = Field(
        default_factory=lambda: [1, 5, 20], min_length=1, max_length=8
    )
    train_dates: int = Field(default=60, ge=1, le=1000)
    test_dates: int = Field(default=20, ge=1, le=500)
    neutralize_by_industry: bool = False


def _parse_observation_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use YYYY-MM-DD",
        ) from exc


@router.post("/factor-validation")
async def validate_factor_endpoint(req: FactorValidationRequest):
    """Return auditable factor diagnostics without changing production weights."""
    if any(horizon < 1 for horizon in req.horizons):
        raise HTTPException(status_code=422, detail="horizons must be positive")

    rows = []
    for observation in req.observations:
        signal_date = _parse_observation_date(observation.date, "date")
        forward_date = _parse_observation_date(observation.forward_date, "forward_date")
        if forward_date <= signal_date:
            raise HTTPException(
                status_code=422,
                detail="forward_date must be after date to prevent look-ahead",
            )
        if not math.isfinite(observation.factor) or not math.isfinite(observation.forward_return):
            raise HTTPException(
                status_code=422,
                detail="factor and forward_return must be finite numbers",
            )
        rows.append(observation.model_dump())

    if req.neutralize_by_industry:
        rows = neutralize_factor(rows, group_key="industry")

    report = validate_factor_horizons(
        rows,
        factor_name=req.factor_name,
        horizons=req.horizons,
    )
    rolling = validate_factor_rolling(
        rows,
        factor_name=req.factor_name,
        train_dates=req.train_dates,
        test_dates=req.test_dates,
    )
    by_horizon = {
        str(horizon): asdict(result)
        for horizon, result in report.by_horizon.items()
    }
    return {
        "status": "ok" if any(item["usable"] for item in by_horizon.values()) else "insufficient_data",
        "factor_name": report.factor_name,
        "observation_count": len(rows),
        "point_in_time": True,
        "neutralized_by_industry": req.neutralize_by_industry,
        "by_horizon": by_horizon,
        "ic_decay": {str(key): value for key, value in report.ic_decay.items()},
        "spread_decay": {str(key): value for key, value in report.spread_decay.items()},
        "rolling": [
            {
                "start_date": window.start_date,
                "end_date": window.end_date,
                "result": asdict(window.result),
            }
            for window in rolling
        ],
        "weight_update": "not_applied",
    }


@router.post("/run")
async def run_research(
    pool_size: int = Query(20),
    top_n: int = Query(3),
    mode: str = Query("pipeline", description="pipeline / lite"),
):
    """Generate a research report from real scanner candidates or journal decisions."""
    from src.api.routes.scanner_routes import run_scanner

    started = time.perf_counter()
    candidates = []
    source = "scanner"
    scanner_error = ""
    try:
        scan = await run_scanner(top_n=max(top_n, min(pool_size, 20)))
        candidates = scan.get("candidates", [])[:top_n]
    except Exception as exc:
        scanner_error = f"{type(exc).__name__}: {exc}"
        candidates = []

    if not candidates:
        source = "decision_journal"
        for i, d in enumerate(get_journal_decisions(limit=top_n)):
            scores = decision_scores(d)
            candidates.append(
                {
                    "rank": i + 1,
                    "stock_code": d.get("stock_code", ""),
                    "stock_name": d.get("stock_name", ""),
                    "fusion_score": d.get("ai_score"),
                    "direction": d.get("direction", "neutral"),
                    "confidence": float(d.get("confidence") or 0),
                    "score_breakdown": scores,
                    "evidence": d.get("evidence") or d.get("recommendation") or "Pipeline decision",
                }
            )

    analyses = []
    for i, c in enumerate(candidates[:top_n]):
        raw_score = c.get("fusion_score") if c.get("fusion_score") is not None else c.get("score")
        try:
            parsed_score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            parsed_score = None
        score = parsed_score if parsed_score is not None and math.isfinite(parsed_score) else None
        evidence = c.get("evidence") or f"Top signal: {top_signal(c)}"
        analyses.append(
            {
                "rank": c.get("rank", i + 1),
                "stock_code": c.get("stock_code", ""),
                "stock_name": c.get("stock_name", ""),
                "score": round(score, 1) if score is not None else None,
                "direction": c.get("direction", "neutral"),
                "evidence_count": len(c.get("score_breakdown", {})),
                "reasoning": evidence,
                "risks": (
                    ["Score unavailable; do not use this row as a ranked recommendation"]
                    if score is None
                    else [] if score >= 65 else ["Score below buy-grade threshold"]
                ),
            }
        )

    if analyses:
        top_score = analyses[0]["score"]
        summary = (
            f"Real-data research found {len(analyses)} candidates; top score {top_score:.0f}."
            if top_score is not None
            else f"Real-data research found {len(analyses)} candidates; score unavailable."
        )
    else:
        summary = "No real scanner candidates or journal decisions are available yet."

    return {
        "report_id": f"research-{source}",
        "title": "Real Pipeline Research Report",
        "summary": summary,
        "market_overview": {"data_source": source},
        "candidates_count": len(analyses),
        "pipeline_duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "candidates": analyses,
        "final_report": summary,
        "data_source": source,
        "data_status": "scanner" if source == "scanner" else "journal_fallback" if analyses else "no_data",
        "degraded": source != "scanner" or bool(scanner_error),
        "fallback_reason": scanner_error if source != "scanner" else "",
        "mode": mode,
    }
