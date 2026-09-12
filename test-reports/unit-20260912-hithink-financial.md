# HiThink 财务补缺与报告期一致性验证

### 判定：PASS

- 命令：`.venv\\Scripts\\pytest.exe --no-cov -q tests/unit/infrastructure/test_hithink_financial.py tests/unit/infrastructure/test_hithink_source_routing.py tests/unit/infrastructure/test_hithink_provider.py --tb=short`
- 结果：22 passed
- 触发条件：只有 Tushare 多期财报请求失败后，且 `HITHINK_FINANCIAL_MODE` 为 `fallback/validator/primary` 时才请求 HiThink；`disabled/shadow` 不请求
- 合并规则：按 `statement_type + end_date` 识别缺失报告期，只插入不存在的期数；已有 Tushare 行和修订不会被 HiThink 覆盖
- 字段语义：`period_end_ms → end_date/report_date`、`report_date_ms → ann_date/f_ann_date`；合法 `null` 保留，不补零
- 存储：补缺行以 `source=hithink` 保存，读取时返回 provider、缓存状态、数据日期和 fallback reason
- 原始响应：未落盘；测试使用合成 provider 与临时内存数据库
