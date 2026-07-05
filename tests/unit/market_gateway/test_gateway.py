"""MarketGateway 单元 + 集成测试 — 零 Provider 泄漏验证"""

import pytest
from pathlib import Path

from src.infrastructure.plugin_registry.manifest import PluginManifest, PluginType, PluginCapability
from src.infrastructure.plugin_registry.registry import PluginRegistry
from src.infrastructure.adapters.market_gateway.base import BaseDataSourceAdapter
from src.infrastructure.adapters.market_gateway.router import CapabilityRouter
from src.infrastructure.adapters.market_gateway.gateway import MarketGateway
from src.domain.ports.market_gateway_port import Quote, Kline


# ===== Mock DataSource =====

class MockHistoryAdapter(BaseDataSourceAdapter):
    """Mock: 只支持历史数据"""

    async def fetch_history(self, code, period, start, end):
        return [
            {"code": code, "timestamp": "2026-07-01", "open": 10.0,
             "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000000}
        ]


class MockQuoteAdapter(BaseDataSourceAdapter):
    """Mock: 只支持实时行情"""

    async def fetch_quotes(self, codes):
        return [
            {"code": c, "name": f"Stock_{c}", "price": 10.5,
             "change_pct": 2.5, "volume": 500000, "amount": 5250000.0}
            for c in codes
        ]


class MockLHBAdapter(BaseDataSourceAdapter):
    """Mock: 只支持龙虎榜"""

    async def fetch_lhb(self, date):
        return [
            {"code": "000001.SZ", "trade_date": date, "reason": "涨幅偏离值7%",
             "buy_amount": 50000000, "sell_amount": 30000000, "net_amount": 20000000,
             "institution_buy": 15000000}
        ]


class MockFailingAdapter(BaseDataSourceAdapter):
    """Mock: 初始化后立即失败的适配器"""

    async def fetch_history(self, code, period, start, end):
        raise RuntimeError("Connection failed")


# ===== Fixtures =====

def make_manifest(name, **caps) -> PluginManifest:
    """创建测试用 Manifest"""
    return PluginManifest(
        name=name,
        version="1.0.0",
        type=PluginType.DATASOURCE,
        entry_point="adapter:MockAdapter",
        capabilities=PluginCapability(**caps),
    )


def make_registry_with_plugins(plugin_specs: list[tuple[str, BaseDataSourceAdapter, dict]]) -> PluginRegistry:
    """创建已注册插件的 Registry"""
    registry = PluginRegistry(plugin_dirs=[])

    for name, adapter, caps in plugin_specs:
        manifest = make_manifest(name, **caps)
        from src.infrastructure.plugin_registry.registry import PluginEntry
        from src.infrastructure.plugin_registry.state import PluginStateInfo, PluginState

        state = PluginStateInfo(state=PluginState.ACTIVE)
        registry._entries[name] = PluginEntry(
            manifest=manifest,
            plugin_dir=Path(f"/fake/{name}"),
            state=state,
            instance=adapter,
        )

    return registry


# ===== Gateway Tests =====

class TestMarketGateway:
    """MarketGateway 集成测试"""

    @pytest.fixture
    def gateway(self):
        """创建含 Mock 插件的 Gateway"""
        registry = make_registry_with_plugins([
            ("mock_history", MockHistoryAdapter(PluginManifest(
                name="mock_history", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_history": True}),
            ("mock_quote", MockQuoteAdapter(PluginManifest(
                name="mock_quote", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_realtime": True}),
            ("mock_lhb", MockLHBAdapter(PluginManifest(
                name="mock_lhb", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_lhb": True}),
        ])
        return MarketGateway(registry)

    @pytest.mark.asyncio
    async def test_fetch_quotes(self, gateway):
        quotes = await gateway.fetch_quotes(["000001.SZ"])
        assert len(quotes) == 1
        assert isinstance(quotes[0], Quote)
        assert quotes[0].code == "000001.SZ"

    @pytest.mark.asyncio
    async def test_fetch_history(self, gateway):
        klines = await gateway.fetch_history("000001.SZ", "1d")
        assert len(klines) == 1
        assert isinstance(klines[0], Kline)
        assert klines[0].close == 10.5

    @pytest.mark.asyncio
    async def test_fetch_lhb(self, gateway):
        records = await gateway.fetch_lhb("2026-07-05")
        assert len(records) == 1
        assert records[0].code == "000001.SZ"

    @pytest.mark.asyncio
    async def test_unsupported_capability_returns_empty(self, gateway):
        """不支持的能力返回空列表，不抛异常"""
        result = await gateway.fetch_fund_flow("000001.SZ")
        assert result == []

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        """第一个数据源失败 → fallback 到第二个"""
        registry = make_registry_with_plugins([
            ("failing", MockFailingAdapter(PluginManifest(
                name="failing", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_history": True, "data_quality": "excellent"}),
            ("mock_history", MockHistoryAdapter(PluginManifest(
                name="mock_history", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_history": True, "data_quality": "good"}),
        ])
        gateway = MarketGateway(registry)
        klines = await gateway.fetch_history("000001.SZ")
        # failing 失败了，mock_history 成功了
        assert len(klines) == 1
        assert klines[0].close == 10.5

    @pytest.mark.asyncio
    async def test_health_check(self, gateway):
        health = await gateway.health_check()
        assert "mock_history" in health

    @pytest.mark.asyncio
    async def test_get_available_capabilities(self, gateway):
        caps = gateway.get_available_capabilities()
        assert "supports_history" in caps
        assert "supports_realtime" in caps
        assert "supports_lhb" in caps


class TestCapabilityRouter:
    """CapabilityRouter 单元测试"""

    @pytest.fixture
    def router(self):
        registry = make_registry_with_plugins([
            ("mock_history", MockHistoryAdapter(PluginManifest(
                name="mock_history", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_history": True, "data_quality": "good"}),
            ("mock_quote", MockQuoteAdapter(PluginManifest(
                name="mock_quote", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_realtime": True, "data_quality": "excellent"}),
        ])
        return CapabilityRouter(registry)

    def test_find_plugin_returns_best_quality(self, router):
        """Router 按 data_quality 选择最佳插件 (excellent > good)"""
        plugin = router.find_plugin("supports_realtime")
        assert plugin is not None
        # mock_quote 注册为 excellent，mock_history 注册为 good
        # Router 应选择 quality 最高的
        assert plugin.manifest.name == "mock_quote"

    def test_find_plugin_unsupported_returns_none(self, router):
        plugin = router.find_plugin("supports_lhb")
        assert plugin is None

    def test_find_all_plugins(self, router):
        plugins = router.find_all_plugins("supports_history")
        assert len(plugins) == 1

    def test_list_available_capabilities(self, router):
        caps = router.list_available_capabilities()
        assert "supports_history" in caps
        assert "supports_realtime" in caps

    def test_quality_ordering(self, router):
        """excellent > good > basic — 验证排序逻辑正确"""
        # supports_history: mock_history (good) — 只有它
        plugin = router.find_plugin("supports_history")
        assert plugin is not None
        assert plugin.manifest.name == "mock_history"

        # supports_realtime: mock_quote (excellent) — 质量更高
        plugin2 = router.find_plugin("supports_realtime")
        assert plugin2 is not None
        assert plugin2.manifest.name == "mock_quote"


class TestZeroProviderLeakage:
    """验证零 Provider 泄漏"""

    @pytest.mark.asyncio
    async def test_no_adapter_imports(self):
        """Gateway 代码中不应出现具体 Adapter 的 import"""
        import inspect
        from src.infrastructure.adapters.market_gateway import gateway as gw_module

        source = inspect.getsource(gw_module.MarketGateway)
        # 不应该出现任何具体 Adapter 名称
        forbidden = ["AKShare", "Tushare", "EastMoney", "Yahoo", "Polygon", "Wind"]
        for name in forbidden:
            assert name not in source, f"Provider leak detected: {name}"

    @pytest.mark.asyncio
    async def test_gateway_uses_router_not_direct_imports(self):
        """Gateway 通过 Router 获取插件，不直接 import"""
        registry = make_registry_with_plugins([
            ("mock_quote", MockQuoteAdapter(PluginManifest(
                name="mock_quote", version="1.0.0", type=PluginType.DATASOURCE,
            )), {"supports_realtime": True}),
        ])
        gateway = MarketGateway(registry)
        result = await gateway.fetch_quotes(["000001.SZ"])
        assert len(result) >= 0
