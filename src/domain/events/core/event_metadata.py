"""事件元数据 — 只描述事件自身属性，不含 delivery 属性"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.events.core.event_type import AnyEventType, SystemEventType
from src.domain.events.core.serializable import Serializable


@dataclass(frozen=True)
class EventMetadata(Serializable):
    """事件元数据 — 事件自身属性

    不含 delivery 属性 (retry/priority/ttl → MessageEnvelope.delivery)
    """

    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: AnyEventType = SystemEventType.HEARTBEAT
    schema_version: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str = ""
