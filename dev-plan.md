# 2026-09-06 外部配置加载修复

- [x] 共享 runtime loader 与后端启动器显式绑定原安装目录 .env；保留配置优先级、源码发布目录不含密钥。
- [x] 9 项专项回归、管理员统一部署、生产 Tushare 两只股票探测通过。证据：test-reports/unit-20260906-external-runtime-env.md。
- [ ] 先前后端反复无响应根因与长期稳定性验证；当前短时健康通过，不标为根治。

# 2026-09-06 Luna 两轮复核返工计划（待实施）

本节是本轮实施入口，依据 `test-reports/quality-20260906-luna-two-round-review.md`。下方历史完成勾选不代表本轮完成。先读本节及根目录另外两份规范；保留所有已有修改，只修六项复核问题及必要验收。常规实现无需中途确认。

边界：使用现有Tushare 2000积分权限，不采购新服务；不改选股公式、排序、分数阈值、65分研究资格、80只即时研究范围、Top N、买卖及学习规则。允许纠正证据状态和挂接；相同有效输入下原判定必须一致，修正错误输入导致结果变化需逐只解释。不得为了“多交易”制造信号。

本轮交付到隔离验收和部署交接为止。不得自动重启、采用生产运行契约、执行生产回填或交易；这些动作待隔离通过后另行授权。生产只读核验可以进行，不在生产注入故障。历史授权和历史报告不得作为本轮已通过的依据。

## 批次A：固定基线，先写能暴露问题的测试

- [ ] scripts/audit_data_completion.py、test-reports/luna-review-remediation-20260906/ | 精确按run_id导出基线，生成一致性隔离副本、源码差异及测试基线；不覆盖已有备份或报告 | 优先级(P0)
- [ ] tests/unit/ai_os/、tests/unit/scripts/、tests/unit/infrastructure/ | 固化六项复现与边界测试，先证明修复前失败，禁止只测试happy path | 优先级(P0)

固定对照：run_id=`b3e44ce2cb3f4b3c8587823f16a10eba`，300只候选，目标交易日2026-09-04。原证据：230只有完整历史、70只只剩摘要；资金流及时覆盖297/300，缓存统计却300且stale=0；默认补采错误选择27132ba233bb404c996af089a6d2fe33。先重新核验，不把旧数字直接当本次测量。确认样本000069.SZ及002998.SZ、002870.SZ、301266.SZ；实际库若变化，保留固定快照对照并说明差异。

基线同时记录候选代码集、四表独立期数/日期/来源、流方向与新鲜度、AI阶段实际输入字段、provider运行预算、交易/持仓/现金/拒单/学习表数量和内容指纹。数据库备份用SQLite一致性备份，不直接复制正在写入的DB文件。先检查现有实现及脏工作树，禁止覆盖他人未提交修改。

## 批次B：修证据完整性与日期（依赖A，两个模块可并行）

- [ ] src/ai_os/candidate_evidence_enricher.py、tests/unit/ai_os/ | 完整历史与最新摘要分开保存，按组件合并；失败、空值或简版不得覆盖有效历史；成功后重新构造最终持久化证据 | 优先级(P0)
- [ ] src/ai_os/candidate_evidence_enricher.py、src/infrastructure/market_data/research_flow.py、src/infrastructure/market_data/source_manager.py | 统一传递本轮已核验目标交易日，历史方向与数据新鲜度分开；缓存和备用链均不得以旧K线降低目标日 | 优先级(P0)
- [ ] src/ai_os/pipeline_observability.py、scripts/audit_data_completion.py | 统计最终挂接后的摘要可用率、四表完整率、资金流及时覆盖、stale/pending及未调度数，不用缓存命中数替代 | 优先级(P0)

验收：000069及全部70个覆写样本，在输入历史有效且摘要补采成功时仍保留四表历史、期数及来源；落库关闭重开后一致。固定快照三只旧流应保持stale，及时覆盖297/300；只有真实获得目标日数据才允许增加覆盖。停牌/未发布可单列解释，不新设交易豁免。前台30秒上限不放宽，未完成后台补采不能声称被本轮AI消费。

## 批次C：修批次身份、财报更新与请求审计（依赖A，可分文件并行）

- [ ] scripts/backfill_research_data.py、tests/unit/scripts/test_backfill_research_data.py | 显式run_id跨日期精确查询；默认使用明确的最新成功批次，未知/不完整run不可空集报完成；候选与额外持仓分别计数 | 优先级(P0)
- [ ] src/infrastructure/market_data/data_completion_service.py、src/infrastructure/market_data/tushare_provider.py、src/infrastructure/market_data/source_manager.py | 四表独立检查缺期、新披露和修订；新鲜缓存复用、仅补需要的表；提交后读回合并数据判完整 | 优先级(P0)
- [ ] src/infrastructure/market_data/tushare_request_budget.py、src/infrastructure/market_data/tushare_provider.py、src/infrastructure/market_data/data_completion_service.py | 透传真实endpoint、请求发送/队列耗时、网络耗时、重试和延期状态，取消由source猜测尝试次数 | 优先级(P1)
- [ ] src/infrastructure/market_data/data_completion_service.py、src/infrastructure/market_data/source_manager.py、tests/unit/infrastructure/ | 统一错误脱敏、空异常类型保留及持久化，使用合成凭据验证，不能输出真实token | 优先级(P1)

批次身份测试：同日四个300行批次、较旧批次行数更多、最新批次未完成、显式历史run、未知run、300候选加候选外持仓、重复股票。持仓不能挤掉300只候选；默认失败时说明原因，不悄悄改选旧批次。

财报测试：2019—2020年各8期不能仅凭行数判当期有效；新披露和同报告期修订可更新；正常未披露不能按自然日误判；仅cashflow失败时另外三表不重复下载；下一轮读回合并结果完整。检查接口现有权限，不假定必须使用高积分接口；若无法核验最新披露，明确freshness_unknown并有限复查，不把未知伪装已核验。

审计测试：排队超时实际发送0次、一次发送成功、有限重试成功、分页多次请求、权限拒绝不循环重试、空TimeoutError、全部失败、合成token/URL参数脱敏；临时数据库关闭重开后逐次详情可读。attempt_count口径必须明确，另记录实际network_send_count；共享任务等待者不得各自重复计算网络发送。

## 批次D：候选入队、有限后台恢复（依赖B、C）

- [ ] src/ai_os/pipeline_runner.py、src/ai_os/task_executor.py、src/api/app.py、src/ai_os/scheduler.py | 候选集合确定后持久化run关联任务；启动恢复和现有定时调度消费同一任务队列；保留20:30作为补充入口 | 优先级(P0)
- [ ] src/infrastructure/storage/market_database.py、src/infrastructure/market_data/data_completion_service.py、scripts/backfill_research_data.py | 复用checkpoint实现组件级幂等、原子认领/租约、有限重试、延期和跨run去重；CLI与后端调用同一服务逻辑 | 优先级(P0)
- [ ] tests/unit/api/、tests/unit/infrastructure/、tests/integration/ | 真实阻塞、进程恢复、并发认领、跨日跨run、预算耗尽及成功组件不重复补采测试 | 优先级(P0)

先确定当前调度器/checkpoint能复用的能力，最小补充缺失字段或索引，不另建任务服务。新候选入队无需等待Deep完成；尚未正式完成的run必须区分运行状态，不能被默认选择器当成功run。相同股票/组件/目标日/窗口的工作可共享，分别保留各run订阅关系。

预算契约：保留现有前台30秒及更严格子预算。后台先核验现有有效配置；若无批次总预算，新增单次恢复切片默认60秒、每任务每轮最多一次初试加一次重试，且不得突破底层更严格限制。使用单调时钟deadline，所有排队、退避、分页和请求纳入预算；不能在剩余预算不足时启动无法及时返回的新请求。到期持久化deferred/next_retry_at并释放worker，禁止while死等；权限拒绝无配置变化不自动连试。

底层阻塞线程无法取消时，不以协程cancel冒充请求已终止；记录inflight并阻止同key重叠重试，限制活动请求数量。旧响应晚到只可更新符合时序/版本的数据，不得篡改已冻结AI输入。租约过期恢复也要考虑旧执行者仍在途的情况。

恢复测试须真正终止隔离worker再启动、验证租约/待补状态读回；仅重新调用同一个函数不算进程恢复。启动恢复与20:30并发只能认领一次；切片结束不能丢剩余候选。跨run/目标日的新任务不能掩盖旧未完成任务；过时任务须明确superseded及继承关系，不能冒充completed。

## 批次E：隔离全链路与交付（依赖B—D全部完成）

- [ ] src/agents/codex_stock_analyzer.py、tests/unit/agents/、tests/integration/ | 在模型发送边界校验真实数值/日期/单位和完整请求hash；保留旧摘要hash兼容性，明确二者口径 | 优先级(P0)
- [ ] scripts/audit_data_completion.py、tests/integration/、test-reports/luna-review-remediation-20260906/ | 固定300只冷暖补采对照、低分与80只外覆盖、隔离AI完整链路、只读生产对照及不变量验收 | 优先级(P0)
- [ ] dev-plan.md、project-structure.md、code-guideline.md、test-reports/luna-review-remediation-20260906/acceptance.md | 按六缺陷逐项列证据、测试命令/结果、剩余问题及部署回滚交接；未验证项保持未完成 | 优先级(P0)

隔离环境必须显式使用隔离DB/输出路径，禁用交易、通知、学习写入和生产调度；检查所有单例实际路径后才运行。真实AI路径保持execute_paper_trades=False；不改预选提示或候选数来追求更好结果。验证20预选/5Deep/5终审是否实际完成，阶段失败原样记录。

区分三层证据：数据库已存、候选最终挂接、实际提交模型。当前轻量预选没有显式财报字段，不宣称其消费全部四表，更不能为验收擅自扩充提示。Deep核对提交载荷中四表关键值/报告日期/单位和20日资金流；hash只证明输入身份，不证明模型理解全部字段。

交付目录须含baseline、after、attempts、isolated-cold、isolated-warm、ai-input-validation、tests及acceptance，JSON/CSV每次独立命名，不覆盖冷跑证据。记录run_id、目标日、分母、配置、源码hash范围、各阶段耗时及真实请求量。固定数据测试要求判定一致；真实来源刷新产生的评级变化逐只解释，不要求LLM输出逐字一致。

完成门槛：六项缺陷测试全部通过；候选+持仓任务登记100%、未解释遗漏0；完整历史被简版覆写0；旧资金流被计为当期有效0；真实阻塞和重启恢复通过；实际输入有可复验数值和完整请求hash；相关回归为本轮新跑；隔离交易/现金/持仓/学习写入零增量且受保护数据内容指纹一致。不得要求外部数据成功率必须100%，不得把provider未提供数据作为代码全通过的借口。隔离、生产部署、生产实跑分别列状态；后两项本轮保持待授权/未验证。

## 可直接交给Luna的指令

按根目录dev-plan.md顶部“2026-09-06 Luna 两轮复核返工计划”及另外两份规范顶部同名增补实施。保留已有修改，使用现有2000积分权限，不改选股、交易、学习规则。先固定基线并复现六项问题，再按依赖修复、完成隔离冷暖补采及真实AI链路验收。常规实现无需中途确认，不重启或写入生产，不触发交易。交付逐只覆盖与缺失原因、真实请求轨迹、最终证据与模型提交输入校验、测试结果及部署交接；未完成项不得标完成。

---

# Adaptive Investment 交易执行分层改造计划

## 2026-09-06 生产数据缺口增补（生产验收已完成，保留3只外部数据 stale）

实施依据：docs/luna-production-evidence-gap-plan-20260906.md，保留历史计划。

- [ ] scripts/audit_data_completion.py | 按analysis_json.run_id固定300只逐组件基线 | P0
- [x] src/infrastructure/market_data/data_completion_service.py、scripts/backfill_research_data.py | 全300只组件缺口队列、断点恢复和生产分批回填 | P0（2026-09-06已完成，297 complete、3 stale）
- [ ] src/infrastructure/market_data/source_manager.py、tushare_provider.py | 财务失败异常类型、发送状态及等待耗时持久化 | P0（异常类型和组件耗时已验；逐次 provider 发送状态仍需后续增强）
- [x] src/ai_os/candidate_evidence_enricher.py、pipeline_runner.py、task_executor.py | 数据补采独立于研究门槛，接入现有后台调度和完成后挂接 | P0（生产调度已注册，新进程AI已实际消费300只缓存）
- [x] src/ai_os/pipeline_observability.py、tests、test-reports | 分组件指标、隔离回归、AI输入校验、生产验收 | P0（748/748，全流程报告已交付）

验收报告：`test-reports/unit-20260906-production-evidence-gap.md`；新进程复跑：`test-reports/luna-production-evidence-gap-20260906/production/ai-run-new-process-validation.md`。剩余3只 stale 是外部行情日期限制，不是静默遗漏。

## 2026-09-05 增量修复（用户批准：仅模拟探索可调整，原计划保留）

报价缺失后续修复：source_manager.py 为主请求/一次重试/备用链各保留8秒预算；超时仍在途时跳过重叠重试并走备用；candidate_evidence_enricher.py 保留失败provenance。已完成真实300792.SZ、实际阻塞、临时SQLite关闭重开和生产30秒参数验证；710项unit/integration通过。新增源码尚未采用到生产进程，需非交易窗口部署后单票复验；不需要整轮AI复跑。

进度快照：代码实现、704项单元/集成测试、隔离全跑及管理员部署已交付。2026-09-05 20:05生产复跑完成，深度5/5、终审5/5、四类财报各8期；账本未新增成交。清单保留未勾选表示端到端尚未完成：仍有1只偶发报价失败、交易日模拟闭环待验。最新证据见 test-reports/unit-20260905-production-research.md，勿将下方历史批次的已完成状态套用到本轮。

- [ ] src/infrastructure/market_data/remote_market_discovery.py、source_manager.py | 发现资金流优先有效Tushare历史；复用缓存减少补齐重复请求，保留来源失败原因 | P0
- [ ] src/infrastructure/market_data/tushare_provider.py | 独立报告期分页去重，补足8期而非8条修订记录；保留部分成功 | P0
- [ ] src/agents/codex_stock_analyzer.py | 结构化财报关键数值不截断；研究日期明确最近已完成交易日，执行报价另判 | P0
- [ ] src/ai_os/pipeline_runner.py | 分阶段计时，定位数据补齐与AI延迟；不改评分排序 | P1
- [ ] src/ai_os/execution_policy.py、tests/unit/ai_os/test_execution_policy.py | 审计零买入，探索扩展仅限paper且需显式批准的可审计证据；不绕过负资金流、财务风险、终审否决与报价风控 | P1
- [ ] tests/unit、tests/integration、test-reports | 新增分页、提示数值、周末新鲜度及交易隔离测试；报告实际执行与未完成项；生产重启需管理员 | P0

学习边界：不得将影子观察伪造成交或混入成交胜率；新增观察学习入口须保持独立样本类型与时间可知性。增加模拟交易不是数量指标，规则变更须先通过隔离验证。

## 批次 A：执行契约与数据模型（可并行）

- [x] src/ai_os/execution_policy.py | 新增纯函数执行策略，只消费既有选股结果；定义 normal、probe、blocked 三种买入模式及 probe 持仓退出/转正状态机 | 优先级(P0)
- [x] config/settings.py | 新增仅用于 paper execution 的探索仓位配置：单笔默认 2%、硬上限 3%、组合总探索敞口 5%、每日最多 1 笔、确认窗口 3 个交易日、最长持有 5 个交易日、止损 -4%；不得修改现有选股阈值 | 优先级(P0)
- [x] src/infrastructure/storage/market_database.py | 为持仓、成交和拒单持久化 execution_tier、entry_flow_state、fallback_status、entry_gate_reasons、probe_expiry、promotion_status、entry_decision_id，并提供兼容迁移 | 优先级(P0)
- [x] src/ai_os/strategy_version.py | 将执行策略、配置和 schema 变更纳入运行代码哈希及启动契约校验 | 优先级(P0)

## 批次 B：证据透传与买入执行（依赖批次 A，可并行）

- [x] src/ai_os/cross_sectional_scoring.py | 不改变排名、分数、方向或阈值，只额外输出 pre_gate_direction、flow_state、flow_sources、fallback_attempted、gate_reasons、non_flow_gates_passed 等可审计元数据 | 优先级(P0)
- [x] src/ai_os/pipeline_runner.py | 将最终候选的执行证据完整透传到 paper execution；neutral 只有在“原始买入意图成立且唯一阻断项为资金流 missing/invalid”时才具备 probe 评估资格 | 优先级(P0)
- [x] src/infrastructure/storage/market_database.py | 在最终买入循环中先执行原有 normal 买入，再评估 probe；negative 一律拒绝，missing/invalid 必须先完成备用源尝试且不得伪装 positive；继续执行报价、因果性、仓位和行业敞口约束 | 优先级(P0)
- [x] src/ai_os/trading_costs.py | normal/probe 共用现有价格取整、滑点、佣金和印花税函数，不新增第二套成交口径 | 优先级(P1)

## 批次 C：卖出、转正与持仓身份（依赖批次 A、B）

- [x] src/ai_os/trading_policy.py | 保持 normal/Deep Buy 现有退出阈值不变；为 probe 增加 -4% 硬止损、资金流转 negative 退出、3 日未确认退出、5 日绝对最长持有；报价缺失时禁止伪造成交 | 优先级(P0)
- [x] src/infrastructure/storage/market_database.py | 当 probe 在确认窗口内重新满足原 normal 买入条件且资金流 positive 时标记 promoted，并仅在行业/总仓位约束允许时补仓至正常目标；不得重复开仓或摊低成本 | 优先级(P0)
- [x] src/ai_os/pipeline_runner.py | 持仓兜底决策继续携带 entry_decision_id、原始 deep_rating、execution_tier 和 probe 状态，防止持仓被中性 stub 改写身份 | 优先级(P0)
- [x] src/ai_os/paper_ledger_rebuild.py | 重建账本时恢复 normal/probe/promoted 身份和原始入场证据，确保重启前后退出规则一致 | 优先级(P1)

## 批次 D：可观测性与接口（依赖批次 B、C，可并行）

- [x] src/ai_os/pipeline_observability.py | 增加 normal_eligible、probe_eligible、blocked_negative、blocked_missing、fallback_exhausted、probe_opened、probe_promoted、probe_expired 计数与原因分类 | 优先级(P1)
- [x] src/ai_os/task_executor.py | 连续出现“有 pre-gate 买入意图但全部因 flow missing/invalid 被阻断”时发送数据源告警；不得自动降低阈值或自动扩大 probe 仓位 | 优先级(P1)
- [x] src/api/routes/portfolio_routes.py | 返回每个持仓的 execution_tier、entry_flow_state、probe_expiry、promotion_status 和对应风险规则 | 优先级(P1)
- [x] src/api/routes/decision_routes.py | 返回 pre_gate_direction、gate_reasons、fallback_status 和最终 execution_disposition，明确区分股票质量与数据不足 | 优先级(P1)
- [x] src/api/routes/trust_routes.py | 增加 normal/probe/blocked 的日度统计和 probe 胜率、亏损、转正率；样本不足时显式 unavailable | 优先级(P2)

## 批次 E：测试与上线门禁（依赖全部实现）

- [x] tests/unit/ai_os/test_execution_policy.py | 覆盖 positive、negative、missing、invalid、备用源成功/失败、唯一阻断项、多个阻断项及所有 probe 生命周期分支 | 优先级(P0)
- [x] tests/unit/infrastructure/test_paper_execution_tiers.py | 验证 2% 单笔、3% 硬上限、5% 总探索敞口、每日 1 笔、行业 40%、不重复开仓、不摊低成本及字段持久化 | 优先级(P0)
- [x] tests/unit/ai_os/test_trading_policy.py | 验证 normal/Deep Buy 规则无回归，以及 probe 的 -4% 止损、negative 退出、3 日超时、5 日上限和缺报价 fail-closed | 优先级(P0)
- [x] tests/integration/test_probe_trading_cycle.py | 验证 missing→备用源失败→probe 买入→positive 转正，以及 missing→negative/超时→卖出的完整闭环和账务恒等式 | 优先级(P0)
- [x] tests/integration/test_algorithm_regression_gate.py | 固化选股排序、分数、阈值、Top N 和 normal 买卖结果基线，证明本次改造只改变执行处置，不改变选股逻辑 | 优先级(P0)
- [x] scripts/adopt_runtime_contract.py | schema、算法代码哈希和测试全部通过后，在非交易窗口采用新运行契约；禁止 --reload，失败时不切换旧实例 | 优先级(P0)
- [x] test-reports/unit-20260903-085831.md | 记录全量测试结果和执行分层回归结果；生产采用需另行在非交易窗口执行 runtime contract adoption | 优先级(P1)

## 2026-09-06 生产部署一致性修复（本轮）

- [x] src/infrastructure/runtime_identity.py、scripts/create_runtime_manifest.py | 生成关键运行文件清单，启动时校验，冻结PID/启动时间/版本摘要，并单独报告磁盘漂移 | P0
- [x] src/api/app.py、src/api/routes/system_routes.py、scripts/run_api.py | 接入启动契约和 `/api/v1/system/runtime` 运行身份接口；生产保持 reload 关闭 | P0
- [x] scripts/deploy_research_backend.ps1、../scripts/start_adaptive_learning_backend.ps1 | 增加部署锁、维护状态、清单比对、进程身份校验、失败熔断和回滚记录 | P0
- [x] scripts/deploy_research_backend.ps1、../scripts/start_adaptive_learning_backend.ps1 | 将清单提升为独立源码发布目录；启动器按清单选择发布源，并显式保持原有市场数据库、Tushare预算库和共享配置路径；部署前停止并验证旧看门狗进程树 | P0（2026-09-06 管理员部署与最终接口验收通过，见 `test-reports/unit-20260906-runtime-final-postcheck.md`）
- [x] ../scripts/start_all.ps1、../scripts/restart_adaptive_backend_admin.ps1、restart.ps1 | 统一转入受版本校验的部署入口，避免普通启动绕过验收 | P0
- [x] tests/unit/infrastructure/test_runtime_identity.py、tests/unit/api/test_system_runtime.py | 验证清单往返、漂移拒绝、托管启动拒绝和运行身份路由 | P0
- [x] 生产计划任务注册与生产版本切换 | 管理员部署报告及 `/api/v1/system/runtime` 已验证计划任务动作、release_id、artifact_hash、PID、启动时间和磁盘漂移；见 `test-reports/unit-20260906-runtime-deployment-postcheck.md` | P0
- [ ] 生产无交易AI复跑与新候选证据持久化验收 | 本轮未触发生产 AI 或写入测试候选，避免把部署验证误报成 AI 运行完成 | P1
