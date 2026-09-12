# HiThink 接入验收矩阵

## 基线记录

- 记录时间：2026-09-12（Asia/Shanghai）
- 工作区：`adaptive-investment-intelligence`
- 开工分支：`codex/pre-hithink-optimization-20260912`
- 优化前备份提交：`75759e1`
- 当前方案提交：`76e1983`
- 当前源码 HEAD：`76e1983`（日线/财务 fallback、财务指标一致性审计、canary 探针/调度、消歧与健康接口及基础设施复跑已提交）
- 远程备份：`origin/codex/pre-hithink-optimization-20260912`
- 工作区状态：已有 197 项未跟踪运行产物/临时文件；本轮未删除、未纳入 HiThink 方案提交
- 默认数据库路径：`data/sqlite/quant.db`（实际运行路径仍以用户级 `ADAPTIVE_DATABASE_URL` 为准）
- 凭据来源：用户环境/系统凭据；本文件不记录任何 API Key

## 源码基线哈希

以下 SHA-256 用于确认路由和数据源核心文件没有被无关改写：

| 文件 | SHA-256 |
| --- | --- |
| `config/settings.py` | `3790ea0b56e1d683f575363e33e0e17726fc16c0d3ce5c2f403f0423a13aecf3` |
| `src/domain/models/market_data.py` | `3e31da8058e6b9d76b5d2952303c1018261a0891a8a9392834514a08b88a893a` |
| `src/infrastructure/market_data/registry.py` | `54f6122011200f7a33323795aa5f39c3d42107b67b46db935bcd7e6381d6ea6d` |
| `src/infrastructure/market_data/source_manager.py` | `5188987f5ce6bb9bdbc69511c46d8fc188b1551a8276fb4e0df7d89fddf58318` |
| `src/infrastructure/market_data/tushare_provider.py` | `1acbf19f218d56d94a40b07d20f9296b7989059a948496ea397d13a3428ad380` |
| `src/infrastructure/market_data/remote_market_discovery.py` | `c18b0087b7d3ea090e424993bfcae01ff9765ae8f101cd07feda3f8bd8434f74` |
| `src/api/routes/market_routes.py` | `3aacfa93ca3b6d677aaaae72e4f3e27de037c5916d21c3a1169ae14463191758` |
| `src/api/routes/valuation_routes.py` | `5d1e99de43c603f74961e764f8e2adcd6393760ebb21a9d2979d668bbba36a35` |
| `src/api/routes/dragon_tiger_routes.py` | `f0120e255db77f72413fbd5ee5becff872a4febb9cbdc98c075338b709203886` |

## 现有测试与线上证据

| 能力 | 基线证据 | 结论 |
| --- | --- | --- |
| Tushare EOD、财务、资金流 | `test-reports/unit-tushare-first-20260905.md`：708 passed；三日 EOD 覆盖率 99.84%–99.87% | 保持历史/财务/资金流真值层 |
| Tushare 补齐链路 | `test-reports/unit-20260906-tushare-completion.md`：746 passed；隔离补采与回放证据完整 | 不改变既有补齐语义 |
| HiThink REST 能力 | `test-reports/unit-20260912-hithink-stability.md`：40/40 成功，P95 333–366ms | 可进入适配器与 shadow 阶段 |
| HiThink 盘中实时 | 当前验证为非交易日，快照无可证明的逐笔成交时间 | 只能 shadow，不得进入执行报价 |
| HiThink 接入后基础设施回归 | `test-reports/unit-20260912-hithink-regression-rerun.md`：272 passed | 未观察到 SourceManager、Tushare、provider resilience 或交易执行回归 |
| HiThink canary 探针契约 | `test-reports/unit-20260912-hithink-probe.md`：3 passed | 只读串行、结果脱敏、未配置安全退出；尚无交易日稳定性结论 |
| HiThink 消歧/健康接口 | `test-reports/quality-20260912-hithink-rollout.md`；相关测试 5 passed | 精确代码本地规范化；名称搜索按 rollout；健康接口仅输出脱敏统计 |
| HiThink canary 调度封装 | `test-reports/unit-20260912-hithink-canary-scheduler.md`：3 passed | 复用 APScheduler 四个工作日 checkpoint；独立串行锁，失败不阻塞策略 |
| HiThink 全量单元回归 | `test-reports/unit-20260912-hithink-full-unit.md`：851 passed | 覆盖评分、排序、Top N、交易门槛、学习链路及 HiThink 新增组件；未观察到单元级回归 |

## 分阶段状态

| 阶段 | 状态 | 证据/备注 |
| --- | --- | --- |
| Phase 0 基线与备份 | `complete` | 备份分支、源码哈希、测试摘要已记录 |
| Phase 1 能力分工与配置 | `complete` | provider manifest、设置项、主备矩阵已提交 |
| Phase 2 REST 适配器 | `complete` | 独立 client/contracts/provider 三层已提交，并由估值/龙虎榜、discovery 和 SourceManager 日线 fallback 使用 |
| Phase 3 适配器契约测试 | `complete` | `test-reports/unit-20260912-hithink-provider.md`：16 passed；仅合成响应 |
| Phase 4 低风险能力接入 | `in_progress` | 估值/龙虎榜 route、市场代码/名称消歧入口已支持 primary/shadow/fallback；涨停池、炸板池、龙虎榜 discovery 已接入 shadow，更多专用特色 API 仍待补齐 |
| Phase 5 日线/财务校验 | `in_progress` | HiThink 日线 fallback、财务三表只补缺不覆盖、EPS/ROE/ROA/同比一致性审计均已实现；修订版本、全量跨源统计仍待补齐 |
| Phase 6 交易日 canary | `in_progress` | 已提供 `scripts/probe_hithink.py`、现有 APScheduler 四个 shadow checkpoint、脱敏健康接口和离线契约测试；至少 3 个完整交易日、300 个受控样本尚未收集 |
| Phase 7 全链路回归 | `in_progress` | 全量 `tests/unit` 已完成（851 passed）；仍需在真实运行进程补集成/扩展回归并确认评分、排序、Top N、交易门槛不变 |
| Phase 8 发布/回滚 | `pending` | 未授权不重启生产、不切 active runtime |

## 不可变约束

- 不修改选股公式、技术分、AI 分、65 分资格、Top N、买卖门槛、仓位和学习规则。
- 不把 HiThink 当前快照标成实时；不在交易执行链路使用未经时间戳验证的数据。
- 不把 `null` 补成 0；不把不同复权、币种、报告期或单位的数据直接比较。
- HiThink 失败必须记录分类和 fallback reason，并沿用现有降级链。
- 任何 `primary` 晋级都必须有 capability 级样本量、延迟、完整率、一致性和回滚开关证据。

## 本阶段结论

Phase 0–3 已完成，Phase 4 已完成估值/龙虎榜路由、RemoteMarketDiscovery 特色数据入口和市场代码/名称消歧入口；Phase 5 已完成日线 fallback、财务“只补空缺、不覆盖”和财务指标一致性审计最小接入；Phase 6 已提供安全有界探针、四个现有调度 checkpoint 和脱敏健康接口，进入交易日样本收集阶段；Phase 7 已完成全量单元回归（851 passed），集成/扩展回归仍在进行。当前默认 shadow/validator：HiThink 观察写入 `provider_observations`，日线/财务只在满足开关和失败条件时进入真实 fallback，不改变候选、排序、分数、Top N 或交易门槛；下一步补齐多标的样本矩阵、全量跨源一致性摘要、更多特色 API、集成/扩展回归和 3 个完整交易日 canary。
