"""内存 EventBus — Phase 0 实现

基于 asyncio.Queue + dict，零外部依赖。
Phase 4+ 切换到 Redis Pub/Sub，Phase 8+ 切换到 Kafka。
接口不变，只换实现。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Callable, Awaitable

from loguru import logger

from src.domain.events.core.event_envelope import EventEnvelope
from src.domain.events.core.event_type import AnyEventType
from src.domain.ports.event_bus_port import EventBusPort


Handler = Callable[[EventEnvelope], Awaitable[None]]


class MemoryEventBus(EventBusPort):
    """内存版 EventBus — asyncio.Queue 实现"""

    def __init__(self, max_queue_size: int = 10000):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._worker_task: asyncio.Task | None = None

    async def publish(self, event: EventEnvelope) -> None:
        """发布事件 — 入队后异步分发"""
        event_type = event.metadata.event_type.value
        logger.debug(
            "Event published: type={}, producer={}, trace_id={}",
            event_type,
            event.metadata.producer,
            event.trace.trace_id,
        )
        await self._queue.put(event)

    async def subscribe(self, event_type: AnyEventType, handler: Handler) -> None:
        """订阅事件 — handler 接收 EventEnvelope"""
        key = event_type.value
        self._handlers[key].append(handler)
        logger.debug("Subscribed to event: {}", key)

    async def unsubscribe(self, event_type: AnyEventType, handler: Handler) -> None:
        """取消订阅"""
        key = event_type.value
        if handler in self._handlers[key]:
            self._handlers[key].remove(handler)

    async def start(self) -> None:
        """启动 EventBus worker"""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("MemoryEventBus started")

    async def stop(self) -> None:
        """停止 EventBus"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("MemoryEventBus stopped")

    async def _worker_loop(self) -> None:
        """Worker: 从队列取事件 → 分发给订阅者"""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                event_type = event.metadata.event_type.value
                handlers = self._handlers.get(event_type, [])
                for handler in handlers:
                    try:
                        await handler(event)
                    except Exception:
                        logger.exception(
                            "Error handling event: type={}, handler={}",
                            event_type,
                            handler.__name__,
                        )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in EventBus worker")
