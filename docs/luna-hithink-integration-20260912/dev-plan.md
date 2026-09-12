# Luna 执行计划：Tushare + HiThink 分层数据源优化

## 0. 任务目标与基线

- [x] `git` | 开工前确认当前分支包含备份提交 `75759e1`，远程备份分支为 `origin/codex/pre-hithink-optimization-20260912`；保存 `git status --short` 和 `git rev-parse HEAD` 到验收报告 | 优先级(P0)
- [x] `docs/luna-hithink-integration-20260912/acceptance.md` | 建立本轮验收矩阵，记录源码基线、数据库路径、配置来源、运行身份、测试命令和每阶段结论；不得记录任何 API Key | 优先级(P0)
- [x] `test-reports/hithink-integration-20260912/baseline/` | 保存现有 Tushare/TickFlow/腾讯/新浪/东方财富路由、关键接口响应摘要和测试基线；只保存脱敏摘要与哈希，不保存凭据或全市场原始响应 | 优先级(P0)

成功标准：改造前状态可从远程分支恢复；本轮所有差异都能追溯到 HiThink 接入，不混入无关重构。

## 1. 固化能力分工与不可变约束

- [x] `docs/数据源.md` | 增加 HiThink 能力、公开边界、时间语义、认证方式和主备矩阵；明确 Tushare 会员数据继续作为历史/财务/资金流真值层 | 优先级(P0)
- [x] `providers/hithink.yaml` | 新增 provider manifest，声明行情快照、日线、复权、财报、指标、估值、指数、基金与特色数据；标注无分钟 K/tick/Level-2/公告新闻原文 | 优先级(P0)
- [x] `config/settings.py` | 增加 HiThink 非敏感设置和逐能力开关；Key 只读取 `HITHINK_FINANCE_API_KEY`，不得复制到项目 `.env`、SQLite、日志或决策记录 | 优先级(P0)
- [x] `.env.example` | 只增加空的 `HITHINK_FINANCE_API_KEY=` 与非敏感默认配置；不得加入真实值或格式相似的示例密钥 | 优先级(P0)

固定主备策略：

1. 本地已验证缓存始终优先于远程历史数据。
2. Tushare 首选：盘后原始日线、历史财务、披露/修订时间、复权因子、资金流、回放可知时点。
3. HiThink 首选：标的消歧、当前估值、涨跌停/炸板/连板/异动/热榜；龙虎榜首选 HiThink，Tushare/东方财富校验。
4. HiThink 交叉验证或补缺：历史日线、财务三表、财务指标、指数、基金。
5. 盘中执行报价保持 TickFlow → 腾讯 → 新浪；HiThink 在 canary 通过前只能 shadow，不得影响订单和评分。
6. 任一新来源失败必须走既有降级链，不得返回模拟数据，也不得把缺失值补零。

## 2. HiThink REST 适配器（可与第 3 批测试先行并行）

- [x] `src/infrastructure/market_data/hithink_provider.py` | 实现零 CLI 依赖的异步 REST client：统一信封校验、超时、有限重试、Retry-After、错误分类、脱敏、代码规范化和字段映射 | 优先级(P0)
- [x] `src/domain/models/market_data.py` | 注册 `hithink` 能力，但初始 `realtime_quote=False`；声明 `daily_kline`、`financial_statements`、`financial_indicators`、`index_data` 等真实支持项 | 优先级(P0)
- [x] `src/infrastructure/market_data/registry.py` | 注册同花顺金融数据服务来源、认证要求、信任初值、能力和当前 rollout 状态 | 优先级(P1)

适配器最小公开方法：

- `configured: bool`
- `fetch_symbol_search(query, limit)`
- `fetch_snapshot(codes)`
- `fetch_daily_history(code, start, end, adjust)`
- `fetch_financial_history(code, period, limit)`
- `fetch_financial_indicators(code, report)`
- `fetch_valuation_snapshot(codes)`
- `fetch_limit_pool(kind, trade_date, page, size)`
- `fetch_dragon_tiger(trade_date, board_type)`
- `runtime_stats()`（只含计数、延迟、错误类型、request_id；绝不含请求头或 Key）

适配器验收：HTTP 200 但 `code != 0` 必须失败；401/业务鉴权、429、5xx、超时、无效 JSON、`data=null`、空数组和合法 `null` 字段必须区分。

## 3. 先写适配器和契约测试

- [x] `tests/unit/infrastructure/test_hithink_provider.py` | 覆盖成功、空数据、业务错误、鉴权失败、429、Retry-After、5xx 有界重试、超时、脱敏、非法代码、周末快照和字段 null 保留 | 优先级(P0)
- [x] `tests/fixtures/hithink/` | 保存人工构造的最小脱敏响应；不得复制真实 Key，不保存大结果，不把线上响应当唯一测试夹具 | 优先级(P0)
- [ ] `tests/unit/infrastructure/test_provider_metrics.py` | 验证 HiThink 成功率、延迟、完整率、降级、半开恢复和不同 capability 分开统计 | 优先级(P1)
- [x] `tests/unit/infrastructure/test_provider_resilience.py` | 验证 429/5xx 冷却、串行节流和成功恢复；不得无限重试或高并发重放 | 优先级(P1)

门禁：适配器单测通过前不得挂入 SourceManager、API 路由或生产调度。

## 4. 第一阶段接入：低风险、高收益能力

- [x] `src/api/routes/valuation_routes.py` | 改为 HiThink 当前估值首选；无配置、权限不足、空值或熔断时回退 Tushare `daily_basic`/现有 native quote；返回明确 provider、data timestamp 和 fallback reason | 优先级(P0)
- [x] `src/api/routes/dragon_tiger_routes.py` | 改为 HiThink 龙虎榜首选，Tushare 与东方财富降级；保持日期范围和板块类型语义，不把榜单热度转成交易建议 | 优先级(P0)
- [x] `src/infrastructure/market_data/remote_market_discovery.py` | 对涨跌停、炸板、连板、热榜等增加 HiThink 主路径；东方财富保留降级，候选排序公式和阈值完全不变 | 优先级(P0)
- [x] `src/api/routes/market_routes.py` | 标的名称/代码消歧优先使用 HiThink meta；已有完整 `thscode` 不做额外请求 | 优先级(P1)

- [x] `tests/unit/api/test_hithink_routes.py` | 验证估值、龙虎榜和特色数据的首选/缺失回退、负估值/null 保留、单位和 provider 元数据 | 优先级(P0)
- [x] `tests/unit/infrastructure/test_hithink_discovery.py` | 证明 HiThink 只替换来源，不改变候选筛选、排序、分数、Top N 和交易门槛 | 优先级(P0)

第一阶段验收：功能开关默认 `shadow`；比较结果落审计摘要，不改变生产返回，待离线与线上 canary 通过后逐能力改为 `primary`。

## 5. 第二阶段接入：日线与财务交叉验证

- [x] `src/infrastructure/market_data/source_manager.py` | 注册 HiThink dispatch；本地缓存优先；Tushare 继续盘后原始日线首选；HiThink 用于前复权日线、Tushare 失败补缺和跨源一致性检查 | 优先级(P0)
- [ ] `src/infrastructure/market_data/data_completion_service.py` | 财务补齐仍由 Tushare 首选；HiThink 只补缺或校验三表/指标，不得用简表覆盖已有完整历史，不得丢失公告日、报告期或修订版本 | 优先级(P0)
- [ ] `src/infrastructure/storage/market_database.py` | 如现有表不能表达来源与修订，只做向后兼容扩展：保存 provider、fetched_at、report period、announcement time、request_id hash 和字段完整率；先在隔离副本迁移 | 优先级(P0)
- [ ] `src/infrastructure/market_data/provider_metrics.py` | 按 provider + capability 计算成功率、P50/P95、完整率、一致性与新鲜度；样本不足不能自动晋级 | 优先级(P1)

- [x] `tests/unit/infrastructure/test_hithink_source_routing.py` | 覆盖本地/Tushare/HiThink/公共源顺序、调整口径、缓存不能遮蔽新首选、失败降级和熔断恢复 | 优先级(P0)
- [x] `tests/unit/infrastructure/test_hithink_financial.py`、`test_hithink_consistency.py` | 覆盖财务期数、null、不覆盖、报告期对齐和跨源指标比较 | 优先级(P0)
- [x] `tests/integration/test_financial_history.py`、`test_history_completion.py` | 使用隔离数据验证财务/历史补齐及现有 Tushare 链路 | 优先级(P0)

一致性规则：

- 原始日线只比较同一交易日、同一复权口径；价格容差不超过 0.01 元，成交量先统一股/手单位。
- 财务字段按币种、报告期、累计/单季、合并口径对齐；不能只按字段名比较。
- 差异只降置信度并记录，不允许在请求内“多数投票”篡改原始值。

## 6. 盘中 canary 与晋级门禁

- [x] `scripts/probe_hithink.py` | 已提供安全的有界单标的探测器，只写脱敏统计；多标的矩阵和 3 日样本门禁仍待在线收集 | 优先级(P0)
- [x] `src/ai_os/scheduler.py` | 在现有调度器中注册 shadow canary，不新建调度平台；失败不影响主流程，不对同一时点并发轰击 | 优先级(P1)
- [x] `src/api/routes/system_routes.py` | 暴露 HiThink 按 capability 的健康、样本量、最后成功时间、P95、熔断状态和当前 rollout；不暴露 Key、请求头或完整响应 | 优先级(P1)
- [x] `tests/unit/scripts/test_probe_hithink.py` | 已覆盖有界串行、未配置、失败脱敏和退出状态；交易日多标的在线门禁仍待补采 | 优先级(P0)

单项晋级到 `primary` 必须同时满足：

- 连续 3 个完整交易日，至少 300 次有界样本请求。
- 总成功率 >= 99.5%，5xx/网络错误率 < 0.5%，无未处理异常。
- P95 < 1.5 秒，P99 < 3 秒；动态限流能按 Retry-After 冷却。
- 数据日期/时间符合能力语义，非交易日不会把前收误标为实时。
- 与 Tushare/腾讯对应字段一致率 >= 99%，所有差异都有单位或口径解释。
- 强制故障注入时 100% 走既有降级链，核心 API 不返回 500。

盘中执行报价额外要求：响应必须能证明交易所数据时间且严格晚于最终信号时间；否则永久保留 shadow/fallback，不晋级。

## 7. 全链路回归与隔离验收

- [x] `tests/unit/` | 全量回归 854 passed，覆盖选股公式、排序、65 分研究资格、Top N、买卖门槛、资金流四态和学习规则 | 优先级(P0)
- [x] `tests/integration/` | 全量回归 19 passed，覆盖冷启动、补齐、provider 失败、完整交易周期、学习闭环和 API 路由验收 | 优先级(P0)
- [ ] `vscode-ext/tests/` | 若系统页展示 provider 状态，验证缺字段、degraded、fallback 和旧后端兼容 | 优先级(P1)
- [ ] `test-reports/hithink-integration-20260912/` | 输出 baseline、unit、integration、canary、consistency、rollback 六类报告；大结果只记录路径、行数和哈希 | 优先级(P0)

推荐命令：

```text
poetry run pytest tests/unit/infrastructure/test_hithink_provider.py -q
poetry run pytest tests/unit/api/test_hithink_valuation_routes.py tests/unit/api/test_hithink_special_routes.py -q
poetry run pytest tests/unit tests/integration -q
cd vscode-ext && npm run compile && npm test
```

## 8. 发布与回滚

- [ ] `scripts/create_runtime_manifest.py` | 将新增 provider、配置和路由文件纳入运行清单哈希 | 优先级(P0)
- [ ] `scripts/adopt_runtime_contract.py` | 校验 capability rollout 配置、Key 只来自用户环境/Secret、数据库 schema 兼容和回滚开关完整 | 优先级(P0)
- [ ] `scripts/deploy_research_backend.ps1` | 复用现有不可变发布流程；本轮不得绕过非交易窗口、维护门禁或运行身份校验 | 优先级(P0)
- [ ] `docs/luna-hithink-integration-20260912/acceptance.md` | 写明每项能力最终状态：disabled/shadow/fallback/primary；未实测不得标 primary | 优先级(P0)

初始发布状态建议：

- `symbol_search=primary`
- `valuation=primary`
- `special_data=primary`
- `dragon_tiger=primary`
- `daily_history=fallback_and_validator`
- `financials=fallback_and_validator`
- `realtime_quote=shadow`

回滚只切逐能力开关并保留审计数据，不删除数据库、不清空缓存、不撤销 Tushare 配置。出现鉴权失败、连续 3 次 5xx、P95 超过 3 秒、数据日期错误、字段完整率下降或跨源严重偏差时，自动降为 fallback；选股或交易回归立即全量关闭 HiThink 路由。
