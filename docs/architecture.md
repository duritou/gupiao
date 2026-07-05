# A股AI交易研究平台 — 架构设计文档

> **版本**: v1.0.0  
> **日期**: 2026-07-05  
> **阶段**: 第一阶段 — 架构设计  
> **状态**: 待评审  

---

## 目录

1. [项目总体架构](#1-项目总体架构)
2. [完整目录结构](#2-完整目录结构)
3. [每个目录职责](#3-每个目录职责)
4. [每个模块职责](#4-每个模块职责)
5. [数据库设计](#5-数据库设计)
6. [数据流设计](#6-数据流设计)
7. [AI分析流程](#7-ai分析流程)
8. [插件通信流程](#8-插件通信流程)
9. [配置管理](#9-配置管理)
10. [日志管理](#10-日志管理)
11. [缓存方案](#11-缓存方案)
12. [未来扩展方案](#12-未来扩展方案)
13. [接口设计](#13-接口设计)
14. [模块依赖图](#14-模块依赖图)
15. [整体开发路线图](#15-整体开发路线图roadmap)

---

## 1. 项目总体架构

### 1.1 架构哲学

本项目采用 **分层架构 + 六边形架构（端口与适配器）** 的混合模式：

- **分层架构** 确保关注点分离，每一层只依赖下层。
- **六边形架构** 确保核心业务逻辑与外部依赖（数据库、API、UI）解耦，方便后续替换和扩展。

### 1.2 分层总览

```
┌──────────────────────────────────────────────────────────────────┐
│                    表示层 (Presentation Layer)                     │
│  ┌─────────────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │   VS Code 插件       │  │   Web 前端    │  │   CLI 命令行      │ │
│  │   (vscode-ext/)      │  │   (web/)      │  │   (cli/)          │ │
│  └─────────┬───────────┘  └──────┬───────┘  └────────┬─────────┘ │
└────────────┼─────────────────────┼───────────────────┼───────────┘
             │                     │                   │
             └─────────────────────┼───────────────────┘
                                   │ REST / WebSocket / IPC
┌──────────────────────────────────┼───────────────────────────────┐
│                    应用层 (Application Layer)                     │
│  ┌───────────────────────────────┴──────────────────────────────┐ │
│  │                  API 网关 (api_gateway/)                       │ │
│  │  路由分发 · 认证鉴权 · 限流 · 请求/响应序列化                   │ │
│  └───────────────────────────────┬──────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌────┴─────┐ ┌──────────────────────┐ │
│  │ 策略服务  │ │ 回测服务  │ │ AI分析服务 │ │ 数据服务              │ │
│  │ strategy │ │ backtest │ │ ai_svc   │ │ data_svc             │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────┬───────────┘ │
└───────┼────────────┼────────────┼──────────────────┼─────────────┘
        │            │            │                  │
┌───────┼────────────┼────────────┼──────────────────┼─────────────┐
│       │      领域层 (Domain Layer)                  │              │
│  ┌────┴────────────┴────────────┴──────────────────┴────────────┐ │
│  │                    领域模型 (domain/)                          │ │
│  │  Stock · Strategy · Portfolio · Order · Signal · MarketData   │ │
│  │  RiskRule · BacktestResult · AnalysisReport · Indicator        │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                 领域服务 (domain/services/)                    │ │
│  │  TradingEngine · RiskManager · SignalGenerator                │ │
│  │  PortfolioOptimizer · MarketScreener                           │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                 端口接口 (domain/ports/)                       │ │
│  │  DataSourcePort · AIPort · BrokerPort · CachePort             │ │
│  │  NotificationPort · RepositoryPort                            │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
        │            │            │                  │
┌───────┼────────────┼────────────┼──────────────────┼─────────────┐
│       │    基础设施层 (Infrastructure Layer)         │              │
│  ┌────┴────────────┴────────────┴──────────────────┴────────────┐ │
│  │                    适配器 (adapters/)                          │ │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌────────────────┐  │ │
│  │  │DataSource│ │ AIProvider│ │  Broker  │ │ Notification   │  │ │
│  │  │Adapter   │ │ Adapter   │ │ Adapter  │ │ Adapter        │  │ │
│  │  │          │ │           │ │          │ │                │  │ │
│  │  │· AKShare │ │· DeepSeek │ │· SimNow  │ │· Email         │  │ │
│  │  │· Tushare │ │· OpenAI  │ │· XTP     │ │· WeChatBot     │  │ │
│  │  │· EastMoney│ │· Claude  │ │· ...     │ │· ...           │  │ │
│  │  └──────────┘ └───────────┘ └──────────┘ └────────────────┘  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    仓储实现 (repositories/)                    │ │
│  │  SQLiteRepository · PostgreSQLRepository · RedisCacheRepo     │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    外部依赖封装 (external/)                     │ │
│  │  DatabaseManager · CacheManager · MessageQueue                │ │
│  │  FileStorage · HttpClient · WebSocketClient                   │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 1.3 核心技术栈

| 层次 | 技术选型 | 说明 |
|------|---------|------|
| 语言 | Python 3.12+ | 主开发语言 |
| 包管理 | Poetry | 依赖管理与虚拟环境 |
| 异步框架 | asyncio + aiohttp | 异步IO，支持高并发数据拉取 |
| Web框架 | FastAPI | REST API + WebSocket |
| ORM | SQLAlchemy 2.0 | 异步ORM，支持SQLite/PostgreSQL |
| 数据验证 | Pydantic v2 | 请求/响应模型验证 |
| 任务队列 | Celery + Redis | 异步任务调度 |
| 缓存 | Redis / diskcache | 多级缓存 |
| 日志 | loguru | 结构化日志 |
| 测试 | pytest + pytest-asyncio | 单元测试/集成测试 |
| 代码质量 | ruff + mypy + black | Lint + 类型检查 + 格式化 |
| CI/CD | GitHub Actions | 自动化测试与部署 |
| 配置 | pydantic-settings | 类型安全的配置管理 |
| VS Code插件 | TypeScript + VS Code API | 插件开发 |
| Web前端 | React + TypeScript | 后期开发 |
| 数据库 | SQLite(dev) / PostgreSQL(prod) | 数据持久化 |
| AI模型 | DeepSeek API / OpenAI兼容 | LLM分析与决策 |

### 1.4 核心设计原则

1. **依赖倒置**: 高层模块不依赖低层模块，二者都依赖抽象（端口接口）。
2. **单一职责**: 每个类/模块只有一个变化的原因。
3. **开闭原则**: 对扩展开放（新增数据源、AI模型），对修改关闭。
4. **接口隔离**: 客户端不应依赖它不需要的接口。
5. **显式优于隐式**: 配置显式声明，依赖显式注入，类型显式标注。

---

## 2. 完整目录结构

```
jiancechengxu/
│
├── .env.example                      # 环境变量模板（提交Git）
├── .env                              # 实际环境变量（不提交Git）
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml           # Git pre-commit hooks
├── pyproject.toml                    # Poetry项目配置 + 工具配置
├── poetry.lock                       # 依赖锁定文件
├── README.md                         # 项目说明
├── CHANGELOG.md                      # 版本变更日志
├── LICENSE                           # 开源协议
├── Makefile                          # 常用命令快捷方式
│
├── docs/                             # 📚 文档目录
│   ├── architecture.md               #   本架构设计文档
│   ├── api-reference.md              #   API接口文档
│   ├── database-schema.md            #   数据库Schema详细文档
│   ├── development-guide.md          #   开发指南
│   ├── deployment-guide.md           #   部署指南
│   ├── user-guide.md                 #   用户使用手册
│   └── changelog/                    #   各版本详细Changelog
│
├── config/                           # ⚙️ 配置目录
│   ├── __init__.py
│   ├── settings.py                   #   全局配置定义（pydantic-settings）
│   ├── database.py                   #   数据库连接配置
│   ├── ai_models.py                  #   AI模型配置
│   ├── data_sources.py               #   数据源配置
│   ├── trading.py                    #   交易相关配置
│   ├── cache.py                      #   缓存配置
│   ├── logging.yaml                  #   日志配置文件
│   └── brokers/                      #   券商配置子目录
│       ├── __init__.py
│       └── simnow.py                 #   模拟交易配置
│
├── src/                              # 🏗️ 源码主目录
│   ├── __init__.py
│   │
│   ├── domain/                       # 🧠 领域层（核心业务逻辑）
│   │   ├── __init__.py
│   │   ├── models/                   #   领域模型（实体/值对象）
│   │   │   ├── __init__.py
│   │   │   ├── stock.py              #     股票实体
│   │   │   ├── market_data.py        #     行情数据值对象
│   │   │   ├── strategy.py           #     策略实体
│   │   │   ├── signal.py             #     交易信号值对象
│   │   │   ├── order.py              #     订单实体
│   │   │   ├── position.py           #     持仓实体
│   │   │   ├── portfolio.py          #     投资组合实体
│   │   │   ├── account.py            #     账户实体
│   │   │   ├── backtest.py           #     回测结果实体
│   │   │   ├── ai_analysis.py        #     AI分析报告实体
│   │   │   ├── risk.py               #     风控规则实体
│   │   │   ├── indicator.py          #     技术指标值对象
│   │   │   └── enums.py              #     枚举类型定义
│   │   ├── services/                 #   领域服务（无状态业务逻辑）
│   │   │   ├── __init__.py
│   │   │   ├── trading_engine.py     #     交易引擎
│   │   │   ├── signal_generator.py   #     信号生成器
│   │   │   ├── risk_manager.py       #     风险管理器
│   │   │   ├── portfolio_optimizer.py#     组合优化器
│   │   │   ├── market_screener.py    #     市场扫描器
│   │   │   ├── backtest_engine.py    #     回测引擎
│   │   │   └── ai_analysis_engine.py #     AI分析引擎
│   │   ├── ports/                    #   端口接口（依赖倒置）
│   │   │   ├── __init__.py
│   │   │   ├── data_source_port.py   #     数据源端口
│   │   │   ├── ai_provider_port.py   #     AI提供商端口
│   │   │   ├── broker_port.py        #     券商端口
│   │   │   ├── cache_port.py         #     缓存端口
│   │   │   ├── repository_port.py    #     仓储端口
│   │   │   ├── notification_port.py  #     通知端口
│   │   │   └── message_queue_port.py #     消息队列端口
│   │   └── events/                   #   领域事件
│   │       ├── __init__.py
│   │       ├── market_events.py      #     行情事件
│   │       ├── trading_events.py     #     交易事件
│   │       ├── signal_events.py      #     信号事件
│   │       └── risk_events.py        #     风控事件
│   │
│   ├── application/                  # 📋 应用层（用例编排）
│   │   ├── __init__.py
│   │   ├── use_cases/                #   用例/交互器
│   │   │   ├── __init__.py
│   │   │   ├── market_data_use_cases.py    # 行情数据用例
│   │   │   ├── strategy_use_cases.py       # 策略管理用例
│   │   │   ├── trading_use_cases.py        # 交易执行用例
│   │   │   ├── backtest_use_cases.py       # 回测用例
│   │   │   ├── ai_analysis_use_cases.py    # AI分析用例
│   │   │   ├── portfolio_use_cases.py      # 组合管理用例
│   │   │   ├── risk_use_cases.py           # 风控用例
│   │   │   └── system_use_cases.py         # 系统管理用例
│   │   ├── dto/                      #   数据传输对象
│   │   │   ├── __init__.py
│   │   │   ├── requests.py           #     请求DTO
│   │   │   └── responses.py          #     响应DTO
│   │   └── event_handlers/           #   事件处理器
│   │       ├── __init__.py
│   │       ├── market_handlers.py    #     行情事件处理
│   │       ├── trading_handlers.py   #     交易事件处理
│   │       └── risk_handlers.py      #     风控事件处理
│   │
│   ├── infrastructure/               # 🔧 基础设施层
│   │   ├── __init__.py
│   │   ├── adapters/                 #   适配器实现
│   │   │   ├── __init__.py
│   │   │   ├── data_sources/         #     数据源适配器
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py           #       数据源基类
│   │   │   │   ├── akshare_adapter.py#       AKShare适配器
│   │   │   │   ├── tushare_adapter.py#       Tushare适配器
│   │   │   │   ├── eastmoney_adapter.py#    东方财富适配器
│   │   │   │   └── factory.py        #       数据源工厂
│   │   │   ├── ai_providers/         #     AI模型适配器
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py           #       AI基类
│   │   │   │   ├── deepseek_adapter.py#      DeepSeek适配器
│   │   │   │   ├── openai_adapter.py #       OpenAI适配器
│   │   │   │   └── factory.py        #       AI工厂
│   │   │   ├── brokers/              #     券商适配器
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py           #       券商基类
│   │   │   │   ├── simnow_adapter.py #       SimNow模拟
│   │   │   │   └── factory.py        #       券商工厂
│   │   │   └── notifications/        #     通知适配器
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── email_adapter.py
│   │   │       ├── wechat_adapter.py
│   │   │       └── factory.py
│   │   ├── repositories/             #   仓储实现
│   │   │   ├── __init__.py
│   │   │   ├── base.py               #     仓储基类
│   │   │   ├── sqlite/               #     SQLite实现
│   │   │   │   ├── __init__.py
│   │   │   │   ├── stock_repo.py
│   │   │   │   ├── strategy_repo.py
│   │   │   │   ├── order_repo.py
│   │   │   │   ├── portfolio_repo.py
│   │   │   │   └── market_data_repo.py
│   │   │   └── postgresql/           #     PostgreSQL实现（后期）
│   │   │       ├── __init__.py
│   │   │       └── ...               #     与sqlite对称的结构
│   │   ├── orm/                      #   ORM模型（SQLAlchemy）
│   │   │   ├── __init__.py
│   │   │   ├── base.py               #     ORM基类
│   │   │   ├── stock_orm.py
│   │   │   ├── market_data_orm.py
│   │   │   ├── strategy_orm.py
│   │   │   ├── order_orm.py
│   │   │   ├── portfolio_orm.py
│   │   │   ├── ai_analysis_orm.py
│   │   │   └── risk_orm.py
│   │   ├── cache/                    #   缓存实现
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── redis_cache.py        #     Redis缓存
│   │   │   ├── disk_cache.py         #     磁盘缓存
│   │   │   └── memory_cache.py       #     内存缓存
│   │   └── external/                 #   外部依赖封装
│   │       ├── __init__.py
│   │       ├── database.py           #     数据库连接管理器
│   │       ├── http_client.py        #     HTTP客户端封装
│   │       ├── websocket_client.py   #     WebSocket客户端封装
│   │       ├── file_storage.py       #     文件存储
│   │       └── scheduler.py          #     定时任务调度器
│   │
│   ├── api/                          # 🌐 API层（FastAPI路由）
│   │   ├── __init__.py
│   │   ├── app.py                    #   FastAPI应用工厂
│   │   ├── dependencies.py           #   依赖注入容器
│   │   ├── middleware/               #   中间件
│   │   │   ├── __init__.py
│   │   │   ├── auth.py               #     认证中间件
│   │   │   ├── cors.py               #     CORS中间件
│   │   │   ├── logging.py            #     请求日志中间件
│   │   │   └── rate_limit.py         #     限流中间件
│   │   └── routes/                   #   路由定义
│   │       ├── __init__.py
│   │       ├── market_data_routes.py #     行情数据API
│   │       ├── strategy_routes.py    #     策略API
│   │       ├── trading_routes.py     #     交易API
│   │       ├── backtest_routes.py    #     回测API
│   │       ├── ai_analysis_routes.py #     AI分析API
│   │       ├── portfolio_routes.py   #     组合API
│   │       ├── risk_routes.py        #     风控API
│   │       └── system_routes.py      #     系统管理API
│   │
│   └── shared/                       # 📦 共享模块
│       ├── __init__.py
│       ├── types.py                  #   通用类型定义
│       ├── constants.py              #   全局常量
│       ├── exceptions.py             #   自定义异常
│       ├── utils/                    #   工具函数
│       │   ├── __init__.py
│       │   ├── date_utils.py         #     日期处理
│       │   ├── math_utils.py         #     数学计算
│       │   ├── validation_utils.py   #     数据验证
│       │   └── encoding_utils.py     #     编码转换
│       └── decorators.py             #   通用装饰器
│
├── tests/                            # 🧪 测试目录
│   ├── __init__.py
│   ├── conftest.py                   #   pytest全局fixtures
│   ├── fixtures/                     #   测试数据fixtures
│   │   ├── __init__.py
│   │   ├── market_data_fixtures.py
│   │   ├── strategy_fixtures.py
│   │   └── order_fixtures.py
│   ├── unit/                         #   单元测试
│   │   ├── __init__.py
│   │   ├── domain/
│   │   │   ├── test_models.py
│   │   │   └── test_services.py
│   │   ├── application/
│   │   │   └── test_use_cases.py
│   │   └── infrastructure/
│   │       ├── test_adapters.py
│   │       └── test_repositories.py
│   ├── integration/                  #   集成测试
│   │   ├── __init__.py
│   │   ├── test_api_routes.py
│   │   ├── test_database.py
│   │   └── test_data_sources.py
│   └── e2e/                          #   端到端测试
│       ├── __init__.py
│       └── test_trading_flow.py
│
├── scripts/                          # 📜 运维/工具脚本
│   ├── init_database.py              #   初始化数据库
│   ├── migrate_database.py           #   数据库迁移
│   ├── sync_market_data.py           #   同步行情数据
│   ├── run_backtest.py               #   运行回测
│   ├── generate_report.py            #   生成报告
│   └── seed_data.py                  #   填充测试数据
│
├── vscode-ext/                       # 🔌 VS Code 插件（TypeScript）
│   ├── package.json                  #   插件清单
│   ├── tsconfig.json
│   ├── src/
│   │   ├── extension.ts             #   插件入口
│   │   ├── commands/                 #   命令实现
│   │   ├── views/                    #   侧边栏/面板视图
│   │   ├── providers/                #   数据提供者
│   │   └── utils/                    #   工具函数
│   └── tests/
│
├── web/                              # 🌐 Web 前端（后期开发）
│   ├── package.json
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── store/
│   └── public/
│
├── deploy/                           # 🚀 部署配置
│   ├── docker/
│   │   ├── Dockerfile
│   │   ├── Dockerfile.dev
│   │   └── docker-compose.yml
│   ├── nginx/
│   │   └── nginx.conf
│   └── k8s/                          #   Kubernetes（后期）
│       └── ...
│
└── data/                             # 💾 本地数据（不提交Git）
    ├── sqlite/                       #   SQLite数据库文件
    ├── cache/                        #   磁盘缓存
    ├── logs/                         #   日志文件
    └── exports/                      #   导出文件（报告/CSV等）
```

---

## 3. 每个目录职责

| 目录 | 职责 | 依赖方向 |
|------|------|---------|
| `docs/` | 所有项目文档：架构设计、API参考、开发指南、部署指南、用户手册 | 无依赖 |
| `config/` | 集中式配置管理：数据库连接、AI模型参数、数据源凭证、缓存策略、日志格式 | 仅依赖 `pydantic-settings` + `.env` |
| `src/domain/` | **核心层**：领域模型、领域服务、端口接口、领域事件。不含任何外部依赖 | 零外部依赖（纯Python） |
| `src/application/` | **用例编排层**：实现具体业务用例，编排领域对象完成业务流程 | 仅依赖 `domain` |
| `src/infrastructure/` | **实现层**：数据源适配器、AI适配器、ORM、仓储、缓存、外部服务封装 | 依赖 `domain` 端口接口 |
| `src/api/` | **接入层**：FastAPI应用、路由、中间件、依赖注入。对外暴露REST/WebSocket | 依赖 `application` + `infrastructure` |
| `src/shared/` | 跨层共享：类型定义、异常类、工具函数、常量、装饰器 | 被所有层依赖 |
| `tests/` | 单元测试、集成测试、端到端测试、测试fixtures | 依赖 `src/` |
| `scripts/` | 运维脚本：数据库初始化、数据同步、回测执行、报告生成 | 依赖 `src/` |
| `vscode-ext/` | VS Code插件：通过IPC/HTTP与Python后端通信 | 独立TypeScript项目 |
| `web/` | Web前端（后期）：React SPA，通过HTTP/WebSocket通信 | 独立TypeScript项目 |
| `deploy/` | Docker、Nginx、K8s部署配置 | 无代码依赖 |
| `data/` | 运行时数据：SQLite文件、缓存、日志、导出文件 | 被 `infrastructure` 读写 |

### 3.1 依赖规则（严格遵守）

```
api ──────────────► application ──────────────► domain ◄────────────── infrastructure
│                        │                          ▲                         │
│                        │                          │                         │
│                        └──────────────────────────┼─────────────────────────┘
│                                                   │
└──────────────────── shared ◄──────────────────────┘
```

- **domain 不依赖任何人**（纯净核心）
- **application 依赖 domain**（编排领域对象）
- **infrastructure 实现 domain 端口**（依赖倒置）
- **api 依赖 application + infrastructure**（组装）
- **所有层可依赖 shared**（公共工具）
- **外层依赖内层，内层不知道外层**

---

## 4. 每个模块职责

### 4.1 领域模型 (`src/domain/models/`)

| 模块 | 类型 | 职责 |
|------|------|------|
| `stock.py` | 实体 | 股票基础信息：代码、名称、市场、行业、上市日期、状态 |
| `market_data.py` | 值对象 | K线/分时/实时行情：OHLCV、成交额、换手率、涨跌幅 |
| `strategy.py` | 实体 | 交易策略定义：名称、参数、信号条件、过滤规则、仓位规则 |
| `signal.py` | 值对象 | 交易信号：股票、方向（买入/卖出）、强度、置信度、生成时间 |
| `order.py` | 实体 | 订单：类型（市价/限价）、方向、数量、价格、状态、成交明细 |
| `position.py` | 实体 | 持仓：股票、数量、成本、浮动盈亏、持仓天数 |
| `portfolio.py` | 实体 | 投资组合：持仓集合、总资产、现金、收益率、夏普比率 |
| `account.py` | 实体 | 交易账户：资金信息、可用资金、冻结资金、总资产 |
| `backtest.py` | 实体 | 回测结果：收益率序列、最大回撤、夏普比率、胜率、交易记录 |
| `ai_analysis.py` | 实体 | AI分析报告：分析类型、输入数据范围、分析结论、置信度、Token消耗 |
| `risk.py` | 实体 | 风控规则：单票上限、行业上限、止损线、最大回撤、黑名单 |
| `indicator.py` | 值对象 | 技术指标：MA/MACD/RSI/KDJ/BOLL等计算结果 |
| `enums.py` | 枚举 | 全局枚举：市场类型、订单类型、订单状态、信号方向、K线周期等 |

### 4.2 领域服务 (`src/domain/services/`)

| 模块 | 职责 | 关键方法 |
|------|------|---------|
| `trading_engine.py` | 交易执行核心：信号→订单→成交的生命周期管理 | `execute_signal()`, `match_order()`, `calculate_commission()` |
| `signal_generator.py` | 基于策略规则生成买卖信号 | `generate_signals()`, `filter_signals()`, `rank_signals()` |
| `risk_manager.py` | 实时风控检查：仓位校验、止损校验、行业集中度 | `check_order_risk()`, `check_portfolio_risk()`, `check_blacklist()` |
| `portfolio_optimizer.py` | 组合优化：资金分配、再平衡、最大夏普/最小方差 | `optimize_weights()`, `rebalance()`, `calculate_var()` |
| `market_screener.py` | 市场扫描：按条件筛选股票池 | `screen_by_indicator()`, `screen_by_fundamental()`, `screen_by_pattern()` |
| `backtest_engine.py` | 回测引擎：历史数据模拟交易，计算绩效指标 | `run_backtest()`, `calculate_metrics()`, `generate_trade_log()` |
| `ai_analysis_engine.py` | AI分析编排：组装prompt→调用AI→解析结果→生成报告 | `analyze_market()`, `analyze_stock()`, `analyze_strategy()` |

### 4.3 端口接口 (`src/domain/ports/`)

| 接口 | 职责 | 核心抽象方法 |
|------|------|------------|
| `data_source_port.py` | 定义数据源抽象 | `get_kline()`, `get_realtime()`, `get_stock_list()`, `get_financials()` |
| `ai_provider_port.py` | 定义AI模型抽象 | `chat()`, `analyze()`, `stream_chat()`, `count_tokens()` |
| `broker_port.py` | 定义券商接口抽象 | `submit_order()`, `cancel_order()`, `query_position()`, `query_account()` |
| `cache_port.py` | 定义缓存抽象 | `get()`, `set()`, `delete()`, `exists()`, `ttl()` |
| `repository_port.py` | 定义仓储抽象（泛型） | `save()`, `find_by_id()`, `find_all()`, `delete()`, `count()` |
| `notification_port.py` | 定义通知抽象 | `send()`, `send_batch()`, `validate_target()` |
| `message_queue_port.py` | 定义消息队列抽象 | `publish()`, `subscribe()`, `ack()`, `nack()` |

### 4.4 应用层用例 (`src/application/use_cases/`)

| 模块 | 职责 | 依赖的领域服务 |
|------|------|--------------|
| `market_data_use_cases.py` | 行情数据查询/订阅/同步的用例编排 | 无（直接调用 DataSourcePort） |
| `strategy_use_cases.py` | 策略CRUD、参数优化、策略对比 | SignalGenerator |
| `trading_use_cases.py` | 交易执行流程：下单→风控→成交→通知 | TradingEngine, RiskManager |
| `backtest_use_cases.py` | 回测流程：加载数据→运行→生成报告 | BacktestEngine |
| `ai_analysis_use_cases.py` | AI分析编排：选择股票→准备数据→调用AI→保存报告 | AIAnalysisEngine |
| `portfolio_use_cases.py` | 组合管理：查询/调仓/优化/再平衡 | PortfolioOptimizer |
| `risk_use_cases.py` | 风控规则管理：CRUD + 实时监控 | RiskManager |
| `system_use_cases.py` | 系统管理：健康检查、数据同步状态、配置管理 | 无 |

### 4.5 基础设施适配器 (`src/infrastructure/adapters/`)

| 子模块 | 职责 |
|--------|------|
| `data_sources/base.py` | 数据源抽象基类，定义统一接口 |
| `data_sources/akshare_adapter.py` | AKShare数据源实现（免费，覆盖A股全量数据） |
| `data_sources/tushare_adapter.py` | Tushare Pro数据源实现（高质量，需Token） |
| `data_sources/eastmoney_adapter.py` | 东方财富数据源实现（实时行情快） |
| `data_sources/factory.py` | 数据源工厂：根据配置创建对应适配器实例 |
| `ai_providers/base.py` | AI模型抽象基类，定义统一接口 |
| `ai_providers/deepseek_adapter.py` | DeepSeek API适配器（默认） |
| `ai_providers/openai_adapter.py` | OpenAI兼容API适配器（通用） |
| `ai_providers/factory.py` | AI工厂：根据配置创建对应模型实例 |
| `brokers/base.py` | 券商抽象基类 |
| `brokers/simnow_adapter.py` | SimNow模拟交易适配器（CTP仿真） |
| `brokers/factory.py` | 券商工厂 |
| `notifications/base.py` | 通知抽象基类 |
| `notifications/email_adapter.py` | 邮件通知 |
| `notifications/wechat_adapter.py` | 微信机器人通知 |
| `notifications/factory.py` | 通知工厂 |

### 4.6 API路由 (`src/api/routes/`)

| 模块 | HTTP方法 | 端点前缀 | 职责 |
|------|---------|---------|------|
| `market_data_routes.py` | GET/POST | `/api/v1/market/` | 行情数据查询、实时订阅 |
| `strategy_routes.py` | CRUD | `/api/v1/strategies/` | 策略管理 |
| `trading_routes.py` | POST/DELETE | `/api/v1/trading/` | 下单、撤单、查单 |
| `backtest_routes.py` | POST/GET | `/api/v1/backtest/` | 回测执行、结果查询 |
| `ai_analysis_routes.py` | POST/GET | `/api/v1/ai/` | AI分析任务、报告查询 |
| `portfolio_routes.py` | GET/POST | `/api/v1/portfolio/` | 组合查询、调仓 |
| `risk_routes.py` | CRUD | `/api/v1/risk/` | 风控规则管理 |
| `system_routes.py` | GET | `/api/v1/system/` | 健康检查、状态监控 |

---

## 5. 数据库设计

### 5.1 设计原则

1. **第一阶段使用SQLite**：零配置，文件存储，便于开发调试。
2. **ORM抽象**：通过SQLAlchemy ORM屏蔽底层差异，后期平滑迁移PostgreSQL。
3. **命名规范**：表名使用snake_case复数形式；字段名snake_case。
4. **时间字段**：统一使用UTC时间戳存储，API层转换为本地时间。
5. **软删除**：核心业务表使用 `deleted_at` 字段软删除，数据不可逆。

### 5.2 ER图（核心表）

```
                         ┌──────────────────┐
                         │     stocks       │
                         │──────────────────│
                         │ PK id            │
                         │ code (000001.SZ) │
                         │ name             │
                         │ market           │
                         │ industry         │
                         │ listing_date     │
                         │ status           │
                         └────────┬─────────┘
                                  │ 1
                                  │
                    ┌─────────────┼─────────────┐
                    │ *           │ *           │ *
          ┌────────┴──────┐ ┌───┴───────────┐ ┌┴──────────────┐
          │ market_data   │ │ positions     │ │ ai_analyses   │
          │───────────────│ │───────────────│ │───────────────│
          │ PK id         │ │ PK id         │ │ PK id         │
          │ FK stock_id   │ │ FK stock_id   │ │ FK stock_id   │
          │ period        │ │ FK account_id │ │ analysis_type │
          │ open          │ │ quantity      │ │ prompt        │
          │ high          │ │ avg_cost      │ │ result        │
          │ low           │ │ current_price │ │ confidence    │
          │ close         │ │ profit_loss   │ │ tokens_used   │
          │ volume        │ │ created_at    │ │ model_name    │
          │ amount        │ │ updated_at    │ │ created_at    │
          │ timestamp     │ └───────────────┘ └───────────────┘
          └───────────────┘
                                  *
                          ┌───────┴────────┐
                          │                │
                  ┌───────┴──────┐  ┌──────┴──────┐
                  │ orders       │  │ portfolios  │
                  │──────────────│  │─────────────│
                  │ PK id        │  │ PK id       │
                  │ FK account_id│  │ FK account_id│
                  │ FK stock_id  │  │ name        │
                  │ FK strategy_id│ │ total_value │
                  │ order_type   │  │ cash        │
                  │ direction    │  │ positions_json│
                  │ quantity     │  │ created_at  │
                  │ price        │  │ updated_at  │
                  │ status       │  └─────────────┘
                  │ filled_qty  │
                  │ filled_price│
                  │ created_at  │
                  │ updated_at  │
                  └─────────────┘
                          *
                    ┌─────┴──────────┐
                    │                │
            ┌───────┴──────┐  ┌──────┴──────────┐
            │ strategies   │  │ accounts        │
            │──────────────│  │─────────────────│
            │ PK id        │  │ PK id           │
            │ name         │  │ broker_type     │
            │ description  │  │ initial_capital │
            │ params_json  │  │ available_cash  │
            │ status       │  │ frozen_cash     │
            │ created_at   │  │ total_asset     │
            │ updated_at   │  │ created_at      │
            └──────────────┘  │ updated_at      │
                              └─────────────────┘
                                      *
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
            ┌───────┴──────┐  ┌───────┴──────┐  ┌───────┴──────┐
            │ risk_rules   │  │ backtests    │  │ notifications│
            │──────────────│  │─────────────│  │──────────────│
            │ PK id        │  │ PK id        │  │ PK id        │
            │ FK account_id│  │ FK strategy_id│ │ type         │
            │ rule_type    │  │ start_date   │  │ recipient    │
            │ params_json  │  │ end_date     │  │ title        │
            │ is_enabled   │  │ metrics_json │  │ content      │
            │ created_at   │  │ trades_json  │  │ is_read      │
            │ updated_at   │  │ created_at   │  │ created_at   │
            └──────────────┘  └──────────────┘  └──────────────┘
```

### 5.3 完整表结构

#### 5.3.1 stocks（股票基础信息表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `code` | VARCHAR(20) | NOT NULL, UNIQUE | 股票代码，如 "000001.SZ" |
| `name` | VARCHAR(50) | NOT NULL | 股票名称 |
| `market` | VARCHAR(10) | NOT NULL | 市场：SH(上海)/SZ(深圳)/BJ(北交所) |
| `industry` | VARCHAR(100) | | 申万一级行业 |
| `sub_industry` | VARCHAR(100) | | 申万二级行业 |
| `listing_date` | DATE | | 上市日期 |
| `delisting_date` | DATE | | 退市日期（NULL=正常上市） |
| `status` | VARCHAR(20) | DEFAULT 'active' | 状态：active/suspended/delisted |
| `total_shares` | BIGINT | | 总股本 |
| `float_shares` | BIGINT | | 流通股本 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |
| `deleted_at` | DATETIME | | 软删除时间 |

**索引**: `idx_stocks_code` (code), `idx_stocks_industry` (industry), `idx_stocks_status` (status)

#### 5.3.2 market_data（行情数据表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `stock_id` | INTEGER | FK → stocks.id, NOT NULL | 股票ID |
| `period` | VARCHAR(10) | NOT NULL | K线周期：1m/5m/15m/30m/60m/1d/1w/1M |
| `timestamp` | DATETIME | NOT NULL | K线时间戳（UTC） |
| `open` | DECIMAL(12,4) | NOT NULL | 开盘价 |
| `high` | DECIMAL(12,4) | NOT NULL | 最高价 |
| `low` | DECIMAL(12,4) | NOT NULL | 最低价 |
| `close` | DECIMAL(12,4) | NOT NULL | 收盘价 |
| `volume` | BIGINT | NOT NULL | 成交量（股） |
| `amount` | DECIMAL(18,2) | NOT NULL | 成交额（元） |
| `turnover_rate` | DECIMAL(8,4) | | 换手率（%） |
| `change_pct` | DECIMAL(8,4) | | 涨跌幅（%） |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |

**索引**: `idx_md_stock_period_time` (stock_id, period, timestamp) UNIQUE, `idx_md_timestamp` (timestamp)

#### 5.3.3 strategies（策略表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `name` | VARCHAR(100) | NOT NULL | 策略名称 |
| `description` | TEXT | | 策略描述 |
| `strategy_type` | VARCHAR(50) | NOT NULL | 策略类型：trend/mean_reversion/momentum/grid/ai |
| `params_json` | TEXT | NOT NULL | 策略参数（JSON） |
| `universe_filter` | TEXT | | 股票池筛选条件（JSON） |
| `status` | VARCHAR(20) | DEFAULT 'draft' | 状态：draft/active/paused/archived |
| `version` | INTEGER | DEFAULT 1 | 版本号 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |
| `deleted_at` | DATETIME | | 软删除时间 |

#### 5.3.4 orders（订单表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `account_id` | INTEGER | FK → accounts.id, NOT NULL | 账户ID |
| `stock_id` | INTEGER | FK → stocks.id, NOT NULL | 股票ID |
| `strategy_id` | INTEGER | FK → strategies.id | 触发策略ID |
| `order_type` | VARCHAR(20) | NOT NULL | 订单类型：market/limit/stop |
| `direction` | VARCHAR(10) | NOT NULL | 方向：buy/sell |
| `quantity` | INTEGER | NOT NULL | 委托数量（股） |
| `price` | DECIMAL(12,4) | | 委托价格（市价单为NULL） |
| `status` | VARCHAR(20) | DEFAULT 'pending' | 状态：pending/submitted/partial_filled/filled/cancelled/rejected |
| `filled_quantity` | INTEGER | DEFAULT 0 | 已成交数量 |
| `filled_avg_price` | DECIMAL(12,4) | | 成交均价 |
| `commission` | DECIMAL(12,4) | DEFAULT 0 | 手续费 |
| `error_message` | TEXT | | 拒绝/失败原因 |
| `external_order_id` | VARCHAR(100) | | 外部系统订单号 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |

**索引**: `idx_orders_account` (account_id), `idx_orders_status` (status), `idx_orders_created` (created_at)

#### 5.3.5 positions（持仓表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `account_id` | INTEGER | FK → accounts.id, NOT NULL | 账户ID |
| `stock_id` | INTEGER | FK → stocks.id, NOT NULL | 股票ID |
| `quantity` | INTEGER | NOT NULL | 持仓数量 |
| `available_quantity` | INTEGER | NOT NULL | 可卖数量 |
| `avg_cost` | DECIMAL(12,4) | NOT NULL | 持仓成本 |
| `current_price` | DECIMAL(12,4) | | 当前市价 |
| `market_value` | DECIMAL(18,2) | | 市值 |
| `profit_loss` | DECIMAL(18,2) | | 浮动盈亏 |
| `profit_loss_pct` | DECIMAL(8,4) | | 盈亏比例（%） |
| `holding_days` | INTEGER | DEFAULT 0 | 持仓天数 |
| `created_at` | DATETIME | DEFAULT NOW | 建仓时间 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |

**索引**: `idx_positions_account_stock` (account_id, stock_id) UNIQUE

#### 5.3.6 accounts（账户表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `name` | VARCHAR(100) | NOT NULL | 账户名称 |
| `broker_type` | VARCHAR(50) | NOT NULL | 券商类型：simnow/xtp/manual |
| `initial_capital` | DECIMAL(18,2) | NOT NULL | 初始资金 |
| `available_cash` | DECIMAL(18,2) | NOT NULL | 可用资金 |
| `frozen_cash` | DECIMAL(18,2) | DEFAULT 0 | 冻结资金 |
| `total_asset` | DECIMAL(18,2) | NOT NULL | 总资产 |
| `total_profit_loss` | DECIMAL(18,2) | DEFAULT 0 | 总盈亏 |
| `config_json` | TEXT | | 券商配置（JSON） |
| `status` | VARCHAR(20) | DEFAULT 'active' | 状态 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |

#### 5.3.7 portfolios（投资组合表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `account_id` | INTEGER | FK → accounts.id, NOT NULL | 关联账户 |
| `name` | VARCHAR(100) | NOT NULL | 组合名称 |
| `snapshot_date` | DATE | NOT NULL | 快照日期 |
| `total_value` | DECIMAL(18,2) | NOT NULL | 组合总价值 |
| `cash` | DECIMAL(18,2) | NOT NULL | 现金 |
| `positions_json` | TEXT | NOT NULL | 持仓明细（JSON快照） |
| `metrics_json` | TEXT | | 绩效指标（JSON） |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |

**索引**: `idx_portfolios_account_date` (account_id, snapshot_date)

#### 5.3.8 backtests（回测表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `strategy_id` | INTEGER | FK → strategies.id, NOT NULL | 策略ID |
| `name` | VARCHAR(200) | NOT NULL | 回测名称 |
| `start_date` | DATE | NOT NULL | 回测开始日期 |
| `end_date` | DATE | NOT NULL | 回测结束日期 |
| `initial_capital` | DECIMAL(18,2) | NOT NULL | 初始资金 |
| `universe_json` | TEXT | | 股票池（JSON） |
| `metrics_json` | TEXT | NOT NULL | 绩效指标（JSON） |
| `trades_json` | TEXT | | 交易记录（JSON） |
| `equity_curve_json` | TEXT | | 权益曲线（JSON） |
| `status` | VARCHAR(20) | DEFAULT 'running' | 状态：running/completed/failed |
| `error_message` | TEXT | | 失败原因 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |
| `completed_at` | DATETIME | | 完成时间 |

#### 5.3.9 ai_analyses（AI分析表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `stock_id` | INTEGER | FK → stocks.id | 分析标的（可为NULL=大盘分析） |
| `analysis_type` | VARCHAR(50) | NOT NULL | 类型：market_review/stock_analysis/strategy_advice/risk_alert |
| `prompt_template` | VARCHAR(100) | | 使用的Prompt模板名称 |
| `input_data_json` | TEXT | | 输入数据摘要（JSON） |
| `result_json` | TEXT | NOT NULL | AI分析结果（JSON） |
| `confidence` | DECIMAL(4,3) | | 置信度 0.000-1.000 |
| `tokens_used` | INTEGER | | Token消耗量 |
| `model_name` | VARCHAR(50) | NOT NULL | 模型名称 |
| `latency_ms` | INTEGER | | 响应延迟（毫秒） |
| `is_starred` | BOOLEAN | DEFAULT FALSE | 是否收藏 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |

**索引**: `idx_ai_stock_type` (stock_id, analysis_type), `idx_ai_created` (created_at)

#### 5.3.10 risk_rules（风控规则表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `account_id` | INTEGER | FK → accounts.id, NOT NULL | 关联账户 |
| `name` | VARCHAR(100) | NOT NULL | 规则名称 |
| `rule_type` | VARCHAR(50) | NOT NULL | 类型：position_limit/stop_loss/industry_limit/drawdown_limit/blacklist |
| `params_json` | TEXT | NOT NULL | 规则参数（JSON） |
| `is_enabled` | BOOLEAN | DEFAULT TRUE | 是否启用 |
| `priority` | INTEGER | DEFAULT 0 | 优先级（数字越大越优先） |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |
| `updated_at` | DATETIME | DEFAULT NOW | 更新时间 |

#### 5.3.11 signals（信号表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `strategy_id` | INTEGER | FK → strategies.id, NOT NULL | 策略ID |
| `stock_id` | INTEGER | FK → stocks.id, NOT NULL | 股票ID |
| `direction` | VARCHAR(10) | NOT NULL | 方向：buy/sell |
| `strength` | DECIMAL(5,2) | | 信号强度 0-100 |
| `confidence` | DECIMAL(4,3) | | 置信度 0.000-1.000 |
| `reason` | TEXT | | 信号生成理由 |
| `is_executed` | BOOLEAN | DEFAULT FALSE | 是否已执行 |
| `executed_order_id` | INTEGER | FK → orders.id | 执行的订单ID |
| `created_at` | DATETIME | DEFAULT NOW | 信号时间 |

#### 5.3.12 notifications（通知表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `type` | VARCHAR(50) | NOT NULL | 类型：trade_confirm/risk_alert/ai_report/system |
| `recipient` | VARCHAR(200) | NOT NULL | 接收者 |
| `title` | VARCHAR(200) | NOT NULL | 通知标题 |
| `content` | TEXT | NOT NULL | 通知内容 |
| `is_read` | BOOLEAN | DEFAULT FALSE | 是否已读 |
| `created_at` | DATETIME | DEFAULT NOW | 创建时间 |

#### 5.3.13 system_logs（系统日志表）

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 内部主键 |
| `level` | VARCHAR(20) | NOT NULL | 级别：DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `module` | VARCHAR(100) | | 模块名 |
| `message` | TEXT | NOT NULL | 日志消息 |
| `extra_json` | TEXT | | 额外上下文（JSON） |
| `created_at` | DATETIME | DEFAULT NOW | 时间 |

---

## 6. 数据流设计

### 6.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          外部数据源                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                │
│  │ AKShare  │  │ Tushare  │  │ EastMoney│  │ 其他...   │                │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘                │
└───────┼──────────────┼──────────────┼──────────────┼────────────────────┘
        │              │              │              │
        └──────────────┴──────────────┴──────────────┘
                           │
                    ┌──────┴──────┐
                    │  数据源适配器 │  ← 统一接口，屏蔽差异
                    │  Factory     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴────┐ ┌────┴─────┐
        │  数据清洗   │ │ 数据验证│ │ 数据标准化│
        │  Cleaner   │ │Validator│ │Normalizer│
        └─────┬─────┘ └───┬────┘ └────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────┴──────┐
                    │  数据管道     │  ← 数据分发中枢
                    │  Pipeline    │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
  ┌─────┴─────┐     ┌──────┴──────┐    ┌──────┴──────┐
  │  数据库存储 │     │  缓存更新    │    │  事件发布    │
  │ Repository │     │  Cache      │    │  Events     │
  └─────┬─────┘     └──────┬──────┘    └──────┬──────┘
        │                  │                  │
        │                  │           ┌──────┴──────┐
        │                  │           │  消息队列    │
        │                  │           │  Redis Pub  │
        │                  │           └──────┬──────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴────┐ ┌────┴─────┐
        │ 策略引擎    │ │AI分析  │ │ 用户查询  │
        │ Strategy   │ │Engine  │ │ API       │
        └─────┬─────┘ └───┬────┘ └────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────┴──────┐
                    │  表示层      │
                    │  VS Code /  │
                    │  Web / CLI  │
                    └─────────────┘
```

### 6.2 关键数据流场景

#### 场景1：行情数据同步（定时任务）

```
定时器触发 (APScheduler)
  → DataSyncUseCase.sync_market_data()
  → DataSourcePort.get_kline(stock_list, period, start, end)
  → [Adapter] 调用 AKShare/Tushare API
  → DataCleaner.clean(raw_data) → 处理缺失值、异常值
  → DataValidator.validate(cleaned_data) → 校验OHLC逻辑
  → DataNormalizer.normalize(validated_data) → 复权处理
  → RepositoryPort.batch_upsert(normalized_data)
  → CachePort.set(f"kline:{stock}:{period}", data, ttl=3600)
  → EventBus.publish(MarketDataUpdatedEvent)
  → [订阅者] 策略引擎重新计算信号 / 前端刷新
```

#### 场景2：AI分析请求

```
用户发起分析 (VS Code/Web/CLI)
  → API Gateway → AIAnalysisUseCase
  → AIAnalysisEngine.analyze(stock_id, analysis_type)
  → DataSourcePort.get_kline() + get_financials()  ← 并行拉取多种数据
  → PromptBuilder.build(analysis_type, context_data)  ← 组装Prompt
  → AIPort.chat(prompt, model, temperature)
  → [Adapter] DeepSeek API / OpenAI API
  → ResultParser.parse(ai_response)  ← 解析JSON，提取结论
  → RepositoryPort.save(ai_analysis_entity)
  → NotificationPort.send(analysis_complete_notification)
  → 返回 AnalysisResponseDTO 给前端
```

#### 场景3：交易信号→下单→成交

```
策略定时检查 (APScheduler 或 事件驱动)
  → SignalGenerator.generate_signals(strategy, market_data)
  → Signal 列表生成
  → [每个Signal] RiskManager.check_order_risk(signal, account, positions)
  → [通过] TradingEngine.execute_signal(signal, account)
  → Order 实体创建 (status=pending)
  → BrokerPort.submit_order(order)
  → [Adapter] SimNow/券商API
  → [成交回报] BrokerPort 异步回调/轮询
  → Order 状态更新 (filled/partial_filled)
  → Position 更新
  → Account 更新
  → NotificationPort.send(trade_confirm)
  → EventBus.publish(OrderFilledEvent)
```

#### 场景4：回测流程

```
用户提交回测参数
  → BacktestUseCase.run_backtest(strategy_id, start, end, capital)
  → Backtest 实体创建 (status=running)
  → [异步任务] Celery Task
  → DataSourcePort.get_kline(universe, period, start, end)  ← 批量加载历史数据
  → BacktestEngine.run(strategy, historical_data, initial_capital)
  → [逐日模拟]
     → SignalGenerator.generate_signals()
     → RiskManager.check_order_risk()
     → TradingEngine.simulate_execution()  ← 模拟成交（考虑滑点/手续费）
     → Portfolio.update()
  → PerformanceCalculator.calculate(equity_curve, trades)
  → Backtest 实体更新 (status=completed, metrics_json, trades_json)
  → NotificationPort.send(backtest_complete)
  → 返回 BacktestResultDTO
```

---

## 7. AI分析流程

### 7.1 AI分析架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      AI Analysis Pipeline                        │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐ │
│  │ 1.上下文  │   │ 2.Prompt │   │ 3.模型    │   │ 4.结果       │ │
│  │   构建    │──►│   组装    │──►│   调用    │──►│   解析        │ │
│  │ Context  │   │ Builder  │   │ Provider │   │ Parser       │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────┬───────┘ │
│       │              │              │                 │          │
│  ┌────┴─────┐   ┌────┴─────┐   ┌────┴─────┐   ┌──────┴───────┐ │
│  │ 行情数据  │   │ Prompt   │   │ DeepSeek │   │ 结构化JSON   │ │
│  │ 财务数据  │   │ 模板库   │   │ OpenAI   │   │ 报告实体     │ │
│  │ 新闻舆情  │   │          │   │ Claude   │   │ 置信度评估   │ │
│  │ 技术指标  │   │          │   │ ...      │   │              │ │
│  └──────────┘   └──────────┘   └──────────┘   └──────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 AI分析类型

| 分析类型 | 输入数据 | Prompt重点 | 输出 |
|---------|---------|-----------|------|
| **market_review** | 大盘指数K线、涨跌家数、板块资金流 | 市场整体判断、关键点位、风险提示 | 市场综述报告 |
| **stock_analysis** | 个股K线、财务数据、技术指标、新闻 | 多维度分析：技术面+基本面+资金面 | 个股分析报告 |
| **strategy_advice** | 策略回测结果、当前持仓、市场环境 | 策略表现评估、参数优化建议 | 策略建议报告 |
| **risk_alert** | 持仓风险指标、市场波动率、黑天鹅事件 | 风险识别、预警级别、应对建议 | 风险预警报告 |
| **sector_analysis** | 行业板块数据、龙头股、政策新闻 | 行业趋势、轮动判断、配置建议 | 行业分析报告 |
| **daily_scan** | 全市场行情、技术形态、异常波动 | 异动扫描、形态识别、机会提示 | 日度扫描报告 |

### 7.3 Prompt管理

```
config/prompts/
├── system_prompts/
│   ├── financial_analyst.yaml     # 金融分析师角色定义
│   ├── risk_manager.yaml          # 风控专家角色定义
│   └── strategy_advisor.yaml      # 策略顾问角色定义
├── templates/
│   ├── market_review.j2           # 市场综述模板
│   ├── stock_analysis.j2          # 个股分析模板
│   ├── strategy_advice.j2         # 策略建议模板
│   ├── risk_alert.j2              # 风险预警模板
│   └── daily_scan.j2              # 日度扫描模板
└── few_shot_examples/
    ├── stock_analysis_examples.yaml
    └── market_review_examples.yaml
```

### 7.4 AI调用策略

```
┌──────────────────────────────────────┐
│          AI调用决策流程               │
│                                      │
│  请求进入                             │
│    │                                 │
│    ▼                                 │
│  ┌─────────────┐                     │
│  │ 缓存检查     │──命中──► 返回缓存    │
│  │ (相同输入+   │         (TTL内)     │
│  │  时间窗口)   │                     │
│  └──────┬──────┘                     │
│         │ 未命中                      │
│         ▼                            │
│  ┌─────────────┐                     │
│  │ 速率限制检查 │──超限──► 排队等待    │
│  └──────┬──────┘                     │
│         │ 通过                        │
│         ▼                            │
│  ┌─────────────┐                     │
│  │ 模型选择     │                     │
│  │ · 简单任务→  │                     │
│  │   cheap模型  │                     │
│  │ · 复杂分析→  │                     │
│  │   premium模型│                     │
│  └──────┬──────┘                     │
│         │                            │
│         ▼                            │
│  ┌─────────────┐                     │
│  │ API调用      │                     │
│  │ · 重试3次    │                     │
│  │ · 超时30s    │                     │
│  │ · 流式输出   │                     │
│  └──────┬──────┘                     │
│         │                            │
│         ▼                            │
│  ┌─────────────┐                     │
│  │ 结果验证     │──失败──► 降级/报错   │
│  │ · JSON解析   │                     │
│  │ · Schema校验 │                     │
│  └──────┬──────┘                     │
│         │ 成功                        │
│         ▼                            │
│  ┌─────────────┐                     │
│  │ 结果写入缓存 │                     │
│  │ + 持久化     │                     │
│  └─────────────┘                     │
└──────────────────────────────────────┘
```

---

## 8. 插件通信流程

### 8.1 通信架构

```
┌──────────────────────────────────────────────────────────┐
│                    VS Code 工作区                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │              VS Code Extension (TypeScript)         │  │
│  │                                                    │  │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────────┐  │  │
│  │  │ Sidebar  │ │ Webview   │ │ Status Bar       │  │  │
│  │  │ Provider │ │ Panel     │ │ Indicator         │  │  │
│  │  └────┬─────┘ └─────┬─────┘ └────────┬─────────┘  │  │
│  │       │             │               │              │  │
│  │       └─────────────┼───────────────┘              │  │
│  │                     │                              │  │
│  │              ┌──────┴──────┐                       │  │
│  │              │  IPC Client │                       │  │
│  │              └──────┬──────┘                       │  │
│  └─────────────────────┼─────────────────────────────┘  │
└────────────────────────┼────────────────────────────────┘
                         │
           ① Unix Socket / Named Pipe / HTTP
                         │
┌────────────────────────┼────────────────────────────────┐
│                        │                                 │
│  ┌─────────────────────┴──────────────────────────────┐ │
│  │           Python Backend (独立进程)                   │ │
│  │                                                     │ │
│  │  ┌─────────────────────────────────────────────┐   │ │
│  │  │           IPC Server (src/ipc/)              │   │ │
│  │  │  · JSON-RPC over Unix Socket                │   │ │
│  │  │  · 请求路由 → Use Cases                      │   │ │
│  │  │  · 事件推送 → Extension                      │   │ │
│  │  └──────────────────┬──────────────────────────┘   │ │
│  │                     │                               │ │
│  │              ┌──────┴──────┐                        │ │
│  │              │  API Layer  │                        │ │
│  │              │  (FastAPI)  │                        │ │
│  │              └──────┬──────┘                        │ │
│  │                     │                               │ │
│  │              ┌──────┴──────┐                        │ │
│  │              │ Application │                        │ │
│  │              │    Layer    │                        │ │
│  │              └─────────────┘                        │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 8.2 通信协议（JSON-RPC 2.0）

```typescript
// VS Code Extension → Python Backend (Request)
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "method": "ai.analyze_stock",
  "params": {
    "stock_code": "000001.SZ",
    "analysis_type": "comprehensive",
    "model": "deepseek-v3"
  }
}

// Python Backend → VS Code Extension (Response)
{
  "jsonrpc": "2.0",
  "id": "req_001",
  "result": {
    "analysis_id": 123,
    "conclusion": "...",
    "confidence": 0.85,
    "tokens_used": 2500
  }
}

// Python Backend → VS Code Extension (Push Notification)
{
  "jsonrpc": "2.0",
  "method": "event.signal_generated",
  "params": {
    "strategy_name": "双均线策略",
    "stock_code": "000001.SZ",
    "direction": "buy",
    "strength": 75
  }
}
```

### 8.3 启动/生命周期管理

```
VS Code Extension 激活
  │
  ├─► 检查 Python 环境 (python3.12+)
  ├─► 检查依赖是否安装 (poetry install)
  ├─► 启动 Python Backend 子进程
  │     └─► python -m src.main --mode ipc --socket {path}
  ├─► 建立 IPC 连接
  │     ├─► Unix Socket (Linux/Mac)
  │     └─► Named Pipe (Windows)
  ├─► 握手协议
  │     ├─► Extension → Backend: {method: "system.ping"}
  │     └─► Backend → Extension: {result: {version: "1.0.0", status: "ready"}}
  ├─► 开始正常工作
  │
  └─► Extension 停用
        ├─► 发送 {method: "system.shutdown"}
        ├─► 等待 Backend 优雅退出
        └─► 必要时强制 kill 子进程
```

---

## 9. 配置管理

### 9.1 配置层次

```
优先级 (高→低):
  1. 环境变量 (.env / 系统环境变量)
  2. config/settings.py (默认值)
  3. 代码内硬编码常量 (仅用于不可变常量)
```

### 9.2 配置文件结构

#### `.env`（不提交Git，密钥管理）

```env
# ===== 运行环境 =====
APP_ENV=development          # development | staging | production
APP_DEBUG=true
APP_SECRET_KEY=your-secret-key-here

# ===== 数据库 =====
DATABASE_URL=sqlite+aiosqlite:///./data/sqlite/quant.db
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/quant  (后期)

# ===== DeepSeek API =====
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# ===== 备用AI (OpenAI兼容) =====
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1

# ===== 数据源 =====
TUSHARE_TOKEN=your-tushare-token

# ===== Redis (缓存) =====
REDIS_URL=redis://localhost:6379/0

# ===== 通知 =====
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

#### `config/settings.py`（pydantic-settings）

```python
"""
全局配置定义
使用 pydantic-settings 实现类型安全的配置管理
所有配置项有类型注解 + 默认值 + 描述
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal


class Settings(BaseSettings):
    """应用全局配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ---- 运行环境 ----
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "change-me-in-production"
    APP_NAME: str = "QuantAI"
    APP_VERSION: str = "0.1.0"

    # ---- 数据库 ----
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite/quant.db"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_ECHO: bool = False  # SQL日志（仅开发环境）

    # ---- DeepSeek ----
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_MAX_TOKENS: int = 4096
    DEEPSEEK_TEMPERATURE: float = 0.3

    # ---- OpenAI 兼容接口 ----
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # ---- 数据源 ----
    TUSHARE_TOKEN: Optional[str] = None
    DEFAULT_DATA_SOURCE: str = "akshare"  # akshare | tushare | eastmoney
    DATA_SYNC_INTERVAL_MINUTES: int = 5  # 数据同步间隔

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_DEFAULT_TTL: int = 3600

    # ---- 交易 ----
    DEFAULT_BROKER: str = "simnow"
    MAX_POSITION_PCT: float = 0.2  # 单票最大仓位 20%
    MAX_INDUSTRY_PCT: float = 0.4  # 单行业最大仓位 40%
    DEFAULT_STOP_LOSS_PCT: float = -0.08  # 默认止损线 -8%

    # ---- API 服务 ----
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8888
    API_CORS_ORIGINS: list[str] = ["*"]

    # ---- 日志 ----
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "json"  # json | text
    LOG_FILE: str = "data/logs/app.log"
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "30 days"

    # ---- IPC (VS Code插件通信) ----
    IPC_SOCKET_PATH: str = "/tmp/quantai.sock"  # Linux/Mac
    # IPC_SOCKET_PATH: str = r"\\.\pipe\quantai"  # Windows

    # ---- 通知 ----
    NOTIFICATION_ENABLED: bool = True
    EMAIL_SMTP_HOST: Optional[str] = None
    EMAIL_SMTP_PORT: int = 587
    EMAIL_USERNAME: Optional[str] = None
    EMAIL_PASSWORD: Optional[str] = None
    WECHAT_WEBHOOK_URL: Optional[str] = None


# 全局单例
settings = Settings()
```

#### `config/ai_models.py`

```python
"""
AI模型配置
定义可用模型列表及其参数
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AIModelConfig:
    """单个AI模型配置"""
    name: str                      # 模型标识
    provider: str                  # 提供商：deepseek/openai/anthropic
    model_id: str                  # API model ID
    base_url: str                  # API地址
    api_key_env: str               # 环境变量名（指向API Key）
    max_tokens: int = 4096
    temperature: float = 0.3
    supports_streaming: bool = True
    cost_per_1k_tokens: float = 0  # 成本估算（美元）


# 已注册模型列表
AVAILABLE_MODELS: dict[str, AIModelConfig] = {
    "deepseek-v3": AIModelConfig(
        name="deepseek-v3",
        provider="deepseek",
        model_id="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        max_tokens=4096,
        temperature=0.3,
        cost_per_1k_tokens=0.001,
    ),
    "deepseek-r1": AIModelConfig(
        name="deepseek-r1",
        provider="deepseek",
        model_id="deepseek-reasoner",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        max_tokens=8192,
        temperature=0.1,
        cost_per_1k_tokens=0.004,
    ),
    "gpt-4o": AIModelConfig(
        name="gpt-4o",
        provider="openai",
        model_id="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        max_tokens=4096,
        temperature=0.3,
        cost_per_1k_tokens=0.01,
    ),
}
```

### 9.3 环境切换

```bash
# 开发环境
export APP_ENV=development

# 测试环境
export APP_ENV=staging

# 生产环境
export APP_ENV=production
```

---

## 10. 日志管理

### 10.1 日志架构

```
┌─────────────────────────────────────────┐
│            Logging Architecture          │
│                                          │
│  ┌──────────┐  ┌──────────┐             │
│  │ loguru   │  │ structlog│ (可选)       │
│  │ (默认)    │  │          │             │
│  └────┬─────┘  └────┬─────┘             │
│       │             │                    │
│       └──────┬──────┘                    │
│              │                           │
│     ┌────────┴────────┐                  │
│     │  LogManager      │                  │
│     │  (统一接口)       │                  │
│     └────────┬────────┘                  │
│              │                           │
│   ┌──────────┼──────────┐                │
│   │          │          │                │
│   ▼          ▼          ▼                │
│ ┌────┐  ┌────┐    ┌────────┐            │
│ │控制台│  │文件│    │数据库   │            │
│ │输出 │  │轮转│    │持久化   │            │
│ └────┘  └────┘    └────────┘            │
│  彩色     JSON      结构化               │
│  开发用   生产用    审计追踪               │
└─────────────────────────────────────────┘
```

### 10.2 日志规范

```python
# 日志级别使用规范
# DEBUG   - 开发调试信息（变量值、中间结果）
# INFO    - 关键业务节点（数据同步、信号生成、订单状态变更）
# WARNING - 潜在问题（数据缺失、超时重试、接近阈值）
# ERROR   - 错误但系统可继续（API调用失败、数据解析异常）
# CRITICAL - 系统级故障（数据库连接丢失、内存溢出）

# 结构化日志格式（JSON，生产环境）
{
  "timestamp": "2026-07-05T12:00:00.000Z",
  "level": "INFO",
  "module": "trading_engine",
  "event": "order_submitted",
  "order_id": 12345,
  "stock_code": "000001.SZ",
  "direction": "buy",
  "quantity": 1000,
  "request_id": "req_abc123"
}
```

### 10.3 日志模块 (`src/shared/logging_config.py`)

```python
"""
日志配置模块
基于 loguru，支持控制台彩色输出 + 文件JSON轮转
"""
import sys
from loguru import logger
from config.settings import settings


def setup_logging():
    """初始化日志系统"""
    # 移除默认handler
    logger.remove()

    # 控制台输出（开发环境：彩色文本）
    if settings.APP_ENV == "development":
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                   "<level>{message}</level>",
            level="DEBUG",
            colorize=True,
        )

    # 文件输出（生产环境：JSON格式，自动轮转）
    logger.add(
        settings.LOG_FILE,
        format="{time} | {level} | {name}:{function}:{line} | {message}",
        level=settings.LOG_LEVEL,
        rotation=settings.LOG_ROTATION,    # 按大小轮转
        retention=settings.LOG_RETENTION,  # 保留天数
        compression="zip",                 # 压缩旧日志
        serialize=settings.LOG_FORMAT == "json",
        enqueue=True,                       # 多进程安全
    )

    # 数据库日志（ERROR及以上自动入库）
    logger.add(
        DatabaseLogSink(),                  # 自定义Sink
        level="ERROR",
        serialize=True,
    )

    return logger
```

---

## 11. 缓存方案

### 11.1 多级缓存架构

```
┌─────────────────────────────────────────────────────┐
│                  Multi-Level Cache                    │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ L1: 内存缓存 (Process Memory)                    │ │
│  │ · 实现: lru_cache / cachetools.TTLCache         │ │
│  │ · 容量: ~1000 entries                           │ │
│  │ · TTL: 60秒                                     │ │
│  │ · 用途: 热点数据（最新K线、实时行情）             │ │
│  │ · 命中延迟: <1ms                                 │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │ MISS                        │
│  ┌──────────────────────┴──────────────────────────┐ │
│  │ L2: Redis缓存 (Shared Memory)                    │ │
│  │ · 实现: redis / aioredis                        │ │
│  │ · 容量: 由内存决定                                │ │
│  │ · TTL: 1小时 ~ 24小时                            │ │
│  │ · 用途: K线数据、AI分析结果、计算指标             │ │
│  │ · 命中延迟: ~1ms (本地) / ~10ms (远程)           │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │ MISS                        │
│  ┌──────────────────────┴──────────────────────────┐ │
│  │ L3: 磁盘缓存 (Disk Cache)                        │ │
│  │ · 实现: diskcache / SQLite缓存表                 │ │
│  │ · 容量: 由磁盘决定                                │ │
│  │ · TTL: 永久（手动清理）                           │ │
│  │ · 用途: 历史K线、回测结果、大型数据集             │ │
│  │ · 命中延迟: ~10ms                                 │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │ MISS                        │
│  ┌──────────────────────┴──────────────────────────┐ │
│  │ L4: 数据库 (SQLite / PostgreSQL)                 │ │
│  │ · 持久化存储                                      │ │
│  │ · 命中延迟: ~50ms                                 │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 11.2 缓存策略

| 数据类型 | L1 (内存) | L2 (Redis) | L3 (磁盘) | 失效策略 |
|---------|----------|-----------|----------|---------|
| 实时行情 | ✅ 30s | ✅ 60s | ❌ | TTL自动过期 |
| 日K线（当日） | ✅ 60s | ✅ 5min | ✅ 1天 | TTL + 收盘后主动失效 |
| 日K线（历史） | ❌ | ✅ 24h | ✅ 永久 | 手动清理 |
| 分钟K线 | ❌ | ✅ 1h | ✅ 永久 | 定时刷新当天数据 |
| 股票列表 | ✅ 5min | ✅ 1h | ✅ 1天 | 定时更新 |
| AI分析结果 | ❌ | ✅ 1h | ✅ 永久 | 相同输入复用 |
| 技术指标计算 | ✅ 5min | ✅ 1h | ❌ | TTL过期 |
| 回测结果 | ❌ | ✅ 24h | ✅ 永久 | 手动删除 |

### 11.3 缓存键命名规范

```
# 格式：{domain}:{entity}:{identifier}:{params}
kline:000001.SZ:1d:2026-01-01:2026-07-01
realtime:000001.SZ
stock_list:SH:active
ai_analysis:comprehensive:000001.SZ:2026-07-05
indicator:macd:000001.SZ:1d:2026-07-05
backtest:result:12345
signal:双均线策略:2026-07-05
```

---

## 12. 未来扩展方案

### 12.1 扩展点总览

```
┌────────────────────────────────────────────────────────────┐
│                    扩展点架构图                              │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  扩展点1: 数据源                                       │  │
│  │  实现 DataSourcePort → 注册到 DataSourceFactory       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐  │  │
│  │  │AKShare │ │Tushare │ │EastMoney│ │  Wind/Bloom  │  │  │
│  │  │(已有)  │ │(已有)  │ │(已有)  │ │  berg(未来)  │  │  │
│  │  └────────┘ └────────┘ └────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  扩展点2: AI模型                                       │  │
│  │  实现 AIPort → 注册到 AIFactory                       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐  │  │
│  │  │DeepSeek│ │OpenAI  │ │Claude  │ │  本地模型     │  │  │
│  │  │(已有)  │ │(已有)  │ │(未来)  │ │  (未来)      │  │  │
│  │  └────────┘ └────────┘ └────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  扩展点3: 券商接口                                     │  │
│  │  实现 BrokerPort → 注册到 BrokerFactory               │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐  │  │
│  │  │SimNow  │ │XTP     │ │CTP     │ │  海外券商     │  │  │
│  │  │(已有)  │ │(未来)  │ │(未来)  │ │  (未来)      │  │  │
│  │  └────────┘ └────────┘ └────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  扩展点4: 通知渠道                                     │  │
│  │  实现 NotificationPort → 注册到 NotificationFactory   │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐  │  │
│  │  │Email   │ │WeChat  │ │钉钉    │ │  Telegram    │  │  │
│  │  │(已有)  │ │(已有)  │ │(未来)  │ │  (未来)      │  │  │
│  │  └────────┘ └────────┘ └────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  扩展点5: 策略框架                                     │  │
│  │  继承 BaseStrategy → 注册到 StrategyRegistry          │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐  │  │
│  │  │双均线  │ │布林带  │ │动量    │ │  AI驱动策略   │  │  │
│  │  │(内置)  │ │(内置)  │ │(内置)  │ │  (未来)      │  │  │
│  │  └────────┘ └────────┘ └────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  扩展点6: 前端界面                                     │  │
│  │  ┌────────────┐ ┌────────────┐ ┌──────────────────┐ │  │
│  │  │ VS Code插件│ │ Web (React)│ │  Mobile App      │ │  │
│  │  │ (第一阶段) │ │ (第二阶段) │ │  (未来)          │ │  │
│  │  └────────────┘ └────────────┘ └──────────────────┘ │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 12.2 新增数据源示例

```python
# 新增一个数据源只需3步
# 1. 实现端口接口
class WindDataAdapter(BaseDataSourceAdapter):
    def __init__(self, config: WindConfig):
        self.client = WindClient(config.api_key)

    async def get_kline(self, stock_code, period, start, end):
        # Wind API调用逻辑
        raw = await self.client.get_kline(stock_code, period, start, end)
        return self._normalize(raw)

# 2. 注册到工厂
DataSourceFactory.register("wind", WindDataAdapter)

# 3. 修改配置
# config/data_sources.py
AVAILABLE_DATA_SOURCES = {
    ...
    "wind": WindConfig(endpoint="...", api_key_env="WIND_API_KEY"),
}
```

### 12.3 数据库迁移路径

```
Phase 1: SQLite (当前)
  ├── 单文件，零配置
  ├── 适合开发和小规模回测
  └── 限制：并发写入差，无高级类型（TIMESTAMP WITH TZ等）

Phase 2: PostgreSQL (数据量增长后)
  ├── 通过 Alembic 迁移
  ├── SQLAlchemy ORM 屏蔽差异（仅需改 DATABASE_URL）
  ├── 高级特性：TimescaleDB时序扩展、全文搜索、JSONB
  └── 读写分离、连接池

迁移步骤:
  1. 安装 psycopg2 + asyncpg
  2. 修改 .env DATABASE_URL
  3. alembic upgrade head (自动建表)
  4. 数据迁移脚本 (SQLite → PostgreSQL)
  5. 双写验证期
  6. 切换完毕
```

### 12.4 性能扩展路径

| 阶段 | 瓶颈 | 方案 |
|------|------|------|
| 单机 | CPU/内存 | 异步IO、多进程回测、缓存 |
| 数据量大 | 数据库 | PostgreSQL + TimescaleDB、分区表 |
| 计算密集 | 回测/扫描 | Celery分布式任务、Dask并行计算 |
| 实时性 | 行情延迟 | WebSocket接入、流式处理 |
| 高可用 | 单点故障 | Redis Sentinel、数据库主从、服务多副本 |

---

## 13. 接口设计

### 13.1 REST API 总览

```
Base URL: http://{host}:{port}/api/v1/

┌──────────────────────────────────────────────────────────────────┐
│                         API Endpoints                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Market Data (行情数据)                                            │
│  ├── GET    /market/stocks                股票列表查询              │
│  ├── GET    /market/stocks/{code}         股票详情                  │
│  ├── GET    /market/kline/{code}          K线数据查询               │
│  ├── GET    /market/realtime/{code}       实时行情                  │
│  ├── GET    /market/indices               指数行情                  │
│  └── POST   /market/sync                  触发数据同步              │
│                                                                   │
│  Strategies (策略)                                                  │
│  ├── GET    /strategies                   策略列表                  │
│  ├── POST   /strategies                   创建策略                  │
│  ├── GET    /strategies/{id}              策略详情                  │
│  ├── PUT    /strategies/{id}              更新策略                  │
│  ├── DELETE /strategies/{id}              删除策略                  │
│  ├── POST   /strategies/{id}/activate     激活策略                  │
│  └── POST   /strategies/{id}/pause        暂停策略                  │
│                                                                   │
│  Trading (交易)                                                      │
│  ├── POST   /trading/orders               提交订单                  │
│  ├── GET    /trading/orders               订单列表                  │
│  ├── GET    /trading/orders/{id}          订单详情                  │
│  ├── DELETE /trading/orders/{id}          撤单                      │
│  └── GET    /trading/positions            持仓查询                  │
│                                                                   │
│  Backtest (回测)                                                     │
│  ├── POST   /backtest/run                 启动回测                  │
│  ├── GET    /backtest/tasks               回测任务列表               │
│  ├── GET    /backtest/tasks/{id}          回测结果                  │
│  ├── GET    /backtest/tasks/{id}/trades   回测交易明细               │
│  └── GET    /backtest/tasks/{id}/chart    回测图表数据               │
│                                                                   │
│  AI Analysis (AI分析)                                               │
│  ├── POST   /ai/analyze                   发起AI分析                │
│  ├── GET    /ai/reports                   分析报告列表               │
│  ├── GET    /ai/reports/{id}              报告详情                  │
│  ├── POST   /ai/chat                      对话式分析                │
│  └── GET    /ai/models                    可用模型列表               │
│                                                                   │
│  Portfolio (投资组合)                                                │
│  ├── GET    /portfolio/summary            组合概览                  │
│  ├── GET    /portfolio/positions          持仓明细                  │
│  ├── GET    /portfolio/performance        绩效分析                  │
│  ├── POST   /portfolio/optimize           组合优化                  │
│  └── POST   /portfolio/rebalance          再平衡建议                │
│                                                                   │
│  Risk (风控)                                                         │
│  ├── GET    /risk/rules                   风控规则列表               │
│  ├── POST   /risk/rules                   创建规则                  │
│  ├── PUT    /risk/rules/{id}              更新规则                  │
│  ├── DELETE /risk/rules/{id}              删除规则                  │
│  └── GET    /risk/alerts                  风险警报历史               │
│                                                                   │
│  System (系统)                                                       │
│  ├── GET    /system/health                健康检查                  │
│  ├── GET    /system/status                系统状态                  │
│  └── GET    /system/config                当前配置（脱敏）            │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### 13.2 端口接口定义（核心）

```python
# ===== src/domain/ports/data_source_port.py =====
from abc import ABC, abstractmethod
from typing import Optional
from datetime import date, datetime


class DataSourcePort(ABC):
    """数据源端口接口 —— 所有数据源适配器必须实现此接口"""

    @abstractmethod
    async def get_stock_list(
        self, market: Optional[str] = None
    ) -> list[dict]:
        """获取股票列表
        Args:
            market: 市场过滤 (SH/SZ/BJ)，None=全市场
        Returns:
            [{"code": "000001.SZ", "name": "平安银行", ...}, ...]
        """
        ...

    @abstractmethod
    async def get_kline(
        self,
        stock_code: str,
        period: str,        # "1m"/"5m"/"15m"/"30m"/"60m"/"1d"/"1w"/"1M"
        start_date: date,
        end_date: date,
        adjust: str = "qfq", # "qfq"(前复权)/"hfq"(后复权)/"none"
    ) -> list[dict]:
        """获取K线数据
        Returns:
            [{"timestamp": ..., "open": ..., "high": ..., "low": ...,
              "close": ..., "volume": ..., "amount": ...}, ...]
        """
        ...

    @abstractmethod
    async def get_realtime_quote(
        self, stock_codes: list[str]
    ) -> list[dict]:
        """获取实时行情"""
        ...

    @abstractmethod
    async def get_financials(
        self, stock_code: str
    ) -> dict:
        """获取财务数据"""
        ...

    @abstractmethod
    async def get_health(self) -> bool:
        """检查数据源是否可用"""
        ...


# ===== src/domain/ports/ai_provider_port.py =====
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class AIPort(ABC):
    """AI提供商端口接口 —— 所有AI适配器必须实现此接口"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """发送对话请求
        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        Returns:
            {"content": "...", "tokens_used": 1234, "model": "...", "finish_reason": "stop"}
        """
        ...

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """流式对话请求 —— 逐Token返回"""
        ...

    @abstractmethod
    async def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """估算Token数量"""
        ...


# ===== src/domain/ports/broker_port.py =====
class BrokerPort(ABC):
    """券商端口接口 —— 所有券商适配器必须实现此接口"""

    @abstractmethod
    async def submit_order(self, order: dict) -> dict:
        """提交订单 → 返回订单确认"""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        ...

    @abstractmethod
    async def query_order(self, order_id: str) -> dict:
        """查询订单状态"""
        ...

    @abstractmethod
    async def query_positions(self) -> list[dict]:
        """查询持仓"""
        ...

    @abstractmethod
    async def query_account(self) -> dict:
        """查询账户资金"""
        ...


# ===== src/domain/ports/repository_port.py =====
from typing import Generic, TypeVar, Optional

T = TypeVar("T")

class RepositoryPort(Generic[T], ABC):
    """泛型仓储端口接口"""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """保存（新增或更新）"""
        ...

    @abstractmethod
    async def find_by_id(self, entity_id: int) -> Optional[T]:
        """按主键查询"""
        ...

    @abstractmethod
    async def find_all(
        self,
        filters: Optional[dict] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[T]:
        """分页查询"""
        ...

    @abstractmethod
    async def delete(self, entity_id: int) -> bool:
        """软删除"""
        ...

    @abstractmethod
    async def count(self, filters: Optional[dict] = None) -> int:
        """统计数量"""
        ...
```

### 13.3 WebSocket接口

```
端点: ws://{host}:{port}/ws

频道订阅:
  → {"action": "subscribe", "channel": "realtime:000001.SZ"}
  → {"action": "subscribe", "channel": "signal"}
  → {"action": "subscribe", "channel": "order_update"}
  → {"action": "subscribe", "channel": "risk_alert"}

推送消息:
  ← {"channel": "realtime:000001.SZ", "data": {...}}
  ← {"channel": "signal", "data": {"strategy": "...", "stock": "...", "direction": "buy"}}
  ← {"channel": "order_update", "data": {"order_id": 123, "status": "filled"}}
```

---

## 14. 模块依赖图

### 14.1 编译时依赖（Import依赖）

```
                    ┌──────────┐
                    │  shared  │  (工具、异常、常量、类型)
                    └────┬─────┘
                         │ (被所有层安全依赖)
        ┌────────────────┼────────────────────┐
        │                │                    │
        ▼                ▼                    ▼
   ┌─────────┐    ┌─────────────┐    ┌──────────────┐
   │ domain  │    │application  │    │infrastructure│
   │ (核心)  │◄───│  (用例)     │    │  (实现)      │
   └────┬────┘    └──────┬──────┘    └──────┬───────┘
        │                │                  │
        │         ┌──────┴──────┐           │
        │         │             │           │
        │         ▼             ▼           │
        │   ┌──────────┐ ┌──────────┐      │
        │   │   dto    │ │  events  │      │
        │   │(传输对象)│ │(事件定义)│      │
        │   └──────────┘ └──────────┘      │
        │                                   │
        └───────────────────────────────────┘
                     │
                     ▼
              ┌─────────────┐
              │     api     │ (FastAPI路由+中间件)
              └──────┬──────┘
                     │
                     ▼
              ┌─────────────┐
              │   config    │ (配置，全局可import)
              └─────────────┘
```

### 14.2 运行时依赖（依赖注入方向）

```
┌─────────────────────────────────────────────────────────────┐
│                    依赖注入容器 (api/dependencies.py)         │
│                                                              │
│  def get_data_source() -> DataSourcePort:                   │
│      return DataSourceFactory.create(settings.DATA_SOURCE)   │
│                                                              │
│  def get_ai_provider() -> AIPort:                           │
│      return AIFactory.create(settings.AI_PROVIDER)           │
│                                                              │
│  def get_broker() -> BrokerPort:                            │
│      return BrokerFactory.create(settings.BROKER)            │
│                                                              │
│  def get_stock_repo() -> RepositoryPort[Stock]:              │
│      return StockSQLiteRepository(session)                   │
│                                                              │
│  def get_cache() -> CachePort:                               │
│      return MultiLevelCache(redis, disk, memory)              │
│                                                              │
│  使用方式 (FastAPI Depends):                                 │
│  @router.get("/market/stocks")                               │
│  async def get_stocks(                                       │
│      data_source: DataSourcePort = Depends(get_data_source), │
│      cache: CachePort = Depends(get_cache),                  │
│  ):                                                          │
│      ...                                                     │
└─────────────────────────────────────────────────────────────┘
```

### 14.3 模块间通信方式

| 通信方式 | 使用场景 | 实现 |
|---------|---------|------|
| 直接方法调用 | 层内通信、用例编排 | Python函数调用 |
| 依赖注入 | 跨层接口调用 | FastAPI Depends / 手动注入 |
| 领域事件 | 解耦的跨模块通知 | EventBus (观察者模式) |
| 消息队列 | 异步任务、事件驱动 | Redis Pub/Sub / Celery |
| WebSocket | 实时推送到前端 | FastAPI WebSocket |
| IPC (JSON-RPC) | VS Code插件 ↔ Python后端 | Unix Socket / Named Pipe |

---

## 15. 整体开发路线图（Roadmap）

### Phase 0：项目基础设施（1-2周）

```
Week 1-2: 项目骨架搭建
├── □ 初始化 Poetry 项目（pyproject.toml）
├── □ 配置 ruff + mypy + black + pre-commit
├── □ 创建完整目录结构
├── □ 配置 .env + pydantic-settings
├── □ 配置 loguru 日志系统
├── □ 配置 SQLAlchemy 异步引擎 + ORM基类
├── □ 编写数据库初始化脚本
├── □ 配置 pytest + fixtures
├── □ CI/CD: GitHub Actions (lint + test)
└── □ 编写 README + 开发指南

验收标准:
  · poetry install 一键安装所有依赖
  · pre-commit 通过所有检查
  · 20+ 单元测试全部通过
  · 日志正常输出到控制台和文件
```

### Phase 1：核心数据层（2-3周）

```
Week 3-5: 数据基础设施
├── □ 实现 Stock / MarketData 领域模型 + 单元测试
├── □ 实现 ORM 模型 (stocks, market_data) + 建表
├── □ 实现 DataSourcePort 端口接口
├── □ 实现 AKShare 适配器（首批数据源）
├── □ 实现 Tushare 适配器
├── □ 实现 DataSourceFactory
├── □ 实现 SQLite Repository（stocks, market_data）
├── □ 实现数据清洗/验证/标准化管道
├── □ 实现 APScheduler 定时数据同步
├── □ 实现 Redis + diskcache 多级缓存
├── □ 编写数据同步脚本 + 填充种子数据

验收标准:
  · 可同步全市场A股列表（5000+只）
  · 可同步任意股票历史K线
  · 定时任务自动增量更新
  · 缓存命中率 > 80%
```

### Phase 2：策略与回测（3-4周）

```
Week 6-9: 策略框架 + 回测引擎
├── □ 实现 Strategy / Signal 领域模型
├── □ 实现 BaseStrategy 策略基类
├── □ 实现内置策略：双均线、布林带、动量
├── □ 实现 SignalGenerator 领域服务
├── □ 实现 BacktestEngine 回测引擎
├── □ 实现 PerformanceCalculator（收益率/夏普/最大回撤等）
├── □ 实现回测用例 + API路由
├── □ 实现回测结果可视化数据接口
├── □ 编写回测集成测试（含已知结果验证）
├── □ 实现策略参数网格搜索优化

验收标准:
  · 3个内置策略可正常运行
  · 回测结果与聚宽/米筐误差 < 1%
  · 1年日线回测耗时 < 5秒（100只股票）
```

### Phase 3：AI分析引擎（2-3周）

```
Week 10-12: AI分析能力
├── □ 实现 AIPort 端口接口
├── □ 实现 DeepSeek 适配器（默认）
├── □ 实现 OpenAI 兼容适配器（备用）
├── □ 实现 AIFactory
├── □ 实现 PromptBuilder（Jinja2模板）
├── □ 设计Prompt模板库（市场综述/个股分析/策略建议/风险预警）
├── □ 实现 AIAnalysisEngine 领域服务
├── □ 实现 ResultParser（JSON提取 + Schema校验）
├── □ 实现 AI分析用例 + API路由
├── □ 实现 AI调用缓存（相同输入复用）
├── □ 实现 Token用量统计 + 成本估算

验收标准:
  · 可调用DeepSeek完成4种分析类型
  · Prompt模板可热更新
  · API异常自动重试3次
  · Token消耗有完整记录
```

### Phase 4：交易与风控（2-3周）

```
Week 13-15: 交易执行 + 风控
├── □ 实现 Order / Position / Account / Portfolio 领域模型
├── □ 实现 BrokerPort 端口接口
├── □ 实现 SimNow 模拟交易适配器
├── □ 实现 TradingEngine 领域服务
├── □ 实现 RiskManager 领域服务（含多种风控规则）
├── □ 实现 PortfolioOptimizer 领域服务
├── □ 实现交易用例 + API路由
├── □ 实现风控用例 + API路由
├── □ 实现订单状态机
├── □ 实现交易事件通知

验收标准:
  · 模拟交易完整链路（下单→风控→成交→持仓更新）
  · 风控规则可拦截超限订单
  · 订单状态流转正确
```

### Phase 5：API服务 + IPC通信（2周）

```
Week 16-17: 服务化
├── □ 实现 FastAPI 应用工厂
├── □ 实现 全部REST API路由（8个模块）
├── □ 实现 WebSocket 实时推送
├── □ 实现 认证中间件（API Key + JWT）
├── □ 实现 限流中间件
├── □ 实现 请求日志中间件
├── □ 实现 IPC Server（JSON-RPC over Socket）
├── □ 实现 VS Code Extension 基础框架（TypeScript）
├── □ 实现 插件启动/连接/握手流程
├── □ 编写 API 集成测试

验收标准:
  · Swagger文档可交互
  · WebSocket实时推送延迟 < 500ms
  · IPC通信正常工作
  · 集成测试覆盖所有端点
```

### Phase 6：VS Code插件（2-3周）

```
Week 18-20: 插件开发
├── □ 实现 Sidebar 股票列表（TreeView）
├── □ 实现 K线图表 Webview（ECharts集成）
├── □ 实现 AI分析面板（命令 + 结果展示）
├── □ 实现 策略管理面板
├── □ 实现 回测结果展示
├── □ 实现 实时行情 Status Bar
├── □ 实现 交易信号通知
├── □ 实现 一键下单命令
├── □ 插件打包发布 (.vsix)
└── □ 编写插件使用文档

验收标准:
  · 插件可在VS Code中正常运行
  · 不需要离开编辑器即可完成完整分析流程
```

### Phase 7：测试与文档完善（1-2周）

```
Week 21-22: 质量保障
├── □ 单元测试覆盖率达到80%+
├── □ 端到端测试（全流程验证）
├── □ 性能测试（大数据量回测）
├── □ API文档完善（OpenAPI + 示例）
├── □ 用户手册编写
├── □ 部署文档（Docker + 裸机）
└── □ CHANGELOG + 版本发布 v1.0.0

验收标准:
  · 测试覆盖率 ≥ 80%
  · 文档完整可用
  · Docker一键部署
```

### Phase 8：Web版本（后期，待规划）

```
Week 23+: Web平台
├── □ React + TypeScript 前端框架搭建
├── □ 仪表盘 / 股票分析 / 策略管理 / 回测 / AI分析 页面
├── □ 图表可视化（TradingView/ECharts）
├── □ 移动端响应式适配
└── □ PWA支持
```

---

## 附录A：技术决策记录（ADR）

| ID | 决策 | 理由 | 替代方案 |
|----|------|------|---------|
| ADR-001 | 使用分层+六边形架构 | 长期维护、可扩展、可测试 | MVC（太简单）、微服务（过早） |
| ADR-002 | SQLAlchemy 2.0 异步ORM | 支持SQLite→PostgreSQL平滑迁移 | Django ORM（同步）、原生SQL（难迁移） |
| ADR-003 | loguru 替代标准logging | 开箱即用，JSON序列化，轮转 | structlog（更复杂）、标准logging（配置繁琐） |
| ADR-004 | pydantic-settings管理配置 | 类型安全、.env自动加载 | python-decouple（功能少）、ConfigParser（无类型） |
| ADR-005 | Poetry管理依赖 | 锁定文件、虚拟环境、构建发布 | pip+requirements.txt（无锁定）、pipenv（慢） |
| ADR-006 | DeepSeek作为默认AI模型 | 性价比高、中文能力强、API兼容OpenAI | 纯OpenAI（贵）、本地模型（维护成本高） |
| ADR-007 | VS Code插件作为第一阶段UI | 目标用户使用VS Code、TypeScript生态好 | Web先行（开发量大）、CLI（体验差） |

---

## 附录B：命名规范

### Python命名

| 元素 | 规范 | 示例 |
|------|------|------|
| 模块/文件名 | snake_case | `market_data_repo.py` |
| 类名 | PascalCase | `StockRepository` |
| 函数/方法 | snake_case | `get_kline_data()` |
| 变量 | snake_case | `stock_list` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT` |
| 私有成员 | _leading_underscore | `_validate_data()` |
| 抽象方法 | 装饰器 @abstractmethod | — |
| 端口接口 | `*Port` 后缀 | `DataSourcePort` |
| 适配器 | `*Adapter` 后缀 | `AKShareAdapter` |
| 用例 | `*UseCase` 后缀 | `BacktestUseCase` |
| 仓储 | `*Repository` 后缀 | `StockRepository` |

### 数据库命名

| 元素 | 规范 | 示例 |
|------|------|------|
| 表名 | snake_case 复数 | `market_data` |
| 主键 | `id` | `id INTEGER PRIMARY KEY` |
| 外键 | `{table}_id` | `stock_id` |
| 时间戳 | `{action}_at` | `created_at`, `updated_at` |
| 布尔值 | `is_{adjective}` | `is_enabled`, `is_read` |

---

> **文档结束**  
> 第一阶段架构设计完成。等待下一步命令。
