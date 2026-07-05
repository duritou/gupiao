"""Stock 领域模型 — 纯 Python，持久化无关"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


@dataclass
class Stock:
    """股票实体 — 不依赖任何 ORM"""

    code: str                        # "000001.SZ"
    name: str = ""
    market: str = ""                 # SH / SZ / BJ
    industry: str = ""
    sub_industry: str = ""
    listing_date: Optional[date] = None
    delisting_date: Optional[date] = None
    status: str = "active"           # active / suspended / delisted
    total_shares: Optional[int] = None
    float_shares: Optional[int] = None
    id: Optional[int] = None         # DB 主键（新实体为 None）
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.delisting_date is None

    @property
    def market_display(self) -> str:
        return {"SH": "上海", "SZ": "深圳", "BJ": "北交所"}.get(self.market, self.market)

    def __hash__(self) -> int:
        return hash(self.code)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Stock):
            return False
        return self.code == other.code
