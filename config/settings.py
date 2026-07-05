"""全局配置定义 — pydantic-settings 类型安全配置管理"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    """应用全局配置 — 所有配置项有类型注解 + 默认值 + 描述"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ---- 运行环境 ----
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "change-me-in-production"
    APP_NAME: str = "AI Research Terminal"
    APP_VERSION: str = "0.1.0"

    # ---- 数据库 ----
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite/quant.db"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_ECHO: bool = False

    # ---- DeepSeek API ----
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_MAX_TOKENS: int = 4096
    DEEPSEEK_TEMPERATURE: float = 0.3

    # ---- OpenAI 兼容接口 ----
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # ---- 数据源 ----
    TUSHARE_TOKEN: str | None = None
    DEFAULT_DATA_SOURCE: str = "akshare"
    DATA_SYNC_INTERVAL_MINUTES: int = 5

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_DEFAULT_TTL: int = 3600

    # ---- 交易 ----
    DEFAULT_BROKER: str = "simnow"
    MAX_POSITION_PCT: float = 0.2
    MAX_INDUSTRY_PCT: float = 0.4
    DEFAULT_STOP_LOSS_PCT: float = -0.08

    # ---- API 服务 ----
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8888
    API_CORS_ORIGINS: list[str] = ["*"]

    # ---- 日志 ----
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "text"
    LOG_FILE: str = "data/logs/app.log"
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
    SCANNER_AI_DEEP_ANALYSIS_N: int = 3

    # ---- Signal Fusion ----
    SIGNAL_WEIGHTS: dict = {
        "macd": 1.0, "rsi": 0.8, "kdj": 0.7, "volume": 0.8,
        "ma": 0.7, "chip": 0.6, "lhb": 1.2, "capital": 1.5,
        "news": 0.7, "sentiment": 0.5,
    }

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
