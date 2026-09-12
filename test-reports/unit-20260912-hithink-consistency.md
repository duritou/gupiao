# HiThink 财务指标交叉校验

### 判定：PASS

- 命令：`.venv\\Scripts\\pytest.exe --no-cov -q tests/unit/infrastructure/test_hithink_consistency.py tests/unit/infrastructure/test_hithink_provider.py tests/unit/infrastructure/test_hithink_source_routing.py tests/unit/infrastructure/test_tushare_provider.py --tb=short`
- 结果：32 passed
- 校验字段：EPS、ROE、ROA、营收同比、净利润同比；字段缺失或合法 `null` 只计入 insufficient，不强行补值
- 输出：`match/mismatch/insufficient`、比较字段数、匹配/不匹配数、相对/绝对容差、request_id 和数据日期
- 策略安全：Tushare fundamental 原值与 sources 列表不变，HiThink 结果只挂在 `provenance.fundamental.hithink_validation`
- 失败安全：HiThink 超时/权限/业务错误只记录错误类型，不影响 Tushare 证据和现有降级链
