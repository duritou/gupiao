"""PluginManifest + PluginCapability 单元测试"""

import pytest
from src.infrastructure.plugin_registry.manifest import (
    PluginManifest,
    PluginCapability,
    PluginType,
)


class TestPluginCapability:
    """PluginCapability 测试"""

    def test_default_values(self):
        cap = PluginCapability()
        assert cap.supports_realtime is False
        assert cap.supports_history is False
        assert cap.data_quality == "basic"

    def test_has_existing_capability(self):
        cap = PluginCapability(supports_lhb=True, supports_history=True)
        assert cap.has("supports_lhb") is True
        assert cap.has("supports_history") is True
        assert cap.has("supports_realtime") is False

    def test_has_nonexistent_capability(self):
        cap = PluginCapability()
        assert cap.has("nonexistent_field") is False

    def test_frozen(self):
        cap = PluginCapability(supports_history=True)
        with pytest.raises(Exception):
            cap.supports_history = False  # type: ignore


class TestPluginManifest:
    """PluginManifest 测试"""

    def test_from_dict_minimal(self):
        data = {
            "plugin": {
                "name": "test",
                "version": "1.0.0",
                "type": "datasource",
                "entry_point": "adapter:TestAdapter",
            }
        }
        m = PluginManifest.from_dict(data)
        assert m.name == "test"
        assert m.version == "1.0.0"
        assert m.type == PluginType.DATASOURCE
        assert m.api_version == 1

    def test_from_dict_with_capabilities(self):
        data = {
            "plugin": {
                "name": "test_source",
                "version": "2.0.0",
                "type": "datasource",
                "entry_point": "adapter:TestAdapter",
                "api_version": 1,
                "minimum_core": "1.0.0",
                "capabilities": {
                    "supports_history": True,
                    "supports_lhb": True,
                    "coverage_markets": ["SH", "SZ"],
                    "data_quality": "good",
                },
            }
        }
        m = PluginManifest.from_dict(data)
        assert m.capabilities.supports_history is True
        assert m.capabilities.supports_lhb is True
        assert m.capabilities.supports_realtime is False
        assert m.capabilities.coverage_markets == ["SH", "SZ"]
        assert m.capabilities.data_quality == "good"

    def test_from_dict_with_maximum_core(self):
        data = {
            "plugin": {
                "name": "test",
                "version": "1.0.0",
                "type": "datasource",
                "entry_point": "adapter:TestAdapter",
                "maximum_core": "2.x",
            }
        }
        m = PluginManifest.from_dict(data)
        assert m.maximum_core == "2.x"

    def test_default_values(self):
        m = PluginManifest(name="t", version="1.0.0", type=PluginType.DATASOURCE)
        assert m.entry_point == ""
        assert m.api_version == 1
        assert m.minimum_core == "1.0.0"
        assert m.maximum_core is None
        assert m.dependencies == []

    def test_frozen(self):
        m = PluginManifest(name="t", version="1.0.0", type=PluginType.DATASOURCE)
        with pytest.raises(Exception):
            m.name = "changed"  # type: ignore

    def test_plugin_type_enum(self):
        assert PluginType.DATASOURCE.value == "datasource"
        assert PluginType.SIGNAL.value == "signal"
        assert PluginType.AGENT.value == "agent"
