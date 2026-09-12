# AI Research Terminal

AI 股票研究终端 — 非 AI 选股工具。

## 快速开始

```bash
# 安装依赖
poetry install

# 复制环境变量
cp .env.example .env

# 运行测试
poetry run pytest

# 代码检查
make lint

# 启动 API (Phase 9)
make run-api
```

## 架构

参见 [docs/architecture-final-v1.0.md](docs/architecture-final-v1.0.md)

## 开发路线

- Phase 0: 基础设施 ✅
- Phase 1: Plugin Registry
- Phase 2: Market Gateway
- ...

## 工程纪律

参见 [ENGINEERING_RULES.md](ENGINEERING_RULES.md)

## Adaptive paper-trading loop

The daily AI pipeline now runs a persistent paper account with initial capital
`100000`. It scans the market, records the decisions, executes auditable
paper BUY/SELL actions, marks the portfolio, and writes a daily review to the
SQLite `learning_log`. The account has no leverage, at most five holdings, and
caps each new position at 20% of marked account value. When Codex deep analysis
is unavailable, only a separate bounded 2% exploration slot may be used after
technical and independent-market-source checks agree. It never sends orders
to a brokerage.

Useful endpoints:

- `POST /api/v1/ai-os/run-pipeline` — scan, decide, trade on paper, and record execution learning.
- `GET /api/v1/portfolio/overview` — cash, holdings, market value, P/L, and recent trades.
- `GET /api/v1/ai-os/memory/today` — today’s decisions, paper portfolio, and review entries.
- `GET /api/v1/ai-os/learning-log` — accumulated learning history across restarts.

To receive the morning brief and evening reflection in WeChat, use
[PushPlus](https://www.pushplus.plus/). After logging in and binding WeChat,
copy your token into `.env`. Set `PUSHPLUS_TOPIC` to a group code for one-to-many
delivery, or leave it empty for personal delivery:

```dotenv
PUSHPLUS_TOKEN=your-pushplus-token
PUSHPLUS_TOPIC=your-group-code
PUSHPLUS_ENDPOINT=https://www.pushplus.plus/send
```

The app sends the daily stock-selection brief and the daily reflection to your
personal WeChat or configured PushPlus group. PushPlus follows the official send API format documented
[here](https://www.pushplus.plus/doc/guide/api.html). Notifications are
best-effort: a failed request does not stop market scanning, paper trading, or
learning. `WECHAT_WEBHOOK_URL` remains supported as an enterprise fallback.
