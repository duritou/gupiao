"""Signal 基类 — 所有信号必须实现 compute()"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SignalDirection(Enum):
    BUY = "buy"
    SELL = "sell"
    NEUTRAL = "neutral"


class SignalCategory(Enum):
    TECHNICAL = "technical"     # MACD/RSI/KDJ/MA/BOLL
    VOLUME = "volume"           # 成交量/换手率
    CAPITAL = "capital"         # 资金流向/北向/主力
    EVENT = "event"             # 龙虎榜/公告/新闻
    SENTIMENT = "sentiment"     # 市场情绪
    FUNDAMENTAL = "fundamental" # 财务/估值
    ML = "ml"                   # 机器学习信号


@dataclass
class SignalResult:
    """信号计算结果"""

    signal_name: str
    category: SignalCategory
    score: float                # 0-100
    direction: SignalDirection
    reason: str = ""
    detail: dict = field(default_factory=dict)


class BaseSignal(ABC):
    """信号基类"""

    name: str = "base"
    category: SignalCategory = SignalCategory.TECHNICAL
    default_weight: float = 1.0

    @abstractmethod
    async def compute(
        self,
        stock_code: str,
        data: list[dict],         # OHLCV list: [{"open":...,"close":...,...}, ...]
    ) -> SignalResult:
        """计算单个股票的信号评分"""
        ...

    async def compute_batch(
        self,
        stock_code: str,
        data: list[dict],
    ) -> SignalResult:
        """批量计算（默认单次，子类可优化）"""
        return await self.compute(stock_code, data)
