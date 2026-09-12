"""全局配置定义 — pydantic-settings 类型安全配置管理"""

import sys
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHARED_PYTHON = _PROJECT_ROOT.parent / "shared" / "python"
if str(_SHARED_PYTHON) not in sys.path:
    sys.path.insert(0, str(_SHARED_PYTHON))

from investment_common import load_runtime_env, runtime_value  # noqa: E402

load_runtime_env(_PROJECT_ROOT)


class Settings(BaseSettings):
    """应用全局配置 — 所有配置项有类型注解 + 默认值 + 描述"""

    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT / ".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 运行环境 ----
    APP_ENV: Literal["development", "staging", "production"] = "production"
    APP_DEBUG: bool = False
    APP_SECRET_KEY: str = "change-me-in-production"
    APP_NAME: str = "Adaptive Investment Intelligence Platform"
    APP_VERSION: str = "6.0.0"

    # ---- 数据库 ----
    DATABASE_URL: str = runtime_value(
        "ADAPTIVE_DATABASE_URL", "sqlite+aiosqlite:///./data/sqlite/quant.db"
    )
    DATABASE_POOL_SIZE: int = 5
    DATABASE_ECHO: bool = False

    # ---- AI routing ----
    AI_PRIMARY_PROVIDER: Literal["deepseek", "codex_cli"] = "codex_cli"
    AI_REVIEW_PROVIDER: Literal["deepseek", "codex_cli"] = "codex_cli"
    CODEX_MODEL: str = "gpt-5.6-terra"
    CODEX_CLI_PATH: str = "codex"
    CODEX_REASONING_EFFORT: Literal["minimal", "low", "medium", "high"] = "low"
    CODEX_TIMEOUT_SECONDS: float = 120.0
    CODEX_MAX_OUTPUT_TOKENS: int = 2000
    CODEX_ANALYSIS_MAX_CONCURRENCY: int = 2

    # Legacy manual provider settings. The scheduled closed loop is Codex-only.
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = runtime_value("DEEPSEEK_MODEL", "deepseek-v4-flash")
    DEEPSEEK_MAX_TOKENS: int = 4096
    DEEPSEEK_TEMPERATURE: float = 0.3
    # 网络抖动、Windows 安全软件短暂拦截或服务端瞬时断开时，AI 请求应
    # 自动重试，而不是把整轮复盘降级成无 AI 结果。
    AI_NETWORK_RETRY_ATTEMPTS: int = 3
    AI_NETWORK_RETRY_BACKOFF_SECONDS: float = 1.0

    # ---- OpenAI 兼容接口 ----
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # ---- 数据源 ----
    TUSHARE_TOKEN: str | None = None
    TUSHARE_BUDGET_DB_PATH: str = runtime_value(
        "TUSHARE_BUDGET_DB_PATH", "data/tushare_request_budget.db"
    )
    TUSHARE_BUDGET_PER_MINUTE: int = 190
    TUSHARE_BUDGET_PER_DAY: int = 95000
    TUSHARE_REQUEST_RETRY_ATTEMPTS: int = 3
    TUSHARE_REQUEST_TIMEOUT_SECONDS: float = 30.0
    DATA_COMPLETION_REQUIRED_BARS: int = 250
    DATA_COMPLETION_FINANCIAL_PERIODS: int = 8
    DATA_COMPLETION_FLOW_DAYS: int = 20
    DATA_COMPLETION_FLOW_BATCH_ENABLED: bool = True
    DATA_COMPLETION_FLOW_BATCH_CODE_CHUNK: int = 100
    DATA_COMPLETION_FLOW_BATCH_MAX_REQUESTS: int = 80
    DATA_COMPLETION_FLOW_BATCH_DEADLINE_SECONDS: float = 180.0
    DEFAULT_DATA_SOURCE: str = "akshare"
    DATA_SYNC_INTERVAL_MINUTES: int = 5
    # HiThink Financial API (fuyao.aicubes.cn).  Credentials are read only
    # from the user environment; never persist them in application state.
    HITHINK_FINANCE_API_KEY: str | None = None
    HITHINK_BASE_URL: str = "https://fuyao.aicubes.cn"
    HITHINK_TIMEOUT_SECONDS: float = 8.0
    HITHINK_RETRY_ATTEMPTS: int = 2
    HITHINK_MIN_INTERVAL_SECONDS: float = 0.25
    HITHINK_FAILURE_THRESHOLD: int = 3
    HITHINK_COOLDOWN_SECONDS: float = 60.0
    HITHINK_SYMBOL_MODE: Literal["disabled", "shadow", "fallback", "validator", "primary"] = "shadow"
    HITHINK_VALUATION_MODE: Literal["disabled", "shadow", "fallback", "validator", "primary"] = "shadow"
    HITHINK_SPECIAL_MODE: Literal["disabled", "shadow", "fallback", "validator", "primary"] = "shadow"
    HITHINK_DAILY_MODE: Literal["disabled", "shadow", "fallback", "validator", "primary"] = "validator"
    HITHINK_FINANCIAL_MODE: Literal["disabled", "shadow", "fallback", "validator", "primary"] = "validator"
    HITHINK_REALTIME_MODE: Literal["disabled", "shadow", "fallback", "validator", "primary"] = "shadow"
    # Optional authenticated primary for real-time quotes and daily K-lines.
    # The key remains local in .env and is never persisted in decisions.
    TICKFLOW_API_KEY: str | None = None
    TICKFLOW_BASE_URL: str = "https://api.tickflow.org"
    TICKFLOW_TIMEOUT_SECONDS: float = 10.0

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_DEFAULT_TTL: int = 3600

    # ---- 交易 ----
    DEFAULT_BROKER: str = "simnow"
    # Hard-capped again inside the execution engine so no entry path can
    # accidentally restore the legacy 20% position size.
    MAX_POSITION_PCT: float = 0.20
    MAX_INDUSTRY_PCT: float = 0.4
    DEFAULT_STOP_LOSS_PCT: float = -0.08

    # ---- API 服务 ----
    API_HOST: str = runtime_value("ADAPTIVE_API_HOST", "127.0.0.1")
    API_PORT: int = int(runtime_value("ADAPTIVE_API_PORT", "8888"))
    API_CORS_ORIGINS: list[str] = ["*"]

    # ---- 日志 ----
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "text"
    LOG_FILE: str = runtime_value("ADAPTIVE_LOG_FILE", "data/logs/app.log")
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "30 days"

    # ---- IPC (VS Code 插件通信) ----
    IPC_SOCKET_PATH: str = r"\\.\pipe\quantai"

    # ---- 通知 ----
    NOTIFICATION_ENABLED: bool = True
    EMAIL_SMTP_HOST: str | None = None
    EMAIL_SMTP_PORT: int = 587
    EMAIL_USERNAME: str | None = None
    EMAIL_PASSWORD: str | None = None
    PUSHPLUS_TOKEN: str | None = None
    PUSHPLUS_TOPIC: str | None = None
    PUSHPLUS_ENDPOINT: str = "https://www.pushplus.plus/send"
    WECHAT_WEBHOOK_URL: str | None = None

    # ---- Event Bus ----
    EVENT_BUS_BACKEND: str = "memory"
    EVENT_BUS_MAX_QUEUE_SIZE: int = 10000

    # ---- Metrics ----
    METRICS_ENABLED: bool = True
    METRICS_BACKEND: str = "memory"

    # ---- Plugin Registry ----
    PLUGIN_ENABLED: bool = True
    PLUGIN_DIRS: list[str] = ["plugins/datasource", "plugins/signal"]
    PLUGIN_AUTO_DISCOVER: bool = True
    PLUGIN_MINIMUM_CORE: str = "1.0.0"

    # ---- Scanner ----
    SCANNER_MIN_MARKET_CAP: float = 20.0
    SCANNER_MIN_DAILY_VOLUME: float = 50.0
    SCANNER_EXCLUDE_ST: bool = True
    SCANNER_EXCLUDE_NEW_IPO_DAYS: int = 60
    SCANNER_FILTER_TARGET_COUNT: int = 100
    SCANNER_SCORE_TOP_N: int = 20
    # The broad pass is deterministic. Only the shortlist enters an LLM
    # stage, which keeps the 6k-stock scan affordable and auditable.
    SCANNER_FULL_UNIVERSE_COUNT: int = 6000
    SCANNER_TECHNICAL_SHORTLIST_COUNT: int = 300
    SCANNER_AI_PRESELECT_COUNT: int = 20
    SCANNER_AI_DEEP_ANALYSIS_N: int = 5
    # The first deep-analysis batch stays at five.  A bounded same-session
    # continuation can inspect more of the existing preselection queue when
    # the first batch produces no executable approval.
    SCANNER_AI_DEEP_ANALYSIS_MORNING_MAX: int = 10
    SCANNER_AI_DEEP_ANALYSIS_MIDDAY_MAX: int = 5
    SCANNER_AI_DEEP_ANALYSIS_DAILY_MAX: int = 15
    SCANNER_AI_DEEP_ANALYSIS_DEADLINE_SECONDS: float = 480.0
    SCANNER_EVIDENCE_ENRICHMENT_COUNT: int = 80
    SCANNER_EVIDENCE_ENRICHMENT_CONCURRENCY: int = 4
    SCANNER_EVIDENCE_ENRICHMENT_TIMEOUT_SECONDS: float = 30.0
    REMOTE_MARKET_DISCOVERY_ENABLED: bool = True
    REMOTE_MARKET_CANDIDATE_LIMIT: int = 300
    REMOTE_MARKET_TIMEOUT_SECONDS: float = 12.0
    REMOTE_MARKET_RETRY_ATTEMPTS: int = 3
    REMOTE_MARKET_RETRY_BACKOFF_SECONDS: float = 0.6
    REMOTE_MARKET_RETRY_JITTER_SECONDS: float = 0.4
    REMOTE_MARKET_RETRY_MAX_BACKOFF_SECONDS: float = 8.0
    REMOTE_MARKET_RETRY_AFTER_MAX_SECONDS: float = 900.0
    PUBLIC_DATA_MIN_INTERVAL_SECONDS: float = 0.25
    PUBLIC_DATA_JITTER_SECONDS: float = 0.15
    PUBLIC_DATA_FAILURE_THRESHOLD: int = 3
    PUBLIC_DATA_COOLDOWN_SECONDS: float = 60.0
    # Eastmoney is a secondary public source with stricter traffic controls.
    # Keep requests serial and slow, then switch to other providers on a clear
    # rate-control signal instead of repeatedly hitting the endpoint.
    EASTMONEY_MIN_INTERVAL_SECONDS: float = 1.5
    EASTMONEY_JITTER_SECONDS: float = 0.5
    EASTMONEY_FAILURE_THRESHOLD: int = 2
    EASTMONEY_COOLDOWN_SECONDS: float = 900.0
    REMOTE_MARKET_LOCAL_FALLBACK_COUNT: int = 6000
    # Execution quotes may need several polls before the provider's exchange
    # timestamp moves strictly past the final signal.
    PAPER_EXECUTION_QUOTE_ATTEMPTS: int = 8
    PAPER_EXECUTION_QUOTE_RETRY_DELAY_SECONDS: float = 1.25
    # Flow-missing exploration is an execution-layer fallback only. It never
    # changes scanner scores, ranking, or the normal buy gate.
    PAPER_EXPLORATION_ENABLED: bool = True
    LIVE_EXPLORATION_ENABLED: bool = False
    PAPER_EXPLORATION_POSITION_PCT: float = 0.02
    PAPER_EXPLORATION_MAX_POSITION_PCT: float = 0.03
    PAPER_EXPLORATION_MAX_TOTAL_PCT: float = 0.05
    PAPER_EXPLORATION_MAX_ENTRIES: int = 1
    PAPER_EXPLORATION_CONFIRMATION_DAYS: int = 3
    PAPER_EXPLORATION_MAX_HOLDING_DAYS: int = 5
    PAPER_EXPLORATION_STOP_LOSS_PCT: float = 4.0
    PAPER_LIVENESS_ALERT_DAYS: int = 5
    PAPER_LIVENESS_MIN_CASH_PCT: float = 0.70
    # The local a-stock-data skill is an evidence/provider fallback only. It
    # never owns the Dashboard ledger or bypasses quote freshness checks.
    STOCK_SKILL_BRIDGE_ENABLED: bool = True
    STOCK_SKILL_MAX_QUOTE_COUNT: int = 300

    # ---- Signal Fusion ----
    SIGNAL_WEIGHTS: dict = {
        "macd": 1.0, "rsi": 0.8, "kdj": 0.7, "volume": 0.8,
        "ma": 0.7, "chip": 0.6, "lhb": 1.2, "capital": 1.5,
        "news": 0.7, "sentiment": 0.5,
    }
    CROSS_SECTIONAL_RANK_WEIGHT: float = 0.70
    SELECTION_TECHNICAL_WEIGHT: float = 0.70
    SELECTION_DISCOVERY_WEIGHT: float = 0.20
    SELECTION_LEARNING_WEIGHT: float = 0.10

    # ---- AI Agent ----
    AGENT_ENABLED: bool = True
    AGENT_DEFAULT_MODE: str = "pipeline"
    AGENT_MAX_REVIEW_RETRIES: int = 2
    AGENT_RESEARCH_TIMEOUT_SECONDS: int = 300
    AI_DAILY_TOKEN_BUDGET: int = 10000
    AI_MAX_TOKENS_PER_REQUEST: int = 2000

    # ---- Research Pipeline ----
    RESEARCH_PIPELINE_ENABLED: bool = True
    RESEARCH_PIPELINE_TRIGGER_TIME: str = "15:30"

    # ---- Knowledge ----
    KNOWLEDGE_HOT_RELOAD: bool = True
    KNOWLEDGE_WATCH_INTERVAL: float = 2.0

    # ---- Prompt Registry ----
    PROMPT_REGISTRY_CACHE_SIZE: int = 100
    PROMPT_HOT_RELOAD: bool = True

    # ---- Research Memory ----
    RESEARCH_MEMORY_ENABLED: bool = True
    RESEARCH_MEMORY_DECAY_DAYS: int = 90


# 全局单例
settings = Settings()
