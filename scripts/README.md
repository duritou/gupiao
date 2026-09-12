# QuantAI 自动化脚本

> 当前工作区推荐从根目录注册任务，不要使用本文旧示例中的
> `c:\vscode_code_data\jiancechengxu` 路径：
>
> ```powershell
> cd C:\vscode_code_data\investment-plugins
> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_adaptive_daily_tasks.ps1 -WhatIf
> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_adaptive_daily_tasks.ps1
> ```
>
> 注册脚本会按当前目录定位批处理脚本；每日同步会在非交易日自动跳过。

让「数据同步 / AI 学习 / ifind 监控」每天自动跑，**不依赖手动打开 VSCode 或后端服务**。

## 组件总览

| 组件 | 触发 | 跑什么 | 日志 |
|---|---|---|---|
| **QuantAI_StartService** | 登录时（启动文件夹 VBS） | 启动 uvicorn 后端服务 | `logs/uvicorn.log` |
| **QuantAI_DailySync** | 每日 16:00（schtasks） | baostock 增量同步近 3 交易日日线入库 | `logs/daily_sync.log` |
| **QuantAI_DailyVerify** | 每日 09:35（schtasks） | 跑 `verify_trading_day.py` 验证 ifind 接入 | `logs/daily_verify.log` |

> **AI 学习闭环**：服务自启后，uvicorn 内的 APScheduler 自动跑两件事——启动时数据新鲜度检查、**每日 16:05 决策结果回填（backfill）**。backfill 就是 AI「学习」（决策→等5交易日真实行情→回填→喂 Calibration）。只要服务在跑 + 数据同步着，时间到了学习就自动发生。

## 文件清单

| 文件 | 作用 |
|---|---|
| `daily_sync.py` | 独立同步日线并保存最新交易日股票元数据快照 |
| `smoke_native_data.py` | 只读探测 Sina / CNINFO / Eastmoney 原生数据源，不写入交易数据 |
| `build_historical_replay_snapshots.py` | 从本地决策日志和点时行情构建离线回放快照，不联网、不写交易库 |
| `run_shadow_gate.py` | 校验 5 个不同交易日的影子报告是否可进入晋级复核 |
| `record_shadow_report.py` | 校验同日 baseline/candidate 文件并保存不可执行的影子报告 |
| `auto_start_service.bat` | 启动 uvicorn（含 8888 端口占用检查 + 日志重定向） |
| `auto_daily_sync.bat` | 包裹 daily_sync.py |
| `auto_daily_verify.bat` | 包裹 verify_trading_day.py |

启动文件夹还有个 `QuantAI_StartService.vbs`（隐藏启动 bat）。

### 原生数据源只读探测

用于排查公开数据源是否可用，不会写入行情库、纸面账户或交易日志：

```cmd
<venv_python> scripts\smoke_native_data.py --code 600519 --trade-date 2026-08-28
```

加 `--strict` 时，任一选定数据源不可用会返回退出码 1，适合接入外部监控。

### HiThink 有界 canary 探测

`probe_hithink.py` 按 capability 串行发起只读请求，只输出脱敏的成功率、行数、
数据日期、延迟、request id 和运行计数；不会保存响应原文、请求头或 API Key：

```cmd
<venv_python> scripts\probe_hithink.py --code 600519.SH --capability snapshot --capability valuation --output reports\hithink-probe.json
```

未配置 HiThink 凭据时返回退出码 2；单项失败不会阻止其他 capability 继续探测。
探测结果只能作为 canary 观测，未满足验收矩阵中的连续交易日、样本量和跨源一致性
门禁前，不得据此把盘中报价切换为主数据源。

服务启动后，现有 APScheduler 会在工作日 09:35、11:30、14:30、15:10 注册同一
探针的 shadow checkpoint；默认按 `HITHINK_CANARY_CODES`（最多 20 个代码）依次
覆盖沪深北样本，探针使用独立串行锁，失败只写日志和 provider 统计，不会阻塞策略
阶段或纸面交易。单进程连续运行 3 个完整交易日后，健康接口中的 capability 计数
可作为晋级门禁的样本基础；仍需额外完成跨源一致性与数据时间语义核验。

### 构建历史回放快照

先从本地决策日志和 `market_daily` 生成两个策略的同日快照，再交给历史门禁：

```cmd
<venv_python> scripts\build_historical_replay_snapshots.py reports\historical-replay-snapshots.json
<venv_python> scripts\run_historical_gate.py reports\historical-replay-snapshots.json
```

该流程默认使用 `technical-v1` 与 `balanced-v2`，不能代表尚未完成历史记录的
`2.2.0-evidence-routing`；元数据覆盖不足时门禁会保持阻断。

### 验证单日完整闭环

使用冻结的交易日清单验证“凌晨计划 → 开盘卖出/买入 → 盘中检查 → 收盘 → 学习回填
→ 晚间复盘”的阶段顺序、数据因果性和降级交易规则。该命令只读清单，不联网、不写入
正式纸面账本：

```cmd
<venv_python> scripts\replay_trading_day.py tests\fixtures\trading_days\2026-09-01\manifest.json --output test-reports\trading-cycle-replay-20260901.json
```

清单是合成的接口契约，不是收益证据；真实收益验证仍需使用连续积累的冻结行情和实际
决策记录。

### 影子运行门禁

影子报告必须标记为不可执行，且至少覆盖 5 个不同交易日；有方向、证据或候选差异
时，先补充人工复核标记 `review_status=reviewed`：

```cmd
<venv_python> scripts\run_shadow_gate.py --from-db
<venv_python> scripts\run_shadow_gate.py reports\shadow-reports.json
```

写入一日影子报告（两个输入文件必须声明同一个交易日）：

```cmd
<venv_python> scripts\record_shadow_report.py 2026-09-01 baseline.json candidate.json --baseline-version 2.1 --candidate-version 2.2.0-evidence-routing
```

输入文件可以是决策数组，也可以是 `{"trade_date": "...", "decisions": [...]}`；脚本只
保存差异报告，不会调用纸面成交接口。

---

## 安装（新机器/重装时配置）

**前置**：3 个 `.bat` 里的 `PYTHON=` 必须指向本机 poetry venv 的 python.exe。查路径：
```cmd
poetry env info --path
:: 输出拼接 \Scripts\python.exe 即可
```

### 1. 注册两个 schtasks 任务（CMD 或 PowerShell）
```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File C:\vscode_code_data\investment-plugins\scripts\register_adaptive_daily_tasks.ps1
```

### 2. 配置服务自启（启动文件夹 VBS，不需要管理员）
PowerShell 跑：
```powershell
$startup = [Environment]::GetFolderPath('Startup')
$vbs = @'
Set ws = CreateObject("WScript.Shell")
ws.Run "cmd /c C:\vscode_code_data\investment-plugins\adaptive-investment-intelligence\scripts\auto_start_service.bat", 0, False
'@
Set-Content -Path "$startup\QuantAI_StartService.vbs" -Value $vbs -Encoding ASCII
```

> **为什么不用 `schtasks /sc onlogon`？** 它要管理员权限。启动文件夹 VBS 效果一样（登录自动跑），普通权限即可，且隐藏无弹窗。

---

## 日常运维

### 查看任务状态
```cmd
schtasks /query /tn "QuantAI_DailySync" /v /fo list
```

### 手动立即触发一次（不等到点）
```cmd
schtasks /run /tn "QuantAI_DailySync"      :: 立即同步
schtasks /run /tn "QuantAI_DailyVerify"    :: 立即验证 ifind
```
StartService（VBS）：双击启动文件夹里的 `QuantAI_StartService.vbs`（路径：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`）。

### 改触发时间
schtasks 改时间最稳是**重建**（`/f` 覆盖）：
```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File C:\vscode_code_data\investment-plugins\scripts\register_adaptive_daily_tasks.ps1 -SyncAt 15:30
```

### 查日志
```cmd
type logs\daily_sync.log      :: 数据同步
type logs\daily_verify.log    :: ifind 验证
type logs\uvicorn.log         :: 后端服务
```

---

## 卸载
```cmd
schtasks /delete /tn "QuantAI_DailySync" /f
schtasks /delete /tn "QuantAI_DailyVerify" /f
```
删服务自启：删启动文件夹里的 `QuantAI_StartService.vbs`。

---

## 排错

**任务到点没跑** → schtasks 到点时电脑关机/休眠就错过。打开「任务计划程序」GUI → 找到任务 → **设置**页 → 勾「如果错过了计划启动时间，尽快启动任务」。命令行设不了，必须 GUI 点。

**DailySync 全量很慢** → `codes=None` 是全 A 股 ≈5000 只，约 20-30 分钟。想加速可改 `daily_sync.py` 的 `DAYS_BACK`，或把 `codes=None` 改成只同步关注股票列表。

**历史回放仍提示元数据不足** → 旧日期不会用当前 `stock_basic` 伪造。DailySync 从本次改动起会在日线同步后保存最新交易日的股票状态快照；需连续积累真实快照后，新的交易日才可用于严格点时回放。

**服务自启和 VSCode 扩展抢 8888 端口** → `auto_start_service.bat` 有端口检查（占用就跳过），先起先得。想让扩展管服务，就别让 VBS 自启的占着（删 VBS 或停掉那个 uvicorn）。

**换电脑 / 重装 venv** → 批处理会优先使用当前项目的 `.venv`，无需维护硬编码 Poetry 路径；迁移后重新运行根目录的任务注册脚本，并按新路径重新生成 VBS 即可。

**backfill（AI 学习）一直没发生** → 见 `src/explain/outcome_backfiller.py`。需要两个条件都满足：① 决策满 9 自然日 ② 决策后 5 个交易日行情齐。服务自启 + DailySync 保证数据和回填自动跑，时间到了（决策后约 7 个交易日）自然开始学习。查进度：`GET /api/v1/decision/backfill/status` 看 `verified` 是否增长。
