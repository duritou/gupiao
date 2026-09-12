# Luna：Tushare 数据补齐闭环实施与验收

状态：方案已交付，实施、隔离实跑及生产验收均未完成。保留现有修改；配合根目录 dev-plan.md、project-structure.md、code-guideline.md 使用。本轮仅修数据供给和可观测性，不调整评分公式、筛选阈值、排序权重、Deep名额或买卖规则，不触发交易。用户已授权常规实现，无需逐项确认。

## 1. 已核验基线与纠正

基线 run_id=27132ba233bb404c996af089a6d2fe33，2026-09-06，行情截至09-04。生产SQLite只读查询 strategy_decision.analysis_json：300条，positive48、negative31、missing221。资金流覆盖率79/300=26.33%；source_coverage=28%是另一指标。

221条missing中220条没有补采attempted字段，1条报价失败。219条最终ranking_score低于65；另两条为600681.SH(65.0，无attempted)和601900.SH(68.1，报价失败)。最终分数不必等于补采前分数，219条的准确历史跳过原因还需Luna对照补采前快照还原，禁止宣称已逐只证明。

源码 candidate_evidence_enricher.enrich_candidate_evidence 同时执行min_ranking_score=65及max_candidates=80，pipeline_runner明确传入这两个条件；本次eligible81、attempted80。不是221条都被限流，也不是简单扩大80上限就解决。

确认缺陷：
1. _default_quote_fetcher在quote不可用时仅返回error/provenance，丢弃同批fundamental/fund_flow；_apply_quote又将其他组件合并绑定到报价成功。601900.SH持久化provenance显示fundamental和fund_flow available=true，而flow_state=missing，构成真实证据丢失。
2. data_completion_service.sync_code的资金流缓存仅按条数判断完成；财报按期数判断，未检查新披露和修订；不能保证新鲜。
3. backfill_research_data断点键为(research_data_backfill,scope,all)，默认跳过completed；sync_code将partial/empty/permission_denied视为terminal。不同目标日期和要求可能沿用旧已处理集合。terminal应表示本轮结束，不代表数据补齐。
4. research_flow要求最近完成交易日，而completed_research_day使用16点边界；普通moneyflow官方更新说明为19点，存在收盘已完成但资金流尚未发布的时窗，需接口独立水位。
5. 预算reserve最多等待65秒，外层fundamental/flow25秒、候选30秒、报价分支8秒，排队等待可被误判为网络超时。tushare_provider._call底层to_thread超时后立即重试，线程是否仍在途需隔离复现；上层报价修复不等于所有SDK调用已解决重叠。
6. request_budget固定分钟桶在边界可能突发；配额按所有endpoint累计，是保守实现，不等于官网每API日限额。外部不共享同一DB的进程不可被本地预算完整统计。
7. 空数据、权限、限流分类是字符串启发式；SDK重试0.5/1秒退避不能代表已跨过服务端限频窗口。

尚待验：后台补采是否有正式调度绑定；不同进程预算DB实际路径；300只在本地是否已有可用资金流但没挂入决策；新闻网页稳定性；完整财报数值和公告正文是否真正送入AI。不得把这些标记为确认修复。

## 2. 权限与运行契约

官方参考：https://tushare.pro/document/1?doc_id=290 （2000档通用200次/分钟，部分接口另有规则）；https://tushare.pro/document/1?doc_id=108 （moneyflow2000积分及更新时间）；https://tushare.pro/document/2?doc_id=143 （news独立权限）。实施时重新核验账户实际响应，不能假定1000次/分钟。保留190默认安全预算，不通过压测撞限额验证。

Tushare优先适用于账户可用的研究数据；有效年包不表示所有接口可用。权限拒绝立即结束当前尝试，限流有限等待后重试，网络/服务异常有限退避，空结果结合停牌、上市时间和发布窗口解释。免费网页不等于收费API授权。

## 3. 依赖化任务清单

### A：基线、分类、组件独立（P0）

- [ ] scripts/audit_data_completion.py | 对固定run的300只逐只导出报价/资金流/财报的已有缓存、数据日、补采前分、是否安排及缺失原因，特别核对600681.SH、601900.SH。
- [ ] src/ai_os/candidate_evidence_enricher.py | 将quote/fundamental/flow分别合并；任一失败不丢其他成功组件，旧有效数据保留且记录本次失败；缓存复用分支也必须透传fundamentals。
- [ ] src/infrastructure/market_data/data_completion_service.py | 组件状态区分available/partial/not_scheduled/deferred_rate_limit/timeout/permission_denied/empty/stale/invalid/provider_error/not_yet_published/not_applicable；不能按整个股票一个成功标志覆盖所有组件。
- [ ] src/infrastructure/storage/market_database.py | 复用现有持久化结构存组件尝试记录和待补任务；迁移向后兼容，保持原历史审计记录不可变。

记录字段：run_id、code、component、endpoint、source、target_date、data_date、requested_window、valid_count、attempt_count、queue_wait、network_time、total_elapsed、error_kind、bounded_message、next_retry_at、is_complete、terminal_reason。无token/cookie。

### B：有限等待与请求去重（依赖A，P0）

- [ ] src/infrastructure/market_data/tushare_request_budget.py | 核验共享路径并采用滑动窗口或平滑放行防分钟边界突发；每次真实发送消耗预算，取消排队不能稍后偷偷发送；外部进程导致限流时尊重服务端冷却。
- [ ] src/infrastructure/market_data/tushare_provider.py | 区分权限/限频/网络/服务/空结果；服务端明确retry-after时优先遵守，过长则持久化延期；无提示采用有界退避。等待预算、网络预算及整体deadline独立且透传。
- [ ] src/infrastructure/market_data/source_manager.py | 排队到期与已发送超时分别记账；保留现有研究报价主备预算，不自动放宽30秒前台预算。以endpoint+规范化参数+数据窗口去重仍在途请求，验证线程超时不重叠同请求。

后台建议初值：一次任务总预算180秒、实际发送最多3次、队列等待累计最多65秒、单次网络最多30秒，全部受单一deadline截断；在deadline前无法合理重试则延期。延期有每日次数上限，供应商持续异常开启冷却探针；不可无限循环。初值须隔离测试后确定，不能覆盖原前台硬预算。

### C：300只后台覆盖与缓存增量（依赖A/B，P0）

- [ ] src/infrastructure/market_data/data_completion_service.py | 数据覆盖队列覆盖固定300只及持仓；65分和80只继续只限制即时昂贵研究补采，不能限制后台基础数据同步或已有有效缓存的挂接。
- [ ] scripts/backfill_research_data.py | checkpoint纳入目标日、窗口、组件和契约版本；恢复时重验水位，partial/empty终止本次但不成为永久完成；权限变更或新的数据日可重新安排。
- [ ] src/infrastructure/market_data/research_flow.py | 资金流按官方发布窗口与交易日独立判新鲜度；未发布期间显式保留上一可用截止日，不假装新数据、不将尚未发布判为供应商宕机。
- [ ] src/ai_os/pipeline_runner.py | 同步阶段后、既有选择流程相应阶段挂接本地有效组件；不因低分跳过缓存读取。补齐证据引起既有门禁结果自然变化需审计，不要求结果与缺数据时相同。
- [ ] src/ai_os/scheduler.py、task_executor.py、src/api/app.py | 核验并接入有界后台补采：19点后资金流发布窗口、盘前缺口恢复；互斥/租约防重复，多次恢复幂等。新候选加入补采队列，前台到期返回部分结果及待补清单。失败不阻塞交易任务调度。

优先级：持仓/现有研究候选→其余300候选；适用接口按日期批量提取并分页查完整，不能把一页当全市场。资金流补最近缺日期，财报只补新报告期/修订及历史空洞，基础信息按更新时间更新；K线检查最新日、窗口、停牌原因及复权因子匹配。复用已有服务，避免第二套调度器或数据库。

### D：AI输入、资讯及展示（依赖A/C，P1）

- [ ] src/agents/codex_stock_analyzer.py及实际证据摘要模块 | 固定输入样本核对三表关键数值、单位、报告期、资金流日期和原始数值；记录输入摘要hash、实际可见行数及截断字段，不凭available/计数认定已消费全文。
- [ ] src/ai_os/pipeline_observability.py、实际scanner/dailybrief路由 | 分开quote/flow/fundamental覆盖率、分母和待补原因；不再将source_coverage当flow覆盖率；研究可用与执行时实时报价分开展示。审查AI是否用盘前无实时价一概拒绝研究评级，先交证据，不私改评级/交易规则。
- [ ] 现有资讯入口（实施先定位真实消费路径） | 小规模读取https://tushare.pro/news/eastmoney并核验公开使用方式。页面稳定可解析则新增轻量适配，低频缓存、去重、发布时间/原始来源/URL/正文范围；登录/验证码/持续403/结构异常即停用并保留原因。不绕过收费API，无可用正文仅作标题线索，不影响主流程。

## 4. 必须交付的测试和实跑

1. 临时DB复现601900：quote失败、flow和财务成功，关闭重开仍保留真实组件；报价门禁仍失败，不伪造可交易。
2. 固定300只输入：低分、80只外都能读取本地有效组件；无数据者全有明确任务/原因。门槛与排序公式不变。
3. 跨交易日缓存：20条旧资金流必须更新最新缺日期；8期旧财报遇新披露/修订应更新；停牌/上市不足不伪补；未发布日状态正确。
4. checkpoint重启、跨目标日、partial/empty/权限恢复均不会永久跳过，成功组件不重复下载。
5. 隔离模拟真实阻塞线程、两个进程共享预算、分钟边界、外部429/SDK限频消息、权限拒绝、服务器5xx、取消排队。验证尝试次数、总等待、无重复在途请求、延期持久化和熔断恢复；不得生产制造故障。
6. 冷缓存与暖缓存实跑固定同一300只、同一行情截止日。交付分组件覆盖率、未处理数、分类失败数、请求量、缓存命中率、阶段耗时；暖缓存不得重拉完整历史。
7. 现有相关unit/integration回归；输入不变时评分/交易纯规则不变，补齐后结果变化单独解释。AI消费需验证最终实际提交内容，模型自称读过不能作证据。
8. 隔离完整pipeline关闭交易；上线前检查无运行任务、非交易窗口、版本/schema一致；部署后新进程复验本轮数据，不以旧716测试替代新测试。

验收底线：固定300只调度/缓存核查覆盖100%，静默遗漏0；可得且日期有效的数据全部挂接，无法取得者逐只解释。不要求行情停牌/权限不支持者伪达到100%数据成功率；不以新增买入数证明优化。真实运行时延交付冷/暖对照，未达到目标注明原因。

## 5. Luna交付物

- test-reports下基线300只逐组件CSV/JSON（注明生产快照或隔离库）、失败记录、前后覆盖表、真实调用次数与耗时。
- 新增测试结果、AI实际输入消费证据、报价/资金流源与日期、规则未改证明。
- 最小修改文件列表、部署状态、剩余问题和待重试清单。全部清单先保持未勾选，逐项有证据后完成。

本次审核未启动新补采、未修改生产代码、未执行新回归、未验证网页稳定采集。上述是Luna实施契约，不是完成声明。
