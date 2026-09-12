"""龙虎榜路由 - 提供股票龙虎榜数据。"""

from fastapi import APIRouter

from src.infrastructure.market_data.eastmoney_billboard import (
    fetch_eastmoney_dragon_tiger,
)
from src.infrastructure.market_data.source_manager import source_manager
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["dragon-tiger"])


@router.get("/dragon-tiger")
async def get_dragon_tiger(code: str):
    """获取指定股票的龙虎榜数据。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 龙虎榜数据，包含买入/卖出营业部、上榜原因等
    """
    try:
        data, provenance = await source_manager.get_dragon_tiger(code.strip().upper())
        if data.get("records"):
            return {
                "data": data,
                "_meta": {
                    **provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare",
                    "available": True,
                    "is_proxy": False,
                    "seat_detail_available": False,
                    "warning": "Tushare 返回龙虎榜摘要，不含营业部席位明细",
                },
            }
    except Exception:
        pass
    try:
        native = await fetch_eastmoney_dragon_tiger(code)
    except Exception as exc:  # Native transport/parser failures use the compatibility source.
        native = {
            "data": {},
            "_meta": {
                "provider": "eastmoney",
                "source_layer": "adaptive_native",
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        }
    if native.get("data"):
        return native

    # Keep Vibe as a transparent fallback when the native datacenter has no
    # usable rows or is temporarily unavailable.
    provider = get_vibe_provider()
    return await provider.get_dragon_tiger(code)
