# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python backend plus a VS Code extension. Core Python code lives in `src/`: `api/` for FastAPI routes, `domain/` for models/events, `infrastructure/` for adapters/storage, and feature modules such as `agents/`, `signals/`, `scanner/`, `backtest/`, `knowledge/`, and `ai_os/`. Tests live in `tests/`, with unit tests under `tests/unit/` and fixtures in `tests/fixtures/`. Configuration and provider manifests are in `config/`, `providers/`, and `plugins/`. Documentation is in `docs/`. Extension source is in `vscode-ext/src/`; generated JavaScript is in `vscode-ext/out/`.

## Build, Test, and Development Commands

- `poetry install`: install Python dependencies.
- `make test`: run the pytest suite with coverage settings from `pyproject.toml`.
- `make test-cov`: run tests and write an HTML coverage report to `htmlcov/`.
- `make lint`: run `ruff check src tests` and strict `mypy src`.
- `make format`: format Python code with Ruff.
- `make run-api`: start the FastAPI app at `http://127.0.0.1:8888`.
- `cd vscode-ext && npm install`: install VS Code extension dependencies.
- `cd vscode-ext && npm run compile`: compile TypeScript into `vscode-ext/out/`.

## Coding Style & Naming Conventions

Use Python 3.10+, 4-space indentation, LF endings, and 100-character lines. Ruff handles linting/import order; mypy runs in strict mode, so public functions should be typed. Use `snake_case` for Python modules, functions, and variables; `PascalCase` for classes. YAML files use 2-space indentation. Keep TypeScript source in `vscode-ext/src/` and compiled output in `vscode-ext/out/`.

## Testing Guidelines

Pytest is the test framework, with `pytest-asyncio` enabled automatically. Name tests `test_*.py` and mirror the source area, for example `tests/unit/signals/test_signals.py`. Prefer focused unit tests for engines, adapters, and routes. Add fixtures under `tests/fixtures/` when data or plugins are reused. Run `make test` before submitting changes; use `make test-cov` when touching shared infrastructure or domain logic.

## Commit & Pull Request Guidelines

Recent commits use concise Conventional Commit subjects, usually `feat: ...` with version or feature context. Keep subjects imperative and scoped, for example `fix: validate plugin manifest paths`. Pull requests should include a short description, testing performed, linked issues or design notes, and screenshots for VS Code UI changes. Call out migrations, new provider credentials, or changes to `.env.example`.

## Security & Configuration Tips

Do not commit secrets or private keys. Copy `.env.example` to `.env` for local configuration and keep provider credentials local. When adding data providers or plugins, include safe sample manifests and tests rather than real credentials.
