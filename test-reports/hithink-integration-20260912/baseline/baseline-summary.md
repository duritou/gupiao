# HiThink 接入基线摘要

- 记录时间：2026-09-12（Asia/Shanghai）
- 代码分支：`codex/pre-hithink-optimization-20260912`
- 源码 HEAD：`6d9c6b33a74b7d216d4770e76ef891a1377e4781`
- 备份提交：`75759e1`
- 数据库：默认 `data/sqlite/quant.db`；实际运行可由用户级 `ADAPTIVE_DATABASE_URL` 指定
- 配置：Tushare/HiThink 凭据均只从运行环境或系统凭据读取，本报告不保存 Key

## 既有路由摘要

| 路由/组件 | 当前定位 |
| --- | --- |
| `TushareProvider` | EOD 日线、财务三表/指标、资金流、指数、元数据 |
| `SourceManager` | 缓存、来源优先级、降级、provenance 和实时执行安全检查 |
| `RemoteMarketDiscovery` | 同花顺/腾讯/东方财富等远程候选发现与固定评分计算 |
| `valuation_routes.py` | 估值查询及来源元数据 |
| `dragon_tiger_routes.py` | 龙虎榜查询及日期语义 |
| `market_routes.py` | 行情、指数、市场宽度、来源注册状态 |

## 已有基线结果

- Tushare 全量回归：708 passed（2026-09-05）；补齐回归：746 passed（2026-09-06）。
- Tushare 最近完整交易日 EOD 全市场覆盖率：99.84%–99.87%。
- HiThink 短时稳定性：5 类能力共 40 次串行授权请求，40/40 成功，P95 333–366ms。
- HiThink 当前验证为非交易日；不能从快照证明交易所实时成交时间。

## 采集与脱敏规则

- 只保存状态码、错误分类、延迟、行数、日期窗口、字段完整率和内容哈希。
- 不保存请求头、URL 中的凭据、完整响应、数据库副本或全市场原始数据。
- 线上样本与 CI 合成夹具分离；无 Key 的 CI 不得使用假数据冒充线上成功。
