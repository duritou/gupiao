# AI Research Terminal — 架构设计文档 Final v1.0

> **版本**: Final v1.0 (Patch)  
> **日期**: 2026-07-05  
> **定位**: AI 股票研究终端（非 AI 选股工具）  
> **状态**: 🔒 架构冻结 — 进入 Phase 0 开发

---

## Patch Notes（v1.0 相对 Final 草稿）

| # | 变更 | 类型 |
|---|------|------|
| ① | Repository 抽象层与 ORM 实现分离（sqlite/postgres/duckdb/clickhouse） | 重构 |
| ② | Knowledge 热加载（loader/indexer/search/watcher） | 新增 |
| ③ | Plugin 版本约束（api_version/minimum_core/maximum_core） | 新增 |
| ④ | Event 结构化信封（version/event_id/timestamp/producer/payload） | 新增 |
| ⑤ | Prompt Registry（版本/热更新/缓存/回滚） | 新增 |
| ⑥ | Scanner 输出 ResearchCandidate（替代硬编码 Top20） | 重构 |
| ⑦ | Roadmap 重排（Repository→P3, VSCode→P10） | 调整 |
| ⑧ | 数据获取伦理原则 + 统一 DataSourcePlugin 接口 | 新增 |
| ⑨ | Research Memory 研究记忆模块 | 新增 |
| ⑩ | 许可配置运维提醒 | 完善 |

---

## 目录

1. [定位宣言](#1-定位宣言)
2. [项目总体架构](#2-项目总体架构)
3. [完整目录结构](#3-完整目录结构)
4. [模块职责](#4-模块职责)
   - 4.1 [Repository 抽象层](#41-repository-抽象层-①)
   - 4.2 [Knowledge 热加载](#42-knowledge-热加载-②)
   - 4.3 [Plugin 版本约束](#43-plugin-版本约束-③)
   - 4.4 [Event 结构化信封](#44-event-结构化信封-④)
   - 4.5 [Prompt Registry](#45-prompt-registry-⑤)
   - 4.6 [Research Candidate](#46-research-candidate-⑥)
   - 4.7 [Research Memory](#47-research-memory-⑨)
   - 4.8 [数据获取伦理原则](#48-数据获取伦理原则-⑧)
5. [数据库设计](#5-数据库设计)
6. [数据流设计](#6-数据流设计)
7. [AI Agent 层设计](#7-ai-agent-层设计)
8. [Plugin Registry 设计](#8-plugin-registry-设计)
9. [配置管理](#9-配置管理)
10. [接口设计](#10-接口设计)
11. [模块依赖图](#11-模块依赖图)
12. [整体开发路线图](#12-整体开发路线图roadmap)
13. [附录](#13-附录)

---

## 1. 定位宣言

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│   ❌ 不是: AI 选股工具                                        │
│   ✅ 是:  AI Research Terminal (AI 股票研究终端)               │
│                                                               │
│   AI 收集信息 → 信号融合 → 给出证据 → 提示风险                  │
│   最终交易决策: 人                                             │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 项目总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                    表示层 (Presentation Layer)                         │
│  ┌─────────────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│  │   VS Code 插件       │  │   Web 前端    │  │   CLI 命令行      │     │
│  │   (纯 UI，P10 开发)   │  │   (后期)      │  │   (后期)          │     │
│  └─────────┬───────────┘  └──────┬───────┘  └────────┬─────────┘     │
└────────────┼─────────────────────┼───────────────────┼───────────────┘
             └─────────────────────┼───────────────────┘
                                   │ REST / WebSocket / IPC
┌──────────────────────────────────┼───────────────────────────────────┐
│                    应用层 · 领域层                                     │
│  ┌───────────────────────────────┴──────────────────────────────────┐ │
│  │  API 网关 · Use Cases · Domain Services · Ports · Events         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    基础设施层                                          │
│                                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │Event Bus │ │Task Queue│ │ Metrics  │ │ Plugin   │ │ Prompt   │  │
│  │          │ │  (Arq)   │ │          │ │ Registry │ │ Registry │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────────┐  │
│  │ AI Agent │ │Compliance│ │Research  │ │ Repository 抽象层       │  │
│  │  Layer   │ │          │ │ Memory   │ │ (sqlite/pg/duckdb/...)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Market Gateway · Signals · Knowledge · Cache                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    插件层                                              │
│  plugins/datasource/*/    plugins/signal/*/                           │
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
├── pyproject.toml
├── poetry.lock
├── README.md
├── CHANGELOG.md
├── Makefile
│
├── docs/
│   ├── architecture-final-v1.0.md    # ← 你在这里
│   ├── architecture-final.md         #   上一版留档
│   ├── architecture-v3.md
│   ├── architecture-v2.md
│   └── architecture-v1.md
│
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── database.py
│   ├── ai_models.py
│   ├── plugin_registry.py
│   ├── event_topics.py
│   ├── task_queue.py
│   ├── metrics.py
│   ├── logging.yaml
│   ├── license_policies.yaml          # ⚠️ 运维数据，需定期人工审核
│   ├── prompts/                       # Agent System Prompts
│   │   ├── registry.yaml              #   Prompt 注册表
│   │   ├── versions/                  #   版本化 Prompt 存储
│   │   └── templates/                 #   Jinja2 模板
│   └── brokers/
│
├── src/
│   ├── __init__.py
│   │
│   ├── domain/
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
│   │   │   ├── research_candidate.py      # ① Research Candidate 实体
│   │   │   ├── research_memory.py         # ⑨ 研究记忆实体
│   │   │   ├── agent_task.py
│   │   │   ├── plugin_manifest.py
│   │   │   ├── datasource_capability.py
│   │   │   ├── ai_analysis.py
│   │   │   ├── risk.py
│   │   │   ├── indicator.py
│   │   │   ├── compliance_record.py
│   │   │   └── enums.py
│   │   ├── services/
│   │   │   ├── trading_engine.py
│   │   │   ├── signal_fusion_engine.py
│   │   │   ├── risk_manager.py
│   │   │   ├── portfolio_optimizer.py
│   │   │   ├── scanner_engine.py          # ① 输出 ResearchCandidate
│   │   │   ├── backtest_engine.py
│   │   │   ├── agent_orchestrator.py
│   │   │   └── research_pipeline.py
│   │   ├── ports/
│   │   │   ├── market_gateway_port.py
│   │   │   ├── ai_provider_port.py
│   │   │   ├── broker_port.py
│   │   │   ├── cache_port.py
│   │   │   ├── repository_port.py         # ① 泛型仓储端口（与 ORM 解耦）
│   │   │   ├── notification_port.py
│   │   │   ├── compliance_port.py
│   │   │   ├── knowledge_base_port.py
│   │   │   ├── plugin_registry_port.py
│   │   │   ├── event_bus_port.py
│   │   │   ├── task_queue_port.py
│   │   │   ├── prompt_registry_port.py    # ⑤ Prompt Registry 端口
│   │   │   └── research_memory_port.py    # ⑨ 研究记忆端口
│   │   └── events/
│   │       ├── __init__.py
│   │       ├── base_event.py              # ④ Event 信封基类
│   │       ├── market_events.py
│   │       ├── signal_events.py
│   │       ├── scanner_events.py
│   │       ├── research_events.py
│   │       ├── trading_events.py
│   │       ├── agent_events.py
│   │       └── risk_events.py
│   │
│   ├── application/
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
│   │       ├── signal_handlers.py
│   │       ├── scanner_handlers.py
│   │       ├── research_handlers.py
│   │       ├── trading_handlers.py
│   │       └── risk_handlers.py
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   │
│   │   ├── eventbus/
│   │   │   ├── bus.py
│   │   │   ├── publisher.py
│   │   │   ├── subscriber.py
│   │   │   └── middleware.py
│   │   │
│   │   ├── task_queue/
│   │   │   ├── broker.py
│   │   │   ├── tasks.py
│   │   │   ├── worker.py
│   │   │   └── scheduler.py
│   │   │
│   │   ├── metrics/
│   │   │   ├── collector.py
│   │   │   ├── prometheus.py
│   │   │   └── dashboard.py
│   │   │
│   │   ├── plugin_registry/
│   │   │   ├── registry.py
│   │   │   ├── loader.py
│   │   │   ├── validator.py              # ③ 版本约束校验
│   │   │   ├── lifecycle.py
│   │   │   └── metadata.py
│   │   │
│   │   ├── prompt_registry/              # ⑤ Prompt Registry
│   │   │   ├── __init__.py
│   │   │   ├── registry.py               #   Prompt 注册表
│   │   │   ├── version_manager.py        #   版本管理
│   │   │   ├── hot_reloader.py           #   热更新
│   │   │   ├── cache.py                  #   Prompt 缓存
│   │   │   └── rollback.py               #   回滚
│   │   │
│   │   ├── adapters/
│   │   │   ├── market_gateway/
│   │   │   │   ├── gateway.py
│   │   │   │   ├── base.py               # ⑧ DataSourcePlugin 统一接口
│   │   │   │   └── factory.py
│   │   │   ├── ai_providers/
│   │   │   ├── brokers/
│   │   │   └── notifications/
│   │   │
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── planner.py
│   │   │   ├── researcher.py
│   │   │   ├── analyst.py
│   │   │   ├── reviewer.py
│   │   │   ├── reporter.py
│   │   │   ├── context_builder.py
│   │   │   └── tool_provider.py
│   │   │
│   │   ├── compliance/
│   │   │   ├── datasource_policy.py
│   │   │   ├── datasource_validator.py
│   │   │   ├── license_checker.py         # 读取 license_policies.yaml
│   │   │   ├── capability_checker.py
│   │   │   ├── rate_limit.py
│   │   │   └── audit_logger.py
│   │   │
│   │   ├── repositories/                  # ① 纯接口，不含 ORM 细节
│   │   │   ├── __init__.py
│   │   │   ├── base.py                    #   泛型 Repository 基类
│   │   │   ├── stock_repository.py        #   StockRepository (抽象)
│   │   │   ├── market_data_repository.py
│   │   │   ├── strategy_repository.py
│   │   │   ├── signal_repository.py
│   │   │   ├── order_repository.py
│   │   │   ├── portfolio_repository.py
│   │   │   ├── report_repository.py       #   AI分析报告 Repository
│   │   │   ├── research_memory_repository.py  # ⑨
│   │   │   └── task_repository.py
│   │   │
│   │   ├── orm/                           # ① ORM 实现（按数据库分）
│   │   │   ├── __init__.py
│   │   │   ├── base.py                    #   ORM 基类
│   │   │   ├── sqlite/                    #   SQLite 实现
│   │   │   │   ├── __init__.py
│   │   │   │   ├── stock_orm.py
│   │   │   │   ├── market_data_orm.py
│   │   │   │   └── ...
│   │   │   ├── postgresql/                #   PostgreSQL 实现
│   │   │   │   └── ...
│   │   │   ├── duckdb/                    #   DuckDB 实现（未来）
│   │   │   │   └── ...
│   │   │   └── clickhouse/               #   ClickHouse 实现（未来）
│   │   │       └── ...
│   │   │
│   │   ├── research_memory/               # ⑨ Research Memory
│   │   │   ├── __init__.py
│   │   │   ├── store.py                   #   记忆存储
│   │   │   ├── query.py                   #   记忆检索
│   │   │   ├── decay.py                   #   记忆衰减/权重
│   │   │   └── sync.py                    #   记忆同步
│   │   │
│   │   ├── cache/
│   │   └── external/
│   │
│   ├── signals/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── fusion.py
│   │   ├── builtin/  (12 signals)
│   │   ├── custom/_template.py
│   │   └── ml/  (xgboost/lightgbm)
│   │
│   ├── api/
│   │   ├── app.py
│   │   ├── dependencies.py
│   │   ├── middleware/
│   │   └── routes/
│   │       ├── plugin_routes.py
│   │       ├── research_routes.py
│   │       ├── metrics_routes.py
│   │       ├── prompt_routes.py           # ⑤ Prompt 管理
│   │       ├── memory_routes.py           # ⑨ 研究记忆查询
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
│   ├── datasource/
│   │   ├── akshare/
│   │   │   ├── plugin.yaml
│   │   │   └── adapter.py
│   │   ├── tushare/
│   │   │   ├── plugin.yaml
│   │   │   └── adapter.py
│   │   └── _template/
│   └── signal/_template/
│
├── knowledge/
│   ├── loader.py                          # ② 知识加载器
│   ├── indexer.py                         # ② 知识索引器
│   ├── search.py                          # ② 知识搜索
│   ├── watcher.py                         # ② 文件监控（热加载）
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
├── research_memory/                       # ⑨ 研究记忆（持久化数据）
│   ├── market_context/                    #   市场环境快照
│   ├── watchlist/                         #   观察列表历史
│   ├── daily_summary/                     #   日度总结
│   ├── trade_journal/                     #   交易日志
│   ├── decision_log/                      #   决策记录
│   ├── strategy_history/                  #   策略变更历史
│   └── llm_memory/                        #   LLM 对话记忆
│
├── tests/
├── scripts/
├── vscode-ext/
├── web/
├── deploy/
└── data/
```

---

## 4. 模块职责

### 4.1 Repository 抽象层 ①

**问题**: 之前 repositories/ 直接写 SQLite 实现，换数据库需改所有 Repository。

**方案**: Repository 接口与 ORM 实现严格分离。

```
┌──────────────────────────────────────────────────────────────┐
│               Repository 抽象层                               │
│                                                               │
│  业务代码 (Use Cases / Domain Services)                        │
│       │                                                       │
│       │  只依赖 RepositoryPort (抽象接口)                       │
│       │  永远不 import orm/ 中的任何类                          │
│       ▼                                                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  src/infrastructure/repositories/  (纯抽象)               │ │
│  │                                                          │ │
│  │  stock_repository.py                                     │ │
│  │  class StockRepository(RepositoryPort[Stock]):           │ │
│  │      def __init__(self, session: AsyncSession):          │ │
│  │          self._session = session  # 任何兼容的 Session    │ │
│  │                                                          │ │
│  │      async def find_by_code(self, code: str) -> Stock:   │ │
│  │          # 调用 self._session，不关心底层是什么数据库     │ │
│  │          ...                                             │ │
│  │                                                          │ │
│  │  特点: 不含任何 from orm.sqlite import ...               │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       │  Repository 通过 Session 与 ORM 通信                   │
│       ▼                                                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  src/infrastructure/orm/  (数据库实现)                    │ │
│  │                                                          │ │
│  │  sqlite/       → SQLAlchemy models for SQLite            │ │
│  │  postgresql/   → SQLAlchemy models for PostgreSQL        │ │
│  │  duckdb/       → DuckDB (OLAP 分析)                      │ │
│  │  clickhouse/   → ClickHouse (时序/大规模数据)             │ │
│  │                                                          │ │
│  │  切换数据库: 改 DATABASE_URL + 换 Session Factory          │ │
│  │  Repository 代码一行不动                                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

```python
# src/infrastructure/repositories/stock_repository.py
# Repository 不 import 任何 ORM 实现

from src.domain.models.stock import Stock
from src.domain.ports.repository_port import RepositoryPort
from sqlalchemy.ext.asyncio import AsyncSession

class StockRepository(RepositoryPort[Stock]):
    """股票仓储 —— 与底层数据库无关"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_code(self, code: str) -> Stock | None:
        result = await self._session.execute(
            # 使用 Stock 领域模型的字段，不引用 ORM 类
            select(Stock).where(Stock.code == code)
        )
        return result.scalar_one_or_none()

    async def save(self, entity: Stock) -> Stock:
        # 不关心底层是 SQLite 还是 PostgreSQL
        self._session.add(entity)
        await self._session.commit()
        return entity
```

### 4.2 Knowledge 热加载 ②

```
┌──────────────────────────────────────────────────────────────┐
│              Knowledge 热加载系统                              │
│                                                               │
│  knowledge/                                                   │
│  ├── loader.py      知识加载器                                │
│  │   · load_all() → 加载全部 YAML                             │
│  │   · load_category(cat) → 加载单个分类                      │
│  │   · load_entry(cat, key) → 加载单个条目                    │
│  │   · validate(yaml_content) → 校验格式                      │
│  │                                                           │
│  ├── indexer.py     知识索引器                                │
│  │   · build_index() → 构建全文索引                           │
│  │   · rebuild_index() → 重建索引                             │
│  │   · get_index_stats() → 索引统计                           │
│  │                                                           │
│  ├── search.py      知识搜索                                  │
│  │   · search(query, category, top_k) → 语义搜索              │
│  │   · fuzzy_search(term) → 模糊匹配                          │
│  │   · cross_reference(entry) → 交叉引用                      │
│  │                                                           │
│  └── watcher.py     文件监控器                                │
│      · 使用 watchdog / inotify 监控 knowledge/ 目录           │
│      · 检测 .yaml 文件变化                                    │
│      · 自动调用 loader.reload(file_path)                      │
│      · 自动调用 indexer.update_index(file_path)               │
│      · 发布 Event: knowledge.entry.updated                    │
│                                                               │
│  使用效果:                                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ $ vim knowledge/policy/monetary_policy.yaml              │ │
│  │   (保存)                                                 │ │
│  │   → watcher 检测到变化                                    │ │
│  │   → loader 重新加载该文件                                  │ │
│  │   → indexer 更新索引                                      │ │
│  │   → publish("knowledge.entry.updated", {...})            │ │
│  │   → Agent 下次分析自动使用新知识                           │ │
│  │   全程不重启                                              │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 Plugin 版本约束 ③

```yaml
# plugins/datasource/akshare/plugin.yaml (v1.0 最终格式)

plugin:
  # ===== 基本信息 =====
  name: "akshare"
  version: "2.0.0"              # 插件自身版本 (semver)
  type: "datasource"
  display_name: "AKShare 数据源"
  description: "基于 AKShare 的 A 股免费数据源"
  author: "QuantAI Team"
  entry_point: "adapter:AKShareAdapter"
  dependencies: ["akshare>=1.14.0"]

  # ===== ③ 版本约束 =====
  api_version: 1                 # 插件 API 协议版本
  engine_version: "1.0.0"       # 插件引擎版本
  minimum_core: "1.2.0"         # 最低核心版本要求
  maximum_core: "2.x"           # 最高兼容核心版本 (semver range)

  # ===== 技术能力（纯技术事实）=====
  capabilities:
    supports_realtime: true
    supports_intraday: true
    supports_history: true
    supports_financials: true
    supports_lhb: true
    supports_fund_flow: true
    supports_news: false
    coverage_markets: ["SH", "SZ", "BJ"]
    data_quality: "good"
    rate_limit_recommended: 60

  # ⚠️ 合规权限不在此声明，见 config/license_policies.yaml
```

```python
# src/infrastructure/plugin_registry/validator.py

class PluginValidator:
    """插件校验器 —— ③ 含版本约束检查"""

    CORE_VERSION = "1.2.0"      # 当前核心版本
    SUPPORTED_API_VERSIONS = [1] # 支持的 API 协议版本

    def validate(self, manifest: PluginManifest) -> ValidationResult:
        errors = []

        # API 版本检查
        if manifest.api_version not in self.SUPPORTED_API_VERSIONS:
            errors.append(
                f"不支持的 API 版本 {manifest.api_version}，"
                f"支持: {self.SUPPORTED_API_VERSIONS}"
            )

        # 最低核心版本检查
        if not self._semver_gte(self.CORE_VERSION, manifest.minimum_core):
            errors.append(
                f"插件要求核心版本 ≥ {manifest.minimum_core}，"
                f"当前核心版本 {self.CORE_VERSION}"
            )

        # 最高核心版本检查
        if manifest.maximum_core:
            if not self._semver_matches(self.CORE_VERSION, manifest.maximum_core):
                errors.append(
                    f"插件不兼容核心版本 {self.CORE_VERSION}，"
                    f"兼容范围: {manifest.maximum_core}"
                )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=[],    # 版本兼容但建议升级等
        )
```

### 4.4 Event 结构化信封 ④

```python
# src/domain/events/base_event.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

@dataclass
class EventEnvelope:
    """事件信封 —— 所有事件的统一外层结构

    版本演进示例:
      v1: {version:1, event_id, timestamp, producer, payload: {...}}
      v2: {version:2, ..., trace_id, parent_event_id, payload: {...}}
      消费者根据 version 字段选择对应的解析器
    """
    version: int = 1
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    producer: str = ""                    # 生产者模块名
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "producer": self.producer,
            "payload": self.payload,
        }

# 使用示例
event = EventEnvelope(
    version=1,
    producer="scanner_engine",
    payload={
        "scan_date": "2026-07-05",
        "candidates_count": 20,
        "top_candidates": [
            {"code": "000725.SZ", "score": 91.8, "direction": "buy"},
        ],
    },
)

await eventbus.publish("scanner.completed", event.to_dict())
```

### 4.5 Prompt Registry ⑤

```
┌──────────────────────────────────────────────────────────────┐
│                  Prompt Registry                              │
│                                                               │
│  设计目标:                                                     │
│  · Prompt 版本化 (v1/v2/...)                                  │
│  · 热更新 (不停机切换 Prompt)                                  │
│  · 缓存 (避免重复渲染 Jinja2)                                  │
│  · 回滚 (新 Prompt 效果差 → 一键回退)                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              PromptRegistry                              │ │
│  │                                                          │ │
│  │  get(name, version=None) → Prompt                       │ │
│  │  register(name, template, version) → None               │ │
│  │  activate(name, version) → None    # 激活指定版本         │ │
│  │  rollback(name) → None             # 回滚到上一版本       │ │
│  │  list_versions(name) → list[str]                        │ │
│  │  compare(name, v1, v2) → str       # 版本 diff           │ │
│  │  render(name, context) → str       # 渲染 Prompt          │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  存储结构:                                                     │
│  config/prompts/                                              │
│  ├── registry.yaml                     # 注册表              │
│  │   prompts:                                                │
│  │     analyst_stock:                                        │
│  │       active_version: "v2"                                │
│  │       versions: ["v1", "v2"]                              │
│  │       category: "agent/analyst"                           │
│  │       model_compatibility: ["deepseek", "openai", "claude"]│
│  │                                                           │
│  ├── versions/                        # 版本化 Prompt 存储   │
│  │   ├── analyst_stock/                                       │
│  │   │   ├── v1.yaml                                          │
│  │   │   └── v2.yaml                                          │
│  │   └── ...                                                  │
│  │                                                           │
│  └── templates/                        # Jinja2 模板          │
│      └── analyst_stock.j2                                     │
│                                                               │
│  Prompt 生命周期:                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 1. 开发者修改 templates/analyst_stock.j2                  │ │
│  │ 2. PromptRegistry.register("analyst_stock", v3)          │ │
│  │ 3. 测试环境验证 v3 效果                                    │ │
│  │ 4. PromptRegistry.activate("analyst_stock", "v3")        │ │
│  │    → 所有 Agent 立即使用新 Prompt (热切换)                 │ │
│  │ 5. 如果效果差:                                             │ │
│  │    PromptRegistry.rollback("analyst_stock")               │ │
│  │    → 自动回到 v2                                          │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 4.6 Research Candidate ⑥

**问题**: Scanner 输出硬编码 Top20，不同策略/市场/国家无法复用。

**方案**: Scanner 输出标准化的 `ResearchCandidate` 对象。

```python
# src/domain/models/research_candidate.py

from dataclasses import dataclass, field
from datetime import date

@dataclass
class ResearchCandidate:
    """研究候选标的 —— Scanner 的标准输出

    不是 "Top 20 列表"，而是 "值得研究的候选标的集合"。
    不同的 Pipeline/策略/市场/国家 都可以输出 ResearchCandidate。
    """

    stock_code: str                    # "000725.SZ"
    stock_name: str                    # "京东方A"
    market: str                        # "SH" / "SZ" / "HK" / "US"

    # 评分
    fusion_score: float                # 91.8
    score_breakdown: dict[str, float]  # {"macd":95, "capital":100, ...}
    direction: str                     # "buy" / "sell" / "neutral"

    # 分类
    candidate_type: str                # "scanner_top" / "watchlist" / "manual" / "event_driven"
    strategy_id: str | None = None     # 哪个策略产生的候选
    pipeline_run_id: str | None = None # 哪个 Pipeline Run 产生的

    # 上下文
    scan_date: date | None = None
    signals_detail: dict = field(default_factory=dict)
    key_metrics: dict = field(default_factory=dict)  # PE/市值/换手率...

    # 元数据
    confidence: float = 0.0            # 整体置信度
    rank: int = 0                      # 在候选池中的排名
    tags: list[str] = field(default_factory=list)  # ["面板","北向流入","MACD金叉"]

    # 研究状态（供 Agent 使用）
    research_status: str = "pending"   # pending / analyzing / completed / skipped
    research_priority: int = 0         # 研究优先级
    assigned_agent: str | None = None


# Scanner 输出示例
scanner_result = ScannerResult(
    pipeline_run_id="run_20260705_1530",
    total_scanned=5000,
    after_coarse_filter=2000,
    after_technical_filter=100,
    candidates=[
        ResearchCandidate(
            stock_code="000725.SZ", stock_name="京东方A",
            fusion_score=91.8, direction="buy",
            candidate_type="scanner_top",
            score_breakdown={"macd":95, "capital":100, "lhb":90, "news":85},
            tags=["面板", "北向流入", "MACD金叉"],
            research_priority=1,
        ),
        # ... 19 more
    ],
)

# Agent 接收 ResearchCandidate 列表
# 不同 Agent 策略可以:
#   - 取 research_priority 最高的 N 个
#   - 取特定 tags 的候选
#   - 取特定 strategy_id 的候选
#   - 取特定 market 的候选
# 全部通过同一个 ResearchCandidate 接口
```

### 4.7 Research Memory ⑨

```
┌──────────────────────────────────────────────────────────────┐
│                 Research Memory 研究记忆                       │
│                                                               │
│  设计目标: AI 不只是分析今天，而是有长期记忆                     │
│                                                               │
│  research_memory/                                             │
│  ├── market_context/      市场环境快照                         │
│  │   · 每天的市场状态 (牛/熊/震荡/结构)                       │
│  │   · 当时的宏观指标 (PMI/CPI/利率)                          │
│  │   · 当时的市场情绪                                        │
│  │                                                           │
│  ├── watchlist/           观察列表历史                         │
│  │   · 什么时候加入的？                                      │
│  │   · 当时的评分是多少？                                    │
│  │   · 评分变化轨迹 (92→78→...)                              │
│  │   · 什么时候移除的？为什么？                              │
│  │                                                           │
│  ├── daily_summary/       日度总结                            │
│  │   · 每天的研究摘要                                        │
│  │   · AI 生成的日度市场综述                                  │
│  │   · 关键事件日志                                          │
│  │                                                           │
│  ├── trade_journal/       交易日志                            │
│  │   · 每笔交易的完整记录                                    │
│  │   · 交易理由 + 事后评估                                   │
│  │                                                           │
│  ├── decision_log/        决策记录                            │
│  │   · 为什么买入 / 为什么卖出 / 为什么不买                   │
│  │   · AI 推理过程                                          │
│  │   · 决策时的证据链                                        │
│  │                                                           │
│  ├── strategy_history/    策略变更历史                         │
│  │   · 策略参数变化记录                                      │
│  │   · 变化原因 + 效果对比                                   │
│  │                                                           │
│  └── llm_memory/          LLM 对话记忆                        │
│      · 历史研究会话摘要                                      │
│      · 关键洞察积累                                          │
│      · Agent 思考过程归档                                    │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              使用场景示例                                 │ │
│  │                                                          │ │
│  │  用户问: "为什么两个月前把京东方A加入观察？"               │ │
│  │                                                          │ │
│  │  AI:                                                      │ │
│  │  ┌────────────────────────────────────────────────────┐  │ │
│  │  │ 根据 Research Memory:                               │  │ │
│  │  │                                                    │  │ │
│  │  │ 2026-05-05 首次发现 (Scanner)                        │  │ │
│  │  │   信号: MACD金叉(92分)+北向流入(95分)+面板涨价新闻    │  │ │
│  │  │   评分: 88.5 | 标记: 面板行业                        │  │ │
│  │  │                                                    │  │ │
│  │  │ 2026-05-15 评分上升至 92.3                           │  │ │
│  │  │   龙虎榜首次出现机构买入                              │  │ │
│  │  │                                                    │  │ │
│  │  │ 2026-06-20 评分下降至 78.1                           │  │ │
│  │  │   北向资金转为流出，面板价格松动                       │  │ │
│  │  │                                                    │  │ │
│  │  │ 2026-07-03 移除观察                                  │  │ │
│  │  │   评分持续低于80，面板周期拐点不确定性增加             │  │ │
│  │  │   Decision Log: "面板Q3涨价预期减弱，转为观望"         │  │ │
│  │  └────────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

```python
# src/domain/models/research_memory.py

@dataclass
class WatchlistEntry:
    """观察列表条目"""
    stock_code: str
    added_date: date
    added_reason: str
    added_score: float
    score_trajectory: list[dict]     # [{"date":"...","score":92}, ...]
    first_discovered_date: date     # 第一次被 Scanner 发现
    key_events: list[dict]           # [{"date":"...","event":"龙虎榜机构买入"},...]
    removed_date: date | None
    removed_reason: str | None

@dataclass
class DecisionRecord:
    """决策记录"""
    decision_date: date
    decision_type: str               # "buy" / "sell" / "hold" / "skip"
    stock_code: str
    reasoning: str                   # AI 推理过程
    evidence_chain: list[str]        # 证据链
    confidence: float
    outcome: str | None              # 事后评估
    outcome_date: date | None
```

### 4.8 数据获取伦理原则 ⑧

```
┌──────────────────────────────────────────────────────────────┐
│            数据获取伦理原则 (Data Acquisition Ethics)          │
│                                                               │
│  ✅ 允许                                                       │
│  ├── 官方 API (AKShare / Tushare / 交易所官网)                 │
│  ├── 用户自行配置的授权 API (Polygon / AlphaVantage / Wind)    │
│  ├── 开源项目 (遵守其 License)                                 │
│  ├── 用户本地数据 (CSV/Parquet/自建数据库)                     │
│  └── 券商/期货公司提供的官方行情接口                            │
│                                                               │
│  ❌ 禁止                                                       │
│  ├── 破解客户端 (逆向工程/脱壳)                                │
│  ├── Hook 同花顺/东方财富/大智慧 等客户端                      │
│  ├── DLL 注入 / 内存读取                                      │
│  ├── OCR 抓取客户端界面                                       │
│  ├── 非授权接口调用 (未公开的 API)                             │
│  ├── 绕过登录/权限验证                                        │
│  ├── Cookie/Token 伪造或复用                                  │
│  └── 任何违反《数据安全法》《个人信息保护法》的行为             │
│                                                               │
│  DataSourcePlugin 统一接口:                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ class DataSourcePlugin(BasePlugin):                     │ │
│  │     async def fetch_quotes(self, codes) → list[Quote]   │ │
│  │     async def fetch_history(self, code, period, ...)    │ │
│  │     async def fetch_financials(self, code) → Financials │ │
│  │     async def fetch_lhb(self, date) → list[LHBRecord]   │ │
│  │     async def fetch_fund_flow(self, code) → FundFlow    │ │
│  │     async def fetch_news(self, code) → list[NewsItem]   │ │
│  │     async def health_check(self) → bool                 │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  新增任何合法数据源: 实现上述接口 → 丢 plugins/datasource/     │
│  业务层代码一行不动                                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. 数据库设计

### 5.1 Repository-ORM 映射

| Repository (抽象) | ORM 实现 (sqlite/) | ORM 实现 (postgresql/) | 说明 |
|-------------------|-------------------|----------------------|------|
| `stock_repository.py` | `sqlite/stock_orm.py` | `postgresql/stock_orm.py` | 股票CRUD |
| `market_data_repository.py` | `sqlite/market_data_orm.py` | ... | 行情CRUD |
| `signal_repository.py` | `sqlite/signal_orm.py` | ... | 信号+融合评分 |
| `report_repository.py` | `sqlite/report_orm.py` | ... | AI分析报告 |
| `research_memory_repository.py` | `sqlite/research_memory_orm.py` | ... | ⑨ 研究记忆 |

### 5.2 v1.0 新增表

#### research_candidates（研究候选池）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | |
| `pipeline_run_id` | VARCHAR(100) | Pipeline Run ID |
| `stock_code` | VARCHAR(20) | 股票代码 |
| `stock_name` | VARCHAR(50) | |
| `fusion_score` | DECIMAL(5,2) | 融合评分 |
| `score_breakdown_json` | TEXT | 各维度评分 |
| `direction` | VARCHAR(10) | |
| `candidate_type` | VARCHAR(30) | scanner_top/watchlist/manual/event_driven |
| `strategy_id` | INTEGER | |
| `research_status` | VARCHAR(20) | pending/analyzing/completed/skipped |
| `research_priority` | INTEGER | |
| `tags_json` | TEXT | |
| `scan_date` | DATE | |
| `created_at` | DATETIME | |

#### research_memory_entries（研究记忆）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | |
| `memory_type` | VARCHAR(30) | watchlist/decision/trade_journal/llm_memory/... |
| `stock_code` | VARCHAR(20) | |
| `entry_date` | DATE | |
| `title` | VARCHAR(200) | |
| `content_json` | TEXT | 结构化记忆内容 |
| `importance` | DECIMAL(3,2) | 重要度 0-1（衰减用） |
| `decay_factor` | DECIMAL(3,2) | 衰减因子 |
| `last_recalled_at` | DATETIME | 最后被查询时间 |
| `created_at` | DATETIME | |

#### prompt_versions（Prompt 版本）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | |
| `prompt_name` | VARCHAR(100) | |
| `version` | VARCHAR(20) | v1/v2/... |
| `is_active` | BOOLEAN | 是否当前激活 |
| `template_content` | TEXT | Jinja2 模板内容 |
| `system_prompt` | TEXT | System Prompt |
| `model_compatibility_json` | TEXT | 兼容的模型列表 |
| `performance_metrics_json` | TEXT | 效果评估指标 |
| `created_at` | DATETIME | |
| `activated_at` | DATETIME | |

（其余表继承 Final 草稿版）

---

## 6. 数据流设计

### 6.1 Scanner → ResearchCandidate → Agent（⑥）

```
Scanner 运行
    │
    ▼
┌──────────────────────────────────────────────┐
│  Scanner Output: ResearchCandidate[]          │
│  (不叫 Top20, 不硬编码数量)                     │
│                                               │
│  candidates = [                                │
│    ResearchCandidate(code="000725.SZ",         │
│      fusion_score=91.8,                        │
│      candidate_type="scanner_top",             │
│      tags=["面板","北向流入"],                  │
│      research_priority=1),                     │
│    ...                                         │
│  ]                                             │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  AgentOrchestrator 消费 ResearchCandidate[]    │
│                                               │
│  不同策略可以不同消费方式:                      │
│                                               │
│  策略A (默认):                                 │
│    candidates[:3]  → AI 深度分析              │
│                                               │
│  策略B (多市场):                               │
│    filter(market="HK") → HK 候选              │
│    filter(market="US") → US 候选              │
│    各自 Top 3 → AI 深度分析                   │
│                                               │
│  策略C (事件驱动):                             │
│    filter(candidate_type="event_driven")       │
│    → AI 分析事件影响                          │
│                                               │
│  策略D (watchlist):                            │
│    filter(candidate_type="watchlist")          │
│    → AI 跟踪已有标的                           │
│                                               │
│  全部通过同一个 ResearchCandidate 接口         │
└──────────────────────────────────────────────┘
```

---

## 7. AI Agent 层设计

（与 Final 草稿一致 — Planner → Researcher → Analyst → Reviewer → Reporter。⑨ Research Memory 作为 Agent 的长期记忆输入源）

---

## 8. Plugin Registry 设计

（与 Final 草稿一致。③ 版本约束校验已集成到 PluginValidator）

---

## 9. 配置管理

```python
# config/settings.py v1.0 新增

class Settings(BaseSettings):
    # ... (所有已有配置) ...

    # ---- ① Repository ----
    DATABASE_BACKEND: str = "sqlite"        # sqlite / postgresql / duckdb / clickhouse
    ORM_MODULE_PATH: str = "src.infrastructure.orm.sqlite"  # 自动切换

    # ---- ② Knowledge ----
    KNOWLEDGE_HOT_RELOAD: bool = True       # 启用文件监控热加载
    KNOWLEDGE_WATCH_INTERVAL: float = 2.0   # 监控扫描间隔（秒）

    # ---- ③ Plugin ----
    PLUGIN_MINIMUM_CORE: str = "1.2.0"      # 当前核心版本
    PLUGIN_SUPPORTED_API_VERSIONS: list = [1]

    # ---- ⑤ Prompt Registry ----
    PROMPT_REGISTRY_CACHE_SIZE: int = 100
    PROMPT_HOT_RELOAD: bool = True
    PROMPT_DEFAULT_VERSION: str = "latest"

    # ---- ⑨ Research Memory ----
    RESEARCH_MEMORY_ENABLED: bool = True
    RESEARCH_MEMORY_DECAY_DAYS: int = 90    # 记忆衰减天数
    RESEARCH_MEMORY_MAX_ENTRIES: int = 10000
```

---

## 10. 接口设计

### 10.1 v1.0 新增端口

```python
# PromptRegistryPort
class PromptRegistryPort(ABC):
    async def get(self, name: str, version: str | None = None) -> Prompt: ...
    async def register(self, name: str, template: str, version: str) -> None: ...
    async def activate(self, name: str, version: str) -> None: ...
    async def rollback(self, name: str) -> str: ...
    async def list_versions(self, name: str) -> list[str]: ...
    async def render(self, name: str, context: dict) -> str: ...

# ResearchMemoryPort
class ResearchMemoryPort(ABC):
    async def remember(self, entry: ResearchMemoryEntry) -> None: ...
    async def recall(self, stock_code: str, memory_type: str | None = None) -> list: ...
    async def query_timeline(self, stock_code: str) -> list[dict]: ...
    async def get_score_trajectory(self, stock_code: str) -> list[dict]: ...
    async def get_decisions(self, stock_code: str) -> list[DecisionRecord]: ...
    async def forget(self, stock_code: str, reason: str) -> None: ...
```

### 10.2 v1.0 新增 REST API

```
Prompt Management
├── GET    /prompts                         列出所有 Prompt
├── GET    /prompts/{name}                  Prompt 详情
├── GET    /prompts/{name}/versions         版本列表
├── POST   /prompts/{name}/activate         激活版本
├── POST   /prompts/{name}/rollback         回滚
├── GET    /prompts/{name}/diff?v1&v2       版本对比
└── POST   /prompts/{name}/render           预览渲染

Research Memory
├── GET    /memory/watchlist                 观察列表
├── GET    /memory/watchlist/{code}/timeline 时间线
├── GET    /memory/decisions/{code}          决策记录
├── GET    /memory/daily/{date}              日度总结
└── GET    /memory/search?q=...              搜索记忆

Research Candidates
├── GET    /candidates/latest                最新候选池
├── GET    /candidates/{date}                指定日期
├── GET    /candidates/{code}/history         标的候选历史
└── POST   /candidates/{code}/status          更新研究状态

Knowledge (新增热加载接口)
├── POST   /knowledge/reload                 手动重载知识库
├── GET    /knowledge/status                 知识库状态（条目数/索引大小/最后更新）
└── POST   /knowledge/validate               校验所有 YAML 格式
```

---

## 11. 模块依赖图

```
                          ┌──────────┐
                          │  shared  │
                          └────┬─────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
    ┌──────────┐       ┌─────────────┐      ┌──────────────┐
    │  domain  │◄──────│ application │      │infrastructure│
    │          │       │             │      │              │
    │ models   │       │ use_cases   │      │ eventbus/    │
    │ services │       │ dto         │      │ task_queue/  │
    │ ports    │       │ handlers    │      │ metrics/     │
    │ events   │       └─────────────┘      │ plugin_reg/  │
    │          │                            │ prompt_reg/  │ ← ⑤
    │ ① candidates                          │ agents/      │
    │ ⑨ memory                             │ repositories/│ ← ① 纯抽象
    │ ④ envelope                           │ orm/         │ ← ① 按DB分
    └──────────┘                            │  sqlite/     │
         ▲                                  │  postgresql/ │
         │                                  │ research_    │
         │         ┌───────────────┐        │  memory/     │ ← ⑨
         │         │    signals/   │        │ compliance/  │
         │         └───────────────┘        │ adapters/    │
         │                                  └──────┬───────┘
         │    ┌────────────────────┐               │
         │    │    knowledge/      │               │
         │    │ ② loader/indexer   │               │
         │    │   search/watcher   │               │
         │    └────────────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │    plugins/        │               │
         │    │ ③ 版本约束         │               │
         │    └────────────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │ research_memory/   │               │
         │    │ ⑨ 7个子目录        │               │
         │    └────────────────────┘               │
         │                                         │
         └─────────────────────────────────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │     api     │
                   └─────────────┘
```

---

## 12. 整体开发路线图（Roadmap v1.0）

```
Phase 0: 基础设施 (Week 1-2)
├── Poetry + ruff + mypy + pre-commit
├── plugin_protocol.py
├── EventBus 内存版 (④ 结构化信封)
├── Metrics 内存版
├── 目录结构 + .env + 配置骨架
├── loguru 日志
├── SQLAlchemy ORM (sqlite/)
├── Repository 抽象层 (base.py + 接口)
└── pytest + CI/CD

Phase 1: Plugin Registry (Week 3-4)
├── PluginRegistry (discover/register/validate/lifecycle)
├── ③ 版本约束校验 (api_version/minimum_core/maximum_core)
├── plugin.yaml 格式规范
├── plugins/datasource/_template/
└── /plugins API

Phase 2: Market Gateway (Week 5-7)
├── MarketGateway (从 Registry 获取)
├── ⑧ DataSourcePlugin 统一接口
├── plugins/datasource/akshare/
├── plugins/datasource/tushare/
├── DataSourceCapability 能力路由
├── 数据清洗/验证/标准化
└── APScheduler 定时同步

Phase 3: Repository (Week 8-9)           ← 提前到 P3
├── ① 完整 Repository 抽象层
├── StockRepository / MarketDataRepository / SignalRepository
├── ReportRepository / TaskRepository
├── ORM sqlite/ 完整实现
├── ORM postgresql/ 骨架
├── Repository 单元测试 (Mock Session)
└── 数据库迁移脚本

Phase 4: Knowledge (Week 10-11)
├── ② Knowledge Loader + Indexer + Search
├── ② File Watcher (热加载)
├── 8 个子目录首批 YAML
├── KnowledgeBasePort + API
└── /knowledge API + /knowledge/reload

Phase 5: Signals (Week 12-14)
├── SignalPlugin 协议
├── builtin/ (12 个信号)
├── custom/_template.py
├── ml/ (XGBoost/LightGBM 骨架)
├── SignalFusion 融合引擎
└── /signals API

Phase 6: Scanner (Week 15-16)
├── ⑥ Scanner 输出 ResearchCandidate
├── 三层管道 (粗筛→技术筛选→评分→候选池)
├── EventBus 集成
└── /scanner + /candidates API

Phase 7: Research Pipeline (Week 17-19)
├── Task Queue (Arq) 部署
├── ⑨ Research Memory (7 个子模块)
├── Research Pipeline (事件驱动 9 步)
├── 交易日历集成
└── /research/pipeline + /memory API

Phase 8: AI Agent Layer (Week 20-23)
├── ⑤ Prompt Registry (版本/热更新/缓存/回滚)
├── BaseAgent + AgentContext
├── Planner / Researcher / Analyst / Reviewer / Reporter
├── AgentOrchestrator (4 种协作模式)
├── Agent ↔ LLM 解耦
├── Reviewer 幻觉检查 + 驳回循环
├── Research Memory 集成到 Agent
├── WebSocket Stream Agent 思考过程
└── /research + /prompts API

Phase 9: Backtest + Trading (Week 24-27)
├── BaseStrategy + 内置策略
├── BacktestEngine + PerformanceCalculator
├── Order/Position/Account/Portfolio 模型
├── BrokerPort + SimNow Adapter
├── TradingEngine + RiskManager
└── /backtest /trading /portfolio /risk API

Phase 10: VSCode Extension (Week 28-30)   ← 移到 Agent 和 Backtest 之后
├── 插件框架 (TypeScript)
├── Sidebar: 股票列表 + 信号评分
├── Webview: K线图表
├── Panel: Agent 研究面板 + 研究历史
├── Panel: Research Memory 时间线
├── Status Bar: 实时行情 + 管线状态
├── Command: 一键发起研究
└── IPC 通信 (JSON-RPC)

Phase 11: Notification (Week 31)
├── Email + WeChat 通知适配器
├── 事件驱动推送
└── /notification API

Phase 12: 测试 + 文档 + 发布 (Week 32-34)
├── 测试覆盖率 ≥ 80%
├── E2E 全流程
├── Agent 评测基准
├── Prometheus + Grafana
├── API 文档 + 用户手册
└── v1.0.0 发布

Phase 13: Web (后期)
└── React 前端
```

**Roadmap 设计原则**:
- Repository 提前到 P3（数据模型准备好了立即抽象）
- Agent 在 P8（依赖 Knowledge/Signals/Scanner/Pipeline/Memory 全部就绪）
- VSCode 在 P10（Agent 和 Backtest 都完成后再做 UI，有内容可展示）
- Research Memory 在 P7（Pipeline 中积累记忆，Agent 使用记忆）

---

## 13. 附录

### A. 核心设计原则（最终 14 条）

1. **AI 永远最后一步** — 解释，不计算
2. **Plugin 丢进去就识别** — Registry 自动发现
3. **能力声明替代 if-else** — 数据源声明能力，系统自动路由
4. **技术能力与合规权限分离** — plugin.yaml / license_policies.yaml
5. **Repository 与 ORM 分离** — 换数据库不改业务代码
6. **Agent 各司其职** — Planner→Researcher→Analyst→Reviewer→Reporter
7. **Agent 与 LLM 解耦** — 每个 Agent 独立选模型
8. **事件驱动解耦** — 模块通过 EventBus 通信，结构化信封
9. **Task Queue 异步化** — 绝不 for 循环处理大量任务
10. **全链路可观测** — Metrics 覆盖性能/成本/缓存/健康
11. **VSCode 纯 UI** — 迁移 Web 不改 Python
12. **知识库先于 AI** — 研报+产业链+政策+历史案例
13. **Research Memory 长期记忆** — AI 不只是分析今天
14. **数据获取合法合规** — API+开源+用户授权，禁止破解/Hook/注入

### B. ⚠️ 运维提醒

`config/license_policies.yaml` 中的数据源许可配置属于**运维数据**，不视为永久正确的事实。每个数据源的许可证、服务条款和数据使用政策可能随时变化。系统管理员应：

- 定期（建议每季度）人工审核许可证变更
- 每次审核记录审核日期和审核人
- 保留每个数据源的官方许可证或服务条款链接
- 将合规检查与实际使用场景结合，不单独依赖配置文件

### C. 架构演进历史

| 版本 | 核心贡献 |
|------|---------|
| v1 | 分层架构、13表、8 API、8 Phase |
| v2 | MarketGateway、Compliance、Knowledge、Signals+Scanner、Pipeline、数据伦理 |
| v3 | Plugin Registry、AI Agent Layer、DataSourceCapability、Knowledge扩展、Research Terminal定位 |
| Final | EventBus、TaskQueue、Metrics、许可分离 |
| **v1.0** | Repository抽象、Knowledge热加载、Plugin版本约束、Event信封、Prompt Registry、ResearchCandidate、Research Memory、数据伦理原则、Roadmap重排 |

---

> **🔒 架构冻结。Phase 0 开始。**
