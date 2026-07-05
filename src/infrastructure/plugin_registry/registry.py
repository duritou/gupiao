"""Plugin Registry — 插件注册中心

职责:
  - 发现 + 校验 + 加载 + 生命周期管理
  - 按类型/能力查询插件
  - enable / disable / reload
  - 元数据查询

不负责:
  - 业务逻辑 (不出现 if plugin.type == "datasource")
  - 缓存插件实例 (只保存 Manifest + State)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from src.infrastructure.plugin_registry.manifest import PluginManifest, PluginType
from src.infrastructure.plugin_registry.state import PluginState, PluginStateInfo
from src.infrastructure.plugin_registry.discovery import PluginDiscovery
from src.infrastructure.plugin_registry.validator import PluginValidator
from src.infrastructure.plugin_registry.loader import PluginLoader
from src.infrastructure.plugin_registry.lifecycle import PluginLifecycle
from src.shared.plugin_protocol import BasePlugin


@dataclass
class PluginEntry:
    """Registry 中的插件条目 — 不永久持有实例"""

    manifest: PluginManifest
    plugin_dir: Path
    state: PluginStateInfo = field(default_factory=PluginStateInfo)
    instance: BasePlugin | None = None  # 仅 ACTIVE 时有值


class PluginRegistry:
    """插件注册中心

    核心原则:
      1. 不缓存插件实例 — 只在 ACTIVE 时持有引用
      2. 无业务知识 — 不判断 type/datasource/signal
      3. 围绕 Manifest 工作 — 不直接操作 dict
    """

    def __init__(
        self,
        plugin_dirs: list[str] | None = None,
        core_version: str = "1.0.0",
    ):
        self._entries: dict[str, PluginEntry] = {}
        self._discovery = PluginDiscovery(plugin_dirs)
        self._validator = PluginValidator(core_version=core_version)
        self._loader = PluginLoader()
        self._lifecycle = PluginLifecycle(self._validator, self._loader)

    # ===== 发现 + 加载 =====

    async def discover_all(self) -> list[PluginManifest]:
        """发现所有插件 → 只到 DISCOVERED 状态"""
        discovered = await self._discovery.discover()
        for plugin_dir, manifest in discovered:
            if manifest.name not in self._entries:
                self._entries[manifest.name] = PluginEntry(
                    manifest=manifest,
                    plugin_dir=plugin_dir,
                    state=PluginStateInfo(state=PluginState.DISCOVERED),
                )
        return [e.manifest for e in self._entries.values()]

    async def load_all(self) -> dict[str, bool]:
        """加载所有已发现的插件 → 完整激活流程"""
        results: dict[str, bool] = {}

        for name, entry in list(self._entries.items()):
            if entry.state.state != PluginState.DISCOVERED:
                continue
            state, instance = await self._lifecycle.activate(
                entry.plugin_dir, entry.manifest
            )
            entry.state = state
            entry.instance = instance
            results[name] = state.state == PluginState.ACTIVE

        active = sum(1 for v in results.values() if v)
        logger.info("Plugin loading complete: {}/{} active", active, len(results))
        return results

    async def load_one(self, name: str) -> bool:
        """加载单个插件"""
        entry = self._get_entry(name)
        if entry.state.state == PluginState.ACTIVE:
            return True
        if entry.state.state == PluginState.DISABLED:
            return False

        state, instance = await self._lifecycle.activate(
            entry.plugin_dir, entry.manifest
        )
        entry.state = state
        entry.instance = instance
        return state.state == PluginState.ACTIVE

    # ===== 查询 =====

    def get(self, name: str) -> PluginManifest:
        """获取插件 Manifest"""
        return self._get_entry(name).manifest

    def get_instance(self, name: str) -> BasePlugin | None:
        """获取插件实例 (仅 ACTIVE)"""
        entry = self._get_entry(name)
        return entry.instance

    def list_all(self) -> list[PluginManifest]:
        """列出所有插件"""
        return [e.manifest for e in self._entries.values()]

    def list_by_type(self, plugin_type: PluginType) -> list[PluginManifest]:
        """按类型列出 — 无业务知识，纯数据过滤"""
        return [
            e.manifest for e in self._entries.values()
            if e.manifest.type == plugin_type
        ]

    def list_active(self) -> list[PluginManifest]:
        """列出所有 ACTIVE 插件"""
        return [
            e.manifest for e in self._entries.values()
            if e.state.state == PluginState.ACTIVE
        ]

    def find_by_capability(
        self,
        capability: str,
        value: bool = True,
    ) -> list[PluginManifest]:
        """按能力查找 — 无业务知识，纯 Manifest 字段过滤"""
        return [
            e.manifest for e in self._entries.values()
            if e.manifest.capabilities.has(capability) == value
        ]

    # ===== 生命周期管理 =====

    async def enable(self, name: str) -> bool:
        """启用插件"""
        entry = self._get_entry(name)
        if entry.state.state != PluginState.DISABLED:
            return False
        if entry.instance is None:
            return False
        await self._lifecycle.enable(entry.instance, entry.state)
        return True

    async def disable(self, name: str) -> bool:
        """禁用插件"""
        entry = self._get_entry(name)
        if entry.state.state != PluginState.ACTIVE:
            return False
        await self._lifecycle.disable(entry.state)
        return True

    async def reload(self, name: str) -> bool:
        """热重载单个插件"""
        entry = self._get_entry(name)

        # Shutdown
        if entry.instance:
            try:
                await entry.instance.shutdown()
            except Exception as e:
                logger.warning("Shutdown error during reload: {}", e)

        # 清理
        entry.instance = None
        entry.state = PluginStateInfo(state=PluginState.DISCOVERED)
        await self._loader.unload(entry.manifest)

        # 重新加载
        return await self.load_one(name)

    async def reload_all(self) -> dict[str, bool]:
        """热重载所有插件"""
        results = {}
        for name in list(self._entries.keys()):
            results[name] = await self.reload(name)
        return results

    async def shutdown_all(self) -> None:
        """关闭所有插件"""
        for entry in self._entries.values():
            if entry.instance:
                try:
                    await entry.instance.shutdown()
                except Exception as e:
                    logger.warning("Shutdown error for {}: {}", entry.manifest.name, e)
            entry.state.transition(PluginState.STOPPED)
        logger.info("All plugins shut down")

    # ===== 元数据 =====

    def get_state(self, name: str) -> PluginStateInfo:
        return self._get_entry(name).state

    def get_status_summary(self) -> dict:
        """获取状态摘要"""
        states = {}
        for entry in self._entries.values():
            state_name = entry.state.state.name
            states[state_name] = states.get(state_name, 0) + 1
        return {
            "total": len(self._entries),
            "by_state": states,
            "by_type": {
                t.value: len(self.list_by_type(t))
                for t in PluginType
                if self.list_by_type(t)
            },
        }

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # ===== 内部 =====

    def _get_entry(self, name: str) -> PluginEntry:
        if name not in self._entries:
            raise KeyError(f"Plugin not found: '{name}'")
        return self._entries[name]
