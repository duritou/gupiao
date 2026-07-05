"""DataSource Adapter 基类 — 提供默认空实现，子类按需覆盖"""

from __future__ import annotations

from src.infrastructure.plugin_registry.manifest import PluginManifest
from src.shared.plugin_protocol import DataSourcePlugin as DSP


class BaseDataSourceAdapter(DSP):
    """数据源适配器基类

    提供所有 fetch_* 方法的默认空实现。
    子类只需覆盖自己支持的方法。
    """

    def __init__(self, manifest: PluginManifest):
        super().__init__(manifest)

    async def initialize(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def shutdown(self) -> None:
        pass

    async def fetch_quotes(self, codes: list[str]) -> list[dict]:
        return []

    async def fetch_history(self, code: str, period: str, start: str, end: str) -> list[dict]:
        return []

    async def fetch_financials(self, code: str) -> list[dict]:
        return []

    async def fetch_lhb(self, date: str) -> list[dict]:
        return []

    async def fetch_fund_flow(self, code: str, days: int = 5) -> list[dict]:
        return []

    async def fetch_news(self, code: str, days: int = 3) -> list[dict]:
        return []
