# HiThink SourceManager 日线路由验证

### 判定：PASS

- 命令：`.venv\\Scripts\\pytest.exe --no-cov -q tests/unit/infrastructure/test_hithink_source_routing.py tests/unit/infrastructure/test_hithink_discovery.py tests/unit/infrastructure/test_hithink_provider.py --tb=short`
- 结果：22 passed
- 路由：HiThink 仅声明 `daily_kline`，不进入实时行情路由；默认未配置时不会被尝试
- 数据语义：HiThink 日线统一标记 `is_live=False`，保留 `data_date`、endpoint、coverage_ratio 和 provider provenance
- 优先级：现有本地缓存和 Tushare 日线优先保持不变；HiThink 仅作为配置允许时的真实 fallback
- 失败处理：空数据、超时、业务错误记录到 provider metrics 并返回可继续降级的 `DataProvenance`
- 原始响应：未落盘；测试使用合成 provider
