"""MemoryEventBus 单元测试"""

import asyncio
import pytest

from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.event_metadata import EventMetadata
from src.domain.events.core.trace_context import TraceContext
from src.domain.events.core.event_type import SignalEventType, ScannerEventType
from src.domain.events.core.base_payload import BaseEventPayload
from src.infrastructure.eventbus.memory_bus import MemoryEventBus

from dataclasses import dataclass


@dataclass(frozen=True)
class TestPayload(BaseEventPayload):
    value: str = ""


class TestMemoryEventBus:
    """MemoryEventBus 单元测试"""

    @pytest.fixture
    def bus(self):
        return MemoryEventBus(max_queue_size=100)

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, bus):
        """发布事件 → 消费者收到"""
        received = []

        async def handler(event: EventEnvelope):
            received.append(event)

        await bus.subscribe(SignalEventType.SIGNAL_CREATED, handler)
        await bus.start()

        event = EventEnvelope[TestPayload](
            metadata=EventMetadata(event_type=SignalEventType.SIGNAL_CREATED),
            payload=TestPayload(value="test"),
        )
        await bus.publish(event)

        # 等待分发
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].payload.value == "test"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus):
        """同一事件多个订阅者"""
        received_a = []
        received_b = []

        async def handler_a(event): received_a.append(event)
        async def handler_b(event): received_b.append(event)

        await bus.subscribe(ScannerEventType.SCANNER_COMPLETED, handler_a)
        await bus.subscribe(ScannerEventType.SCANNER_COMPLETED, handler_b)
        await bus.start()

        event = EventEnvelope[TestPayload](
            metadata=EventMetadata(event_type=ScannerEventType.SCANNER_COMPLETED),
        )
        await bus.publish(event)
        await asyncio.sleep(0.2)

        assert len(received_a) == 1
        assert len(received_b) == 1

        await bus.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus):
        """取消订阅后不再收到"""
        received = []

        async def handler(event): received.append(event)

        await bus.subscribe(SignalEventType.SIGNAL_CREATED, handler)
        await bus.unsubscribe(SignalEventType.SIGNAL_CREATED, handler)
        await bus.start()

        event = EventEnvelope[TestPayload](
            metadata=EventMetadata(event_type=SignalEventType.SIGNAL_CREATED),
        )
        await bus.publish(event)
        await asyncio.sleep(0.2)

        assert len(received) == 0

        await bus.stop()

    @pytest.mark.asyncio
    async def test_different_event_types_not_mixed(self, bus):
        """不同类型事件不混淆"""
        signal_received = []
        scanner_received = []

        async def signal_handler(event): signal_received.append(event)
        async def scanner_handler(event): scanner_received.append(event)

        await bus.subscribe(SignalEventType.SIGNAL_CREATED, signal_handler)
        await bus.subscribe(ScannerEventType.SCANNER_COMPLETED, scanner_handler)
        await bus.start()

        await bus.publish(EventEnvelope[TestPayload](
            metadata=EventMetadata(event_type=SignalEventType.SIGNAL_CREATED),
        ))
        await asyncio.sleep(0.2)

        assert len(signal_received) == 1
        assert len(scanner_received) == 0

        await bus.stop()

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash_bus(self, bus):
        """Handler 抛异常不影响其他 handler"""
        good_received = []

        async def bad_handler(event): raise RuntimeError("boom")
        async def good_handler(event): good_received.append(event)

        await bus.subscribe(SignalEventType.SIGNAL_CREATED, bad_handler)
        await bus.subscribe(SignalEventType.SIGNAL_CREATED, good_handler)
        await bus.start()

        await bus.publish(EventEnvelope[TestPayload](
            metadata=EventMetadata(event_type=SignalEventType.SIGNAL_CREATED),
        ))
        await asyncio.sleep(0.2)

        # 好的 handler 仍然收到
        assert len(good_received) == 1

        await bus.stop()
