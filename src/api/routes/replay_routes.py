"""Replay & Simulation Engine Routes — v7.1.

  POST /replay/freeze       — Freeze world state at a date
  POST /replay/rerun        — Deterministic rerun
  POST /replay/compare      — Compare model versions
  POST /replay/simulate     — Scenario simulation
  GET  /replay/history      — Past replay runs
  GET  /replay/report/{date} — Replay report for a date
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.replay.engine import get_replay_engine

router = APIRouter(tags=["replay"], prefix="/replay")


class FreezeRequest(BaseModel):
    target_date: str = "2024-09-10"
    pool_size: int = 30
    knowledge_version: str = "v12"
    prompt_version: str = "v5.1"
    model_version: str = "v6.0"


class CompareRequest(BaseModel):
    target_date: str = "2024-09-10"
    versions: list[str] = ["v4.0", "v4.2", "v5.0", "v6.0"]


class SimulateRequest(BaseModel):
    target_date: str = "2024-09-10"
    scenarios: list[dict] = []


@router.post("/freeze")
async def freeze_world(req: FreezeRequest):
    """Layer 1: Freeze entire world state at a point in time."""
    engine = get_replay_engine()
    ctx = engine.freeze_world(
        target_date=req.target_date,
        knowledge_version=req.knowledge_version,
        prompt_version=req.prompt_version,
        model_version=req.model_version,
    )
    return {"context": ctx.to_dict()}


@router.post("/rerun")
async def rerun(req: FreezeRequest):
    """Layer 2: Deterministic rerun of the AI pipeline."""
    engine = get_replay_engine()
    ctx = engine.freeze_world(
        target_date=req.target_date,
        knowledge_version=req.knowledge_version,
        prompt_version=req.prompt_version,
        model_version=req.model_version,
    )
    result = await engine.rerun(ctx)
    return result.to_dict()


@router.post("/compare")
async def compare_models(req: CompareRequest):
    """Layer 3: Compare AI model versions on same historical data."""
    engine = get_replay_engine()
    result = await engine.compare_models(req.target_date, req.versions)
    return result.to_dict()


@router.post("/simulate")
async def simulate(req: SimulateRequest):
    """Layer 4: Run what-if scenarios."""
    engine = get_replay_engine()
    result = await engine.simulate(req.target_date, req.scenarios or None)
    return result.to_dict()


@router.get("/history")
async def replay_history():
    """Past replay runs."""
    engine = get_replay_engine()
    history = {}
    for date_str, runs in engine._replay_runs.items():
        history[date_str] = [r.to_dict() for r in runs]
    return {"history": history, "total_dates": len(history)}


@router.get("/report/{target_date}")
async def replay_report(target_date: str):
    """Generate a complete replay report for a date."""
    engine = get_replay_engine()

    # Run all four layers
    ctx = engine.freeze_world(target_date)
    rerun_result = await engine.rerun(ctx)
    compare_result = await engine.compare_models(target_date)
    sim_result = await engine.simulate(target_date)

    # Generate human-readable report
    report = {
        "date": target_date,
        "context": ctx.to_dict(),
        "pipeline_result": {
            "scanned": rerun_result.total_scanned,
            "candidates": rerun_result.candidates_found,
            "top_pick": rerun_result.candidates[0] if rerun_result.candidates else None,
            "is_deterministic": rerun_result.is_deterministic,
            "result_hash": rerun_result.current_hash,
        },
        "model_comparison": {
            "improvement": compare_result.improvement_summary,
            "best_version": compare_result.best_version,
            "accuracy_by_version": compare_result.accuracy_change,
        },
        "simulation": {
            "best_scenario": sim_result.best_scenario,
            "best_alpha": sim_result.best_alpha_pct,
            "insights": sim_result.insights,
            "scenario_results": sim_result.results,
        },
        "summary": _generate_report_summary(
            target_date, rerun_result, compare_result, sim_result
        ),
    }
    return report


def _generate_report_summary(
    date: str, rerun, compare, sim
) -> str:
    """Generate human-readable report summary."""
    parts = [f"## Replay Report — {date}\n"]

    parts.append("### 市场环境")
    parts.append(f"- 指数: {rerun.context.index_level:.0f} ({rerun.context.index_change_pct:+.1f}%)")
    parts.append(f"- 涨跌比: {rerun.context.market_breadth_up}/{rerun.context.market_breadth_down}")
    parts.append(f"- 北向资金: {rerun.context.northbound_flow:+.0f}亿")
    parts.append("")

    parts.append("### AI 推荐")
    parts.append(f"- 扫描{rerun.total_scanned}只, 发现{rerun.candidates_found}只候选")
    parts.append(f"- 买入信号: {rerun.buy_signals}个")
    parts.append(f"- 确定性: {'✓ 已验证' if rerun.is_deterministic else '⏳ 首次运行' if rerun.is_deterministic is None else '✗ 不一致'}")
    parts.append("")

    parts.append("### 模型对比")
    parts.append(f"- {compare.improvement_summary}")
    parts.append("")

    parts.append("### 策略实验")
    for insight in sim.insights:
        parts.append(f"- {insight}")

    return "\n".join(parts)
