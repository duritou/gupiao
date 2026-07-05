"""Prompt Registry — 版本化 Prompt 管理

Prompt 生命周期:
  draft → active → deprecated

支持:
  - 版本化 (v1/v2/...)
  - 热切换 (activate)
  - 回滚 (rollback)
  - 模板渲染
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Prompt:
    """Prompt 模板"""

    name: str
    version: str
    template: str
    system_prompt: str = ""
    is_active: bool = False
    metadata: dict = field(default_factory=dict)


class PromptRegistry:
    """Prompt 注册表"""

    def __init__(self):
        self._prompts: dict[str, dict[str, Prompt]] = {}   # name → version → Prompt
        self._active: dict[str, str] = {}                   # name → active_version

    # ===== 注册 =====

    def register(self, prompt: Prompt) -> None:
        """注册 Prompt 版本"""
        if prompt.name not in self._prompts:
            self._prompts[prompt.name] = {}
        self._prompts[prompt.name][prompt.version] = prompt

        # 如果是第一个版本或标记为 active，设为激活
        if prompt.is_active or prompt.name not in self._active:
            self._active[prompt.name] = prompt.version
            prompt.is_active = True

    # ===== 获取 =====

    def get(self, name: str, version: str | None = None) -> Optional[Prompt]:
        """获取 Prompt"""
        versions = self._prompts.get(name, {})
        if version:
            return versions.get(version)
        active_ver = self._active.get(name)
        if active_ver:
            return versions.get(active_ver)
        return None

    def get_active(self, name: str) -> Optional[Prompt]:
        """获取当前激活版本"""
        return self.get(name)

    # ===== 生命周期 =====

    def activate(self, name: str, version: str) -> bool:
        """激活指定版本"""
        versions = self._prompts.get(name, {})
        if version not in versions:
            return False

        # 旧版本取消激活
        old_ver = self._active.get(name)
        if old_ver and old_ver in versions:
            versions[old_ver].is_active = False

        # 新版本激活
        versions[version].is_active = True
        self._active[name] = version
        return True

    def rollback(self, name: str) -> Optional[str]:
        """回滚到上一个版本"""
        versions = self._prompts.get(name, {})
        if len(versions) < 2:
            return None

        sorted_versions = sorted(versions.keys(), reverse=True)
        current = self._active.get(name)
        if current and current in sorted_versions:
            idx = sorted_versions.index(current)
            if idx + 1 < len(sorted_versions):
                prev = sorted_versions[idx + 1]
                self.activate(name, prev)
                return prev
        return None

    # ===== 查询 =====

    def list_versions(self, name: str) -> list[str]:
        return sorted(self._prompts.get(name, {}).keys())

    def list_all(self) -> list[str]:
        return list(self._prompts.keys())

    # ===== 渲染 =====

    def render(self, name: str, context: dict, version: str | None = None) -> str:
        """渲染 Prompt 模板 — 简易变量替换"""
        prompt = self.get(name, version)
        if not prompt:
            return ""

        result = prompt.template
        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
