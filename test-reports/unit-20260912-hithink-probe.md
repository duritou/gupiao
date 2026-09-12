### 判定：PASS

## 范围

- 对象：`scripts/probe_hithink.py` 只读、有界、脱敏 canary 探测器。
- 测试：`.venv\Scripts\pytest.exe --no-cov -q tests/unit/scripts/test_probe_hithink.py --tb=short`。
- 结果：3 passed（2026-09-12，Windows/Python 3.10.11）。
- 联合回归：探针、适配器、discovery、财务、SourceManager、一致性和 API 路由共 39 passed。

## 已验证行为

- capability 请求串行执行，单项失败不会阻止其他能力继续探测。
- 输出只保留状态、行数、数据日期、`is_live`、延迟和截断后的 request id；测试确认异常消息中的敏感片段不会被回显。
- 未配置凭据时安全返回 `not_configured`，不发起远程请求。
- 支持快照、估值、日线、财务指标、涨停池、炸板池和龙虎榜的 bounded probe 入口。

## 限制

本报告是离线契约测试，不代表交易日实时稳定性。连续 3 个完整交易日、至少 300 个样本、
跨源一致性和时间戳门禁仍需通过后续 canary 运行收集，期间 HiThink 实时能力保持 shadow。
