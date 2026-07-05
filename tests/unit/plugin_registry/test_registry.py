"""PluginRegistry 单元 + 集成测试"""

import pytest
from pathlib import Path

from src.infrastructure.plugin_registry.manifest import PluginType
from src.infrastructure.plugin_registry.state import PluginState
from src.infrastructure.plugin_registry.registry import PluginRegistry


TEST_PLUGIN_DIRS = ["tests/fixtures/plugins/datasource"]


class TestRegistryDiscovery:
    """Discovery 阶段测试"""

    @pytest.mark.asyncio
    async def test_discover_finds_test_plugin(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        manifests = await registry.discover_all()
        assert len(manifests) == 1
        assert manifests[0].name == "test_source"

    @pytest.mark.asyncio
    async def test_discover_empty_dir(self):
        registry = PluginRegistry(plugin_dirs=["tests/fixtures/plugins/nonexistent"])
        manifests = await registry.discover_all()
        assert len(manifests) == 0

    @pytest.mark.asyncio
    async def test_discover_skips_template(self):
        """_template 目录被跳过"""
        registry = PluginRegistry(plugin_dirs=["plugins/datasource"])
        manifests = await registry.discover_all()
        names = [m.name for m in manifests]
        assert "my_datasource" not in names  # _template 里的


class TestRegistryLoad:
    """Load + Activate 阶段测试"""

    @pytest.mark.asyncio
    async def test_load_all_activates_plugin(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        results = await registry.load_all()
        assert results["test_source"] is True

    @pytest.mark.asyncio
    async def test_active_plugin_appears_in_list_active(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        await registry.load_all()
        active = registry.list_active()
        assert len(active) == 1
        assert active[0].name == "test_source"

    @pytest.mark.asyncio
    async def test_load_one(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        ok = await registry.load_one("test_source")
        assert ok is True
        assert registry.get_state("test_source").state == PluginState.ACTIVE


class TestRegistryStateManagement:
    """状态管理测试"""

    @pytest.mark.asyncio
    async def test_status_summary(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        summary = registry.get_status_summary()
        assert summary["total"] == 1
        assert "DISCOVERED" in summary["by_state"]

    @pytest.mark.asyncio
    async def test_get_state_after_discovery(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        state = registry.get_state("test_source")
        assert state.state == PluginState.DISCOVERED

    @pytest.mark.asyncio
    async def test_get_state_after_load(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        await registry.load_all()
        state = registry.get_state("test_source")
        assert state.state == PluginState.ACTIVE


class TestRegistryQueries:
    """查询测试 — 无业务知识"""

    @pytest.mark.asyncio
    async def test_list_by_type(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        datasources = registry.list_by_type(PluginType.DATASOURCE)
        assert len(datasources) == 1
        # 无 SIGNAL 类型插件
        assert len(registry.list_by_type(PluginType.SIGNAL)) == 0

    @pytest.mark.asyncio
    async def test_find_by_capability(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        # 有 supports_lhb
        found = registry.find_by_capability("supports_lhb", True)
        assert len(found) == 1
        # 没有 supports_news
        not_found = registry.find_by_capability("supports_news", True)
        assert len(not_found) == 0

    @pytest.mark.asyncio
    async def test_get_manifest(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        m = registry.get("test_source")
        assert m.name == "test_source"
        assert m.version == "1.0.0"

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        with pytest.raises(KeyError):
            registry.get("nonexistent")


class TestRegistryLifecycle:
    """Enable/Disable/Reload/Shutdown 测试"""

    @pytest.mark.asyncio
    async def test_disable_and_enable(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        await registry.load_all()

        # Disable
        ok = await registry.disable("test_source")
        assert ok is True
        assert registry.get_state("test_source").state == PluginState.DISABLED

        # Enable
        ok = await registry.enable("test_source")
        assert ok is True
        assert registry.get_state("test_source").state == PluginState.ACTIVE

    @pytest.mark.asyncio
    async def test_reload(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        await registry.load_all()

        ok = await registry.reload("test_source")
        assert ok is True
        assert registry.get_state("test_source").state == PluginState.ACTIVE

    @pytest.mark.asyncio
    async def test_shutdown_all(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        await registry.load_all()

        await registry.shutdown_all()
        assert registry.get_state("test_source").state == PluginState.STOPPED

    @pytest.mark.asyncio
    async def test_disable_not_active_fails(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        # 还未加载，不能 disable
        ok = await registry.disable("test_source")
        assert ok is False

    @pytest.mark.asyncio
    async def test_reload_all(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        await registry.load_all()
        results = await registry.reload_all()
        assert results["test_source"] is True


class TestRegistryProperties:
    """属性测试"""

    @pytest.mark.asyncio
    async def test_entry_count(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        assert registry.entry_count == 0
        await registry.discover_all()
        assert registry.entry_count == 1

    @pytest.mark.asyncio
    async def test_list_all(self):
        registry = PluginRegistry(plugin_dirs=TEST_PLUGIN_DIRS)
        await registry.discover_all()
        assert len(registry.list_all()) == 1
