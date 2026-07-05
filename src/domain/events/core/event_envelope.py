"""事件信封 — Domain 层不可变协议

只包含事件自身的三个维度:
  metadata  → 事件是什么 (类型/版本/时间/生产者)
  trace     → 事件从哪来 (分布式追踪)
  payload   → 事件带什么 (业务数据)

不含任何 Transport 属性 (retry/priority/ttl → MessageEnvelope)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from src.domain.events.core.base_payload import BaseEventPayload, EmptyPayload
from src.domain.events.core.event_metadata import EventMetadata
from src.domain.events.core.trace_context import TraceContext
from src.domain.events.core.serializable import Serializable

T = TypeVar("T", bound=BaseEventPayload)


@dataclass(frozen=True)
class EventEnvelope(Generic[T], Serializable):
    """事件信封 — Domain 层不可变协议

    使用:
      event = EventEnvelope[SignalCreatedPayload](
          metadata=EventMetadata(event_type=SignalEventType.SIGNAL_CREATED),
          trace=TraceContext.root(),
          payload=SignalCreatedPayload(stock_code="000725.SZ", score=95),
      )
    """

    metadata: EventMetadata = field(default_factory=EventMetadata)
    trace: TraceContext = field(default_factory=TraceContext)
    payload: T = field(default_factory=lambda: EmptyPayload())  # type: ignore
