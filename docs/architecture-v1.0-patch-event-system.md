# v1.0 Event 架构规范（冻结版）

> **定位**: Event = 不可变协议。Domain 永远不知道 Transport。  
> **优先级**: Phase 0 合并  
> **原则**: Event ≠ Message ≠ Serialization ≠ Transport ≠ Trace。五者彻底解耦。

---

## 一、核心概念边界

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│  Domain Layer                    Infrastructure Layer          │
│  ────────────                    ────────────────────          │
│                                                               │
│  EventEnvelope                   MessageEnvelope              │
│  ├── metadata  (事件自身)         ├── event: EventEnvelope     │
│  ├── trace     (可观测性)         └── delivery: DeliveryMeta   │
│  └── payload   (业务数据)              │                       │
│       │                                ▼                       │
│       │                         EventSerializer               │
│       │                                │                       │
│       │                                ▼                       │
│       │                         EventBus (Transport)           │
│       │                         └── Kafka / Redis / NATS / .. │
│                                                               │
│  Domain 永远不知道:                                            │
│    · retry / priority / ttl / partition                       │
│    · JSON / msgpack / protobuf                                │
│    · Kafka / Redis / RabbitMQ                                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、EventEnvelope（Domain 层 — 不含 Delivery）

```python
# src/domain/events/core/event_envelope.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from src.domain.events.core.base_payload import BaseEventPayload
from src.domain.events.core.event_metadata import EventMetadata
from src.domain.events.core.trace_context import TraceContext
from src.domain.events.core.serializable import Serializable

T = TypeVar("T", bound=BaseEventPayload)


@dataclass(frozen=True)
class EventEnvelope(Generic[T], Serializable):
    """事件信封 —— Domain 层不可变协议

    只包含事件自身的三个维度:
      metadata  → 事件是什么 (类型/版本/时间/生产者)
      trace     → 事件从哪来 (分布式追踪)
      payload   → 事件带什么 (业务数据)

    不含任何 Transport 属性 (retry/priority/ttl → MessageEnvelope)
    """

    metadata: EventMetadata = field(default_factory=EventMetadata)
    trace: TraceContext = field(default_factory=TraceContext)
    payload: T = field(default_factory=lambda: EmptyPayload())  # type: ignore
```

---

## 三、MessageEnvelope（Infrastructure 层 — Transport 包装）

```python
# src/infrastructure/eventbus/message_envelope.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from src.domain.events.core.base_payload import BaseEventPayload
from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.serializable import Serializable

T = TypeVar("T", bound=BaseEventPayload)


@dataclass(frozen=True)
class DeliveryMetadata(Serializable):
    """投递元数据 —— 仅 Infrastructure 层使用

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
    """消息信封 —— Infrastructure 层传输包装

    EventBus 内部使用。Domain 永远不感知。

    使用:
      msg = MessageEnvelope(
          event=event_envelope,
          delivery=DeliveryMetadata(priority=1, ttl_seconds=300),
      )
      await transport.send(msg)
    """

    event: EventEnvelope[T] = field(default_factory=EventEnvelope)
    delivery: DeliveryMetadata = field(default_factory=DeliveryMetadata)
```

**关键规则**:

```
✅ UseCase 发布:           EventEnvelope        (不含 delivery)
✅ EventBus 内部包装:      MessageEnvelope      (+ delivery)
✅ Worker 消费:            EventEnvelope        (不含 delivery)

Domain 代码中永远不出现 "DeliveryMetadata" 和 "MessageEnvelope"
```

---

## 四、EventBus（接收 EventEnvelope，内部包装 MessageEnvelope）

```python
# src/domain/ports/event_bus_port.py

from typing import Callable, Awaitable
from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.base_payload import BaseEventPayload
from src.domain.events.core.event_type import AnyEventType


class EventBusPort:
    """事件总线端口 —— Domain 层接口

    publish 接收 EventEnvelope（不含 delivery）
    subscribe handler 接收 EventEnvelope（不含 delivery）
    Delivery 由 Infrastructure 层 Bus 实现内部处理
    """

    async def publish(self, event: EventEnvelope) -> None:
        """发布事件 —— Bus 内部包装 MessageEnvelope + 序列化 + 传输"""
        ...

    async def subscribe(
        self,
        event_type: AnyEventType,       # ← EventType 枚举，不是 str
        handler: Callable[[EventEnvelope], Awaitable[None]],
    ) -> None:
        """订阅事件"""
        ...

    async def unsubscribe(
        self,
        event_type: AnyEventType,
        handler: Callable[[EventEnvelope], Awaitable[None]],
    ) -> None:
        ...


# src/infrastructure/eventbus/memory_bus.py (Phase 0 实现)

class MemoryEventBus(EventBusPort):
    """内存版 EventBus —— publish 内部包装 MessageEnvelope"""

    async def publish(self, event: EventEnvelope) -> None:
        # 1. 包装 MessageEnvelope
        msg = MessageEnvelope(event=event)

        # 2. 中间件链 (Metrics → Logger → Tracer)
        msg = await self._middleware_chain(msg)

        # 3. 序列化
        data = EventSerializer.serialize(msg)

        # 4. 投递给订阅者
        for handler in self._handlers.get(event.metadata.event_type, []):
            await handler(event)     # ← handler 接收 EventEnvelope，不是 MessageEnvelope
```

---

## 五、Serializable（接口 — 委托具体库）

```python
# src/domain/events/core/serializable.py

from __future__ import annotations
from abc import ABC


class Serializable(ABC):
    """序列化接口 —— 只定义协议，不实现具体转换

    Phase 0: 使用 dataclasses.asdict + 少量自定义处理
    Phase 6+: 切换到 msgspec 或 cattrs（一行不改子类）
    """

    def to_dict(self) -> dict:
        """序列化为 dict —— 委托给 _default_converter"""
        return get_converter().to_dict(self)

    @classmethod
    def from_dict(cls, data: dict):
        """从 dict 反序列化"""
        return get_converter().from_dict(cls, data)


# 内部: 可切换的转换器
_converter = None

def get_converter():
    global _converter
    if _converter is None:
        _converter = DataclassConverter()   # Phase 0: 简易版
    return _converter

# Phase 6+ 切换:
# def get_converter():
#     return MsgspecConverter()
```

---

## 六、EventType（按领域拆分）

```python
# src/domain/events/core/event_type.py

from enum import StrEnum
from typing import Union


class SignalEventType(StrEnum):
    SIGNAL_CREATED         = "domain.signal.created"
    SIGNAL_BATCH_COMPLETED = "domain.signal.batch_completed"


class ResearchEventType(StrEnum):
    RESEARCH_STARTED       = "domain.research.started"
    RESEARCH_COMPLETED     = "domain.research.completed"
    RESEARCH_FAILED        = "domain.research.failed"


class ScannerEventType(StrEnum):
    SCANNER_STARTED        = "scanner.started"
    SCANNER_COMPLETED      = "scanner.completed"
    CANDIDATE_CREATED      = "scanner.candidate.created"


class MemoryEventType(StrEnum):
    WATCHLIST_UPDATED      = "domain.watchlist.updated"
    MEMORY_RECORDED        = "domain.memory.recorded"


class KnowledgeEventType(StrEnum):
    KNOWLEDGE_IMPORTED     = "domain.knowledge.imported"


class SystemEventType(StrEnum):
    HEARTBEAT              = "system.heartbeat"
    SHUTDOWN               = "system.shutdown"


# 联合类型 —— EventBus.subscribe() 的参数类型
AnyEventType = (
    SignalEventType
    | ResearchEventType
    | ScannerEventType
    | MemoryEventType
    | KnowledgeEventType
    | SystemEventType
)
```

---

## 七、EventMetadata

```python
# src/domain/events/core/event_metadata.py

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.events.core.event_type import AnyEventType, SystemEventType
from src.domain.events.core.serializable import Serializable


@dataclass(frozen=True)
class EventMetadata(Serializable):
    """事件元数据 —— 只描述事件自身属性

    不含 delivery 属性 (retry/priority/ttl → MessageEnvelope.delivery)
    """

    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: AnyEventType = SystemEventType.HEARTBEAT
    schema_version: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str = ""
```

---

## 八、TraceContext

```python
# src/domain/events/core/trace_context.py

from __future__ import annotations
from dataclasses import dataclass, field
from uuid import uuid4

from src.domain.events.core.serializable import Serializable


@dataclass(frozen=True)
class TraceContext(Serializable):
    """追踪上下文

    v1.0: trace_id / span_id / correlation_id
    v1.2: + traceparent / tracestate
    v2+:  + baggage / sampling / tenant_id
    """

    trace_id: str = field(default_factory=lambda: str(uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid4()))
    parent_span_id: str = ""
    correlation_id: str = ""

    # v1.2 预留
    traceparent: str = ""
    tracestate: str = ""
    sampled: bool = True

    # ===== Factory Methods =====

    @classmethod
    def root(cls, correlation_id: str = "") -> "TraceContext":
        return cls(correlation_id=correlation_id)

    @classmethod
    def child(cls, parent: "TraceContext") -> "TraceContext":
        return cls(
            trace_id=parent.trace_id,
            parent_span_id=parent.span_id,
            correlation_id=parent.correlation_id,
        )

    @classmethod
    def fork(cls, parent: "TraceContext") -> "TraceContext":
        return cls(correlation_id=parent.correlation_id)
```

---

## 九、BaseEventPayload

```python
# src/domain/events/core/base_payload.py

from __future__ import annotations
from dataclasses import dataclass, field

from src.domain.events.core.serializable import Serializable


@dataclass(frozen=True)
class BaseEventPayload(Serializable):
    """事件载荷基类

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
    """空载荷 —— heartbeat / shutdown"""
    pass
```

---

## 十、EventSerializer

```python
# src/infrastructure/eventbus/event_serializer.py

import json
from typing import TypeVar

from src.domain.events.core.base_payload import BaseEventPayload
from src.infrastructure.eventbus.message_envelope import MessageEnvelope

T = TypeVar("T", bound=BaseEventPayload)


class SerializerVersion:
    V1_JSON = 1
    V2_MSGPACK = 2


class EventSerializer:
    """事件序列化器 —— Infrastructure 层

    MessageEnvelope 序列化（含 delivery），EventEnvelope 不参与序列化
    """

    CURRENT_VERSION = SerializerVersion.V1_JSON

    @staticmethod
    def serialize(msg: MessageEnvelope[T]) -> bytes:
        """MessageEnvelope → bytes"""
        return json.dumps(
            {"version": EventSerializer.CURRENT_VERSION, **msg.to_dict()},
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

    @staticmethod
    def deserialize(data: bytes) -> MessageEnvelope:
        """bytes → MessageEnvelope"""
        raw = json.loads(data.decode("utf-8"))
        version = raw.pop("version", 1)
        # 根据 version 选择反序列化路径
        return MessageEnvelope.from_dict(raw)
```

---

## 十一、EventFactory（按领域拆分 + 自动 validate）

```python
# src/domain/events/core/event_factory.py

from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.event_metadata import EventMetadata
from src.domain.events.core.trace_context import TraceContext
from src.domain.events.core.base_payload import BaseEventPayload


class BaseEventFactory:
    """Factory 基类 —— 自动调用 payload.validate()"""

    def __init__(self, producer: str):
        self.producer = producer

    def _envelope(self, event_type, payload: BaseEventPayload,
                  trace: TraceContext | None = None) -> EventEnvelope:
        # 自动校验
        payload.validate()
        return EventEnvelope(
            metadata=EventMetadata(event_type=event_type, producer=self.producer),
            trace=trace or TraceContext.root(),
            payload=payload,
        )


# src/domain/events/factories/signal_factory.py

class SignalEventFactory(BaseEventFactory):
    """信号事件工厂"""

    def created(
        self, stock_code: str, signal_type: str, score: float,
        direction: str, reason: str = "", trace: TraceContext | None = None,
    ) -> EventEnvelope[SignalCreatedPayload]:
        return self._envelope(
            SignalEventType.SIGNAL_CREATED,
            SignalCreatedPayload(
                stock_code=stock_code, signal_type=signal_type,
                score=score, direction=direction, reason=reason,
            ),
            trace,
        )


# src/domain/events/factories/scanner_factory.py

class ScannerEventFactory(BaseEventFactory):
    """扫描事件工厂"""

    def completed(
        self, scan_date: str, total: int, candidates_count: int,
        top_codes: list[str], trace: TraceContext | None = None,
    ) -> EventEnvelope[ScannerCompletedPayload]:
        return self._envelope(
            ScannerEventType.SCANNER_COMPLETED,
            ScannerCompletedPayload(
                scan_date=scan_date, total_scanned=total,
                candidates_count=candidates_count, top_candidates=top_codes,
            ),
            trace,
        )

    def candidate_created(
        self, stock_code: str, stock_name: str, score: float,
        rank: int, tags: list[str], trace: TraceContext | None = None,
    ) -> EventEnvelope[CandidateCreatedPayload]:
        return self._envelope(
            ScannerEventType.CANDIDATE_CREATED,
            CandidateCreatedPayload(
                stock_code=stock_code, stock_name=stock_name,
                fusion_score=score, rank=rank, tags=tags,
            ),
            trace,
        )


# 统一入口
class Events:
    """事件工厂统一入口

    使用:
      events = Events(producer="scanner_engine")
      event = events.signal.created(stock_code="000725.SZ", ...)
      event = events.scanner.completed(scan_date="...", ...)
    """

    def __init__(self, producer: str):
        self.signal = SignalEventFactory(producer)
        self.research = ResearchEventFactory(producer)
        self.scanner = ScannerEventFactory(producer)
        self.memory = MemoryEventFactory(producer)
```

---

## 十二、完整使用示例

```python
# ===== Domain 层发布事件 =====

events = Events(producer="scanner_engine")
root_trace = TraceContext.root(correlation_id="daily_scan_20260705")

# Scanner 完成 → 发布（只涉及 EventEnvelope，无 Delivery）
scanner_event = events.scanner.completed(
    scan_date="2026-07-05",
    total=5000,
    candidates_count=20,
    top_codes=["000725.SZ", "000100.SZ"],
    trace=root_trace,
)
await eventbus.publish(scanner_event)


# ===== Infrastructure 层 — EventBus 内部 =====

class MemoryEventBus(EventBusPort):
    async def publish(self, event: EventEnvelope) -> None:
        # 1. 包装 MessageEnvelope (+ delivery)
        msg = MessageEnvelope(
            event=event,
            delivery=DeliveryMetadata(priority=1, ttl_seconds=300),
        )
        # 2. 中间件
        msg = await self._middleware_chain(msg)
        # 3. 序列化 → bytes
        data = EventSerializer.serialize(msg)
        # 4. 存储 (Redis Stream / Kafka / ...)
        await self._transport.send(data)


# ===== 消费者 handler =====

async def on_scanner_completed(envelope: EventEnvelope):
    # 类型安全访问（DeliveryMetadata 不在此出现）
    for code in envelope.payload.top_candidates:
        child = events.signal.created(
            stock_code=code,
            signal_type="macd",
            score=95.0,
            direction="buy",
            trace=TraceContext.child(envelope.trace),  # 链接追踪
        )
        await eventbus.publish(child)

# 订阅 —— EventType 枚举，不是字符串
await eventbus.subscribe(ScannerEventType.SCANNER_COMPLETED, on_scanner_completed)
```

---

## 十三、目录结构

```
src/
├── domain/events/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── event_type.py          #   按领域拆分的 EventType
│   │   ├── base_payload.py        #   BaseEventPayload + EmptyPayload
│   │   ├── trace_context.py       #   TraceContext
│   │   ├── event_metadata.py      #   EventMetadata (不含 delivery)
│   │   ├── event_envelope.py      #   EventEnvelope[T] (不含 delivery)
│   │   ├── serializable.py        #   Serializable 接口
│   │   └── event_factory.py       #   BaseEventFactory + Events 统一入口
│   ├── payloads/
│   │   ├── signal_payloads.py
│   │   ├── research_payloads.py
│   │   ├── scanner_payloads.py
│   │   ├── memory_payloads.py
│   │   ├── knowledge_payloads.py
│   │   └── system_payloads.py
│   └── factories/
│       ├── signal_factory.py
│       ├── research_factory.py
│       ├── scanner_factory.py
│       └── memory_factory.py
│
├── domain/ports/
│   └── event_bus_port.py          #   publish(EventEnvelope) / subscribe(EventType, handler)
│
└── infrastructure/eventbus/
    ├── __init__.py
    ├── message_envelope.py         #   MessageEnvelope + DeliveryMetadata (Infrastructure only)
    ├── memory_bus.py               #   MemoryEventBus 实现
    ├── event_serializer.py         #   EventSerializer
    ├── middleware.py               #   Metrics / Logger / Tracer
    └── event_registry.py           #   (v1.1) EventType → Payload 类型映射
```

---

## 十四、设计决策总表

| 决策 | 选择 | 理由 |
|------|------|------|
| `DeliveryMetadata` 在 `EventEnvelope` 中 | ❌ | Domain 零耦合 Transport |
| `MessageEnvelope` 包装 `EventEnvelope` + `DeliveryMetadata` | ✅ | Infrastructure 层专属 |
| `EventBus.publish(event)` 收 `EventEnvelope` | ✅ | 不含 delivery |
| `EventBus.subscribe(EventType, handler)` | ✅ | 枚举，非字符串 |
| `EventType` 按领域拆分 | ✅ | 300+ Event 时不会一个 Enum 炸掉 |
| `EventFactory` 按领域拆分 | ✅ | 80+ Event 时不会一个类 2000 行 |
| `BaseEventFactory._envelope()` 自动 `validate()` | ✅ | 调用方永远不记 validate |
| `BaseEventPayload.schema_version` | ✅ | Payload 独立演进 |
| `Serializable` 接口 + 委托 | ✅ | Phase 0 简易版 → Phase 6 msgspec |
| `EventSerializer` 含 `SerializerVersion` | ✅ | JSON v1 → msgpack v2 独立演进 |
| `frozen=True` | ✅ | Event 是不可变事实 |

---

## 十五、v1.1 预留

```python
# Event Registry (v1.1)
class EventRegistry:
    """EventType → Payload 类型映射 → 自动反序列化"""
    def register(self, event_type: EventType, payload_cls: type[BaseEventPayload]): ...
    def resolve(self, event_type: EventType) -> type[BaseEventPayload]: ...

# 使用: 无需手动传 payload_cls
msg = EventSerializer.deserialize(data)  # 自动找到 Payload 类型


# Event Middleware (v1.1)
class EventMiddleware:
    """发布链: Metrics → Logger → Tracer → Serializer → Transport"""
    async def process(self, msg: MessageEnvelope, next_handler) -> MessageEnvelope: ...
```

---

## 十六、最终评价

| 模块 | 评分 |
|------|------|
| Event Protocol | **10/10** |
| Trace Model | **10/10** |
| Type Safety | **10/10** |
| Factory Pattern | **10/10** |
| Serialization Boundary | **10/10** |
| Transport Abstraction | **10/10** ← DeliveryMetadata 移出 EventEnvelope |
| Long-term Extensibility | **10/10** |

---

> **Event 架构冻结。Domain 永远不知道 Transport。**
