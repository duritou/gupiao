"""Portfolio routes backed by real pipeline decisions."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.api.routes.journal_utils import decision_scores, risk_level, top_signal
from src.domain.models.portfolio import Portfolio, Position

router = APIRouter(tags=["portfolio"], prefix="/portfolio")


_RISK_LABELS = {"low": "低", "medium": "中", "high": "高"}


def _position_risk_level(decision: dict[str, Any] | None, weight_pct: float) -> str:
    """Map the latest decision and position concentration to a risk label."""
    if not decision:
        return "未知"

    score = float(decision.get("ai_score") or decision.get("fusion_score") or 50)
    confidence = float(decision.get("confidence") or 0)
    signals = decision_scores(decision)
    signal_spread = max(signals.values()) - min(signals.values())
    base = risk_level(confidence)

    # Low confidence, weak scores, or disagreeing indicators should never be
    # presented as low risk. Concentration adds portfolio-level risk.
    if score < 40 or base == "high" or signal_spread >= 35 or weight_pct > 20:
        return "高"
    if score < 55 or base == "medium" or weight_pct >= 15:
        return "中"
    return _RISK_LABELS[base]


def _build_ai_summary(
    positions: list[Position], known_count: int, latest_score_at: str
) -> str:
    if not positions:
        return "当前无持仓，暂无 AI 持仓评分。"
    market_value = sum(position.market_value for position in positions)
    weighted_score = sum(
        position.ai_score * position.market_value for position in positions
    )
    average = weighted_score / market_value if market_value else 50.0
    coverage = known_count / len(positions) * 100
    updated = latest_score_at.replace("T", " ")[:19] if latest_score_at else "暂无"
    return (
        f"AI 持仓评分 {average:.1f}，已接入 {known_count}/{len(positions)} 只持仓的最新决策 "
        f"（覆盖率 {coverage:.0f}%）。评分更新时间：{updated}。"
    )


def _build_risk_summary(
    positions: list[Position],
    cash: float,
    total_value: float,
    stale_positions: list[str],
    known_count: int,
) -> tuple[str, str]:
    """Build a transparent portfolio-level risk assessment from live fields."""
    if not positions:
        return "低", "组合风险等级：低。当前无持仓，主要风险来自未来建仓。"

    high_count = sum(position.risk_level == "高" for position in positions)
    medium_count = sum(position.risk_level == "中" for position in positions)
    max_weight = max((position.weight_pct for position in positions), default=0.0)
    cash_pct = cash / total_value * 100 if total_value else 0.0
    weak_count = sum(position.ai_score < 50 for position in positions)

    if high_count or stale_positions or cash_pct < 10 or max_weight > 20:
        overall = "高"
    elif medium_count or weak_count or cash_pct < 15:
        overall = "中"
    else:
        overall = "低"

    reasons: list[str] = []
    if high_count:
        reasons.append(f"{high_count} 只持仓个股风险较高")
    if medium_count and not high_count:
        reasons.append(f"{medium_count} 只持仓处于中风险")
    if weak_count:
        reasons.append(f"{weak_count} 只持仓 AI 评分低于 50")
    if max_weight > 20:
        reasons.append(f"最高仓位 {max_weight:.1f}% 超过 20%")
    if cash_pct < 10:
        reasons.append(f"现金比例仅 {cash_pct:.1f}%")
    if stale_positions:
        reasons.append(f"{len(stale_positions)} 只持仓行情不是最新交易日")
    if not reasons:
        reasons.append("当前持仓分散度、现金比例和行情新鲜度均在监控范围内")

    coverage = f"AI 决策覆盖 {known_count}/{len(positions)} 只持仓"
    return overall, f"组合风险等级：{overall}。{coverage}；" + "；".join(reasons) + "。"


@router.get("/overview")
async def portfolio_overview():
    """Return the persistent paper account from its latest marked snapshot."""
    from src.infrastructure.storage.market_database import market_db

    paper = market_db.get_paper_portfolio()
    raw_positions = paper["positions"]
    decision_history = market_db.get_decision_history_for_codes(
        [str(position["stock_code"]) for position in raw_positions],
        limit_per_code=2,
    )
    positions: list[Position] = []
    latest_score_at = ""
    known_count = 0
    for p in raw_positions:
        history = decision_history.get(str(p["stock_code"]).strip().upper(), [])
        decision = history[0] if history else None
        previous = history[1] if len(history) > 1 else None
        score = float(
            (decision or {}).get("ai_score")
            or (decision or {}).get("fusion_score")
            or 50
        )
        previous_score = float(
            (previous or {}).get("ai_score")
            or (previous or {}).get("fusion_score")
            or score
        )
        known_count += int(decision is not None)
        created_at = str((decision or {}).get("created_at") or "")
        if created_at > latest_score_at:
            latest_score_at = created_at
        weight_pct = (
            p["market_value"] / paper["total_value"] * 100
            if paper["total_value"] else 0
        )
        direction = str(
            (decision or {}).get("effective_direction")
            or (decision or {}).get("direction")
            or "neutral"
        ).lower()
        positions.append(Position(
            stock_code=p["stock_code"], stock_name=p["stock_name"],
            shares=p["shares"], cost_price=p["cost_price"],
            current_price=p["current_price"], market_value=p["market_value"],
            cost_value=p["cost_value"], profit_loss=p["profit_loss"],
            profit_loss_pct=p["profit_loss_pct"],
            daily_pl=p.get("daily_pl", 0), daily_pl_pct=p.get("daily_pl_pct", 0),
            price_date=p.get("price_date", ""),
            price_source=p.get("price_source", ""),
            price_fresh=bool(p.get("price_fresh")),
            weight_pct=weight_pct,
            ai_score=score,
            ai_direction=direction,
            ai_signal=top_signal(decision) if decision else "暂无决策",
            risk_level=_position_risk_level(decision, weight_pct),
            added_date="",
            last_score_change=score - previous_score if decision and previous else 0,
        ))

    portfolio_risk_level, risk_summary = _build_risk_summary(
        positions,
        float(paper["cash"]),
        float(paper["total_value"]),
        list(paper.get("stale_positions") or []),
        known_count,
    )
    top_performer = (
        max(positions, key=lambda position: position.profit_loss_pct).stock_name
        if positions else ""
    )
    worst_performer = (
        min(positions, key=lambda position: position.profit_loss_pct).stock_name
        if positions else ""
    )
    result = Portfolio(
        date=paper["date"], total_value=paper["total_value"],
        total_cost=sum(p.cost_value for p in positions),
        total_pl=paper["total_pl"], total_pl_pct=paper["total_pl_pct"],
        daily_pl=paper.get("daily_pl", 0),
        daily_pl_pct=paper.get("daily_pl_pct", 0),
        cash=paper["cash"], positions=positions,
        ai_summary=_build_ai_summary(positions, known_count, latest_score_at),
        risk_summary=risk_summary,
        top_performer=top_performer,
        worst_performer=worst_performer,
    ).to_dict()
    raw_by_code = {
        str(item.get("stock_code") or "").upper(): item
        for item in raw_positions
    }
    for item in result.get("positions") or []:
        execution = raw_by_code.get(str(item.get("stock_code") or "").upper(), {})
        item.update({
            "execution_tier": execution.get("execution_tier", "normal"),
            "entry_flow_state": execution.get("entry_flow_state", ""),
            "entry_fallback_status": execution.get("entry_fallback_status", ""),
            "entry_gate_reasons": execution.get("entry_gate_reasons", []),
            "probe_expiry_date": execution.get("probe_expiry_date", ""),
            "promotion_status": execution.get("promotion_status", "none"),
        })
    result.update({
        "initial_capital": paper["initial_capital"],
        "trades": paper["trades"],
        "order_rejections": paper.get("order_rejections", []),
        "portfolio_mode": "paper_trading",
        "data_source": paper.get("data_source", "local SQLite paper account"),
        "price_date": paper.get("price_date", ""),
        "price_coverage": paper.get("price_coverage", 0),
        "price_sources": paper.get("price_sources", []),
        "stale_positions": paper.get("stale_positions", []),
        "valuation_status": paper.get("valuation_status", "stale"),
        "ledger_version": paper.get("ledger_version", 1),
        "ledger_quality": paper.get("ledger_quality", "legacy_unverified"),
        "ledger_rebuilt_at": paper.get("ledger_rebuilt_at", ""),
        "price_policy": paper.get("price_policy", "legacy"),
        "commission_rate": paper.get("commission_rate", 0),
        "stamp_tax_rate": paper.get("stamp_tax_rate", 0),
        "fee_policy": paper.get("fee_policy", "legacy"),
        "execution_policy": paper.get("execution_policy", "legacy"),
        "total_commission": paper.get("total_commission", 0),
        "total_stamp_tax": paper.get("total_stamp_tax", 0),
        "total_fees": paper.get("total_fees", 0),
        "market_pnl": paper.get("market_pnl", 0),
        "realized_pnl": paper.get("realized_pnl", 0),
        "fees": paper.get("fees", 0),
        "equity_change": paper.get("equity_change", 0),
        "reconciliation_delta": paper.get("reconciliation_delta", 0),
        "reconciliation_status": paper.get("reconciliation_status", "unknown"),
        "portfolio_risk_level": portfolio_risk_level,
        "ai_score_source": "decision_journal" if known_count else "unavailable",
        "ai_score_coverage": known_count / len(positions) if positions else 1.0,
        "ai_score_updated_at": latest_score_at,
        "risk_assessment_updated_at": datetime.now().isoformat(),
    })
    return result


@router.get("/trades")
async def portfolio_trades(
    limit: int = Query(100, ge=1, le=500),
    stock_code: str = "",
    action: str = "",
    date_from: str = "",
    date_to: str = "",
):
    """Query paper fills with signal/execution timestamps and itemized costs."""
    from src.infrastructure.storage.market_database import market_db

    try:
        trades = market_db.get_paper_trades(
            limit=limit,
            stock_code=stock_code,
            action=action,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "count": len(trades),
        "timezone": "Asia/Shanghai",
        "filters": {
            "stock_code": stock_code,
            "action": action.upper(),
            "date_from": date_from,
            "date_to": date_to,
        },
        "fee_policy": {
            "commission_rate": 0.0005,
            "commission_sides": ["BUY", "SELL"],
            "stamp_tax_rate": 0.0005,
            "stamp_tax_side": "SELL",
        },
        "time_fields": {
            "data_cutoff_at": "策略允许读取数据的最晚时间",
            "signal_at": "策略生成时间，不代表委托或成交",
            "quote_exchange_at": "交易所行情自身携带的时间",
            "quote_fetched_at": "模拟器实际收到该行情的时间",
            "execution_at": "收到合格行情后完成模拟记账的时间",
            "causality_status": "成交因果校验状态；历史K线重放不冒充实时逐笔成交",
        },
        "trades": trades,
    }


@router.get("/order-rejections")
async def portfolio_order_rejections(
    limit: int = Query(100, ge=1, le=500),
):
    """Query simulated orders blocked by time, freshness, or causality rules."""
    from src.infrastructure.storage.market_database import market_db

    rows = market_db.get_paper_order_rejections(limit=limit)
    return {
        "count": len(rows),
        "timezone": "Asia/Shanghai",
        "note": "这些尝试均未成交、未改变现金或持仓",
        "rejections": rows,
    }
