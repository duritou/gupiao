# ADR-0001: Event System Architecture

- **日期**: 2026-07-05
- **状态**: Accepted
- **Phase**: Phase 0

---

## Context

项目需要一套事件驱动架构来解耦模块（Scanner → Signal → Agent → Report → Notification）。需要决定：使用现有消息队列框架，还是自建轻量 EventBus。

## Options Considered

| 方案 | 优点 | 缺点 |
|------|------|------|
| Redis Pub/Sub | 生产级、持久化 | Phase 0 引入外部依赖过重 |
| 直接方法调用 | 简单 | 模块强耦合 |
| **自建 MemoryEventBus + EventEnvelope 协议** | 零依赖、类型安全、后期可切换 | 需要自己设计协议 |

## Decision

自建 Event 系统，分三层：

1. **EventEnvelope[T]** (Domain) — 不可变协议：metadata + trace + payload，不含 delivery
2. **MessageEnvelope** (Infrastructure) — 传输包装：event + delivery (retry/priority/ttl)
3. **MemoryEventBus** (Phase 0) — asyncio.Queue 实现，Phase 4+ 切换 Redis

## Consequences

**优点**:
- Domain 层完全不知道 Transport (retry/ttl/priority 在 MessageEnvelope 中)
- EventEnvelope frozen + Generic[T] — 类型安全，IDE 补全
- TraceContext 独立封装 (root/child/fork)，v1.2 预留 W3C Trace Context 字段
- EventType 按领域拆分 (SignalEventType/ScannerEventType/...)，不炸成一个超长 Enum
- 切换 MQ 只需换 EventBus 实现，Event 协议不变

**缺点**:
- Phase 0 需自己实现 EventBus worker loop
- 尚未经过高吞吐验证

## Related

- ADR-0002-plugin-registry.md
- docs/architecture-v1.0-patch-event-system.md
