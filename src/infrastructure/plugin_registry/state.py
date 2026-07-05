"""Plugin State — 生命周期状态机

状态转移:
  DISCOVERED → VALIDATED → LOADED → INITIALIZED → ACTIVE
                ├── FAILED
  ACTIVE → DISABLED → ACTIVE (重新启用)
  ACTIVE → FAILED
  Any → STOPPED (shutdown)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto


class PluginState(Enum):
    """插件状态"""
    DISCOVERED = auto()     # 已发现 (plugin.yaml 存在)
    VALIDATED = auto()      # 校验通过
    LOADED = auto()         # Python 模块已加载
    INITIALIZED = auto()    # initialize() 调用成功
    ACTIVE = auto()         # 正常运行
    DISABLED = auto()       # 已禁用
    FAILED = auto()         # 失败 (记录错误)
    STOPPED = auto()        # 已停止 (shutdown)


# 合法状态转移
VALID_TRANSITIONS: dict[PluginState, set[PluginState]] = {
    PluginState.DISCOVERED:  {PluginState.VALIDATED, PluginState.FAILED},
    PluginState.VALIDATED:   {PluginState.LOADED, PluginState.FAILED},
    PluginState.LOADED:      {PluginState.INITIALIZED, PluginState.FAILED, PluginState.STOPPED},
    PluginState.INITIALIZED: {PluginState.ACTIVE, PluginState.FAILED, PluginState.STOPPED},
    PluginState.ACTIVE:      {PluginState.DISABLED, PluginState.FAILED, PluginState.STOPPED},
    PluginState.DISABLED:    {PluginState.ACTIVE, PluginState.STOPPED},
    PluginState.FAILED:      {PluginState.DISCOVERED, PluginState.STOPPED},
    PluginState.STOPPED:     set(),
}


@dataclass
class PluginStateInfo:
    """插件运行时状态信息"""

    state: PluginState = PluginState.DISCOVERED
    state_history: list[tuple[PluginState, str]] = field(default_factory=list)
    error_message: str = ""
    loaded_at: datetime | None = None
    initialized_at: datetime | None = None
    health_last_check: datetime | None = None
    health_status: bool = False

    def transition(self, new_state: PluginState) -> None:
        """执行状态转移 — 非法转移抛 ValueError"""
        if new_state not in VALID_TRANSITIONS.get(self.state, set()):
            raise InvalidStateTransitionError(
                f"Cannot transition from {self.state.name} to {new_state.name}"
            )
        self.state_history.append((self.state, ""))
        self.state = new_state

    def transition_to_failed(self, error_message: str) -> None:
        """转移到 FAILED 状态并记录错误"""
        self.error_message = error_message
        self.state_history.append((self.state, error_message))
        self.state = PluginState.FAILED


class InvalidStateTransitionError(Exception):
    """非法状态转移"""
    pass
