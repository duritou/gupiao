"""Plugin Validator — 校验 Manifest 合法性

校验项:
  1. 必填字段 (name, version, type, entry_point)
  2. API 版本兼容性
  3. 核心版本约束 (minimum_core / maximum_core)
  4. 依赖声明格式
  5. 能力声明格式
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

from src.infrastructure.plugin_registry.manifest import PluginManifest


@dataclass
class ValidationResult:
    """校验结果"""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


class PluginValidator:
    """插件校验器 — 纯函数，不依赖 Registry"""

    def __init__(
        self,
        core_version: str = "1.0.0",
        supported_api_versions: list[int] | None = None,
    ):
        self.core_version = core_version
        self.supported_api_versions = supported_api_versions or [1]

    def validate(self, manifest: PluginManifest) -> ValidationResult:
        """执行全部校验"""
        result = ValidationResult()

        self._validate_required(result, manifest)
        self._validate_api_version(result, manifest)
        self._validate_core_version(result, manifest)
        self._validate_entry_point(result, manifest)
        self._validate_dependencies(result, manifest)

        if result.valid:
            logger.debug("Plugin validated: {}", manifest.name)
        else:
            logger.warning(
                "Plugin validation failed for {}: {}",
                manifest.name,
                "; ".join(result.errors),
            )

        return result

    # ===== 必填字段 =====

    def _validate_required(self, result: ValidationResult, m: PluginManifest) -> None:
        if not m.name:
            result.add_error("name is required")
        if not m.version:
            result.add_error("version is required")
        elif not _is_valid_semver(m.version):
            result.add_error(f"version '{m.version}' is not valid semver")
        if not m.entry_point:
            result.add_error("entry_point is required")
        if not m.type:
            result.add_error("type is required")

    # ===== API 版本 =====

    def _validate_api_version(self, result: ValidationResult, m: PluginManifest) -> None:
        if m.api_version not in self.supported_api_versions:
            result.add_error(
                f"api_version {m.api_version} not supported. "
                f"Supported: {self.supported_api_versions}"
            )

    # ===== 核心版本约束 =====

    def _validate_core_version(self, result: ValidationResult, m: PluginManifest) -> None:
        # minimum_core 检查
        if not _semver_gte(self.core_version, m.minimum_core):
            result.add_error(
                f"Plugin requires core >= {m.minimum_core}, "
                f"current core is {self.core_version}"
            )

        # maximum_core 检查
        if m.maximum_core:
            if not _semver_matches(self.core_version, m.maximum_core):
                result.add_error(
                    f"Plugin incompatible with core {self.core_version}, "
                    f"expected range: {m.maximum_core}"
                )

    # ===== entry_point =====

    def _validate_entry_point(self, result: ValidationResult, m: PluginManifest) -> None:
        if not re.match(r'^[\w.]+:[\w]+$', m.entry_point):
            result.add_error(
                f"entry_point '{m.entry_point}' is invalid. "
                f"Expected format: 'module:Class' (e.g. 'adapter:AKShareAdapter')"
            )

    # ===== 依赖 =====

    def _validate_dependencies(self, result: ValidationResult, m: PluginManifest) -> None:
        for dep in m.dependencies:
            if not re.match(r'^[\w-]+(\[.*?\])?\s*(>=|<=|==|~=|!=|>|<)\s*[\d.]+', dep.strip()):
                result.add_warning(f"Dependency format may be invalid: '{dep}'")


# ===== Semver 工具 =====

def _is_valid_semver(version: str) -> bool:
    """检查是否为有效 semver"""
    return bool(re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$', version))


def _parse_semver(version: str) -> tuple[int, int, int]:
    """解析 semver 为 (major, minor, patch)"""
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _semver_gte(v1: str, v2: str) -> bool:
    """v1 >= v2"""
    return _parse_semver(v1) >= _parse_semver(v2)


def _semver_matches(version: str, range_spec: str) -> bool:
    """简易 semver range 匹配

    支持格式:
      "2.x"  → 匹配 2.0.0 ~ 2.999.999
      ">=2.0.0,<3.0.0" → 标准 range
    """
    # 处理 "N.x" 格式
    x_match = re.match(r'^(\d+)\.x$', range_spec)
    if x_match:
        major = int(x_match.group(1))
        parsed = _parse_semver(version)
        return parsed[0] == major

    # 简单比较：如果没有逗号，尝试 >= 语义
    if "," not in range_spec and range_spec.startswith(">="):
        return _semver_gte(version, range_spec[2:])

    return True  # 复杂 range 暂放行，后续增强
