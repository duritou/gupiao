"""MarketGateway — 统一数据网关实现

所有数据请求统一入口。内部通过 CapabilityRouter 自动选择数据源。
业务代码永远不 import 具体 Adapter。零 Provider 泄漏。

使用:
  gateway = MarketGateway(registry)
  quotes = await gateway.fetch_quotes(["000001.SZ", "000002.SZ"])
  history = await gateway.fetch_history("000001.SZ", "1d", "2026-01-01", "2026-07-01")

如果 AKShare 挂了 → 自动 fallback 到 Tushare。
如果都不支持某个能力 → 返回空列表 + log warning。
"""

from __future__ import annotations

from loguru import logger

from src.domain.ports.market_gateway_port import (
    MarketGatewayPort,
    Quote,
    Kline,
    FinancialData,
    LHBRecord,
    FundFlow,
)
from src.infrastructure.plugin_registry.registry import PluginRegistry
from src.infrastructure.adapters.market_gateway.router import CapabilityRouter
from src.shared.plugin_protocol import DataSourcePlugin


class MarketGateway(MarketGatewayPort):
    """统一数据网关 — 零 Provider 泄漏"""

    def __init__(self, registry: PluginRegistry):
        self._registry = registry
        self._router = CapabilityRouter(registry)

    # ===== Quotes =====

    async def fetch_quotes(self, codes: list[str]) -> list[Quote]:
        plugins = self._router.find_all_plugins("supports_realtime")
        if not plugins:
            logger.warning("No active plugin supports realtime quotes")
            return []

        for plugin in plugins:
            try:
                result = await plugin.fetch_quotes(codes)
                return [Quote(**item) if isinstance(item, dict) else item for item in result]
            except Exception as e:
                logger.warning("Plugin {} fetch_quotes failed: {}", plugin.manifest.name, e)
                continue

        logger.error("All plugins failed for fetch_quotes")
        return []

    # ===== History =====

    async def fetch_history(
        self,
        code: str,
        period: str = "1d",
        start: str = "",
        end: str = "",
    ) -> list[Kline]:
        plugins = self._router.find_all_plugins("supports_history")
        if not plugins:
            logger.warning("No active plugin supports history data")
            return []

        for plugin in plugins:
            try:
                result = await plugin.fetch_history(code, period, start, end)
                return [Kline(**item) if isinstance(item, dict) else item for item in result]
            except Exception as e:
                logger.warning("Plugin {} fetch_history failed: {}", plugin.manifest.name, e)
                continue

        logger.error("All plugins failed for fetch_history")
        return []

    # ===== Financials =====

    async def fetch_financials(self, code: str) -> list[FinancialData]:
        plugins = self._router.find_all_plugins("supports_financials")
        if not plugins:
            logger.warning("No active plugin supports financials")
            return []

        for plugin in plugins:
            try:
                result = await plugin.fetch_financials(code)
                return [FinancialData(**item) if isinstance(item, dict) else item for item in result]
            except Exception as e:
                logger.warning("Plugin {} fetch_financials failed: {}", plugin.manifest.name, e)
                continue

        return []

    # ===== LHB =====

    async def fetch_lhb(self, date: str) -> list[LHBRecord]:
        plugins = self._router.find_all_plugins("supports_lhb")
        if not plugins:
            logger.warning("No active plugin supports LHB data")
            return []

        for plugin in plugins:
            try:
                result = await plugin.fetch_lhb(date)
                return [LHBRecord(**item) if isinstance(item, dict) else item for item in result]
            except Exception as e:
                logger.warning("Plugin {} fetch_lhb failed: {}", plugin.manifest.name, e)
                continue

        return []

    # ===== Fund Flow =====

    async def fetch_fund_flow(self, code: str, days: int = 5) -> list[FundFlow]:
        plugins = self._router.find_all_plugins("supports_fund_flow")
        if not plugins:
            logger.warning("No active plugin supports fund flow data")
            return []

        for plugin in plugins:
            try:
                result = await plugin.fetch_fund_flow(code, days)
                return [FundFlow(**item) if isinstance(item, dict) else item for item in result]
            except Exception as e:
                logger.warning("Plugin {} fetch_fund_flow failed: {}", plugin.manifest.name, e)
                continue

        return []

    # ===== Health =====

    async def health_check(self) -> dict[str, bool]:
        result = {}
        for manifest in self._registry.list_active():
            instance = self._registry.get_instance(manifest.name)
            if instance:
                try:
                    result[manifest.name] = await instance.health_check()
                except Exception:
                    result[manifest.name] = False
            else:
                result[manifest.name] = False
        return result

    # ===== Utility =====

    def get_available_capabilities(self) -> dict[str, list[str]]:
        """获取当前可用能力概览"""
        return self._router.list_available_capabilities()
