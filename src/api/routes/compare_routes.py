"""Compare routes — side-by-side stock comparison"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.shared.mock_data import generate_klines, mock_signal_result, get_stock_name

router = APIRouter(tags=["compare"], prefix="/compare")


class CompareRequest(BaseModel):
    codes: list[str]


@router.post("")
async def compare_stocks(req: CompareRequest):
    """Compare multiple stocks side by side."""
    stocks = []
    for code in req.codes[:6]:  # Max 6 at a time
        klines = generate_klines(code, 80)
        signal = mock_signal_result(code, klines)

        stocks.append({
            "stock_code": code,
            "stock_name": get_stock_name(code),
            "ai_score": signal["fusion_score"],
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "stars": 5 if signal["fusion_score"] >= 80 else 4 if signal["fusion_score"] >= 65 else
                     3 if signal["fusion_score"] >= 45 else 2,
            "macd": "✓ 金叉" if signal["scores"].get("macd", 50) >= 60 else
                    "✗ 死叉" if signal["scores"].get("macd", 50) <= 40 else "→ 中性",
            "rsi": round(signal["scores"].get("rsi", 50)),
            "ma": "多头排列" if signal["scores"].get("ma", 50) >= 60 else
                  "空头排列" if signal["scores"].get("ma", 50) <= 40 else "横盘整理",
            "volume": "放量" if signal["scores"].get("volume", 50) >= 60 else
                      "缩量" if signal["scores"].get("volume", 50) <= 40 else "正常",
            "valuation": "偏高" if signal["fusion_score"] >= 75 and signal["direction"] == "buy" else
                         "合理" if 45 <= signal["fusion_score"] <= 75 else "偏低",
            "industry_score": signal["scores"].get("boll", 50),
            "recommendation": "买入" if signal["fusion_score"] >= 75 else
                            "持有" if signal["fusion_score"] >= 55 else
                            "观望" if signal["fusion_score"] >= 40 else "回避",
            "top_signal": signal["top_signal"],
            "risk_level": signal["risk_level"],
        })

    return {"stocks": stocks}
