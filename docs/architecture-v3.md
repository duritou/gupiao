# AI Research Terminal — 架构设计文档 v3

> **版本**: v3.0.0  
> **日期**: 2026-07-05  
> **定位**: AI 股票研究终端（非 AI 选股工具）  
> **状态**: 待评审  
> **核心变更**: Plugin Registry / AI Agent Layer / DataSourceCapability / 知识库扩展 / 信号插件化

---

## 目录

1. [定位宣言](#定位宣言)
2. [v2 → v3 核心变更](#v2--v3-核心变更)
3. [项目总体架构](#3-项目总体架构)
4. [完整目录结构](#4-完整目录结构)
5. [每个目录职责](#5-每个目录职责)
6. [每个模块职责](#6-每个模块职责)
7. [数据库设计](#7-数据库设计)
8. [数据流设计](#8-数据流设计)
9. [AI Agent 层设计（核心新增）](#9-ai-agent-层设计核心新增)
10. [Plugin Registry 设计（核心新增）](#10-plugin-registry-设计核心新增)
11. [插件通信流程](#11-插件通信流程)
12. [配置管理](#12-配置管理)
13. [日志管理](#13-日志管理)
14. [缓存方案](#14-缓存方案)
15. [未来扩展方案](#15-未来扩展方案)
16. [接口设计](#16-接口设计)
17. [模块依赖图](#17-模块依赖图)
18. [整体开发路线图](#18-整体开发路线图roadmap)

---

## 定位宣言

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│   ❌ 不是: AI 选股工具                                        │
│   ✅ 是:  AI Research Terminal (AI 股票研究终端)               │
│                                                               │
│   区别:                                                        │
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

## v2 → v3 核心变更

| # | 变更项 | v2 | v3 | 理由 |
|---|--------|-----|-----|------|
| 1 | 数据源架构 | MarketGateway 硬编码适配器列表 | **Plugin Registry + `plugins/datasource/`** | 丢进去就能识别，10年不重构 |
| 2 | 信号架构 | `signals/` 平铺文件 | **`signals/builtin/` + `custom/` + `ml/`** | 内置/自定义/ML信号三层隔离，SignalFusion 不用改 |
| 3 | 知识库 | 4个子目录 | **8个子目录 + reports/policy/strategy/books/papers** | AI 的上下文从"新闻+K线"升级为"研报+产业链+政策+历史案例" |
| 4 | AI 层 | 单个 AIAnalysisEngine | **AI Agent Layer: Planner/Researcher/Analyst/Reviewer/Reporter** | 多 Agent 协作，分工明确，可接任何 LLM |
| 5 | 合规 | 5 个检查维度 | **+ DataSourceCapability 能力声明** | 数据源自己声明能做什么，系统自动路由，消除 if-else |
| 6 | 定位 | AI 股票分析系统 | **AI Research Terminal（AI股票研究终端）** | 本质跨越：推荐工具 → 研究终端 |
| 7 | 插件 | 无统一注册机制 | **Plugin Registry（插件注册中心）** | 数据源/信号/Agent/通知/券商 全部插件化 |

---

## 3. 项目总体架构（v3）

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
                                   │ REST / WebSocket / IPC (JSON-RPC)
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
│  │  [v3新增] PluginRegistryPort · AgentOrchestrator · ResearchSession│ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    基础设施层 (Infrastructure Layer)                   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Plugin Registry (插件注册中心) — v3 核心           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │   │
│  │  │DataSource│ │ Signal   │ │ Agent    │ │ Notification     │ │   │
│  │  │Plugins   │ │ Plugins  │ │ Plugins  │ │ Plugins          │ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              AI Agent Layer (智能体层) — v3 核心                │   │
│  │  Planner → Researcher → Analyst → Reviewer → Reporter          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Compliance + Knowledge + Cache + Repositories     │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                    插件层 (Plugin Layer) — v3 核心                     │
│                                                                       │
│  plugins/                                                             │
│  ├── datasource/    (丢进去就能识别)                                   │
│  ├── signal/        (builtin / custom / ml)                           │
│  ├── agent/         (未来: 自定义 Agent)                               │
│  └── broker/        (未来: 自定义券商)                                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. 完整目录结构（v3）

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
│   ├── architecture-v3.md            # 本架构设计文档 v3
│   ├── architecture-v2.md            # v2 留档
│   ├── architecture-v1.md            # v1 留档
│   ├── api-reference.md
│   ├── database-schema.md
│   ├── development-guide.md
│   ├── deployment-guide.md
│   ├── user-guide.md
│   └── changelog/
│
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── database.py
│   ├── ai_models.py
│   ├── plugin_registry.py            # [v3] 插件注册表配置
│   ├── trading.py
│   ├── cache.py
│   ├── logging.yaml
│   ├── prompts/                      # [v3扩展] Agent 各自有自己的 prompt
│   │   ├── system_prompts/
│   │   │   ├── planner.yaml          #   Planner Agent 角色
│   │   │   ├── researcher.yaml       #   Researcher Agent 角色
│   │   │   ├── analyst.yaml          #   Analyst Agent 角色
│   │   │   ├── reviewer.yaml         #   Reviewer Agent 角色
│   │   │   └── reporter.yaml         #   Reporter Agent 角色
│   │   ├── templates/
│   │   │   ├── market_review.j2
│   │   │   ├── stock_deep_research.j2
│   │   │   ├── sector_analysis.j2
│   │   │   ├── risk_assessment.j2
│   │   │   └── daily_briefing.j2
│   │   └── few_shot_examples/
│   └── brokers/
│       ├── __init__.py
│       └── simnow.py
│
├── src/
│   ├── __init__.py
│   │
│   ├── domain/                       # 🧠 领域层
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── stock.py
│   │   │   ├── market_data.py
│   │   │   ├── strategy.py
│   │   │   ├── signal.py
│   │   │   ├── order.py
│   │   │   ├── position.py
│   │   │   ├── portfolio.py
│   │   │   ├── account.py
│   │   │   ├── backtest.py
│   │   │   ├── research_session.py      # [v3] 研究会话实体
│   │   │   ├── agent_task.py            # [v3] Agent 任务实体
│   │   │   ├── plugin_manifest.py       # [v3] 插件清单实体
│   │   │   ├── ai_analysis.py
│   │   │   ├── risk.py
│   │   │   ├── indicator.py
│   │   │   ├── datasource_capability.py # [v3] 数据源能力声明
│   │   │   ├── compliance_record.py
│   │   │   └── enums.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── trading_engine.py
│   │   │   ├── signal_fusion_engine.py
│   │   │   ├── risk_manager.py
│   │   │   ├── portfolio_optimizer.py
│   │   │   ├── market_screener.py
│   │   │   ├── scanner_engine.py
│   │   │   ├── backtest_engine.py
│   │   │   ├── agent_orchestrator.py       # [v3] Agent 编排器（核心）
│   │   │   └── research_pipeline.py
│   │   ├── ports/
│   │   │   ├── __init__.py
│   │   │   ├── market_gateway_port.py
│   │   │   ├── ai_provider_port.py
│   │   │   ├── broker_port.py
│   │   │   ├── cache_port.py
│   │   │   ├── repository_port.py
│   │   │   ├── notification_port.py
│   │   │   ├── compliance_port.py
│   │   │   ├── knowledge_base_port.py
│   │   │   ├── plugin_registry_port.py     # [v3] 插件注册中心端口
│   │   │   └── message_queue_port.py
│   │   └── events/
│   │       ├── __init__.py
│   │       ├── market_events.py
│   │       ├── trading_events.py
│   │       ├── signal_events.py
│   │       ├── agent_events.py             # [v3] Agent 事件
│   │       └── risk_events.py
│   │
│   ├── application/
│   │   ├── __init__.py
│   │   ├── use_cases/
│   │   │   ├── __init__.py
│   │   │   ├── market_data_use_cases.py
│   │   │   ├── strategy_use_cases.py
│   │   │   ├── trading_use_cases.py
│   │   │   ├── backtest_use_cases.py
│   │   │   ├── research_use_cases.py          # [v3] 研究用例（Agent 驱动）
│   │   │   ├── portfolio_use_cases.py
│   │   │   ├── risk_use_cases.py
│   │   │   ├── scanner_use_cases.py
│   │   │   ├── research_pipeline_use_cases.py
│   │   │   └── system_use_cases.py
│   │   ├── dto/
│   │   │   ├── __init__.py
│   │   │   ├── requests.py
│   │   │   └── responses.py
│   │   └── event_handlers/
│   │       ├── __init__.py
│   │       ├── market_handlers.py
│   │       ├── trading_handlers.py
│   │       ├── agent_handlers.py             # [v3] Agent 事件处理
│   │       └── risk_handlers.py
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── plugin_registry/                  # [v3核心] 插件注册中心
│   │   │   ├── __init__.py
│   │   │   ├── registry.py                   #   注册中心核心
│   │   │   ├── loader.py                     #   插件发现与加载
│   │   │   ├── validator.py                  #   插件校验
│   │   │   ├── lifecycle.py                  #   插件生命周期管理
│   │   │   └── metadata.py                   #   插件元数据
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── market_gateway/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── gateway.py                #   MarketGateway（只知道 PluginRegistry）
│   │   │   │   ├── base.py                   #   适配器基类
│   │   │   │   └── factory.py                #   从 Registry 创建适配器
│   │   │   ├── ai_providers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   ├── deepseek_adapter.py
│   │   │   │   ├── openai_adapter.py
│   │   │   │   └── factory.py
│   │   │   ├── brokers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   ├── simnow_adapter.py
│   │   │   │   └── factory.py
│   │   │   └── notifications/
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── email_adapter.py
│   │   │       ├── wechat_adapter.py
│   │   │       └── factory.py
│   │   ├── agents/                            # [v3核心] AI Agent 层
│   │   │   ├── __init__.py
│   │   │   ├── base.py                        #   Agent 基类
│   │   │   ├── planner.py                     #   规划 Agent
│   │   │   ├── researcher.py                  #   研究 Agent（找数据）
│   │   │   ├── analyst.py                     #   分析 Agent（评分）
│   │   │   ├── reviewer.py                    #   审查 Agent（检查幻觉）
│   │   │   ├── reporter.py                    #   报告 Agent（生成日报/周报/研报）
│   │   │   ├── context_builder.py             #   Agent 上下文构建器
│   │   │   └── tool_provider.py               #   Agent 可用工具集
│   │   ├── compliance/
│   │   │   ├── __init__.py
│   │   │   ├── datasource_policy.py
│   │   │   ├── datasource_validator.py
│   │   │   ├── license_checker.py
│   │   │   ├── capability_checker.py          # [v3] 能力声明检查 + 自动路由
│   │   │   ├── rate_limit.py
│   │   │   └── audit_logger.py
│   │   ├── repositories/
│   │   │   └── ...
│   │   ├── orm/
│   │   │   ├── ...
│   │   │   ├── plugin_manifest_orm.py         # [v3]
│   │   │   ├── research_session_orm.py        # [v3]
│   │   │   └── agent_task_orm.py              # [v3]
│   │   ├── cache/
│   │   │   └── ...
│   │   └── external/
│   │       └── ...
│   │
│   ├── signals/                               # [v3重构] 信号插件化
│   │   ├── __init__.py
│   │   ├── base.py                            #   信号基类（实现 PluginProtocol）
│   │   ├── registry.py                        #   信号注册表
│   │   ├── fusion.py                          #   Signal Fusion（不改）
│   │   ├── builtin/                           #   内置信号
│   │   │   ├── __init__.py
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
│   │   ├── custom/                            #   用户自定义信号（丢进来就识别）
│   │   │   ├── __init__.py
│   │   │   └── _template.py                   #   信号模板
│   │   └── ml/                                #   机器学习信号
│   │       ├── __init__.py
│   │       ├── base_ml.py                     #   ML信号基类
│   │       ├── xgboost_signal.py              #   XGBoost 信号
│   │       ├── lightgbm_signal.py             #   LightGBM 信号
│   │       └── transformer_signal.py          #   Transformer 信号
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── dependencies.py
│   │   ├── middleware/
│   │   │   └── ...
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── market_data_routes.py
│   │       ├── strategy_routes.py
│   │       ├── trading_routes.py
│   │       ├── backtest_routes.py
│   │       ├── research_routes.py             # [v3] Agent 驱动的研究
│   │       ├── portfolio_routes.py
│   │       ├── risk_routes.py
│   │       ├── scanner_routes.py
│   │       ├── research_pipeline_routes.py
│   │       ├── plugin_routes.py               # [v3] 插件管理 API
│   │       └── system_routes.py
│   │
│   └── shared/
│       ├── __init__.py
│       ├── types.py
│       ├── constants.py
│       ├── exceptions.py
│       ├── plugin_protocol.py                 # [v3] 插件协议基类
│       ├── utils/
│       │   └── ...
│       └── decorators.py
│
├── plugins/                                   # [v3核心] 插件目录
│   ├── README.md                              #   插件开发指南
│   │
│   ├── datasource/                            #   数据源插件
│   │   ├── akshare/                           #     每个插件一个目录
│   │   │   ├── plugin.yaml                    #       插件清单
│   │   │   ├── __init__.py
│   │   │   └── adapter.py                     #       适配器实现
│   │   ├── tushare/
│   │   │   ├── plugin.yaml
│   │   │   ├── __init__.py
│   │   │   └── adapter.py
│   │   ├── yahoo/
│   │   │   ├── plugin.yaml
│   │   │   ├── __init__.py
│   │   │   └── adapter.py
│   │   ├── polygon/
│   │   │   ├── plugin.yaml
│   │   │   ├── __init__.py
│   │   │   └── adapter.py
│   │   ├── alpha_vantage/
│   │   │   ├── plugin.yaml
│   │   │   ├── __init__.py
│   │   │   └── adapter.py
│   │   └── _template/                         #   数据源插件开发模板
│   │       ├── plugin.yaml
│   │       ├── __init__.py
│   │       └── adapter.py
│   │
│   └── signal/                                #   信号插件（未来可扩展）
│       └── _template/
│           ├── plugin.yaml
│           └── signal.py
│
├── knowledge/                                 # [v3扩展] 知识库
│   ├── README.md
│   │
│   ├── industry/                              #   行业知识
│   │   ├── index.yaml
│   │   ├── semiconductor.yaml
│   │   ├── new_energy.yaml
│   │   └── ...
│   │
│   ├── macro/                                 #   宏观经济
│   │   ├── gdp.yaml
│   │   ├── monetary_policy.yaml
│   │   └── ...
│   │
│   ├── concepts/                              #   概念板块
│   │   ├── index.yaml
│   │   └── ...
│   │
│   ├── finance/                               #   财务知识
│   │   ├── financial_statements.yaml
│   │   └── ...
│   │
│   ├── reports/                               # [v3新增] 研报分析方法论
│   │   ├── how_to_read_research_report.yaml   #     如何读研报
│   │   ├── common_fallacies.yaml              #     常见分析谬误
│   │   └── rating_systems.yaml                #     评级体系解读
│   │
│   ├── policy/                                # [v3新增] 政策解读框架
│   │   ├── monetary_policy_impact.yaml        #     货币政策影响传导
│   │   ├── fiscal_policy_impact.yaml          #     财政政策影响传导
│   │   ├── industry_regulation.yaml           #     行业监管政策
│   │   └── five_year_plan.yaml                #     五年规划解读
│   │
│   ├── strategy/                              # [v3新增] 策略知识
│   │   ├── trend_following.yaml               #     趋势跟踪
│   │   ├── mean_reversion.yaml                #     均值回归
│   │   ├── momentum.yaml                      #     动量策略
│   │   ├── event_driven.yaml                  #     事件驱动
│   │   └── risk_parity.yaml                   #     风险平价
│   │
│   ├── books/                                 # [v3新增] 经典书籍摘要
│   │   ├── intelligent_investor.yaml          #     聪明的投资者
│   │   ├── market_wizards.yaml                #     金融怪杰
│   │   └── ...
│   │
│   ├── papers/                                # [v3新增] 重要论文摘要
│   │   ├── fama_french.yaml                   #     三因子模型
│   │   ├── momentum_anomaly.yaml              #     动量异象
│   │   └── ...
│   │
│   └── glossary/                              #   术语表
│       ├── technical_terms.yaml
│       └── ...
│
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   │   ├── test_plugin_registry.py        # [v3]
│   │   │   ├── test_agents.py                 # [v3]
│   │   │   └── test_capability_checker.py     # [v3]
│   │   └── signals/
│   ├── integration/
│   └── e2e/
│
├── scripts/
│   ├── init_database.py
│   ├── register_plugins.py                    # [v3] 插件注册脚本
│   ├── validate_plugins.py                    # [v3] 插件校验脚本
│   ├── run_research_pipeline.py
│   ├── build_knowledge_base.py
│   └── ...
│
├── vscode-ext/                                # 纯 UI
├── web/                                       # 后期
├── deploy/
└── data/
```

---

## 5. 每个目录职责

| 目录 | 职责 | v3 变更 |
|------|------|---------|
| `plugins/` | **插件目录** — 数据源/信号等的物理存放位置 | **新增**: 丢进去就能识别 |
| `plugins/datasource/` | 数据源插件 — 每个插件一个子目录 + `plugin.yaml` | **新增** |
| `src/infrastructure/plugin_registry/` | **插件注册中心** — 发现/加载/校验/生命周期管理 | **新增核心模块** |
| `src/infrastructure/agents/` | **AI Agent 层** — Planner/Researcher/Analyst/Reviewer/Reporter | **新增核心模块** |
| `src/domain/services/agent_orchestrator.py` | **Agent 编排器** — 协调 5 个 Agent 协作 | **新增核心模块** |
| `src/signals/builtin/` | 内置信号（MACD/RSI/KDJ...） | **重构**: 从平铺 → builtin/ 子目录 |
| `src/signals/custom/` | 用户自定义信号（丢进来就识别） | **新增** |
| `src/signals/ml/` | ML 信号（XGBoost/LightGBM/Transformer） | **新增** |
| `knowledge/reports/` | 研报分析方法论 | **新增** |
| `knowledge/policy/` | 政策解读框架 | **新增** |
| `knowledge/strategy/` | 策略知识库 | **新增** |
| `knowledge/books/` | 经典投资书籍摘要 | **新增** |
| `knowledge/papers/` | 重要学术论文摘要 | **新增** |
| `src/shared/plugin_protocol.py` | 插件协议基类 — 所有插件的抽象 | **新增** |

---

## 6. 每个模块职责

### 6.1 Plugin Registry — 插件注册中心（v3 核心）

```
┌──────────────────────────────────────────────────────────────┐
│                  Plugin Registry 架构                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                  PluginRegistry                          │ │
│  │                                                          │ │
│  │  register(plugin)     ← 注册插件                         │ │
│  │  discover()           ← 自动发现 plugins/ 目录下的插件    │ │
│  │  get(name)            ← 按名称获取插件                    │ │
│  │  list_by_type(type)   ← 按类型列出插件                    │ │
│  │  validate(plugin)     ← 校验插件合法性                    │ │
│  │  get_capability(name) ← 获取插件能力声明                  │ │
│  │  enable(name)         ← 启用插件                         │ │
│  │  disable(name)        ← 禁用插件                         │ │
│  │  reload()             ← 热重载插件                        │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  插件类型:                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │DataSource│ │ Signal   │ │ Agent    │ │ Notification │    │
│  │ Plugin   │ │ Plugin   │ │ Plugin   │ │ Plugin       │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │
│                                                               │
│  发现机制:                                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 1. 扫描 plugins/ 目录                                     │ │
│  │ 2. 找到所有 plugin.yaml                                   │ │
│  │ 3. 解析清单 → 校验格式 → 校验能力声明                       │ │
│  │ 4. 动态加载 Python 模块                                    │ │
│  │ 5. 实例化 → 注册到 Registry                               │ │
│  │ 6. MarketGateway/SignalFusion 从 Registry 获取插件列表     │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**插件清单格式** (`plugin.yaml`):

```yaml
# plugins/datasource/akshare/plugin.yaml

plugin:
  name: "akshare"
  version: "1.0.0"
  type: "datasource"
  display_name: "AKShare 数据源"
  description: "基于 AKShare 的 A 股免费数据源"
  author: "QuantAI Team"
  license: "MIT"

  entry_point: "adapter:AKShareAdapter"    # Python 入口
  dependencies: ["akshare>=1.12.0"]        # 依赖声明
  python_version: ">=3.12"

  capabilities:                             # [v3核心] 能力声明
    supports_realtime: true
    supports_intraday: true                 # 支持分钟线
    supports_history: true
    supports_financials: true
    supports_lhb: true                      # 龙虎榜
    supports_fund_flow: true                # 资金流向
    supports_news: false                    # 不直接支持新闻
    supports_ai_analysis: true
    supports_cache: true                    # 允许缓存
    supports_commercial: true               # 允许商业使用
    rate_limit_per_minute: 60
    data_quality: "good"                    # basic/good/excellent
    coverage_markets: ["SH", "SZ", "BJ"]    # 覆盖市场
    latency: "t+0"                          # 数据延迟

  compliance:                                # 合规声明
    is_legal: true
    allow_commercial: true
    allow_cache: true
    allow_redis: true
    allow_ai_analysis: true
    allow_long_term_storage: true
    require_attribution: false
    data_retention_days: 0
```

### 6.2 DataSourceCapability — 能力声明 + 自动路由（v3 核心）

```
┌──────────────────────────────────────────────────────────────┐
│            DataSourceCapability 自动路由                      │
│                                                               │
│  以前（if-else 地狱）:                                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ if need_lhb:                                            │ │
│  │     if source == "akshare":                             │ │
│  │         return akshare.get_lhb()                        │ │
│  │     elif source == "tushare":                           │ │
│  │         return tushare.get_lhb()                        │ │
│  │     elif ...   ← 每次新增数据源要改这里                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  现在（能力声明 + 自动路由）:                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ # system needs: lhb_data                                │ │
│  │ matched = registry.find_by_capability(                   │ │
│  │     capability="supports_lhb",                          │ │
│  │     value=True,                                         │ │
│  │ )                                                       │ │
│  │ # matched = [akshare, tushare]  ← 自动发现              │ │
│  │ # 按优先级选择 → 调用 → 完成                              │ │
│  │ # 新增数据源只需声明 supports_lhb: true                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  DataSourceCapability 枚举:                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ supports_realtime       # 实时行情                       │ │
│  │ supports_intraday       # 分钟级数据                     │ │
│  │ supports_history        # 历史日线                       │ │
│  │ supports_financials     # 财务报表                       │ │
│  │ supports_lhb            # 龙虎榜                         │ │
│  │ supports_fund_flow      # 资金流向（北向/主力）           │ │
│  │ supports_news           # 新闻/公告                      │ │
│  │ supports_indices        # 指数行情                       │ │
│  │ supports_sectors        # 板块行情                       │ │
│  │ supports_ai_analysis    # 可用于AI分析                   │ │
│  │ supports_cache          # 允许缓存                       │ │
│  │ supports_commercial     # 允许商业使用                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 6.3 AI Agent Layer — 智能体层（v3 核心新增）

```
┌──────────────────────────────────────────────────────────────┐
│                    AI Agent Layer                             │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              AgentOrchestrator (编排器)                   │ │
│  │                                                          │ │
│  │  接收: 用户研究请求                                       │ │
│  │  输出: 研究报告                                           │ │
│  │                                                          │ │
│  │  内部流程:                                                │ │
│  │                                                          │ │
│  │  ┌──────────┐                                           │ │
│  │  │ Planner  │ ← 理解用户意图，制定研究计划                 │ │
│  │  │ 规划者   │   输出: ResearchPlan (步骤列表)              │ │
│  │  └────┬─────┘                                           │ │
│  │       │ plan                                             │ │
│  │       ▼                                                  │ │
│  │  ┌──────────┐                                           │ │
│  │  │Researcher│ ← 按计划收集数据                            │ │
│  │  │ 研究员   │   调用: MarketGateway / Knowledge / News    │ │
│  │  │          │   输出: ResearchData (结构化数据集)          │ │
│  │  └────┬─────┘                                           │ │
│  │       │ data                                             │ │
│  │       ▼                                                  │ │
│  │  ┌──────────┐                                           │ │
│  │  │ Analyst  │ ← 分析数据 + Signal Fusion 评分             │ │
│  │  │ 分析师   │   调用: SignalEngine / 知识库 / LLM         │ │
│  │  │          │   输出: AnalysisResult (评分+逻辑+证据)      │ │
│  │  └────┬─────┘                                           │ │
│  │       │ analysis                                         │ │
│  │       ▼                                                  │ │
│  │  ┌──────────┐                                           │ │
│  │  │ Reviewer │ ← 审查分析结果                              │ │
│  │  │ 审查员   │   检查: 幻觉/逻辑漏洞/数据支撑/过度推断      │ │
│  │  │          │   输出: ReviewResult (通过/驳回+修改建议)    │ │
│  │  └────┬─────┘                                           │ │
│  │       │ reviewed                                         │ │
│  │       ▼                                                  │ │
│  │  ┌──────────┐                                           │ │
│  │  │ Reporter │ ← 生成最终报告                              │ │
│  │  │ 报告员   │   输出: ResearchReport (Markdown/PDF)       │ │
│  │  │          │   推送: VSCode / Email / WeChat             │ │
│  │  └──────────┘                                           │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  每个 Agent 可独立配置 LLM:                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Planner   → DeepSeek-V3  (便宜，规划不需要太强推理)       │ │
│  │ Researcher→ 不需要 LLM     (纯函数调用)                   │ │
│  │ Analyst   → DeepSeek-R1  (需要强推理)                    │ │
│  │ Reviewer  → Claude Opus   (需要严谨的逻辑检查)            │ │
│  │ Reporter  → DeepSeek-V3  (格式化输出)                    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**Agent 基类**:

```python
# src/infrastructure/agents/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class AgentContext:
    """Agent 执行上下文"""
    session_id: str
    user_query: str
    previous_results: dict       # 上游 Agent 的输出
    available_tools: list[str]   # 可调用的工具列表
    knowledge_context: str       # 知识库上下文
    budget_tokens: int           # Token 预算

@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    output: dict                 # 结构化输出
    tokens_used: int
    tools_called: list[str]
    thinking_trace: str          # 思考过程（可审计）
    errors: list[str]

class BaseAgent(ABC):
    """Agent 基类 —— 所有 Agent 必须实现"""

    name: str
    description: str
    llm_model: str               # 默认使用的 LLM
    tools: list[str]             # 可用工具列表

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        """执行 Agent 任务"""
        ...

    @abstractmethod
    def get_system_prompt(self) -> str:
        """获取 Agent 的系统提示词"""
        ...
```

**Planner Agent 示例**:

```python
# src/infrastructure/agents/planner.py

class PlannerAgent(BaseAgent):
    name = "planner"
    description = "理解用户意图，制定研究计划"
    llm_model = "deepseek-v3"

    async def execute(self, context: AgentContext) -> AgentResult:
        """
        输入: "分析京东方A的投资价值"
        输出: ResearchPlan(
            steps=[
                "1. 收集京东方A的基本信息（市值/行业/财务）",
                "2. 加载面板行业知识库",
                "3. 计算技术指标信号",
                "4. 获取北向资金和龙虎榜数据",
                "5. 获取近期新闻和公告",
                "6. 融合评分",
                "7. 深度分析",
                "8. 审查结果",
                "9. 生成报告"
            ],
            estimated_tokens=3500,
            data_sources=["akshare", "tushare"],
            knowledge_modules=["industry/semiconductor", "macro/monetary_policy"],
            signal_modules=["macd", "rsi", "capital", "lhb", "news"],
        )
        """
```

### 6.4 Knowledge Base — v3 扩展

```
knowledge/
│
├── industry/          # 行业知识 (v2已有)
├── macro/             # 宏观经济 (v2已有)
├── concepts/          # 概念板块 (v2已有)
├── finance/           # 财务知识 (v2已有)
│
├── reports/           # [v3新增] 研报分析方法论
│   ├── how_to_read_research_report.yaml
│   │   """
│   │   卖方研报的结构：摘要→公司概况→行业分析→财务分析→盈利预测→估值→风险提示
│   │   关键阅读技巧：看评级变化不看绝对值/看逻辑不看结论/看风险提示部分
│   │   """
│   ├── common_fallacies.yaml
│   │   """
│   │   常见分析谬误：幸存者偏差/后见之明/过度拟合/确认偏误/锚定效应
│   │   """
│   └── rating_systems.yaml
│       """
│       券商评级体系：买入/增持/中性/减持/卖出 → 实际含义与统计分布
│       """
│
├── policy/            # [v3新增] 政策解读框架
│   ├── monetary_policy_impact.yaml
│   │   """
│   │   降准/降息 → 银行间流动性 → 信贷扩张 → 实体企业 → 股市
│   │   传导时间：降准 T+1月 / 降息 T+3月 / LPR调整 T+1周
│   │   受益板块：银行（降准）/ 地产（降息）/ 券商（流动性）
│   │   """
│   ├── fiscal_policy_impact.yaml
│   ├── industry_regulation.yaml
│   └── five_year_plan.yaml
│
├── strategy/          # [v3新增] 策略知识
│   ├── trend_following.yaml
│   │   """
│   │   核心逻辑：趋势一旦形成，更可能延续而非反转
│   │   入场：均线多头排列 + MACD金叉 + 放量突破
│   │   出场：均线死叉 或 最高点回撤8%
│   │   适用：牛市/震荡市上行段
│   │   不适用：熊市/剧烈震荡
│   │   """
│   ├── mean_reversion.yaml
│   ├── momentum.yaml
│   ├── event_driven.yaml
│   └── risk_parity.yaml
│
├── books/             # [v3新增] 经典书籍摘要
│   ├── intelligent_investor.yaml
│   │   """
│   │   核心概念：安全边际 / 市场先生 / 内在价值
│   │   对A股的启示：...
│   │   """
│   └── market_wizards.yaml
│
├── papers/            # [v3新增] 学术论文摘要
│   ├── fama_french.yaml
│   │   """
│   │   Fama-French 三因子模型 (1993)
│   │   因子：市场风险 + 规模(SMB) + 价值(HML)
│   │   A股实证：...
│   │   """
│   └── momentum_anomaly.yaml
│
└── glossary/          # 术语表 (v2已有)
```

**v3 AI Prompt 上下文（升级后）**:

```
传统 Prompt (v1):
  K线数据 + "请分析京东方A"

v3 Prompt (升级后):
  ┌────────────────────────────────────────┐
  │ ## 知识库上下文                          │
  │                                        │
  │ ### 行业知识 (knowledge/industry/)       │
  │ 面板行业处于周期上行阶段...               │
  │                                        │
  │ ### 政策背景 (knowledge/policy/)         │
  │ 最新货币政策：降准25bp...                │
  │                                        │
  │ ### 策略框架 (knowledge/strategy/)       │
  │ 趋势跟踪策略在面板行业的适用性...          │
  │                                        │
  │ ### 学术依据 (knowledge/papers/)          │
  │ Fama-French 模型在A股面板行业的实证...    │
  │                                        │
  │ ### 历史案例 (knowledge/books/)          │
  │ 类似周期行业的投资案例...                 │
  │                                        │
  │ ## 实时数据                              │
  │ 行情 + 信号评分 + 资金流向 + 龙虎榜       │
  │                                        │
  │ ## 请基于以上信息进行分析                 │
  └────────────────────────────────────────┘
```

---

## 7. 数据库设计

### 7.1 v3 新增表

#### plugin_manifests（插件清单表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `plugin_name` | VARCHAR(100) | NOT NULL, UNIQUE | 插件名称 |
| `plugin_type` | VARCHAR(50) | NOT NULL | 类型：datasource/signal/agent/notification/broker |
| `version` | VARCHAR(20) | NOT NULL | 版本号 |
| `display_name` | VARCHAR(200) | | 显示名称 |
| `description` | TEXT | | 描述 |
| `author` | VARCHAR(100) | | 作者 |
| `entry_point` | VARCHAR(200) | NOT NULL | Python入口 |
| `manifest_yaml` | TEXT | NOT NULL | 完整 plugin.yaml 内容 |
| `capabilities_json` | TEXT | | 能力声明 JSON |
| `is_enabled` | BOOLEAN | DEFAULT TRUE | 是否启用 |
| `is_valid` | BOOLEAN | DEFAULT TRUE | 校验是否通过 |
| `validation_errors` | TEXT | | 校验错误信息 |
| `loaded_at` | DATETIME | | 加载时间 |
| `created_at` | DATETIME | DEFAULT NOW | |
| `updated_at` | DATETIME | DEFAULT NOW | |

#### research_sessions（研究会话表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `user_query` | TEXT | NOT NULL | 用户原始问题 |
| `research_plan_json` | TEXT | | Planner 生成的计划 |
| `status` | VARCHAR(20) | NOT NULL | planning/researching/analyzing/reviewing/reporting/completed/failed |
| `current_agent` | VARCHAR(50) | | 当前执行的 Agent |
| `total_tokens_used` | INTEGER | DEFAULT 0 | 总 Token 消耗 |
| `report_path` | VARCHAR(500) | | 最终报告路径 |
| `started_at` | DATETIME | | |
| `completed_at` | DATETIME | | |
| `created_at` | DATETIME | DEFAULT NOW | |

#### agent_tasks（Agent 任务表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `session_id` | INTEGER | FK → research_sessions.id | 所属会话 |
| `agent_name` | VARCHAR(50) | NOT NULL | planner/researcher/analyst/reviewer/reporter |
| `agent_model` | VARCHAR(50) | | 使用的 LLM 模型 |
| `input_json` | TEXT | | Agent 输入 |
| `output_json` | TEXT | | Agent 输出 |
| `tokens_used` | INTEGER | | Token 消耗 |
| `tools_called_json` | TEXT | | 调用的工具 |
| `thinking_trace` | TEXT | | 思考过程 |
| `status` | VARCHAR(20) | NOT NULL | pending/running/completed/failed |
| `error_message` | TEXT | | |
| `started_at` | DATETIME | | |
| `completed_at` | DATETIME | | |
| `created_at` | DATETIME | DEFAULT NOW | |

（其余表 stocks / market_data / strategies / orders / positions / accounts / portfolios / backtests / ai_analyses / risk_rules / signals / notifications / system_logs / compliance_records / knowledge_entries / signal_scores / fusion_scores / research_pipeline_runs 保持不变，参见 v2 文档）

---

## 8. 数据流设计

### 8.1 v3 Agent 驱动的研究流程（核心新增）

```
用户发起研究请求
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│                  AgentOrchestrator                            │
│                                                               │
│  Step 1: Planner Agent                                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 输入: "分析面板行业的投资机会"                              │ │
│  │ LLM: DeepSeek-V3 (轻量)                                  │ │
│  │ 输出: ResearchPlan {                                     │ │
│  │   stocks: ["000725.SZ", "000100.SZ", "002475.SZ"],       │ │
│  │   knowledge: ["industry/semiconductor", "policy/..."],   │ │
│  │   signals: ["macd", "capital", "lhb", "news"],           │ │
│  │   data_sources: ["akshare"],                             │ │
│  │   analysis_angle: "周期位置+估值+资金面"                   │ │
│  │ }                                                        │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼                                                       │
│  Step 2: Researcher Agent (纯函数，不调 LLM)                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 按 ResearchPlan 并行拉取数据:                              │ │
│  │ · MarketGateway.get_kline()       → 3只股票日K线          │ │
│  │ · MarketGateway.get_financials()  → 财务数据              │ │
│  │ · MarketGateway.get_capital_flow()→ 北向资金              │ │
│  │ · MarketGateway.get_lhb_data()    → 龙虎榜                │ │
│  │ · MarketGateway.get_news()        → 新闻                  │ │
│  │ · KnowledgeBase.get_industry()    → 面板行业知识           │ │
│  │ · KnowledgeBase.get_policy()      → 相关政策               │ │
│  │ 输出: ResearchData { structured_data }                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼                                                       │
│  Step 3: Analyst Agent                                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 对每只股票:                                                │ │
│  │ · 运行 Signal Fusion (Python 计算)                        │ │
│  │ · 加载 Knowledge 上下文                                    │ │
│  │ · LLM: DeepSeek-R1 (强推理)                               │ │
│  │ · 分析: 技术面+基本面+资金面+行业位置+风险                  │ │
│  │ 输出: AnalysisResult {                                    │ │
│  │   stock: "000725.SZ",                                     │ │
│  │   score: 91.8,                                            │ │
│  │   reasoning: "面板价格Q3预期上涨15%...",                    │ │
│  │   evidence: ["北向连续5日流入", "MACD周线金叉", ...],       │ │
│  │   risks: ["面板价格不及预期", "下游需求疲软"],              │ │
│  │ }                                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼                                                       │
│  Step 4: Reviewer Agent                                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 审查 Analyst 的输出:                                       │ │
│  │ · 逻辑是否自洽？                                           │ │
│  │ · 证据是否支撑结论？                                       │ │
│  │ · 是否存在幻觉（编造数据）？                                │ │
│  │ · 是否过度推断？                                           │ │
│  │ · 风险是否被低估？                                         │ │
│  │ LLM: Claude Opus / DeepSeek-R1 (严谨)                      │ │
│  │ 输出: ReviewResult { passed: true/false, issues: [...] }   │ │
│  │                                                           │ │
│  │ 如果 passed=false → 返回 Step 3 重新分析                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼                                                       │
│  Step 5: Reporter Agent                                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 生成结构化研究报告:                                         │ │
│  │ # 面板行业研究日报                                         │ │
│  │ ## 摘要                                                   │ │
│  │ ## 行业概况                                               │ │
│  │ ## 重点标的分析                                            │ │
│  │ ## 信号评分汇总                                            │ │
│  │ ## 风险提示                                               │ │
│  │ ## 证据链                                                 │ │
│  │ LLM: DeepSeek-V3                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│       │                                                       │
│       ▼                                                       │
│  输出: ResearchReport (Markdown + PDF)                         │
│  推送: VSCode / Email / WeChat                                 │
│  持久化: research_sessions + agent_tasks 表                     │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 Plugin Registry 数据流

```
应用启动
    │
    ▼
┌────────────────────────────────────────────┐
│         PluginRegistry.discover()           │
│                                             │
│  1. 扫描 plugins/ 目录                       │
│     ├── plugins/datasource/akshare/         │
│     │   └── plugin.yaml ← 发现              │
│     ├── plugins/datasource/tushare/         │
│     │   └── plugin.yaml ← 发现              │
│     └── ...                                 │
│                                             │
│  2. 解析每个 plugin.yaml                     │
│     ├── 校验格式                             │
│     ├── 提取 capabilities                   │
│     └── 校验合规声明                          │
│                                             │
│  3. 动态加载 Python 模块                     │
│     importlib.import_module(entry_point)    │
│                                             │
│  4. 实例化 + 注册                            │
│     registry.register(akshare_plugin)       │
│     registry.register(tushare_plugin)       │
│                                             │
│  5. MarketGateway 查询 Registry              │
│     adapters = registry.list_by_type("datasource")  │
│     # MarketGateway 不需要知道具体有哪些      │
│                                             │
│  6. 按需路由                                 │
│     # 需要龙虎榜数据                          │
│     candidates = registry.find_by_capability(│
│         type="datasource",                  │
│         capability="supports_lhb",          │
│         value=True                          │
│     )                                       │
│     # 自动选择最优的                          │
└────────────────────────────────────────────┘
```

---

## 9. AI Agent 层设计（核心新增）

### 9.1 Agent 协作模式

```
┌──────────────────────────────────────────────────────────────┐
│                  Agent 协作模式                                │
│                                                               │
│  模式 1: 线性流水线 (默认)                                     │
│  Planner → Researcher → Analyst → Reviewer → Reporter         │
│  适用: 标准研究任务                                            │
│                                                               │
│  模式 2: Reviewer 驳回循环                                     │
│  Analyst → Reviewer → (驳回) → Analyst → Reviewer → (通过)    │
│  适用: 需要高质量保证的分析                                     │
│                                                               │
│  模式 3: 并行 Analyst                                         │
│                    ┌→ Analyst(技术面) ─┐                      │
│  Planner → Researcher → Analyst(基本面) → Reviewer → Reporter │
│                    └→ Analyst(资金面) ─┘                      │
│  适用: 多维度独立分析                                          │
│                                                               │
│  模式 4: 轻量模式                                              │
│  Planner → Analyst → Reporter                                 │
│  适用: 快速查询（跳过 Researcher 和 Reviewer）                  │
└──────────────────────────────────────────────────────────────┘
```

### 9.2 Agent 与 LLM 的解耦

```python
# 每个 Agent 可以独立选择 LLM
# 新增 LLM 只需实现 AIPort

AGENT_LLM_MAPPING = {
    "planner": {
        "default": "deepseek-v3",       # 规划不需要太强推理
        "fallback": "gpt-4o-mini",
    },
    "researcher": {
        "default": None,                # 不需要 LLM，纯函数
    },
    "analyst": {
        "default": "deepseek-r1",       # 需要强推理
        "fallback": "claude-opus-4-8",
    },
    "reviewer": {
        "default": "deepseek-r1",       # 需要严谨性
        "fallback": "claude-haiku-4-5",
    },
    "reporter": {
        "default": "deepseek-v3",       # 格式化输出
        "fallback": "gpt-4o",
    },
}
```

---

## 10. Plugin Registry 设计（核心新增）

### 10.1 插件协议

```python
# src/shared/plugin_protocol.py

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class PluginType(Enum):
    DATASOURCE = "datasource"
    SIGNAL = "signal"
    AGENT = "agent"
    NOTIFICATION = "notification"
    BROKER = "broker"


@dataclass
class PluginManifest:
    """插件清单 —— 从 plugin.yaml 解析"""
    name: str
    version: str
    type: PluginType
    display_name: str
    description: str
    author: str
    entry_point: str
    dependencies: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)


class BasePlugin(ABC):
    """所有插件的基类"""

    manifest: PluginManifest

    @abstractmethod
    async def initialize(self) -> bool:
        """初始化插件"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """优雅关闭"""
        ...


class DataSourcePlugin(BasePlugin):
    """数据源插件协议"""

    @abstractmethod
    def get_capabilities(self) -> dict:
        """返回能力声明"""
        ...

    @abstractmethod
    async def query(self, method: str, **params) -> dict:
        """统一查询接口"""
        ...


class SignalPlugin(BasePlugin):
    """信号插件协议"""

    @abstractmethod
    async def compute(self, stock_code: str, context: dict) -> dict:
        """计算信号"""
        ...

    @abstractmethod
    async def compute_batch(self, stock_codes: list[str], context: dict) -> list[dict]:
        """批量计算"""
        ...
```

### 10.2 插件生命周期

```
┌──────────────────────────────────────────────┐
│            Plugin Lifecycle                   │
│                                               │
│   DISCOVERED  → 插件被发现 (plugin.yaml 存在)  │
│       │                                       │
│       ▼                                       │
│   VALIDATED   → 校验格式/能力/合规             │
│       │                                       │
│       ├── 失败 → DISABLED (记录错误)           │
│       │                                       │
│       ▼                                       │
│   LOADED      → Python 模块加载成功            │
│       │                                       │
│       ▼                                       │
│   INITIALIZED → initialize() 调用成功          │
│       │                                       │
│       ▼                                       │
│   ACTIVE      → 可正常使用                     │
│       │                                       │
│       ├── health_check 失败 → DEGRADED        │
│       ├── disable() → DISABLED               │
│       └── shutdown() → STOPPED               │
└──────────────────────────────────────────────┘
```

---

## 11. 插件通信流程

（v2 的 VSCode 纯 UI 定位保持不变。v3 新增 Plugin Management API）

```
VSCode Extension
    │
    │ IPC (JSON-RPC)
    ▼
Python Server
    │
    ├── GET  /api/v1/plugins                   列出所有插件
    ├── GET  /api/v1/plugins/{name}            插件详情
    ├── POST /api/v1/plugins/{name}/enable     启用插件
    ├── POST /api/v1/plugins/{name}/disable    禁用插件
    ├── POST /api/v1/plugins/reload            热重载所有插件
    ├── POST /api/v1/plugins/validate          校验插件
    │
    ├── POST /api/v1/research/start            启动 Agent 研究
    ├── GET  /api/v1/research/{session_id}     查询研究进度
    ├── GET  /api/v1/research/{session_id}/report  获取研究报告
    └── WS   /ws/research/{session_id}         实时 Stream Agent 思考过程
```

---

## 12. 配置管理

```python
# config/settings.py v3 新增

class Settings(BaseSettings):
    # ... (v1+v2 所有配置保持不变) ...

    # ---- [v3新增] Plugin Registry ----
    PLUGIN_ENABLED: bool = True
    PLUGIN_DIRS: list[str] = ["plugins/datasource", "plugins/signal"]
    PLUGIN_AUTO_DISCOVER: bool = True          # 启动时自动发现
    PLUGIN_HOT_RELOAD: bool = False            # 开发模式热重载
    PLUGIN_STRICT_VALIDATION: bool = True      # 严格校验模式

    # ---- [v3新增] Agent 配置 ----
    AGENT_ENABLED: bool = True
    AGENT_DEFAULT_MODE: str = "pipeline"        # pipeline / parallel / lite
    AGENT_MAX_REVIEW_RETRIES: int = 2           # Reviewer 驳回最大重试次数
    AGENT_RESEARCH_TIMEOUT_SECONDS: int = 300   # 单次研究超时时间
    AGENT_LLM_MAPPING: dict = {                 # Agent → LLM 映射
        "planner": "deepseek-v3",
        "analyst": "deepseek-r1",
        "reviewer": "deepseek-r1",
        "reporter": "deepseek-v3",
    }

    # ---- [v3新增] DataSource 能力路由 ----
    DATASOURCE_ROUTING_STRATEGY: str = "priority"  # priority / quality / latency
```

---

## 13. 日志管理

（架构与 v1/v2 一致。v3 新增 Agent 执行日志）

```python
# Agent 思考过程独立日志
logger.add(
    "data/logs/agent_traces.log",
    format="{time} | {level} | {message}",
    level="DEBUG",
    rotation="50 MB",
    retention="30 days",
    filter=lambda record: record["extra"].get("category") == "agent",
)
```

---

## 14. 缓存方案

（与 v2 一致。v3 新增插件清单缓存）

| 数据类型 | L1(内存) | L2(Redis) | L3(磁盘) | 说明 |
|---------|---------|----------|---------|------|
| Plugin Manifest | ✅ 永久 | ✅ 24h | ✅ 永久 | 启动时加载，变更时刷新 |
| DataSource Capability | ✅ 永久 | ✅ 24h | ✅ 永久 | 能力声明不常变 |
| Agent Task Result | ❌ | ✅ 1h | ✅ 永久 | 相同查询复用 |

---

## 15. 未来扩展方案

### 15.1 扩展点总览

```
插件化后，扩展变得极其简单：

新增数据源:
  cp -r plugins/datasource/_template plugins/datasource/wind/
  编辑 plugin.yaml → 实现 adapter.py → 重启 → 自动识别

新增信号:
  cp src/signals/custom/_template.py src/signals/custom/my_signal.py
  实现 compute() → SignalFusion 自动发现

新增 Agent:
  继承 BaseAgent → 实现 execute() → 注册到 AgentOrchestrator

新增 LLM:
  实现 AIPort → 注册到 AIFactory → 所有 Agent 可选用

新增知识:
  在 knowledge/ 对应目录下新增 YAML → KnowledgeBase 自动加载
```

### 15.2 插件市场（远期设想）

```
未来可以建立社区插件市场:

plugins/
  datasource/
    akshare/         ← 官方
    tushare/         ← 官方
    wind/            ← 社区贡献
    bloomberg/       ← 社区贡献
  signal/
    my_custom_signal/ ← 用户自己写的
  agent/
    sentiment_agent/  ← 社区贡献的情绪分析Agent
```

---

## 16. 接口设计

### 16.1 PluginRegistryPort

```python
class PluginRegistryPort(ABC):
    """插件注册中心端口"""

    @abstractmethod
    async def discover(self) -> list[PluginManifest]:
        """自动发现所有插件"""
        ...

    @abstractmethod
    async def register(self, plugin: BasePlugin) -> bool:
        """注册插件"""
        ...

    @abstractmethod
    async def unregister(self, name: str) -> bool:
        """注销插件"""
        ...

    @abstractmethod
    async def get(self, name: str) -> Optional[BasePlugin]:
        """获取插件实例"""
        ...

    @abstractmethod
    async def list_by_type(self, plugin_type: PluginType) -> list[BasePlugin]:
        """按类型列出所有已激活插件"""
        ...

    @abstractmethod
    async def find_by_capability(
        self,
        plugin_type: PluginType,
        capability: str,
        value: Any = True,
    ) -> list[BasePlugin]:
        """按能力查找插件 —— 自动路由的核心"""
        ...

    @abstractmethod
    async def enable(self, name: str) -> bool:
        """启用插件"""
        ...

    @abstractmethod
    async def disable(self, name: str) -> bool:
        """禁用插件"""
        ...

    @abstractmethod
    async def reload(self) -> dict:
        """热重载所有插件 → 返回变更摘要"""
        ...
```

### 16.2 v3 新增 REST API

```
Plugin Management (插件管理)
├── GET    /plugins                         列出所有插件
├── GET    /plugins/{name}                  插件详情（含能力声明）
├── POST   /plugins/{name}/enable           启用
├── POST   /plugins/{name}/disable          禁用
├── POST   /plugins/reload                  热重载
├── POST   /plugins/validate                校验所有插件
└── GET    /plugins/capabilities/{capability}  按能力查找数据源

Agent Research (Agent 驱动研究)
├── POST   /research/start                  启动研究 (body: {query, mode})
├── GET    /research/{session_id}           研究会话状态
├── GET    /research/{session_id}/plan      Planner 输出
├── GET    /research/{session_id}/data      Researcher 输出
├── GET    /research/{session_id}/analysis  Analyst 输出
├── GET    /research/{session_id}/review    Reviewer 输出
├── GET    /research/{session_id}/report    Reporter 输出（最终报告）
├── DELETE /research/{session_id}           取消研究
├── GET    /research/history                研究历史
└── WS     /ws/research/{session_id}        Stream 实时进度
```

---

## 17. 模块依赖图（v3）

```
                          ┌──────────┐
                          │  shared  │ ← plugin_protocol.py (插件协议)
                          └────┬─────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
    ┌──────────┐       ┌─────────────┐      ┌──────────────┐
    │  domain  │◄──────│ application │      │infrastructure│
    │          │       │             │      │              │
    │ models   │       │ use_cases   │      │ plugin_      │
    │ services │       │ dto         │      │  registry/   │ ← [v3核心]
    │ ports    │       │ handlers    │      │ agents/      │ ← [v3核心]
    │ events   │       └─────────────┘      │ market_      │
    └──────────┘                            │  gateway/    │
         ▲                                  │ compliance/  │
         │                                  │ adapters/    │
         │         ┌───────────────┐        │ repositories │
         │         │    signals/   │        └──────┬───────┘
         │         │ builtin/      │               │
         │         │ custom/       │               │
         │         │ ml/           │               │
         │         │ fusion.py     │               │
         │         └───────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │    knowledge/      │               │
         │    │ (v3: 8子目录)      │               │
         │    └────────────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │    plugins/        │ ← [v3核心]    │
         │    │ (物理插件存放)      │               │
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

## 18. 整体开发路线图（Roadmap v3）

### Phase 0：项目基础设施（1-2周）

```
Week 1-2: 骨架 + Plugin 协议
├── □ Poetry 项目初始化
├── □ plugin_protocol.py（插件协议基类）
├── □ PluginRegistry 核心（discover/register/validate）
├── □ plugin.yaml 格式规范 + 校验器
├── □ 目录结构（含 plugins/）
├── □ .env + 配置（含 v3 新增项）
├── □ loguru（含 Agent trace 日志）
├── □ SQLAlchemy ORM + 建表（含 v3 新增表）
└── □ pytest + CI/CD
```

### Phase 1：插件化数据层（3-4周）

```
Week 3-6: Plugin Registry + MarketGateway + Compliance
├── □ PluginRegistry 完整实现
├── □ DataSourcePlugin 协议
├── □ plugins/datasource/akshare/ (plugin.yaml + adapter.py)
├── □ plugins/datasource/tushare/
├── □ plugins/datasource/yahoo/
├── □ MarketGateway（从 Registry 获取适配器，不硬编码）
├── □ DataSourceCapability 能力声明 + 自动路由
├── □ Compliance 模块（v2 全部 + v3 capability_checker）
├── □ Knowledge 加载器（8个子目录全部）
├── □ 首批知识库 YAML（10+ 行业 + 5+ 政策 + 3+ 策略）
├── □ 缓存层 + 定时同步
└── □ 插件管理 API

验收标准:
  · cp -r _template wind/ → 编辑 → 重启 → 自动识别
  · capability 路由正常工作
  · Compliance 全链路拦截
```

### Phase 2：信号引擎（2-3周）

```
Week 7-9: Signal Plugins + Fusion
├── □ SignalPlugin 协议
├── □ signals/builtin/ (12个信号全部)
├── □ signals/custom/_template.py
├── □ signals/ml/ (XGBoost + LightGBM 骨架)
├── □ SignalFusion（自动发现 + 加权融合）
├── □ Scanner 三层筛选管道
└── □ 信号管理 API
```

### Phase 3：AI Agent Layer（3-4周）⚠️ v3 核心新增

```
Week 10-13: 5-Agent 研究系统
├── □ BaseAgent 基类 + AgentContext
├── □ Planner Agent（理解意图→研究计划）
├── □ Researcher Agent（纯函数，数据收集）
├── □ Analyst Agent（LLM推理 + Signal Fusion）
├── □ Reviewer Agent（幻觉检查 + 逻辑审查）
├── □ Reporter Agent（报告生成）
├── □ AgentOrchestrator（4种协作模式）
├── □ Agent 与 LLM 解耦（每个Agent独立选模型）
├── □ ToolProvider（Agent可调用的工具集）
├── □ ContextBuilder（知识库+数据→Agent上下文）
├── □ Agent 执行日志 + 审计追踪
├── □ 研究 API（/research/start, /research/{id}/report）
└── □ WebSocket 实时 Stream Agent 思考过程

验收标准:
  · "分析面板行业" → 自动 Plan → Research → Analyze → Review → Report
  · Reviewer 可驳回 Analyst 的错误推理
  · 5 个 Agent 全部可独立替换 LLM
  · 研究过程完整可追溯
```

### Phase 4：策略与回测（3-4周）

```
Week 14-17: 复用 v2 Phase 4
```

### Phase 5：交易与风控（2-3周）

```
Week 18-20: 复用 v2 Phase 5
```

### Phase 6：Research Pipeline（2周）

```
Week 21-22: 复用 v2 Phase 6
  + Agent 模式可选（传统 Pipeline vs Agent 驱动）
```

### Phase 7：API + IPC + VSCode 插件（3-4周）

```
Week 23-26: 服务化 + 前端
  + 插件管理面板（VSCode 中管理插件）
  + Agent 研究面板（VSCode 中发起研究/查看报告）
```

### Phase 8：测试 + 文档 + 发布（1-2周）

```
Week 27-28: 质量保障
  + Agent 评测基准（幻觉率/准确率/Token效率）
```

---

## 附录A：v2 → v3 变更清单

| # | 变更项 | 类型 | 影响范围 |
|---|--------|------|---------|
| 1 | 新增 `plugins/` 目录 + `plugin.yaml` 规范 | **新增** | 项目根目录 |
| 2 | 新增 `PluginRegistry` 注册中心（discover/register/lifecycle） | **新增** | infrastructure/plugin_registry/ |
| 3 | MarketGateway 改为从 Registry 获取适配器 | **重构** | infrastructure/adapters/market_gateway/ |
| 4 | 新增 `DataSourceCapability` 能力声明 + 自动路由 | **新增** | domain/models/ + compliance/capability_checker.py |
| 5 | 信号重构为 `builtin/` + `custom/` + `ml/` 三层 | **重构** | signals/ |
| 6 | 新增 `AI Agent Layer`（5个Agent + Orchestrator） | **新增** | infrastructure/agents/ |
| 7 | 知识库扩展为 8 个子目录（+reports/policy/strategy/books/papers） | **扩展** | knowledge/ |
| 8 | 项目重新定位为 **AI Research Terminal** | **定位** | README + 所有文档 |
| 9 | 新增 `plugin_protocol.py`（BasePlugin/DataSourcePlugin/SignalPlugin） | **新增** | shared/ |
| 10 | 数据库新增 `plugin_manifests` / `research_sessions` / `agent_tasks` 表 | **新增** | 数据库 |
| 11 | 新增 API: Plugin管理 + Agent研究 | **新增** | api/routes/ |
| 12 | Roadmap 新增 Phase 3 (AI Agent Layer)，Phase 1 加入 Plugin Registry | **调整** | Roadmap |

---

## 附录B：v3 核心设计原则

1. **AI 永远最后一步** — 负责解释，不负责计算
2. **Plugin 丢进去就识别** — MarketGateway 不知道有什么数据源，Registry 告诉它
3. **能力声明替代 if-else** — 数据源声明自己能做什么，系统自动路由
4. **Agent 各司其职** — Planner 规划 / Researcher 收集 / Analyst 分析 / Reviewer 审查 / Reporter 报告
5. **Agent 与 LLM 解耦** — 每个 Agent 独立选模型，新增 LLM 无需改 Agent
6. **VSCode 纯 UI** — 迁移 Web 不改 Python
7. **知识库先于 AI** — 研报+产业链+政策+历史案例 > 裸问模型
8. **信号可插拔** — 内置/自定义/ML 三层，SignalFusion 不用改
9. **不内置破解** — 用户自配 Key，程序只提供插件框架
10. **AI Research Terminal 不是选股工具** — AI 收集信息+融合信号+给出证据+提示风险，人做决策

---

> **v3 文档结束**  
> 架构演进完成。Plugin Registry + AI Agent Layer + DataSourceCapability + 知识库扩展 + 重新定位 = AI Research Terminal  
> 等待下一步命令。
