"""Plugin Discovery — 扫描 plugins/ 目录，发现 plugin.yaml

流程:
  1. 扫描配置的插件目录
  2. 找到所有 plugin.yaml
  3. 解析为 PluginManifest (frozen)
  4. 返回 Manifest 列表
  5. 最后一步才由 Loader import Python 模块
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Optional

from loguru import logger

from src.infrastructure.plugin_registry.manifest import PluginManifest


class PluginDiscovery:
    """插件发现器 — 扫描目录 + 解析 manifest"""

    def __init__(self, plugin_dirs: list[str] | None = None):
        self._plugin_dirs = plugin_dirs or ["plugins/datasource", "plugins/signal"]

    async def discover(self) -> list[tuple[Path, PluginManifest]]:
        """扫描所有插件目录 → 返回 (plugin_dir, manifest) 列表

        不会 import Python 模块。
        解析失败的插件不会影响其他插件。
        """
        results: list[tuple[Path, PluginManifest]] = []

        for dir_path in self._plugin_dirs:
            plugin_root = Path(dir_path)
            if not plugin_root.exists():
                logger.warning("Plugin directory not found: {}", dir_path)
                continue

            for plugin_dir in plugin_root.iterdir():
                if not plugin_dir.is_dir():
                    continue
                if plugin_dir.name.startswith("_"):  # 跳过 _template
                    continue

                manifest = await self._discover_one(plugin_dir)
                if manifest:
                    results.append((plugin_dir, manifest))

        logger.info("Discovered {} plugins in {} directories", len(results), len(self._plugin_dirs))
        return results

    async def _discover_one(self, plugin_dir: Path) -> Optional[PluginManifest]:
        """发现单个插件"""
        yaml_path = plugin_dir / "plugin.yaml"
        if not yaml_path.exists():
            logger.debug("No plugin.yaml in {}", plugin_dir)
            return None

        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if not data:
                logger.warning("Empty plugin.yaml: {}", yaml_path)
                return None

            manifest = PluginManifest.from_dict(data)
            logger.debug("Discovered plugin: {} ({})", manifest.display_name or manifest.name, yaml_path)
            return manifest

        except yaml.YAMLError as e:
            logger.error("Failed to parse plugin.yaml {}: {}", yaml_path, e)
            return None
        except Exception as e:
            logger.error("Failed to load plugin manifest from {}: {}", yaml_path, e)
            return None


async def discover_plugins(plugin_dirs: list[str] | None = None) -> list[tuple[Path, PluginManifest]]:
    """快捷函数"""
    discovery = PluginDiscovery(plugin_dirs)
    return await discovery.discover()
