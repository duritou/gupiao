# 分阶段验收与运行状态优化实施方案

日期：2026-09-09。状态：代码实现、隔离回归和隔离真实 AI 验证已完成；生产部署/实跑及历史旧代码完整重放未执行，详见 `test-reports/luna-stage-acceptance-20260909/acceptance.md`。

## 1. 目标与范围

让系统准确回答：本轮流程是否完成、每一阶段所需证据是否充分、哪些缺失是计划内、哪些是采集或交付故障、交易是否延期、学习是否正常。

本轮只修审计、验收、展示和必要的状态一致性问题。保留已有修改，遵守根目录 dev-plan.md、project-structure.md、code-guideline.md。本专项的阶段验收口径替代历史“全池覆盖率直接决定本轮研究验收”的解释，但不删除历史记录或取消历史已约定的后台补采工作。

- 使用现有会员权限；不新增付费源，不修改选股公式、阈值、排序、研究名额、提示策略、买卖和学习算法。
- 不增加买入数量作为验收门槛，不把正常 Hold/Underweight 判为失败。
- 不扩大网络补采范围或等待预算来制造通过率；必要采集缺陷先定位并单列后续修复建议。
- 本轮交付到代码实现、隔离验收和部署交接；不自动部署、重启生产或触发生产 AI/交易/通知。
- 生产只读；隔离运行允许写隔离研究结果，保护交易账本、现金、持仓和学习数据。

## 2. 固定基线，不沿用旧报告的完成勾选

首先按 run_id 核验 2026-09-09 凌晨运行：

`d48e781a12f04e538b4fea79bb5f0c2f`

已观察到的参考值，Luna 必须重新核验：

| 项目 | 当时记录 |
|---|---|
| 扫描/技术信号/决策 | 5207 / 3973 / 300 |
| AI 预选/Deep/终审 | 20 / 10 / 10 |
| 决策持久化 | 精确 run_id 读回 300 行 |
| 整池财务摘要可用率 | 123/300，41% |
| 整池资金流有效覆盖 | 296/300，98.67% |
| 资金流 missing 代码 | 002870.SZ、002998.SZ、600929.SH、688432.SH |
| 额外报价采集 | 3 成功，297 因 below_min_ranking_score 未安排 |
| 决策状态 | data_blocked=272，不能直接解释为 272 次采集失败 |
| 流批量补采 | 20 次请求成功，缺口单元从 48 降至 28，partial |
| 晨报 | task success，degraded=true |
| 研究补采 | 运行快照记录 pending，不代表查询时仍 pending 或已完成 |
| 执行 | deferred_until_market_session；无 actionable picks |
| 无买入计数 | 扫描记录 1 天，随后告警记录 4 天，需要统一口径 |

同日 latest 接口可能混入后续运行。不得用 latest、最大日期、最大行数代替精确批次。当前 strategy_decision 存在按日期/股票/策略唯一键：若后续覆盖导致原始记录不足，使用对应 task_execution 输出及原始冻结证据补充，明确证据来源和缺口；不得将别轮数据拼成该 run。新增审计快照须可按 run 保留，优先复用现有持久化结构。

记录原工作树差异、生产 release/hash、数据库实际路径、配置及目标交易日。SQLite 使用一致性备份建立隔离副本，不能直接复制正在写入的数据库。敏感配置不输出。

## 3. 阶段契约和覆盖率

先从实际调用链提取每阶段已有必需字段，形成版本化 stage requirement 清单。需求清单用于衡量已有约定，不得借此改变准入或提示。

| 阶段 | 分母固定方式 | 应核验内容 |
|---|---|---|
| universe/technical | 本轮实际登记的初筛集合 | 基础信息、既有技术算法所需行情窗口、时序；正常政策排除与数据原因排除分别统计 |
| preselection | 实际提交预选模型的集合 | 实际提示消费的字段和发送结果；未消费财报不能要求完整四表作为本阶段通过条件 |
| deep_research | 入选 Deep 的集合，在请求前冻结 | 既有研究契约所需 K 线、财务、资金流、新闻/公告证据，以及模型实际可见内容 |
| final_review | 应进入终审的集合 | 预期数、尝试数、完成数和缺席原因；终审确实收到此前结论及必要证据 |
| execution | 到达执行评估的候选及必要持仓检查，分列 | 当前交易窗口、因果报价、现有风控；延期与无候选独立显示 |
| learning | 按现有学习规则已到期且适用的样本 | 应回填数、成功/延期/缺基准数、持久化和任务状态；未成熟样本不算失败 |

各阶段同时输出 target_count、attempted_count、completed_count、skipped_count、failed_count、unverified_count 及逐只清单。失败或缺数据的入选股票仍留在原阶段分母，禁止只统计成功者。

每个组件输出 required_count、available_count、fresh_count、missing_count、invalid_count、stale_count、unknown_count、not_required_count 及原始比例。计数维度明确，状态分组互斥；多原因列表单独统计并注明不互斥。

- 分母为零时比例为 null，available=false，并说明 no_eligible_candidates；不能显示 100% 或 0% 覆盖失败。
- 财务摘要可用率、四表独立期数完整率、实际提交字段完整率分开；123/300 不得重命名成完整财报覆盖率。
- 资金流方向和新鲜度独立；负值有效，不因 negative 降低数据覆盖率。
- 保存股票数和“股票×日期”单元数，两者不可相互替代。
- 已核验停牌、历史不足、未披露可归 expected_unavailable，但保留原始缺口及证明，不自动算 available，更不形成新交易豁免。
- 公告不是强制每天存在；区分确无相关公告、发现相关公告但正文缺失、标题截断、正文已取得但未提交。不能一律强抓全部公告正文。
- 盘前研究按最近完成交易日检查日线，执行时报价按执行时刻检查。凌晨没有当日盘中报价不单独判研究失败；既有提示若误把它作为研究否决，记录语义问题，本轮不擅改提示和评级。

## 4. 未采集与缺失原因分开

增加兼容的审计字段，名称可适配现有结构，必须具有以下语义：

- run_id、stage、stock_code、component、required_for_stage、requirement_version。
- scheduling_status、data_status、freshness_status、reason_codes。
- target_trade_date、as_of、actual_data_date、source、evidence_ref。
- background_task_id/status、next_retry_at、last_attempt_at（仅有真实记录才填）。

not_scheduled 只是采集状态：若已有有效缓存，证据仍可 available；若本阶段不需要，是 not_required；若阶段必需却未安排且缓存不足，则是 required_not_scheduled，须列为流程缺陷或未核验。

保留全池后台补采任务登记率和任务老化/延期指标。即时研究不需要某数据，不意味着后台既有补采义务消失。不得改为“低分候选全部无需回填”，也不得把 pending、superseded 或成功空响应改称 completed。

## 5. 运行结果分维度表达

复核 src/ai_os/pipeline_observability.py：当前 classify_run_outcome 优先判断 execution_deferred，可能遮盖数据不足。新增独立维度，兼容旧字段，旧交易消费者不得依赖新验收标签改变动作：

- process_status：completed / partial / failed / unverified。
- persistence_status：verified / partial / failed / unverified。
- evidence_status：sufficient / partial / insufficient / unverified，附分阶段原因。
- research_status：completed / partial / failed / not_requested / unverified。
- execution_status：deferred / no_eligible_candidates / completed / blocked / failed / not_requested。
- learning_status：completed / partial / failed / not_due / unverified。
- acceptance_status：pass / partial / fail / unverified，明确代码验收与本轮运行质量的范围。

单个 task success 仅表达任务函数完成；输出 degraded、部分完成、子调用错误应完整透传。无买入且研究证据不足时，不得宣称“市场无机会”；显示“当前已完成研究无买入信号，部分判断受证据限制”。

晨报记录具体降级组件及原因。无候选不是晨报基础设施失败，缺市场环境也不能仅报 generated。API和报告优先读持久化的小型审计摘要，避免每次健康/状态请求解析几千行大 JSON。

## 6. 学习故障与无交易计数一致性

两个学习任务曾在 9 月 8 日 20:01 成功，但 incident 的最后失败为当晚 22:22/22:25。必须按事件时间、执行身份和持久化来源重建先后，不能用较早成功清掉较晚故障，也不能直接删除 incident 表。

- 核查成功幂等键、失败记录保留、内存历史加载与 incident 聚合是否丢失后续尝试。
- 仅在现有恢复判定下，本次成功确实晚于对应失败时更新 recovered；旧成功、乱序回调不得解除新故障。
- 未查到后续真实恢复，状态保持 open/unverified 并说明依据；不通过写假成功“修复”。
- 必要修复限于状态持久化、时序一致性和展示，不改熔断阈值、重试频率及学习算法。
- 连续无买入天数复用同一计算函数、同一账户、同一截至时刻及已完成交易日集合；扫描和告警相同输入结果必须一致。明确未开盘当日如何计数、停市日如何处理，不用任务运行次数代替交易日。

## 7. 循环淘汰审计

沿实际顺序核对：基础数据 → 分数/资格 → 补采入队 → Deep → 终审。

对被数据影响的分数记录 score_before_gate、缺失组件、消费阶段、排除原因及后台任务关联（已有字段优先复用）。验证是否存在“必需数据缺失压分 → 低分不补 → 永久缺失”的路径。

本轮只诊断和增加可复验审计。不为验证而修改生产评分、准入或给低分股票特殊交易资格。如果确认存在需调整调度/准入的循环，交付最小后续方案并标未修复；若已有后台独立补采，验证其任务登记、恢复和下一轮可用性，不能仅凭代码有入口判通过。

## 8. 实施批次与文件职责

先阅读现有实现，再确定最小 diff；下列路径不是强制全部修改。

### A：基线及需求映射

- [x] scripts/audit_data_completion.py | 精确 run 的只读分阶段导出及历史证据来源 | P0
- [x] test-reports/luna-stage-acceptance-20260909/baseline/ | 冻结代码、配置、集合、数据库和现有状态 | P0
- [x] 本报告目录 requirements.json | 从实际消费者提取阶段字段及分母契约 | P0

### B：纯统计与持久化（依赖 A）

- [x] src/ai_os/pipeline_observability.py 或必要小型辅助模块 | 独立状态维度、分母及原因分类纯函数 | P0
- [x] src/ai_os/pipeline_runner.py、candidate_evidence_enricher.py | 冻结阶段集合，挂接审计，不改评分与调度 | P0
- [x] src/infrastructure/storage/market_database.py | 复用现有存储保存紧凑 run 审计，重开读回，旧记录 unknown | P0

### C：状态一致性与展示（依赖 B，可按文件并行）

- [x] src/ai_os/task_executor.py、必要存储函数 | 故障恢复时序及无交易计数统一 | P0
- [x] src/api/routes/brief_utils.py、ai_os_routes.py、scanner_routes.py | 晨报降级原因、阶段状态只读展示和旧字段兼容 | P1
- [x] scripts/audit_data_completion.py | 前后对照、逐只缺口和后台义务单独报告 | P0

### D：隔离验收及交接

- [x] tests/unit/ai_os/、tests/unit/api/、tests/unit/infrastructure/ | 下述关键矩阵回归 | P0
- [ ] tests/integration/ | 临时数据库重开、固定输入全链路、状态乱序及无副作用验证（历史固定输入完整重放未执行） | P0
- [x] test-reports/luna-stage-acceptance-20260909/acceptance.md | 逐项证据、剩余问题、部署交接 | P0
- [ ] 根目录三份规范 | 仅增补本专项进度和模块职责，不覆盖历史 | P1

## 9. 必须覆盖的测试与实跑

1. 初筛不需要完整四表时，不因其缺失报本阶段失败；Deep 入选后必需证据缺失仍留分母并报部分完成。
2. 300 初筛、20 预选、10 Deep，Deep 中 2 个失败：Deep 分母仍为10，不能变8；零候选比例为 null。
3. 未安排网络采集但缓存有效；必需却漏调度；预期外部缺失；unknown不能伪装停牌。
4. 请求20次均成功但留下28个单元缺口，仍为partial；负流有效、stale不算当期覆盖。
5. 盘前 execution deferred 与研究证据不足同时显示；Hold本身不算失败；无交易不能证明无机会。
6. DB四表各8期，但模型只收到部分字段或截断文本：分别报告，不将存储完整伪装输入完整。
7. 同日两个run、覆盖旧strategy_decision、未知run、旧记录缺新增字段：不串批、不补造历史。
8. 先成功后失败、先失败后成功、乱序回调、重启加载：故障状态时序一致。
9. 周末、节假日、盘前、同日多次扫描：无买入交易日计数一致。
10. 固定有效输入、固定模型返回下，候选次序、各分数、最终评级、执行方向、拒单原因与改前一致。新标签只改变解释。

先对固定基线做隔离重放；需要模型发送边界验证时使用受控模型返回检查真实载荷。另做一次隔离真实AI研究链路，使用当前合法数据并单独命名新run，不能伪装成凌晨历史回放。不把真实LLM输出逐字一致当回归条件。

隔离运行前核对DB、缓存、队列、配置和单例的实际路径；禁用生产调度、通知、交易及学习写入。前后核对受保护表内容指纹、账户金额；研究审计记录允许写隔离DB。真实运行失败须交付实际失败，不能仅用mock称全部完成。

运行相关回归、编译检查、git diff --check；存储改动须做兼容迁移与重开验证。共享链路改动按影响范围扩展回归，报告本轮真实测试数，不沿用787等历史数字。

## 10. 交付与通过门槛

交付目录：test-reports/luna-stage-acceptance-20260909/，包含 baseline、after、per-stock、ai-input-validation、tests、isolated-run、acceptance.md。所有产物带run_id、目标日、截止时刻、分母、契约版本及代码hash范围。

必须交付：

- 同一固定run改前/改后分阶段对照，解释为何数字变化；不能把指标分母改变说成数据补齐。
- 全300只阶段归属、必需组件、真实缺失原因及后台任务状态；阶段内数据异常与整池背景指标并列。
- 10只Deep预期/实际数量、实际提交字段证据；历史无法恢复则明确未验证。
- 循环淘汰核查结论及证据、学习incident时序、无买入计数对照。
- 代码、隔离验收、真实AI、生产部署、生产实跑分别标状态。后两项本轮未执行。

通过要求：固定输入业务判定不变；阶段分母无失踪项；全部异常有真实状态或明确unknown；无伪造数据/恢复；必要持久化可重开验证；隔离受保护数据无变化。外部数据未提供可以保留为限制，但不能因此把该次研究证据完整性标pass。代码测试通过与数据充分分开验收。

## 11. 可直接交给 Luna 的指令

按 docs/luna-stage-acceptance-plan-20260909.md 和根目录三份规范实施与验收。保留已有修改，使用现有权限，不改变选股、采集范围与预算、交易或学习算法。先按指定run核验基线和阶段必需字段，再完善分阶段指标、独立运行状态、故障时序与计数一致性；保留全池后台补采义务。完成固定输入回归、临时数据库重开和隔离真实AI验证，交付同run前后对照、逐只缺口、AI实际输入证据及剩余问题。常规实现无需中途确认；不自动部署或写入生产。涉及准入/调度策略调整的循环淘汰问题先出证据与后续方案，未修复和未验证项不得标完成。
