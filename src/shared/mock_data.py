"""Centralized mock data factory — deterministic, realistic Chinese stock market data.

All API routes use this for consistent mock data. Seed by date + stock code
so the same code always gets the same score on the same day.
When real data integration comes, only this module needs to change.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta
from typing import Any


# ============================================================
# Deterministic seed
# ============================================================

def _seed(code: str, day_offset: int = 0) -> float:
    """Deterministic float in [0, 1) from code + today + offset."""
    today = date.today().isoformat()
    key = f"{code}:{today}:{day_offset}"
    h = hashlib.md5(key.encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _seeded_random(code: str, day_offset: int = 0) -> random.Random:
    """Return a random.Random seeded from code + date + offset."""
    today = date.today().isoformat()
    key = f"{code}:{today}:{day_offset}"
    h = hashlib.md5(key.encode()).digest()
    return random.Random(int.from_bytes(h[:8], 'big'))


# ============================================================
# Stock name database
# ============================================================

STOCK_NAMES: dict[str, str] = {
    "000001.SZ": "平安银行", "000002.SZ": "万科A", "000858.SZ": "五粮液",
    "002475.SZ": "立讯精密", "002371.SZ": "北方华创", "002415.SZ": "海康威视",
    "300750.SZ": "宁德时代", "300308.SZ": "中际旭创", "300059.SZ": "东方财富",
    "600519.SH": "贵州茅台", "600036.SH": "招商银行", "600900.SH": "长江电力",
    "601318.SH": "中国平安", "601012.SH": "隆基绿能", "601138.SH": "工业富联",
    "601899.SH": "紫金矿业", "603259.SH": "药明康德", "603986.SH": "兆易创新",
    "688256.SH": "寒武纪", "688981.SH": "中芯国际", "688111.SH": "金山办公",
    "688126.SH": "沪硅产业", "000977.SZ": "浪潮信息", "000725.SZ": "京东方A",
    "600809.SH": "山西汾酒", "000333.SZ": "美的集团", "000651.SZ": "格力电器",
    "600030.SH": "中信证券", "601688.SH": "华泰证券", "600887.SH": "伊利股份",
}


def get_stock_name(code: str) -> str:
    """Get Chinese stock name for a code, or generate a plausible one."""
    return STOCK_NAMES.get(code, f"个股{code[:6]}")


# ============================================================
# Sectors
# ============================================================

SECTORS = [
    {"name": "AI人工智能", "base_score": 88, "stocks": ["688256.SH", "002415.SZ", "300308.SZ"]},
    {"name": "半导体芯片", "base_score": 92, "stocks": ["688981.SH", "002371.SZ", "688126.SH", "603986.SH"]},
    {"name": "机器人", "base_score": 75, "stocks": ["300750.SZ", "002475.SZ"]},
    {"name": "电力设备", "base_score": 82, "stocks": ["601012.SH", "300750.SZ"]},
    {"name": "医药生物", "base_score": 35, "stocks": ["603259.SH"]},
    {"name": "银行", "base_score": 45, "stocks": ["000001.SZ", "600036.SH"]},
    {"name": "消费电子", "base_score": 78, "stocks": ["002475.SZ", "000725.SZ"]},
    {"name": "新能源车", "base_score": 68, "stocks": ["300750.SZ", "601012.SH"]},
    {"name": "食品饮料", "base_score": 62, "stocks": ["600519.SH", "000858.SZ", "600887.SH"]},
    {"name": "证券", "base_score": 55, "stocks": ["600030.SH", "601688.SH"]},
    {"name": "光模块", "base_score": 85, "stocks": ["300308.SZ"]},
    {"name": "PCB印制电路板", "base_score": 80, "stocks": ["002475.SZ"]},
]


def get_sectors() -> list[dict]:
    """Get all sectors with today's scores (slightly randomized around base)."""
    today_seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16)
    rng = random.Random(today_seed)
    result = []
    for s in SECTORS:
        jitter = rng.randint(-5, 5)
        score = max(10, min(99, s["base_score"] + jitter))
        stars = 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 45 else 2 if score >= 25 else 1
        status = "强势" if score >= 70 else "震荡" if score >= 40 else "弱势"
        result.append({**s, "score": score, "stars": stars, "status": status})
    result.sort(key=lambda s: s["score"], reverse=True)
    return result


# ============================================================
# Market overview
# ============================================================

def get_market_overview() -> dict:
    """Generate today's market overview with realistic mock data."""
    today_seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16)
    rng = random.Random(today_seed)

    up = rng.randint(3200, 4200)
    down = rng.randint(600, 1500)
    flat = rng.randint(50, 200)
    sentiment = rng.randint(55, 85)
    stars = 5 if sentiment >= 75 else 4 if sentiment >= 60 else 3 if sentiment >= 40 else 2

    indices = {
        "shanghai": {"name": "上证指数", "value": rng.uniform(3200, 3450), "change_pct": round(rng.uniform(-1.5, 2.0), 2)},
        "shenzhen": {"name": "深证成指", "value": rng.uniform(10500, 11200), "change_pct": round(rng.uniform(-1.5, 2.0), 2)},
        "chinext": {"name": "创业板指", "value": rng.uniform(2100, 2300), "change_pct": round(rng.uniform(-2.0, 2.5), 2)},
        "star50": {"name": "科创50", "value": rng.uniform(930, 1020), "change_pct": round(rng.uniform(-2.0, 2.5), 2)},
    }

    # Round index values
    for k in indices:
        indices[k]["value"] = round(indices[k]["value"], 2)

    northbound_direction = "inflow" if rng.random() > 0.3 else "outflow"
    northbound_amount = round(rng.uniform(-80, 120), 1)

    sectors = get_sectors()
    hot_sectors = [s for s in sectors[:5]]

    risk_types = [
        {"type": "高位放量", "count": rng.randint(2, 6), "severity": "warn"},
        {"type": "跌破MA20", "count": rng.randint(5, 12), "severity": "high"},
        {"type": "机构减仓", "count": rng.randint(3, 8), "severity": "warn"},
        {"type": "北向流出", "count": rng.randint(1, 5), "severity": "medium"},
    ]

    return {
        "date": date.today().isoformat(),
        "indices": indices,
        "market_breadth": {
            "up": up, "down": down, "flat": flat,
            "limit_up": rng.randint(30, 90),
            "limit_down": rng.randint(2, 20),
        },
        "total_volume": round(rng.uniform(0.8, 2.0), 2),  # 万亿
        "northbound": {"net_flow": northbound_amount, "direction": northbound_direction},
        "sentiment_score": sentiment,
        "sentiment_stars": stars,
        "sentiment_label": "积极" if sentiment >= 70 else "中性" if sentiment >= 40 else "谨慎",
        "hot_sectors": hot_sectors,
        "risk_summary": risk_types,
    }


# ============================================================
# K-line generation
# ============================================================

def generate_klines(
    code: str,
    days: int = 80,
    trend: str = "mixed",
    base_price: float | None = None,
) -> list[dict]:
    """Generate deterministic mock K-line data for a stock.

    Args:
        code: Stock code (used for deterministic seeding)
        days: Number of trading days to generate
        trend: "up", "down", or "mixed" (default mixed uses seeded pattern)
        base_price: Starting price (defaults to deterministic value from code)
    """
    rng = _seeded_random(code)
    if base_price is None:
        base_price = rng.uniform(8.0, 200.0)

    klines = []
    price = base_price
    for i in range(days):
        # Determine trend for this day
        if trend == "up":
            drift = 0.08
        elif trend == "down":
            drift = -0.08
        else:
            # Mixed: use a seeded sine-wave pattern
            drift = math.sin(i * 0.15 + _seed(code) * 10) * 0.1

        change = drift + rng.uniform(-0.03, 0.03)
        close = price * (1 + change)
        open_p = close * (1 + rng.uniform(-0.01, 0.01))
        high = max(open_p, close) * (1 + rng.uniform(0, 0.02))
        low = min(open_p, close) * (1 - rng.uniform(0, 0.02))
        vol = int(rng.uniform(500000, 5000000))

        trade_date = (date.today() - timedelta(days=days - i)).isoformat()
        klines.append({
            "date": trade_date,
            "open": round(open_p, 2), "high": round(high, 2),
            "low": round(low, 2), "close": round(close, 2),
            "volume": vol,
        })
        price = close

    return klines


# ============================================================
# Stock pool generation
# ============================================================

def generate_stock_pool(size: int = 40) -> list[dict]:
    """Generate a deterministic stock pool for scanning."""
    codes = list(STOCK_NAMES.keys())
    # Pad with generated codes if needed
    while len(codes) < size:
        idx = len(codes) - len(STOCK_NAMES)
        if idx < size // 2:
            codes.append(f"{600000 + idx:06d}.SH")
        else:
            codes.append(f"{idx - size // 2:06d}.SZ")

    pool = []
    for i, code in enumerate(codes[:size]):
        rng = _seeded_random(code)
        name = get_stock_name(code)
        pool.append({
            "code": code,
            "name": name,
            "market_cap": round(rng.uniform(20, 5000), 1),  # 亿
            "avg_amount": round(rng.uniform(50, 500), 1),    # 百万元
            "price": round(rng.uniform(5, 300), 2),
            "change_pct": round(rng.uniform(-5, 5), 2),
        })
    return pool


# ============================================================
# Signal computation mock helpers
# ============================================================

def mock_signal_result(code: str, klines: list[dict]) -> dict:
    """Generate a deterministic mock signal result for a stock."""
    rng = _seeded_random(code)

    # Use recent price action to bias the score
    if len(klines) >= 20:
        recent = klines[-20:]
        start_price = recent[0]["close"]
        end_price = recent[-1]["close"]
        price_change = (end_price / start_price - 1) * 100
    else:
        price_change = 0

    # Score: biased by price trend but with randomness
    base_score = 50 + price_change * 5
    base_score = max(10, min(95, base_score + rng.uniform(-10, 10)))

    direction = "buy" if base_score >= 60 else "sell" if base_score <= 40 else "neutral"
    confidence = rng.uniform(0.3, 0.95)

    # Individual signal scores
    signals = {
        "macd": round(base_score + rng.uniform(-10, 10), 1),
        "rsi": round(max(10, min(95, base_score + rng.uniform(-15, 15))), 1),
        "kdj": round(max(10, min(95, base_score + rng.uniform(-12, 12))), 1),
        "ma": round(max(10, min(95, base_score + rng.uniform(-8, 8))), 1),
        "volume": round(max(10, min(95, base_score + rng.uniform(-15, 15))), 1),
        "boll": round(max(10, min(95, base_score + rng.uniform(-10, 10))), 1),
    }

    # Determine top signal
    top_signal_name = max(signals, key=signals.get)
    top_signal_value = signals[top_signal_name]
    if top_signal_value >= 70:
        if top_signal_name == "macd":
            top_signal = "MACD金叉"
        elif top_signal_name == "ma":
            top_signal = "MA多头排列"
        elif top_signal_name == "volume":
            top_signal = "放量突破"
        elif top_signal_name == "rsi":
            top_signal = "RSI强势"
        elif top_signal_name == "kdj":
            top_signal = "KDJ金叉"
        else:
            top_signal = f"{top_signal_name.upper()}看多"
    elif top_signal_value <= 35:
        if top_signal_name == "macd":
            top_signal = "MACD死叉"
        elif top_signal_name == "ma":
            top_signal = "跌破MA20"
        else:
            top_signal = f"{top_signal_name.upper()}看空"
    else:
        top_signal = f"{top_signal_name.upper()}中性"

    # Risk level
    if base_score >= 75 and confidence > 0.7:
        risk_level = "极低"
    elif base_score >= 65:
        risk_level = "低"
    elif base_score >= 45:
        risk_level = "中"
    elif base_score >= 30:
        risk_level = "高"
    else:
        risk_level = "极高"

    # Trend
    if price_change > 3:
        trend_arrow = "↑↑"
    elif price_change > 1:
        trend_arrow = "↑"
    elif price_change > -1:
        trend_arrow = "→"
    elif price_change > -3:
        trend_arrow = "↓"
    else:
        trend_arrow = "↓↓"

    buy_signals = sum(1 for v in signals.values() if v >= 60)
    sell_signals = sum(1 for v in signals.values() if v <= 40)
    neutral_signals = len(signals) - buy_signals - sell_signals

    # Generate human-readable reasons
    reasons = []
    if "macd" in signals and signals["macd"] >= 65:
        reasons.append("[macd] MACD形成金叉，DIF上穿DEA")
    elif "macd" in signals and signals["macd"] <= 35:
        reasons.append("[macd] MACD形成死叉，短期走弱")
    if "ma" in signals and signals["ma"] >= 65:
        reasons.append("[ma] MA20上穿MA60，均线多头排列")
    elif "ma" in signals and signals["ma"] <= 35:
        reasons.append("[ma] 价格跌破MA20支撑")
    if "volume" in signals and signals["volume"] >= 65:
        reasons.append("[volume] 成交量显著放大，资金入场明显")
    if "rsi" in signals and signals["rsi"] >= 70:
        reasons.append("[rsi] RSI进入强势区间")
    elif "rsi" in signals and signals["rsi"] <= 30:
        reasons.append("[rsi] RSI进入超卖区间，关注反弹")
    if buy_signals >= 3:
        reasons.append(f"[fusion] {buy_signals}个信号共振看多")
    if sell_signals >= 3:
        reasons.append(f"[fusion] {sell_signals}个信号共振看空")

    return {
        "stock_code": code,
        "stock_name": get_stock_name(code),
        "fusion_score": round(base_score, 1),
        "direction": direction,
        "confidence": round(confidence, 3),
        "scores": signals,
        "reasons": reasons,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "neutral_signals": neutral_signals,
        "top_signal": top_signal,
        "risk_level": risk_level,
        "trend_arrow": trend_arrow,
        "price": round(klines[-1]["close"], 2) if klines else 0,
    }


# ============================================================
# Alert generation
# ============================================================

def generate_alerts(count: int = 20) -> list[dict]:
    """Generate today's mock alerts distributed throughout the trading day."""
    rng = random.Random(int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16))

    alert_types = [
        ("MACD金叉", "up"), ("MACD死叉", "down"),
        ("放量突破", "up"), ("跌破MA20", "down"),
        ("跌破MA60", "down"), ("MA多头排列", "up"),
        ("RSI超卖反弹", "up"), ("北向加仓", "up"),
        ("北向减仓", "down"), ("KDJ金叉", "up"),
        ("BOLL突破上轨", "up"), ("BOLL跌破下轨", "down"),
    ]

    # Generate times throughout the trading day
    codes = list(STOCK_NAMES.keys())
    rng.shuffle(codes)

    alerts = []
    for i in range(min(count, len(codes) * 2)):
        code = codes[i % len(codes)]
        alert_type, direction = alert_types[i % len(alert_types)]
        hour = 9 + (i * 37) // 60  # Spread across 9:30-15:00
        minute = 30 + (i * 37) % 60
        if hour >= 15 or (hour == 15 and minute > 0):
            hour = 14
            minute = rng.randint(0, 59)

        score = rng.randint(35, 95)
        if direction == "up":
            score = rng.randint(65, 95)
        else:
            score = rng.randint(15, 55)

        alerts.append({
            "id": f"a_{date.today().isoformat()}_{i:03d}",
            "time": f"{hour:02d}:{minute:02d}",
            "stock_code": code,
            "stock_name": get_stock_name(code),
            "alert_type": alert_type,
            "signal_type": alert_type,
            "score": score,
            "direction": direction,
            "read": i > 5,  # First 6 are unread
        })

    # Sort by time
    alerts.sort(key=lambda a: a["time"])
    return alerts


# ============================================================
# Timeline / score history
# ============================================================

def generate_timeline(code: str, days: int = 30) -> dict:
    """Generate a deterministic score timeline for a stock."""
    rng = _seeded_random(code)
    base_score = rng.uniform(55, 85)
    today = date.today()

    entries = []
    current_score = base_score - rng.uniform(10, 20)  # Start lower
    current_score = max(10, min(95, current_score))

    for i in range(days):
        day = today - timedelta(days=days - 1 - i)
        # Generate a plausible trajectory trending toward base_score
        target = base_score + (i / days) * (base_score - current_score)
        jitter = rng.uniform(-3, 3)
        score = current_score + (target - current_score) * 0.15 + jitter
        score = round(max(10, min(95, score)), 1)

        change = round(score - current_score, 1)
        direction = "up" if change > 0.5 else "down" if change < -0.5 else "flat"

        # Generate reasons for significant changes
        events = []
        if abs(change) >= 2:
            possible_events = [
                {"event": "MACD金叉", "impact": "+5", "source": "signal"},
                {"event": "北向资金流入", "impact": f"+{abs(change):.1f}", "source": "market"},
                {"event": "成交量放大150%", "impact": "+3", "source": "market"},
                {"event": "行业评分提升", "impact": f"+{abs(change):.1f}", "source": "knowledge"},
                {"event": "跌破MA20", "impact": f"-{abs(change):.1f}", "source": "signal"},
                {"event": "MACD死叉", "impact": "-4", "source": "signal"},
                {"event": "北向资金流出", "impact": f"-{abs(change):.1f}", "source": "market"},
            ]
            # Pick events that match the direction
            matching = [e for e in possible_events if
                        (direction == "up" and float(e["impact"]) > 0) or
                        (direction == "down" and float(e["impact"]) < 0)]
            if matching:
                events.append(matching[i % len(matching)])

        entries.append({
            "date": day.isoformat(),
            "score": score,
            "change": change,
            "direction": direction,
            "events": events,
        })
        current_score = score

    return {
        "stock_code": code,
        "stock_name": get_stock_name(code),
        "current_score": entries[-1]["score"],
        "start_score": entries[0]["score"],
        "total_change": round(entries[-1]["score"] - entries[0]["score"], 1),
        "entries": entries,
    }


# ============================================================
# Daily brief
# ============================================================

def generate_daily_brief() -> dict:
    """Generate today's mock daily brief."""
    today = date.today()
    market = get_market_overview()
    sectors = get_sectors()
    hot = sectors[:4]

    # Top opportunities from known stocks
    pool = generate_stock_pool(20)
    klines_map = {s["code"]: generate_klines(s["code"], 60) for s in pool[:10]}
    opportunities = []
    for s in pool[:5]:
        klines = klines_map.get(s["code"], [])
        sig = mock_signal_result(s["code"], klines)
        opportunities.append({
            "rank": len(opportunities) + 1,
            "stock_code": s["code"],
            "stock_name": s["name"],
            "score": sig["fusion_score"],
            "direction": sig["direction"],
            "reason": sig["top_signal"],
        })

    opportunities.sort(key=lambda o: o["score"], reverse=True)
    for i, o in enumerate(opportunities):
        o["rank"] = i + 1

    # Risk warnings
    risk_warnings = [
        "新能源板块持续走弱，关注政策面变化",
        "消费板块资金流出明显，短期回避",
        "北向资金午后可能转向流出",
        "高估值标的回调风险加大",
    ]

    one_liners = [
        "AI服务器产业链继续强化，关注光模块和PCB龙头，半导体设备国产替代加速。",
        "市场情绪温和回暖，科技成长风格占优，关注AI和半导体方向。",
        "大盘震荡整理，结构性行情延续，精选个股优于追涨杀跌。",
        "北向资金持续流入，外资偏好消费和金融蓝筹，关注低估值修复机会。",
    ]
    rng = _seeded_random("dailybrief")
    one_liner = rng.choice(one_liners)

    return {
        "date": today.isoformat(),
        "generated_at": "09:00",
        "market_sentiment": {
            "score": market["sentiment_score"],
            "stars": market["sentiment_stars"],
            "label": market["sentiment_label"],
        },
        "market_summary": (f"上涨{market['market_breadth']['up']}家 · "
                          f"成交{market['total_volume']}万亿 · "
                          f"北向{market['northbound']['net_flow']:+.0f}亿"),
        "hot_sectors": [{"name": s["name"], "stars": s["stars"], "score": s["score"]} for s in hot],
        "top_opportunities": opportunities[:3],
        "risk_warnings": risk_warnings,
        "one_liner": one_liner,
    }


# ============================================================
# Stock detail / evidence
# ============================================================

def generate_stock_detail(code: str) -> dict:
    """Generate a comprehensive stock detail payload."""
    klines = generate_klines(code, 120)
    signal = mock_signal_result(code, klines)
    rng = _seeded_random(code)

    # Evidence cards
    evidence = []
    for reason in signal["reasons"]:
        # Parse "[signal_name] description" format
        if reason.startswith("["):
            sig_name = reason[1:reason.index("]")]
            desc = reason[reason.index("]") + 2:]
        else:
            sig_name = "signal"
            desc = reason

        credibility = round(rng.uniform(0.75, 0.98), 2)
        score_impact = round((signal["scores"].get(sig_name, 50) - 50) * 0.3, 1)

        evidence.append({
            "evidence_id": f"ev_{code}_{sig_name}",
            "evidence_type": "signal",
            "icon": "check",
            "title": desc.split("，")[0] if "，" in desc else desc,
            "description": desc,
            "credibility": credibility,
            "score_impact": score_impact,
            "source": f"{sig_name.upper()} Signal",
            "timestamp": date.today().isoformat(),
            "detail": desc,
        })

    # Add knowledge-based evidence
    sector = None
    for s in SECTORS:
        if code in s["stocks"]:
            sector = s
            break

    if sector:
        evidence.append({
            "evidence_id": f"ev_{code}_knowledge",
            "evidence_type": "knowledge",
            "icon": "star",
            "title": f"{sector['name']}行业景气度提升",
            "description": f"知识库 {sector['name']} 行业景气度提升",
            "credibility": round(rng.uniform(0.80, 0.95), 2),
            "score_impact": round(sector["base_score"] * 0.1, 1),
            "source": f"Knowledge:{sector['name']}",
            "timestamp": date.today().isoformat(),
            "detail": f"{sector['name']}行业评分{sector['base_score']}分，处于{'强势' if sector['base_score'] >= 70 else '中性' if sector['base_score'] >= 40 else '弱势'}区间",
        })

    # Risk factors
    risk_factors: list[str] = []
    if signal["fusion_score"] >= 80:
        risk_factors = ["估值偏高，注意回调风险", "短期涨幅较大，可等待回调介入"]
    elif signal["fusion_score"] <= 35:
        risk_factors = ["趋势偏弱，不建议盲目抄底", "等待企稳信号出现"]
    else:
        risk_factors = ["需关注大盘整体走势", "行业政策变化需持续跟踪"]

    # Indicators summary
    indicators = {
        "macd": {"dif": round(rng.uniform(-0.5, 0.5), 3), "dea": round(rng.uniform(-0.3, 0.3), 3),
                 "histogram": round(rng.uniform(-0.1, 0.1), 3),
                 "signal": "金叉" if signal["scores"].get("macd", 50) >= 60 else "死叉" if signal["scores"].get("macd", 50) <= 40 else "中性"},
        "rsi": {"value": round(signal["scores"].get("rsi", 50) * 0.8 + 10, 1),
                "status": "健康" if 30 <= signal["scores"].get("rsi", 50) <= 70 else "超买" if signal["scores"].get("rsi", 50) > 70 else "超卖"},
        "ma": {"ma5": round(klines[-1]["close"] * rng.uniform(0.97, 1.03), 2) if klines else 0,
               "ma20": round(klines[-1]["close"] * rng.uniform(0.94, 1.01), 2) if klines else 0,
               "ma60": round(klines[-1]["close"] * rng.uniform(0.90, 0.98), 2) if klines else 0,
               "trend": "多头排列" if signal["scores"].get("ma", 50) >= 60 else "空头排列"},
    }

    # Financials
    financials = {
        "pe": round(rng.uniform(5, 80), 1),
        "pb": round(rng.uniform(0.5, 15), 1),
        "roe": round(rng.uniform(5, 35), 1),
        "revenue_growth": round(rng.uniform(-10, 40), 1),
        "profit_growth": round(rng.uniform(-15, 50), 1),
    }

    # Fund flow
    fund_flow = {
        "northbound": round(rng.uniform(-5, 10), 1),
        "institutional": round(rng.uniform(-10, 20), 1),
        "retail": round(rng.uniform(-15, 10), 1),
    }

    # News
    news_templates = [
        (f"{get_stock_name(code)}发布季度报告，业绩超预期", "positive"),
        (f"{get_stock_name(code)}获机构调研，关注度提升", "positive"),
        (f"行业政策利好，{get_stock_name(code)}有望受益", "positive"),
        (f"{get_stock_name(code)}公告回购计划", "positive"),
        (f"分析师上调{get_stock_name(code)}目标价", "positive"),
        (f"{get_stock_name(code)}大股东减持", "negative"),
        (f"行业竞争加剧，{get_stock_name(code)}市场份额承压", "negative"),
    ]
    news = []
    for i in range(min(4, len(news_templates))):
        title, sentiment = news_templates[i]
        news.append({
            "title": title,
            "sentiment": sentiment,
            "date": (date.today() - timedelta(days=i)).isoformat(),
            "source": "模拟资讯",
        })

    return {
        "stock_code": code,
        "stock_name": get_stock_name(code),
        "ai_score": signal["fusion_score"],
        "direction": signal["direction"],
        "confidence": signal["confidence"],
        "recommendation": "强烈关注" if signal["fusion_score"] >= 80 else
                         "关注" if signal["fusion_score"] >= 65 else
                         "观望" if signal["fusion_score"] >= 45 else "回避",
        "stars": 5 if signal["fusion_score"] >= 80 else 4 if signal["fusion_score"] >= 65 else
                 3 if signal["fusion_score"] >= 45 else 2,
        "evidence": evidence,
        "risk_factors": risk_factors,
        "latest_price": signal["price"],
        "price_change_pct": round(rng.uniform(-3, 3), 2),
        "indicators": indicators,
        "fund_flow": fund_flow,
        "financials": financials,
        "news": news,
        "scores": signal["scores"],
        "buy_signals": signal["buy_signals"],
        "sell_signals": signal["sell_signals"],
        "top_signal": signal["top_signal"],
        "trend_arrow": signal["trend_arrow"],
    }
