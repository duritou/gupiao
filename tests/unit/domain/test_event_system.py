"""Event 系统核心单元测试 — TraceContext / EventMetadata / EventEnvelope"""

import pytest
from dataclasses import dataclass

from src.domain.events.core.trace_context import TraceContext
from src.domain.events.core.event_metadata import EventMetadata
from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.base_payload import BaseEventPayload, EmptyPayload
from src.domain.events.core.event_type import (
    SignalEventType,
    ScannerEventType,
    SystemEventType,
)


# ===== Test Payload =====

@dataclass(frozen=True)
class TestSignalPayload(BaseEventPayload):
    stock_code: str = ""
    score: float = 0.0
    direction: str = "buy"


class TestTraceContext:
    """TraceContext 单元测试"""

    def test_root_creates_new_trace(self):
        root = TraceContext.root(correlation_id="test_001")
        assert root.trace_id != ""
        assert root.span_id != ""
        assert root.parent_span_id == ""
        assert root.correlation_id == "test_001"

    def test_child_inherits_trace_id(self):
        root = TraceContext.root()
        child = TraceContext.child(root)
        assert child.trace_id == root.trace_id
        assert child.parent_span_id == root.span_id
        assert child.span_id != root.span_id

    def test_fork_creates_new_trace_id(self):
        root = TraceContext.root(correlation_id="shared")
        forked = TraceContext.fork(root)
        assert forked.trace_id != root.trace_id
        assert forked.correlation_id == "shared"  # 保留关联 ID

    def test_child_chain(self):
        """child → child → child 形成完整调用链"""
        root = TraceContext.root()
        child1 = TraceContext.child(root)
        child2 = TraceContext.child(child1)
        child3 = TraceContext.child(child2)

        # 所有 child 共享同一个 trace_id
        assert child1.trace_id == root.trace_id
        assert child2.trace_id == root.trace_id
        assert child3.trace_id == root.trace_id

        # 每个 child 的 parent_span_id 指向上一个
        assert child1.parent_span_id == root.span_id
        assert child2.parent_span_id == child1.span_id
        assert child3.parent_span_id == child2.span_id

    def test_frozen_prevents_mutation(self):
        ctx = TraceContext.root()
        with pytest.raises(Exception):
            ctx.trace_id = "modified"  # type: ignore

    def test_to_dict_and_from_dict(self):
        ctx = TraceContext.root(correlation_id="test")
        d = ctx.to_dict()
        restored = TraceContext.from_dict(d)
        assert restored.trace_id == ctx.trace_id
        assert restored.correlation_id == ctx.correlation_id


class TestEventMetadata:
    """EventMetadata 单元测试"""

    def test_defaults(self):
        meta = EventMetadata()
        assert meta.event_id != ""
        assert meta.schema_version == 1
        assert meta.event_type == SystemEventType.HEARTBEAT

    def test_with_event_type(self):
        meta = EventMetadata(
            event_type=SignalEventType.SIGNAL_CREATED,
            producer="signal_engine",
            schema_version=1,
        )
        assert meta.event_type == SignalEventType.SIGNAL_CREATED
        assert meta.producer == "signal_engine"

    def test_frozen(self):
        meta = EventMetadata()
        with pytest.raises(Exception):
            meta.producer = "changed"  # type: ignore


class TestEventEnvelope:
    """EventEnvelope 单元测试"""

    def test_create_with_typed_payload(self):
        event = EventEnvelope[TestSignalPayload](
            metadata=EventMetadata(
                event_type=SignalEventType.SIGNAL_CREATED,
                producer="signal_engine",
            ),
            trace=TraceContext.root(correlation_id="sess_001"),
            payload=TestSignalPayload(
                stock_code="000725.SZ",
                score=95.0,
                direction="buy",
            ),
        )

        assert event.metadata.event_type == SignalEventType.SIGNAL_CREATED
        assert event.trace.correlation_id == "sess_001"
        assert event.payload.stock_code == "000725.SZ"
        assert event.payload.score == 95.0

    def test_default_payload_is_empty(self):
        event = EventEnvelope()
        assert isinstance(event.payload, EmptyPayload)

    def test_frozen_prevents_payload_mutation(self):
        event = EventEnvelope[TestSignalPayload](
            payload=TestSignalPayload(stock_code="000725.SZ", score=95.0),
        )
        with pytest.raises(Exception):
            event.payload.stock_code = "changed"  # type: ignore

    def test_to_dict_serialization(self):
        event = EventEnvelope[TestSignalPayload](
            metadata=EventMetadata(
                event_type=ScannerEventType.SCANNER_COMPLETED,
                producer="scanner_engine",
            ),
            trace=TraceContext.root(correlation_id="test"),
            payload=TestSignalPayload(stock_code="000001.SZ", score=80.0),
        )

        d = event.to_dict()
        assert "metadata" in d
        assert "trace" in d
        assert "payload" in d
        assert d["metadata"]["event_type"] == "scanner.completed"
        assert d["payload"]["stock_code"] == "000001.SZ"

    def test_event_type_str_enum_values(self):
        """验证 EventType StrEnum 的 value 格式"""
        assert SignalEventType.SIGNAL_CREATED.value == "domain.signal.created"
        assert ScannerEventType.SCANNER_COMPLETED.value == "scanner.completed"
        assert SystemEventType.HEARTBEAT.value == "system.heartbeat"


class TestBaseEventPayload:
    """BaseEventPayload 单元测试"""

    def test_validate_default_passes(self):
        payload = TestSignalPayload()
        payload.validate()  # 默认不抛异常

    def test_schema_version_default(self):
        payload = TestSignalPayload()
        assert payload.schema_version == 1
