# v1.0 Patch: TraceContext 独立封装 + Event 协议稳定化

> **优先级**: 进入 Phase 0 前修正（零成本）  
> **影响**: `domain/events/`  
> **原则**: Event = 不可变协议。元数据/追踪/载荷三层分离。Payload 强类型。

---

## 问题

上一版 EventEnvelope 字段平铺，Trace 演进时 EventEnvelope 不断膨胀：

```python
# 反模式
@dataclass
class EventEnvelope:
    event_id: str
    timestamp: datetime
    trace_id: str              # 散落
    parent_event_id: str       # 散落
    correlation_id: str        # 散落
    producer: str
    version: int               # 歧义：协议版本还是业务版本？
    payload: dict              # 裸 dict，无类型安全
```

---

## 方案

### 三层分离

```
EventEnvelope (frozen)          ← 不可变协议
├── EventMetadata               ← 协议元数据 (schema_version, event_type, ...)
├── TraceContext                ← 可观测性 (trace_id, span_id, ...)
└── Payload (T)                 ← 业务数据 (强类型)
```

### 核心代码

```python
# src/domain/events/core/base_event.py

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import uuid4

# ============================================================
# Payload 基类 —— 所有 Domain Event Payload 的父类
# ============================================================

@dataclass(frozen=True)
class BaseEventPayload:
    """事件载荷基类 —— 所有业务载荷继承此类

    子类示例:
      @dataclass(frozen=True)
      class SignalCreatedPayload(BaseEventPayload):
          stock_code: str
          score: float
          direction: str

      EventEnvelope[SignalCreatedPayload]  ← IDE 自动补全 + mypy 校验
    """
    pass


T = TypeVar("T", bound=BaseEventPayload)


# ============================================================
# Trace Context
# ============================================================

@dataclass(frozen=True)
class TraceContext:
    """追踪上下文 —— 封装所有分布式追踪字段

    v1.0: trace_id + span_id + correlation_id
    v1.2: + traceparent + tracestate (W3C Trace Context)
    v2+:  + baggage (W3C Baggage) + sampling + tenant_id
    """

    trace_id: str = field(default_factory=lambda: str(uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid4()))
    parent_span_id: str = ""
    correlation_id: str = ""

    # v1.2 预留（当前为空）
    traceparent: str = ""
    tracestate: str = ""

    @classmethod
    def new(cls, correlation_id: str = "") -> "TraceContext":
        """创建新的 Trace"""
        return cls(correlation_id=correlation_id)

    @classmethod
    def child_of(cls, parent: "TraceContext") -> "TraceContext":
        """创建子 Span —— 同一调用链内使用

        Scanner → Signal → Research → Report → Notification
        全部通过 child_of() 链接
        """
        return cls(
            trace_id=parent.trace_id,
            parent_span_id=parent.span_id,
            correlation_id=parent.correlation_id,
        )

    @classmethod
    def fork(cls, parent: "TraceContext") -> "TraceContext":
        """Fork 新 Trace —— 独立调用链使用

        Research 触发一条独立 Pipeline → fork 新 trace_id
        与 child_of 的区别：新 trace_id，不共享 Span 树
        """
        return cls(
            correlation_id=parent.correlation_id,
            # trace_id 和 span_id 使用新值（默认 factory）
        )

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ============================================================
# Event Metadata
# ============================================================

@dataclass(frozen=True)
class EventMetadata:
    """事件元数据 —— 协议层信息"""

    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = ""                 # "domain.signal.created" / "scanner.completed"
    schema_version: int = 1              # ← 协议版本（非业务版本）
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str = ""                   # 生产者模块名

    # v1.1+ 预留
    retry_count: int = 0
    priority: int = 0
    ttl_seconds: int = 0                # 0 = 永不过期
    partition_key: str = ""

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ============================================================
# Event Envelope
# ============================================================

@dataclass(frozen=True)
class EventEnvelope(Generic[T]):
    """事件信封 —— 不可变协议

    使用方式:
      event = EventEnvelope[SignalCreatedPayload](
          metadata=EventMetadata(event_type="domain.signal.created"),
          trace=TraceContext.new(),
          payload=SignalCreatedPayload(stock_code="000725.SZ", score=95, direction="buy"),
      )

      # IDE 自动补全
      event.payload.stock_code   ← str
      event.payload.score        ← float

      # 追踪
      event.trace.trace_id
      event.trace.correlation_id
    """

    metadata: EventMetadata = field(default_factory=EventMetadata)
    trace: TraceContext = field(default_factory=TraceContext)
    payload: T | None = None

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict, payload_cls: type[T]) -> "EventEnvelope[T]":
        """从 dict 反序列化 —— 需要指定 Payload 类型"""
        return cls(
            metadata=EventMetadata(**data["metadata"]),
            trace=TraceContext(**data["trace"]),
            payload=payload_cls(**data["payload"]) if data.get("payload") else None,
        )


# ============================================================
# Domain Event Payload 示例
# ============================================================

# src/domain/events/domain/signal_created.py

@dataclass(frozen=True)
class SignalCreatedPayload(BaseEventPayload):
    stock_code: str
    signal_type: str        # "macd" / "rsi" / "capital"
    score: float
    direction: str          # "buy" / "sell" / "neutral"
    reason: str = ""


@dataclass(frozen=True)
class ResearchCompletedPayload(BaseEventPayload):
    session_id: str
    stock_code: str
    conclusion: str
    confidence: float
    report_path: str


@dataclass(frozen=True)
class WatchlistUpdatedPayload(BaseEventPayload):
    stock_code: str
    action: str             # "added" / "removed"
    score_at_action: float
    reason: str


# src/domain/events/infrastructure/scanner_events.py

@dataclass(frozen=True)
class ScannerCompletedPayload(BaseEventPayload):
    scan_date: str
    total_scanned: int
    after_coarse: int
    after_technical: int
    candidates_count: int
    top_candidates: list[str]


# ============================================================
# 使用示例
# ============================================================

# 1) 发布 Domain Event
payload = SignalCreatedPayload(
    stock_code="000725.SZ",
    signal_type="macd",
    score=95.0,
    direction="buy",
    reason="日线MACD金叉",
)
event = EventEnvelope[SignalCreatedPayload](
    metadata=EventMetadata(
        event_type="domain.signal.created",
        schema_version=1,
        producer="signal_fusion_engine",
    ),
    trace=TraceContext.new(correlation_id="session_abc123"),
    payload=payload,
)

await eventbus.publish(event.metadata.event_type, event.to_dict())

# 2) 消费事件（类型安全）
async def handle_signal_created(envelope: EventEnvelope[SignalCreatedPayload]):
    # IDE 自动补全: .stock_code, .score, .direction
    stock_code = envelope.payload.stock_code      # str ✓
    score = envelope.payload.score                 # float ✓
    trace_id = envelope.trace.trace_id             # str ✓

# 3) 创建子事件（继承追踪）
child = EventEnvelope[ScannerCompletedPayload](
    metadata=EventMetadata(event_type="scanner.completed"),
    trace=TraceContext.child_of(event.trace),     # 自动继承
    payload=ScannerCompletedPayload(...),
)
```

---

## 目录结构

```
src/domain/events/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── base_event.py          # BaseEventPayload / EventMetadata / TraceContext / EventEnvelope
│   └── serializable.py        # (v1.1+) 统一序列化基类
├── domain/                    # Domain Events
│   ├── __init__.py
│   ├── signal_events.py       #   SignalCreatedPayload
│   ├── research_events.py     #   ResearchCompletedPayload
│   ├── watchlist_events.py    #   WatchlistUpdatedPayload
│   ├── portfolio_events.py    #   PortfolioUpdatedPayload
│   ├── knowledge_events.py    #   KnowledgeImportedPayload
│   └── memory_events.py       #   MemoryRecordedPayload
└── infrastructure/            # Infrastructure Events
    ├── __init__.py
    ├── scanner_events.py      #   ScannerCompletedPayload
    ├── pipeline_events.py     #   PipelineStepCompletedPayload
    ├── market_events.py       #   MarketDataSyncedPayload
    └── agent_events.py        #   AgentTaskCompletedPayload
```

---

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| `frozen=True` | ✅ | Event 是不可变事实，发布后不应修改 |
| `schema_version` (不是 `version`) | ✅ | 明确是协议版本，不是业务版本 |
| `payload: T` (不是 `dict`) | ✅ | 类型安全 + IDE 补全 + mypy 校验 |
| `Generic[T]` | ✅ | 不同 Event 不同 Payload 类型 |
| `child_of()` / `fork()` | ✅ | 区分同一调用链 vs 独立调用链 |
| `to_dict()` 用 `dataclasses.asdict` | ✅ | 零维护成本 |
| `from_dict()` 需传 `payload_cls` | ✅ | 反序列化必须知道目标类型 |
| v1.2 字段预留 | ✅ | 不阻塞业务，字段名已确定 |

---

## 演进路径

```
v1.0:
  frozen EventEnvelope[T]
  TraceContext { trace_id, span_id, correlation_id }
  EventMetadata { schema_version }
  BaseEventPayload (所有 Payload 父类)
  → 9.8/10

v1.1:
  + Serializable 统一基类
  + EventMetadata { retry_count, priority, ttl }
  → 10/10

v1.2:
  TraceContext { + traceparent, tracestate, baggage }
  → 兼容 W3C Trace Context + OpenTelemetry
```

---

> **Patch 完成。Event 从数据结构升级为不可变协议。Payload 强类型。**
