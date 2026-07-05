# A股AI交易研究平台 — 架构设计文档 v2

> **版本**: v2.0.0  
> **日期**: 2026-07-05  
> **阶段**: 第一阶段 — 架构设计（评审修订版）  
> **状态**: 待评审  
> **变更**: 新增 MarketGateway / Compliance / Knowledge / Signal Engine / Research Pipeline / 数据伦理分层

---

## 目录

1. [v1 → v2 核心变更](#v1--v2-核心变更)
2. [项目总体架构](#2-项目总体架构)
3. [完整目录结构](#3-完整目录结构)
4. [每个目录职责](#4-每个目录职责)
5. [每个模块职责](#5-每个模块职责)
6. [数据库设计](#6-数据库设计)
7. [数据流设计](#7-数据流设计)
8. [AI 分析流程（大重构）](#8-ai-分析流程大重构)
9. [插件通信流程](#9-插件通信流程)
10. [配置管理](#10-配置管理)
11. [日志管理](#11-日志管理)
12. [缓存方案](#12-缓存方案)
13. [未来扩展方案](#13-未来扩展方案)
14. [接口设计](#14-接口设计)
15. [模块依赖图](#15-模块依赖图)
16. [整体开发路线图](#16-整体开发路线图roadmap)

---

## v1 → v2 核心变更

| # | 变更项 | v1 | v2 | 理由 |
|---|--------|-----|-----|------|
| 1 | 数据源架构 | 独立 Adapter 文件 | **MarketGateway** 统一抽象 | 数据源网站改版时只改 Gateway 内部 |
| 2 | 数据合规 | 无 | **compliance/** 模块 | 数据许可证/商业使用/缓存权限/存盘权限全链路校验 |
| 3 | 知识库 | 无 | **knowledge/** 目录 | AI 不是裸问模型，而是行情+知识库+新闻+龙虎榜+资金+财报+行业+AI |
| 4 | 信号引擎 | SignalGenerator 单体 | **signals/** 模块 + **Signal Fusion** | MACD/RSI/KDJ/资金/龙虎榜/新闻 独立评分 + 加权融合 |
| 5 | AI 定位 | 数据→AI | **行情→指标→资金→板块→情绪→知识库→AI总结** | AI 永远最后一步，负责解释，不负责计算 |
| 6 | Token 管控 | AI 直接分析全市场 | **Scanner → 筛选100 → 评分20 → AI分析3** | Token 从 80万/天 → 5000/天 |
| 7 | 数据伦理 | 无分层 | **三层数据源**（免费合法/实时授权/机构专业） | 不内置破解/Cookie/抓包/绕过权限 |
| 8 | VSCode 定位 | 混合逻辑 | **插件纯 UI**，Python Server 处理一切 | 迁移 Web 时不用改 Python |
| 9 | 研究管线 | 无 | **Research Pipeline** 收盘自动工作流 | 职业交易员 16:00 后的全自动化流程 |

---

## 2. 项目总体架构

### 2.1 架构分层（v2）

```
┌──────────────────────────────────────────────────────────────────────┐
│                      表示层 (Presentation Layer)                       │
│  ┌─────────────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│  │   VS Code 插件       │  │   Web 前端    │  │   CLI 命令行      │     │
│  │   (纯 UI，不请求网络) │  │   (后期)      │  │   (后期)          │     │
│  └─────────┬───────────┘  └──────┬───────┘  └────────┬─────────┘     │
└────────────┼─────────────────────┼───────────────────┼───────────────┘
             │                     │                   │
             └─────────────────────┼───────────────────┘
                                   │ REST / WebSocket / IPC (JSON-RPC)
┌──────────────────────────────────┼───────────────────────────────────┐
│                    应用层 (Application Layer)                         │
│  ┌───────────────────────────────┴──────────────────────────────────┐ │
│  │                     API 网关 (api_gateway/)                        │ │
│  │  路由分发 · 认证鉴权 · 限流 · 请求/响应序列化                       │ │
│  └───────────────────────────────┬──────────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌────┴─────┐ ┌──────────┐ ┌────────────┐ │
│  │ 策略服务  │ │ 回测服务  │ │ AI分析服务│ │信号服务   │ │ 研究管线    │ │
│  │ strategy │ │ backtest │ │ ai_svc   │ │signal_svc│ │research_pipe│ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬─────┘ │
└───────┼────────────┼────────────┼────────────┼──────────────┼───────┘
        │            │            │            │              │
┌───────┼────────────┼────────────┼────────────┼──────────────┼───────┐
│       │      领域层 (Domain Layer)              │              │       │
│  ┌────┴────────────────────────────────────────┴──────────────┴─────┐ │
│  │                    领域模型 (domain/models/)                       │ │
│  │  Stock · MarketData · Strategy · Signal · Order · Position       │ │
│  │  Portfolio · Account · Backtest · AIAnalysis · RiskRule          │ │
│  │  Indicator · ComplianceRecord                                    │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    领域服务 (domain/services/)                     │ │
│  │  TradingEngine · SignalFusionEngine · RiskManager                │ │
│  │  PortfolioOptimizer · MarketScreener · BacktestEngine             │ │
│  │  ResearchPipelineOrchestrator · ScannerEngine                    │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    端口接口 (domain/ports/)                        │ │
│  │  MarketGatewayPort · AIPort · BrokerPort · CachePort             │ │
│  │  RepositoryPort · NotificationPort · CompliancePort              │ │
│  │  KnowledgeBasePort                                               │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
        │            │            │            │              │
┌───────┼────────────┼────────────┼────────────┼──────────────┼───────┐
│       │    基础设施层 (Infrastructure Layer)                           │
│  ┌────┴────────────────────────────────────────────────────────────┐ │
│  │                    适配器 (adapters/)                              │ │
│  │  ┌─────────────────┐ ┌───────────┐ ┌──────────┐ ┌────────────┐  │ │
│  │  │ MarketGateway   │ │AIProvider │ │ Broker   │ │Notification│  │ │
│  │  │ (统一数据网关)   │ │Adapter   │ │ Adapter  │ │Adapter     │  │ │
│  │  │                 │ │           │ │          │ │            │  │ │
│  │  │· AKShareAdapter │ │· DeepSeek │ │· SimNow  │ │· Email     │  │ │
│  │  │· TushareAdapter │ │· OpenAI  │ │· XTP     │ │· WeChat    │  │ │
│  │  │· YahooFinance   │ │· Claude  │ │          │ │            │  │ │
│  │  │· PolygonAdapter │ │           │ │          │ │            │  │ │
│  │  │· AlphaVantage   │ │           │ │          │ │            │  │ │
│  │  │· ...            │ │           │ │          │ │            │  │ │
│  │  └─────────────────┘ └───────────┘ └──────────┘ └────────────┘  │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │              compliance/ (数据合规模块 — 所有数据源必经)            │ │
│  │  DataSourcePolicy · DataSourceValidator · LicenseChecker         │ │
│  │  RateLimiter · AuditLogger                                       │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │              knowledge/ (知识库 — AI分析的基础上下文)               │ │
│  │  industries/ · concepts/ · macro/ · finance/ · glossary/         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │              signals/ (信号引擎 — 多维评分 + 融合)                  │ │
│  │  macd.py · kdj.py · rsi.py · volume.py · ma.py                   │ │
│  │  chip.py · lhb.py · capital.py · news.py                          │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │              仓储实现 (repositories/) + 外部依赖封装                │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心技术栈（未变）

| 层次 | 技术选型 | 说明 |
|------|---------|------|
| 语言 | Python 3.12+ | 主开发语言 |
| 包管理 | Poetry | 依赖管理与虚拟环境 |
| 异步框架 | asyncio + aiohttp | 异步IO |
| Web框架 | FastAPI | REST API + WebSocket |
| ORM | SQLAlchemy 2.0 | 异步ORM，支持SQLite/PostgreSQL |
| 数据验证 | Pydantic v2 | 请求/响应模型验证 |
| 任务队列 | Celery + Redis | 异步任务调度 |
| 缓存 | Redis / diskcache | 多级缓存 |
| 日志 | loguru | 结构化日志 |
| 测试 | pytest + pytest-asyncio | 单元/集成测试 |
| 代码质量 | ruff + mypy + black | Lint + 类型检查 + 格式化 |
| CI/CD | GitHub Actions | 自动化测试与部署 |
| 配置 | pydantic-settings | 类型安全配置管理 |
| VS Code插件 | TypeScript + VS Code API | **纯 UI，不直接请求网络** |
| Web前端 | React + TypeScript | 后期开发 |
| 数据库 | SQLite(dev) / PostgreSQL(prod) | 数据持久化 |
| AI模型 | DeepSeek API / OpenAI兼容 | **AI 永远最后一步** |

---

## 3. 完整目录结构（v2）

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
│   ├── architecture-v2.md            # 本架构设计文档 v2
│   ├── architecture-v1.md            # v1 原版（留档）
│   ├── api-reference.md
│   ├── database-schema.md
│   ├── development-guide.md
│   ├── deployment-guide.md
│   ├── user-guide.md
│   └── changelog/
│
├── config/
│   ├── __init__.py
│   ├── settings.py                   # 全局配置（pydantic-settings）
│   ├── database.py
│   ├── ai_models.py
│   ├── data_sources.py               # 数据源注册表 + 合规级别
│   ├── trading.py
│   ├── cache.py
│   ├── logging.yaml
│   ├── prompts/                      # AI Prompt 模板
│   │   ├── system_prompts/
│   │   │   ├── financial_analyst.yaml
│   │   │   ├── risk_manager.yaml
│   │   │   └── strategy_advisor.yaml
│   │   ├── templates/
│   │   │   ├── market_review.j2
│   │   │   ├── stock_analysis.j2
│   │   │   ├── strategy_advice.j2
│   │   │   ├── risk_alert.j2
│   │   │   └── daily_scan.j2
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
│   │   │   ├── ai_analysis.py
│   │   │   ├── risk.py
│   │   │   ├── indicator.py
│   │   │   ├── compliance_record.py  # [v2新增] 合规记录实体
│   │   │   └── enums.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── trading_engine.py
│   │   │   ├── signal_fusion_engine.py  # [v2新增] 多因子信号融合
│   │   │   ├── risk_manager.py
│   │   │   ├── portfolio_optimizer.py
│   │   │   ├── market_screener.py
│   │   │   ├── scanner_engine.py        # [v2新增] 市场扫描→筛选→评分
│   │   │   ├── backtest_engine.py
│   │   │   └── research_pipeline.py     # [v2新增] 收盘自动研究管线
│   │   ├── ports/
│   │   │   ├── __init__.py
│   │   │   ├── market_gateway_port.py   # [v2重构] 统一数据网关端口
│   │   │   ├── ai_provider_port.py
│   │   │   ├── broker_port.py
│   │   │   ├── cache_port.py
│   │   │   ├── repository_port.py
│   │   │   ├── notification_port.py
│   │   │   ├── compliance_port.py       # [v2新增] 合规端口
│   │   │   ├── knowledge_base_port.py   # [v2新增] 知识库端口
│   │   │   └── message_queue_port.py
│   │   └── events/
│   │       ├── __init__.py
│   │       ├── market_events.py
│   │       ├── trading_events.py
│   │       ├── signal_events.py
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
│   │   │   ├── ai_analysis_use_cases.py
│   │   │   ├── portfolio_use_cases.py
│   │   │   ├── risk_use_cases.py
│   │   │   ├── scanner_use_cases.py       # [v2新增] 扫描用例
│   │   │   ├── research_pipeline_use_cases.py  # [v2新增] 研究管线用例
│   │   │   └── system_use_cases.py
│   │   ├── dto/
│   │   │   ├── __init__.py
│   │   │   ├── requests.py
│   │   │   └── responses.py
│   │   └── event_handlers/
│   │       ├── __init__.py
│   │       ├── market_handlers.py
│   │       ├── trading_handlers.py
│   │       └── risk_handlers.py
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── market_gateway/              # [v2重构] 统一数据网关
│   │   │   │   ├── __init__.py
│   │   │   │   ├── gateway.py              #   MarketGateway 主入口
│   │   │   │   ├── base.py                 #   数据源适配器基类
│   │   │   │   ├── akshare_adapter.py      #   AKShare（免费层）
│   │   │   │   ├── tushare_adapter.py      #   Tushare（免费层）
│   │   │   │   ├── yahoo_finance_adapter.py#   Yahoo Finance（免费层）
│   │   │   │   ├── polygon_adapter.py      #   Polygon（授权层）
│   │   │   │   ├── alpha_vantage_adapter.py#   Alpha Vantage（授权层）
│   │   │   │   └── factory.py              #   适配器工厂
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
│   │   ├── compliance/                     # [v2新增] 数据合规模块
│   │   │   ├── __init__.py
│   │   │   ├── datasource_policy.py        #   数据源使用策略定义
│   │   │   ├── datasource_validator.py     #   数据源合法性校验
│   │   │   ├── license_checker.py          #   许可证检查（商业/缓存/存储/AI）
│   │   │   ├── rate_limit.py               #   速率限制与配额管理
│   │   │   └── audit_logger.py             #   合规审计日志
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── sqlite/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── stock_repo.py
│   │   │   │   ├── strategy_repo.py
│   │   │   │   ├── order_repo.py
│   │   │   │   ├── portfolio_repo.py
│   │   │   │   └── market_data_repo.py
│   │   │   └── postgresql/
│   │   │       └── ...
│   │   ├── orm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── stock_orm.py
│   │   │   ├── market_data_orm.py
│   │   │   ├── strategy_orm.py
│   │   │   ├── order_orm.py
│   │   │   ├── portfolio_orm.py
│   │   │   ├── ai_analysis_orm.py
│   │   │   ├── risk_orm.py
│   │   │   └── compliance_orm.py          # [v2新增]
│   │   ├── cache/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── redis_cache.py
│   │   │   ├── disk_cache.py
│   │   │   └── memory_cache.py
│   │   └── external/
│   │       ├── __init__.py
│   │       ├── database.py
│   │       ├── http_client.py
│   │       ├── websocket_client.py
│   │       ├── file_storage.py
│   │       └── scheduler.py
│   │
│   ├── signals/                            # [v2新增] 信号引擎
│   │   ├── __init__.py
│   │   ├── base.py                         #   信号基类
│   │   ├── macd.py                         #   MACD 信号
│   │   ├── kdj.py                          #   KDJ 信号
│   │   ├── rsi.py                          #   RSI 信号
│   │   ├── volume.py                       #   成交量信号
│   │   ├── ma.py                           #   均线信号
│   │   ├── chip.py                         #   筹码分布信号
│   │   ├── lhb.py                          #   龙虎榜信号
│   │   ├── capital.py                      #   资金流向信号（北向/主力）
│   │   ├── news.py                         #   新闻情绪信号
│   │   ├── sentiment.py                    #   市场情绪信号
│   │   └── fusion.py                       #   Signal Fusion 融合引擎
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── dependencies.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── cors.py
│   │   │   ├── logging.py
│   │   │   └── rate_limit.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── market_data_routes.py
│   │       ├── strategy_routes.py
│   │       ├── trading_routes.py
│   │       ├── backtest_routes.py
│   │       ├── ai_analysis_routes.py
│   │       ├── portfolio_routes.py
│   │       ├── risk_routes.py
│   │       ├── scanner_routes.py          # [v2新增]
│   │       ├── research_routes.py         # [v2新增]
│   │       └── system_routes.py
│   │
│   └── shared/
│       ├── __init__.py
│       ├── types.py
│       ├── constants.py
│       ├── exceptions.py
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── date_utils.py
│       │   ├── math_utils.py
│       │   ├── validation_utils.py
│       │   └── encoding_utils.py
│       └── decorators.py
│
├── knowledge/                              # [v2新增] 知识库
│   ├── README.md                           #   知识库构建说明
│   ├── industries/                         #   行业知识
│   │   ├── index.yaml                      #     行业索引
│   │   ├── banking.yaml                    #     银行业
│   │   ├── semiconductor.yaml              #     半导体
│   │   ├── new_energy.yaml                 #     新能源
│   │   └── ...                             #     40+申万一级行业
│   ├── concepts/                           #   概念板块
│   │   ├── index.yaml
│   │   ├── ai_artificial_intelligence.yaml
│   │   ├── autonomous_driving.yaml
│   │   └── ...
│   ├── macro/                              #   宏观经济
│   │   ├── gdp.yaml
│   │   ├── cpi_ppi.yaml
│   │   ├── pmi.yaml
│   │   ├── monetary_policy.yaml
│   │   └── fiscal_policy.yaml
│   ├── finance/                            #   财务知识
│   │   ├── financial_statements.yaml       #     三张表解读
│   │   ├── valuation_methods.yaml          #     估值方法
│   │   ├── financial_ratios.yaml           #     财务比率
│   │   └── earnings_quality.yaml           #     盈利质量
│   └── glossary/                           #   术语表
│       ├── technical_terms.yaml            #     技术分析术语
│       ├── fundamental_terms.yaml          #     基本面术语
│       └── market_jargon.yaml              #     市场行话
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── signals/                       # [v2新增]
│   ├── integration/
│   └── e2e/
│
├── scripts/
│   ├── init_database.py
│   ├── migrate_database.py
│   ├── sync_market_data.py
│   ├── run_research_pipeline.py           # [v2新增] 运行研究管线
│   ├── build_knowledge_base.py            # [v2新增] 构建知识库
│   ├── run_backtest.py
│   ├── generate_report.py
│   └── seed_data.py
│
├── vscode-ext/                             # 🔌 纯 UI，不直接请求网络
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── extension.ts
│   │   ├── commands/
│   │   ├── views/
│   │   ├── providers/
│   │   └── utils/
│   └── tests/
│
├── web/
│   └── ...
│
├── deploy/
│   └── ...
│
└── data/
    ├── sqlite/
    ├── cache/
    ├── logs/
    └── exports/
```

---

## 4. 每个目录职责

| 目录 | 职责 | v2 变更 |
|------|------|---------|
| `docs/` | 所有项目文档 | 新增 `architecture-v2.md` |
| `config/` | 集中式配置 + Prompt 模板 | 新增 `prompts/` 子目录 |
| `src/domain/` | 核心层：模型+服务+端口+事件 | 新增 `signal_fusion_engine.py`, `scanner_engine.py`, `research_pipeline.py` |
| `src/application/` | 用例编排层 | 新增 `scanner_use_cases.py`, `research_pipeline_use_cases.py` |
| `src/infrastructure/adapters/market_gateway/` | **统一数据网关** | **重构**: 从分散的 adapter 文件 → 统一的 MarketGateway |
| `src/infrastructure/compliance/` | **数据合规模块** | **新增**: 所有数据源必经的合规校验 |
| `src/infrastructure/repositories/` | 仓储实现 | 不变 |
| `src/signals/` | **信号引擎** | **新增**: 多维信号 + Signal Fusion |
| `src/api/` | FastAPI 路由 | 新增 `scanner_routes.py`, `research_routes.py` |
| `src/shared/` | 跨层共享 | 不变 |
| `knowledge/` | **知识库** | **新增**: 行业/概念/宏观/财务/术语的结构化知识 |
| `tests/` | 测试 | 新增 `signals/` 测试 |
| `scripts/` | 运维脚本 | 新增 `run_research_pipeline.py`, `build_knowledge_base.py` |
| `vscode-ext/` | **纯 UI**（不请求网络） | **约束强化**: 所有数据经 Python Server 中转 |
| `data/` | 运行时数据 | 不变 |

### 4.1 依赖规则（未变，严格执行）

```
api ──────────────► application ──────────────► domain ◄────────────── infrastructure
│                        │                          ▲                         │
│                        │                          │                         │
│                        └──────────────────────────┼─────────────────────────┘
│                                                   │
└──────────────────── shared ◄──────────────────────┘
```

**v2 重要约束**:
- `vscode-ext/` **不直接调用任何外部 API**，所有网络请求经 Python Server
- `signals/` 独立于 AI，在 AI 之前运行
- `compliance/` 是 infrastructure 的一部分，所有数据源调用必须经合规层
- `knowledge/` 是静态结构化数据，可被 domain 和 signals 读取

---

## 5. 每个模块职责

### 5.1 MarketGateway — 统一数据网关（v2 重构）

```
┌─────────────────────────────────────────────────────────────┐
│                    MarketGateway                             │
│                                                              │
│  market_gateway/gateway.py  ← 统一入口，对外暴露             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  class MarketGateway(MarketGatewayPort):                │ │
│  │                                                        │ │
│  │    def __init__(self, adapters: list[BaseAdapter]):    │ │
│  │        self._adapters = adapters  # 优先级排序          │ │
│  │        self._compliance = ComplianceChecker()          │ │
│  │                                                        │ │
│  │    async def get_kline(self, code, period, start, end):│ │
│  │        # 1. 合规检查                                    │ │
│  │        # 2. 按优先级尝试适配器                           │ │
│  │        # 3. 失败自动 fallback 到下一个                   │ │
│  │        # 4. 数据标准化后返回                             │ │
│  │                                                        │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  内置适配器（优先级从高到低）:                                 │
│  ┌──────────────────┐                                       │
│  │ AKShareAdapter   │ ← 免费层 #1（A股最全）                 │
│  │ TushareAdapter   │ ← 免费层 #2（需Token，质量高）         │
│  │ YahooFinance     │ ← 免费层 #3（全球市场）                │
│  │ PolygonAdapter   │ ← 授权层（用户自配Key）               │
│  │ AlphaVantage     │ ← 授权层（用户自配Key）               │
│  │ FinnhubAdapter   │ ← 授权层（用户自配Key）               │
│  │ CustomAdapter    │ ← 用户自定义                          │
│  └──────────────────┘                                       │
│                                                              │
│  关键设计: 任何适配器只负责"翻译数据"，                      │
│            MarketGateway 负责调度/合规/标准化/fallback       │
└─────────────────────────────────────────────────────────────┘
```

**为什么用 Gateway 而不是独立 Adapter 文件？**

```
之前的设计:
  eastmoney_adapter.py  ← 如果东方财富改版 → 改这个文件 → 调用方也要改

现在的设计:
  market_gateway/
    gateway.py          ← 对外接口永远不变
    akshare_adapter.py  ← 内部实现，改版只改这一个文件
    tushare_adapter.py  ← 每个适配器独立维护
    ...

调用方代码永远写:
  gateway.get_kline("000001.SZ", "1d", start, end)
而不是:
  EastMoneyAdapter().get_kline(...)  ← 耦合具体实现
```

### 5.2 Compliance — 数据合规模块（v2 新增）

```
src/infrastructure/compliance/
│
├── datasource_policy.py       # 数据源使用策略定义
│   """
│   定义每个数据源的使用权限:
│   - is_legal: 是否合法获取
│   - allow_commercial: 是否允许商业使用
│   - allow_cache: 是否允许缓存
│   - allow_redis: 是否允许放入 Redis
│   - allow_ai_analysis: 是否允许用于 AI 分析
│   - allow_long_term_storage: 是否允许长期存储
│   - require_attribution: 是否需要署名
│   - data_retention_days: 数据保留天数
│   """
│
├── datasource_validator.py    # 数据源合法性校验
│   """
│   每次数据请求前校验:
│   - 该数据源是否已注册
│   - 该数据源的许可证是否有效
│   - 该操作是否在许可证允许范围内
│   """
│
├── license_checker.py         # 许可证检查器
│   """
│   检查项:
│   - 商业使用授权
│   - 缓存授权（内存/磁盘）
│   - Redis 存储授权
│   - AI 分析使用授权
│   - 长期存储授权
│   - 数据再分发授权
│   """
│
├── rate_limit.py              # 速率限制
│   """
│   管理:
│   - 每个数据源的调用频率上限
│   - 每次调用的 Token 配额
│   - 超限后的冷却策略
│   """
│
└── audit_logger.py            # 合规审计日志
    """
    记录每次数据访问:
    - 时间、数据源、操作类型、数据量
    - 合规检查结果（通过/拒绝及原因）
    - 用于审计追溯
    """
```

**数据源合规配置示例**:

```yaml
# config/data_sources.py 中的数据源注册

REGISTERED_DATA_SOURCES = {
    "akshare": DataSourcePolicy(
        name="AKShare",
        is_legal=True,                    # 合法（公开数据）
        allow_commercial=True,            # MIT 协议，允许商业使用
        allow_cache=True,                 # 允许缓存
        allow_redis=True,                 # 允许放入 Redis
        allow_ai_analysis=True,           # 允许 AI 分析
        allow_long_term_storage=True,     # 允许长期存储
        require_attribution=False,        # 不需要署名
        data_retention_days=0,            # 0 = 永久
        rate_limit_per_minute=60,         # 每分钟最大请求数
    ),
    "tushare": DataSourcePolicy(
        name="Tushare Pro",
        is_legal=True,
        allow_commercial=True,            # 需商业授权
        allow_cache=True,
        allow_redis=True,
        allow_ai_analysis=True,
        allow_long_term_storage=True,
        require_attribution=False,
        data_retention_days=0,
        rate_limit_per_minute=200,
    ),
    "yahoo_finance": DataSourcePolicy(
        name="Yahoo Finance",
        is_legal=True,
        allow_commercial=False,           # ⚠️ 不可商业使用！
        allow_cache=True,
        allow_redis=False,                # ⚠️ 不允许放入共享缓存
        allow_ai_analysis=False,          # ⚠️ 不允许 AI 分析
        allow_long_term_storage=False,    # ⚠️ 不允许长期存储
        require_attribution=True,         # 需要署名
        data_retention_days=7,            # 最多保留7天
        rate_limit_per_minute=10,
    ),
}
```

### 5.3 Knowledge — 知识库（v2 新增）

```
knowledge/
│
├── README.md
│
├── industries/                  # 行业知识
│   │
│   │   # 每个行业一个 YAML 文件，包含:
│   │   # - 行业概述
│   │   # - 产业链上下游
│   │   # - 关键驱动因素
│   │   # - 主要公司
│   │   # - 行业周期
│   │   # - 政策环境
│   │   # - 估值基准
│   │
│   ├── index.yaml              # 行业索引
│   ├── banking.yaml            # 银行
│   ├── semiconductor.yaml      # 半导体
│   ├── new_energy.yaml         # 新能源
│   ├── pharmaceutical.yaml     # 医药
│   ├── real_estate.yaml        # 房地产
│   ├── consumer_electronics.yaml
│   ├── automobile.yaml
│   ├── food_beverage.yaml
│   └── ...                     # 40+ 申万一级行业
│
├── concepts/                    # 概念板块
│   ├── index.yaml
│   ├── ai_artificial_intelligence.yaml
│   ├── autonomous_driving.yaml
│   ├── digital_economy.yaml
│   ├── carbon_neutrality.yaml
│   └── ...
│
├── macro/                       # 宏观经济
│   ├── gdp.yaml                # GDP 与经济周期
│   ├── cpi_ppi.yaml            # 通胀
│   ├── pmi.yaml                # 采购经理指数
│   ├── monetary_policy.yaml    # 货币政策
│   ├── fiscal_policy.yaml      # 财政政策
│   └── international_trade.yaml
│
├── finance/                     # 财务知识
│   ├── financial_statements.yaml    # 三张表解读
│   ├── valuation_methods.yaml       # PE/PB/PS/DCF/...
│   ├── financial_ratios.yaml        # ROE/ROA/毛利率/...
│   └── earnings_quality.yaml        # 盈利质量分析
│
└── glossary/                    # 术语表
    ├── technical_terms.yaml     # 金叉/死叉/背离/...
    ├── fundamental_terms.yaml   # PE/ROE/FCF/...
    └── market_jargon.yaml       # 北向资金/游资/...
```

**知识库与 AI 的交互**:

```
传统做法（v1）:
  用户问: "分析京东方A"
  → AI 直接基于训练数据回答
  → 问题: 训练数据可能过时、包含幻觉

v2 做法:
  用户问: "分析京东方A"
  → 1. 从 knowledge/industries/semiconductor.yaml 加载面板行业知识
  → 2. 从数据库加载京东方A的财务数据
  → 3. 从 signals/ 获取技术指标评分
  → 4. 从数据库加载北向资金/龙虎榜
  → 5. 组装 Prompt: 知识库上下文 + 行情数据 + 信号评分 + 用户问题
  → 6. AI 基于完整上下文进行分析
  → 结果: 准确率大幅提升
```

### 5.4 Signals — 信号引擎（v2 新增）

```
src/signals/
│
├── base.py                      # 信号基类
│   """
│   class BaseSignal(ABC):
│       name: str                # 信号名称
│       weight: float            # 默认权重（可配置）
│       category: SignalCategory # 技术/资金/情绪/事件
│
│       @abstractmethod
│       async def compute(self, stock: Stock, context: dict) -> SignalResult:
│           '''计算单个股票的信号分数 (0-100) 和方向 (buy/sell/neutral)'''
│
│       @abstractmethod
│       async def compute_batch(self, stocks: list[Stock], context: dict) -> list[SignalResult]:
│           '''批量计算多个股票的信号'''
│   """
│
├── macd.py                      # MACD 信号
│   """金叉/死叉/背离/零轴位置 → 0-100 评分"""
│
├── kdj.py                       # KDJ 信号
│   """超买超卖/金叉死叉/钝化 → 0-100 评分"""
│
├── rsi.py                       # RSI 信号
│   """超买超卖/背离/趋势强度 → 0-100 评分"""
│
├── volume.py                    # 成交量信号
│   """放量/缩量/量价配合/异常量 → 0-100 评分"""
│
├── ma.py                        # 均线信号
│   """多头排列/空头排列/均线粘合/突破 → 0-100 评分"""
│
├── chip.py                      # 筹码分布信号
│   """筹码集中度/获利盘比例/成本分布 → 0-100 评分"""
│
├── lhb.py                       # 龙虎榜信号
│   """机构买入/游资动向/买卖力度 → 0-100 评分"""
│
├── capital.py                   # 资金流向信号
│   """北向资金/主力净流入/大单动向 → 0-100 评分"""
│
├── news.py                      # 新闻情绪信号
│   """NLP情感分析/公告解读 → 0-100 评分"""
│
├── sentiment.py                 # 市场情绪信号
│   """涨跌比/涨停数/恐慌指数 → 0-100 评分"""
│
└── fusion.py                    # Signal Fusion 融合引擎
    """
    class SignalFusion:
        '''多信号融合评分引擎'''

        def __init__(self, signals: list[BaseSignal], weights: dict[str, float]):
            self.signals = signals
            self.weights = weights  # 可配置权重

        async def score_stock(self, stock, context) -> FusionResult:
            results = []
            for signal in self.signals:
                result = await signal.compute(stock, context)
                results.append(result)

            # 加权融合
            final_score = sum(
                r.score * self.weights.get(r.signal_name, 1.0)
                for r in results
            ) / sum(self.weights.get(r.signal_name, 1.0) for r in results)

            return FusionResult(
                stock_code=stock.code,
                individual_scores={
                    "macd": 95,
                    "rsi": 80,
                    "capital": 100,
                    "lhb": 90,
                    "news": 85,
                    "volume": 95,
                    "ai": 88,
                },
                final_score=91.8,
                direction="buy",
                confidence=0.92,
                reason="多维度共振看多，MACD金叉+北向持续流入+龙虎榜机构净买入",
            )
    """
```

**Signal Fusion 评分示例**:

```
京东方A (000725.SZ) 综合评分:

┌──────────────┬───────┬────────┬──────────────────────────┐
│ 信号维度      │ 得分  │ 权重   │ 信号描述                   │
├──────────────┼───────┼────────┼──────────────────────────┤
│ MACD         │  95   │  1.0   │ 日线MACD金叉，周线多头     │
│ RSI          │  80   │  0.8   │ RSI=62，健康上升趋势       │
│ 北向资金      │ 100   │  1.5   │ 连续5日净流入，累计8.2亿   │
│ 龙虎榜        │  90   │  1.2   │ 3家机构席位买入，净买1.5亿 │
│ 新闻情绪      │  85   │  0.7   │ 面板涨价新闻+公司回购公告  │
│ 成交量        │  95   │  0.8   │ 放量突破平台，量价配合良好  │
│ AI分析        │  88   │  0.5   │ 面板行业景气度回升          │
├──────────────┼───────┼────────┼──────────────────────────┤
│ 加权最终评分   │ 91.8  │        │ ★★★★ 强烈看多             │
└──────────────┴───────┴────────┴──────────────────────────┘

决策: BUY
置信度: 0.92
理由: 多维度共振看多。MACD金叉+北向持续流入+龙虎榜机构净买入+面板行业景气周期确认。
```

### 5.5 Scanner Engine — 三层筛选管道（v2 新增）

```
┌──────────────────────────────────────────────────────────────┐
│                 Scanner Pipeline (三层筛选)                    │
│                                                               │
│  全市场 (~5000只)                                              │
│      │                                                        │
│      ▼                                                        │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Layer 1: 粗筛 (Scanner)                                  │ │
│  │ · 排除 ST / *ST                                          │ │
│  │ · 排除 次新股 (<60天)                                     │ │
│  │ · 排除 停牌                                              │ │
│  │ · 排除 市值 < 20亿                                        │ │
│  │ · 排除 日均成交额 < 5000万                                 │ │
│  │ → 剩余 ~2000只                                            │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             │                                 │
│                             ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Layer 2: 技术筛选 (Filter)                               │ │
│  │ · MACD 金叉 / 多头排列                                    │ │
│  │ · 成交量放大 > 1.5倍20日均量                               │ │
│  │ · 站上20日均线                                            │ │
│  │ · RSI 30-70 健康区间                                      │ │
│  │ → 剩余 ~100只                                             │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             │                                 │
│                             ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Layer 3: Signal Fusion 评分 (Score)                      │ │
│  │ · 10维信号综合评分                                        │ │
│  │ · 排序取 Top 20                                           │ │
│  │ → 剩余 ~20只                                              │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             │                                 │
│                             ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Layer 4: AI 深度分析                                     │ │
│  │ · 取 Top 3 做 AI 深度分析                                 │ │
│  │ · 结合知识库 + 财务数据 + 新闻                             │ │
│  │ → 输出最终建议                                            │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  Token 消耗对比:                                               │
│    全市场直接 AI: ~800,000 tokens/天    ← v1                   │
│    三层筛选后 AI: ~5,000 tokens/天      ← v2                   │
│    节省: 99.4%                                                │
└──────────────────────────────────────────────────────────────┘
```

### 5.6 Research Pipeline — 职业交易员工作流（v2 新增）

```
┌──────────────────────────────────────────────────────────────┐
│              Research Pipeline (收盘后自动执行)                │
│                                                               │
│  触发时间: 每个交易日 15:30 (收盘后30分钟)                      │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Step 1: 数据同步 (16:00)                                  │ │
│  │ ├── 同步全市场日K线                                       │ │
│  │ ├── 同步指数行情                                          │ │
│  │ ├── 同步板块涨跌                                          │ │
│  │ └── 同步个股财务数据                                      │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 2: 公告/事件同步 (16:05)                              │ │
│  │ ├── 同步上市公司公告                                      │ │
│  │ ├── 同步龙虎榜数据                                        │ │
│  │ ├── 同步北向资金流向                                      │ │
│  │ └── 同步融资融券数据                                      │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 3: 资金数据同步 (16:10)                               │ │
│  │ ├── 同步主力资金流向                                      │ │
│  │ ├── 同步大宗交易                                          │ │
│  │ └── 同步股东增减持                                        │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 4: 新闻舆情同步 (16:15)                               │ │
│  │ ├── 同步财经新闻                                          │ │
│  │ ├── 同步研报摘要                                          │ │
│  │ └── NLP 情感分析                                          │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 5: 计算技术指标 (16:20)                               │ │
│  │ ├── 全市场 MACD/RSI/KDJ/BOLL 计算                          │ │
│  │ ├── 均线系统计算                                          │ │
│  │ ├── 筹码分布计算                                          │ │
│  │ └── 形态识别（双底/头肩/三角形...）                         │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 6: 更新数据库 (16:25)                                 │ │
│  │ ├── 所有计算结果写入 SQLite/PostgreSQL                     │ │
│  │ └── 更新缓存 (Redis + diskcache)                          │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 7: Scanner 扫描 (16:30)                               │ │
│  │ ├── 粗筛 → 技术筛选 → Signal Fusion 评分                   │ │
│  │ └── 输出 Top 20 标的                                      │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 8: AI 深度分析 (16:35)                                │ │
│  │ ├── Top 3 个股深度分析（结合知识库）                        │ │
│  │ ├── 市场综述                                              │ │
│  │ └── 风险提示                                              │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ Step 9: 生成报告 (16:40)                                   │ │
│  │ ├── Markdown 日度报告                                     │ │
│  │ ├── 信号列表 + AI 建议                                    │ │
│  │ └── 推送到 VS Code / 邮件 / 微信                           │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  预计总耗时: 5-10 分钟                                         │
│  人工介入: 0（全自动）                                         │
└──────────────────────────────────────────────────────────────┘
```

### 5.7 数据源三层架构（v2 数据伦理设计）

```
┌──────────────────────────────────────────────────────────────┐
│                    数据源三层架构                               │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 第一层：永久免费 + 合法                                    │ │
│  │                                                          │ │
│  │ · AKShare         ← MIT协议，可商业使用                    │ │
│  │ · Tushare (基础版) ← 个人免费，数据质量高                   │ │
│  │ · 交易所官网       ← 公开数据                              │ │
│  │ · 上市公司公告     ← 法定公开                              │ │
│  │ · 新闻RSS         ← 公开信息                              │ │
│  │                                                          │ │
│  │ 特点: 可缓存、可长期存储、可用于AI分析                      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 第二层：用户自配 Key（实时/高级数据）                       │ │
│  │                                                          │ │
│  │ · Tushare Pro     ← 用户自己的Token                       │ │
│  │ · 雪球 API         ← 用户自己的认证                        │ │
│  │ · Alpha Vantage   ← 用户自己的API Key                     │ │
│  │ · Polygon.io      ← 用户自己的API Key                     │ │
│  │ · Finnhub         ← 用户自己的API Key                     │ │
│  │ · Wind            ← 用户自己的账号                        │ │
│  │                                                          │ │
│  │ 特点: 用户自行承担费用和合规责任                           │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 第三层：券商/机构 API                                     │ │
│  │                                                          │ │
│  │ · IBKR API        ← 用户自己的券商账户                    │ │
│  │ · CTP 行情         ← 期货公司提供                          │ │
│  │ · XTP 行情         ← 券商提供                              │ │
│  │                                                          │ │
│  │ 特点: 实时行情，专业级，需要对应账户                       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ⚠️ 程序绝不内置:                                              │
│    · 破解/Cookie/抓包/绕过权限                                │
│    · 硬编码的第三方账号                                       │
│    · 商业数据源的共享Key                                     │
│                                                               │
│  程序只负责:                                                  │
│    · 提供 Adapter 框架                                       │
│    · 用户填入自己的 Key                                       │
│    · 合规检查 + 速率控制                                      │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. 数据库设计

### 6.1 设计原则（未变）

1. 第一阶段使用 SQLite
2. ORM 抽象（SQLAlchemy 2.0）
3. snake_case 命名
4. UTC 时间戳
5. 软删除

### 6.2 v2 新增表

#### compliance_records（合规审计表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `datasource_name` | VARCHAR(50) | NOT NULL | 数据源名称 |
| `operation` | VARCHAR(50) | NOT NULL | 操作类型：get_kline/sync_stocks/... |
| `params_json` | TEXT | | 请求参数 |
| `compliance_result` | VARCHAR(20) | NOT NULL | 结果：passed/denied/warning |
| `deny_reason` | TEXT | | 拒绝原因 |
| `license_check_json` | TEXT | | 许可证检查详情 |
| `data_volume` | INTEGER | | 数据量（条数） |
| `created_at` | DATETIME | DEFAULT NOW | 时间 |

#### knowledge_entries（知识库条目表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `category` | VARCHAR(50) | NOT NULL | 分类：industry/concept/macro/finance/glossary |
| `key` | VARCHAR(100) | NOT NULL | 唯一键 |
| `content_yaml` | TEXT | NOT NULL | YAML 格式内容 |
| `version` | INTEGER | DEFAULT 1 | 版本 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |

#### signal_scores（信号评分表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `stock_id` | INTEGER | FK → stocks.id | 股票ID |
| `signal_name` | VARCHAR(50) | NOT NULL | 信号名称：macd/rsi/kdj/lhb/... |
| `score` | DECIMAL(5,2) | NOT NULL | 评分 0-100 |
| `direction` | VARCHAR(10) | | buy/sell/neutral |
| `detail_json` | TEXT | | 信号详情 |
| `calc_date` | DATE | NOT NULL | 计算日期 |
| `created_at` | DATETIME | DEFAULT NOW | 时间 |

**索引**: `idx_signal_stock_date` (stock_id, calc_date), `idx_signal_name_date` (signal_name, calc_date)

#### fusion_scores（融合评分表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `stock_id` | INTEGER | FK → stocks.id | 股票ID |
| `final_score` | DECIMAL(5,2) | NOT NULL | 最终融合评分 0-100 |
| `individual_scores_json` | TEXT | NOT NULL | 各维度评分JSON |
| `direction` | VARCHAR(10) | NOT NULL | buy/sell/neutral |
| `confidence` | DECIMAL(4,3) | | 置信度 |
| `reason` | TEXT | | 融合理由 |
| `calc_date` | DATE | NOT NULL | 计算日期 |
| `created_at` | DATETIME | DEFAULT NOW | 时间 |

#### research_pipeline_runs（研究管线执行记录）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK | 主键 |
| `run_date` | DATE | NOT NULL | 运行日期 |
| `status` | VARCHAR(20) | NOT NULL | running/completed/failed |
| `steps_json` | TEXT | | 各步骤状态JSON |
| `total_duration_ms` | INTEGER | | 总耗时（毫秒） |
| `scanned_count` | INTEGER | | 扫描股票数 |
| `filtered_count` | INTEGER | | 筛选后数量 |
| `scored_count` | INTEGER | | 评分数量 |
| `ai_analyzed_count` | INTEGER | | AI分析数量 |
| `tokens_used` | INTEGER | | 总Token消耗 |
| `report_path` | VARCHAR(500) | | 报告文件路径 |
| `error_message` | TEXT | | 错误信息 |
| `started_at` | DATETIME | | 开始时间 |
| `completed_at` | DATETIME | | 完成时间 |

（其余表 stocks / market_data / strategies / orders / positions / accounts / portfolios / backtests / ai_analyses / risk_rules / signals / notifications / system_logs 保持不变，参见 v1 文档）

---

## 7. 数据流设计

### 7.1 v2 修正后的 AI 分析数据流

```
❌ v1 错误流程:
  数据 → AI → 结果
  (AI 既做计算又做分析，Token 爆炸)

✅ v2 正确流程:
  ┌─────────┐
  │  行情数据  │ ← MarketGateway
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ 计算指标  │ ← signals/ (纯 Python 计算，0 Token)
  │ MACD/RSI │
  │ KDJ/BOLL │
  │ 均线/量价 │
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ 资金数据  │ ← 北向/主力/龙虎榜/融资融券
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ 板块数据  │ ← 行业涨跌/概念热度/轮动
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ 情绪指标  │ ← 涨跌比/涨停数/恐慌指数/NLP新闻情绪
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ 知识库    │ ← knowledge/ (行业/概念/宏观/财务/术语)
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │Signal    │ ← 所有信号在此融合评分
  │Fusion    │   这一步不需要 AI
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ AI 总结   │ ← DeepSeek/OpenAI
  │          │   AI 只做最后一步：
  │          │   解释为什么这些信号同时出现
  │          │   提供交易建议
  │          │   提醒风险
  │          │   Token 消耗极小
  └────┬────┘
       │
       ▼
  ┌─────────┐
  │ 输出报告  │ ← 推送到 VS Code / 邮件 / 微信
  └─────────┘
```

### 7.2 Scanner → AI 管道数据流

```
全市场 5000只
    │
    ▼
【粗筛】排除 ST/次新/停牌/小市值/无成交 → 减少到 ~2000只
    │
    ▼
【技术筛选】MACD/均线/成交量/RSI 条件过滤 → 减少到 ~100只
    │
    ▼
【Signal Fusion】10维信号评分 + 排序 → 取 Top 20
    │
    ▼
【AI 深度分析】Top 3 深度分析（结合知识库+财务+新闻+龙虎榜）
    │
    ▼
【输出】最终建议 + 风险提示

Token 消耗: ~5,000 (仅分析3只)
vs v1 直接 AI 全市场: ~800,000
节省 99.4%
```

### 7.3 Research Pipeline 数据流

```
交易日 15:30 触发
    │
    ▼
┌──────────────────────────────────────────────────┐
│              ResearchPipelineOrchestrator         │
│                                                   │
│  Step 1-4: 数据同步 (并行)                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐ │
│  │行情同步  │ │公告同步  │ │资金同步  │ │新闻同步 │ │
│  │Gateway  │ │Gateway  │ │Gateway  │ │Gateway │ │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬───┘ │
│       └───────────┴──────────┴───────────┘       │
│                     │                             │
│                     ▼                             │
│  Step 5: 计算指标 (并行)                           │
│  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐  │
│  │MA│ │RS│ │KD│ │BO│ │VO│ │CH│ │LH│ │CA│ │NE│  │
│  │CD│ │I │ │J │ │LL│ │L │ │IP│ │B │ │P │ │WS│  │
│  └──┘ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘  │
│       └───────────────────┬───────────────────┘   │
│                           ▼                       │
│  Step 6: 更新数据库 + 缓存                          │
│                           │                       │
│                           ▼                       │
│  Step 7: Scanner 扫描                               │
│  粗筛 → 技术筛选 → Signal Fusion → Top 20          │
│                           │                       │
│                           ▼                       │
│  Step 8: AI 深度分析 Top 3 (带知识库上下文)          │
│                           │                       │
│                           ▼                       │
│  Step 9: 生成报告 + 推送                            │
│  ┌─────────┐ ┌─────────┐ ┌──────────────────────┐ │
│  │VS Code  │ │  Email  │ │ WeChat Work Bot      │ │
│  └─────────┘ └─────────┘ └──────────────────────┘ │
└──────────────────────────────────────────────────┘
```

---

## 8. AI 分析流程（大重构）

### 8.1 v1 vs v2 对比

| 维度 | v1 | v2 |
|------|-----|-----|
| AI 定位 | 计算 + 分析 | **只解释，不计算** |
| AI 在流程中的位置 | 第一步 | **最后一步** |
| Token 消耗 | 80万/天 | **5000/天** |
| 分析对象 | 全市场 | **Scanner 筛选后的 Top 3** |
| 上下文 | 纯行情数据 | **行情 + 知识库 + 信号评分 + 资金 + 新闻 + 财务** |
| 准确率 | 依赖模型训练数据 | **基于实时结构化数据 + 领域知识** |

### 8.2 AI 分析类型（v2 修正）

| 分析类型 | 前置步骤（AI之前已完成） | AI 的职责 | Token 估算 |
|---------|------------------------|-----------|-----------|
| **stock_deep_analysis** | 知识库加载 + 财务数据 + Signal Fusion 评分 | 解释各维度信号含义、综合判断、风险提示 | ~1500 |
| **market_review** | 大盘技术指标 + 涨跌统计 + 板块轮动 | 市场整体判断、关键点位、情绪解读 | ~800 |
| **strategy_review** | 回测引擎（纯Python） | 策略表现解读、参数调整建议 | ~1000 |
| **risk_assessment** | RiskManager 量化计算 | 风险解释、情景分析、应对建议 | ~600 |
| **daily_summary** | Research Pipeline 全部步骤 | 日度综述、Top 3点评、明日关注 | ~1200 |

### 8.3 Prompt 构建流程（v2）

```python
# AI 永远最后一步 —— 它的输入是所有人的输出

async def build_ai_analysis_prompt(
    stock: Stock,
    knowledge: KnowledgeContext,
    fusion_result: FusionResult,
    financials: dict,
    news_sentiment: dict,
    capital_flow: dict,
) -> list[dict]:
    """
    system_prompt: 你是资深A股分析师，基于以下结构化数据进行分析。
                   不要凭空猜测，严格基于提供的数据。

    user_prompt:
      ## 标的信息
      京东方A (000725.SZ) | 面板行业 | 市值: 1800亿

      ## 行业知识
      {从 knowledge/industries/semiconductor.yaml 加载}

      ## 技术面评分
      MACD: 95分 | RSI: 80分 | 均线: 85分 | 成交量: 95分
      信号融合评分: 91.8/100  → 强烈看多

      ## 资金面
      北向资金: 连续5日净流入，累计8.2亿
      主力资金: 近3日净流入2.1亿
      龙虎榜: 3家机构席位买入，净买1.5亿

      ## 财务面
      PE: 15.2 | PB: 1.8 | ROE: 12.5%
      营收增速: 18% | 净利润增速: 25%

      ## 新闻情绪
      正面: 面板涨价周期确认
      正面: 公司回购2亿
      中性: 行业竞争格局分析

      ## 请回答
      1. 综合以上数据，对京东方A给出买入/持有/卖出的建议
      2. 列出最关键的风险因素
      3. 建议的仓位比例和止损位
    """
```

### 8.4 AI 调用决策（v2）

```
请求进入
  │
  ▼
┌─────────────┐
│ Scanner前置  │  ← [v2新增] 必须先经过 Scanner 管道
│ 是否已完成？  │
└──────┬──────┘
       │ 是
       ▼
┌─────────────┐
│ 缓存检查     │──命中──► 返回缓存
│ (相同股票+   │
│  同一交易日) │
└──────┬──────┘
       │ 未命中
       ▼
┌─────────────┐
│ 合规检查     │  ← [v2新增]
│ · 该数据源   │
│   允许AI分析?│
│ · Token预算  │
│   是否充足？ │
└──────┬──────┘
       │ 通过
       ▼
┌─────────────┐
│ 上下文组装   │  ← [v2新增] Knowledge + Signals + Financials + News
│ Prompt构建  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ API调用      │
│ · 重试3次    │
│ · 超时30s    │
│ · 流式输出   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 结果验证     │──失败──► 降级/报错
│ · JSON解析   │
│ · Schema校验 │
└──────┬──────┘
       │ 成功
       ▼
  返回结果 + 持久化
```

---

## 9. 插件通信流程

### 9.1 v2 约束：VSCode 纯 UI

```
┌──────────────────────────────────────────────────────────────┐
│                     VSCode Extension                          │
│                                                               │
│  ⚠️ 约束规则:                                                 │
│  ├── ❌ 不直接请求任何外部 API                                  │
│  ├── ❌ 不直接访问数据库                                       │
│  ├── ❌ 不直接调用 AI API                                      │
│  ├── ❌ 不直接读取数据源                                       │
│  ├── ✅ 只通过 IPC 调用 Python Server                          │
│  └── ✅ 只负责 UI 渲染和用户交互                               │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │               VSCode Extension (纯 UI)                    │ │
│  │                                                          │ │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────────┐        │ │
│  │  │ Sidebar  │ │ Webview   │ │ Status Bar       │        │ │
│  │  │ 股票列表  │ │ K线图表    │ │ 信号/持仓/风控    │        │ │
│  │  └────┬─────┘ └─────┬─────┘ └────────┬─────────┘        │ │
│  │       │             │               │                    │ │
│  │       └─────────────┼───────────────┘                    │ │
│  │                     │                                    │ │
│  │              ┌──────┴──────┐                             │ │
│  │              │  IPC Client │  ← 只做这一件事              │ │
│  │              └──────┬──────┘                             │ │
│  └─────────────────────┼────────────────────────────────────┘ │
└────────────────────────┼──────────────────────────────────────┘
                         │
              JSON-RPC 2.0 (Unix Socket / Named Pipe)
                         │
┌────────────────────────┼──────────────────────────────────────┐
│                        │                                       │
│  ┌─────────────────────┴────────────────────────────────────┐ │
│  │              Python Backend (一切逻辑)                     │ │
│  │                                                          │ │
│  │  ┌────────────────────────────────────────────────────┐  │ │
│  │  │ IPC Server ─► Use Cases ─► Domain Services         │  │ │
│  │  │                    │                               │  │ │
│  │  │         ┌──────────┼──────────┐                    │  │ │
│  │  │         │          │          │                    │  │ │
│  │  │    MarketGateway  Signals   AI Provider            │  │ │
│  │  │         │          │          │                    │  │ │
│  │  │    Compliance   Knowledge   Database              │  │ │
│  │  └────────────────────────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**为什么这样设计？**

> 如果插件直接请求网络，迁移 Web 版时所有数据获取逻辑要重写。
> 如果所有逻辑在 Python Server，迁移 Web 只改前端，Python 一行不用改。

---

## 10. 配置管理

### 10.1 配置结构（v2 新增项）

```python
# config/settings.py v2 新增配置项

class Settings(BaseSettings):
    # ... (v1 所有配置保持不变) ...

    # ---- [v2新增] 数据合规 ----
    COMPLIANCE_ENABLED: bool = True           # 是否启用合规检查
    COMPLIANCE_AUDIT_LOG: bool = True         # 是否记录审计日志
    COMPLIANCE_STRICT_MODE: bool = False      # 严格模式：不合规直接拒绝（非严格仅警告）

    # ---- [v2新增] Scanner 管道 ----
    SCANNER_MIN_MARKET_CAP: float = 20.0      # 最小市值（亿）
    SCANNER_MIN_DAILY_VOLUME: float = 50.0    # 最小日均成交额（百万）
    SCANNER_EXCLUDE_ST: bool = True           # 排除ST
    SCANNER_EXCLUDE_NEW_IPO_DAYS: int = 60    # 排除次新股天数
    SCANNER_FILTER_TARGET_COUNT: int = 100    # 技术筛选目标数量
    SCANNER_SCORE_TOP_N: int = 20             # 评分后保留Top N
    SCANNER_AI_DEEP_ANALYSIS_N: int = 3       # AI深度分析Top N

    # ---- [v2新增] Signal Fusion ----
    SIGNAL_WEIGHTS: dict = {                  # 信号权重配置
        "macd": 1.0,
        "rsi": 0.8,
        "kdj": 0.7,
        "volume": 0.8,
        "ma": 0.7,
        "chip": 0.6,
        "lhb": 1.2,
        "capital": 1.5,
        "news": 0.7,
        "sentiment": 0.5,
    }

    # ---- [v2新增] Research Pipeline ----
    RESEARCH_PIPELINE_ENABLED: bool = True     # 是否启用自动研究管线
    RESEARCH_PIPELINE_TRIGGER_TIME: str = "15:30"  # 触发时间（交易日）
    RESEARCH_PIPELINE_SYNC_STOCKS: bool = True
    RESEARCH_PIPELINE_SYNC_FUND_FLOW: bool = True
    RESEARCH_PIPELINE_AI_ANALYSIS: bool = True
    RESEARCH_PIPELINE_NOTIFY_VSCODE: bool = True
    RESEARCH_PIPELINE_NOTIFY_EMAIL: bool = False
    RESEARCH_PIPELINE_NOTIFY_WECHAT: bool = False

    # ---- [v2新增] Token 预算 ----
    AI_DAILY_TOKEN_BUDGET: int = 10000         # 每日Token预算
    AI_MAX_TOKENS_PER_REQUEST: int = 2000      # 单次请求最大Token
```

---

## 11. 日志管理

（架构与 v1 一致，基于 loguru。v2 新增合规审计日志 sink）

```python
# 合规审计日志独立文件
logger.add(
    "data/logs/compliance.log",
    format="{time} | {level} | {message}",
    level="INFO",
    rotation="50 MB",
    retention="90 days",   # 合规日志保留更久
    serialize=True,
    filter=lambda record: record["extra"].get("category") == "compliance",
)
```

---

## 12. 缓存方案

### 12.1 v2 缓存策略（增加合规约束）

| 数据类型 | L1(内存) | L2(Redis) | L3(磁盘) | 合规约束 |
|---------|---------|----------|---------|---------|
| 实时行情 | ✅ 30s | ✅ 60s | ❌ | 需检查数据源允许缓存 |
| 日K线（历史） | ❌ | ✅ 24h | ✅ 永久 | 需检查允许长期存储 |
| Yahoo Finance数据 | ✅ 60s | ❌ 不允许 | ❌ 允许7天 | **不可商用/不可Redis** |
| AKShare数据 | ✅ | ✅ | ✅ | MIT协议，无限制 |
| AI分析结果 | ❌ | ✅ 1h | ✅ 永久 | 无合规限制（自有数据） |
| Signal Fusion评分 | ✅ 5min | ✅ 1h | ❌ | 无合规限制（计算结果） |
| Knowledge Base | ✅ 永久 | ✅ 24h | ✅ 永久 | 自有知识库，无限制 |

---

## 13. 未来扩展方案

（v1 的6大扩展点全部保留，v2 新增以下）

### 13.1 数据源扩展（MarketGateway 模式）

```python
# 新增数据源只需3步（比v1更简单）

# Step 1: 实现 BaseAdapter
class MyNewAdapter(BaseAdapter):
    async def get_kline(self, code, period, start, end):
        # 你的实现
        pass

# Step 2: 定义合规策略
DataSourceRegistry.register("my_new_source", DataSourcePolicy(
    name="My New Source",
    is_legal=True,
    allow_commercial=True,
    allow_cache=True,
    allow_redis=True,
    allow_ai_analysis=True,
    allow_long_term_storage=True,
    rate_limit_per_minute=30,
))

# Step 3: 注册到 Gateway
MarketGateway.register_adapter(MyNewAdapter(), priority=10)
```

### 13.2 信号扩展

```python
# 新增信号只需继承 BaseSignal
class MyCustomSignal(BaseSignal):
    name = "my_custom"
    weight = 1.0

    async def compute(self, stock, context):
        # 你的信号逻辑
        return SignalResult(score=85, direction="buy", detail={...})

# 注册到 SignalFusion
fusion.add_signal(MyCustomSignal())
```

---

## 14. 接口设计

### 14.1 MarketGatewayPort（v2 核心端口）

```python
# src/domain/ports/market_gateway_port.py

from abc import ABC, abstractmethod
from typing import Optional
from datetime import date

class MarketGatewayPort(ABC):
    """统一数据网关端口 —— 所有数据访问的唯一入口"""

    @abstractmethod
    async def get_kline(
        self,
        stock_code: str,
        period: str,
        start_date: date,
        end_date: date,
        adjust: str = "qfq",
    ) -> list[dict]:
        """获取K线——Gateway内部自动选择最佳适配器"""
        ...

    @abstractmethod
    async def get_realtime_quote(
        self, stock_codes: list[str]
    ) -> list[dict]:
        """获取实时行情"""
        ...

    @abstractmethod
    async def get_stock_list(
        self, market: Optional[str] = None
    ) -> list[dict]:
        """获取股票列表"""
        ...

    @abstractmethod
    async def get_financials(
        self, stock_code: str
    ) -> dict:
        """获取财务数据"""
        ...

    @abstractmethod
    async def get_capital_flow(
        self, stock_code: str, days: int = 5
    ) -> dict:
        """[v2新增] 获取资金流向（北向/主力）"""
        ...

    @abstractmethod
    async def get_lhb_data(
        self, trade_date: date
    ) -> list[dict]:
        """[v2新增] 获取龙虎榜数据"""
        ...

    @abstractmethod
    async def get_news(
        self, stock_code: str, days: int = 3
    ) -> list[dict]:
        """[v2新增] 获取相关新闻"""
        ...

    @abstractmethod
    async def get_health(self) -> dict:
        """检查各适配器健康状态"""
        ...
```

### 14.2 KnowledgeBasePort（v2 新增）

```python
class KnowledgeBasePort(ABC):
    """知识库端口"""

    @abstractmethod
    async def get_industry_knowledge(self, industry: str) -> dict:
        """获取行业知识"""
        ...

    @abstractmethod
    async def get_concept_knowledge(self, concept: str) -> dict:
        """获取概念板块知识"""
        ...

    @abstractmethod
    async def get_macro_context(self) -> dict:
        """获取当前宏观经济上下文"""
        ...

    @abstractmethod
    async def get_glossary(self, term: str) -> Optional[str]:
        """查询术语定义"""
        ...

    @abstractmethod
    async def search(self, query: str, category: Optional[str] = None) -> list[dict]:
        """搜索知识库"""
        ...
```

### 14.3 v2 新增 REST API

```
Scanner (扫描)
├── POST   /scanner/run                  运行全市场扫描
├── GET    /scanner/results/latest       最新扫描结果
├── GET    /scanner/results/{date}       指定日期扫描结果
└── GET    /scanner/config               扫描配置

Signals (信号)
├── GET    /signals/list                 可用信号列表
├── POST   /signals/compute/{code}       计算单股信号
├── POST   /signals/fusion/{code}        计算单股融合评分
├── GET    /signals/fusion/top           Top N 融合评分排名
└── PUT    /signals/weights              更新信号权重

Research Pipeline (研究管线)
├── POST   /research/run                 手动触发研究管线
├── GET    /research/status              管线运行状态
├── GET    /research/runs                历史运行记录
├── GET    /research/reports/latest      最新日度报告
└── GET    /research/reports/{date}      指定日期报告

Knowledge (知识库)
├── GET    /knowledge/industries         行业列表
├── GET    /knowledge/industries/{name}  行业详情
├── GET    /knowledge/concepts           概念列表
├── GET    /knowledge/glossary/{term}    术语查询
└── POST   /knowledge/search             搜索知识库

Compliance (合规)
├── GET    /compliance/datasources       已注册数据源及合规状态
├── GET    /compliance/audit-log         合规审计日志
└── GET    /compliance/status            合规检查状态
```

---

## 15. 模块依赖图（v2）

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
    │ models   │       │ use_cases   │      │ market_      │
    │ services │       │ dto         │      │  gateway/    │
    │ ports    │       │ handlers    │      │ compliance/  │
    │ events   │       └─────────────┘      │ adapters/    │
    └──────────┘                            │ repositories │
         ▲                                  └──────┬───────┘
         │                                         │
         │         ┌───────────────┐               │
         │         │    signals/   │               │
         │         │ (独立模块)     │               │
         │         │ macd/rsi/kdj  │               │
         │         │ fusion        │               │
         │         └───────────────┘               │
         │                                         │
         │    ┌────────────────────┐               │
         │    │    knowledge/      │               │
         │    │ (静态知识库)        │               │
         │    └────────────────────┘               │
         │                                         │
         └─────────────────────────────────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │     api     │
                   │ (FastAPI)   │
                   └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  vscode-ext  │  ← 纯 UI，不参与核心依赖
                   └─────────────┘
```

**关键依赖关系说明**:
- `signals/` 依赖 `domain/models`（读取行情数据）、不依赖 AI
- `compliance/` 位于 infrastructure 内，被 MarketGateway 强制调用
- `knowledge/` 是静态数据，被 domain/services 读取后传入 AI prompt
- `vscode-ext` 不依赖 src 任何模块，仅通过 IPC 通信

---

## 16. 整体开发路线图（Roadmap v2）

### Phase 0：项目基础设施（1-2周）

```
Week 1-2: 项目骨架
├── □ Poetry 项目初始化 + 依赖锁定
├── □ ruff + mypy + black + pre-commit
├── □ 完整目录结构（含 v2 新增目录）
├── □ .env + pydantic-settings（含 v2 新增配置项）
├── □ loguru 日志系统 + 合规审计日志
├── □ SQLAlchemy 异步引擎 + ORM 基类
├── □ 数据库初始化脚本（含 v2 新增表）
├── □ pytest + fixtures + CI/CD
└── □ README + 开发指南

验收标准: poetry install 一键安装，pre-commit 全过，20+ 测试全绿
```

### Phase 1：核心数据层（2-3周）

```
Week 3-5: MarketGateway + Compliance + Knowledge
├── □ 实现 MarketGateway 统一网关 + BaseAdapter
├── □ 实现 AKShareAdapter（免费层 #1）
├── □ 实现 TushareAdapter（免费层 #2）
├── □ 实现 YahooFinanceAdapter（免费层 #3）
├── □ 实现 AdapterFactory + fallback 链
├── □ 实现 Compliance 模块（5个子模块全部）
├── □ 数据源合规策略注册表
├── □ 实现 Knowledge 知识库加载器
├── □ 编写首批知识库 YAML 文件（5-10个行业）
├── □ 实现 SQLite Repository
├── □ 缓存层 + APScheduler 定时同步

验收标准:
  · MarketGateway 可自动 fallback
  · Compliance 拦截不合规请求
  · 知识库可正常加载
```

### Phase 2：信号引擎（2-3周）⚠️ 比 v1 提前

```
Week 6-8: Signals + Signal Fusion
├── □ 实现 BaseSignal 基类
├── □ 实现技术类信号: MACD / KDJ / RSI / MA / Volume / BOLL
├── □ 实现资金类信号: Capital / Chip
├── □ 实现事件类信号: LHB / News
├── □ 实现情绪类信号: Sentiment
├── □ 实现 SignalFusion 融合引擎
├── □ 信号权重配置与管理
├── □ 单元测试（每个信号独立测试）
├── □ 融合评分可视化接口
├── □ 实现 Scanner 三层筛选管道

验收标准:
  · 10个信号全部可计算
  · Signal Fusion 输出合理评分
  · Scanner 5000→100→20→3 管道正常
```

### Phase 3：AI 分析引擎（2-3周）

```
Week 9-11: AI 最后一步
├── □ 实现 AIPort + DeepSeekAdapter
├── □ 实现 OpenAI 兼容 Adapter
├── □ 实现 PromptBuilder（Jinja2 + Knowledge上下文）
├── □ 设计 Prompt 模板（v2风格：结构数据 + AI解释）
├── □ 实现 AIAnalysisEngine
├── □ 实现 Token 预算管理
├── □ 实现 AI调用缓存（同股同日复用）
├── □ 单元测试 + 集成测试

验收标准:
  · AI 只接收预处理后的结构化数据
  · Token 消耗在预算内
  · Prompt 包含知识库上下文
```

### Phase 4：策略与回测（3-4周）

```
Week 12-15: 策略框架 + 回测引擎
├── □ BaseStrategy + 内置策略
├── □ BacktestEngine
├── □ PerformanceCalculator
├── □ 参数优化
└── □ 回测集成测试
```

### Phase 5：交易与风控（2-3周）

```
Week 16-18: 交易执行 + 风控
├── □ Order/Position/Account/Portfolio 模型
├── □ BrokerPort + SimNow Adapter
├── □ TradingEngine + RiskManager
├── □ PortfolioOptimizer
└── □ 交易集成测试
```

### Phase 6：Research Pipeline（2周）⚠️ v2 新增

```
Week 19-20: 职业交易员收盘工作流
├── □ ResearchPipelineOrchestrator
├── □ 9步工作流编排（并行+串行混合）
├── □ 交易日历集成（自动跳过节假日）
├── □ 报告生成（Markdown模板）
├── □ 通知推送（VSCode/Email/WeChat）
├── □ 管线监控与告警
└── □ 端到端集成测试

验收标准:
  · 无人值守全自动运行
  · 5-10分钟完成全流程
  · 失败步骤自动重试+告警
```

### Phase 7：API + IPC + VSCode 插件（3-4周）

```
Week 21-24: 服务化 + 前端
├── □ FastAPI 全量路由（含 v2 新增）
├── □ WebSocket 实时推送
├── □ IPC Server (JSON-RPC)
├── □ VSCode 插件（纯UI）
│   ├── Sidebar 股票列表
│   ├── K线图表 Webview
│   ├── 信号评分面板 [v2新增]
│   ├── AI 分析面板
│   ├── Research Pipeline 状态 [v2新增]
│   └── Scanner 结果展示 [v2新增]
├── □ 插件打包
└── □ 集成测试
```

### Phase 8：测试 + 文档 + 发布（1-2周）

```
Week 25-26: 质量保障
├── □ 测试覆盖率 ≥ 80%
├── □ E2E 全流程测试
├── □ API 文档 (OpenAPI)
├── □ 用户手册
├── □ 部署文档
└── □ v1.0.0 发布
```

### Phase 9：Web 版本（后期）

```
Week 27+: React 前端
```

---

## 附录A：v1 → v2 变更清单

| # | 变更 | 类型 | 影响范围 |
|---|------|------|---------|
| 1 | `eastmoney_adapter.py` → `market_gateway/` 统一网关 | 重构 | infrastructure/adapters/ |
| 2 | 新增 `compliance/` 数据合规模块 | 新增 | infrastructure/compliance/ |
| 3 | 新增 `knowledge/` 知识库目录 | 新增 | knowledge/ |
| 4 | 新增 `signals/` 信号引擎 + Signal Fusion | 新增 | signals/ |
| 5 | AI 流程重构：AI 永远最后一步 | 重构 | domain/services/ai_analysis_engine.py |
| 6 | 新增 Scanner 三层筛选管道 | 新增 | domain/services/scanner_engine.py |
| 7 | 新增数据源三层架构 + 伦理约束 | 新增 | config/data_sources.py |
| 8 | VSCode 纯 UI 约束强化 | 约束 | vscode-ext/ |
| 9 | 新增 Research Pipeline 收盘工作流 | 新增 | domain/services/research_pipeline.py |
| 10 | 数据库新增 compliance_records / knowledge_entries / signal_scores / fusion_scores / research_pipeline_runs 表 | 新增 | 数据库 |
| 11 | MarketGatewayPort / KnowledgeBasePort / CompliancePort 端口新增 | 新增 | domain/ports/ |
| 12 | 新增 REST API: Scanner / Signals / Research / Knowledge / Compliance | 新增 | api/routes/ |
| 13 | 新增配置项: 合规/Signal权重/Scanner管道/Research Pipeline/Token预算 | 新增 | config/settings.py |
| 14 | Roadmap 调整: 信号引擎提前到 Phase 2，Research Pipeline 新增为 Phase 6 | 调整 | Roadmap |

---

## 附录B：核心设计原则（重申）

1. **AI 永远最后一步** — 负责解释，不负责计算
2. **MarketGateway 统一入口** — 数据源变更不影响上层
3. **Compliance 全链路** — 数据获取 → 缓存 → 存储 → AI 分析，每一步都检查许可证
4. **VSCode 纯 UI** — 不请求网络，不直接访问数据库，迁移 Web 不改 Python
5. **Signal Fusion 先于 AI** — Python 算出来的分数一定比 AI 猜的准确
6. **Scanner 先于 AI** — 5000 → 100 → 20 → 3，Token 从 80万 降到 5000
7. **知识库先于 AI** — 给 AI 上下文比给 AI 自由发挥更可靠
8. **不内置破解** — 用户自配 Key，程序只提供 Adapter 框架

---

> **v2 文档结束**  
> 架构升级完成。等待下一步命令。
