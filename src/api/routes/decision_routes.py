"""Decision Center API — v8.0. Daily prioritized action list."""

from fastapi import APIRouter, Query

from src.explain.decision_center import decision_center
from src.shared.mock_data import STOCK_NAMES, generate_stock_pool, mock_signal_result

router = APIRouter(tags=["decision"], prefix="/decision")


@router.get("/today")
async def daily_decisions():
    """Today's prioritized decision list with Bull/Bear analysis.

    Combines portfolio positions + scanner candidates + personal history
    → ranked actionable items.
    """
    import hashlib
    import random
    from datetime import date

    today_seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16)
    rng = random.Random(today_seed)

    # Generate portfolio
    portfolio = [
        {"stock_code": "688256.SH", "stock_name": "寒武纪", "ai_score": 92, "weight_pct": 25, "ai_direction": "buy"},
        {"stock_code": "002371.SZ", "stock_name": "北方华创", "ai_score": 88, "weight_pct": 20, "ai_direction": "buy"},
        {"stock_code": "300308.SZ", "stock_name": "中际旭创", "ai_score": 85, "weight_pct": 18, "ai_direction": "buy"},
        {"stock_code": "688981.SH", "stock_name": "中芯国际", "ai_score": 72, "weight_pct": 15, "ai_direction": "neutral"},
        {"stock_code": "600519.SH", "stock_name": "贵州茅台", "ai_score": 58, "weight_pct": 22, "ai_direction": "neutral"},
    ]

    # Generate scanner candidates
    pool = generate_stock_pool(20)
    candidates = []
    for i, p in enumerate(pool[:8]):
        if p["code"] in [pos["stock_code"] for pos in portfolio]:
            continue
        sig = mock_signal_result(p["code"], [])
        candidates.append({
            "stock_code": p["code"],
            "stock_name": p.get("name", STOCK_NAMES.get(p["code"], p["code"])),
            "fusion_score": sig["fusion_score"],
            "direction": sig["direction"],
        })

    # User history (simulated personal memory)
    user_history = {
        "688256.SH": {"trades": 6, "wins": 5, "last_action": "2026-06-28 买入", "total_return": 31.2},
        "002371.SZ": {"trades": 4, "wins": 3, "last_action": "2026-07-02 加仓", "total_return": 18.5},
        "600519.SH": {"trades": 8, "wins": 3, "last_action": "2026-06-15 减仓", "total_return": -12.3},
        "000725.SZ": {"trades": 2, "wins": 1, "last_action": "2026-05-20 卖出", "total_return": 5.8},
    }

    decisions = decision_center.generate_daily_decisions(
        scanner_candidates=candidates,
        portfolio_positions=portfolio,
        user_history=user_history,
    )

    return {
        "date": date.today().isoformat(),
        "total_items": len(decisions),
        "urgent_count": sum(1 for d in decisions if d.urgency == "today"),
        "decisions": [d.to_dict() for d in decisions],
        "summary": _generate_summary(decisions),
    }


def _generate_summary(decisions) -> str:
    urgent = [d for d in decisions if d.urgency == "today"]
    if urgent:
        return f"今日{len(urgent)}条紧急建议需要关注。优先级最高: {urgent[0].stock_name}。"
    return f"今日{len(decisions)}条建议，暂无紧急操作。保持现有仓位。"
