# ADR-0002: Plugin Registry Architecture

- **日期**: 2026-07-05
- **状态**: Accepted
- **Phase**: Phase 1

---

## Context

项目需要支持多种数据源（AKShare/Tushare/Yahoo/Polygon/...）、多种信号（MACD/RSI/自定义/ML）、多种 AI Provider、多种通知渠道。需要一个统一的插件机制来管理这些扩展。

## Options Considered

| 方案 | 优点 | 缺点 |
|------|------|------|
| pluggy (pytest 插件框架) | 成熟、hook-based | 引入重依赖、不适合非 hook 场景 |
| setuptools entry_points | Python 标准 | 需要 pip install 每个插件、不灵活 |
| **自建 PluginRegistry** | 轻量、适合项目需求 | 需要自己实现 |

## Decision

自建 PluginRegistry，核心原则：

1. **Discovery 不 import Python 模块** — 只解析 plugin.yaml → Manifest，最后一步才 importlib
2. **Manifest 强类型 (frozen dataclass)** — 不操作 dict
3. **生命周期状态机** — DISCOVERED→VALIDATED→LOADED→INITIALIZED→ACTIVE，非法转移抛异常
4. **Registry 无业务知识** — 不出现 `if plugin.type == "datasource"`，只做元数据管理
5. **Registry 不缓存实例** — 支持 reload/hot swap/disable

## Consequences

**优点**:
- 插件目录丢入即识别（`plugins/datasource/xxx/plugin.yaml`）
- 版本约束（api_version/minimum_core/maximum_core）防止升级不兼容
- 按能力查询（`find_by_capability("supports_lhb")`）替代 if-else
- 坏插件不崩溃 Registry（Discovery 阶段隔离错误）

**缺点**:
- 不是标准 Python 插件机制，外部贡献者需学习 plugin.yaml 规范
- 尚不支持插件依赖解析

## Related

- ADR-0001-event-system.md
- docs/architecture-final-v1.0.md
