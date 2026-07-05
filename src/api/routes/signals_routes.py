"""Signal routes"""

import math
from fastapi import APIRouter, Query

router = APIRouter(tags=["signals"], prefix="/signals")


def _mock_klines(n: int = 60, trend: str = "up") -> list[dict]:
    result = []
    for i in range(n):
        p = 10.0 + (i * 0.1 if trend == "up" else -i * 0.1) + math.sin(i * 0.2) * 0.3
        result.append({"close": p, "open": p - 0.03, "high": p + 0.05,
                       "low": p - 0.05, "volume": 1000000 + i * 5000})
    return result


@router.get("/list")
async def list_signals():
    return {
        "signals": [
            {"name": "macd", "category": "technical", "weight": 1.0},
            {"name": "rsi", "category": "technical", "weight": 0.8},
            {"name": "kdj", "category": "technical", "weight": 0.7},
            {"name": "ma", "category": "technical", "weight": 0.7},
            {"name": "volume", "category": "volume", "weight": 0.8},
            {"name": "boll", "category": "technical", "weight": 0.6},
        ]
    }


@router.get("/compute/{code}")
async def compute_signals(
    code: str,
    trend: str = Query("up", description="up/down — 模拟趋势方向"),
):
    """计算单只股票的全部信号"""
    from src.signals.builtin.technical import (
        MACDSignal, RSISignal, KDJJSignal, MASignal, VolumeSignal, BOLLSignal,
    )
    from src.signals.fusion import SignalFusion

    klines = _mock_klines(80, trend)
    fusion = SignalFusion([
        MACDSignal(), RSISignal(), KDJJSignal(),
        MASignal(), VolumeSignal(), BOLLSignal(),
    ])
    result = await fusion.score(code, klines)

    return {
        "stock_code": code,
        "fusion_score": result.final_score,
        "direction": result.direction.value,
        "confidence": result.confidence,
        "scores": result.individual_scores,
        "reasons": result.reasons,
        "buy_signals": result.buy_signals,
        "sell_signals": result.sell_signals,
    }
