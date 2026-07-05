"""Portfolio routes — position tracking + AI rescoring."""

from datetime import date

from fastapi import APIRouter

from src.domain.models.portfolio import Portfolio, Position
from src.shared.mock_data import mock_signal_result, generate_klines, get_stock_name

router = APIRouter(tags=["portfolio"], prefix="/portfolio")


# Demo portfolio data
DEMO_POSITIONS = [
    {"code": "688256.SH", "shares": 500, "cost": 220.0, "added": "2026-05-15"},
    {"code": "002371.SZ", "shares": 1000, "cost": 180.0, "added": "2026-06-01"},
    {"code": "300308.SZ", "shares": 800, "cost": 95.0, "added": "2026-06-20"},
    {"code": "688981.SH", "shares": 1200, "cost": 55.0, "added": "2026-04-10"},
    {"code": "600519.SH", "shares": 100, "cost": 1380.0, "added": "2026-03-01"},
]


@router.get("/overview")
async def portfolio_overview():
    """Get complete portfolio snapshot with AI rescoring."""
    today = date.today().isoformat()
    positions: list[Position] = []
    total_value = 0.0
    total_cost = 0.0

    for dp in DEMO_POSITIONS:
        code = dp["code"]
        name = get_stock_name(code)
        klines = generate_klines(code, 80, "up")
        signal = mock_signal_result(code, klines)

        current_price = signal["price"]
        shares = dp["shares"]
        cost_price = dp["cost"]
        market_value = shares * current_price
        cost_value = shares * cost_price
        pl = market_value - cost_value
        pl_pct = (current_price / cost_price - 1) * 100

        total_value += market_value
        total_cost += cost_value

        positions.append(Position(
            stock_code=code,
            stock_name=name,
            shares=shares,
            cost_price=cost_price,
            current_price=current_price,
            market_value=market_value,
            cost_value=cost_value,
            profit_loss=pl,
            profit_loss_pct=pl_pct,
            ai_score=signal["fusion_score"],
            ai_direction=signal["direction"],
            ai_signal=signal["top_signal"],
            risk_level=signal["risk_level"],
            added_date=dp["added"],
            last_score_change=signal["fusion_score"] - 75,
        ))

    # Calculate weights
    for p in positions:
        p.weight_pct = (p.market_value / total_value * 100) if total_value > 0 else 0

    total_pl = total_value - total_cost
    total_pl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0
    daily_pl = total_value * 0.01  # mock 1% daily change
    daily_pl_pct = 1.0

    # Sort by AI score
    positions.sort(key=lambda p: p.ai_score, reverse=True)

    # AI Summary
    buy_count = sum(1 for p in positions if p.ai_score >= 65)
    sell_count = sum(1 for p in positions if p.ai_score <= 35)
    avg_score = sum(p.ai_score * p.weight_pct for p in positions) / 100

    if avg_score >= 70:
        ai_summary = f"持仓整体评分{avg_score:.0f}，偏积极。{buy_count}只标的看多信号明显，建议维持现有仓位。"
    elif avg_score >= 50:
        ai_summary = f"持仓评分{avg_score:.0f}，中性偏稳。关注{buy_count}只强势标的，{sell_count}只标的信号偏弱需留意。"
    else:
        ai_summary = f"持仓评分{avg_score:.0f}，偏谨慎。{sell_count}只标的信号走弱，建议减仓或设置止损。"

    risk_summary = (
        f"仓位集中度{'偏高' if max(p.weight_pct for p in positions) > 30 else '适中'}，"
        f"最大持仓{max(positions, key=lambda p: p.weight_pct).stock_name}"
        f"({max(p.weight_pct for p in positions):.0f}%)"
    )

    top = max(positions, key=lambda p: p.profit_loss_pct)
    worst = min(positions, key=lambda p: p.profit_loss_pct)

    portfolio = Portfolio(
        date=today,
        total_value=total_value,
        total_cost=total_cost,
        total_pl=total_pl,
        total_pl_pct=total_pl_pct,
        daily_pl=daily_pl,
        daily_pl_pct=daily_pl_pct,
        cash=total_value * 0.1,
        positions=positions,
        ai_summary=ai_summary,
        risk_summary=risk_summary,
        top_performer=f"{top.stock_name}(+{top.profit_loss_pct:.1f}%)",
        worst_performer=f"{worst.stock_name}({worst.profit_loss_pct:.1f}%)",
    )

    return portfolio.to_dict()
