"""资金流向路由 - 提供股票资金流入流出数据。"""

from fastapi import APIRouter

from config.settings import settings
from src.infrastructure.market_data.native_quote_views import get_native_fundflow
from src.infrastructure.market_data.source_manager import source_manager  # noqa: F401
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["fundflow"])


def _active_trade_ratio(quote: dict) -> float | None:
    value = quote.get("active_volume_ratio")
    if value is None:
        try:
            outer = float(quote.get("outer_volume_lots") or 0)
            inner = float(quote.get("inner_volume_lots") or 0)
        except (TypeError, ValueError):
            return None
        total = outer + inner
        value = (outer - inner) / total if total > 0 else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _quote_proxy(quote: dict, provenance: object, normalized: str) -> dict | None:
    active_ratio = _active_trade_ratio(quote)
    if active_ratio is None:
        return None
    amount_wan = quote.get("amount_wan")
    if amount_wan is None and quote.get("amount") is not None:
        try:
            amount_wan = float(quote["amount"]) / 10_000
        except (TypeError, ValueError):
            amount_wan = None
    metadata = provenance.to_dict() if hasattr(provenance, "to_dict") else {}
    return {
        "data": {
            "name": quote.get("stock_name") or quote.get("name") or normalized,
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct"),
            "main_net_pct": round(active_ratio * 100, 2),
            "outer_volume_lots": quote.get("outer_volume_lots"),
            "inner_volume_lots": quote.get("inner_volume_lots"),
            "amount_wan": amount_wan,
            "data_date": quote.get("data_date"),
            "proxy_type": "active_trade_ratio",
        },
        "_meta": {
            **metadata,
            "provider": metadata.get("provider") or "adaptive_source_manager",
            "available": True,
            "is_proxy": True,
            "source_layer": "adaptive_source_manager_quote",
            "warning": "主力资金源不可用；当前展示主动买卖盘差额占比代理指标",
            "error": "",
        },
    }


@router.get("/fundflow")
async def get_fundflow(code: str):
    """获取指定股票的资金流向数据。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 资金流向数据，包含主力资金、散户资金等流入流出情况
    """
    try:
        history, history_provenance = await source_manager.get_fund_flow_history(
            code.strip().upper(), days=settings.DATA_COMPLETION_FLOW_DAYS
        )
        if history.get("available") and history.get("rows"):
            return {
                "data": history,
                "_meta": {
                    **history_provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare_flow_history",
                    "available": True,
                    "data_date": history.get("data_date") or "",
                    "endpoint": history.get("endpoint") or history_provenance.endpoint,
                    "is_realtime": False,
                    "is_proxy": False,
                    "requested_days": history.get("requested_days"),
                    "row_count": history.get("row_count"),
                    "warning": "Tushare 个股资金流为盘后数据，不等同于盘中实时资金流",
                },
            }
    except Exception:
        pass
    try:
        evidence = await source_manager.get_stock_evidence(code.strip().upper())
        flow = evidence.get("fund_flow") or {}
        if flow:
            return {
                "data": flow,
                "_meta": {
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare",
                    "available": True,
                    "data_date": flow.get("data_date") or "",
                    "endpoint": flow.get("endpoint") or "moneyflow",
                    "is_realtime": False,
                    "is_proxy": False,
                    "warning": "Tushare 个股资金流为盘后数据，不等同于盘中实时资金流",
                },
            }
    except Exception:
        pass

    provider = get_vibe_provider()
    data = await provider.get_fundflow(code)
    if data.get("data") or (data.get("_meta") or {}).get("available"):
        return data

    try:
        native = await get_native_fundflow(code)
        if native is not None:
            return native
    except Exception:
        pass

    try:
        from src.infrastructure.market_data.stock_skill_bridge import (
            fetch_tencent_quotes,
            normalize_stock_code,
        )

        normalized = normalize_stock_code(code)
        quotes = await fetch_tencent_quotes([normalized], timeout_seconds=3.0)
        quote = quotes.get(normalized) or {}
        active_ratio = quote.get("active_volume_ratio")
        if active_ratio is None:
            return data
        return {
            "data": {
                "name": quote.get("name") or normalized,
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "main_net_pct": round(float(active_ratio) * 100, 2),
                "outer_volume_lots": quote.get("outer_volume_lots"),
                "inner_volume_lots": quote.get("inner_volume_lots"),
                "amount_wan": quote.get("amount_wan"),
                "data_date": quote.get("data_date"),
                "proxy_type": "active_trade_ratio",
            },
            "_meta": {
                "provider": "stock_skill_tencent_live_quote",
                "fetched_at": quote.get("fetched_at", ""),
                "available": True,
                "is_proxy": True,
                "warning": "主力资金源不可用；当前展示主动买卖盘差额占比代理指标",
                "error": "",
            },
        }
    except Exception:
        return data
