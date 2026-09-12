# HiThink 集成编码与验收规范

## 1. 安全与凭据

- 只读取 `HITHINK_FINANCE_API_KEY`；兼容来源如需支持必须明确列出且不得覆盖推荐来源。
- Key 不得进入源码、命令参数、URL、日志、异常、SQLite、响应、测试夹具、Markdown、Git 或模型 Prompt。
- 请求只允许通过 `X-api-key` header 传递；错误脱敏必须覆盖 header、query、repr、嵌套异常和第三方库信息。
- `.env.example` 只允许空值。任何 `sk-fuyao-` 字符串进入暂存区都应使提交失败。
- 线上测试结果只保存 request_id、状态、延迟、行数、时间窗口和内容哈希。

## 2. 命名与文件组织

- provider ID 固定为 `hithink`；展示名为“同花顺金融数据服务”。不要混用 `fuyao` 作为业务 provider ID。
- 类名使用 `HiThinkProvider`，响应值对象使用清晰的 `HiThinkPayload`/`ProviderPayload`。
- 上游字段只在 `hithink_provider.py` 解析；API 路由和业务层不得重复读取上游 JSON 键。
- 单文件超过 280 行时拆成 client、mapping 或 endpoint group；不要让 SourceManager 继续膨胀。
- 不复制官方仓库的完整 CLI/SDK；本项目运行时直接调用稳定 REST 契约。

## 3. 请求与错误模式

- 成功必须同时满足 HTTP 2xx、JSON 可解析、顶层 `code == 0`、`data` 类型符合端点契约。
- HTTP 200 + 业务错误不是成功；保留脱敏后的 `code`、`message`、`request_id`。
- 错误至少分类为：`not_configured`、`authentication`、`permission`、`validation`、`not_found`、`empty`、`rate_limited`、`timeout`、`network`、`server`、`parse_error`、`contract_error`。
- 认证、权限、参数和不支持能力不重试；429 尊重 Retry-After；网络和 5xx 最多有限重试。
- 所有排队、退避和请求必须纳入调用方 deadline。协程取消不得伪装底层阻塞请求已停止。
- 使用已有 `provider_resilience.py` 和 `provider_metrics.py`，不再创建第二套全局熔断器。
- 禁止高并发逐股请求；优先批量端点。全市场结果必须落盘。

## 4. 时间与新鲜度

- 毫秒时间戳统一转换为带 `Asia/Shanghai` 语义的日期/时间；存储用带时区 ISO 8601 或既有 UTC 约定，不使用无时区本地时间。
- 区分 response assembly timestamp、数据就绪时间、交易日、报告期、公告日和抓取时间。
- 周末/节假日快照返回上一交易日数据时必须标为 EOD/previous-session，不能标 `is_live=True`。
- 盘中执行报价必须包含可验证的数据时间，并严格晚于最终决策信号时间；缺失时 fail closed 或使用既有实时源。
- 历史回放只可使用 as-of 当时已披露数据；当前最新财报不得泄漏到历史日期。

## 5. 代码与市场标识

- A 股统一使用完整 `thscode`/内部标准代码：`.SH`、`.SZ`、`.BJ`；不能仅按首位数字猜测后直接用于关键调用，名称输入先走 meta 消歧。
- 上游股票代码、指数、板块、基金、期货和期权不得混在同一无类型字符串路径。
- 单个端点只接受其契约允许的资产类型；不支持时明确失败，不尝试相似标的。

## 6. 数值、单位与空值

- `null` 表示未披露或上游无值，必须保留；禁止自动补 0。
- 价格保留上游精度；金额、成交量、换手率和比例在 mapping 层明确单位。
- `price_change_ratio_pct=10.0` 表示 10%，不是 0.10；跨源比较前统一百分比口径。
- Tushare 成交量常用手、HiThink 返回值需按契约核实单位；未确认前不得比较或落同一字段。
- 财务比较必须同时对齐币种、报告期、年报/季报、累计/单季、合并/母公司和公司类型。
- 估值允许为负或 null；不得过滤亏损公司或自己补算历史估值。

## 7. Provenance 与审计

- 每次成功结果至少带：provider、endpoint/capability、fetched_at、data_date/report_period、is_live、is_cached、trust_score。
- 每次 fallback 记录前序 provider、失败分类和脱敏摘要；不能只显示最终成功源。
- 动态信任按 provider + capability 计算，不能因估值成功就推定实时行情可靠。
- 初始信任只是先验；样本不足、未跨交易时段验证时不得自动晋级。
- 原始 provider 值不可被融合覆盖。融合结果必须可追溯到各源输入和口径转换。

## 8. 主备与融合规则

- 本地完整且新鲜的历史数据优先，避免重复消耗 Tushare 积分和 HiThink 配额。
- Tushare 保持历史日线、财务、资金流和回放真值首选。
- HiThink 初始只在标的消歧、当前估值、特色榜单和龙虎榜使用 primary；每项都必须有独立开关。
- HiThink 日线/财务先作为 validator/fallback；只有独立验收通过才能改变顺序。
- 实时执行报价初始 shadow。不得因为短时 40/40 成功直接晋级。
- provider 差异触发降置信度、告警或人工复核；不得无依据平均价格或多数投票。

## 9. 配置规则

建议配置项：

```text
HITHINK_FINANCE_API_KEY=
HITHINK_BASE_URL=https://fuyao.aicubes.cn
HITHINK_TIMEOUT_SECONDS=8
HITHINK_RETRY_ATTEMPTS=2
HITHINK_MIN_INTERVAL_SECONDS=0.25
HITHINK_FAILURE_THRESHOLD=3
HITHINK_COOLDOWN_SECONDS=60
HITHINK_SYMBOL_MODE=primary
HITHINK_VALUATION_MODE=primary
HITHINK_SPECIAL_MODE=primary
HITHINK_DAILY_MODE=validator
HITHINK_FINANCIAL_MODE=validator
HITHINK_REALTIME_MODE=shadow
```

- mode 仅允许 `disabled|shadow|fallback|validator|primary`。
- 非法配置启动失败，不静默改成 primary。
- 生产默认值应与发布阶段一致；测试可显式覆盖，不能修改全局用户环境。

## 10. 测试要求

- 单测必须使用合成响应和假 Key，禁止真实联网。
- happy path 与边界至少覆盖：沪深北、ST、停牌、退市、空值、负估值、非交易日、报告修订、银行/保险报表。
- 故障覆盖：401/403、HTTP 200 业务错误、429、Retry-After、500/503、超时、断网、非法 JSON、schema 漂移、部分数组。
- 路由测试必须断言实际调用顺序、调用次数、fallback reason、缓存来源和最终 provenance。
- 回归必须证明选股候选、分数、排序、Top N、交易方向、仓位、费用和学习输入在相同有效数据下不变。
- 线上 canary 与 CI 分离；没有 Key 时 CI 必须跳过线上测试而不是失败或使用假数据冒充。

## 11. Canary 统计与晋级

- 按 capability 分开统计，不汇总成单一“HiThink 稳定率”。
- 至少记录 count、success rate、P50/P95/P99、429、5xx、timeout、empty、stale、completeness、agreement。
- 三个交易日覆盖开盘、午间、尾盘和盘后；样本覆盖沪深北及特殊状态标的。
- 数据变化是正常现象，一致性签名只能用于静态端点；实时数据比较必须对齐采样时间。
- 任何 primary 晋级都必须在 acceptance.md 中列出证据、日期、样本量、阈值和回滚开关。

## 12. 发布、回滚与禁止事项

- 先隔离测试，再 shadow，再单项 primary；不得一次性切换全部能力。
- 不自动重启生产、不在交易时段部署、不直接修改 active runtime release。
- 发布使用既有不可变 release/manifest 流程，验证 source root、artifact hash、PID、启动时间和数据库路径。
- 回滚通过 capability mode 完成，不删除数据、不重置 Git、不清理现有 provider 配置。
- 严禁顺手重构 SourceManager、数据库、评分、交易或 UI；发现无关问题只记录。
- 严禁因 HiThink 新增特色字段改变现有选股公式。新字段进入策略必须另立需求、回放和算法晋级门禁。

