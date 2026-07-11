"""User Profile Routes — v7.5: honest about data status.

User behavior profile requires real interaction data. Until the system
accumulates enough real user data, returns honest "数据积累中" status.

Previously (v6-v7.4): generated fake user profiles from fake trust snapshots.
Now (v7.5): minimal profile. User profiling requires real behavior.
"""

from fastapi import APIRouter, Query

router = APIRouter(tags=["user"], prefix="/user")


@router.get("/profile")
async def user_profile():
    return {
        "status": "insufficient_data",
        "message": "用户画像数据积累中",
        "detail": (
            "AI 需要通过真实的投资行为来学习你的风格、风险偏好、"
            "行业优势领域和策略特长。当前尚未积累足够的行为数据。"
            "预计需要至少30次真实交互记录才能生成有意义的用户画像。"
        ),
        "profile_version": "v7.5-minimal",
        "current_interactions": 0,
        "min_required": 30,
    }


@router.get("/profile/summary")
async def profile_summary():
    return {
        "status": "insufficient_data",
        "summary": "数据不足，无法生成用户画像摘要。",
        "greeting": "欢迎使用量化AI研究平台。随着你的使用，AI会逐渐了解你的投资风格。",
    }


@router.get("/adapt")
async def adapt_recommendation(
    stock_code: str = Query(""),
    base_score: float = Query(70.0),
):
    if not stock_code:
        from src.api.routes.journal_utils import recommended_codes
        codes = recommended_codes(limit=1)
        stock_code = codes[0] if codes else ""
    return {
        "status": "insufficient_data",
        "stock_code": stock_code,
        "base_score": base_score,
        "adjusted_score": base_score,
        "message": "用户画像数据不足，无法进行个性化调整。当前返回基础评分。",
        "adjustments": [],
    }
