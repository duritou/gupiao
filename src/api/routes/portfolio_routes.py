"""Portfolio routes backed by real pipeline decisions."""

from datetime import date

from fastapi import APIRouter

from src.api.routes.journal_utils import (
    empty_journal_response,
    get_journal_decisions,
    latest_close,
    recommendation_from_score,
    risk_level,
    top_signal,
)
from src.domain.models.portfolio import Portfolio, Position

router = APIRouter(tags=["portfolio"], prefix="/portfolio")


@router.get("/overview")
async def portfolio_overview():
    """Return the real pipeline watchlist in the Portfolio page shape.

    There is no persisted user holdings table yet, so this endpoint does not
    invent shares, costs, market value, or P/L. It exposes real decision
    journal names and scores, with money fields intentionally zero.
    """
    today = date.today().isoformat()
    decisions = get_journal_decisions(limit=30)
    if not decisions:
        portfolio = Portfolio(date=today, ai_summary="No real pipeline decisions yet.")
        return {**empty_journal_response(), **portfolio.to_dict()}

    positions: list[Position] = []
    for d in decisions[:12]:
        code = str(d.get("stock_code") or "")
        score = float(d.get("ai_score") or 50)
        confidence = float(d.get("confidence") or 0)
        current_price = await latest_close(code)
        positions.append(
            Position(
                stock_code=code,
                stock_name=str(d.get("stock_name") or code),
                shares=0,
                cost_price=0,
                current_price=current_price,
                market_value=0,
                cost_value=0,
                profit_loss=0,
                profit_loss_pct=0,
                weight_pct=0,
                ai_score=score,
                ai_direction=str(d.get("direction") or "neutral"),
                ai_signal=top_signal(d),
                risk_level=risk_level(confidence),
                added_date=str(d.get("decision_date") or ""),
                last_score_change=score - float(d.get("fusion_score") or score),
            )
        )

    positions.sort(key=lambda p: p.ai_score, reverse=True)
    avg_score = sum(p.ai_score for p in positions) / len(positions)
    buy_count = sum(
        1
        for p in positions
        if recommendation_from_score(p.ai_score, p.ai_direction) in {"buy", "strong_buy"}
    )
    sell_count = sum(1 for p in positions if p.ai_direction == "sell" or p.ai_score < 40)
    top = positions[0]
    worst = positions[-1]

    portfolio = Portfolio(
        date=today,
        total_value=0,
        total_cost=0,
        total_pl=0,
        total_pl_pct=0,
        daily_pl=0,
        daily_pl_pct=0,
        cash=0,
        positions=positions,
        ai_summary=(
            f"Pipeline watchlist from decision journal: average score {avg_score:.0f}; "
            f"{buy_count} buy-grade names, {sell_count} risk-off names."
        ),
        risk_summary="No real holdings table is configured; money and P/L fields are zero.",
        top_performer=f"{top.stock_name}({top.ai_score:.0f})",
        worst_performer=f"{worst.stock_name}({worst.ai_score:.0f})",
    )
    result = portfolio.to_dict()
    result["avg_ai_score"] = round(avg_score, 1)
    result["data_source"] = "decision_journal (real AI pipeline)"
    result["portfolio_mode"] = "pipeline_watchlist"
    return result
