"""插件协议基类 — 所有插件的抽象

Plugin Registry 通过此协议发现/加载/管理插件。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class PluginType(Enum):
    DATASOURCE = "datasource"
    SIGNAL = "signal"
    AGENT = "agent"
    NOTIFICATION = "notification"
    BROKER = "broker"


@dataclass
class PluginManifest:
    """插件清单 — 从 plugin.yaml 解析"""

    name: str
    version: str
    type: PluginType
    display_name: str = ""
    description: str = ""
    author: str = ""
    entry_point: str = ""
    api_version: int = 1
    minimum_core: str = "1.0.0"
    maximum_core: str = ""
    dependencies: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)


class BasePlugin(ABC):
    """所有插件的基类"""

    manifest: PluginManifest

    def __init__(self, manifest: PluginManifest):
        self.manifest = manifest

    @abstractmethod
    async def initialize(self) -> bool:
        """初始化插件 — 返回 True 表示成功"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """优雅关闭"""
        ...


class DataSourcePlugin(BasePlugin):
    """数据源插件协议 — 所有数据源适配器必须实现"""

    @abstractmethod
    async def fetch_quotes(self, codes: list[str]) -> list[dict]:
        """获取实时行情"""
        ...

    @abstractmethod
    async def fetch_history(
        self, code: str, period: str, start: str, end: str
    ) -> list[dict]:
        """获取历史K线"""
        ...

    @abstractmethod
    async def fetch_financials(self, code: str) -> dict:
        """获取财务数据"""
        ...

    @abstractmethod
    async def fetch_lhb(self, date: str) -> list[dict]:
        """获取龙虎榜数据"""
        ...


class SignalPlugin(BasePlugin):
    """信号插件协议 — 所有信号必须实现"""

    @abstractmethod
    async def compute(self, stock_code: str, context: dict) -> dict:
        """计算单个股票的信号"""
        ...

    @abstractmethod
    async def compute_batch(
        self, stock_codes: list[str], context: dict
    ) -> list[dict]:
        """批量计算"""
        ...
