"""Trust API Routes — v7.6: reads from real decision journal.

Trust metrics come from the decision_journal SQLite table.
When decisions exist → real stats. When empty → honest "数据积累中".
Trust is earned from real AI decisions.
"""

from fastapi import APIRouter, Query

from src.infrastructure.storage.market_database import market_db

router = APIRouter(tags=["trust"], prefix="/trust")


@router.get("/track-record")
async def track_record(days: int = Query(30, ge=7, le=365)):
    stats = market_db.get_decision_stats()
    total = stats["total_decisions"]
    if total == 0:
        return _insufficient("track-record", days)
    return {
        "status": "live",
        "period_days": days,
        "total_decisions": total,
        "verified_decisions": stats["verified_decisions"],
        "correct_decisions": stats["correct_decisions"],
        "accuracy": stats["accuracy"],
        "by_direction": stats["by_direction"],
        "message": f"AI 共产生 {total} 条决策，已验证 {stats['verified_decisions']} 条",
    }


@router.get("/ai-alpha")
async def ai_alpha(days: int = Query(90, ge=30, le=365)):
    stats = market_db.get_decision_stats()
    if stats["total_decisions"] == 0:
        return _insufficient("ai-alpha", days)
    return {
        "status": "live",
        "period_days": days,
        "total_decisions": stats["total_decisions"],
        "verified_decisions": stats["verified_decisions"],
        "accuracy": stats["accuracy"],
        "message": f"AI Alpha 将随验证结果积累而自动计算。当前已积累 {stats['total_decisions']} 条决策。",
    }


@router.get("/journal")
async def journal(limit: int = Query(30, ge=1, le=100)):
    decisions = market_db.get_recent_decisions(limit)
    return {
        "status": "live" if decisions else "accumulating",
        "total_entries": len(decisions),
        "entries": [
            {
                "id": d["id"],
                "date": d["decision_date"],
                "stock_code": d["stock_code"],
                "stock_name": d["stock_name"],
                "ai_score": d["ai_score"],
                "direction": d["direction"],
                "recommendation": d["recommendation"],
                "outcome_known": bool(d["outcome_known"]),
                "was_correct": d["was_correct"],
            }
            for d in decisions
        ],
    }


@router.get("/journal/summary")
async def journal_summary():
    stats = market_db.get_decision_stats()
    return {
        "status": "live" if stats["total_decisions"] > 0 else "accumulating",
        **stats,
    }


@router.get("/resume")
async def resume():
    stats = market_db.get_decision_stats()
    total = stats["total_decisions"]
    return {
        "status": "live" if total > 0 else "accumulating",
        "total_decisions": total,
        "verified_decisions": stats["verified_decisions"],
        "accuracy": stats["accuracy"],
        "message": (
            f"AI 已产生 {total} 条真实决策。"
            f"随着验证结果积累，Resume 将自动更新。"
            if total > 0 else "尚无决策记录。运行 AI Pipeline 后自动生成。"
        ),
    }


@router.get("/strategies")
async def strategies():
    return {"status": "pending", "message": "策略分解将在积累 30+ 条验证记录后自动生成"}


@router.get("/score-ranges")
async def score_ranges():
    return {"status": "pending", "message": "评分区间分析将在积累 30+ 条验证记录后自动生成"}


@router.get("/model-evolution")
async def model_evolution():
    return {"status": "pending", "message": "模型演进将在积累多个版本数据后自动生成"}


@router.get("/monthly")
async def monthly():
    return {"status": "pending", "message": "月度趋势将在积累 3+ 个月数据后自动生成"}


@router.get("/snapshot/{snapshot_id}")
async def snapshot(snapshot_id: str):
    return {"status": "not_found", "snapshot_id": snapshot_id}


def _insufficient(endpoint: str, days: int) -> dict:
    return {
        "status": "insufficient_data",
        "endpoint": endpoint,
        "requested_days": days,
        "message": "尚无 AI 决策记录。运行 AI Pipeline Runner 后自动生成。",
        "next_step": "调用 /api/v1/ai-os/run-pipeline 启动 AI 决策流水线",
    }
