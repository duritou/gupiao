.PHONY: help install dev-install test lint format typecheck clean docs

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖
	poetry install --no-dev

dev-install: ## 安装开发依赖
	poetry install

test: ## 运行测试
	poetry run pytest

test-cov: ## 运行测试 + 覆盖率报告
	poetry run pytest --cov=src --cov-report=html

lint: ## 代码检查
	poetry run ruff check src tests
	poetry run mypy src

format: ## 代码格式化
	poetry run ruff format src tests

typecheck: ## 类型检查
	poetry run mypy src

clean: ## 清理构建产物
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage .coverage.* dist/ build/

init-db: ## 初始化数据库
	poetry run python scripts/init_database.py

sync-data: ## 同步行情数据
	poetry run python scripts/sync_market_data.py

run-api: ## 启动 API 服务
	poetry run uvicorn src.api.app:app --host 127.0.0.1 --port 8888 --reload

docs: ## 查看架构文档
	@echo "架构文档: docs/architecture-final-v1.0.md"
