# Tushare 2000 积分优先接入：Luna 实施方案

日期：2026-09-05。状态：核心闭环已实施并通过验收；未验证权限或口径不匹配的扩展数据仍保留备用源。

## 1. 目标与边界

用户已开通 Tushare 2000 积分。Adaptive 当前消费的数据，只要该账户能获取且满足字段、覆盖率和时效要求，一律优先采用 Tushare；合格的 Tushare 缓存属于该主源。备用源只在无权限、不支持、缺失、过期或故障时补位，并记录原因。

本次改变数据供给，不调整选股公式、评分权重、入选阈值或交易策略。不通过强制产生买入来验收。资金流保持 positive/negative/missing/invalid 的既有语义；保留已存在的执行分层规则，不新增缺失放行。

优先覆盖现有 A 股研究、市场环境、模拟执行与学习使用的数据，不扩展到无消费者的港美股、期货等全站数据。

## 2. 已确认的起点

- 本会话直接测试 daily_basic、moneyflow 返回 2026-09-04 数据；fina_indicator、income 返回财务记录，最新报告期为 2026-06-30。不能由此推断所有股票覆盖完整。
- Adaptive 的 _try_tushare_quote 已完成日期传播；实测 600519.SH 返回 2026-09-04 的 EOD 数据。
- 已增加可重复的运行中接口探测，区分 supported、empty、permission_denied、transient_error；不能靠清空历史失败计数宣称恢复。
- source_manager.py 的指数、市场宽度、日线、财务、资金流和研究证据入口已接入 Tushare 优先路径。
- providers/tushare.yaml 已改为准确的 EOD 能力声明，不再把 daily_basic 未提供的量价字段混入映射。
- scripts/daily_sync.py 是现有同步入口；scripts/README.md 描述当前日线同步依赖 baostock。应复用现有任务，不建立重复定时任务。
- 当前工作区有大量既有改动。Luna 开始时记录 git status，保留这些改动，不覆盖根目录已有规划文档。

## 3. 权限与能力矩阵

下列接口是实施候选，不是全部已实测通过。Luna 必须逐接口做有限只读探测，输出 supported/permission_denied/empty/transient_error 等结果；空数据不等于无权限。

| 能力 | Tushare 候选接口/计算 | 实施要求 |
|---|---|---|
| 股票列表、上市日期、行业、交易日历 | stock_basic、trade_cal | 优先接入，覆盖系统支持的交易所；历史元数据保留时点 |
| 日线和复权 | daily、adj_factor | 按交易日批量拉取；保存原始价、因子和复权基准 |
| 日估值、市值、换手 | daily_basic | 与 daily 按代码和日期连接，不能伪造不存在的字段 |
| 财务指标、三表 | fina_indicator、income、balancesheet、cashflow | 普通接口按股票缓存，不能默认使用高权限 VIP 全量接口 |
| 个股资金流 | moneyflow | 对齐既有资金流定义、单位和观察窗口后接入买入证据 |
| 指数趋势、学习基准 | index_daily、index_basic | 覆盖当前使用的指数与沪深300；从指数清单确定准确代码 |
| 指数估值等扩展指标 | index_dailybasic | 官方总表与单接口页门槛不一致，按账户实测启用 |
| 全市场宽度和成交额 | daily + 股票池/停牌状态 | 计算涨跌平家数、覆盖率、成交额；仅完整快照供环境判断 |
| 涨跌停价和停牌 | stk_limit、suspend_d | 实测可用则优先；按证券当日规则识别，不能统一用 9.9% |
| 行业分类与强弱 | index_classify、index_member_all；行业行情接口按权限探测 | 成分聚合注明为自算统计，不伪装官方行业指数 |
| 两融、龙虎榜、大宗及其他已有消费者 | margin、margin_detail、top_list、top_inst、block_trade 等 | 盘点消费者后逐项探测，支持且满足口径的全部迁移为 Tushare 优先 |
| 盘中行情、分钟、新闻、公告、特色热榜 | 对应接口独立探测权限 | 2000 积分不能视为独立权限已开通；缺口保留现有可用源 |

此前“index_dailybasic 一定需要 4000”的结论应撤回：总表标 4000，单接口页标 2000，以本账户实际响应为准。不能据此要求用户升级。

## 4. 路由与数据契约

1. 调用方先明确用途、目标交易日、频率、复权口径和必需字段；优先选合格 Tushare 缓存或 Tushare 网络结果，再走该能力的备用源。
2. 实时执行报价只能使用满足现有新鲜度要求的实时源。Tushare 盘后数据可供研究、昨收、历史学习，不可被标成实时或作为当前成交报价。
3. 权限、健康度按接口维护。moneyflow 无权限不能关闭 daily；单股停牌无行不能熔断整个源。记录最后成功时间、数据日期、错误类型和恢复探测时间。
4. 复用 provider_resilience/provider_metrics；统一请求预算和退避。API 进程与同步进程共享配额控制或明确分配预算，不能每个进程各自用满账户限额。遵从接口单独限额，重试计入预算。
5. 缓存键包含接口、参数、交易日、复权方式。权限失败有限缓存，并支持购买后手动重探测；临时故障有界重试，禁止永久封禁或静默填值。
6. 每项证据保存 provider、endpoint、data_date/as_of、fetched_at、交易日、单位、复权方式、coverage、status、fallback_reason；复用现有结构，缺字段再做兼容扩展。
7. 财务有效期按公告可知时间而非报告期；历史回放不可读取后来修订的数据冒充当时已知版本。修订记录和首次获取时间保留。
8. 全市场成交额统一单位后逐证券求和；指数成分成交额不能相加当全市场成交额。指数、资金流和行情的金额单位分别转换并测试。
9. 缺失值保存为空并标原因，零值仅代表有效观测为零；同源缓存不能计为第二个独立来源。

## 5. 按依赖顺序实施

### A：P0 能力探测与统一路由

- [x] providers/tushare.yaml、src/domain/models/market_data.py | 修正能力、字段与时效声明，删除未经复验的可信度断言 | P0
- [x] src/infrastructure/market_data/tushare_provider.py（新增） | 统一 SDK 请求、规范化、限流、EOD 证据和接口探测 | P0
- [x] src/infrastructure/market_data/source_manager.py | 统一日线、指数、市场宽度、证据和备用路由的 Tushare 优先策略 | P0
- [x] src/api/routes/market_routes.py、provider_metrics.py | 保留探测与健康诊断入口，输出实际数据日期和缺口 | P0

完成 A 后，B/C 可以分工；同文件编辑需协调，D 依赖 B/C。

### B：P1 日线、全市场环境与基准

- [x] scripts/daily_sync.py、current_metadata_sync.py、market_database.py | 复用现有同步任务，Tushare 批量日线/每日指标/元数据优先入库 | P1
- [x] source_manager.py、src/ai_os/market_regime.py | 全市场宽度及指数环境消费统一快照；不改变环境分类公式 | P1
- [x] src/explain/outcome_backfiller.py | 沪深300基准由合格 Tushare 数据优先供给，原基准备用源保留 | P1

全市场拉取必须处理单次行数上限、分页/分片、重复与截断；按目标市场股票清单核算覆盖，不将一页成功视为全量成功。停牌、新股、退市和数据缺失分列。

保留原始未复权价用于成交与估值；指标复权采用一致基准。缺日须识别是否停牌，不用前值伪造成交 K 线。目标历史长度取自现有指标最大回看需求，不固定宣称 60 根足够所有指标。

先暂存并验证整批，再原子发布 completed 快照；部分批次不得替换上一份完整快照。重复同步幂等且可断点续传。

凌晨 1 点先验证最近应完成交易日的数据，再分析。周末、节假日使用交易日历，不用自然日差判过期。盘后任务若碰到尚未发布数据，标 pending 并有限补采，不把旧日数据记成当日成功。

### C：P1 财务、资金流与其他可用能力

- [x] src/ai_os/candidate_evidence_enricher.py、src/agents/codex_stock_analyzer.py | Tushare 财务与资金流进入实际分析证据，保留日期、单位和来源 | P1
- [x] src/ai_os/pipeline_runner.py | 验证最终 decision evidence 保留补齐的财务与资金流，不以 missing 伪装 positive | P1
- [x] src/api/routes/financials_routes.py、fundflow_routes.py、valuation_routes.py、dragon_tiger_routes.py、unified_research_routes.py | 按已实测可用接口迁移，复用统一 provider | P1
- [ ] 其他数据消费者（新闻、公告、研报、席位明细等） | Tushare 账户权限/字段/时效尚未全部验证；继续保留原适配器并在验收报告中列明，不把未验证接口强行切主 | P1

moneyflow 的净额、大单净额及历史窗口不可互相替代；明确现有字段需要哪一种。口径不匹配时保存为独立证据或标不可替代，不能靠字段改名改变选股含义。

### D：P2 可观察性与运行验收

- [x] src/api/routes/market_routes.py、src/ai_os/pipeline_observability.py | 输出行情、财务、资金流、指数、市场宽度的日期与缺口 | P2
- [x] 现有前端数据源/市场页（按接口确需修改） | 沿用接口返回的数据日期、完整性和备用原因字段 | P2
- [x] tests/unit/infrastructure、tests/unit/ai_os、tests/integration | 完成行为测试及无下单链路验证 | P2
- [x] docs/数据源.md、test-reports/ | 更新主备映射、实测能力矩阵、运行结果和已知限制 | P2

## 6. 验收标准

- 路由：Tushare 合格时选中 Tushare；无权限/过期/截断/超时才选择备用并记录原因；一个接口故障不影响其他接口。
- 时点：周末凌晨正确取最近交易日；财务公告日期不晚于分析时点；盘后数据在执行报价路径被拒绝。
- K线：覆盖复权、除权日、停牌、新上市和缺因子；价格/股数/金额单位准确；结果按日期升序、无重复。
- 市场宽度：分页截断可被识别；部分入库不发布 completed；停牌不误判平盘；不同板块/ST/无涨跌幅限制证券规则正确。
- 资金流：正、负、零、缺失、非法、过期分别测试；Tushare 成功补齐可在最终 decision evidence 看见，且不被后续步骤覆盖。
- 常驻后端：购买前权限失败后，重探测能恢复对应能力，显示实际成功样本与数据日期，而非仅清零计数。
- 完成相关单元/集成测试及仓库要求的 make test；共享基础设施变更按仓库要求运行覆盖检查。无法运行时给出具体错误，不宣称通过。
- 真实验证至少包含最近完整交易日的全市场批次、当前持仓和深度候选，以及指数/财务/资金流样本；给出请求次数、耗时、应有/实有条数、覆盖率、主备占比和缺口清单。
- 同一冻结输入下，选股公式、权重、交易策略与实施前一致。新增证据造成的结果变化单独说明；无最低买入数、无最低股票评分要求。
- 执行一次隔离的完整研究流程，禁用模拟与真实下单副作用；定时任务运行健康单独核实，不重放买卖任务验收数据接入。

## 7. 部署与交付

复用配置增加按能力切换的 Tushare 优先开关，保留旧主备路径供回滚；不删除既有数据。若需要 DB 迁移，先备份、验证兼容迁移和回滚读取。

在非交易窗口部署并重启后端，禁用 --reload，核对已有代码/算法/schema 版本检查与关键任务告警。若现有运行契约阻止启动，报告具体差异，不能仅改期望版本绕过检查。

Luna 交付：变更文件清单、实际接口能力矩阵、所有消费者的主备映射、测试与真实采样报告、部署/回滚命令。无法覆盖的接口写明是权限、字段、时效还是工程原因。不得仅凭一个股票的 API 成功宣称闭环完成。

## 8. 给 Luna 的执行指令

请按本文 A→B/C→D 实施 Tushare 优先接入。用户已开通 2000 积分，现有 A 股功能中权限、口径和时效满足的数据全部优先 Tushare，备用源按能力保留。保留工作区已有修改，先提交实测权限矩阵，再贯通同步、DB、市场环境、候选证据、基准回填与前端状态。保持选股与交易规则一致，完成测试及隔离研究链路验收，并按第 7 节交付。不要为零买入放宽阈值，也不要为本任务购买新权限。

## 9. 本次实施与验收结果（2026-09-05）

- 只读探测 17 个接口：16 个 supported，1 个 empty（suspend_d）；未发现本次探测中的 permission_denied 或 transient_error。empty 保持为空语义，不转成停牌或正面证据。
- 最近完整交易日为 2026-09-04。Tushare 全市场快照写入 2026-09-02/03/04 三日，分别为 5548/5549/5548 条，按 5556 只 active 股票计算覆盖率约 99.84%/99.87%/99.86%；不完整批次不会发布 completed。
- 真实 SourceManager 验证：指数 4/4、市场宽度 Tushare、K 线 `600519` 返回 5 根升序 EOD 日线；市场宽度同时输出 coverage 和涨跌停统计完整性。
- 真实同步结果：三日共写入 16644 条，`daily_bars_tushare` 同步日志均为 completed；重复执行走幂等 UPSERT。
- 选股公式、评分权重、阈值和交易规则未调整；Tushare 只改变证据供给与主备顺序。资金流仍保持 positive/negative/missing/invalid 四态，缺失不会被当成正面。
- 全量测试：`.venv\\Scripts\\pytest.exe --no-cov -q --tb=short`，708 passed。

仍有明确边界：Tushare 目前在本适配器中是 EOD 源，不承担盘中实时/分钟/盘口；qfq/hfq 继续走具备对应能力的备用源；基本面并非每只股票每个报告期都保证有数据；龙虎榜当前接入汇总，席位明细保留原备用源。详情见 `docs/tushare-first-acceptance-20260905.md`。

## 官方核验资料

- 权限总表：https://tushare.pro/document/1?doc_id=108
- 指数每日指标单接口页（与总表门槛存在差异）：https://tushare.pro/document/2?doc_id=128
- 权限与独立订阅：https://tushare.pro/document/1?doc_id=290
- 指数日线：https://tushare.pro/document/1?doc_id=95
- 个股资金流：https://tushare.pro/document/2?doc_id=170
