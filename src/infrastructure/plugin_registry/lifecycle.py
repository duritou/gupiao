"""Plugin Lifecycle — 插件生命周期管理

协调 Discovery → Validator → Loader → Initialize → Active 全流程。
不缓存插件实例，只管理状态转移。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.infrastructure.plugin_registry.manifest import PluginManifest
from src.infrastructure.plugin_registry.state import PluginState, PluginStateInfo
from src.infrastructure.plugin_registry.validator import PluginValidator, ValidationResult
from src.infrastructure.plugin_registry.loader import PluginLoader, PluginLoadError
from src.shared.plugin_protocol import BasePlugin


class PluginLifecycle:
    """插件生命周期管理器

    负责:
      1. 状态转移 (VALIDATED → LOADED → INITIALIZED → ACTIVE)
      2. 协调 Validator / Loader / Plugin.initialize()
      3. 错误时转移到 FAILED
    """

    def __init__(self, validator: PluginValidator, loader: PluginLoader):
        self._validator = validator
        self._loader = loader

    async def activate(
        self, plugin_dir: Path, manifest: PluginManifest
    ) -> tuple[PluginStateInfo, BasePlugin | None]:
        """完整激活流程 → 返回 (最终状态, 插件实例或 None)"""
        state = PluginStateInfo()

        # 1. Validate
        result = self._validator.validate(manifest)
        if not result.valid:
            state.transition_to_failed("; ".join(result.errors))
            return state, None
        state.transition(PluginState.VALIDATED)

        # 2. Load
        try:
            instance = await self._loader.load(plugin_dir, manifest)
        except PluginLoadError as e:
            state.transition_to_failed(str(e))
            return state, None
        state.transition(PluginState.LOADED)

        # 3. Initialize
        try:
            ok = await instance.initialize()
            if not ok:
                state.transition_to_failed("initialize() returned False")
                return state, None
        except Exception as e:
            state.transition_to_failed(f"initialize() raised: {e}")
            return state, None
        state.transition(PluginState.INITIALIZED)

        # 4. Active
        try:
            health = await instance.health_check()
            state.health_status = health
            if not health:
                logger.warning("Plugin {} health check returned False", manifest.name)
        except Exception as e:
            logger.warning("Plugin {} health check failed: {}", manifest.name, e)
            state.health_status = False

        state.transition(PluginState.ACTIVE)
        logger.info("Plugin {} is now ACTIVE", manifest.name)
        return state, instance

    async def deactivate(self, instance: BasePlugin, state: PluginStateInfo) -> None:
        """停用插件"""
        try:
            await instance.shutdown()
        except Exception as e:
            logger.warning("Plugin shutdown error: {}", e)
        state.transition(PluginState.STOPPED)

    async def disable(self, state: PluginStateInfo) -> None:
        """禁用插件（不 shutdown）"""
        if state.state != PluginState.ACTIVE:
            raise ValueError(f"Cannot disable: plugin is {state.state.name}")
        state.transition(PluginState.DISABLED)

    async def enable(self, instance: BasePlugin, state: PluginStateInfo) -> None:
        """重新启用"""
        if state.state != PluginState.DISABLED:
            raise ValueError(f"Cannot enable: plugin is {state.state.name}")
        try:
            health = await instance.health_check()
            state.health_status = health
        except Exception:
            state.health_status = False
        state.transition(PluginState.ACTIVE)
