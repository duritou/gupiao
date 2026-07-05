"""Market Gateway Port — 统一数据网关端口（Domain 层接口）

所有数据访问必须经过此端口。业务代码永远不 import 具体 Adapter。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Quote:
    """实时行情"""
    code: str
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    amount: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    pre_close: float = 0.0
    timestamp: str = ""


@dataclass(frozen=True)
class Kline:
    """K线数据"""
    code: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float = 0.0


@dataclass(frozen=True)
class FinancialData:
    """财务数据"""
    code: str
    report_date: str
    eps: float = 0.0
    bps: float = 0.0
    roe: float = 0.0
    total_revenue: float = 0.0
    net_profit: float = 0.0


@dataclass(frozen=True)
class LHBRecord:
    """龙虎榜记录"""
    code: str
    trade_date: str
    reason: str = ""
    buy_amount: float = 0.0
    sell_amount: float = 0.0
    net_amount: float = 0.0
    institution_buy: float = 0.0


@dataclass(frozen=True)
class FundFlow:
    """资金流向"""
    code: str
    date: str
    main_net_inflow: float = 0.0
    north_bound_inflow: float = 0.0


class MarketGatewayPort(ABC):
    """统一数据网关端口 — 所有数据访问的唯一入口

    业务代码只调用此接口，不 import 任何具体 Adapter。
    Gateway 内部通过 CapabilityRouter 自动选择数据源。
    """

    @abstractmethod
    async def fetch_quotes(self, codes: list[str]) -> list[Quote]:
        """获取实时行情"""
        ...

    @abstractmethod
    async def fetch_history(
        self,
        code: str,
        period: str = "1d",
        start: str = "",
        end: str = "",
    ) -> list[Kline]:
        """获取历史K线"""
        ...

    @abstractmethod
    async def fetch_financials(self, code: str) -> list[FinancialData]:
        """获取财务数据"""
        ...

    @abstractmethod
    async def fetch_lhb(self, date: str) -> list[LHBRecord]:
        """获取龙虎榜数据"""
        ...

    @abstractmethod
    async def fetch_fund_flow(self, code: str, days: int = 5) -> list[FundFlow]:
        """获取资金流向"""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, bool]:
        """各数据源健康状态"""
        ...
