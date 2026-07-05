"""Scanner routes"""

from fastapi import APIRouter, Query

router = APIRouter(tags=["scanner"], prefix="/scanner")


@router.post("/run")
async def run_scanner(
    pool_size: int = Query(30, description="模拟股票池大小"),
    top_n: int = Query(5, description="返回Top N"),
):
    """运行全市场扫描"""
    from src.scanner.engine import ScannerEngine, ScannerConfig
    from src.shared.mock_data import generate_stock_pool, generate_klines, mock_signal_result

    pool = generate_stock_pool(pool_size)

    klines = {}
    for i in range(min(15, pool_size)):
        code = pool[i]["code"]
        klines[code] = generate_klines(code, 60, "up" if i % 3 != 0 else "mixed")

    engine = ScannerEngine(ScannerConfig(
        score_top_n=top_n, require_above_ma20=False,
    ))
    result = await engine.scan(pool, klines)

    # Enrich with mock_signal_result for varied, realistic scores
    enriched = []
    for c in result.candidates:
        sig = mock_signal_result(c.stock_code, klines.get(c.stock_code, []))
        enriched.append({
            "rank": c.rank, "stock_code": c.stock_code, "stock_name": c.stock_name,
            "fusion_score": sig["fusion_score"], "direction": sig["direction"],
            "confidence": sig["confidence"], "tags": c.tags,
            "score_breakdown": sig["scores"],
        })
    enriched.sort(key=lambda c: c["fusion_score"], reverse=True)
    for i, c in enumerate(enriched):
        c["rank"] = i + 1

    return {
        "total_scanned": result.total_scanned,
        "after_coarse": result.after_coarse,
        "after_technical": result.after_technical,
        "candidates_found": len(enriched),
        "duration_ms": result.duration_ms,
        "candidates": enriched[:top_n],
    }
