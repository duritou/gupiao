"""Point-in-time Replay, policy comparison, and observed-path simulation routes."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.replay.engine import get_replay_engine

router = APIRouter(tags=["replay"], prefix="/replay")


def _today() -> str:
    return date.today().isoformat()


def _validated_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="target_date must be YYYY-MM-DD") from exc


class FreezeRequest(BaseModel):
    target_date: str = Field(default_factory=_today)
    pool_size: int = Field(default=200, ge=1, le=500)
    knowledge_version: str = "journal"
    prompt_version: str = "journal"
    model_version: str = "balanced-v2"
    horizon_days: int = Field(default=5, ge=1, le=20)
    metadata_policy: str = "auto"


class CompareRequest(BaseModel):
    target_date: str = Field(default_factory=_today)
    versions: list[str] = Field(
        default_factory=lambda: ["technical-v1", "balanced-v2", "defensive-v2"]
    )
    pool_size: int = Field(default=200, ge=1, le=500)
    horizon_days: int = Field(default=5, ge=1, le=20)
    metadata_policy: str = "auto"


class SimulateRequest(BaseModel):
    target_date: str = Field(default_factory=_today)
    scenarios: list[dict] = Field(default_factory=list)
    pool_size: int = Field(default=200, ge=1, le=500)
    metadata_policy: str = "auto"


@router.get("/dates")
async def replay_dates(limit: int = Query(60, ge=1, le=365)):
    """Dates with exact journal snapshots and local bar availability."""
    from src.infrastructure.storage.market_database import market_db

    engine = get_replay_engine()
    dates = market_db.get_replay_dates(limit=limit)
    return {
        "dates": dates,
        "default_date": next(
            (item["date"] for item in dates if item["evaluation_ready"]),
            dates[0]["date"] if dates else "",
        ),
        "models": engine.available_models(),
        "data_source": "decision_journal + market_daily",
    }


@router.post("/freeze")
async def freeze_world(req: FreezeRequest):
    """Freeze exact-date decisions and point-in-time market breadth."""
    engine = get_replay_engine()
    ctx = engine.freeze_world(
        target_date=_validated_date(req.target_date),
        pool_size=req.pool_size,
        knowledge_version=req.knowledge_version,
        prompt_version=req.prompt_version,
        model_version=req.model_version,
        metadata_policy=req.metadata_policy,
    )
    return {"context": ctx.to_dict()}


@router.post("/rerun")
async def rerun(req: FreezeRequest):
    """Recompute signals using only bars observable at the selected date."""
    engine = get_replay_engine()
    ctx = engine.freeze_world(
        target_date=_validated_date(req.target_date),
        pool_size=req.pool_size,
        knowledge_version=req.knowledge_version,
        prompt_version=req.prompt_version,
        model_version=req.model_version,
        metadata_policy=req.metadata_policy,
    )
    result = await engine.rerun(ctx, horizon_days=req.horizon_days)
    return result.to_dict()


@router.post("/compare")
async def compare_models(req: CompareRequest):
    """Compare real scoring policies on one frozen universe and future path."""
    engine = get_replay_engine()
    result = await engine.compare_models(
        _validated_date(req.target_date),
        req.versions,
        pool_size=req.pool_size,
        horizon_days=req.horizon_days,
        metadata_policy=req.metadata_policy,
    )
    return result.to_dict()


@router.post("/simulate")
async def simulate(req: SimulateRequest):
    """Evaluate threshold/position/holding scenarios on observed future bars."""
    engine = get_replay_engine()
    result = await engine.simulate(
        _validated_date(req.target_date),
        req.scenarios or None,
        pool_size=req.pool_size,
        metadata_policy=req.metadata_policy,
    )
    return result.to_dict()


@router.get("/history")
async def replay_history(limit: int = Query(50, ge=1, le=200)):
    """Persisted replay history; survives backend and extension restarts."""
    from src.infrastructure.storage.market_database import market_db

    runs = market_db.get_replay_runs(limit=limit)
    return {
        "runs": runs,
        "total_runs": len(runs),
        "data_source": "replay_run",
    }


@router.get("/report/{target_date}")
async def replay_report(
    target_date: str,
    pool_size: int = Query(200, ge=1, le=500),
    horizon_days: int = Query(5, ge=1, le=20),
    model_version: str = Query("balanced-v2"),
    metadata_policy: str = Query("auto"),
):
    """Generate one complete, lookahead-safe replay report."""
    target_date = _validated_date(target_date)
    engine = get_replay_engine()
    ctx = engine.freeze_world(
        target_date,
        pool_size=pool_size,
        model_version=model_version,
        metadata_policy=metadata_policy,
    )
    rerun_result = await engine.rerun(ctx, horizon_days=horizon_days)
    compare_result = await engine.compare_models(
        target_date,
        pool_size=pool_size,
        horizon_days=horizon_days,
        metadata_policy=metadata_policy,
    )
    simulation_result = await engine.simulate(
        target_date, pool_size=pool_size, metadata_policy=metadata_policy
    )

    report = {
        "status": ctx.status if ctx.status != "ok" else rerun_result.status,
        "message": ctx.message or rerun_result.message,
        "date": target_date,
        "market_data_date": ctx.market_data_date,
        "lookahead_safe": ctx.lookahead_safe,
        # What these numbers are and are not about.  "lookahead_safe" answers
        # whether the replay respected the point-in-time cutoff; it does not
        # mean the live strategy has been validated, and the two get conflated
        # the moment this reaches a screen without saying so.
        "scope": {
            "replays": "技术指标评分口径（macd/rsi/kdj/ma/volume/boll 的固定权重向量）",
            "does_not_replay": (
                "线上决策管道 —— 横截面评分、证据门禁、AI 深度分析与终审均未参与"
            ),
            "accuracy_is_about": "被重放的评分配置，不是 live strategy 的验证结论",
        },
        "market_regime": ctx.market_regime,
        "context": ctx.to_dict(),
        "pipeline_result": {
            "status": rerun_result.status,
            "scanned": rerun_result.total_scanned,
            "candidates": rerun_result.candidates_found,
            "candidate_rows": rerun_result.to_dict()["candidates"],
            "top_pick": rerun_result.candidates[0] if rerun_result.candidates else None,
            "is_deterministic": rerun_result.is_deterministic,
            "result_hash": rerun_result.current_hash,
            "model_version": rerun_result.model_version,
            "model_label": rerun_result.model_label,
            "evaluated_count": rerun_result.evaluated_count,
            "correct_count": rerun_result.correct_count,
            "accuracy": rerun_result.accuracy,
            "avg_forward_return_pct": rerun_result.avg_forward_return_pct,
            "horizon_days": rerun_result.horizon_days,
        },
        "model_comparison": {
            "status": compare_result.status,
            "improvement": compare_result.improvement_summary,
            "best_version": compare_result.best_version,
            "best_accuracy": compare_result.best_accuracy,
            "accuracy_by_version": compare_result.accuracy_by_version,
            "metrics": compare_result.metrics,
        },
        "simulation": {
            "status": simulation_result.status,
            "best_scenario": simulation_result.best_scenario,
            "best_alpha": simulation_result.best_alpha_pct,
            "insights": simulation_result.insights,
            "scenario_results": simulation_result.results,
        },
        "summary": _generate_report_summary(
            target_date, rerun_result, compare_result, simulation_result
        ),
    }
    return report


def _generate_report_summary(target_date: str, rerun, compare, simulation) -> str:
    """Generate a concise Chinese audit summary for the Replay page."""
    if rerun.status not in ("ok", "insufficient_history"):
        return f"## Replay Report — {target_date}\n\n{rerun.message}"

    context = rerun.context
    parts = [f"## Replay Report — {target_date}", ""]
    parts.extend([
        "### 冻结环境",
        f"- 决策日: {target_date}；行情截点: {context.market_data_date}",
        f"- 涨跌家数: {context.market_breadth_up}/{context.market_breadth_down}",
        f"- 市场覆盖: {context.market_coverage}只；未来数据未进入信号计算",
        "",
        "### 历史重算",
        f"- 成功重算 {rerun.total_scanned} 只，方向信号 {rerun.candidates_found} 个",
        f"- 使用策略: {rerun.model_label} ({rerun.model_version})",
    ])
    if rerun.accuracy is None:
        parts.append(f"- {rerun.horizon_days}日结果尚不可验证")
    else:
        parts.append(
            f"- {rerun.horizon_days}日方向准确率: {rerun.accuracy:.1%} "
            f"({rerun.correct_count}/{rerun.evaluated_count})"
        )
    parts.extend(["", "### 策略对比", f"- {compare.improvement_summary}", "", "### 场景实验"])
    parts.extend(f"- {insight}" for insight in simulation.insights)
    return "\n".join(parts)
