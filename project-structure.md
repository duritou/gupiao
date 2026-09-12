# 2026-09-06 Luna 两轮复核返工目录（待实施）

本轮仅增量修改下列职责涉及的必要代码；先确认现有实现再决定最小改动，目录列出不表示每个文件都必须改。不添加独立调度平台。历史目录及完成记录保留于下方，不代替本轮验收。

```text
adaptive-investment-intelligence/
├── dev-plan.md                         # 六项返工依赖、预算、隔离验收及Luna指令
├── project-structure.md                # 本轮文件边界与职责
├── code-guideline.md                   # 证据、任务、日期、请求和测试契约
├── scripts/
│   ├── audit_data_completion.py        # 按run_id核验固定集合和最终证据覆盖
│   └── backfill_research_data.py       # 显式目标的CLI适配，不拥有另一套恢复逻辑
├── src/
│   ├── ai_os/
│   │   ├── candidate_evidence_enricher.py # 历史/摘要合并与统一目标日挂接
│   │   ├── pipeline_runner.py         # 候选任务登记、输入截止与既有流程衔接
│   │   ├── pipeline_observability.py  # 最终挂接覆盖和缺口分类
│   │   ├── task_executor.py           # 有限后台工作切片及恢复调度
│   │   └── scheduler.py               # 复用现有触发/恢复生命周期
│   ├── api/app.py                     # 启动恢复与定时入口，不承载数据业务循环
│   ├── agents/codex_stock_analyzer.py  # 实际请求边界校验及摘要/完整请求hash区分
│   └── infrastructure/
│       ├── market_data/
│       │   ├── data_completion_service.py # 组件任务、提交后读回与更新判断
│       │   ├── research_flow.py        # 历史流方向与时效独立建模
│       │   ├── source_manager.py      # 来源适配、缓存和错误元数据透传
│       │   ├── tushare_provider.py    # 按表增量获取、披露修订核验及实际请求元数据
│       │   └── tushare_request_budget.py # 共享配额、在途去重与真实尝试记录
│       └── storage/market_database.py # checkpoint兼容扩展、原子认领及组件读写
├── tests/
│   ├── unit/ai_os/                    # 不覆盖历史、日期口径和既有规则回归
│   ├── unit/scripts/                  # 同日多run、跨日、未知run及持仓集合
│   ├── unit/infrastructure/           # 财报更新、预算、请求审计和恢复边界
│   ├── unit/api/                      # 启动/定时并发触发与恢复注册
│   ├── unit/agents/                   # 实际模型载荷、字段数值和hash口径
│   └── integration/                   # 临时DB重开、隔离进程恢复及无交易AI链路
└── test-reports/
    ├── quality-20260906-luna-two-round-review.md # 本轮需求及已复现问题，不覆盖
    └── luna-review-remediation-20260906/
        ├── baseline/                  # 固定run/代码集合/目标日/源码和数据基线
        ├── after/                     # 同口径逐只JSON/CSV及证据完整率
        ├── attempts/                  # 脱敏逐请求轨迹、重试/延期及错误读回
        ├── isolated-cold/             # 单独保存冷跑副本、配置与耗时
        ├── isolated-warm/             # 同集合暖跑、跳过与请求量对照
        ├── ai-input-validation/       # 模型提交字段校验、输入指纹及阶段结果
        ├── tests/                     # 本轮命令、失败复现、修复后回归输出
        └── acceptance.md              # 六项证据矩阵、限制、部署与回滚交接
```

仅在现有模块无法合理容纳必要逻辑时拆出小型帮助模块；须在交付中解释其对应缺陷，禁止顺手重构。数据库任何兼容扩展须在隔离副本先验证迁移和回滚，不在本轮采用生产schema。

---

# Adaptive Investment 交易执行分层改造目录

## 2026-09-06 生产补齐增补

验收状态：组件补采源码、隔离实跑、生产分批写入、管理员重启、新调度注册和新进程无交易AI复跑均已完成；仍有3只外部资金流数据 stale。详见 `test-reports/unit-20260906-production-evidence-gap.md`。

- `docs/luna-production-evidence-gap-plan-20260906.md`：本轮原因、组件补采、调度恢复及生产验收契约。
- `src/infrastructure/market_data/data_completion_service.py`：复用组件增量补采。
- `scripts/backfill_research_data.py`：隔离/生产显式目标、分批恢复。
- `scripts/audit_data_completion.py`：固定运行批次的逐组件前后对照。
- `src/ai_os/task_executor.py`：复用现有后台调度，恢复待补任务。
- `test-reports/`：逐只基线、失败详情、输入证据及生产验收产物。

## 2026-09-05 增量范围

- `src/ai_os/candidate_evidence_enricher.py`：失败报价来源及错误透传。
- `tests/unit/infrastructure/test_research_quote_budget.py`：研究报价主备预算与有限重试。

- `src/infrastructure/market_data/tushare_provider.py`：报告期完整读取。
- `src/infrastructure/market_data/remote_market_discovery.py`：发现层真实资金流主备。
- `src/infrastructure/market_data/source_manager.py`：有效缓存和候选复用。
- `src/agents/codex_stock_analyzer.py`：结构化提示证据、研究时间语义。
- `src/ai_os/pipeline_runner.py`：阶段计时，不改选股。
- `src/ai_os/execution_policy.py`：隔离评估模拟探索规则。
- `tests/unit/`、`tests/integration/`：本轮回归与隔离验收。
- `test-reports/`：逐项证据及未完成状态。

```text
adaptive-investment-intelligence/
├── dev-plan.md                                  # Luna 可直接执行的依赖化任务清单
├── project-structure.md                         # 本次改造涉及的完整目录及职责
├── code-guideline.md                            # 执行策略契约、编码约束和验收标准
├── src/
│   ├── config.py                                # paper probe 的仓位、期限、止损和总敞口配置
│   ├── ai_os/
│   │   ├── execution_policy.py                  # 新增：normal/probe/blocked 判定与 probe 生命周期纯函数
│   │   ├── cross_sectional_scoring.py           # 既有选股逻辑；只新增执行证据元数据，不改评分结果
│   │   ├── pipeline_runner.py                    # 将选择结果及执行证据传给模拟交易层
│   │   ├── trading_policy.py                     # normal、Deep Buy 与 probe 的退出规则
│   │   ├── trading_costs.py                      # 统一成交价格、滑点、佣金和税费
│   │   ├── pipeline_observability.py             # 执行模式、阻断原因及数据质量统计
│   │   ├── paper_ledger_rebuild.py               # 重建账本并恢复持仓执行身份
│   │   ├── strategy_version.py                   # 算法代码哈希及运行契约源文件清单
│   │   └── task_executor.py                      # 数据不足、连续弃权和关键失败告警
│   ├── infrastructure/
│   │   └── storage/
│   │       └── market_database.py                # schema 迁移、最终买卖执行、持仓/成交/拒单持久化
│   └── api/
│       └── routes/
│           ├── portfolio_routes.py               # 展示持仓 execution tier 与 probe 生命周期
│           ├── decision_routes.py                # 展示 pre-gate 意图、阻断原因和执行处置
│           └── trust_routes.py                   # 展示 normal/probe 结果及样本可用性
├── scripts/
│   └── adopt_runtime_contract.py                 # 非交易窗口采用新 schema 与代码契约
├── tests/
│   ├── unit/
│   │   ├── ai_os/
│   │   │   ├── test_execution_policy.py          # 执行判定矩阵与 probe 状态机单测
│   │   │   └── test_trading_policy.py            # normal/Deep Buy 不变及 probe 退出规则单测
│   │   └── infrastructure/
│   │       └── test_paper_execution_tiers.py     # 仓位、行业、持久化和拒单约束单测
│   └── integration/
│       ├── test_probe_trading_cycle.py            # probe 买入、转正、退出和账务闭环
│       └── test_algorithm_regression_gate.py       # 选股逻辑零变化回归门禁
└── test-reports/
    └── execution-tier-rollout.md                  # shadow、回归、上线和回滚验收记录
```

## 2026-09-06 部署一致性增补

- `src/infrastructure/runtime_identity.py`：运行清单、启动身份、源码漂移检测。
- `scripts/create_runtime_manifest.py`：按关键文件生成/验证清单。
- `scripts/deploy_research_backend.ps1`：唯一部署事务入口、维护门禁、版本验收和失败记录。
- `runtime/`：本地发布清单、活动清单、部署锁和维护状态；不存数据库、凭据或日志。
- `test-reports/luna-deployment-consistency-20260906/`：专项准备和验收证据。

### 不可变源码发布

- `runtime/releases/<release-id>/adaptive-investment-intelligence` 是生产代码发布目录；生产启动必须从 active manifest 的 `source_root` 启动，不得在完成切换后直接从工作树运行。
- 发布目录不携带 `.venv`、生产数据库或运行时缓存；启动器显式保留原工作树的市场数据库、Tushare预算库和共享配置路径，避免切换到空数据库。
- `runtime/active-manifest.json` 只由部署事务原子替换；发布目录和清单不应被开发进程直接修改。
