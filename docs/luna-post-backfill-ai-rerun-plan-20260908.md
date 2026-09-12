# Luna：补采完成后自动触发 AI 持久化重跑实施与验收方案（2026-09-08）

## 1. 目标

修复“AI 先运行、补采后完成，但最新 AI 结果仍消费旧证据”的时序断点。

补采进程结束后，系统应基于同一交易日、同一候选集合重新计算覆盖率：

- 达到现有数据质量门槛时，只触发一次 AI 持久化重跑；
- 未达到门槛时不触发 AI，持久化逐只缺失原因和下一步状态；
- 分区状态为 `partial` 但整体覆盖率已达门槛时，允许重跑，由现有逐股证据闸门处理少量缺失股票；
- 不改变选股评分、买入、卖出、仓位、止损或学习规则；
- 自动重跑只生成和持久化研究决策，不调用开盘/午盘交易执行入口。

## 2. 已核验基线

2026-09-08 的实际时序：

- 13:30 AI 扫描成功结束，但消费时资金流覆盖为 `80/300（26.67%）`、基本面覆盖为 `115/300（38.33%）`，最终为 `data_insufficient_abstention`；
- 后续补采持续到 20:42:36，多数候选分区已达到 `295/300` 或 `297/300`；
- 当日 14 个补采分区均标记为 `partial`，没有 `completed`；
- 补采结束后没有产生新的 AI run，因此页面继续展示 13:30 的旧证据结果；
- 当前 `partial` 是严格全量完成状态，不等于整个分区补采失败。

## 3. 不可变约束

1. 保留当前工作区已有修改，不覆盖或回退无关代码。
2. 遵守根目录 `dev-plan.md`、`project-structure.md`、`code-guideline.md`。
3. 不修改选股与交易规则，不放宽资金流、财报、行情或 Deep 分析闸门。
4. 不因“需要交易学习”而制造信号、伪造证据或强制买卖。
5. 不在 API 事件循环中执行长时间补采或完整 AI 流程；继续使用受控外部 worker。
6. 不使用生产 `--reload`，不在测试中制造生产故障。
7. Tushare 限频使用现有速率控制和有限退避；不得无限等待或无限重试。
8. 自动 AI 重跑与交易执行解耦。验收过程中不得触发模拟或真实成交。

## 4. 目标闭环

```text
定时补采启动
  -> 外部补采 worker 执行/恢复 checkpoint
  -> worker 结束并写入结构化结果
  -> 重新读取同日、同候选集合的数据库覆盖率
  -> 数据质量判定
       ├─ 达标：生成 data_revision -> 幂等检查 -> AI 持久化重跑一次
       │                                      -> 核验 AI 实际消费新证据
       └─ 未达标：写入逐只缺失原因 -> 等待下一次有限恢复任务
```

## 5. 实施任务

### P0-A：统一补采完成结果与覆盖率判定

涉及文件（以实际项目结构为准，禁止复制出第二套实现）：

- `scripts/backfill_research_data.py`
- 现有 research backfill/service 模块
- `src/infrastructure/storage/market_database.py`
- 相关数据契约模块

要求：

1. 补采 worker 退出时输出并持久化结构化 summary，至少包含：
   - `target_date`
   - `source_run_id`
   - `candidate_count`
   - `complete_candidate_count`
   - `component_coverage.daily`
   - `component_coverage.adjustment_factor`
   - `component_coverage.financial_history`
   - `component_coverage.fund_flow_history`
   - `missing_by_component`
   - `missing_reason_by_symbol`
   - `checkpoint_updated_at`
   - `worker_status`
2. 覆盖率必须从 worker 退出后的数据库状态重新计算，不能直接复用启动前或内存中的旧统计。
3. `completed/partial/pending` 保留原语义，但不得把 `partial` 直接等同于“禁止 AI 重跑”。
4. 每只未完成股票必须保留组件、来源、错误类型、尝试次数、最后数据日期和是否可重试；失败不得伪造成 available。
5. 同一股票的成功组件不得在恢复任务中重复补采。

验收：用 300 只候选构造 297 只完整、3 只失败的隔离场景，summary 必须显示 `partial`，同时准确给出 `297/300` 和三只失败详情。

### P0-B：新增“是否触发 AI 重跑”的纯判定器

建议放在现有 AI OS 调度/数据质量模块中，禁止把判定散落在 API 路由和脚本两处。

输入：补采 summary、当前数据质量策略、最近一次 AI run 元数据。

输出：

- `eligible: bool`
- `reason_codes: list[str]`
- `coverage_snapshot`
- `data_revision`
- `source_run_id`

判定原则：

1. 优先复用当前系统已有的数据质量/发布门槛；不得另造一套与 AI 消费口径冲突的百分比。
2. 如果目前没有可复用的统一门槛，只允许提取现有 pipeline 中的判定为共享纯函数，并保持原阈值不变。
3. `worker_status=partial` 时，只要覆盖率达到现有门槛且不存在系统性错误（Token 缺失、数据库不可写、全源不可用等），可以 `eligible=true`。
4. 未达门槛时必须返回明确原因，例如：
   - `fund_flow_coverage_below_threshold`
   - `financial_coverage_below_threshold`
   - `daily_coverage_below_threshold`
   - `systemic_data_source_failure`
   - `no_material_data_improvement`
5. 判定器只决定是否重新研究，不改变任何股票的买卖资格。

验收：覆盖边界值、低于边界、`partial` 但达标、系统性故障、无数据变化五类单元测试。

### P0-C：幂等的 AI 持久化重跑编排

涉及文件：

- `src/api/app.py` 中现有 `_daily_research_data_backfill` 调度入口
- 现有外部 worker/任务编排模块
- `task_execution` 或现有运行审计存储模块
- AI pipeline 的唯一正式持久化入口

要求：

1. 补采 worker 正常退出后才执行覆盖率判定；worker 超时、崩溃或结果不可解析时不得触发 AI。
2. 使用稳定执行键保证同一数据版本最多触发一次：
   `post_backfill_ai_rerun:{target_date}:{source_run_id}:{data_revision}`。
3. `data_revision` 必须由候选集合、各组件最新数据日期/更新时间和 checkpoint 版本稳定生成；相同数据重复调度必须得到相同 revision。
4. AI 重跑沿用正式持久化 pipeline，不调用仅返回内存结果的调试接口。
5. 自动重跑带上明确触发来源 `post_backfill_coverage_gate`，写入 `task_execution`，并关联原 `source_run_id` 和补采 checkpoint。
6. 自动重跑不得调用 `execute_open_strategy`、午盘执行或任何成交入口。
7. AI 重跑自身不得再次递归触发同一补采—重跑闭环；每日同一 source run 每个 data revision 最多一次。
8. API 重启后仍能从数据库识别已执行键，不能只依赖进程内存。
9. 若正式 pipeline 需要较长时间，必须通过受控外部 worker 执行，并记录 PID、开始/结束时间、退出码和超时原因。

验收：并发调用两次只能产生一个新 AI run；API 重启后重复调用仍不得重复重跑。

### P1：AI 实际消费新证据的闭环核验

重跑成功不能只以 HTTP 200、进程退出码或“数据库已有补采记录”判定。

必须核验：

1. 新 AI run 的创建时间晚于 `checkpoint_updated_at`；
2. 新 run id 不等于补采前旧 run id；
3. 新 run 的 300 条（或实际候选数）决策已经持久化；
4. 决策中的资金流、财报、行情来源和数据日期与补采后的数据库一致；
5. 汇总中的 `flow_coverage`、`fundamental_coverage` 来自新 run 的实际 evidence，而不是补采表覆盖率；
6. 少量仍缺证据的股票继续由现有逐股闸门阻断，不应导致已完整股票全部被全局抹除，除非现有全局质量规则明确要求；
7. 输出 `run_outcome`、`actionable_count`、各证据覆盖率和阻断原因；允许市场确实无机会时仍为零信号，但必须能区分“市场无机会”和“数据不足弃权”。

### P1：失败恢复与可观测性

1. 补采失败、覆盖率不足、AI worker 失败、AI 消费校验失败分别记录不同状态。
2. 有限恢复只针对 `retryable=true` 的股票和组件；沿用现有限频等待，不无限重试。
3. 输出最终状态：
   - `backfill_completed_ai_rerun_succeeded`
   - `backfill_partial_threshold_met_ai_rerun_succeeded`
   - `backfill_below_threshold_ai_not_triggered`
   - `ai_rerun_failed`
   - `ai_consumption_verification_failed`
4. 失败详情需能在进程重启后从数据库读取。
5. 现有关键任务失败告警与熔断继续生效，不用扩大超时掩盖错误。

### P2：结果展示

在现有状态接口/页面返回以下字段，不改变推荐列表排序：

- 补采前覆盖率；
- 补采后数据库覆盖率；
- AI 新 run 实际消费覆盖率；
- 是否触发重跑及原因；
- 重跑 run id、开始/结束时间；
- 未补齐股票数及逐只原因；
- “流程成功”“数据达标”“产生可交易信号”三个独立状态。

## 6. 测试要求

### 单元测试

- 覆盖率判定边界；
- `partial` 达标可触发；
- 未达标不触发；
- 系统性数据源故障不触发；
- data revision 稳定性；
- execution key 幂等；
- 已成功组件不重复补采；
- 禁止交易入口调用；
- 禁止递归触发。

### 集成测试（临时数据库）

1. 构造旧 AI run；
2. 执行真实 `backfill_research_data` worker 路径；
3. 写入 `partial` 且达标的 checkpoint；
4. 验证只产生一个新持久化 AI run；
5. 关闭并重开数据库后验证执行键、失败原因和关联关系仍存在；
6. 验证没有新增 `paper_trade`，也没有调用交易执行任务。

### 隔离真实数据实跑

使用当前 Tushare 权限和真实候选链路，但使用隔离数据库/报告目录：

- 保留真实来源、行情日期、财报期数和资金流日期；
- 不制造生产故障；
- 不重启或部署生产；
- 不触发交易；
- 记录补采耗时、等待/退避耗时、AI 重跑耗时及总耗时。

### 回归测试

- 运行新增测试；
- 运行补采、调度、AI pipeline、数据库持久化、交易隔离相关测试；
- 最后运行项目完整测试集；
- 任何失败必须列为未完成，不得用“与本改动无关”直接判定通过。

## 7. 验收标准

以下条件必须全部满足才能标记完成：

1. 补采结束后能重新计算数据库真实覆盖率；
2. `partial` 但达到现有质量门槛时会自动触发一次 AI 持久化重跑；
3. 未达门槛时不触发，并持久化逐只缺失原因；
4. 相同 data revision 重复执行不会生成第二个 AI run；
5. 服务重启后幂等仍有效；
6. 新 AI run 的时间晚于补采 checkpoint，且 AI evidence 确实消费补采后的来源和日期；
7. 能明确区分流程成功、数据达标和交易信号三个状态；
8. 隔离实跑无任何模拟或真实成交；
9. 新增测试、相关回归和完整测试集全部通过；
10. 不改变任何选股和交易规则。

## 8. Luna 交付物

1. 修改文件清单及每个修改的原因；
2. 修复前后时序对照；
3. 补采前、补采后数据库、AI 实际消费三组覆盖率；
4. 新旧 AI run id、时间和 evidence 日期对照；
5. execution key 与重复触发测试证据；
6. 未补齐股票逐只原因、尝试次数、来源和最后数据日期；
7. 隔离实跑耗时拆分；
8. 新增测试、相关回归、完整测试结果；
9. 所有未验证项和剩余问题；
10. 不自动部署生产。生产部署和生产 AI 重跑另行执行。

## 9. Luna 执行指令

按本文件和项目根目录三份规范实施与验收。保留已有修改，使用现有 Tushare 2000 积分权限，不改变选股和交易规则。先核验基线，再实现补采后覆盖率判定、幂等 AI 持久化重跑和实际消费验证。完成单元、临时数据库集成、隔离真实数据实跑及完整回归；不得触发交易，不自动部署生产。交付前后覆盖率、run 关联、逐只缺失原因、耗时、AI 消费证据和测试结果。未验证项不得标记完成。
