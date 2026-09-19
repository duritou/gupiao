"""Vibe-Research compatible API hosted by the Adaptive process.

This router keeps the existing Vibe frontend contract stable while allowing
the frontend to use Adaptive as its only data backend.  The implementation
calls Vibe's reusable modules in-process and does not import Vibe's FastAPI
application, avoiding a second server and duplicate schedulers.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.infrastructure.market_data.vibe_embedded import get_embedded_vibe_service
from src.infrastructure.market_data.vibe_provider import VIBE_PROVIDER_MODE
from investment_common import plain_code

router = APIRouter(prefix="/vibe", tags=["vibe-compat"])
_service = get_embedded_vibe_service()


def _code(value: str) -> str:
    normalized = plain_code(value)
    if not normalized.isdigit() or len(normalized) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return normalized


async def _call(module: str, function: str, *args, **kwargs) -> Any:
    try:
        return await _service.call(module, function, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Vibe 数据源异常：{exc}") from exc


def _data(value: Any) -> dict[str, Any]:
    return {"data": value}


@router.get("/health")
async def health():
    return {"ok": True, "service": "adaptive-vibe-compat", "vibe_mode": VIBE_PROVIDER_MODE}


@router.get("/market/overview")
async def market_overview():
    return _data(await _call("market", "get_overview"))


@router.get("/market/emotion")
async def market_emotion():
    return _data(await _call("market", "get_short_term_emotion"))


@router.get("/market/turnover-top")
async def market_turnover_top():
    return _data(await _call("market", "get_turnover_top"))


@router.get("/global/indices")
async def global_indices():
    return _data(await _call("market", "get_global_indices"))


@router.get("/global/stock")
async def global_stock(symbol: str = Query(..., min_length=1, max_length=16)):
    value = await _call("gstock", "us_hk_stock", symbol.strip())
    if not value:
        raise HTTPException(404, f"未找到美股/港股代码 {symbol}")
    return _data(value)


@router.get("/indices")
async def indices():
    return _data(await _call("astock", "index_quote"))


@router.get("/quote")
async def quote(codes: str = Query(...)):
    values = [_code(item) for item in codes.split(",") if item.strip()]
    if not values:
        raise HTTPException(400, "codes 不能为空")
    return _data(await _call("astock", "tencent_quote", list(dict.fromkeys(values))))


@router.get("/news")
async def news(code: str = Query(...), limit: int = Query(20, ge=1, le=50)):
    return _data(await _call("astock", "stock_news", _code(code), limit=limit))


@router.get("/margin")
async def margin(code: str = Query(...)):
    return _data(await _call("astock", "margin_trading", _code(code)))


@router.get("/block-trade")
async def block_trade(code: str = Query(...)):
    return _data(await _call("astock", "block_trade", _code(code)))


@router.get("/holders")
async def holders(code: str = Query(...)):
    return _data(await _call("astock", "holder_num_change", _code(code)))


@router.get("/dividend")
async def dividend(code: str = Query(...)):
    return _data(await _call("astock", "dividend_history", _code(code)))


@router.get("/lockup")
async def lockup(code: str = Query(...)):
    return _data(await _call("astock", "lockup_expiry", _code(code)))


@router.get("/blocks")
async def blocks(code: str = Query(...)):
    return _data(await _call("astock", "concept_blocks", _code(code)))


@router.get("/hot-concepts")
async def hot_concepts(code: str = Query(...)):
    return _data(await _call("astock", "hot_concepts", _code(code)))


@router.get("/investor-qa")
async def investor_qa(code: str = Query(...)):
    return _data(await _call("astock", "investor_qa", _code(code)))


@router.get("/industry")
async def industry(top: int = Query(20, ge=5, le=50)):
    return _data(await _call("astock", "industry_comparison", top_n=top))


@router.get("/portfolio")
async def portfolio():
    return _data(await _call("portfolio", "get_portfolio"))


class HoldingRequest(BaseModel):
    code: str
    shares: float
    cost: float


@router.post("/portfolio/holding")
async def add_holding(req: HoldingRequest):
    if req.shares <= 0:
        raise HTTPException(400, "数量必须大于 0")
    return _data(await _call("portfolio", "add_holding", _code(req.code), req.shares, req.cost))


@router.delete("/portfolio/holding")
async def remove_holding(code: str = Query(...)):
    return _data(await _call("portfolio", "remove_holding", _code(code)))


@router.post("/portfolio/refresh")
async def refresh_portfolio():
    return _data(await _call("portfolio", "get_portfolio"))


class CloseRequest(BaseModel):
    code: str
    date: str
    price: float
    shares: float
    cost: float


@router.post("/portfolio/close")
async def close_position(req: CloseRequest):
    return _data(await _call("portfolio", "close_position", _code(req.code), req.date, req.price, req.shares, req.cost))


@router.delete("/portfolio/close")
async def remove_closed(index: int = Query(..., ge=0)):
    return _data(await _call("portfolio", "remove_closed", index))


class LLMConfig(BaseModel):
    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str


class ChatRequest(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.messages or not req.llm.model:
        raise HTTPException(400, "messages 和 model 不能为空")
    is_cli = req.llm.provider.startswith("cli-")
    cfg = req.llm.model_dump()
    if not is_cli:
        key_env = {"deepseek": "DEEPSEEK_API_KEY"}.get(req.llm.provider)
        cfg["apiKey"] = (os.environ.get(key_env, "") if key_env else "") or req.llm.apiKey
        cfg["baseURL"] = req.llm.baseURL or {"deepseek": "https://api.deepseek.com"}.get(req.llm.provider, "")
        if not cfg["apiKey"] or not cfg["baseURL"]:
            raise HTTPException(400, "缺少 Base URL 或 API Key")
    if is_cli:
        kind = req.llm.provider[4:]
        detect_cli = _service.get_function("cli_runtime", "detect_cli")
        if not detect_cli(kind):
            raise HTTPException(400, f"未检测到 {kind} CLI")

    def generate():
        try:
            function_name = "run_chat_cli_stream" if is_cli else "run_chat_stream"
            run_chat = _service.get_function("chat", function_name)
            for event in run_chat(cfg, req.messages, req.context):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": f"对话失败：{exc}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
