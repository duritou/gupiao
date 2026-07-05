"""Plugin Manifest — 强类型不可变模型

plugin.yaml 解析后的结构化表示。
整个 Registry 围绕 Manifest 工作，不直接操作 dict。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PluginType(Enum):
    """插件类型"""
    DATASOURCE = "datasource"
    SIGNAL = "signal"
    AGENT = "agent"
    NOTIFICATION = "notification"
    BROKER = "broker"


@dataclass(frozen=True)
class PluginCapability:
    """插件能力声明 — 只包含技术能力（不含合规权限）"""

    supports_realtime: bool = False
    supports_intraday: bool = False
    supports_history: bool = False
    supports_financials: bool = False
    supports_lhb: bool = False
    supports_fund_flow: bool = False
    supports_news: bool = False
    supports_indices: bool = False
    supports_sectors: bool = False
    coverage_markets: list[str] = field(default_factory=list)
    data_quality: str = "basic"     # basic / good / excellent
    latency: str = "t+0"
    rate_limit_recommended: int = 60

    def has(self, capability_name: str) -> bool:
        """检查是否具备某项能力"""
        return bool(getattr(self, capability_name, False))


@dataclass(frozen=True)
class PluginManifest:
    """插件清单 — frozen，整个生命周期不可变

    从 plugin.yaml 解析后创建。需要更新时用 dataclasses.replace()。
    """

    name: str
    version: str
    type: PluginType
    display_name: str = ""
    description: str = ""
    author: str = ""
    entry_point: str = ""
    api_version: int = 1
    minimum_core: str = "1.0.0"
    maximum_core: str | None = None
    dependencies: list[str] = field(default_factory=list)
    capabilities: PluginCapability = field(default_factory=PluginCapability)

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        """从 plugin.yaml 解析的 dict 创建 Manifest"""
        plugin_data = data.get("plugin", data)

        # 解析 capabilities
        cap_data = plugin_data.get("capabilities", {})
        capabilities = PluginCapability(
            supports_realtime=cap_data.get("supports_realtime", False),
            supports_intraday=cap_data.get("supports_intraday", False),
            supports_history=cap_data.get("supports_history", False),
            supports_financials=cap_data.get("supports_financials", False),
            supports_lhb=cap_data.get("supports_lhb", False),
            supports_fund_flow=cap_data.get("supports_fund_flow", False),
            supports_news=cap_data.get("supports_news", False),
            supports_indices=cap_data.get("supports_indices", False),
            supports_sectors=cap_data.get("supports_sectors", False),
            coverage_markets=cap_data.get("coverage_markets", []),
            data_quality=cap_data.get("data_quality", "basic"),
            latency=cap_data.get("latency", "t+0"),
            rate_limit_recommended=cap_data.get("rate_limit_recommended", 60),
        )

        return cls(
            name=plugin_data.get("name", ""),
            version=plugin_data.get("version", "0.0.0"),
            type=PluginType(plugin_data.get("type", "datasource")),
            display_name=plugin_data.get("display_name", ""),
            description=plugin_data.get("description", ""),
            author=plugin_data.get("author", ""),
            entry_point=plugin_data.get("entry_point", ""),
            api_version=plugin_data.get("api_version", 1),
            minimum_core=plugin_data.get("minimum_core", "1.0.0"),
            maximum_core=plugin_data.get("maximum_core"),
            dependencies=plugin_data.get("dependencies", []),
            capabilities=capabilities,
        )
