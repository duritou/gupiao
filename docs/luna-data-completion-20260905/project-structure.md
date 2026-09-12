# 本轮文件职责

以下是本轮完整范围树，非仓库全量目录。现有文件先确认调用关系再改，新文件仅在无法复用已有实现时创建。

```text
adaptive-investment-intelligence/
├─ src/
│  ├─ infrastructure/
│  │  ├─ market_data/
│  │  │  ├─ tushare_provider.py           端点、分页、多期/历史请求与日期口径
│  │  │  ├─ tushare_request_budget.py     必要时新增：跨进程共用预算
│  │  │  ├─ current_metadata_sync.py      股票清单与当期元数据同步
│  │  │  └─ source_manager.py             主备、部分成功和统一证据接口
│  │  └─ storage/
│  │     └─ market_database.py            幂等保存、版本、日期和兼容迁移
│  ├─ ai_os/
│  │  ├─ candidate_evidence_enricher.py   原有队列的补齐与状态投影
│  │  └─ pipeline_runner.py               同步后消费与分阶段可观测性
│  ├─ agents/
│  │  └─ codex_stock_analyzer.py          多期财报与资金历史的真实研究输入
│  └─ api/routes/                        仅修改实际消费上述数据的现有路由
├─ scripts/
│  ├─ daily_sync.py                      既有增量同步入口
│  ├─ audit_data_completion.py           新增：只读覆盖/差集审计
│  ├─ backfill_research_data.py           新增：分批断点补采与显式目标DB
│  └─ run_isolated_acceptance.py          复用：完整研究链隔离验收
├─ tests/
│  ├─ unit/                             就近补充解析、日期、缓存测试
│  └─ integration/
│     ├─ test_tushare_shared_budget.py   跨进程并发/取消/限流
│     ├─ test_history_completion.py      股票映射及K线因子覆盖
│     ├─ test_financial_history.py       多期财报和点时防泄漏
│     └─ test_candidate_flow_completion.py 资金流补齐及消费一致性
├─ test-reports/data-completion-20260905/
│  ├─ baseline.json                      本轮冻结基线与分母
│  ├─ acceptance.json                    可机器核验的结果与原因清单
│  └─ acceptance.md                      前后对照、部署状态、剩余问题
└─ docs/luna-data-completion-20260905/
   ├─ dev-plan.md                        顺序、硬约束、验收标准
   ├─ project-structure.md               文件职责和编辑边界
   └─ code-guideline.md                  编码、存储和验证规范
```

并行编辑约束：tushare_provider.py、source_manager.py、market_database.py分别单一负责人，C/D/E共享修改串行合并。避免为了分工复制SDK实例、预算器、行情缓存和资金流判定器。
