"""事件总线端口 — Domain 层接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.event_type import AnyEventType

Handler = Callable[[EventEnvelope], Awaitable[None]]


class EventBusPort(ABC):
    """事件总线端口 — publish 收 EventEnvelope，subscribe 收 EventType 枚举"""

    @abstractmethod
    async def publish(self, event: EventEnvelope) -> None:
        """发布事件 — Bus 内部负责序列化 + 传输"""
        ...

    @abstractmethod
    async def subscribe(self, event_type: AnyEventType, handler: Handler) -> None:
        """订阅事件 — handler 接收 EventEnvelope（不是 dict）"""
        ...

    @abstractmethod
    async def unsubscribe(self, event_type: AnyEventType, handler: Handler) -> None:
        """取消订阅"""
        ...
