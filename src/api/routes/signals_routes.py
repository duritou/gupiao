"""Signal routes — v7.5: real signal computation from baostock daily bars.

Signals are computed deterministically from real OHLCV data:
  MACD — EMA(12,26,9) crossovers and histogram
  RSI  — Wilder's RSI(14)
  KDJ  — Stochastic oscillator
  MA   — MA5/MA10/MA20 alignment
  Volume — Volume expansion/contraction vs price direction

All computation is in RealDataProvider.compute_signals().
No random numbers.
"""

from time import monotonic
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(tags=["signals"], prefix="/signals")
_SIGNAL_CACHE_TTL_SECONDS = 300
_signal_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class BatchRequest(BaseModel):
    codes: list[str]


@router.get("/list")
async def list_signals():
    """List available signal types."""
    return {
        "signals": [
            {"name": "macd", "category": "technical", "weight": 1.0,
             "description": "EMA(12,26,9) — 趋势 + 金叉/死叉"},
            {"name": "rsi", "category": "technical", "weight": 0.8,
             "description": "RSI(14) — 超买/超卖"},
            {"name": "kdj", "category": "technical", "weight": 0.7,
             "description": "随机指标 — 短期动能"},
            {"name": "ma", "category": "technical", "weight": 0.7,
             "description": "MA5/MA10/MA20 多空排列"},
            {"name": "volume", "category": "volume", "weight": 0.8,
             "description": "量价配合 — 放量/缩量"},
            {"name": "boll", "category": "technical", "weight": 0.6,
             "description": "布林带 — 波动率 (待实现)"},
        ],
        "data_source": "baostock (T-1 daily close)",
    }


@router.get("/compute/{code}")
async def compute_signals(code: str):
    """Compute all signals for a single stock from real K-line data."""
    from src.api.routes.journal_utils import stock_name_from_journal
    from src.infrastructure.market_data.real_data_provider import real_data

    name = stock_name_from_journal(code)
    bars = await real_data.get_daily_bars(code, days=250)

    if not bars or len(bars) < 20:
        return {
            "stock_code": code,
            "error": "数据不足",
            "detail": f"仅有{len(bars) if bars else 0}根K线，至少需要20根。数据来自baostock(T-1)。",
            "data_source": "baostock",
        }

    try:
        sig = real_data.compute_signals(code, name, bars)
    except Exception as e:
        return {
            "stock_code": code,
            "error": "信号计算失败",
            "detail": str(e)[:200],
            "data_days": len(bars),
            "data_source": "baostock",
        }

    return {
        "stock_code": code,
        "stock_name": name,
        "fusion_score": sig.fusion_score,
        "direction": sig.direction,
        "confidence": sig.confidence,
        "data_days": sig.data_days,
        "data_source": sig.data_source,
        "computed_at": sig.computed_at[:19] if sig.computed_at else "",
        "scores": {
            "macd": sig.macd_score,
            "rsi": sig.rsi_score,
            "kdj": sig.kdj_score,
            "ma": sig.ma_score,
            "volume": sig.volume_score,
        },
    }


@router.post("/batch")
async def compute_batch(req: BatchRequest):
    """Batch compute signals — used by Watchlist auto-refresh."""
    from src.api.routes.journal_utils import stock_name_from_journal
    from src.infrastructure.market_data.real_data_provider import real_data

    results = []
    for code in req.codes:
        cached = _signal_cache.get(code)
        if cached and monotonic() - cached[0] < _SIGNAL_CACHE_TTL_SECONDS:
            results.append({**cached[1], "cached": True})
            continue

        name = stock_name_from_journal(code)
        try:
            bars = await real_data.get_daily_bars(code, days=250)
            if bars and len(bars) >= 20:
                sig = real_data.compute_signals(code, name, bars)
                price = bars[-1]["close"] if bars else 0
                arrow = (
                    "↑↑" if sig.fusion_score >= 80 else
                    "↑" if sig.fusion_score >= 65 else
                    "→" if sig.fusion_score >= 50 else
                    "↓" if sig.fusion_score >= 35 else "↓↓"
                )
                scores_map = {
                    "MACD": sig.macd_score, "RSI": sig.rsi_score,
                    "KDJ": sig.kdj_score, "MA": sig.ma_score,
                    "Volume": sig.volume_score,
                }
                top = max(scores_map, key=scores_map.get)
                risk = (
                    "低" if sig.confidence >= 0.7 else
                    "中" if sig.confidence >= 0.5 else "高"
                )
                results.append({
                    "stock_code": code,
                    "stock_name": name,
                    "fusion_score": sig.fusion_score,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "macd_score": sig.macd_score,
                    "rsi_score": sig.rsi_score,
                    "ma_score": sig.ma_score,
                    "volume_score": sig.volume_score,
                    "data_days": sig.data_days,
                    "data_source": sig.data_source,
                    "price": price,
                    "trend_arrow": arrow,
                    "top_signal": f"{top}信号",
                    "risk_level": risk,
                })
            else:
                results.append({
                    "stock_code": code,
                    "stock_name": name,
                    "error": "数据不足",
                    "data_days": len(bars) if bars else 0,
                })
        except Exception as e:
            results.append({
                "stock_code": code,
                "stock_name": name,
                "error": str(e)[:100],
            })
        if results:
            _signal_cache[code] = (monotonic(), results[-1])

    return {
        "signals": results,
        "data_note": "所有信号从 baostock T-1 日线数据计算。非实时。",
    }
