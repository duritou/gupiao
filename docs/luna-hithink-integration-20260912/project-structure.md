# HiThink 集成涉及目录与职责

```text
adaptive-investment-intelligence/
├── .env.example
│   └── 只声明空的 HiThink Key 和非敏感配置，禁止真实凭据
├── config/
│   └── settings.py
│       └── HiThink URL、超时、节流、重试和逐能力 rollout 开关
├── providers/
│   ├── tushare.yaml
│   │   └── 保持 Tushare 会员数据的历史/财务/资金流能力说明
│   └── hithink.yaml
│       └── HiThink 能力、时间语义、限制与认证 manifest
├── docs/
│   ├── 数据源.md
│   │   └── 面向运维的最终主备矩阵与数据口径
│   └── luna-hithink-integration-20260912/
│       ├── dev-plan.md
│       │   └── Luna 按依赖执行的任务、门禁与回滚步骤
│       ├── project-structure.md
│       │   └── 本轮允许涉及的文件和职责
│       ├── code-guideline.md
│       │   └── 字段、错误、时间、密钥、测试和发布规范
│       └── acceptance.md
│           └── Luna 执行时新增，记录逐项证据与最终状态
├── src/
│   ├── domain/models/market_data.py
│   │   └── 注册 hithink provider capability；初始不声明盘中实时报价
│   ├── infrastructure/market_data/
│   │   ├── hithink_provider.py
│   │   │   └── 新增：官方 REST API 客户端、字段归一化和运行统计
│   │   ├── source_manager.py
│   │   │   └── 日线/财务主备路由、缓存、provenance 与降级
│   │   ├── data_completion_service.py
│   │   │   └── Tushare 首选补齐、HiThink 补缺/校验和组件级状态
│   │   ├── remote_market_discovery.py
│   │   │   └── HiThink 特色数据首选、东方财富降级；不改评分公式
│   │   ├── provider_metrics.py
│   │   │   └── provider+capability 成功率、延迟、完整率与信任分
│   │   ├── provider_resilience.py
│   │   │   └── 共享节流、熔断、Retry-After 和半开恢复
│   │   └── registry.py
│   │       └── 数据源目录和展示元数据
│   └── infrastructure/storage/market_database.py
│       └── 必要时兼容扩展来源、修订、完整率和请求审计元数据
│   ├── api/routes/
│   │   ├── valuation_routes.py
│   │   │   └── HiThink 估值首选、Tushare/native 降级
│   │   ├── dragon_tiger_routes.py
│   │   │   └── HiThink 龙虎榜首选、Tushare/东方财富降级
│   │   ├── market_routes.py
│   │   │   └── 名称消歧和行情响应 provenance
│   │   └── system_routes.py
│   │       └── 暴露脱敏 provider 健康与 rollout 状态
│   └── ai_os/scheduler.py
│       └── 复用现有调度器运行有限 shadow canary
├── scripts/
│   ├── probe_hithink.py
│   │   └── 新增：交易时段稳定性与跨源一致性探测器
│   ├── create_runtime_manifest.py
│   │   └── 将新增关键文件纳入发布哈希
│   ├── adopt_runtime_contract.py
│   │   └── 发布前配置、schema、凭据来源和回滚校验
│   └── deploy_research_backend.ps1
│       └── 复用不可变发布与身份验收，不新增第二部署入口
├── tests/
│   ├── fixtures/hithink/
│   │   └── 合成、脱敏、最小 API 信封和字段夹具
│   ├── unit/infrastructure/
│   │   ├── test_hithink_provider.py
│   │   ├── test_hithink_source_routing.py
│   │   ├── test_hithink_financial_merge.py
│   │   ├── test_hithink_discovery.py
│   │   ├── test_provider_metrics.py
│   │   └── test_provider_resilience.py
│   ├── unit/api/
│   │   ├── test_hithink_valuation_routes.py
│   │   └── test_hithink_special_routes.py
│   ├── unit/scripts/
│   │   └── test_probe_hithink.py
│   └── integration/
│       └── test_hithink_tushare_consistency.py
└── test-reports/hithink-integration-20260912/
    ├── baseline/
    ├── unit/
    ├── integration/
    ├── canary/
    ├── consistency/
    └── rollback/
```

## 默认禁止触碰

- 选股公式、技术分、AI 分、65 分资格、Top N、买卖阈值和仓位规则。
- paper/live 交易账本内容与生产数据库原始文件。
- Deep/Codex 模型路由和提示词，除非仅增加来源说明且有独立测试。
- `.env`、用户级凭据、CLI keyring、运行日志和任何真实 API Key。
- HiThink 下载仓库 `.skill-build/`；它只作为研究材料，不应成为运行时依赖。
- VSIX 产物和前端页面，除非后端健康字段需要最小展示改动。

新增文件只有在现有职责无法容纳时才允许；不得借接入数据源重构整个 SourceManager、数据库或调度器。

