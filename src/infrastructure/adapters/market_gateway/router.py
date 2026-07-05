"""CapabilityRouter — 按能力自动路由到最佳数据源

路由策略:
  1. 按 capability 过滤 (supports_history, supports_lhb, ...)
  2. 按 data_quality 排序 (excellent > good > basic)
  3. 返回优先级最高的插件
  4. 调用失败时 fallback 到下一个

零 Provider 泄漏: 返回的是 PluginManifest，不是 Adapter 实例。
"""

from __future__ import annotations

from loguru import logger

from src.infrastructure.plugin_registry.manifest import PluginManifest
from src.infrastructure.plugin_registry.registry import PluginRegistry
from src.shared.plugin_protocol import DataSourcePlugin


class CapabilityRouter:
    """能力路由器 — 根据能力声明选择数据源"""

    QUALITY_ORDER = {"excellent": 3, "good": 2, "basic": 1}

    def __init__(self, registry: PluginRegistry):
        self._registry = registry

    def find_plugin(self, capability: str) -> DataSourcePlugin | None:
        """按能力查找最佳可用插件 → 返回实例

        选择逻辑:
          1. 过滤: 只有声明了该 capability 的插件
          2. 过滤: 只选 ACTIVE 状态的插件
          3. 排序: data_quality 最高的优先
          4. 返回: 第一个的实例

        Manifest 信息从 Registry entry 读取（非 instance.manifest），
        因为 Registry 中的 Manifest 才是经过校验的权威版本。
        """
        candidates = self._registry.find_by_capability(capability, True)
        if not candidates:
            return None

        active = [m for m in candidates
                  if self._registry.get_state(m.name).state.name == "ACTIVE"]

        if not active:
            return None

        active.sort(
            key=lambda m: self.QUALITY_ORDER.get(m.capabilities.data_quality, 0),
            reverse=True,
        )

        best_manifest = active[0]
        logger.debug(
            "Router selected {} for capability '{}' (quality: {})",
            best_manifest.name, capability, best_manifest.capabilities.data_quality,
        )
        instance = self._registry.get_instance(best_manifest.name)
        if isinstance(instance, DataSourcePlugin):
            return instance
        return None

    def find_all_plugins(self, capability: str) -> list[DataSourcePlugin]:
        """获取所有支持该能力的插件（用于 fallback 链）"""
        candidates = self._registry.find_by_capability(capability, True)
        active = [m for m in candidates
                  if self._registry.get_state(m.name).state.name == "ACTIVE"]
        active.sort(
            key=lambda m: self.QUALITY_ORDER.get(m.capabilities.data_quality, 0),
            reverse=True,
        )
        return [
            inst for m in active
            if (inst := self._registry.get_instance(m.name)) is not None
            and isinstance(inst, DataSourcePlugin)
        ]

    def list_available_capabilities(self) -> dict[str, list[str]]:
        """列出当前可用的能力 → 数据源映射"""
        result: dict[str, list[str]] = {}
        for manifest in self._registry.list_active():
            caps = manifest.capabilities
            for field_name in caps.__dataclass_fields__:
                if caps.has(field_name):
                    result.setdefault(field_name, []).append(manifest.name)
        return result
