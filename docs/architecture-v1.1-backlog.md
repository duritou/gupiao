# AI Research Terminal — v1.1 / v1.2 增强规划

> **状态**: Backlog  
> **v1.1**: Phase 0~12 期间逐步纳入  
> **v1.2**: Phase 12 之后  
> **前提**: v1.0 架构冻结，以下为演进方向，不阻塞 Phase 0 开发

---

## 版本路线

```
v1.0 (当前)       架构冻结，进入 Phase 0 开发
    │
    ├── v1.0 Patch   ① Domain/ORM 三层分离
    │                 ② Event 协议完整规范 (TraceContext + MessageEnvelope)
    │                 ③ Knowledge 基础设施移至 src/infrastructure/knowledge/
    │
    ├── v1.1 (P0~12) UoW / ContextEngine / ToolRegistry
    │                 CapabilityQuery / KnowledgeSearchPort
    │                 EpisodicMemory / PromptExperiment
    │                 DataSourceQualityScore / ScannerPipeline事件化
    │                 Domain Events / CQRS ReadModel / Research Snapshot
    │                 Workflow DSL / Agent Capability / Vector Memory
    │
    ├── v1.2 (P12后)  DI Container / Feature Flag / Policy Engine
    │                  Knowledge 格式抽象 / OpenTelemetry 兼容
    │                  Scanner → Pipeline Engine 抽象
    │                  Research Memory → Semantic/Episodic/Procedural
    │                  Command Bus / Metrics Collector 独立化
    │                  Prompt Lifecycle 完整化 / Knowledge 版本号
    │
    └── v2+            Query Model 完整版 / Pipeline → DAG
```

---

## 优先级排序

| 优先级 | 编号 | 增强项 | 影响范围 | 建议纳入时间 |
|--------|------|--------|---------|------------|
| P0 | ① | Unit of Work 事务边界 | Repository 层 | Phase 3 (Repository 实现时直接做) |
| ✅ | ② | Event Trace (TraceContext 独立封装) | Event Envelope | **已解决** (Event System Patch) |
| P1 | ⑩ | Context Engine (统一 AI 上下文构建) | Agent ↔ LLM | Phase 8 (Agent 层) |
| P1 | ⑦ | Tool Registry (Agent 工具插件化) | Agent Tools | Phase 8 (Agent 层) |
| P1 | ③ | Capability Query + Route Policy | Plugin Registry | Phase 2 (Gateway) |
| P2 | ④ | KnowledgeSearchPort (搜索后端解耦) | Knowledge | Phase 4 (Knowledge) |
| P2 | ⑤ | Episodic Memory | Research Memory | Phase 7 (Research Memory) |
| P2 | ⑥ | Prompt Experiment / A/B Testing | Prompt Registry | Phase 8 (Agent 层) |
| P2 | ⑧ | DataSource Quality Score + Route Policy | Plugin Registry | Phase 2 (Gateway) |
| P2 | ⑨ | Scanner Pipeline 细粒度事件化 | Scanner | Phase 6 (Scanner) |
| P3 | — | `orm/` → `storage/` 重命名 | 目录结构 | Phase 3 或更晚 |

---

## ① Unit of Work

**问题**: Repository 各自 commit，一个 UseCase 涉及多张表时无法保证事务一致性。

**方案**:

```python
# src/infrastructure/repositories/unit_of_work.py

class UnitOfWork:
    """事务边界 —— UseCase 通过它操作所有 Repository"""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

        # 所有 Repository 共享同一个 Session
        self.stocks: StockRepository | None = None
        self.signals: SignalRepository | None = None
        self.portfolios: PortfolioRepository | None = None
        self.memories: ResearchMemoryRepository | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        self.stocks = StockRepository(self._session)
        self.signals = SignalRepository(self._session)
        self.portfolios = PortfolioRepository(self._session)
        self.memories = ResearchMemoryRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self._session.rollback()
        else:
            await self._session.commit()
        await self._session.close()

# UseCase 使用
async def execute_trade_signal(signal: Signal, uow: UnitOfWork):
    async with uow:
        # 四张表在同一事务中
        await uow.signals.save(signal)
        await uow.portfolios.update_position(...)
        await uow.stocks.update_status(...)
        await uow.memories.remember(decision)
    # 全部成功 → commit | 任一失败 → rollback
```

---

## ② Event Trace（✅ 已通过 Event System Patch 解决）

**方案**: TraceContext 独立封装 — 已纳入 `architecture-v1.0-patch-event-system.md`。

```python
# 最终方案 (见 Event System Patch)
@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: str
    correlation_id: str
    # v1.2 预留: traceparent / tracestate / baggage

@dataclass(frozen=True)
class EventEnvelope(Generic[T]):
    metadata: EventMetadata
    trace: TraceContext      # ← 独立对象，不是平铺字段
    payload: T

# 使用
child = TraceContext.child(parent.trace)
forked = TraceContext.fork(parent.trace)
```

**状态**: ✅ 已在 Phase 0 前解决。无需额外工作。

---

## ③ Capability Query + Route Policy

**问题**: 业务代码不能 `if plugin.name == "akshare"`。

**方案**:

```python
# PluginRegistry 增强
class PluginRegistry:
    async def find_by_capability(
        self,
        capability: str,       # "supports_history"
        market: str = None,    # "CN" / "US" / "HK"
        realtime: bool = None,
    ) -> list[DataSourcePlugin]: ...

    async def find_best(
        self,
        capability: str,
        route_policy: RoutePolicy = None,  # quality_first / latency_first / cost_first
        **filters,
    ) -> DataSourcePlugin: ...
```

---

## ④ KnowledgeSearchPort

**问题**: 自己写全文索引是重复造轮子。

**方案**: 抽象 KnowledgeSearchPort，后端可插拔。

```python
class KnowledgeSearchPort(ABC):
    async def search(self, query: str, top_k: int = 10, category: str = None) -> list: ...
    async def index(self, entry: KnowledgeEntry) -> None: ...
    async def reindex_all(self) -> None: ...
    async def get_backend_info(self) -> dict: ...

# 后端实现
# Phase 0-4:  SQLite FTS5 (零依赖)
# Phase 8+:   Meilisearch / Elasticsearch / Vector DB (语义搜索)
```

---

## ⑤ Episodic Memory

**问题**: Research Memory 缺少"情节记忆"——Agent 在某个时间点的发现和判断。

**方案**:

```yaml
# research_memory/llm_memory/episodes/

- episode_id: "ep_20260705_001"
  date: "2026-07-05"
  agent: "analyst"
  title: "面板行业连续三周资金流入"
  summary: >
    经 Scanner 扫描和北向资金数据确认，面板行业
    (京东方A/TCL科技/深天马A) 连续三周北向资金净流入，
    累计超 50 亿。结合面板价格 Q3 涨价预期，
    决定将面板行业研究优先级提升至最高。
  decision: "提高面板行业整体研究优先级"
  confidence: 0.85
  evidence: ["北向资金连续流入数据", "面板报价趋势", "行业研报"]
  referenced_by: ["ep_20260801_003"]  # 后续 Episode 引用
```

---

## ⑥ Prompt Experiment / A/B Testing

**问题**: 新 Prompt 不应拍脑袋上线。

**方案**:

```python
class PromptExperiment:
    """Prompt A/B 测试"""

    variants: dict[str, float]  # {"v2": 0.7, "v3": 0.3}
    metrics: list[str]           # ["token", "latency", "hallucination", "score", "cost"]

    async def run(self, test_cases: list[dict]) -> ExperimentResult:
        """自动分流 → 收集指标 → 统计显著性检验 → 输出结论"""

    async def auto_activate(self, threshold: float = 0.95):
        """如果新版本显著优于旧版本 → 自动激活"""
```

---

## ⑦ Tool Registry

**问题**: Agent 的工具应该插件化，不能硬编码在 ToolProvider 里。

**方案**:

```python
# 工具注册
class ToolRegistry:
    async def register(self, tool: BaseTool): ...
    async def get_for_agent(self, agent_name: str) -> list[BaseTool]: ...
    async def get_schema_for_llm(self, tools: list[BaseTool]) -> list[dict]: ...

# 内置工具
class WeatherTool(BaseTool): ...     # 宏观环境
class FinancialTool(BaseTool): ...   # 财务数据查询
class NewsTool(BaseTool): ...        # 新闻搜索
class PythonTool(BaseTool): ...      # 代码执行（沙盒）
class KnowledgeTool(BaseTool): ...   # 知识库查询
class MemoryTool(BaseTool): ...      # Research Memory 查询
class SignalTool(BaseTool): ...      # 信号评分查询

# Agent 只调用 tool.call(...)，不关心实现
# 未来 MCP / Function Calling / Agent SDK 全部无痛接入
```

---

## ⑧ DataSource Quality Score

**问题**: 有多个数据源支持同一能力时，系统不知道选哪个。

**方案**:

```yaml
# plugin.yaml 增加 quality 字段

capabilities:
  supports_history: true
  ...
  quality:                          # ⑧ v1.1
    score: 80                       # 综合质量分 0-100
    latency_ms: 100                 # 平均延迟
    availability: 0.995             # 可用性 SLA
    cost_per_request: 0             # 单次请求成本 (USD)
    data_freshness: "t+0"           # 数据新鲜度
```

```python
# Route Policy
class RoutePolicy(Enum):
    QUALITY_FIRST = "quality_first"       # 质量优先
    LATENCY_FIRST = "latency_first"       # 延迟优先
    COST_FIRST = "cost_first"             # 成本优先
    BALANCED = "balanced"                 # 综合平衡

# 自动路由
best = await registry.find_best(
    capability="supports_history",
    route_policy=RoutePolicy.QUALITY_FIRST,
    market="CN",
)
# → 在支持 CN 市场历史数据的插件中，选 quality.score 最高的
```

---

## ⑨ Scanner Pipeline 细粒度事件化

**问题**: Scanner 是一个黑盒，无法在中间阶段插入逻辑。

**方案**:

```
scanner.started
    │
    ▼
coarse_filter.started → coarse_filter.completed  (5000 → 2000)
    │
    ▼
technical_filter.started → technical_filter.completed  (2000 → 100)
    │
    ▼
    [插件插入点] ← 例如 SentimentPlugin 在这里执行
    │
    ▼
signal_scoring.started → signal_scoring.completed  (100 只有分数)
    │
    ▼
candidate.created (每个候选标的) × N
    │
    ▼
candidate.persisted
    │
    ▼
scanner.completed
```

---

## ⑩ Context Engine

**问题**: AI 的上下文构建逻辑散落在各个 Agent 中，Token 预算、RAG、裁剪逻辑重复。

**方案**:

```
Agent
    │
    ▼
┌──────────────────────────────────────────────┐
│              Context Engine                   │
│                                               │
│  输入: AgentRequest + Token Budget            │
│                                               │
│  ┌─────────────────────────────────────────┐ │
│  │ 1. Knowledge Selector                   │ │
│  │    从 Knowledge 检索相关上下文            │ │
│  │ 2. Memory Retriever                     │ │
│  │    从 Research Memory 检索相关记忆        │ │
│  │ 3. Signal Aggregator                    │ │
│  │    从 Signals 获取最新评分                │ │
│  │ 4. News/Event Selector                  │ │
│  │    从 News 检索相关事件                   │ │
│  │ 5. Context Assembler                    │ │
│  │    组装 → 按优先级排序 → Token 预算裁剪    │ │
│  │ 6. Prompt Renderer                      │ │
│  │    Jinja2 渲染 → 最终 Prompt              │ │
│  └─────────────────────────────────────────┘ │
│                                               │
│  输出: 优化后的 Messages[] + Token 分配报告     │
└──────────────────────────────────────────────┘
    │
    ▼
  LLM
```

---

## orm/ → storage/ 重命名

```
当前:
  infrastructure/
    repositories/   (纯接口)
    orm/             (不准确——DuckDB/ClickHouse 不是 ORM)
      sqlite/
      postgresql/
      duckdb/
      clickhouse/

v1.1:
  infrastructure/
    repositories/   (纯接口)
    storage/         (更准确的语义)
      backends/
        sqlite/
        postgresql/
        duckdb/
        clickhouse/
```

---

## ⑫ v1.1 新增项（来自最终评审）

---

### (N) Domain Event 与 Integration Event 分离

**问题**: 所有事件共用 `EventEnvelope`，Domain Event 和 Infrastructure Event 混在一起。

**方案**: 在 Event System Patch 的 `events/domain/` 和 `events/infrastructure/` 目录分离基础上，进一步约定：

| | Domain Event | Integration Event |
|---|---|---|
| 目录 | `events/domain/` | `events/infrastructure/` |
| 语义 | 业务事实 | 系统通知 |
| 生产者 | UseCase | Scanner / Pipeline / Scheduler |
| 消费者 | Notification / Metrics / Audit / Memory | 其他系统模块 |
| 持久化 | 需要（审计） | 不需要 |
| 示例 | `SignalCreated` | `scanner.completed` |

---

### (O) CQRS (读写分离)

**问题**: Repository 同时负责读和写，复杂查询性能受限。

**方案**:

```python
# Write (不变)
class StockRepository(RepositoryPort[Stock]): ...

# Read (新增 — v1.1)
class SignalReadModel:
    async def get_top_signals(self, date, industry=None, top_k=20) -> list[SignalView]: ...
    async def get_score_trajectory(self, stock_code, days=90) -> list[ScorePoint]: ...

class TimelineReadModel:
    async def get_research_timeline(self, stock_code) -> list[TimelineEntry]: ...

class DashboardReadModel:
    async def get_daily_summary(self, date) -> DashboardView: ...
```

---

### (P) Research Snapshot

**问题**: Memory 越来越多，无法恢复某个时刻的完整上下文。

**方案**:

```python
class ResearchSnapshot:
    """研究会话快照 —— 完整上下文存档"""

    async def capture(self, session_id: str) -> Snapshot:
        """捕获当前会话的完整状态:
        - Agent 状态
        - 上下文数据
        - Signal 评分
        - Knowledge 版本
        - Prompt 版本
        """

    async def restore(self, snapshot_id: str) -> ResearchContext:
        """恢复快照 → 用于 Debug / 审计 / 复盘"""

    async def diff(self, snap1: str, snap2: str) -> SnapshotDiff:
        """对比两次快照 → 理解 AI 行为变化原因"""
```

---

### (Q) Workflow DSL

**问题**: Pipeline 步骤硬编码在 Python 中（for/if/else），步骤增多后难以维护。

**方案**:

```yaml
# config/workflows/daily_research.yaml
workflow:
  name: daily_research
  trigger: "market.close"
  steps:
    - id: sync_data
      type: parallel
      tasks: [sync_kline, sync_lhb, sync_news, sync_capital]
    
    - id: scanner
      depends_on: [sync_data]
      type: pipeline
      stages: [coarse_filter, technical_filter, scoring]
    
    - id: agent_research
      depends_on: [scanner]
      type: agent
      agent: planner
      next: [analyst]
    
    - id: notification
      depends_on: [agent_research]
      type: notify
      channels: [vscode, email]
```

Workflow Engine 解析 YAML → 执行 DAG，替代硬编码。

---

### (R) Agent Capability 声明

**问题**: `if agent.name == "planner"` 散落各处。

**方案**: 每个 Agent 声明自己的能力。

```python
class PlannerAgent(BaseAgent):
    capabilities = [
        AgentCapability.PLAN,
        AgentCapability.SCHEDULE,
        AgentCapability.DELEGATE,
    ]

class ResearcherAgent(BaseAgent):
    capabilities = [
        AgentCapability.SEARCH,
        AgentCapability.QUERY_KNOWLEDGE,
        AgentCapability.FETCH_DATA,
    ]

# Orchestrator 按能力匹配 Agent，不用 if-else
agent = orchestrator.find_agent_with(AgentCapability.SEARCH)
```

---

### (S) Vector Memory

**问题**: Memory 基于 JSON 存储，无法语义搜索。

**方案**:

```python
class VectorMemoryStore:
    """向量记忆存储 —— v1.1 可选，v2.0 默认"""

    async def embed_and_store(self, entry: ResearchMemoryEntry) -> None:
        """Embedding → Vector Index"""

    async def semantic_search(self, query: str, top_k: int = 5) -> list[ResearchMemoryEntry]:
        """语义搜索 → '以前有没有和宁德时代类似的案例？'"""

    async def hybrid_search(self, query: str, filters: dict, top_k: int = 5):
        """混合搜索: 语义 + 过滤条件"""
```

Phase 0-7: JSON (简单)  
Phase 8+: Vector (语义)

---

## ⑪ Domain Events（领域事件层）

**问题**: 当前 Event Bus 只有 Infrastructure Event（`scanner.started`），缺少能表达业务事实的 Domain Event。

**方案**: 增加一层 Domain Event，Infrastructure Event 是"系统通知"，Domain Event 是"业务事实"。

```
Application UseCase
    │
    ├── 发布 Domain Event (业务事实)
    │   SignalCreated / ResearchCompleted / PortfolioUpdated
    │   WatchlistAdded / KnowledgeImported / MemoryRecorded
    │
    ▼
EventBus
    │
    ├── Notification   (Domain Event → 推送)
    ├── Metrics         (Domain Event → 指标记录)
    ├── Audit           (Domain Event → 审计日志)
    └── Memory          (Domain Event → Research Memory)
```

```python
# src/domain/events/domain_events.py

@dataclass
class SignalCreated:
    """领域事件: 新信号已生成"""
    signal_id: str
    stock_code: str
    signal_type: str    # macd / rsi / capital / ...
    score: float
    direction: str

@dataclass
class ResearchCompleted:
    """领域事件: 研究已完成"""
    session_id: str
    stock_code: str
    conclusion: str
    confidence: float
    report_path: str

@dataclass
class PortfolioUpdated:
    """领域事件: 组合已变更"""
    account_id: str
    change_type: str    # rebalance / add_position / reduce_position
    details: dict
```

Infrastructure Event vs Domain Event 对比:

| | Infrastructure Event | Domain Event |
|---|---|---|
| 语义 | 系统通知 | 业务事实 |
| 示例 | `scanner.started` | `SignalCreated` |
| 生产者 | Scanner/Pipeline | UseCase |
| 消费者 | 其他系统模块 | Notification / Metrics / Audit / Memory |
| 持久化 | 不需要 | 需要（审计） |

---

## v1.2 新增项

---

### (H) Command Bus

**问题**: Agent 越来越多后，Agent 直接调 UseCase → 耦合。

**方案**: Command → CommandBus → Handler → Repository。

```python
# 命令定义
@dataclass
class RunResearchCommand:
    stock_code: str
    analysis_depth: str = "comprehensive"

@dataclass
class UpdateWatchlistCommand:
    stock_code: str
    action: str          # add / remove
    reason: str

# Command Bus
class CommandBus:
    async def dispatch(self, command: Any) -> Any:
        handler = self._resolve_handler(type(command))
        return await handler.handle(command)

# Agent 只发命令，不知道 UseCase
result = await command_bus.dispatch(RunResearchCommand(
    stock_code="000725.SZ",
))
```

效果: Agent → CommandBus → Handler → UseCase → Repository。Agent 与 UseCase 完全解耦。

---

### (I) Metrics Collector 独立化

**问题**: Metrics 散落在各处，缺乏统一的采集器。

**方案**: `MetricsCollector` 作为独立基础设施，覆盖全链路。

```python
class MetricsCollector:
    """统一指标采集器"""

    # LLM 指标
    def record_llm_call(self, model: str, tokens: int, latency_ms: int, cost: float): ...
    def record_llm_error(self, model: str, error: str): ...

    # Plugin 指标
    def record_plugin_call(self, plugin: str, duration_ms: int): ...

    # Scanner 指标
    def record_scanner_stage(self, stage: str, count: int, duration_ms: int): ...

    # Knowledge 指标
    def record_knowledge_search(self, query: str, results: int, duration_ms: int): ...

    # Memory 指标
    def record_memory_hit(self, memory_type: str): ...
    def record_memory_miss(self, memory_type: str): ...

    # Prompt 指标
    def record_prompt_version(self, name: str, version: str): ...

    # Cache 指标
    def record_cache_hit(self, cache_level: str): ...
    def record_cache_miss(self, cache_level: str): ...

    # RAG 指标
    def record_rag_recall(self, query: str, chunks: int, relevant: int): ...

    # 导出
    def snapshot(self) -> dict: ...     # 当前快照
    def to_prometheus(self) -> str: ... # Prometheus 格式
```

Dashboard 全部从 MetricsCollector 消费。

---

### (J) Prompt Lifecycle 完整化

**问题**: Prompt 没有生命周期管理。

**方案**:

```
Draft → Review → Approved → Active → Deprecated
  │                            │
  └────────────────────────────┘
         直接废弃
```

```python
class PromptLifecycle:
    VALID_TRANSITIONS = {
        "draft":      ["review", "deprecated"],
        "review":     ["approved", "draft"],
        "approved":   ["active", "deprecated"],
        "active":     ["deprecated"],
        "deprecated": [],
    }

    def transition(self, prompt_name: str, from_state: str, to_state: str, 
                   approved_by: str = "", reason: str = "") -> None: ...
```

---

### (K) Knowledge 版本号

**问题**: 知识库内容不断更新，无法追踪变更。

**方案**: 每个 `KnowledgeDocument` 带版本元数据。

```python
@dataclass
class KnowledgeDocument:
    id: str
    title: str
    content: str
    version: int = 1
    checksum: str = ""            # SHA256
    parent_version: int | None = None  # 上一版本
    published_at: datetime | None = None
    updated_at: datetime | None = None
    source_url: str = ""          # 原始来源
```

用途:
- 重新 Embedding 时只处理版本变化的文档
- 重新 Index 时增量更新
- 回滚到历史版本
- 审计知识变更

---

## v2+ 远期规划

---

### (L) Query Model / CQRS

**时机**: Phase 10 以后。**现在千万不要做。**

```
当前 (v1.x):
  Repository 同时负责读和写

未来 (v2+):
  Write Model → Repository → Database
  Read Model  → ViewRepository → 优化的查询

ViewRepository 示例:
  SignalView:      预聚合的信号排名（按日期/行业/分数）
  PortfolioView:   组合快照（含历史对比）
  TimelineView:    研究时间线（跨表关联）
  DashboardView:   Dashboard 聚合数据
```

---

### (M) Pipeline → DAG

**时机**: v2 以后。**现在不需要。**

```
当前:
  Stage1 → Stage2 → Stage3 (线性)

未来:
      A
    ┌─┼─┐
    B C D
    └─┼─┘
    Merge
      │
    Score
      │
  Candidate
```

适用场景: 多维度并行分析（技术面/基本面/资金面 同时跑 → 合并评分）。

---

### (A) Dependency Injection Container

**问题**: 对象多了以后，手动注入失控。

```python
# 反模式
pipeline = ResearchPipeline(
    stock_repo,
    signal_repo,
    memory_repo,
    knowledge_base,
    prompt_registry,
    event_bus,
    metrics,
    logger,
)
```

**方案**:

```python
# 声明式注入
class ResearchPipeline:
    def __init__(
        self,
        stock_repo: StockRepository = Inject(),
        signal_repo: SignalRepository = Inject(),
        memory_repo: ResearchMemoryRepository = Inject(),
        knowledge: KnowledgeBasePort = Inject(),
        prompts: PromptRegistryPort = Inject(),
        eventbus: EventBusPort = Inject(),
        metrics: MetricsCollector = Inject(),
    ): ...

# 容器自动解析
pipeline = container.resolve(ResearchPipeline)
```

技术选型: `punq` / `python-dependency-injector` / `rodi` — 轻量优先。

---

### (B) Feature Flag

**问题**: `if DEV:` / `if TEST:` 散落代码各处。

**方案**:

```yaml
# config/features.yaml
features:
  scanner_v2: false           # Scanner 新版（灰度中）
  context_engine: true        # Context Engine 已全量
  new_memory_backend: false   # 新记忆后端（实验）
  prompt_ab_testing: false    # Prompt A/B 测试
```

```python
if feature_flag.is_enabled("scanner_v2", user_id=request.user_id):
    return await scanner_v2.run()
else:
    return await scanner_v1.run()
```

---

### (C) Policy Engine

**问题**: Compliance / License / Capability 三个模块各自判断权限。

**方案**: 统一 Policy Engine。

```python
class PolicyEngine:
    """统一策略引擎"""

    async def evaluate(
        self,
        subject: str,       # "user_001" / "agent:analyst"
        action: str,        # "can_run_research" / "can_use_plugin" / "can_trade"
        resource: str,      # "plugin:akshare" / "stock:000725.SZ"
        context: dict,      # 额外上下文
    ) -> PolicyDecision:
        """评估策略 → 返回 allow/deny/warn + 原因"""
```

适用场景:
- 免费版 vs 企业版功能限制
- 不同用户的数据源使用权限
- AI Agent 的操作边界控制
- 数据导出/分发权限

---

### (D) Knowledge 格式抽象

**问题**: Loader 与 YAML 绑定，未来加入 PDF 研报需改 Loader。

**方案**: 统一 `KnowledgeDocument` 中间表示。

```python
@dataclass
class KnowledgeDocument:
    """知识文档 —— 格式无关的中间表示"""
    id: str
    title: str
    category: str             # industry / macro / report / paper / ...
    source_format: str        # yaml / markdown / pdf / html / ...
    source_path: str
    content: str              # 纯文本（已解析）
    metadata: dict
    chunks: list[dict]        # RAG 分块
    embedded_at: datetime | None

class KnowledgeLoader(ABC):
    """加载器 —— 每种格式一个实现"""
    @abstractmethod
    async def load(self, path: str) -> KnowledgeDocument: ...

class YamlLoader(KnowledgeLoader): ...
class MarkdownLoader(KnowledgeLoader): ...
class PDFLoader(KnowledgeLoader): ...      # 未来
class WebLoader(KnowledgeLoader): ...      # 未来
```

---

### (E) Event Bus ↔ OpenTelemetry 兼容

**方案**: TraceContext 已预留 `traceparent`/`tracestate` 字段（v1.2 启用）。

```python
# 当前 (v1.0 Event System Patch — 已预留)
@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: str
    correlation_id: str
    # v1.2 启用:
    traceparent: str = ""       # W3C traceparent header
    tracestate: str = ""        # W3C tracestate header
    sampled: bool = True

# v1.2: 启用 traceparent/tracestate 后，Grafana/Jaeger/Tempo 直接识别
# EventEnvelope 完全不用动
```

---

### (F) Scanner → Pipeline Engine 抽象

**问题**: Scanner 的管道逻辑只服务股票扫描。

**方案**: Scanner 变成通用 Pipeline Engine。

```python
class PipelineStage(ABC):
    @abstractmethod
    async def process(self, items: list[Any], context: dict) -> list[Any]: ...

class CoarseFilter(FilterStage): ...
class TechnicalFilter(FilterStage): ...
class ScoreStage(RankStage): ...
class PluginStage(PipelineStage): ...      # 用户/社区插件插入点

class PipelineEngine:
    """通用管道引擎 —— 股票/ETF/期货/数字货币全部可用"""

    def __init__(self, stages: list[PipelineStage]): ...

    async def run(self, items: list[Any], context: dict) -> list[Any]:
        for stage in self.stages:
            items = await stage.process(items, context)
        return items
```

---

### (G) Research Memory 认知三层升级

```
当前 (v1.0):
  watchlist / decision / journal / summary / episode

v1.2 升级 → 认知三层:

  Semantic Memory (语义记忆)
    · "面板行业历史上 Q3 上涨概率 65%"
    · "这种技术形态在过去 100 次中出现后，胜率 42%"
    · 从大量 Episode 中提炼的统计规律

  Episodic Memory (情节记忆)
    · "2026-05-05 第一次发现京东方A MACD 金叉"
    · 你当前已有 → 继续完善

  Procedural Memory (程序记忆)
    · "如何分析半导体行业: Step1→Step2→..."
    · "如何评估一只银行股: checklist → scoring → report"
    · Agent 的分析流程知识
```

---

## 架构成熟度评估

| 能力 | v1.0 | + v1.1 | + v1.2 |
|------|------|--------|--------|
| 分层架构 | 10 | 10 | 10 |
| Domain 纯度 | 8.5 | 9.5 | **10** |
| 插件体系 | 10 | 10 | 10 |
| Agent 设计 | 9.5 | 10 | 10 |
| 可维护性 | 9.5 | 10 | 10 |
| 可扩展性 | 10 | 10 | 10 |
| 可观测性 | 8 | 9.5 | **10** |
| Prompt 管理 | 10 | 10 | 10 |
| Knowledge | 9.5 | 10 | 10 |
| Repository | 8.5 | 9.5 | **10** |
| **总体** | **9.2** | **9.7-9.8** | **~10** |

---

> **v1.0 架构冻结。Phase 0 开始。**
> **v1.1 在 Phase 0~12 逐步纳入。**
> **v1.2 在正式发布后启动。**
