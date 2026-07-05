"""Scanner routes"""

from fastapi import APIRouter, Query

router = APIRouter(tags=["scanner"], prefix="/scanner")


@router.post("/run")
async def run_scanner(
    pool_size: int = Query(30, description="模拟股票池大小"),
    top_n: int = Query(5, description="返回Top N"),
):
    """运行全市场扫描"""
    import math
    from src.scanner.engine import ScannerEngine, ScannerConfig

    # 构造模拟股票池
    pool = []
    for i in range(pool_size):
        code = f"{600000 + i:06d}.SH" if i < pool_size // 2 else f"{i - pool_size // 2:06d}.SZ"
        pool.append({
            "code": code, "name": f"股票{i}",
            "market_cap": 30 + i * 3, "avg_amount": 80 + i * 2,
            "price": 8.0 + i * 0.3, "change_pct": (i - pool_size // 2) * 0.3,
        })

    # 构造模拟K线
    klines = {}
    for i in range(min(15, pool_size)):
        code = pool[i]["code"]
        trend_data = []
        for j in range(60):
            p = 10.0 + j * 0.08 + math.sin(j * 0.15) * 0.4
            trend_data.append({"close": p, "open": p - 0.02, "high": p + 0.06,
                               "low": p - 0.04, "volume": 1000000 + j * 8000})
        klines[code] = trend_data

    engine = ScannerEngine(ScannerConfig(score_top_n=top_n))
    result = await engine.scan(pool, klines)

    return {
        "total_scanned": result.total_scanned,
        "after_coarse": result.after_coarse,
        "after_technical": result.after_technical,
        "candidates_found": result.after_scoring,
        "duration_ms": result.duration_ms,
        "candidates": [
            {
                "rank": c.rank, "stock_code": c.stock_code, "stock_name": c.stock_name,
                "fusion_score": c.fusion_score, "direction": c.direction,
                "confidence": c.confidence, "tags": c.tags,
                "score_breakdown": c.score_breakdown,
            }
            for c in result.candidates
        ],
    }
