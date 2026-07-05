"""事件载荷基类"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.events.core.serializable import Serializable


@dataclass(frozen=True)
class BaseEventPayload(Serializable):
    """事件载荷基类 — 所有 Payload 继承此类

    schema_version: Payload 自身的版本（与 Envelope schema_version 独立）
      例如: SignalCreatedPayload v2 增加了 confidence 字段
            Envelope 协议未变，但 Payload 变了
    """

    schema_version: int = 1

    def validate(self) -> None:
        """子类重写以添加业务校验。Factory 自动调用。"""
        pass


@dataclass(frozen=True)
class EmptyPayload(BaseEventPayload):
    """空载荷 — heartbeat / shutdown"""
    pass
