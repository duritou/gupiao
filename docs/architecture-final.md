# AI Research Terminal — 架构设计文档（最终版）

> **版本**: Final  
> **日期**: 2026-07-05  
> **定位**: AI 股票研究终端（非 AI 选股工具）  
> **状态**: 架构冻结，进入开发阶段

---

## 目录

1. [定位宣言](#1-定位宣言)
2. [项目总体架构](#2-项目总体架构)
3. [完整目录结构](#3-完整目录结构)
4. [每个目录职责](#4-每个目录职责)
5. [每个模块职责](#5-每个模块职责)
6. [数据库设计](#6-数据库设计)
7. [事件总线设计（Event Bus）](#7-事件总线设计event-bus)
8. [任务队列设计（Task Queue）](#8-任务队列设计task-queue)
9. [监控指标设计（Metrics）](#9-监控指标设计metrics)
10. [数据流设计](#10-数据流设计)
11. [AI Agent 层设计](#11-ai-agent-层设计)
12. [Plugin Registry 设计](#12-plugin-registry-设计)
13. [插件通信流程](#13-插件通信流程)
14. [配置管理](#14-配置管理)
15. [日志管理](#15-日志管理)
16. [缓存方案](#16-缓存方案)
17. [未来扩展方案](#17-未来扩展方案)
18. [接口设计](#18-接口设计)
19. [模块依赖图](#19-模块依赖图)
20. [整体开发路线图](#20-整体开发路线图roadmap)

---

## 1. 定位宣言

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│   ❌ 不是: AI 选股工具                                        │
│   ✅ 是:  AI Research Terminal (AI 股票研究终端)               │
│                                                               │
│   AI选股工具              vs    AI Research Terminal           │
│   ─────────                    ────────────────────            │
│   AI 直接说"买"               AI 收集信息                      │
│   AI 做决策                    AI 做信号融合                   │
│   黑盒推荐                     给出证据                        │
│   替代人                       增强人                          │
│   单次输出                     持续研究                        │
│   Token 换答案                上下文换洞察                     │
│                                                               │
│   最终交易决策: 人                                             │
│   信息收集/信号融合/证据呈现/风险提示: AI Research Terminal     │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**设计哲学**:

> 像职业投资机构的研究部门一样工作——
> 研究员收集信息 → 分析师评分 → 审核员检查 → 报告员输出
> 基金经理（人）做最终决策。

---

## 2. 项目总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                    表示层 (Presentation Layer)                         │
│  ┌─────────────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│  │   VS Code 插件       │  │   Web 前端    │  │   CLI 命令行      │     │
│  │   (纯 UI)            │  │   (后期)      │  │   (后期)          │     │
│  └─────────┬───────────┘  └──────┬───────┘  └────────┬─────────┘     │
└────────────┼─────────────────────┼───────────────────┼───────────────┘
             │                     │                   │
             └─────────────────────┼───────────────────┘
                                   │ REST / WebSocket / IPC
┌──────────────────────────────────┼───────────────────────────────────┐
│                    应用层 (Application Layer)                         │
│  ┌───────────────────────────────┴──────────────────────────────────┐ │
│  │                     API 网关                                      │ │
│  └───────────────────────────────┬──────────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌────┴─────┐ ┌──────────┐ ┌────────────┐ │
│  │ 策略服务  │ │ 回测服务  │ │ 研究服务  │ │ 信号服务  │ │ 管线服务    │ │
│  │ strategy │ │ backtest │ │research  │ │signal_svc│ │pipeline    │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    领域层 (Domain Layer)                              │
│  ┌───────────────────────────────┴──────────────────────────────────┐ │
│  │  领域模型 · 领域服务 · 端口接口                                   │ │
│  │  PluginRegistryPort · AgentOrchestrator · ResearchSession         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    领域事件 (domain/events/)                       │ │
│  │  MarketUpdated · SignalGenerated · ScannerCompleted               │ │
│  │  ResearchCompleted · RiskAlertTriggered                           │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    基础设施层 (Infrastructure Layer)                   │
│                                                                       │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────────────┐   │
│  │  Event Bus     │ │  Task Queue    │ │  Plugin Registry       │   │
│  │  (事件驱动)     │ │  (异步任务)     │ │  (插件注册中心)         │   │
│  └────────────────┘ └────────────────┘ └────────────────────────┘   │
│                                                                       │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────────────┐   │
│  │  Metrics       │ │  AI Agent      │ │  Compliance            │   │
│  │  (监控指标)     │ │  Layer         │ │  (数据合规)             │   │
│  └────────────────┘ └────────────────┘ └────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Market Gateway · Signals · Knowledge · Cache · Repositories  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    插件层 (Plugin Layer)                               │
│                                                                       │
│  plugins/                                                             │
│  ├── datasource/    (丢进去就能识别)                                   │
│  └── signal/        (未来扩展)                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 完整目录结构

```
jiancechengxu/
│
├── .env.example
├── .env
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml
├── pyproject.toml
├── poetry.lock
├── README.md
├── CHANGELOG.md
├── LICENSE
├── Makefile
│
├── docs/
│   ├── architecture-final.md         # 最终架构文档
│   ├── architecture-v3.md            # v3 留档
│   ├── architecture-v2.md            # v2 留档
│   ├── architecture-v1.md            # v1 留档
│   ├── api-reference.md
│   ├── database-schema.md
│   ├── development-guide.md
│   └── deployment-guide.md
│
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── database.py
│   ├── ai_models.py
│   ├── plugin_registry.py
│   ├── event_topics.py               # 事件主题定义
│   ├── task_queue.py                 # 任务队列配置
│   ├── trading.py
│   ├── cache.py
│   ├── metrics.py                    # 监控指标配置
│   ├── logging.yaml
│   ├── license_policies.yaml         # [重要] 独立许可配置（与插件解耦）
│   ├── prompts/
│   │   ├── system_prompts/
│   │   │   ├── planner.yaml
│   │   │   ├── researcher.yaml
│   │   │   ├── analyst.yaml
│   │   │   ├── reviewer.yaml
│   │   │   └── reporter.yaml
│   │   ├── templates/
│   │   └── few_shot_examples/
│   └── brokers/
│
├── src/
│   ├── __init__.py
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── stock.py
│   │   │   ├── market_data.py
│   │   │   ├── strategy.py
│   │   │   ├── signal.py
│   │   │   ├── order.py
│   │   │   ├── position.py
│   │   │   ├── portfolio.py
│   │   │   ├── account.py
│   │   │   ├── backtest.py
│   │   │   ├── research_session.py
│   │   │   ├── agent_task.py
│   │   │   ├── plugin_manifest.py
│   │   │   ├── datasource_capability.py
│   │   │   ├── ai_analysis.py
│   │   │   ├── risk.py
│   │   │   ├── indicator.py
│   │   │   ├── compliance_record.py
│   │   │   ├── task_record.py            # 任务队列执行记录
│   │   │   └── enums.py
│   │   ├── services/
│   │   │   ├── trading_engine.py
│   │   │   ├── signal_fusion_engine.py
│   │   │   ├── risk_manager.py
│   │   │   ├── portfolio_optimizer.py
│   │   │   ├── market_screener.py
│   │   │   ├── scanner_engine.py
│   │   │   ├── backtest_engine.py
│   │   │   ├── agent_orchestrator.py
│   │   │   └── research_pipeline.py
│   │   ├── ports/
│   │   │   ├── market_gateway_port.py
│   │   │   ├── ai_provider_port.py
│   │   │   ├── broker_port.py
│   │   │   ├── cache_port.py
│   │   │   ├── repository_port.py
│   │   │   ├── notification_port.py
│   │   │   ├── compliance_port.py
│   │   │   ├── knowledge_base_port.py
│   │   │   ├── plugin_registry_port.py
│   │   │   ├── event_bus_port.py          # 事件总线端口
│   │   │   ├── task_queue_port.py         # 任务队列端口
│   │   │   └── message_queue_port.py
│   │   └── events/
│   │       ├── __init__.py
│   │       ├── market_events.py           # MarketUpdated, DataSyncCompleted
│   │       ├── signal_events.py           # SignalGenerated, FusionCompleted
│   │       ├── scanner_events.py          # ScannerCompleted, TopStocksReady
│   │       ├── research_events.py         # ResearchStarted, ResearchCompleted
│   │       ├── trading_events.py
│   │       ├── agent_events.py
│   │       └── risk_events.py
│   │
│   ├── application/
│   │   ├── __init__.py
│   │   ├── use_cases/
│   │   │   ├── market_data_use_cases.py
│   │   │   ├── strategy_use_cases.py
│   │   │   ├── trading_use_cases.py
│   │   │   ├── backtest_use_cases.py
│   │   │   ├── research_use_cases.py
│   │   │   ├── portfolio_use_cases.py
│   │   │   ├── risk_use_cases.py
│   │   │   ├── scanner_use_cases.py
│   │   │   ├── research_pipeline_use_cases.py
│   │   │   └── system_use_cases.py
│   │   ├── dto/
│   │   └── event_handlers/
│   │       ├── market_handlers.py
│   │       ├── signal_handlers.py         # SignalGenerated → Scanner → AI
│   │       ├── scanner_handlers.py        # ScannerCompleted → Agent
│   │       ├── research_handlers.py       # ResearchCompleted → Notification
│   │       ├── trading_handlers.py
│   │       └── risk_handlers.py
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   │
│   │   ├── eventbus/                      # [Final新增] 事件总线
│   │   │   ├── __init__.py
│   │   │   ├── bus.py                     #   事件总线核心
│   │   │   ├── publisher.py               #   事件发布器
│   │   │   ├── subscriber.py              #   事件订阅器
│   │   │   └── middleware.py              #   中间件（日志/重试/死信）
│   │   │
│   │   ├── task_queue/                    # [Final新增] 任务队列
│   │   │   ├── __init__.py
│   │   │   ├── broker.py                  #   队列 Broker 封装（Celery/Arq）
│   │   │   ├── tasks.py                   #   预定义任务
│   │   │   ├── worker.py                  #   Worker 入口
│   │   │   └── scheduler.py               #   定时任务调度
│   │   │
│   │   ├── metrics/                       # [Final新增] 监控指标
│   │   │   ├── __init__.py
│   │   │   ├── collector.py               #   指标采集器
│   │   │   ├── prometheus.py              #   Prometheus 导出
│   │   │   └── dashboard.py               #   内置 Dashboard 数据接口
│   │   │
│   │   ├── plugin_registry/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py
│   │   │   ├── loader.py
│   │   │   ├── validator.py
│   │   │   ├── lifecycle.py
│   │   │   └── metadata.py
│   │   ├── adapters/
│   │   │   ├── market_gateway/
│   │   │   │   ├── gateway.py
│   │   │   │   ├── base.py
│   │   │   │   └── factory.py
│   │   │   ├── ai_providers/
│   │   │   │   ├── base.py
│   │   │   │   ├── deepseek_adapter.py
│   │   │   │   ├── openai_adapter.py
│   │   │   │   └── factory.py
│   │   │   ├── brokers/
│   │   │   └── notifications/
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── planner.py
│   │   │   ├── researcher.py
│   │   │   ├── analyst.py
│   │   │   ├── reviewer.py
│   │   │   ├── reporter.py
│   │   │   ├── context_builder.py
│   │   │   └── tool_provider.py
│   │   ├── compliance/
│   │   │   ├── datasource_policy.py
│   │   │   ├── datasource_validator.py
│   │   │   ├── license_checker.py         # 读取独立许可配置
│   │   │   ├── capability_checker.py
│   │   │   ├── rate_limit.py
│   │   │   └── audit_logger.py
│   │   ├── repositories/
│   │   ├── orm/
│   │   ├── cache/
│   │   └── external/
│   │
│   ├── signals/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── fusion.py
│   │   ├── builtin/
│   │   │   ├── macd.py
│   │   │   ├── kdj.py
│   │   │   ├── rsi.py
│   │   │   ├── volume.py
│   │   │   ├── ma.py
│   │   │   ├── boll.py
│   │   │   ├── chip.py
│   │   │   ├── lhb.py
│   │   │   ├── capital.py
│   │   │   ├── news.py
│   │   │   └── sentiment.py
│   │   ├── custom/
│   │   │   └── _template.py
│   │   └── ml/
│   │       ├── base_ml.py
│   │       ├── xgboost_signal.py
│   │       └── lightgbm_signal.py
│   │
│   ├── api/
│   │   ├── app.py
│   │   ├── dependencies.py
│   │   ├── middleware/
│   │   └── routes/
│   │       ├── plugin_routes.py
│   │       ├── research_routes.py
│   │       ├── metrics_routes.py          # [Final新增] 指标查询API
│   │       └── ...
│   │
│   └── shared/
│       ├── plugin_protocol.py
│       ├── types.py
│       ├── constants.py
│       ├── exceptions.py
│       ├── utils/
│       └── decorators.py
│
├── plugins/
│   ├── README.md
│   ├── datasource/
│   │   ├── akshare/
│   │   │   ├── plugin.yaml
│   │   │   ├── __init__.py
│   │   │   └── adapter.py
│   │   ├── tushare/
│   │   │   ├── plugin.yaml
│   │   │   ├── __init__.py
│   │   │   └── adapter.py
│   │   └── _template/
│   │       ├── plugin.yaml
│   │       ├── __init__.py
│   │       └── adapter.py
│   └── signal/
│       └── _template/
│
├── knowledge/
│   ├── industry/
│   ├── macro/
│   ├── concepts/
│   ├── finance/
│   ├── reports/
│   ├── policy/
│   ├── strategy/
│   ├── books/
│   ├── papers/
│   └── glossary/
│
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   │   ├── test_eventbus.py
│   │   │   ├── test_task_queue.py
│   │   │   ├── test_metrics.py
│   │   │   ├── test_plugin_registry.py
│   │   │   └── test_agents.py
│   │   └── signals/
│   ├── integration/
│   └── e2e/
│
├── scripts/
├── vscode-ext/
├── web/
├── deploy/
└── data/
```

---

## 4. 每个目录职责

| 目录 | 职责 |
|------|------|
| `src/infrastructure/eventbus/` | **[Final]** 事件总线 — 模块间解耦通信，发布/订阅模式 |
| `src/infrastructure/task_queue/` | **[Final]** 任务队列 — 异步任务调度，避免大循环阻塞 |
| `src/infrastructure/metrics/` | **[Final]** 监控指标 — Prometheus + Dashboard，全链路可观测 |
| `config/license_policies.yaml` | **[Final]** 独立许可配置 — 与 plugin.yaml 技术能力严格分离 |
| `src/domain/events/` | **[Final扩展]** 领域事件定义 — Scanner/Signal/Research 事件 |
| `src/application/event_handlers/` | **[Final扩展]** 事件处理器 — 事件链编排 |

---

## 5. 每个模块职责

### 5.1 Event Bus — 事件总线（Final 新增）

**为什么需要？**

```
没有 Event Bus 时:
  MarketDataSync → 直接调用 Scanner.run()
  Scanner → 直接调用 SignalFusion.compute()
  SignalFusion → 直接调用 AgentOrchestrator.start()
  Agent → 直接调用 Reporter.generate()
  Reporter → 直接调用 Notification.send()

  问题:
  · 模块之间强耦合
  · 新增一个消费者要改生产者代码
  · 无法独立测试
  · 无法独立部署

有 Event Bus 后:
  MarketDataSync → publish(MarketUpdated)
  Scanner 订阅 MarketUpdated → 自动触发
  Scanner → publish(ScannerCompleted)
  SignalFusion 订阅 ScannerCompleted → 自动触发
  SignalFusion → publish(FusionCompleted)
  AgentOrchestrator 订阅 FusionCompleted → 自动触发
  AgentOrchestrator → publish(ResearchCompleted)
  Notification 订阅 ResearchCompleted → 自动推送到 VSCode

  优势:
  · 模块完全解耦
  · 新增消费者只需订阅，不碰生产者
  · 可独立测试每个模块
  · 天然支持异步
```

**事件总线架构**:

```
┌──────────────────────────────────────────────────────────────┐
│                      Event Bus                                │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    EventBus                              │ │
│  │                                                          │ │
│  │  publish(topic, event)     ← 发布事件                    │ │
│  │  subscribe(topic, handler) ← 订阅事件                    │ │
│  │  unsubscribe(topic, handler)                             │ │
│  │                                                          │ │
│  │  中间件链:                                                │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │ │
│  │  │ Logging  │→│ Retry    │→│ Dead     │→│ Metrics   │  │ │
│  │  │Middleware│ │Middleware│ │Letter    │ │Middleware │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  事件主题 (config/event_topics.py):                            │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ market.data.updated        → 行情数据更新完成             │ │
│  │ market.data.sync.completed → 全量同步完成                 │ │
│  │ scanner.completed          → Scanner 筛选完成             │ │
│  │ scanner.top_stocks.ready   → Top N 股票已选出             │ │
│  │ signal.computed            → 单只股票信号计算完成          │ │
│  │ signal.fusion.completed    → 融合评分完成                 │ │
│  │ research.pipeline.started  → 研究管线开始                 │ │
│  │ research.pipeline.step     → 管线步骤完成                 │ │
│  │ research.pipeline.completed→ 管线完成                     │ │
│  │ research.agent.completed   → Agent 研究完成               │ │
│  │ report.generated           → 报告生成完成                 │ │
│  │ order.submitted            → 订单提交                     │ │
│  │ order.filled               → 订单成交                     │ │
│  │ risk.alert.triggered       → 风控预警触发                 │ │
│  │ system.health.check        → 健康检查                     │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**实现策略（分阶段）**:

```
Phase 0-3:   内存版 EventBus（asyncio.Queue + dict）
             零外部依赖，适合早期开发

Phase 4+:    Redis Pub/Sub 版
             持久化 + 多进程支持

Phase 8+:    Kafka / RabbitMQ（如果规模需要）
             高吞吐 + 消息持久化 + 重放
```

**核心接口**:

```python
# src/domain/ports/event_bus_port.py

class EventBusPort(ABC):
    """事件总线端口"""

    @abstractmethod
    async def publish(self, topic: str, event: dict) -> None:
        """发布事件到指定主题"""
        ...

    @abstractmethod
    async def subscribe(
        self, topic: str, handler: Callable[[dict], Awaitable[None]]
    ) -> None:
        """订阅主题"""
        ...

    @abstractmethod
    async def unsubscribe(
        self, topic: str, handler: Callable[[dict], Awaitable[None]]
    ) -> None:
        """取消订阅"""
        ...
```

**典型事件链**:

```python
# 收盘后的事件链
# 无需任何模块显式调用其他模块

# 1. 数据同步完成后发布
await eventbus.publish("market.data.sync.completed", {
    "sync_date": "2026-07-05",
    "stocks_synced": 5000,
})

# 2. Scanner 订阅 → 自动运行 → 完成后发布
# (Scanner 的 event_handler 自动触发)
await eventbus.publish("scanner.completed", {
    "filtered_count": 100,
    "top_20": ["000725.SZ", "000100.SZ", ...],
})

# 3. SignalFusion 订阅 → 自动运行 → 完成后发布
await eventbus.publish("signal.fusion.completed", {
    "scores": { "000725.SZ": 91.8, ... },
})

# 4. Agent 订阅 → 自动分析 → 完成后发布
await eventbus.publish("research.agent.completed", {
    "session_id": "sess_001",
    "report_path": "data/exports/report_20260705.md",
})

# 5. Notification 订阅 → 自动推送
await eventbus.publish("report.generated", {
    "report_path": "...",
    "channels": ["vscode", "email"],
})
```

---

### 5.2 Task Queue — 任务队列（Final 新增）

**为什么需要？**

```
没有 Task Queue 时:
  for stock in all_5000_stocks:         ← 单线程，阻塞
      compute_signals(stock)
      save_to_db(stock)
  
  问题:
  · 5000 只股票串行处理 > 30 分钟
  · 阻塞主线程，API 无法响应
  · 失败一只就中断整个流程
  · 无法重试失败的任务

有 Task Queue 后:
  for stock in all_5000_stocks:
      compute_signal_task.delay(stock)   ← 异步分发到 Worker

  · 8 个 Worker 并行处理
  · 5000 只股票 < 2 分钟
  · API 不受影响
  · 失败自动重试
  · 可监控进度
```

**技术选型: Arq（推荐）**

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **Arq** | 纯 asyncio、基于 Redis、轻量、代码即任务 | 社区较小 | ⭐⭐⭐⭐⭐ |
| Celery | 功能全、生态大 | 配置复杂、同步设计、重 | ⭐⭐⭐ |
| Dramatiq | 简洁、可靠 | 需要 RabbitMQ | ⭐⭐⭐ |
| RQ | 简单 | 同步、功能少 | ⭐⭐⭐ |

**选择 Arq 的理由**: 与项目 asyncio 架构天然兼容；基于 Redis（已引入）；零配置；Worker 代码就是普通 async 函数。

**架构设计**:

```
┌──────────────────────────────────────────────────────────────┐
│                     Task Queue (Arq)                          │
│                                                               │
│  ┌─────────────────┐                                         │
│  │  Task Producer   │  (FastAPI / Cron / EventBus Handler)   │
│  │                  │                                         │
│  │  await task_     │                                         │
│  │  queue.enqueue(  │                                         │
│  │    "sync_stock", │                                         │
│  │    stock_code    │                                         │
│  │  )               │                                         │
│  └────────┬────────┘                                         │
│           │                                                   │
│           ▼                                                   │
│  ┌─────────────────┐     ┌──────────────────┐               │
│  │     Redis        │────►│  Arq Worker #1   │               │
│  │  (Job Queue)     │     │  Arq Worker #2   │               │
│  │                  │     │  Arq Worker #3   │               │
│  │                  │     │  Arq Worker #N   │               │
│  └─────────────────┘     └────────┬─────────┘               │
│                                   │                           │
│                                   ▼                           │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  预定义任务 (task_queue/tasks.py)                         │ │
│  │                                                          │ │
│  │  sync_stock_kline(code, period, start, end)              │ │
│  │  sync_all_stocks_daily()          # 全量同步（定时）      │ │
│  │  compute_stock_signals(code)      # 单股信号计算          │ │
│  │  compute_all_signals_daily()      # 全量信号（定时）      │ │
│  │  run_scanner_pipeline()           # 扫描管道              │ │
│  │  run_agent_research(query)        # Agent 研究            │ │
│  │  run_research_pipeline()          # 收盘研究管线           │ │
│  │  generate_daily_report()          # 日度报告              │ │
│  │  cleanup_old_cache()              # 缓存清理              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  任务配置 (config/task_queue.py)                          │ │
│  │                                                          │ │
│  │  TASK_RETRY_MAX: 3            # 最大重试次数              │ │
│  │  TASK_RETRY_DELAY: 60         # 重试间隔（秒）            │ │
│  │  TASK_TIMEOUT: 300            # 超时时间（秒）            │ │
│  │  WORKER_COUNT: 8              # Worker 数量               │ │
│  │  JOB_RESULT_TTL: 86400        # 结果保留（秒）            │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**核心接口**:

```python
# src/domain/ports/task_queue_port.py

class TaskQueuePort(ABC):
    """任务队列端口"""

    @abstractmethod
    async def enqueue(
        self,
        task_name: str,
        *args,
        **kwargs,
    ) -> str:
        """入队任务 → 返回 job_id"""
        ...

    @abstractmethod
    async def get_result(self, job_id: str) -> Optional[dict]:
        """获取任务结果"""
        ...

    @abstractmethod
    async def get_status(self, job_id: str) -> str:
        """获取任务状态: queued/running/completed/failed"""
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """取消任务"""
        ...
```

---

### 5.3 Metrics — 监控指标（Final 新增）

**为什么需要？**

> 你的平台越来越专业。没有 Metrics 就不知道：
> Scanner 为什么变慢了？AI Token 为什么暴增？缓存命中率下降了吗？
> 哪个 Plugin 最慢？今天花了多少 API 费用？

**指标分类**:

```
┌──────────────────────────────────────────────────────────────┐
│                     Metrics 指标体系                          │
│                                                               │
│  📊 性能指标                                                   │
│  ├── scanner_duration_seconds        Scanner 耗时             │
│  ├── signal_compute_duration_seconds 信号计算耗时（分信号）    │
│  ├── ai_request_duration_seconds     AI 请求延迟              │
│  ├── plugin_query_duration_seconds   Plugin 查询耗时          │
│  ├── data_sync_duration_seconds      数据同步耗时             │
│  └── api_request_duration_seconds    API 请求延迟             │
│                                                               │
│  💰 成本指标                                                   │
│  ├── ai_tokens_used_total            Token 总消耗              │
│  ├── ai_tokens_used_by_model         Token 消耗（分模型）      │
│  ├── ai_cost_estimated_usd           API 费用估算（美元）      │
│  └── ai_cost_daily_usd               每日 API 费用            │
│                                                               │
│  📈 业务指标                                                   │
│  ├── research_sessions_total         研究会话总数              │
│  ├── research_sessions_daily         每日研究数                │
│  ├── signals_computed_total          信号计算总数              │
│  ├── scanner_stocks_filtered         Scanner 筛选数量          │
│  ├── reports_generated_total         报告生成总数              │
│  └── alerts_triggered_total          预警触发总数              │
│                                                               │
│  💾 缓存指标                                                   │
│  ├── cache_hit_ratio                 缓存命中率               │
│  ├── cache_size_bytes                缓存大小                 │
│  └── cache_evictions_total           缓存淘汰次数              │
│                                                               │
│  🏥 健康指标                                                   │
│  ├── plugin_health_status            插件健康状态              │
│  ├── datasource_availability         数据源可用性              │
│  ├── task_queue_size                 任务队列积压量            │
│  └── worker_status                   Worker 状态              │
│                                                               │
│  🔌 插件指标                                                   │
│  ├── plugin_load_duration_seconds    插件加载耗时              │
│  ├── plugin_error_count_total        插件错误计数              │
│  └── plugin_query_count_total        插件查询计数              │
└──────────────────────────────────────────────────────────────┘
```

**实现策略（分阶段）**:

```
Phase 0-5:   内存版（Python dict + JSON dump）
             零外部依赖，打印到日志

Phase 6+:    Prometheus (prometheus_client)
             标准 /metrics 端点，Grafana Dashboard

Phase 10+:   分布式追踪（OpenTelemetry）
             全链路 Trace
```

**核心代码骨架**:

```python
# src/infrastructure/metrics/collector.py

from dataclasses import dataclass, field
from collections import defaultdict
import time

@dataclass
class MetricsCollector:
    """指标采集器（Phase 0: 内存版，Phase 6: 切换 Prometheus）"""

    # 计数器
    counters: dict = field(default_factory=lambda: defaultdict(int))
    # 直方图
    histograms: dict = field(default_factory=lambda: defaultdict(list))
    # 仪表
    gauges: dict = field(default_factory=dict)

    def increment(self, name: str, value: int = 1):
        self.counters[name] += value

    def observe(self, name: str, value: float):
        self.histograms[name].append(value)

    def set_gauge(self, name: str, value: float):
        self.gauges[name] = value

    def get_snapshot(self) -> dict:
        """获取当前指标快照"""
        return {
            "counters": dict(self.counters),
            "histograms": {
                k: {
                    "count": len(v),
                    "avg": sum(v) / len(v) if v else 0,
                    "max": max(v) if v else 0,
                    "min": min(v) if v else 0,
                }
                for k, v in self.histograms.items()
            },
            "gauges": dict(self.gauges),
        }


# 全局单例
metrics = MetricsCollector()


# 使用示例（装饰器方式）
def track_duration(metric_name: str):
    """装饰器：自动记录函数耗时"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                metrics.observe(metric_name, duration)
        return wrapper
    return decorator

# 使用示例
@track_duration("scanner_duration_seconds")
async def run_scanner():
    ...
```

---

### 5.4 许可配置分离（Final 完善）

**核心原则**:

> plugin.yaml 只声明**技术能力**（有没有分钟线、龙虎榜、新闻等）
> 合规权限（能不能商业用、能不能缓存、能不能 AI 分析）由独立的 `license_policies.yaml` 管理
> 这样数据源许可条款变化时，只改配置文件，不改插件代码

**plugin.yaml（只声明技术能力）**:

```yaml
# plugins/datasource/akshare/plugin.yaml

plugin:
  name: "akshare"
  version: "1.0.0"
  type: "datasource"
  display_name: "AKShare 数据源"
  description: "基于 AKShare 的 A 股免费数据源"
  author: "QuantAI Team"
  entry_point: "adapter:AKShareAdapter"
  dependencies: ["akshare>=1.12.0"]
  python_version: ">=3.12"

  # ===== 只声明技术能力 =====
  # 这里写: 这个数据源"能不能"做什么（纯技术事实）
  capabilities:
    supports_realtime: true
    supports_intraday: true
    supports_history: true
    supports_financials: true
    supports_lhb: true
    supports_fund_flow: true
    supports_news: false
    supports_indices: true
    supports_sectors: true
    coverage_markets: ["SH", "SZ", "BJ"]
    latency: "t+0"
    data_quality: "good"
    rate_limit_recommended: 60     # 建议速率（非强制）

  # ===== 不在这里写合规声明 =====
  # 合规权限由 config/license_policies.yaml 统一管理
```

**license_policies.yaml（独立许可配置）**:

```yaml
# config/license_policies.yaml
# 此文件管理所有数据源的合规权限
# 与 plugin.yaml 的技术能力严格分离
# 许可条款变化时，只改此文件

license_policies:
  akshare:
    # 以下权限依据: AKShare MIT License
    # 最后审查日期: 2026-07-05
    license_type: "MIT"
    license_url: "https://github.com/akfamily/akshare/blob/master/LICENSE"
    permissions:
      allow_commercial: true
      allow_cache: true
      allow_redis: true
      allow_ai_analysis: true
      allow_long_term_storage: true
      allow_redistribution: true
      require_attribution: false
      data_retention_days: 0          # 0 = 无限制
    disclaimer: |
      AKShare 使用 MIT 协议，允许商业使用。
      但 AKShare 自身数据来源于公开渠道，对于其中可能包含的
      第三方数据，用户应自行评估合规风险。
    last_reviewed: "2026-07-05"
    reviewer: "project-maintainer"

  tushare:
    license_type: "Proprietary"
    license_url: "https://tushare.pro/document/1?doc_id=40"
    permissions:
      allow_commercial: false         # 基础版不可商用
      allow_cache: true
      allow_redis: true
      allow_ai_analysis: true
      allow_long_term_storage: true
      allow_redistribution: false
      require_attribution: true
      data_retention_days: 0
    disclaimer: |
      Tushare 基础版仅供个人学习和研究使用，不可用于商业目的。
      商业使用需购买 Tushare Pro 商业授权。
    last_reviewed: "2026-07-05"

  yahoo_finance:
    license_type: "Proprietary (Yahoo Terms of Service)"
    license_url: "https://legal.yahoo.com/us/en/yahoo/terms/product-atos/index.html"
    permissions:
      allow_commercial: false
      allow_cache: true
      allow_redis: false              # 不允许共享缓存
      allow_ai_analysis: false        # 不可用于 AI 训练/分析
      allow_long_term_storage: false
      allow_redistribution: false
      require_attribution: true
      data_retention_days: 7          # 最多保留 7 天
    disclaimer: |
      Yahoo Finance 数据仅供个人非商业使用。
      不授予 AI/ML 训练权利。缓存仅限本地临时使用。
      超过 7 天的数据应主动清理。
    last_reviewed: "2026-07-05"
```

**Compliance 如何使用这个分离**:

```python
# src/infrastructure/compliance/license_checker.py

class LicenseChecker:
    """许可检查器 —— 读取独立的 license_policies.yaml"""

    def __init__(self, policies_path: str = "config/license_policies.yaml"):
        self.policies = self._load_policies(policies_path)

    def check(self, datasource_name: str, operation: str) -> LicenseCheckResult:
        policy = self.policies.get(datasource_name)
        if not policy:
            return LicenseCheckResult(denied=True, reason=f"未找到 {datasource_name} 的许可策略")

        allowed = policy["permissions"].get(operation, False)
        return LicenseCheckResult(
            allowed=allowed,
            license_type=policy["license_type"],
            disclaimer=policy.get("disclaimer", ""),
        )

# 使用
checker = LicenseChecker()
result = checker.check("yahoo_finance", "allow_ai_analysis")
# → LicenseCheckResult(allowed=False, license_type="Proprietary",
#                       disclaimer="不授予 AI/ML 训练权利")
```

---

### 5.5 其他模块（继承 v3，简述）

| 模块 | 职责 |
|------|------|
| **Plugin Registry** | 插件发现/加载/校验/生命周期。所有数据源丢 `plugins/datasource/` 就识别 |
| **Market Gateway** | 统一数据网关。从 Registry 获取适配器列表，按能力自动路由 |
| **Compliance** | 5 个子模块 + DataSourceCapability + LicenseChecker（分离配置） |
| **AI Agent Layer** | Planner/Researcher/Analyst/Reviewer/Reporter 5 Agent 协作 |
| **Signals** | builtin/custom/ml 三层 + SignalFusion 融合引擎 |
| **Knowledge** | 8 个子目录，为 AI 提供深度上下文 |

---

## 6. 数据库设计

（核心表继承 v3。Final 新增以下表）

#### task_records（任务队列执行记录）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | |
| `job_id` | VARCHAR(100) | NOT NULL, UNIQUE | Arq Job ID |
| `task_name` | VARCHAR(100) | NOT NULL | 任务名称 |
| `params_json` | TEXT | | 任务参数 |
| `status` | VARCHAR(20) | NOT NULL | queued/running/completed/failed |
| `result_json` | TEXT | | 任务结果 |
| `error_message` | TEXT | | 失败原因 |
| `retry_count` | INTEGER | DEFAULT 0 | |
| `duration_ms` | INTEGER | | 执行耗时 |
| `worker_id` | VARCHAR(100) | | Worker 标识 |
| `queued_at` | DATETIME | | |
| `started_at` | DATETIME | | |
| `completed_at` | DATETIME | | |

#### metric_snapshots（指标快照 — Phase 0 内存版用）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | |
| `snapshot_date` | DATE | NOT NULL | 快照日期 |
| `metrics_json` | TEXT | NOT NULL | 完整指标 JSON |
| `created_at` | DATETIME | DEFAULT NOW | |

---

## 7. 事件总线设计（Event Bus）

> 详见 §5.1

---

## 8. 任务队列设计（Task Queue）

> 详见 §5.2

---

## 9. 监控指标设计（Metrics）

> 详见 §5.3

---

## 10. 数据流设计

### 10.1 事件驱动的收盘研究管线（Final）

```
交易日 15:30 Cron 触发
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Task Queue: run_research_pipeline()                          │
│                                                               │
│  Step 1: 数据同步 (并行入队)                                   │
│  ├── enqueue("sync_stock_kline", batch_1)  ──► Worker Pool   │
│  ├── enqueue("sync_stock_kline", batch_2)  ──► Worker Pool   │
│  ├── enqueue("sync_lhb_data")              ──► Worker Pool   │
│  └── enqueue("sync_news")                  ──► Worker Pool   │
│       │                                                       │
│       ▼ (全部完成后)                                          │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  publish("market.data.sync.completed")                   │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼ (Event Handler 自动触发)                              │
│  Step 2: Scanner                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  (订阅 market.data.sync.completed)                       │ │
│  │  → run_scanner_pipeline()                                │ │
│  │  → publish("scanner.completed", {top_20: [...]})         │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼ (Event Handler 自动触发)                              │
│  Step 3: Signal Fusion                                        │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  (订阅 scanner.completed)                                │ │
│  │  → 并行计算 top_20 的信号                                 │ │
│  │  → fusion.score_all(top_20)                              │ │
│  │  → publish("signal.fusion.completed", {scores: {...}})   │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼ (Event Handler 自动触发)                              │
│  Step 4: AI Agent 深度分析                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  (订阅 signal.fusion.completed)                          │ │
│  │  → AgentOrchestrator.start(top_3, knowledge_context)     │ │
│  │  → publish("research.agent.completed", {report: ...})    │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼ (Event Handler 自动触发)                              │
│  Step 5: 推送                                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  (订阅 research.agent.completed)                         │ │
│  │  → Notification.send(report, channels=["vscode","email"])│ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 11. AI Agent 层设计

（与 v3 完全一致 — Planner → Researcher → Analyst → Reviewer → Reporter）

---

## 12. Plugin Registry 设计

（与 v3 完全一致 — 丢 `plugins/datasource/` 就识别）

---

## 13. 插件通信流程

```
VSCode Extension (纯 UI)
    │
    │ IPC (JSON-RPC)
    ▼
Python Server
    │
    ├── REST API
    │   ├── /plugins             插件管理
    │   ├── /research            研究管理
    │   ├── /metrics             指标查询
    │   └── ...
    │
    └── WebSocket
        └── /ws/research/{id}    Agent 研究实时进度
        └── /ws/events           事件总线 Stream
```

---

## 14. 配置管理

```python
# config/settings.py Final 新增

class Settings(BaseSettings):
    # ... (v3 所有配置保持不变) ...

    # ---- [Final] Event Bus ----
    EVENT_BUS_BACKEND: str = "memory"       # memory / redis / kafka
    EVENT_BUS_MAX_QUEUE_SIZE: int = 10000
    EVENT_RETRY_MAX: int = 3
    EVENT_DEAD_LETTER_ENABLED: bool = True

    # ---- [Final] Task Queue ----
    TASK_QUEUE_BACKEND: str = "arq"         # arq / celery
    TASK_REDIS_URL: str = "redis://localhost:6379/1"
    TASK_WORKER_COUNT: int = 8
    TASK_RETRY_MAX: int = 3
    TASK_RETRY_DELAY_SECONDS: int = 60
    TASK_TIMEOUT_SECONDS: int = 300

    # ---- [Final] Metrics ----
    METRICS_ENABLED: bool = True
    METRICS_BACKEND: str = "memory"         # memory / prometheus
    METRICS_SNAPSHOT_INTERVAL_MINUTES: int = 5
    METRICS_PROMETHEUS_PORT: int = 9090

    # ---- [Final] License ----
    LICENSE_POLICIES_PATH: str = "config/license_policies.yaml"
```

---

## 15. 日志管理

（与 v3 一致。新增 Event Bus 和 Task Queue 的日志分类）

```python
# 事件总线日志
logger.add("data/logs/eventbus.log", filter=lambda r: r["extra"].get("category") == "eventbus")

# 任务队列日志
logger.add("data/logs/task_queue.log", filter=lambda r: r["extra"].get("category") == "task_queue")

# Metrics 日志
logger.add("data/logs/metrics.log", filter=lambda r: r["extra"].get("category") == "metrics")
```

---

## 16. 缓存方案

（与 v3 一致）

---

## 17. 未来扩展方案

```
插件化后，扩展极其简单：

新增数据源:
  cp -r plugins/datasource/_template plugins/datasource/wind/
  编辑 plugin.yaml（技术能力）
  编辑 config/license_policies.yaml（合规权限）  ← [Final] 许可配置分离
  实现 adapter.py → 重启 → 自动识别

新增信号:
  在 signals/custom/ 新增文件 → SignalFusion 自动发现

新增 Agent:
  继承 BaseAgent → 注册到 AgentOrchestrator

新增 LLM:
  实现 AIPort → 所有 Agent 可选用

新增知识:
  在 knowledge/ 新增 YAML → 自动加载
```

---

## 18. 接口设计

### 18.1 EventBusPort

```python
class EventBusPort(ABC):
    async def publish(self, topic: str, event: dict) -> None: ...
    async def subscribe(self, topic: str, handler: Callable) -> None: ...
    async def unsubscribe(self, topic: str, handler: Callable) -> None: ...
```

### 18.2 TaskQueuePort

```python
class TaskQueuePort(ABC):
    async def enqueue(self, task_name: str, *args, **kwargs) -> str: ...
    async def get_result(self, job_id: str) -> Optional[dict]: ...
    async def get_status(self, job_id: str) -> str: ...
    async def cancel(self, job_id: str) -> bool: ...
```

### 18.3 v3 以来的所有 API（完整清单）

```
Plugin Management
├── GET    /plugins
├── GET    /plugins/{name}
├── POST   /plugins/{name}/enable
├── POST   /plugins/{name}/disable
├── POST   /plugins/reload
├── POST   /plugins/validate
└── GET    /plugins/capabilities/{capability}

Agent Research
├── POST   /research/start
├── GET    /research/{session_id}
├── GET    /research/{session_id}/plan
├── GET    /research/{session_id}/data
├── GET    /research/{session_id}/analysis
├── GET    /research/{session_id}/review
├── GET    /research/{session_id}/report
├── DELETE /research/{session_id}
├── GET    /research/history
└── WS     /ws/research/{session_id}

Scanner
├── POST   /scanner/run
├── GET    /scanner/results/latest
├── GET    /scanner/results/{date}
└── GET    /scanner/config

Signals
├── GET    /signals/list
├── POST   /signals/compute/{code}
├── POST   /signals/fusion/{code}
├── GET    /signals/fusion/top
└── PUT    /signals/weights

Research Pipeline
├── POST   /research/pipeline/run
├── GET    /research/pipeline/status
├── GET    /research/pipeline/runs
└── GET    /research/pipeline/reports/{date}

Metrics [Final新增]
├── GET    /metrics                     Prometheus /metrics 端点
├── GET    /metrics/snapshot            当前指标快照
├── GET    /metrics/daily/{date}        日度指标统计
└── GET    /metrics/costs               成本统计

Knowledge
├── GET    /knowledge/industries
├── GET    /knowledge/industries/{name}
├── GET    /knowledge/concepts
├── GET    /knowledge/glossary/{term}
└── POST   /knowledge/search

Compliance
├── GET    /compliance/datasources
├── GET    /compliance/audit-log
└── GET    /compliance/status

Market Data / Strategies / Trading / Backtest / Portfolio / Risk / System
（与 v2 一致）

WebSocket
├── WS  /ws                         实时行情推送
├── WS  /ws/research/{session_id}   Agent 研究进度
└── WS  /ws/events                  事件总线 Stream [Final新增]
```

---

## 19. 模块依赖图

```
                          ┌──────────┐
                          │  shared  │ ← plugin_protocol.py
                          └────┬─────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
    ┌──────────┐       ┌─────────────┐      ┌──────────────┐
    │  domain  │◄──────│ application │      │infrastructure│
    │          │       │             │      │              │
    │ models   │       │ use_cases   │      │ eventbus/    │ ← [Final]
    │ services │       │ dto         │      │ task_queue/  │ ← [Final]
    │ ports    │       │ handlers    │      │ metrics/     │ ← [Final]
    │ events   │       │ (事件处理)   │      │ plugin_      │
    └──────────┘       └─────────────┘      │  registry/   │
         ▲                                  │ agents/      │
         │                                  │ market_      │
         │         ┌───────────────┐        │  gateway/    │
         │         │    signals/   │        │ compliance/  │
         │         │ builtin/      │        │ adapters/    │
         │         │ custom/       │        └──────┬───────┘
         │         │ ml/           │               │
         │         │ fusion.py     │               │
         │         └───────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │    knowledge/      │               │
         │    │ (8 子目录)          │               │
         │    └────────────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │    plugins/        │               │
         │    │ datasource/*/     │               │
         │    └────────────────────┘               │
         │                                         │
         └─────────────────────────────────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │     api     │
                   └─────────────┘
```

**Event Bus 依赖关系**:
- EventBus 是基础设施，被所有模块使用
- domain/events/ 定义事件类型（纯数据结构）
- application/event_handlers/ 编排事件处理链
- 任何模块可以 `publish()` 和 `subscribe()`

---

## 20. 整体开发路线图（Roadmap Final）

```
Phase 0: 基础设施 (Week 1-2)
├── Poetry + ruff + mypy + pre-commit
├── plugin_protocol.py (BasePlugin/DataSourcePlugin/SignalPlugin)
├── EventBus 内存版 (eventbus/)
├── Metrics 内存版 (metrics/)
├── 目录结构 + .env + 配置骨架
├── loguru 日志 + 分类
├── SQLAlchemy ORM + 全量表
└── pytest + CI/CD

Phase 1: Plugin Registry (Week 3-4)
├── PluginRegistry (discover/register/validate/lifecycle)
├── plugin.yaml 格式规范 + 校验器
├── plugins/datasource/_template/
├── /plugins API (enable/disable/reload/validate)
└── 插件管理单元测试

Phase 2: Market Gateway (Week 5-7)
├── MarketGateway (从 Registry 获取适配器)
├── plugins/datasource/akshare/
├── plugins/datasource/tushare/
├── plugins/datasource/yahoo/
├── DataSourceCapability 能力路由
├── 数据清洗/验证/标准化管道
├── SQLite Repository
└── APScheduler 定时同步

Phase 3: Compliance (Week 8-9)
├── license_policies.yaml (独立许可配置)
├── LicenseChecker + CapabilityChecker
├── DataSourceValidator + RateLimiter
├── AuditLogger
├── 合规全链路拦截
└── /compliance API

Phase 4: Knowledge (Week 10-11)
├── KnowledgeBase 加载器
├── 8 个子目录首批 YAML
├── KnowledgeBasePort + API
└── Knowledge 搜索接口

Phase 5: Signals (Week 12-14)
├── SignalPlugin 协议
├── builtin/ (12 个信号)
├── custom/_template.py
├── ml/ (XGBoost/LightGBM 骨架)
├── SignalFusion 融合引擎
└── /signals API

Phase 6: Scanner (Week 15-16)
├── Scanner 三层管道
├── 粗筛 → 技术筛选 → 评分 → Top N
├── EventBus 集成
│   market.data.sync.completed → Scanner
│   Scanner → scanner.completed → SignalFusion
└── /scanner API

Phase 7: Research Pipeline (Week 17-18)
├── Task Queue (Arq) 部署
├── Research Pipeline (9步工作流)
├── 事件链: 数据同步 → Scanner → Signal → Agent → 报告 → 推送
├── 交易日历集成
└── /research/pipeline API

Phase 8: AI Agent Layer (Week 19-22)  ← 比 v3 更晚
├── BaseAgent 基类 + AgentContext
├── Planner / Researcher / Analyst / Reviewer / Reporter
├── AgentOrchestrator (4种协作模式)
├── Prompt 模板（每个 Agent 独立 System Prompt）
├── Agent ← LLM 解耦
├── Reviewer 幻觉检查 + 驳回循环
├── WebSocket Stream Agent 思考过程
└── /research API

Phase 9: FastAPI (Week 23-24)
├── FastAPI 应用工厂
├── 全部路由（含 /plugins /research /scanner /metrics /signals 等）
├── WebSocket (行情 + 研究进度 + 事件 Stream)
├── 认证中间件 + 限流中间件
└── API 集成测试

Phase 10: VSCode Extension (Week 25-27)
├── 插件框架 (TypeScript)
├── Sidebar: 股票列表 + 信号评分
├── Webview: K线图表
├── Panel: Agent 研究面板 + 研究历史
├── Status Bar: 实时行情 + 管线状态
├── Command: 一键发起研究
└── IPC 通信 (JSON-RPC)

Phase 11: Backtest + Trading (Week 28-31)
├── BaseStrategy + 内置策略
├── BacktestEngine + PerformanceCalculator
├── Order/Position/Account/Portfolio 模型
├── BrokerPort + SimNow Adapter
├── TradingEngine + RiskManager
└── /backtest /trading /portfolio /risk API

Phase 12: Notification (Week 32)
├── Email + WeChat 通知适配器
├── 事件驱动推送
│   research.agent.completed → 推送报告
│   risk.alert.triggered → 推送预警
└── /notification API

Phase 13: 测试 + 文档 + 发布 (Week 33-34)
├── 测试覆盖率 ≥ 80%
├── E2E 全流程: 数据同步 → Scanner → Signal → Agent → 报告 → 推送
├── Agent 评测基准 (幻觉率/准确率/Token效率)
├── Prometheus + Grafana Dashboard [Final]
├── API 文档 + 用户手册 + 部署文档
└── v1.0.0 发布

Phase 14: Web (后期)
└── React 前端
```

**Roadmap 设计原则**:

> Agent 越晚越好。
> 因为 Agent 依赖 Knowledge、Scanner、Signal、Pipeline。
> 这些没准备好之前，Agent 没有东西可分析。
> Phase 0 就把 EventBus/Metrics 骨架建好，后续模块直接复用。

---

## 附录A：架构演进历史

| 版本 | 核心贡献 |
|------|---------|
| **v1** | 分层+六边形架构、13表数据库、8模块API、8 Phase Roadmap |
| **v2** | MarketGateway统一网关、Compliance合规模块、Knowledge知识库、Signals信号引擎+融合、Scanner三层管道、Research Pipeline收盘工作流、数据伦理三层、VSCode纯UI |
| **v3** | Plugin Registry插件注册中心、AI Agent Layer(5 Agent协作)、DataSourceCapability能力声明+自动路由、Knowledge扩展8子目录、信号三层(builtin/custom/ml)、重新定位AI Research Terminal |
| **Final** | Event Bus事件驱动、Task Queue异步任务(Arq)、Metrics全链路监控、许可配置与插件技术能力分离、Roadmap重新排序(Agent→Phase 8) |

---

## 附录B：核心设计原则（最终版）

1. **AI 永远最后一步** — 负责解释，不负责计算
2. **Plugin 丢进去就识别** — MarketGateway 不知道有什么数据源，Registry 告诉它
3. **能力声明替代 if-else** — 数据源声明自己能做什么，系统自动路由
4. **技术能力与合规权限分离** — plugin.yaml 只管技术，license_policies.yaml 只管合规
5. **Agent 各司其职** — Planner 规划 / Researcher 收集 / Analyst 分析 / Reviewer 审查 / Reporter 报告
6. **Agent 与 LLM 解耦** — 每个 Agent 独立选模型，新增 LLM 无需改 Agent
7. **事件驱动解耦** — 模块不互相调用，通过 EventBus 通信
8. **Task Queue 异步化** — 绝不 for 循环处理大量任务
9. **全链路可观测** — Metrics 覆盖性能/成本/缓存/健康
10. **VSCode 纯 UI** — 迁移 Web 不改 Python
11. **知识库先于 AI** — 研报+产业链+政策+历史案例 > 裸问模型
12. **不内置破解** — 用户自配 Key，程序只提供插件框架
13. **AI Research Terminal** — AI 收集信息+融合信号+给出证据+提示风险，人做决策

---

> **架构冻结。进入 Phase 0：开始写代码。**
