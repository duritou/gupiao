"""龙虎榜路由 - 提供股票龙虎榜数据。"""

from fastapi import APIRouter

from config.settings import settings
from src.infrastructure.market_data.eastmoney_billboard import (
    fetch_eastmoney_dragon_tiger,
)
from src.infrastructure.market_data.hithink_contracts import normalize_thscode
from src.infrastructure.market_data.hithink_provider import hithink_provider
from src.infrastructure.market_data.source_manager import source_manager
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["dragon-tiger"])


def _hithink_dragon_view(payload: object, requested_code: str) -> dict | None:
    """Project a dated HiThink market-wide board into the route's stock view."""
    packet = getattr(payload, "data", None)
    if not isinstance(packet, dict):
        return None
    try:
        wanted = normalize_thscode(requested_code)
    except ValueError:
        wanted = requested_code.strip().upper()
    rows = [row for row in packet.get("stock_items", []) if isinstance(row, dict)]
    match = next(
        (row for row in rows if str(row.get("thscode") or "").upper() == wanted),
        None,
    )
    if match is None:
        return None
    trade_date = str(packet.get("trade_date") or "")[:10]
    records = [{
        "date": trade_date,
        "reason": match.get("limit_reason") or "龙虎榜",
        "net_value": match.get("net_value"),
        "buy_value": match.get("buy_value"),
        "sell_value": match.get("sell_value"),
        "net_rate": match.get("net_rate"),
    }]
    institution = {}
    if match.get("org_net_value") is not None:
        institution["net_value"] = match.get("org_net_value")
    return {
        "data": {
            "code": match.get("thscode") or requested_code,
            "name": match.get("name") or "",
            "records": records,
            "seats": {"buy": [], "sell": []},
            "institution": institution,
            "board_type": packet.get("board_type", "all"),
        },
        "_meta": {
            "provider": "hithink",
            "source_name": "同花顺金融数据服务",
            "source_layer": "hithink_rest",
            "endpoint": getattr(payload, "endpoint", ""),
            "request_id": getattr(payload, "request_id", ""),
            "fetched_at": getattr(payload, "fetched_at", ""),
            "data_date": trade_date,
            "is_live": False,
            "is_cached": False,
            "available": True,
            "seat_detail_available": False,
            "amount_unit": "provider_native",
            "warning": "HiThink 龙虎榜金额保留上游原始单位，未伪造营业部席位明细",
        },
    }


async def _try_hithink_dragon(code: str) -> dict | None:
    if not hithink_provider.configured:
        return None
    payload = await hithink_provider.fetch_dragon_tiger(board_type="all")
    return _hithink_dragon_view(payload, code)


@router.get("/dragon-tiger")
async def get_dragon_tiger(code: str):
    """获取指定股票的龙虎榜数据。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 龙虎榜数据，包含买入/卖出营业部、上榜原因等
    """
    normalized_code = code.strip().upper()
    mode = settings.HITHINK_SPECIAL_MODE
    hithink_error = ""
    if mode in {"primary", "shadow", "validator"}:
        try:
            hithink_view = await _try_hithink_dragon(normalized_code)
            if mode == "primary" and hithink_view is not None:
                return hithink_view
        except Exception as exc:
            hithink_error = getattr(exc, "category", type(exc).__name__)

    try:
        data, provenance = await source_manager.get_dragon_tiger(code.strip().upper())
        if isinstance(data, dict) and data.get("records"):
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
                    **({"hithink_fallback_reason": hithink_error} if hithink_error else {}),
                },
            }
    except Exception:
        pass
    if mode == "fallback":
        try:
            hithink_view = await _try_hithink_dragon(normalized_code)
            if hithink_view is not None:
                return hithink_view
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
