"""Scanner routes — v7.5: real data from baostock.

The scanner now:
  1. Gets real stock universe from RealDataProvider
  2. Fetches real daily bars from baostock for each stock
  3. Computes signals from real OHLCV data (no random numbers)
  4. Ranks candidates by computed fusion score
"""

from time import monotonic
from typing import Annotated, Any

from fastapi import APIRouter, Query

router = APIRouter(tags=["scanner"], prefix="/scanner")
_SCANNER_CACHE_TTL_SECONDS = 300
_scanner_cache: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}


@router.post("/run")
async def run_scanner(
    top_n: Annotated[int, Query(ge=1, le=100, description="Return top N candidates")] = 10,
    pool_size: Annotated[int, Query(ge=1, le=5000, description="Stocks to scan")] = 50,
):
    """Run market scan on real stock data.

    Uses baostock daily bars. Data is T-1 (yesterday's close).
    This is a research system, not HFT — T-1 is sufficient for
    MACD/RSI/KDJ/MA/Volume signal computation.
    """
    from src.infrastructure.market_data.real_data_provider import real_data

    cache_key = (pool_size, top_n)
    cached = _scanner_cache.get(cache_key)
    if cached and monotonic() - cached[0] < _SCANNER_CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    t0 = monotonic()

    # 1. Get real stock universe
    universe = (await real_data.get_stock_universe(min_count=pool_size))[:pool_size]

    # 2. Fetch real K-line data (parallel would be better, but baostock
    #    needs sequential access to avoid connection issues)
    candidates = []
    scanned = 0

    for stock in universe:
        code = stock["code"]
        name = stock.get("name", code)

        try:
            bars = await real_data.get_daily_bars(code, days=250)
            if not bars or len(bars) < 20:
                scanned += 1
                continue

            # 3. Compute real signals from real K-lines
            sig = real_data.compute_signals(code, name, bars)
            scanned += 1

            # Only include stocks with sufficient signal strength
            if abs(sig.fusion_score - 50) < 2:
                continue

            candidates.append({
                "stock_code": sig.stock_code,
                "stock_name": sig.stock_name,
                "fusion_score": sig.fusion_score,
                "direction": sig.direction,
                "confidence": sig.confidence,
                "data_days": sig.data_days,
                "data_source": sig.data_source,
                "score_breakdown": {
                    "macd": sig.macd_score,
                    "rsi": sig.rsi_score,
                    "kdj": sig.kdj_score,
                    "ma": sig.ma_score,
                    "volume": sig.volume_score,
                },
            })
        except Exception:
            scanned += 1
            continue

    # 4. Sort by fusion score
    candidates.sort(key=lambda c: c["fusion_score"], reverse=True)
    for i, c in enumerate(candidates[:top_n]):
        c["rank"] = i + 1

    elapsed_ms = int((monotonic() - t0) * 1000)

    result = {
        "total_scanned": scanned,
        "pool_size": pool_size,
        "candidates_found": len(candidates),
        "duration_ms": elapsed_ms,
        "cached": False,
        "data_source": "baostock (T-1 daily close)",
        "data_note": "数据为最近交易日收盘价。非实时行情。研究系统不需要实时数据。",
        "candidates": candidates[:top_n],
    }
    _scanner_cache[cache_key] = (monotonic(), result)
    return result
