"""Research routes backed by real scanner output and decision journal."""

from fastapi import APIRouter, Query

from src.api.routes.journal_utils import decision_scores, get_journal_decisions, top_signal

router = APIRouter(tags=["research"], prefix="/research")


@router.post("/run")
async def run_research(
    pool_size: int = Query(20),
    top_n: int = Query(3),
    mode: str = Query("pipeline", description="pipeline / lite"),
):
    """Generate a research report from real scanner candidates or journal decisions."""
    from src.api.routes.scanner_routes import run_scanner

    candidates = []
    source = "scanner"
    try:
        scan = await run_scanner(top_n=max(top_n, min(pool_size, 20)))
        candidates = scan.get("candidates", [])[:top_n]
    except Exception:
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
                    "fusion_score": float(d.get("ai_score") or 50),
                    "direction": d.get("direction", "neutral"),
                    "confidence": float(d.get("confidence") or 0),
                    "score_breakdown": scores,
                    "evidence": d.get("evidence") or d.get("recommendation") or "Pipeline decision",
                }
            )

    analyses = []
    for i, c in enumerate(candidates[:top_n]):
        score = float(c.get("fusion_score") or c.get("score") or 50)
        evidence = c.get("evidence") or f"Top signal: {top_signal(c)}"
        analyses.append(
            {
                "rank": c.get("rank", i + 1),
                "stock_code": c.get("stock_code", ""),
                "stock_name": c.get("stock_name", ""),
                "score": round(score, 1),
                "direction": c.get("direction", "neutral"),
                "evidence_count": len(c.get("score_breakdown", {})),
                "reasoning": evidence,
                "risks": [] if score >= 65 else ["Score below buy-grade threshold"],
            }
        )

    if analyses:
        summary = f"Real-data research found {len(analyses)} candidates; top score {analyses[0]['score']:.0f}."
    else:
        summary = "No real scanner candidates or journal decisions are available yet."

    return {
        "report_id": f"research-{source}",
        "title": "Real Pipeline Research Report",
        "summary": summary,
        "market_overview": {"data_source": source},
        "candidates_count": len(analyses),
        "pipeline_duration_ms": 0,
        "candidates": analyses,
        "final_report": summary,
        "data_source": source,
        "mode": mode,
    }
