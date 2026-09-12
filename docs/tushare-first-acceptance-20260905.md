# Tushare-first 实施验收记录

日期：2026-09-05  
范围：adaptive-investment-intelligence 的 A 股行情、市场环境、研究证据、学习基准与日线同步。

## 结论

核心 Tushare-first 闭环已落地并通过回归。选股公式、评分权重、入选阈值和交易策略没有修改；本次只调整数据供给、证据日期/来源传播、主备路由和同步完整性。

## 已落地内容

- `tushare_provider.py`：统一 SDK 调用、请求间隔、代码/日期/单位规范化、日线快照、指数、宽度、基本面、三表、资金流和龙虎榜汇总。
- `source_manager.py`：Tushare 优先的 EOD 行情、K 线、指数、市场宽度、个股证据、财务和龙虎榜入口；实时路径拒绝把 EOD 冒充实时。
- `daily_sync.py`、`current_metadata_sync.py`、`market_database.py`：最近交易日批量同步、覆盖率门槛、原子 UPSERT、幂等同步日志和元数据刷新。
- `candidate_evidence_enricher.py`、研究路由和深度分析：财务/估值/资金流进入最终证据，保留 `provider`、`endpoint`、`data_date`、`fetched_at`、`coverage` 等信息。
- `outcome_backfiller.py`：沪深300基准优先 Tushare，失败才使用 BaoStock。
- `scripts/probe_tushare.py`：可重复的只读能力探测，不输出 token。

## 真实接口探测

本机已配置 Tushare token，探测脚本未打印 token。以 `600519.SH` 和最近完整交易日 `2026-09-04` 为样本：

| 项目 | 结果 |
|---|---:|
| 探测接口 | 17 |
| supported | 16 |
| empty | 1（`suspend_d`） |
| permission_denied | 0 |
| transient_error | 0 |
| `daily` / `daily_basic` / `moneyflow` | supported |
| `fina_indicator` / 三表 | supported |
| `index_daily` / `index_dailybasic` | supported |
| `stk_limit` / `margin` / `top_list` | supported |

`suspend_d` 的空结果只表示本次查询没有返回记录，系统保留为空，不把它伪装成“无停牌风险”或正面交易证据。单只股票的基本面也可能缺失，仍按 missing 处理。

对扩展消费者执行 `scripts/probe_tushare.py --extended` 后：24 个接口中 18 个 supported、3 个 empty（`suspend_d`、`report_rc`、`block_trade`）、3 个 permission_denied（`anns_d`、`news`、`major_news`），没有 transient_error。`margin_detail` 和 `index_member_all` 可用，但当前没有对应的核心选股消费者，因此不新增无需求的数据链路；公告、新闻、研报继续使用已有适配器是账户权限结果，不是漏接主源。

## 全市场真实同步

Tushare 最近三个交易日批量同步结果：

| 交易日 | 目标股票数 | 实际日线数 | 覆盖率 | 发布状态 |
|---|---:|---:|---:|---|
| 2026-09-02 | 5556 | 5548 | 99.84% | completed |
| 2026-09-03 | 5556 | 5549 | 99.87% | completed |
| 2026-09-04 | 5556 | 5548 | 99.86% | completed |

三日函数结果共写入 16644 条；数据库同步日志 `daily_bars_tushare` 均为 completed，重复同步使用 UPSERT，不产生重复主键。覆盖率仍会展示，不能解释为 100% 全市场无缺口。

另验证了：

- 指数：Tushare 返回当前使用的 4 个指数。
- 市场宽度：Tushare 返回涨/跌/平、成交额、覆盖率和涨跌停统计完整性。
- K 线：`600519` 经过代码规范化后由 Tushare 返回 5 根升序 EOD 日线。
- 元数据：`600519.SH` 的当前快照由 Tushare 提供，并保留数据日期。

## 主备和边界

Tushare 合格且字段/时效满足用途时优先；以下情形才走备用：无权限、不支持、空结果、过期、覆盖不足或请求故障，并写入 `fallback_reason`。

- 实时行情、分钟线、盘口：继续使用已有实时源；Tushare EOD 不能进入实时成交路径。
- qfq/hfq：当前 Tushare 适配器只提供 raw 日线，复权请求继续走已有复权源。
- 基本面：普通接口已接入，但不能承诺每只股票、每个报告期都有完整记录。
- 龙虎榜：Tushare 接入榜单汇总；席位明细字段不足时保留 EastMoney/Vibe 备用。
- 新闻、公告、研报及部分特色事件：本次未将未经权限/口径验证的接口强行切为主源，继续沿用原适配器，并单独记录缺口。
- 资金流：`positive`、`negative`、`missing`、`invalid` 仍严格区分；missing 不自动放行买入。

## 回归验证

执行：

```text
.venv\Scripts\pytest.exe --no-cov -q --tb=short
```

结果：`708 passed in 30.67s`。

新增/更新测试覆盖 Tushare 代码规范化、金额单位、K 线排序、资金流四态、全市场覆盖率、完整批次写入、部分批次拒绝、来源优先和备用回退。

## 部署注意

生产交易进程不开 `--reload`。代码或 schema 变化应在非交易窗口部署并重启，启动时校验代码/算法/schema 版本；关键 ImportError 即时报，连续同错按现有熔断/告警策略处理。Tushare 探测和同步是只读/数据同步验证，不以强行产生买入作为验收条件。
