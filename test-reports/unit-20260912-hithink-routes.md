### 判定：PASS

# HiThink 路由级主备测试

- 日期：2026-09-12（Asia/Shanghai）
- 命令：`.venv\\Scripts\\pytest.exe --no-cov -q tests/unit/api/test_hithink_routes.py tests/unit/api/test_native_route_failover.py tests/unit/api/test_operational_routes.py -k "valuation or dragon_tiger or native_adapter_exception" --tb=short`
- 结果：10 passed，31 deselected
- 结论：估值/龙虎榜支持 primary、shadow、fallback 三种模式；shadow 保持原 Tushare/东方财富/Vibe 返回，primary 成功时不调用旧链路，fallback 仅在旧链路无数据时尝试 HiThink
- 约束：不改变选股评分、排序、Top N、交易门槛；未调用线上 HiThink
