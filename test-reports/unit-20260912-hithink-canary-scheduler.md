### 判定：PASS

## 范围

- `src/ai_os/hithink_canary.py`：对现有探针做 scheduler-safe 封装，并支持最多 20 个标的的串行矩阵。
- `src/ai_os/scheduler.py`：声明 09:35、11:30、14:30、15:10 四个 shadow checkpoint。
- `src/api/app.py`：复用现有 APScheduler 注册 checkpoint；部署验收期间跳过，失败隔离。

## 结果

- 命令：`.venv\Scripts\pytest.exe --no-cov -q tests/unit/ai_os/test_hithink_canary.py --tb=short`
- 结果：5 passed（串行锁、未配置、错误脱敏、代码规范化、矩阵聚合）。
- 关键约束：canary 不加入策略任务依赖图；同一进程只允许一个 probe；日志仅输出状态、代码/能力计数和错误类型。

## 限制

调度注册证明不等于交易日稳定性证明。连续 3 个完整交易日、300 个样本、跨源一致性和
交易时间戳门禁仍需在凭据可见的运行进程中收集，HiThink 实时报价继续保持 shadow。
