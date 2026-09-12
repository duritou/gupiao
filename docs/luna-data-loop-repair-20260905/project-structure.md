# 本次修复涉及的文件职责

以下为修复范围目录树，不代表仓库全部文件。路径以 adaptive-investment-intelligence 为根；实施前确认当前入口和调用关系，不因计划提到文件就必须修改它。

```text
src/
  ai_os/
    candidate_evidence_enricher.py  候选取数、部分成功保留和派生字段同步
    cross_sectional_scoring.py     既有评分及资金流语义复用入口
    execution_policy.py            执行门禁消费证据
    pipeline_runner.py             阶段顺序、重评估、保存与执行衔接
    pipeline_observability.py      分阶段覆盖率与失败原因
    recommendation_quality.py      最终证据及发布条件
    market_learning.py             已有学习调整和各周期消费
  infrastructure/
    market_data/
      tushare_provider.py          SDK、接口时点、请求预算与缓存
      source_manager.py            主备选择、分接口失败和标准证据
      current_metadata_sync.py     当前及点时元数据同步
    storage/
      market_database.py           证据持久化、兼容读取及幂等回填
  explain/
    outcome_backfiller.py          到期标签及基准对齐
  api/routes/                     只修改实际消费错误字段的路由
scripts/
  daily_sync.py                    既有同步入口及历史补采
  [独立验收脚本]                   复用可用脚本；确需新增时自行命名
tests/
  unit/ai_os/                      字段语义、门禁、降级、学习测试
  unit/infrastructure/             缓存、超时、配额和数据库往返测试
  unit/explain/                    学习回填及基准测试
  integration/                     保存→重读→门禁及隔离副作用验证
test-reports/                      实测与回归结果
docs/luna-data-loop-repair-20260905/
  dev-plan.md                      主实施任务与验收标准
  project-structure.md              本文件
  code-guideline.md                 实施约束
```

并行边界：先完成字段契约，再分取数组与展示组。source_manager.py、pipeline_runner.py、market_database.py 各指定一个编辑负责人，避免并行覆盖。历史补采和学习验证依赖统一契约完成。
