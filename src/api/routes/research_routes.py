"""Research Pipeline routes"""

from fastapi import APIRouter, Query

router = APIRouter(tags=["research"], prefix="/research")


@router.post("/run")
async def run_research(
    pool_size: int = Query(20),
    top_n: int = Query(3),
    mode: str = Query("pipeline", description="pipeline / lite"),
):
    """运行完整研究管线 → 生成研究报告"""
    import math
    from src.scanner.engine import ScannerConfig
    from src.pipeline.research_pipeline import ResearchPipeline
    from src.agents.orchestrator import AgentOrchestrator

    # 构造模拟数据
    pool = []
    for i in range(pool_size):
        code = f"{600000 + i:06d}.SH" if i < pool_size // 2 else f"{i - pool_size // 2:06d}.SZ"
        pool.append({
            "code": code, "name": f"研究标的{i}",
            "market_cap": 50 + i * 5, "avg_amount": 100 + i * 3,
            "price": 10.0 + i * 0.5, "change_pct": (i - pool_size // 2) * 0.4,
        })

    klines = {}
    for i in range(min(10, pool_size)):
        code = pool[i]["code"]
        trend = []
        for j in range(80):
            p = 10.0 + j * 0.1 + math.sin(j * 0.15) * 0.5
            trend.append({"close": p, "open": p - 0.03, "high": p + 0.08,
                         "low": p - 0.06, "volume": 1000000 + j * 10000})
        klines[code] = trend

    # Pipeline
    pipeline = ResearchPipeline(scanner_config=ScannerConfig(score_top_n=top_n))
    report = await pipeline.run(pool, klines, title="API研究日报")

    # Agent
    orch = AgentOrchestrator()
    candidates_for_agent = [
        {
            "stock_code": c.stock_code, "stock_name": c.stock_name,
            "fusion_score": c.fusion_score, "direction": c.direction,
            "confidence": c.confidence, "rank": c.rank,
            "evidence": [
                {"source": f"signal:{sig}", "description": f"{sig}评分{s:.0f}", "score_contribution": s - 50}
                for sig, s in (c.score_breakdown or {}).items()
            ],
        }
        for c in report.candidates
    ]

    if mode == "lite":
        agent_result = await orch.run_lite(candidates_for_agent, title="API研究日报")
    else:
        agent_result = await orch.run_pipeline(candidates_for_agent, title="API研究日报",
                                               summary=report.summary)

    return {
        "report_id": report.report_id,
        "title": report.title,
        "summary": report.summary,
        "market_overview": report.market_overview,
        "candidates_count": len(report.candidates),
        "pipeline_duration_ms": report.pipeline_duration_ms,
        "candidates": [
            {
                "rank": c.get("rank", i + 1),
                "stock_code": c.get("stock_code", ""),
                "stock_name": c.get("stock_name", ""),
                "score": c.get("score", 0),
                "direction": c.get("direction", "neutral"),
                "evidence_count": c.get("evidence_count", 0),
                "reasoning": c.get("reasoning", ""),
                "risks": c.get("risks", []),
            }
            for i, c in enumerate(agent_result.analyst_result.output.get("analyses", []))
            if agent_result.analyst_result
        ],
        "final_report": agent_result.final_report[:2000] if agent_result.final_report else "",
    }
