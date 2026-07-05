"""Morning Brief — 每日晨报: portfolio + market + AI recommendations."""

from datetime import date

from fastapi import APIRouter

from src.shared.mock_data import (
    get_market_overview, get_sectors,
    mock_signal_result, generate_klines, get_stock_name,
)

router = APIRouter(tags=["morning-brief"], prefix="/morning-brief")


@router.get("/today")
async def get_morning_brief():
    """Generate today's morning brief: personal portfolio + market."""
    today = date.today().isoformat()

    # 1. Portfolio summary (demo holdings)
    holdings = [
        {"code": "688256.SH", "shares": 500, "cost": 220.0},
        {"code": "002371.SZ", "shares": 1000, "cost": 180.0},
        {"code": "300308.SZ", "shares": 800, "cost": 95.0},
        {"code": "688981.SH", "shares": 1200, "cost": 55.0},
        {"code": "600519.SH", "shares": 100, "cost": 1380.0},
    ]

    portfolio_items = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        code = h["code"]
        klines = generate_klines(code, 80, "up")
        signal = mock_signal_result(code, klines)
        name = get_stock_name(code)
        price = signal["price"]
        mv = h["shares"] * price
        cv = h["shares"] * h["cost"]
        pl = mv - cv
        pl_pct = (price / h["cost"] - 1) * 100

        # Score change (mock: ±5 from yesterday)
        yesterday_score = signal["fusion_score"] + (5 if "688" in code or "002371" in code else
                                                    3 if "300308" in code else -4)
        score_change = signal["fusion_score"] - yesterday_score

        total_value += mv
        total_cost += cv

        portfolio_items.append({
            "stock_code": code,
            "stock_name": name,
            "ai_score": round(signal["fusion_score"], 1),
            "score_change": round(score_change, 1),
            "direction": signal["direction"],
            "top_signal": signal["top_signal"],
            "risk_level": signal["risk_level"],
            "pl_pct": round(pl_pct, 1),
            "price": round(price, 2),
        })

    total_pl = total_value - total_cost
    total_pl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0
    avg_score = sum(p["ai_score"] for p in portfolio_items) / len(portfolio_items)
    yesterday_avg = sum(p["ai_score"] - p["score_change"] for p in portfolio_items) / len(portfolio_items)
    score_trend = avg_score - yesterday_avg

    # Sort: biggest improvers first
    portfolio_items.sort(key=lambda p: p["score_change"], reverse=True)

    upgraders = [p for p in portfolio_items if p["score_change"] > 2]
    downgraders = [p for p in portfolio_items if p["score_change"] < -2]
    stable = [p for p in portfolio_items if abs(p["score_change"]) <= 2]

    # 2. Market overview
    market = get_market_overview()
    sectors = get_sectors()
    hot = sectors[:4]

    # 3. AI recommendations
    recommendations = []
    for p in portfolio_items:
        if p["ai_score"] >= 80 and p["score_change"] > 0:
            recommendations.append({
                "type": "hold_or_add",
                "stock_code": p["stock_code"],
                "stock_name": p["stock_name"],
                "reason": f"评分{p['ai_score']:.0f}(↑{p['score_change']:+.0f})，{p['top_signal']}",
            })
        elif p["ai_score"] <= 45 or p["score_change"] < -5:
            recommendations.append({
                "type": "reduce",
                "stock_code": p["stock_code"],
                "stock_name": p["stock_name"],
                "reason": f"评分{p['ai_score']:.0f}({p['score_change']:+.0f})，{p['risk_level']}风险",
            })

    # 4. One-line AI summary
    pl_desc = f"账户{'盈利' if total_pl >= 0 else '亏损'}{abs(total_pl_pct):.1f}%"
    score_desc = f"AI综合评分{avg_score:.0f}({'↑' if score_trend > 0 else '↓'}{abs(score_trend):.0f})"
    market_desc = f"市场{market['sentiment_label']}({market['sentiment_score']}分)"

    one_liner = f"{pl_desc}，{score_desc}，{market_desc}。"
    if upgraders:
        one_liner += f" {upgraders[0]['stock_name']}评分提升，值得关注。"
    if downgraders:
        one_liner += f" {downgraders[0]['stock_name']}评分下滑，建议留意。"

    return {
        "date": today,
        "portfolio": {
            "total_value": round(total_value, 2),
            "total_pl": round(total_pl, 2),
            "total_pl_pct": round(total_pl_pct, 2),
            "daily_pl_pct": 1.2,  # mock
            "avg_score": round(avg_score, 1),
            "score_trend": round(score_trend, 1),
            "position_count": len(portfolio_items),
            "items": portfolio_items,
        },
        "score_changes": {
            "upgraded": upgraders,
            "downgraded": downgraders,
            "stable": stable,
        },
        "market": {
            "sentiment_stars": market["sentiment_stars"],
            "sentiment_label": market["sentiment_label"],
            "sentiment_score": market["sentiment_score"],
            "up_count": market["market_breadth"]["up"],
            "down_count": market["market_breadth"]["down"],
            "total_volume": market["total_volume"],
            "northbound": market["northbound"],
            "indices": market["indices"],
        },
        "hot_sectors": [{"name": s["name"], "stars": s["stars"], "score": s["score"]} for s in hot],
        "recommendations": recommendations,
        "one_liner": one_liner,
    }
