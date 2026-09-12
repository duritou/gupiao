# HiThink Discovery Shadow/Primary 单元验证

### 判定：PASS

- 命令：`.venv\\Scripts\\pytest.exe --no-cov -q tests/unit/infrastructure/test_hithink_discovery.py tests/unit/infrastructure/test_remote_market_learning.py -k "hithink or discovery_skips_eastmoney_hot_rank or normalize_a_share_code" --tb=short`
- 结果：6 passed，14 deselected
- 覆盖：特色数据字段投影、代码规范化、请求标识脱敏、shadow 不改变候选/评分、primary 使用既有评分管线、shadow 失败不污染主错误列表
- 设计约束：默认 `HITHINK_SPECIAL_MODE=shadow`；shadow/validator 只保存 `provider_observations`，不改变候选、排序、分数、Top N 或交易门槛
- 失败处理：HiThink 失败只记录错误类型；primary/fallback 由现有发现链继续处理，不返回模拟数据
- 原始响应：未落盘；测试仅使用合成 payload
