"""Plugin Loader — 动态 import Python 模块

流程:
  1. 接收已校验的 PluginManifest + plugin_dir
  2. 动态 import entry_point (module:Class)
  3. 实例化插件
  4. 返回插件实例

这是整个 Pipeline 的最后一步。
Discovery / Validator 都不 import 模块。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from src.infrastructure.plugin_registry.manifest import PluginManifest
from src.shared.plugin_protocol import BasePlugin


class PluginLoader:
    """插件加载器 — 只负责 import + 实例化"""

    def __init__(self):
        self._loaded_modules: dict[str, type] = {}

    async def load(self, plugin_dir: Path, manifest: PluginManifest) -> BasePlugin:
        """加载插件 → 返回实例

        Raises:
            PluginLoadError: 加载失败
        """
        module_path, class_name = self._parse_entry_point(manifest.entry_point)
        logger.debug("Loading plugin: {} -> {}:{}", manifest.name, module_path, class_name)

        # 1. 将插件目录加入 sys.path
        plugin_parent = str(plugin_dir.parent)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)

        try:
            # 2. 动态 import
            module = importlib.import_module(f"{plugin_dir.name}.{module_path}")
            plugin_cls = getattr(module, class_name, None)

            if plugin_cls is None:
                raise PluginLoadError(
                    f"Class '{class_name}' not found in module '{module_path}'"
                )

            if not issubclass(plugin_cls, BasePlugin):
                raise PluginLoadError(
                    f"Class '{class_name}' does not implement BasePlugin"
                )

            # 3. 实例化
            instance = plugin_cls(manifest)
            self._loaded_modules[manifest.name] = plugin_cls

            logger.info("Plugin loaded: {} v{}", manifest.name, manifest.version)
            return instance

        except (ImportError, ModuleNotFoundError) as e:
            raise PluginLoadError(
                f"Failed to import module for plugin '{manifest.name}': {e}"
            ) from e
        except Exception as e:
            if not isinstance(e, PluginLoadError):
                raise PluginLoadError(
                    f"Failed to load plugin '{manifest.name}': {e}"
                ) from e
            raise

    async def unload(self, manifest: PluginManifest) -> None:
        """卸载插件模块（尽力而为）"""
        module_key = f"{manifest.name}"
        self._loaded_modules.pop(module_key, None)
        logger.debug("Plugin unloaded: {}", manifest.name)

    @staticmethod
    def _parse_entry_point(entry_point: str) -> tuple[str, str]:
        """解析 'module:Class' 格式"""
        parts = entry_point.rsplit(":", 1)
        if len(parts) != 2:
            raise PluginLoadError(f"Invalid entry_point format: '{entry_point}'")
        return parts[0], parts[1]


class PluginLoadError(Exception):
    """插件加载失败"""
    pass
