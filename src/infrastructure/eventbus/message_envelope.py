"""消息信封 — Infrastructure 层传输包装

EventBus 内部使用。Domain 永远不感知。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from src.domain.events.core.base_payload import BaseEventPayload
from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.serializable import Serializable

T = TypeVar("T", bound=BaseEventPayload)


@dataclass(frozen=True)
class DeliveryMetadata(Serializable):
    """投递元数据 — 仅 Infrastructure 层使用

    Domain 代码永远不 import 此类
    """

    retry_count: int = 0
    max_retries: int = 3
    priority: int = 0
    ttl_seconds: int = 0
    partition_key: str = ""
    delivered_at: str = ""


@dataclass(frozen=True)
class MessageEnvelope(Generic[T], Serializable):
    """消息信封 — Infrastructure 层传输包装

    EventBus 内部使用。Domain 永远不感知。

    使用:
      msg = MessageEnvelope(
          event=event_envelope,
          delivery=DeliveryMetadata(priority=1, ttl_seconds=300),
      )
      await transport.send(msg)
    """

    event: EventEnvelope[T] = field(default_factory=EventEnvelope)  # type: ignore
    delivery: DeliveryMetadata = field(default_factory=DeliveryMetadata)
