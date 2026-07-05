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
