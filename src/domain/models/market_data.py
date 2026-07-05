"""MarketData 领域模型"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class MarketData:
    """K线数据 — 值对象 (不可变)"""

    stock_code: str
    period: str                     # 1d / 1w / 1m / 60m / ...
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal = Decimal("0")
    turnover_rate: Optional[Decimal] = None
    change_pct: Optional[Decimal] = None
    id: Optional[int] = None
