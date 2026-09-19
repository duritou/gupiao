"""Local Market Database — v7.5 Data Foundation.

SQLite-based local data warehouse. Sync once daily from baostock.
AI queries local DB — no network, no API rate limits, no anti-scraping.

Tables:
  stock_basic      — stock code, name, industry
  market_daily     — OHLCV per stock per day
  indicator_daily  — pre-computed MACD/RSI/KDJ/MA/Volume signals
  sync_log         — sync history for incremental updates

After initial sync: Scanner 5000 stocks in <2s (SQL vs 30s API).
Replay: SELECT date range instead of re-fetching from API.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date as dt_date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.ai_os.numeric_policy import finite_or
from src.explain.benchmark import BenchmarkBasis, equal_weight_return
from src.ai_os.price_limit_policy import (
    at_limit_down,
    at_limit_up,
    price_limit_pct,
    resolve_change_pct,
)
from src.ai_os.causal_execution import (
    CHINA_TZ,
    in_a_share_session,
    parse_timestamp,
    validate_post_signal_quote,
)
from src.ai_os.execution_policy import (
    ExecutionTier,
    evaluate_entry_execution,
    flow_execution_metadata,
    is_flow_probe_candidate,
    is_probe_promotion_candidate,
    probe_exit_reason,
)
from src.ai_os.trading_costs import (
    COMMISSION_RATE,
    FEE_POLICY,
    quantize_price,
    STAMP_TAX_RATE,
    calculate_trade_costs,
)
from src.ai_os.trading_policy import (
    PAPER_MAX_POSITION_PCT,
    PAPER_MAX_POSITIONS,
    PAPER_MIN_CASH_RESERVE_PCT,
    PAPER_MOMENTUM_PROBE_MAX_ENTRIES,
    PAPER_MOMENTUM_PROBE_POSITION_PCT,
    bounded_position_cap,
    conditional_probe_rejection_reason,
    decision_direction,
    deep_buy_rejection_reason,
    is_buy_signal,
    is_conditional_probe_candidate,
    is_deep_buy_approved,
    is_momentum_probe_candidate,
    momentum_probe_rank,
    momentum_probe_rejection_reason,
    position_exit_reason,
)
from src.ai_os.universe_policy import projected_industry_exposure

DB_PATH = Path(os.environ.get("ADAPTIVE_MARKET_DB_PATH") or Path(__file__).parent / "market_data.db")
DB_SCHEMA_VERSION = 6


def _is_a_share_stock_code(code: str) -> bool:
    """Exclude indices, funds, bonds and other exchange-listed instruments."""
    if code.endswith(".SH"):
        return code[:3] in {"600", "601", "603", "605", "688", "689"}
    if code.endswith(".SZ"):
        return code[:3] in {"000", "001", "002", "003", "300", "301"}
    return False


def _trading_days_held(
    connection: sqlite3.Connection,
    entry_date: str,
    trade_date: str,
) -> int:
    """Count completed market days after entry using the local calendar data."""
    if not entry_date or not trade_date or trade_date <= entry_date:
        return 0
    row = connection.execute(
        """SELECT COUNT(DISTINCT trade_date) AS days
           FROM market_daily
           WHERE trade_date > ? AND trade_date <= ?""",
        (entry_date, trade_date),
    ).fetchone()
    return int(row["days"] or 0)


def _future_trading_date(
    connection: sqlite3.Connection,
    entry_date: str,
    days: int,
) -> str:
    """Return a persisted calendar deadline when local bars are available."""
    if not entry_date or days <= 0:
        return ""
    row = connection.execute(
        """SELECT trade_date FROM market_daily
           WHERE trade_date > ? GROUP BY trade_date
           ORDER BY trade_date LIMIT 1 OFFSET ?""",
        (entry_date, max(0, int(days) - 1)),
    ).fetchone()
    return str(row["trade_date"] or "") if row else ""


def _highest_mark_price(
    connection: sqlite3.Connection,
    stock_code: str,
    entry_date: str,
    trade_date: str,
    current_price: float,
) -> float:
    """Return the high-water mark used by the profit-retrace protection."""
    row = connection.execute(
        """SELECT MAX(price) AS high_price
           FROM paper_position_mark
           WHERE stock_code = ? AND mark_date >= ? AND mark_date <= ?""",
        (stock_code, entry_date or trade_date, trade_date),
    ).fetchone()
    return max(float(row["high_price"] or 0), float(current_price or 0))


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


@dataclass
class SyncResult:
    """Result of a data sync operation."""
    new_daily: int = 0
    new_indicators: int = 0
    stocks_updated: int = 0
    errors: list[str] = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class MarketDatabase:
    """Local SQLite market data warehouse."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        # BaoStock has one process-global socket session.  Do not let startup
        # refresh and the scheduled daily refresh login/logout concurrently.
        self._daily_sync_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stock_basic (
                    ts_code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    industry TEXT DEFAULT '',
                    list_date TEXT DEFAULT '',
                    market_cap_yi REAL,
                    float_mcap_yi REAL,
                    turnover_pct REAL,
                    metadata_source TEXT DEFAULT '',
                    metadata_as_of TEXT DEFAULT '',
                    metadata_fetched_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS stock_metadata_history (
                    ts_code TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    industry TEXT DEFAULT '',
                    list_date TEXT DEFAULT '',
                    delist_date TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    is_st INTEGER DEFAULT 0,
                    is_suspended INTEGER DEFAULT 0,
                    market_cap_yi REAL,
                    float_mcap_yi REAL,
                    turnover_pct REAL,
                    market_cap_source TEXT DEFAULT '',
                    market_cap_fetched_at TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    PRIMARY KEY (ts_code, as_of_date)
                );

                CREATE INDEX IF NOT EXISTS idx_stock_metadata_history_date
                    ON stock_metadata_history(as_of_date, ts_code);

                CREATE TABLE IF NOT EXISTS market_adjustment_factor (
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    adj_factor REAL NOT NULL,
                    source TEXT DEFAULT '',
                    data_date TEXT DEFAULT '',
                    fetched_at TEXT DEFAULT '',
                    PRIMARY KEY (ts_code, trade_date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_market_adjustment_factor_code
                    ON market_adjustment_factor(ts_code, trade_date);

                CREATE TABLE IF NOT EXISTS financial_statement_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    statement_type TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    ann_date TEXT DEFAULT '',
                    f_ann_date TEXT DEFAULT '',
                    row_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL DEFAULT '',
                    data_status TEXT NOT NULL DEFAULT 'available',
                    UNIQUE(ts_code, statement_type, report_date, ann_date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_financial_statement_history_code
                    ON financial_statement_history(ts_code, statement_type, report_date DESC);

                CREATE TABLE IF NOT EXISTS fund_flow_history (
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    main_net REAL,
                    net_amount REAL,
                    status TEXT NOT NULL DEFAULT 'missing',
                    source TEXT NOT NULL DEFAULT '',
                    endpoint TEXT DEFAULT 'moneyflow',
                    data_date TEXT DEFAULT '',
                    fetched_at TEXT DEFAULT '',
                    raw_json TEXT DEFAULT '{}',
                    data_status TEXT NOT NULL DEFAULT 'available',
                    PRIMARY KEY (ts_code, trade_date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_fund_flow_history_code
                    ON fund_flow_history(ts_code, trade_date DESC);

                CREATE TABLE IF NOT EXISTS data_completion_checkpoint (
                    job_name TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    partition_key TEXT NOT NULL,
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'running',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_name, target_name, partition_key)
                );

                CREATE TABLE IF NOT EXISTS research_rerun_dispatch (
                    execution_key TEXT PRIMARY KEY,
                    target_date TEXT NOT NULL DEFAULT '',
                    source_run_id TEXT NOT NULL DEFAULT '',
                    data_revision TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'claimed',
                    triggered_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS market_daily (
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL DEFAULT 0,
                    high REAL DEFAULT 0,
                    low REAL DEFAULT 0,
                    close REAL DEFAULT 0,
                    pre_close REAL DEFAULT 0,
                    change_pct REAL DEFAULT 0,
                    volume REAL DEFAULT 0,
                    amount REAL DEFAULT 0,
                    turnover REAL DEFAULT 0,
                    PRIMARY KEY (ts_code, trade_date)
                );

                CREATE INDEX IF NOT EXISTS idx_market_daily_date
                    ON market_daily(trade_date);
                CREATE INDEX IF NOT EXISTS idx_market_daily_code
                    ON market_daily(ts_code);

                CREATE TABLE IF NOT EXISTS indicator_daily (
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    macd_score REAL DEFAULT 50,
                    rsi_score REAL DEFAULT 50,
                    kdj_score REAL DEFAULT 50,
                    ma_score REAL DEFAULT 50,
                    volume_score REAL DEFAULT 50,
                    fusion_score REAL DEFAULT 50,
                    direction TEXT DEFAULT 'neutral',
                    confidence REAL DEFAULT 0,
                    PRIMARY KEY (ts_code, trade_date)
                );

                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    new_rows INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                );

                CREATE TABLE IF NOT EXISTS task_execution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_source TEXT DEFAULT 'legacy',
                    started_at TEXT DEFAULT '',
                    completed_at TEXT DEFAULT '',
                    duration_seconds REAL DEFAULT 0,
                    error TEXT DEFAULT '',
                    output_json TEXT DEFAULT '{}',
                    execution_key TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_task_execution_completed
                    ON task_execution(completed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_execution_name
                    ON task_execution(task_name, completed_at DESC);

                CREATE TABLE IF NOT EXISTS decision_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    ai_score REAL DEFAULT 50,
                    direction TEXT DEFAULT 'neutral',
                    confidence REAL DEFAULT 0,
                    recommendation TEXT DEFAULT '',
                    fusion_score REAL DEFAULT 50,
                    macd_score REAL DEFAULT 50,
                    rsi_score REAL DEFAULT 50,
                    kdj_score REAL DEFAULT 50,
                    ma_score REAL DEFAULT 50,
                    volume_score REAL DEFAULT 50,
                    buy_signals INTEGER DEFAULT 0,
                    sell_signals INTEGER DEFAULT 0,
                    evidence TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    outcome_known INTEGER DEFAULT 0,
                    was_correct INTEGER DEFAULT NULL,
                    actual_return REAL DEFAULT NULL,
                    outcome_checked_at TEXT DEFAULT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_decision_date
                    ON decision_journal(decision_date);
                CREATE INDEX IF NOT EXISTS idx_decision_code
                    ON decision_journal(stock_code);

                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_capital REAL NOT NULL DEFAULT 100000,
                    cash REAL NOT NULL DEFAULT 100000,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_position (
                    stock_code TEXT PRIMARY KEY,
                    stock_name TEXT NOT NULL,
                    shares INTEGER NOT NULL DEFAULT 0,
                    avg_cost REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    industry TEXT DEFAULT '',
                    execution_tier TEXT DEFAULT 'normal',
                    entry_flow_state TEXT DEFAULT '',
                    entry_fallback_status TEXT DEFAULT '',
                    entry_gate_reasons TEXT DEFAULT '[]',
                    probe_expiry_date TEXT DEFAULT '',
                    promotion_status TEXT DEFAULT 'none'
                );

                CREATE TABLE IF NOT EXISTS paper_trade (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    action TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL NOT NULL,
                    value REAL NOT NULL,
                    reason TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    realized_pnl REAL DEFAULT 0,
                    execution_tier TEXT DEFAULT 'normal',
                    flow_state TEXT DEFAULT '',
                    fallback_status TEXT DEFAULT '',
                    gate_reasons TEXT DEFAULT '[]',
                    promotion_status TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_paper_trade_date
                    ON paper_trade(trade_date DESC);
                CREATE INDEX IF NOT EXISTS idx_paper_trade_created_at
                    ON paper_trade(created_at DESC);

                CREATE TABLE IF NOT EXISTS paper_ledger_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    archived_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    rebuilt_summary_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS paper_order_rejection (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT DEFAULT '',
                    direction TEXT DEFAULT '',
                    reason TEXT NOT NULL,
                    quote_date TEXT DEFAULT '',
                    quote_source TEXT DEFAULT '',
                    quote_price REAL DEFAULT 0,
                    execution_at TEXT NOT NULL,
                    execution_tier TEXT DEFAULT 'blocked',
                    flow_state TEXT DEFAULT '',
                    fallback_status TEXT DEFAULT '',
                    gate_reasons TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_paper_order_rejection_date
                    ON paper_order_rejection(signal_date DESC);

                CREATE TABLE IF NOT EXISTS paper_position_mark (
                    mark_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL NOT NULL,
                    pre_close REAL NOT NULL,
                    market_value REAL NOT NULL,
                    daily_pl REAL NOT NULL DEFAULT 0,
                    price_date TEXT DEFAULT '',
                    price_source TEXT DEFAULT '',
                    fetched_at TEXT DEFAULT '',
                    is_fresh INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (mark_date, stock_code)
                );
                CREATE INDEX IF NOT EXISTS idx_paper_position_mark_date
                    ON paper_position_mark(mark_date DESC);

                CREATE TABLE IF NOT EXISTS paper_portfolio_snapshot (
                    snapshot_date TEXT PRIMARY KEY,
                    cash REAL NOT NULL,
                    market_value REAL NOT NULL,
                    total_value REAL NOT NULL,
                    daily_pl REAL NOT NULL DEFAULT 0,
                    daily_pl_pct REAL NOT NULL DEFAULT 0,
                    market_pnl REAL NOT NULL DEFAULT 0,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    trade_pnl_bridge REAL NOT NULL DEFAULT 0,
                    fees REAL NOT NULL DEFAULT 0,
                    equity_change REAL NOT NULL DEFAULT 0,
                    reconciliation_delta REAL NOT NULL DEFAULT 0,
                    reconciliation_status TEXT NOT NULL DEFAULT 'unknown',
                    price_coverage REAL NOT NULL DEFAULT 0,
                    price_sources_json TEXT DEFAULT '[]',
                    stale_positions_json TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    learning_date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    evidence_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_date
                    ON learning_log(learning_date DESC);

                CREATE TABLE IF NOT EXISTS market_learning_observation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id INTEGER NOT NULL,
                    observation_date TEXT NOT NULL,
                    horizon_days INTEGER NOT NULL DEFAULT 1,
                    stock_code TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    was_correct INTEGER NOT NULL,
                    stock_return REAL NOT NULL,
                    benchmark_return REAL NOT NULL,
                    excess_return REAL NOT NULL,
                    sources_json TEXT DEFAULT '[]',
                    feature_json TEXT DEFAULT '{}',
                    benchmark_basis TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(decision_id, horizon_days)
                );
                CREATE INDEX IF NOT EXISTS idx_market_learning_symbol
                    ON market_learning_observation(stock_code, horizon_days);
                CREATE INDEX IF NOT EXISTS idx_market_learning_observation_date
                    ON market_learning_observation(observation_date DESC);

                CREATE TABLE IF NOT EXISTS strategy_decision (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id INTEGER,
                    decision_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    strategy_name TEXT NOT NULL DEFAULT 'adaptive-paper-v1',
                    strategy_version TEXT NOT NULL DEFAULT '1.0',
                    technical_score REAL DEFAULT 50,
                    deep_rating TEXT DEFAULT '',
                    effective_direction TEXT DEFAULT 'neutral',
                    analysis_json TEXT DEFAULT '{}',
                    outcome_status TEXT DEFAULT 'pending',
                    actual_return REAL,
                    reflection TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(decision_date, stock_code, strategy_name)
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_decision_code
                    ON strategy_decision(stock_code, decision_date DESC);
                CREATE INDEX IF NOT EXISTS idx_strategy_decision_journal_id
                    ON strategy_decision(journal_id);

                CREATE TABLE IF NOT EXISTS replay_run (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    replay_date TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'replay',
                    model_version TEXT DEFAULT '',
                    context_hash TEXT DEFAULT '',
                    result_hash TEXT DEFAULT '',
                    status TEXT DEFAULT '',
                    result_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_replay_run_date
                    ON replay_run(replay_date, created_at DESC);

                CREATE TABLE IF NOT EXISTS runtime_contract (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    algorithm_version TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    build_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    validated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_failure_incident (
                    incident_key TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    state TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    first_failed_at TEXT NOT NULL,
                    last_failed_at TEXT NOT NULL,
                    last_alert_state TEXT DEFAULT '',
                    next_probe_at TEXT DEFAULT '',
                    recovered_at TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_failure_incident_task
                    ON task_failure_incident(task_name, updated_at DESC);

                CREATE TABLE IF NOT EXISTS pipeline_run_audit (
                    run_id TEXT PRIMARY KEY,
                    decision_date TEXT NOT NULL DEFAULT '',
                    target_trade_date TEXT NOT NULL DEFAULT '',
                    requirement_version TEXT NOT NULL DEFAULT '',
                    strategy_version TEXT NOT NULL DEFAULT '',
                    code_hash TEXT NOT NULL DEFAULT '',
                    config_hash TEXT NOT NULL DEFAULT '',
                    audit_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pipeline_run_audit_updated
                    ON pipeline_run_audit(updated_at DESC);

                CREATE TABLE IF NOT EXISTS deep_analysis_attempt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_date TEXT NOT NULL,
                    research_window TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'reserved',
                    error_type TEXT DEFAULT '',
                    error_detail TEXT DEFAULT '',
                    duration_seconds REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(budget_date, research_window, stock_code, input_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_deep_analysis_attempt_budget
                    ON deep_analysis_attempt(budget_date, research_window, created_at);
            """)
            # Existing installations get the paper account lazily below; this
            # keeps the migration idempotent and avoids resetting user state.
            for table, column, definition in (
                ("paper_account", "ledger_version", "INTEGER DEFAULT 1"),
                ("paper_account", "ledger_quality", "TEXT DEFAULT 'legacy_unverified'"),
                ("paper_account", "ledger_rebuilt_at", "TEXT DEFAULT ''"),
                ("paper_account", "price_policy", "TEXT DEFAULT 'legacy'"),
                ("paper_account", "commission_rate", "REAL DEFAULT 0.0005"),
                ("paper_account", "stamp_tax_rate", "REAL DEFAULT 0.0005"),
                ("paper_account", "fee_policy", "TEXT DEFAULT 'legacy'"),
                ("paper_account", "execution_policy", "TEXT DEFAULT 'legacy'"),
                ("paper_position", "entry_date", "TEXT DEFAULT ''"),
                ("paper_position", "eligible_sell_date", "TEXT DEFAULT ''"),
                ("paper_position", "entry_price_date", "TEXT DEFAULT ''"),
                ("paper_position", "entry_price_source", "TEXT DEFAULT ''"),
                ("paper_position", "execution_mode", "TEXT DEFAULT ''"),
                ("paper_trade", "decision_id", "INTEGER"),
                ("paper_trade", "fee", "REAL DEFAULT 0"),
                ("paper_trade", "commission", "REAL DEFAULT 0"),
                ("paper_trade", "stamp_tax", "REAL DEFAULT 0"),
                ("paper_trade", "slippage", "REAL DEFAULT 0"),
                ("paper_trade", "signal_date", "TEXT DEFAULT ''"),
                ("paper_trade", "signal_at", "TEXT DEFAULT ''"),
                ("paper_trade", "data_cutoff_at", "TEXT DEFAULT ''"),
                ("paper_trade", "quote_exchange_at", "TEXT DEFAULT ''"),
                ("paper_trade", "source_lag_seconds", "REAL"),
                ("paper_trade", "causality_status", "TEXT DEFAULT 'legacy_unverified'"),
                ("paper_trade", "price_date", "TEXT DEFAULT ''"),
                ("paper_trade", "price_source", "TEXT DEFAULT ''"),
                ("paper_trade", "execution_mode", "TEXT DEFAULT ''"),
                ("paper_trade", "quote_fetched_at", "TEXT DEFAULT ''"),
                ("paper_trade", "integrity_status", "TEXT DEFAULT 'legacy_unverified'"),
                ("paper_trade", "legacy_trade_id", "INTEGER"),
                ("paper_order_rejection", "signal_at", "TEXT DEFAULT ''"),
                ("paper_order_rejection", "data_cutoff_at", "TEXT DEFAULT ''"),
                ("paper_order_rejection", "quote_exchange_at", "TEXT DEFAULT ''"),
                ("task_execution", "trigger_source", "TEXT DEFAULT 'legacy'"),
                ("task_execution", "execution_key", "TEXT DEFAULT ''"),
                ("paper_position", "entry_decision_id", "INTEGER"),
                ("paper_position", "entry_strategy_version", "TEXT DEFAULT ''"),
                ("paper_position", "entry_deep_rating", "TEXT DEFAULT ''"),
                ("paper_position", "entry_identity_status", "TEXT DEFAULT 'legacy_unverified'"),
                ("paper_position", "industry", "TEXT DEFAULT ''"),
                ("paper_position", "execution_tier", "TEXT DEFAULT 'normal'"),
                ("paper_position", "entry_flow_state", "TEXT DEFAULT ''"),
                ("paper_position", "entry_fallback_status", "TEXT DEFAULT ''"),
                ("paper_position", "entry_gate_reasons", "TEXT DEFAULT '[]'"),
                ("paper_position", "probe_expiry_date", "TEXT DEFAULT ''"),
                ("paper_position", "promotion_status", "TEXT DEFAULT 'none'"),
                ("paper_trade", "realized_pnl", "REAL DEFAULT 0"),
                ("paper_trade", "execution_tier", "TEXT DEFAULT 'normal'"),
                ("paper_trade", "flow_state", "TEXT DEFAULT ''"),
                ("paper_trade", "fallback_status", "TEXT DEFAULT ''"),
                ("paper_trade", "gate_reasons", "TEXT DEFAULT '[]'"),
                ("paper_trade", "promotion_status", "TEXT DEFAULT ''"),
                ("paper_order_rejection", "execution_tier", "TEXT DEFAULT 'blocked'"),
                ("paper_order_rejection", "flow_state", "TEXT DEFAULT ''"),
                ("paper_order_rejection", "fallback_status", "TEXT DEFAULT ''"),
                ("paper_order_rejection", "gate_reasons", "TEXT DEFAULT '[]'"),
                ("paper_portfolio_snapshot", "market_pnl", "REAL DEFAULT 0"),
                ("paper_portfolio_snapshot", "realized_pnl", "REAL DEFAULT 0"),
                ("paper_portfolio_snapshot", "trade_pnl_bridge", "REAL DEFAULT 0"),
                ("paper_portfolio_snapshot", "fees", "REAL DEFAULT 0"),
                ("paper_portfolio_snapshot", "equity_change", "REAL DEFAULT 0"),
                ("paper_portfolio_snapshot", "reconciliation_delta", "REAL DEFAULT 0"),
                ("paper_portfolio_snapshot", "reconciliation_status", "TEXT DEFAULT 'unknown'"),
                ("stock_basic", "market_cap_yi", "REAL"),
                ("stock_basic", "float_mcap_yi", "REAL"),
                ("stock_basic", "turnover_pct", "REAL"),
                ("stock_basic", "metadata_source", "TEXT DEFAULT ''"),
                ("stock_basic", "metadata_as_of", "TEXT DEFAULT ''"),
                ("stock_basic", "metadata_fetched_at", "TEXT DEFAULT ''"),
                ("stock_metadata_history", "market_cap_yi", "REAL"),
                ("stock_metadata_history", "float_mcap_yi", "REAL"),
                ("stock_metadata_history", "turnover_pct", "REAL"),
                ("stock_metadata_history", "market_cap_source", "TEXT DEFAULT ''"),
                ("stock_metadata_history", "market_cap_fetched_at", "TEXT DEFAULT ''"),
                # Which benchmark a learning observation was scored against.
                # Rows predating the equal-weight switch carry 沪深300 excess and
                # must never be pooled with the new basis.
                ("market_learning_observation", "benchmark_basis", "TEXT DEFAULT ''"),
            ):
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            # Every observation written before the equal-weight switch carries
            # 沪深300 excess in a column that did not exist yet, so its basis
            # reads as the default.  Label it instead of deleting it: the two
            # bases must never be pooled, and the old rows are still the record
            # of what the broken configuration produced.  Idempotent -- new rows
            # always carry a real basis, so '' only ever matches legacy rows.
            conn.execute(
                """UPDATE market_learning_observation
                      SET benchmark_basis='hs300_legacy'
                    WHERE COALESCE(benchmark_basis, '') = ''"""
            )
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if schema_version not in (0, 1, 2, 3, 4, 5, DB_SCHEMA_VERSION):
                raise RuntimeError(
                    f"unsupported database schema version: {schema_version}"
                )
            if schema_version != DB_SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
            self._backfill_entry_identity(conn)

    @staticmethod
    def _backfill_entry_identity(conn: sqlite3.Connection) -> None:
        """Backfill only uniquely attributable legacy open positions."""
        positions = conn.execute(
            """SELECT stock_code FROM paper_position
               WHERE shares > 0 AND COALESCE(entry_identity_status, '')
                     IN ('', 'legacy_unverified')"""
        ).fetchall()
        for position in positions:
            code = str(position["stock_code"] or "")
            buys = conn.execute(
                """SELECT t.decision_id, s.strategy_version, s.deep_rating
                   FROM paper_trade AS t
                   LEFT JOIN strategy_decision AS s
                     ON s.journal_id=t.decision_id
                  WHERE t.stock_code=? AND t.action='BUY'
                    AND t.decision_id IS NOT NULL
                  ORDER BY t.trade_date, t.id""",
                (code,),
            ).fetchall()
            candidates = {
                (
                    int(row["decision_id"]),
                    str(row["strategy_version"] or ""),
                    str(row["deep_rating"] or ""),
                )
                for row in buys
                if row["strategy_version"]
            }
            if len(candidates) != 1:
                continue
            decision_id, strategy_version, deep_rating = next(iter(candidates))
            conn.execute(
                """UPDATE paper_position
                      SET entry_decision_id=?, entry_strategy_version=?,
                          entry_deep_rating=?, entry_identity_status=?
                    WHERE stock_code=? AND shares > 0""",
                (decision_id, strategy_version, deep_rating, "verified", code),
            )

    # ================================================================
    # Sync — pull from baostock into local DB
    # ================================================================

    def upsert_tushare_daily_rows(
        self,
        rows: list[dict[str, Any]],
        target_date: str,
        *,
        expected_count: int = 0,
        complete: bool = True,
    ) -> dict[str, Any]:
        """Atomically persist one validated Tushare daily snapshot."""
        normalized_target = str(target_date or "").strip().replace("/", "-")
        if len(normalized_target) == 8 and normalized_target.isdigit():
            normalized_target = (
                f"{normalized_target[:4]}-{normalized_target[4:6]}-"
                f"{normalized_target[6:]}"
            )
        if not normalized_target or not complete or not rows:
            return {
                "status": "partial" if rows and not complete else "empty",
                "target_date": normalized_target,
                "stored_count": 0,
                "expected_count": expected_count,
            }
        clean_rows = []
        for item in rows:
            code = str(item.get("ts_code") or "").strip().upper()
            trade_date = str(item.get("trade_date") or "").strip().replace("/", "-")
            if len(trade_date) == 8 and trade_date.isdigit():
                trade_date = (
                    f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
                )
            close = item.get("close")
            if not code or trade_date != normalized_target or close in (None, ""):
                continue
            clean_rows.append(
                (
                    code,
                    trade_date,
                    float(item.get("open") or 0),
                    float(item.get("high") or 0),
                    float(item.get("low") or 0),
                    float(close or 0),
                    float(item.get("pre_close") or 0),
                    float(item.get("change_pct") or 0),
                    float(item.get("volume") or 0),
                    float(item.get("amount") or 0),
                    float(item.get("turnover") or 0),
                )
            )
        if not clean_rows:
            return {
                "status": "empty", "target_date": normalized_target,
                "stored_count": 0, "expected_count": expected_count,
            }
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO market_daily
                   (ts_code, trade_date, open, high, low, close, pre_close,
                    change_pct, volume, amount, turnover)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code, trade_date) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, pre_close=excluded.pre_close,
                     change_pct=excluded.change_pct, volume=excluded.volume,
                     amount=excluded.amount, turnover=excluded.turnover""",
                clean_rows,
            )
        self._record_sync_log(
            "daily_bars_tushare", datetime.now().isoformat(),
            datetime.now().isoformat(), len(clean_rows), "completed",
        )
        return {
            "status": "completed", "target_date": normalized_target,
            "stored_count": len(clean_rows), "expected_count": expected_count,
            "coverage_ratio": (
                round(len(clean_rows) / expected_count, 4)
                if expected_count else None
            ),
        }

    @staticmethod
    def _normalize_date(value: Any) -> str:
        text = str(value or "").strip().replace("/", "-")
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:]}"
        return text[:10]

    def upsert_tushare_daily_history(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        """Insert historical raw daily bars without overwriting existing bars."""
        clean: list[tuple[Any, ...]] = []
        for item in rows:
            code = str(item.get("ts_code") or "").strip().upper()
            trade_date = self._normalize_date(item.get("trade_date"))
            close = item.get("close")
            if not code or not trade_date or close in (None, ""):
                continue
            clean.append((
                code, trade_date, item.get("open"), item.get("high"), item.get("low"),
                close, item.get("pre_close"), item.get("change_pct"), item.get("volume"),
                item.get("amount"), item.get("turnover", 0),
            ))
        if not clean:
            return {"stored_count": 0, "input_count": len(rows)}
        with self._get_conn() as conn:
            before = conn.total_changes
            conn.executemany(
                """INSERT INTO market_daily
                   (ts_code, trade_date, open, high, low, close, pre_close,
                    change_pct, volume, amount, turnover)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code, trade_date) DO NOTHING""",
                clean,
            )
            stored = conn.total_changes - before
        return {"stored_count": int(stored or 0), "input_count": len(rows)}

    def upsert_adjustment_factors(self, rows: list[dict[str, Any]]) -> int:
        """Persist adjustment factors independently from unadjusted OHLCV."""
        clean = []
        for item in rows:
            code = str(item.get("ts_code") or "").strip().upper()
            trade_date = self._normalize_date(item.get("trade_date"))
            factor = item.get("adj_factor")
            if not code or not trade_date or factor in (None, ""):
                continue
            clean.append((
                code, trade_date, float(factor), str(item.get("source") or "tushare"),
                trade_date, str(item.get("fetched_at") or datetime.now().isoformat()),
            ))
        if not clean:
            return 0
        with self._get_conn() as conn:
            before = conn.total_changes
            conn.executemany(
                """INSERT INTO market_adjustment_factor
                   (ts_code, trade_date, adj_factor, source, data_date, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code, trade_date, source) DO UPDATE SET
                     adj_factor=excluded.adj_factor, data_date=excluded.data_date,
                     fetched_at=excluded.fetched_at""",
                clean,
            )
            stored = conn.total_changes - before
        return int(stored)

    def get_adjustment_factor_coverage(
        self, code: str, required_rows: int = 250
    ) -> dict[str, Any]:
        """Return dated-factor coverage without conflating it with OHLC bars."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS n, MIN(trade_date) AS first_date,
                          MAX(trade_date) AS last_date
                     FROM market_adjustment_factor
                    WHERE ts_code=?""",
                (str(code or "").strip().upper(),),
            ).fetchone()
        count = int(row["n"] or 0)
        return {
            "ts_code": str(code or "").strip().upper(), "row_count": count,
            "first_date": str(row["first_date"] or ""),
            "last_date": str(row["last_date"] or ""),
            "status": "sufficient" if count >= int(required_rows)
            else "insufficient" if count else "missing",
        }

    def upsert_financial_history(
        self, code: str, statements: dict[str, list[dict[str, Any]]],
        *, source: str = "tushare", fetched_at: str = ""
    ) -> dict[str, int]:
        """Store report-period rows and preserve provider revisions."""
        fetched = fetched_at or datetime.now().isoformat()
        clean: list[tuple[Any, ...]] = []
        for statement_type, rows in (statements or {}).items():
            for row in rows or []:
                report_date = self._normalize_date(row.get("end_date") or row.get("report_date"))
                if not report_date:
                    continue
                clean.append((
                    str(row.get("ts_code") or code).strip().upper(),
                    str(statement_type), report_date,
                    self._normalize_date(row.get("ann_date")),
                    self._normalize_date(row.get("f_ann_date")),
                    json.dumps(row, ensure_ascii=False, default=str), source, fetched,
                    "available",
                ))
        if not clean:
            return {"stored_count": 0, "input_count": sum(len(v or []) for v in (statements or {}).values())}
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO financial_statement_history
                   (ts_code, statement_type, report_date, ann_date, f_ann_date,
                    row_json, source, fetched_at, data_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code, statement_type, report_date, ann_date, source)
                   DO UPDATE SET f_ann_date=excluded.f_ann_date, row_json=excluded.row_json,
                     fetched_at=excluded.fetched_at, data_status=excluded.data_status""",
                clean,
            )
        return {"stored_count": len(clean), "input_count": sum(len(v or []) for v in (statements or {}).values())}

    def get_financial_history(self, code: str, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
        """Read stored statement rows grouped by statement type."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT statement_type, row_json FROM financial_statement_history
                   WHERE ts_code=? AND data_status='available'
                   ORDER BY report_date DESC, ann_date DESC""",
                (str(code or "").strip().upper(),),
            ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {}
        seen_periods: dict[str, set[str]] = {}
        for row in rows:
            group = result.setdefault(str(row["statement_type"]), [])
            statement_type = str(row["statement_type"])
            if len(group) >= max(1, int(limit)):
                continue
            try:
                decoded = json.loads(row["row_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(decoded, dict):
                period = str(decoded.get("end_date") or decoded.get("report_date") or "")
                if period and period in seen_periods.setdefault(statement_type, set()):
                    continue
                group.append(decoded)
                if period:
                    seen_periods.setdefault(statement_type, set()).add(period)
        return result

    def get_financial_history_metadata(self, code: str) -> dict[str, Any]:
        """Return freshness metadata without changing the history read shape."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT statement_type, MAX(ann_date) AS latest_ann_date,
                          MAX(report_date) AS latest_report_date,
                          MAX(fetched_at) AS latest_fetched_at
                     FROM financial_statement_history
                    WHERE ts_code=? AND data_status='available'
                    GROUP BY statement_type""",
                (str(code or "").strip().upper(),),
            ).fetchall()
        return {
            str(row["statement_type"]): {
                "latest_ann_date": str(row["latest_ann_date"] or ""),
                "latest_report_date": str(row["latest_report_date"] or ""),
                "latest_fetched_at": str(row["latest_fetched_at"] or ""),
            }
            for row in rows
        }

    def upsert_fund_flow_history(self, rows: list[dict[str, Any]]) -> int:
        """Persist dated, normalized money-flow rows idempotently."""
        clean = []
        for item in rows:
            code = str(item.get("ts_code") or "").strip().upper()
            trade_date = self._normalize_date(item.get("trade_date"))
            if not code or not trade_date:
                continue
            clean.append((
                code, trade_date, item.get("main_net"), item.get("net_amount"),
                str(item.get("status") or "missing"), str(item.get("source") or "tushare"),
                str(item.get("endpoint") or "moneyflow"), trade_date,
                str(item.get("fetched_at") or datetime.now().isoformat()),
                json.dumps(item.get("raw") or item, ensure_ascii=False, default=str),
                "available",
            ))
        if not clean:
            return 0
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO fund_flow_history
                   (ts_code, trade_date, main_net, net_amount, status, source,
                    endpoint, data_date, fetched_at, raw_json, data_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code, trade_date, source) DO UPDATE SET
                     main_net=excluded.main_net, net_amount=excluded.net_amount,
                     status=excluded.status, endpoint=excluded.endpoint,
                     data_date=excluded.data_date, fetched_at=excluded.fetched_at,
                     raw_json=excluded.raw_json, data_status=excluded.data_status""",
                clean,
            )
        return len(clean)

    def get_fund_flow_history(self, code: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT ts_code, trade_date, main_net, net_amount, status, source,
                          endpoint, data_date, fetched_at
                   FROM fund_flow_history WHERE ts_code=? AND data_status='available'
                   ORDER BY trade_date DESC LIMIT ?""",
                (str(code or "").strip().upper(), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_market_dates(self, target_date: str, limit: int = 20) -> list[str]:
        """Return distinct locally observed market dates, newest first."""
        if not target_date:
            return []
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT trade_date FROM market_daily
                   WHERE trade_date<=? ORDER BY trade_date DESC LIMIT ?""",
                (str(target_date)[:10], max(1, int(limit))),
            ).fetchall()
        return [str(row["trade_date"] or "")[:10] for row in rows if row["trade_date"]]

    def get_fund_flow_coverage(
        self, codes: list[str], trade_dates: list[str]
    ) -> dict[str, set[str]]:
        """Return cached flow dates by code for one bounded batch."""
        normalized_codes = sorted({str(code or "").strip().upper() for code in codes if code})
        normalized_dates = sorted({str(day or "")[:10] for day in trade_dates if day})
        coverage = {code: set() for code in normalized_codes}
        if not normalized_codes or not normalized_dates:
            return coverage
        code_marks = ",".join("?" for _ in normalized_codes)
        date_marks = ",".join("?" for _ in normalized_dates)
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT ts_code, trade_date FROM fund_flow_history
                    WHERE data_status='available'
                      AND ts_code IN ({code_marks})
                      AND trade_date IN ({date_marks})""",
                (*normalized_codes, *normalized_dates),
            ).fetchall()
        for row in rows:
            code = str(row["ts_code"] or "").upper()
            if code in coverage:
                coverage[code].add(str(row["trade_date"] or "")[:10])
        return coverage

    def get_completion_checkpoint(
        self, job_name: str, target_name: str, partition_key: str
    ) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT progress_json, status, updated_at FROM data_completion_checkpoint
                   WHERE job_name=? AND target_name=? AND partition_key=?""",
                (job_name, target_name, partition_key),
            ).fetchone()
        if not row:
            return None
        try:
            progress = json.loads(row["progress_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            progress = {}
        return {"progress": progress, "status": row["status"], "updated_at": row["updated_at"]}

    def save_completion_checkpoint(
        self, job_name: str, target_name: str, partition_key: str,
        progress: dict[str, Any], status: str = "running",
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO data_completion_checkpoint
                   (job_name, target_name, partition_key, progress_json, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_name, target_name, partition_key) DO UPDATE SET
                     progress_json=excluded.progress_json, status=excluded.status,
                     updated_at=excluded.updated_at""",
                (job_name, target_name, partition_key,
                 json.dumps(progress or {}, ensure_ascii=False, default=str), status,
                datetime.now().isoformat()),
            )

    def try_claim_completion_checkpoint(
        self, job_name: str, target_name: str, partition_key: str,
        lease_owner: str, lease_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Atomically claim a resumable checkpoint, preventing overlap across processes."""
        now = datetime.now().astimezone()
        now_iso = now.isoformat()
        expires_iso = (now.timestamp() + max(1.0, float(lease_seconds)))
        expires = datetime.fromtimestamp(expires_iso, tz=now.tzinfo).isoformat()
        with self._get_conn() as conn:
            # Claim under a write lock so two processes cannot both observe an
            # expired/pending lease and then overwrite each other's owner.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT progress_json, status FROM data_completion_checkpoint
                   WHERE job_name=? AND target_name=? AND partition_key=?""",
                (job_name, target_name, partition_key),
            ).fetchone()
            progress: dict[str, Any] = {}
            status = "pending"
            if row:
                status = str(row["status"] or "pending")
                try:
                    progress = json.loads(row["progress_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    progress = {}
                current_owner = str(progress.get("lease_owner") or "")
                current_expires = str(progress.get("lease_expires_at") or "")
                lease_active = False
                if current_owner and current_owner != lease_owner and current_expires:
                    try:
                        lease_active = datetime.fromisoformat(current_expires).timestamp() > now.timestamp()
                    except ValueError:
                        lease_active = False
                if status == "running" and lease_active:
                    return {
                        "claimed": False, "status": status,
                        "lease_owner": current_owner,
                        "lease_expires_at": current_expires,
                        "progress": progress,
                    }
            progress.update({
                "lease_owner": lease_owner,
                "lease_acquired_at": now_iso,
                "lease_heartbeat_at": now_iso,
                "lease_expires_at": expires,
            })
            conn.execute(
                """INSERT INTO data_completion_checkpoint
                   (job_name, target_name, partition_key, progress_json, status, updated_at)
                   VALUES (?, ?, ?, ?, 'running', ?)
                   ON CONFLICT(job_name, target_name, partition_key) DO UPDATE SET
                     progress_json=excluded.progress_json, status='running',
                     updated_at=excluded.updated_at""",
                (job_name, target_name, partition_key,
                 json.dumps(progress, ensure_ascii=False, default=str), now_iso),
            )
        return {
            "claimed": True, "status": "running",
            "lease_owner": lease_owner, "lease_expires_at": expires,
            "progress": progress,
        }

    def list_completion_checkpoints(
        self, job_name: str, target_name: str = ""
    ) -> list[dict[str, Any]]:
        """List resumable checkpoints for the shared background worker."""
        query = (
            "SELECT job_name, target_name, partition_key, progress_json, status, updated_at "
            "FROM data_completion_checkpoint WHERE job_name=?"
        )
        params: list[Any] = [job_name]
        if target_name:
            query += " AND target_name=?"
            params.append(target_name)
        query += " ORDER BY updated_at ASC"
        with self._get_conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                progress = json.loads(row["progress_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                progress = {}
            result.append({
                "job_name": row["job_name"],
                "target_name": row["target_name"],
                "partition_key": row["partition_key"],
                "progress": progress,
                "status": row["status"],
                "updated_at": row["updated_at"],
            })
        return result

    def get_latest_strategy_run(self) -> dict[str, Any]:
        """Return the newest persisted strategy run and its candidate codes."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id, decision_date, stock_code, analysis_json
                     FROM strategy_decision
                    ORDER BY decision_date DESC, id DESC"""
            ).fetchall()
        runs: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                analysis = json.loads(row["analysis_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                analysis = {}
            run_id = str(analysis.get("run_id") or "").strip()
            if not run_id:
                continue
            item = runs.setdefault(
                run_id,
                {
                    "run_id": run_id,
                    "decision_date": str(row["decision_date"] or ""),
                    "run_created_at": str(analysis.get("run_created_at") or ""),
                    "codes": [],
                    "last_id": 0,
                },
            )
            item["codes"].append(str(row["stock_code"] or "").strip().upper())
            item["decision_date"] = max(
                item["decision_date"], str(row["decision_date"] or "")
            )
            item["run_created_at"] = max(
                item["run_created_at"], str(analysis.get("run_created_at") or "")
            )
            item["last_id"] = max(item["last_id"], int(row["id"] or 0))
        if not runs:
            return {"run_id": "", "decision_date": "", "run_created_at": "", "codes": []}
        latest = max(
            runs.values(),
            key=lambda item: (item["decision_date"], item["last_id"]),
        )
        latest["codes"] = sorted({code for code in latest["codes"] if code})
        latest.pop("last_id", None)
        return latest

    def get_strategy_run_evidence_summary(self, run_id: str) -> dict[str, Any]:
        """Summarize evidence actually persisted in one strategy run."""
        wanted = str(run_id or "").strip()
        if not wanted:
            return {"run_id": "", "decision_count": 0}
        rows: list[sqlite3.Row]
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT decision_date, stock_code, analysis_json
                     FROM strategy_decision ORDER BY id ASC"""
            ).fetchall()
        matched: list[dict[str, Any]] = []
        for row in rows:
            try:
                analysis = json.loads(row["analysis_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if str(analysis.get("run_id") or "").strip() != wanted:
                continue
            matched.append(analysis)
        flow_states: dict[str, int] = {}
        source_count = 0
        fundamental_count = 0
        dates: set[str] = set()
        sources: set[str] = set()
        run_created_dates: set[str] = set()
        for analysis in matched:
            state = str(
                analysis.get("flow_status") or analysis.get("flow_state") or "missing"
            )
            flow_states[state] = flow_states.get(state, 0) + 1
            market_sources = analysis.get("market_sources")
            if market_sources:
                source_count += 1
                if isinstance(market_sources, list):
                    sources.update(str(item) for item in market_sources if item)
            fundamentals = analysis.get("fundamentals")
            if analysis.get("fundamental_evidence_available") is True or (
                isinstance(fundamentals, dict) and fundamentals.get("available")
            ):
                fundamental_count += 1
            created = str(analysis.get("run_created_at") or "")
            if created:
                run_created_dates.add(created)
            for key in ("market_price_date", "quote_date", "data_cutoff_at"):
                value = str(analysis.get(key) or "")[:10]
                if value:
                    dates.add(value)
                    break
        total = len(matched)
        return {
            "run_id": wanted,
            "decision_count": total,
            "source_coverage": round(source_count / total, 4) if total else 0.0,
            "flow_coverage": round(
                sum(flow_states.get(state, 0) for state in ("positive", "negative"))
                / total,
                4,
            ) if total else 0.0,
            "fundamental_coverage": round(fundamental_count / total, 4) if total else 0.0,
            "flow_status_counts": flow_states,
            "evidence_dates": sorted(dates),
            "evidence_sources": sorted(sources),
            "run_created_at": min(run_created_dates) if run_created_dates else "",
        }

    def save_pipeline_run_audit(self, audit: dict[str, Any]) -> None:
        """Persist one compact, run-scoped stage acceptance snapshot."""
        run_id = str(audit.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("pipeline run audit requires run_id")
        now = datetime.now().astimezone().isoformat()
        payload = dict(audit)
        payload.setdefault("schema_version", "unknown")
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT created_at FROM pipeline_run_audit WHERE run_id=?",
                (run_id,),
            ).fetchone()
            created_at = str(existing["created_at"] or "") if existing else now
            conn.execute(
                """INSERT INTO pipeline_run_audit(
                       run_id, decision_date, target_trade_date,
                       requirement_version, strategy_version, code_hash,
                       config_hash, audit_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       decision_date=excluded.decision_date,
                       target_trade_date=excluded.target_trade_date,
                       requirement_version=excluded.requirement_version,
                       strategy_version=excluded.strategy_version,
                       code_hash=excluded.code_hash,
                       config_hash=excluded.config_hash,
                       audit_json=excluded.audit_json,
                       updated_at=excluded.updated_at""",
                (
                    run_id,
                    str(payload.get("decision_date") or ""),
                    str(payload.get("target_trade_date") or ""),
                    str(payload.get("requirement_version") or ""),
                    str(payload.get("strategy_version") or ""),
                    str(payload.get("code_hash") or ""),
                    str(payload.get("config_hash") or ""),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    created_at,
                    now,
                ),
            )

    def get_pipeline_run_audit(self, run_id: str) -> dict[str, Any] | None:
        """Read one compact run audit; missing legacy rows remain unverified."""
        wanted = str(run_id or "").strip()
        if not wanted:
            return None
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_run_audit WHERE run_id=?",
                (wanted,),
            ).fetchone()
        if row is None:
            return {
                "run_id": wanted,
                "acceptance_status": "unverified",
                "persistence_status": "unverified",
                "reason_codes": ["run_audit_not_persisted"],
            }
        try:
            payload = json.loads(row["audit_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("run_id", wanted)
        payload.setdefault("decision_date", row["decision_date"] or "")
        payload.setdefault("target_trade_date", row["target_trade_date"] or "")
        payload.setdefault("requirement_version", row["requirement_version"] or "")
        payload.setdefault("strategy_version", row["strategy_version"] or "")
        payload.setdefault("code_hash", row["code_hash"] or "")
        payload.setdefault("config_hash", row["config_hash"] or "")
        payload["audit_created_at"] = row["created_at"] or ""
        payload["audit_updated_at"] = row["updated_at"] or ""
        return payload

    def get_latest_pipeline_run_audit(self) -> dict[str, Any] | None:
        """Read the newest compact audit without scanning strategy JSON rows."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT run_id FROM pipeline_run_audit ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return self.get_pipeline_run_audit(row["run_id"]) if row else None

    def get_research_component_coverage(
        self, codes: list[str], target_date: str, required_bars: int = 250,
        periods: int = 8, flow_days: int = 20,
    ) -> dict[str, Any]:
        """Re-read research component coverage from SQLite without provider calls."""
        normalized = sorted({str(code or "").strip().upper() for code in codes if code})
        empty = {
            "candidate_count": 0,
            "components": {},
            "details": {},
            "expected_flow_dates": [],
        }
        if not normalized:
            return empty
        marks = ",".join("?" for _ in normalized)
        target = str(target_date or "")[:10]
        with self._get_conn() as conn:
            daily_rows = conn.execute(
                f"""SELECT ts_code, COUNT(*) AS row_count, MAX(trade_date) AS last_date
                       FROM market_daily WHERE ts_code IN ({marks}) GROUP BY ts_code""",
                tuple(normalized),
            ).fetchall()
            factor_rows = conn.execute(
                f"""SELECT ts_code, COUNT(*) AS row_count, MAX(trade_date) AS last_date
                       FROM market_adjustment_factor
                      WHERE ts_code IN ({marks}) GROUP BY ts_code""",
                tuple(normalized),
            ).fetchall()
            financial_rows = conn.execute(
                f"""SELECT ts_code, statement_type, COUNT(DISTINCT report_date) AS period_count,
                              MAX(report_date) AS last_date
                       FROM financial_statement_history
                      WHERE data_status='available' AND ts_code IN ({marks})
                      GROUP BY ts_code, statement_type""",
                tuple(normalized),
            ).fetchall()
            market_dates = conn.execute(
                """SELECT DISTINCT trade_date FROM market_daily
                    WHERE trade_date<=? ORDER BY trade_date DESC LIMIT ?""",
                (target, max(1, int(flow_days))),
            ).fetchall()
            expected_flow_dates = [str(row["trade_date"] or "")[:10] for row in market_dates]
            flow_marks = ",".join("?" for _ in normalized)
            flow_rows = conn.execute(
                f"""SELECT ts_code, trade_date FROM fund_flow_history
                      WHERE data_status='available' AND ts_code IN ({flow_marks})""",
                tuple(normalized),
            ).fetchall()

        daily = {str(row["ts_code"]): dict(row) for row in daily_rows}
        factors = {str(row["ts_code"]): dict(row) for row in factor_rows}
        financial: dict[str, dict[str, dict[str, Any]]] = {}
        for row in financial_rows:
            financial.setdefault(str(row["ts_code"]), {})[str(row["statement_type"])] = {
                "period_count": int(row["period_count"] or 0),
                "last_date": str(row["last_date"] or ""),
            }
        flows: dict[str, set[str]] = {code: set() for code in normalized}
        for row in flow_rows:
            flows.setdefault(str(row["ts_code"]), set()).add(
                str(row["trade_date"] or "")[:10]
            )

        details: dict[str, dict[str, Any]] = {}
        component_missing = {name: [] for name in (
            "daily", "adjustment_factor", "financial_history", "fund_flow_history"
        )}
        for code in normalized:
            daily_item = daily.get(code) or {}
            factor_item = factors.get(code) or {}
            financial_item = financial.get(code) or {}
            financial_counts = {
                name: int((financial_item.get(name) or {}).get("period_count") or 0)
                for name in ("income", "balancesheet", "cashflow", "fina_indicator")
            }
            component = {
                "daily": {
                    "row_count": int(daily_item.get("row_count") or 0),
                    "last_date": str(daily_item.get("last_date") or ""),
                    "complete": int(daily_item.get("row_count") or 0) >= int(required_bars),
                },
                "adjustment_factor": {
                    "row_count": int(factor_item.get("row_count") or 0),
                    "last_date": str(factor_item.get("last_date") or ""),
                    "complete": int(factor_item.get("row_count") or 0) >= int(required_bars),
                },
                "financial_history": {
                    "period_counts": financial_counts,
                    "last_dates": {
                        name: str((financial_item.get(name) or {}).get("last_date") or "")
                        for name in financial_counts
                    },
                    "complete": all(count >= int(periods) for count in financial_counts.values()),
                },
                "fund_flow_history": {
                    "row_count": len(flows.get(code) or set()),
                    "data_date": max(flows.get(code) or {""}),
                    "complete": (
                        len(expected_flow_dates) >= int(flow_days)
                        and set(expected_flow_dates).issubset(flows.get(code) or set())
                        and max(flows.get(code) or {""}) >= target
                    ),
                },
            }
            details[code] = component
            for name, item in component.items():
                if not item["complete"]:
                    component_missing[name].append(code)

        candidate_count = len(normalized)
        components = {}
        for name, missing in component_missing.items():
            components[name] = {
                "candidate_count": candidate_count,
                "complete_count": candidate_count - len(missing),
                "coverage": round(
                    (candidate_count - len(missing)) / candidate_count, 4
                ),
                "missing_codes": missing,
            }
        return {
            "candidate_count": candidate_count,
            "components": components,
            "details": details,
            "expected_flow_dates": expected_flow_dates,
        }

    def claim_research_rerun(
        self, execution_key: str, target_date: str, source_run_id: str,
        data_revision: str,
    ) -> dict[str, Any]:
        """Atomically claim one post-backfill AI rerun across restarts."""
        key = str(execution_key or "").strip()
        if not key:
            return {"claimed": False, "reason": "empty_execution_key"}
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, triggered_at, completed_at FROM research_rerun_dispatch "
                "WHERE execution_key=?", (key,)
            ).fetchone()
            if row:
                existing_status = str(row["status"] or "")
                if existing_status in {"claimed", "running"}:
                    try:
                        age_seconds = (
                            datetime.fromisoformat(now)
                            - datetime.fromisoformat(str(row["triggered_at"] or ""))
                        ).total_seconds()
                    except ValueError:
                        age_seconds = 0.0
                    # A crashed API can leave a claim behind.  The child
                    # worker is bounded to 1800s, so only reclaim an old
                    # claim after a longer safety window.
                    if age_seconds > 3600:
                        conn.execute(
                            """UPDATE research_rerun_dispatch
                                  SET status='claimed', triggered_at=?,
                                      completed_at='', result_json='{}'
                                WHERE execution_key=?""",
                            (now, key),
                        )
                        return {
                            "claimed": True, "status": "claimed",
                            "triggered_at": now, "reclaimed": True,
                        }
                return {
                    "claimed": False,
                    "reason": "already_dispatched",
                    "status": existing_status,
                    "triggered_at": str(row["triggered_at"] or ""),
                    "completed_at": str(row["completed_at"] or ""),
                }
            conn.execute(
                """INSERT INTO research_rerun_dispatch
                   (execution_key, target_date, source_run_id, data_revision,
                    status, triggered_at)
                   VALUES (?, ?, ?, ?, 'claimed', ?)""",
                (key, str(target_date or ""), str(source_run_id or ""),
                 str(data_revision or ""), now),
            )
        return {"claimed": True, "status": "claimed", "triggered_at": now}

    def finish_research_rerun(
        self, execution_key: str, status: str, result: dict[str, Any] | None = None,
    ) -> None:
        """Persist the terminal result of a claimed post-backfill rerun."""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE research_rerun_dispatch
                      SET status=?, completed_at=?, result_json=?
                    WHERE execution_key=?""",
                (
                    str(status or "failed"), datetime.now().isoformat(),
                    json.dumps(result or {}, ensure_ascii=False, default=str),
                    str(execution_key or ""),
                ),
            )

    def get_research_rerun_dispatches(self, limit: int = 20) -> list[dict[str, Any]]:
        """Load durable post-backfill dispatch state for observability."""
        safe_limit = max(1, min(int(limit), 100))
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT execution_key, target_date, source_run_id, data_revision,
                          status, triggered_at, completed_at, result_json
                     FROM research_rerun_dispatch
                    ORDER BY triggered_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["result_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            result.append({
                "execution_key": row["execution_key"],
                "target_date": row["target_date"],
                "source_run_id": row["source_run_id"],
                "data_revision": row["data_revision"],
                "status": row["status"],
                "triggered_at": row["triggered_at"],
                "completed_at": row["completed_at"],
                "result": payload,
            })
        return result

    def get_expected_market_absences(
        self, codes: list[str], dates: list[str]
    ) -> dict[str, dict[str, str]]:
        """Return evidenced non-trading cells; missing quotes prove nothing.

        Suspension is date-specific: never carry an old suspension snapshot
        forward, or apply today's status to earlier trading sessions.
        """
        if not codes or not dates:
            return {}
        result: dict[str, dict[str, str]] = {}
        with self._get_conn() as conn:
            for offset in range(0, len(codes), 500):
                chunk = codes[offset:offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""SELECT ts_code, as_of_date, list_date, delist_date,
                               is_suspended, source
                        FROM stock_metadata_history
                        WHERE ts_code IN ({placeholders}) AND as_of_date<=?
                        ORDER BY as_of_date""",
                    (*chunk, max(dates)),
                ).fetchall()
                for row in rows:
                    if not row["source"]:
                        continue
                    for day in dates:
                        if row["as_of_date"] > day:
                            continue
                        reason = ""
                        listed = str(row["list_date"] or "").replace("-", "")
                        delisted = str(row["delist_date"] or "").replace("-", "")
                        compact_day = day.replace("-", "")
                        if listed and compact_day < listed:
                            reason = "not_yet_listed"
                        elif delisted and compact_day >= delisted:
                            reason = "delisted"
                        elif row["as_of_date"] == day and row["is_suspended"]:
                            reason = "suspended"
                        cells = result.setdefault(row["ts_code"], {})
                        if reason:
                            cells[day] = reason
                        else:
                            cells.pop(day, None)
        return result

    def get_bar_coverage(self, codes: list[str], required_bars: int = 250) -> dict[str, Any]:
        """Classify requested symbols without treating unavailable history as suspension."""
        normalized = sorted({str(code or "").strip().upper() for code in codes if code})
        if not normalized:
            return {"requested": 0, "sufficient": 0, "insufficient": 0, "missing": 0, "details": []}
        placeholders = ",".join("?" for _ in normalized)
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT ts_code, COUNT(*) AS bar_count, MIN(trade_date) AS first_date,
                           MAX(trade_date) AS last_date FROM market_daily
                    WHERE ts_code IN ({placeholders}) GROUP BY ts_code""",
                tuple(normalized),
            ).fetchall()
        by_code = {str(row["ts_code"]): dict(row) for row in rows}
        details = []
        for code in normalized:
            row = by_code.get(code)
            count = int(row["bar_count"] or 0) if row else 0
            details.append({
                "ts_code": code, "bar_count": count,
                "first_date": str(row["first_date"] or "") if row else "",
                "last_date": str(row["last_date"] or "") if row else "",
                "status": "sufficient" if count >= required_bars else "insufficient" if count else "missing",
            })
        return {
            "requested": len(normalized),
            "sufficient": sum(item["status"] == "sufficient" for item in details),
            "insufficient": sum(item["status"] == "insufficient" for item in details),
            "missing": sum(item["status"] == "missing" for item in details),
            "details": details,
        }

    def sync_daily_bars(
        self, codes: list[str] | None = None,
        days_back: int = 30,
        progress_callback=None,
        target_date: str = "",
    ) -> SyncResult:
        """Sync daily OHLCV data from baostock to local DB.

        Args:
            codes: Stock codes to sync. None = use default universe.
            days_back: How many days back to sync.
            progress_callback: Optional callback(stock_idx, total, code, status)

        Returns:
            SyncResult with counts and errors.
        """
        from src.infrastructure.market_data.baostock_lock import mark_sync_start, mark_sync_end

        result = SyncResult()
        t0 = time.time()
        started_iso = datetime.now().isoformat()
        today = dt_date.today()

        if not self._daily_sync_lock.acquire(blocking=False):
            result.errors.append("baostock sync already in progress")
            result.duration_seconds = time.time() - t0
            self._record_sync_log(
                "daily_bars",
                started_iso,
                datetime.now().isoformat(),
                0,
                "skipped_busy",
            )
            return result

        # Acquire the local lock before importing/starting BaoStock. A busy
        # concurrent sync must return the deterministic busy result even when
        # the optional BaoStock package is not installed in this process.
        try:
            import baostock as bs
        except ImportError as exc:
            result.errors.append(f"baostock unavailable: {exc}")
            result.duration_seconds = time.time() - t0
            self._record_sync_log(
                "daily_bars",
                started_iso,
                datetime.now().isoformat(),
                0,
                "failed",
            )
            self._daily_sync_lock.release()
            return result

        # 标记同步进行中:API 侧 baostock fallback 将跳过,避免与长 session 互踢
        mark_sync_start()
        try:
            # BaoStock is a stateful socket session and transient disconnects
            # are common. Retry the login before falling back to the local
            # cache, while keeping the whole sync bounded.
            lg = None
            for attempt in range(1, 4):
                lg = bs.login()
                if lg.error_code == '0' or attempt >= 3:
                    break
                time.sleep(1.0 * attempt)
            assert lg is not None
            if lg.error_code != '0':
                result.errors.append(f"baostock login failed: {lg.error_msg}")
                self._record_sync_log("daily_bars", started_iso,
                                      datetime.now().isoformat(), 0, "failed")
                return result

            # codes=None:在已 login 会话内拉真实全 A 股(替代返回空的 _get_default_universe)
            if codes is None:
                universe = self._fetch_baostock_universe(bs)
                codes = [u["code"] for u in universe]
                # 批量初始化 stock_basic(名称来自 baostock code_name)
                if universe:
                    today_iso = today.isoformat()
                    with self._get_conn() as conn:
                        for u in universe:
                            conn.execute(
                                """INSERT INTO stock_basic(ts_code, name, updated_at)
                                   VALUES (?, ?, ?)
                                   ON CONFLICT(ts_code) DO UPDATE SET
                                     name=excluded.name,
                                     updated_at=excluded.updated_at""",
                                (u["code"], u["name"], today_iso),
                            )
                if not codes:
                    result.errors.append("baostock universe fetch returned empty")

            if target_date and codes:
                codes = self.get_codes_missing_market_date(codes, target_date)

            for idx, code in enumerate(codes):
                try:
                    # Convert code format
                    if ".SH" in code:
                        bs_code = f"sh.{code.replace('.SH', '')}"
                    elif ".SZ" in code:
                        bs_code = f"sz.{code.replace('.SZ', '')}"
                    elif ".BJ" in code:
                        bs_code = f"bj.{code.replace('.BJ', '')}"
                    else:
                        continue

                    start = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
                    end = today.strftime('%Y-%m-%d')

                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        'date,open,high,low,close,preclose,volume,amount,turn',
                        start_date=start, end_date=end,
                        frequency='d', adjustflag='3',
                    )

                    if rs.error_code != '0':
                        continue

                    rows = []
                    while (rs.error_code == '0') & rs.next():
                        rows.append(rs.get_row_data())

                    if not rows:
                        continue

                    # Also get stock name if not in DB
                    stock_name = code
                    stock_metadata: dict[str, Any] = {}
                    try:
                        rs_name = bs.query_stock_basic(code=bs_code)
                        if rs_name.error_code == '0':
                            while rs_name.next():
                                stock_metadata = dict(
                                    zip(rs_name.fields, rs_name.get_row_data())
                                )
                                stock_name = str(
                                    stock_metadata.get("code_name") or stock_name
                                )
                                break
                    except Exception:
                        pass

                    # Upsert into local DB
                    with self._get_conn() as conn:
                        conn.execute(
                            """INSERT INTO stock_basic(ts_code, name, industry, list_date, updated_at)
                               VALUES (?, ?, ?, ?, ?)
                               ON CONFLICT(ts_code) DO UPDATE SET
                                 name=excluded.name,
                                 list_date=CASE WHEN excluded.list_date <> ''
                                                THEN excluded.list_date
                                                ELSE stock_basic.list_date END,
                                 updated_at=excluded.updated_at""",
                            (
                                code,
                                stock_name,
                                str(stock_metadata.get("industry") or ""),
                                str(stock_metadata.get("ipoDate") or ""),
                                today.isoformat(),
                            ),
                        )

                        conn.execute(
                            """INSERT INTO stock_metadata_history
                               (ts_code, as_of_date, name, industry, list_date,
                                delist_date, status, is_st, is_suspended, source, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(ts_code, as_of_date) DO UPDATE SET
                                 name=excluded.name,
                                 list_date=excluded.list_date,
                                 delist_date=excluded.delist_date,
                                 status=excluded.status,
                                 is_st=excluded.is_st,
                                 updated_at=excluded.updated_at""",
                            (
                                code,
                                today.isoformat(),
                                stock_name,
                                str(stock_metadata.get("industry") or ""),
                                str(stock_metadata.get("ipoDate") or ""),
                                str(stock_metadata.get("outDate") or ""),
                                str(stock_metadata.get("status") or "active"),
                                int(
                                    self._metadata_bool(stock_metadata.get("isST"))
                                    or self._metadata_name_is_st(stock_name)
                                ),
                                0,
                                "baostock",
                                datetime.now().isoformat(),
                            ),
                        )

                        for r in rows:
                            if not r[0] or not r[4]:
                                continue
                            close = float(r[4]) if r[4] else 0
                            pre_close = float(r[5]) if r[5] else float(r[1]) if r[1] else close
                            change_pct = ((close - pre_close) / pre_close * 100) if pre_close > 0 else 0

                            conn.execute(
                                """INSERT OR REPLACE INTO market_daily
                                   (ts_code, trade_date, open, high, low, close,
                                    pre_close, change_pct, volume, amount, turnover)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    code, r[0],
                                    float(r[1]) if r[1] else 0,
                                    float(r[2]) if r[2] else 0,
                                    float(r[3]) if r[3] else 0,
                                    close, pre_close, round(change_pct, 2),
                                    float(r[6]) if r[6] else 0,
                                    float(r[7]) if r[7] else 0,
                                    float(r[8]) if len(r) > 8 and r[8] else 0,
                                ),
                            )
                            result.new_daily += 1

                    result.stocks_updated += 1

                    if progress_callback:
                        progress_callback(idx + 1, len(codes), code, "ok")

                except Exception as e:
                    result.errors.append(f"{code}: {str(e)[:80]}")
                    if progress_callback:
                        progress_callback(idx + 1, len(codes), code, f"err: {str(e)[:40]}")

            # Record sync log(用真实起始时间 started_iso,而非循环结束时刻)
            self._record_sync_log(
                "daily_bars", started_iso,
                datetime.now().isoformat(), result.new_daily, "completed",
            )

        finally:
            try:
                bs.logout()
            except Exception:
                pass
            mark_sync_end()
            self._daily_sync_lock.release()

        result.duration_seconds = time.time() - t0
        return result

    def sync_stock_metadata_snapshot(
        self, as_of_date: str, codes: list[str] | None = None
    ) -> dict[str, Any]:
        """Pull an exchange-day stock universe into the replay metadata table.

        BaoStock's ``query_all_stock`` is date-aware for listing and trading
        status. It does not provide a complete historical industry taxonomy;
        those fields remain empty until a dated industry source is supplied.
        """
        import baostock as bs
        from src.infrastructure.market_data.baostock_lock import mark_sync_end, mark_sync_start

        dt_date.fromisoformat(as_of_date)
        if not self._daily_sync_lock.acquire(blocking=False):
            return {
                "status": "skipped_busy",
                "as_of_date": as_of_date,
                "stock_count": 0,
                "stored_count": 0,
                "errors": ["baostock sync already in progress"],
            }

        allowed = set(codes or [])
        snapshots: list[dict[str, Any]] = []
        errors: list[str] = []
        mark_sync_start()
        try:
            login = bs.login()
            if login.error_code != "0":
                return {
                    "status": "failed",
                    "as_of_date": as_of_date,
                    "stock_count": 0,
                    "stored_count": 0,
                    "errors": [f"baostock login failed: {login.error_msg}"],
                }
            source_date = as_of_date
            used_fallback = False
            warnings: list[str] = []
            target_day = dt_date.fromisoformat(as_of_date)
            # BaoStock commonly publishes query_all_stock after the session.
            # During trading hours the target day can therefore be a valid
            # exchange day while the response is still empty.  Use the most
            # recent published universe as a listing/ST baseline, but never
            # carry its date-specific suspension flag into the target day.
            for offset in range(16):
                query_date = (target_day - timedelta(days=offset)).isoformat()
                result = bs.query_all_stock(day=query_date)
                if result.error_code != "0":
                    errors.append(
                        f"query_all_stock {query_date} failed: {result.error_msg}"
                    )
                    continue
                candidate_rows: list[dict[str, Any]] = []
                while result.next():
                    item = dict(zip(result.fields, result.get_row_data()))
                    raw_code = str(item.get("code") or "")
                    if not raw_code.startswith(("sh.", "sz.")):
                        continue
                    suffix = "SH" if raw_code.startswith("sh.") else "SZ"
                    code = f"{raw_code[3:]}.{suffix}"
                    if not _is_a_share_stock_code(code) or (allowed and code not in allowed):
                        continue
                    name = str(item.get("code_name") or code)
                    trade_status = str(item.get("tradeStatus") or "1")
                    same_day = query_date == as_of_date
                    candidate_rows.append(
                        {
                            "ts_code": code,
                            "name": name,
                            "industry": item.get("industry") or "",
                            "list_date": item.get("ipoDate") or "",
                            "delist_date": item.get("outDate") or "",
                            "status": (
                                "active" if trade_status in {"", "1"}
                                else "suspended"
                            ) if same_day else "status_unknown",
                            "is_st": self._metadata_bool(item.get("isST"))
                            or self._metadata_name_is_st(name),
                            "is_suspended": (
                                trade_status not in {"", "1"} if same_day else False
                            ),
                            "source": (
                                "baostock_query_all_stock" if same_day
                                else "baostock_previous_day_baseline"
                            ),
                        }
                    )
                if candidate_rows:
                    snapshots = candidate_rows
                    source_date = query_date
                    used_fallback = not same_day
                    break
            if used_fallback:
                warnings.append("same_day_status_unavailable")
            if not snapshots:
                warnings.append("status_source_unpublished_or_empty")
            stored = self.upsert_stock_metadata_snapshot(snapshots, as_of_date, "baostock")
            return {
                "status": (
                    "fallback" if used_fallback else "ok" if stored else "unavailable"
                ),
                "as_of_date": as_of_date,
                "source_date": source_date if stored else "",
                "stock_count": len(snapshots),
                "stored_count": stored,
                "suspension_status": (
                    "unknown_pending_live_quote" if used_fallback
                    else "verified" if stored else "unknown"
                ),
                "warnings": warnings,
                "errors": errors,
            }
        except Exception as exc:
            errors.append(f"metadata snapshot failed: {type(exc).__name__}: {str(exc)[:160]}")
            return {
                "status": "failed",
                "as_of_date": as_of_date,
                "stock_count": len(snapshots),
                "stored_count": 0,
                "errors": errors,
            }
        finally:
            try:
                bs.logout()
            except Exception:
                pass
            mark_sync_end()
            self._daily_sync_lock.release()

    def _record_sync_log(self, sync_type, started_at, completed_at, new_rows, status):
        """写一条 sync_log 记录(容错,不抛错)。"""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO sync_log (sync_type, started_at, completed_at, new_rows, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (sync_type, started_at, completed_at, new_rows, status),
                )
        except Exception:
            pass

    def get_codes_missing_market_date(
        self,
        codes: list[str],
        target_date: str,
    ) -> list[str]:
        """Return codes not yet stored for a target day so interrupted syncs resume."""
        if not codes or not target_date:
            return list(codes)
        with self._get_conn() as conn:
            existing = {
                str(row["ts_code"])
                for row in conn.execute(
                    "SELECT ts_code FROM market_daily WHERE trade_date = ?",
                    (target_date,),
                ).fetchall()
            }
        return [code for code in codes if code not in existing]

    def _fetch_baostock_universe(self, bs) -> list[dict]:
        """在已 login 的 baostock 会话上拉取全 A 股股票池。

        复用 get_stock_universe 的过滤逻辑(仅 sh./sz.、tradeStatus 正常)。
        非交易日 query_all_stock 可能返回空,因此向前回溯最多 5 天。
        返回 [{"code": "600000.SH", "name": "浦发银行"}, ...]。
        """
        universe: list[dict] = []
        try:
            today = dt_date.today()
            for offset in range(5):
                query_date = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
                rs = bs.query_all_stock(day=query_date)
                if rs.error_code != '0':
                    continue
                while rs.next():
                    item = dict(zip(rs.fields, rs.get_row_data()))
                    raw_code = item.get("code", "")
                    if not raw_code.startswith(("sh.", "sz.")):
                        continue
                    # 排除指数:上证 000xxx 系列(上证综指等)、深证 399xxx 系列(深证成指等)
                    if raw_code.startswith("sh.000") or raw_code.startswith("sz.399"):
                        continue
                    if item.get("tradeStatus") not in ("", "1"):
                        continue
                    suffix = "SH" if raw_code.startswith("sh.") else "SZ"
                    normalized = f"{raw_code[3:]}.{suffix}"
                    if not _is_a_share_stock_code(normalized):
                        continue
                    universe.append({"code": normalized, "name": item.get("code_name", normalized)})
                if universe:
                    break
        except Exception:
            pass
        return universe

    @staticmethod
    def _metadata_bool(value: Any) -> bool:
        """Normalize provider flags without treating arbitrary text as true."""
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {
            "1", "true", "yes", "y", "st", "suspended", "停牌", "是"
        }

    @staticmethod
    def _metadata_name_is_st(value: Any) -> bool:
        """Detect ST labels without false positives such as ``Test``."""
        normalized = str(value or "").strip().upper().lstrip("*")
        return normalized.startswith("ST")

    def upsert_stock_metadata_snapshot(
        self, snapshots: list[dict], as_of_date: str, source: str = ""
    ) -> int:
        """Persist a point-in-time metadata snapshot for replay-safe filtering.

        The current ``stock_basic`` table is intentionally not used for replay:
        it represents the latest provider state and can therefore leak future
        listing, industry or ST status into an old decision.
        """
        if not as_of_date or not snapshots:
            return 0
        now = datetime.now().isoformat()
        rows = []
        for item in snapshots:
            code = str(item.get("ts_code") or item.get("code") or "").strip()
            if not code:
                continue
            rows.append(
                (
                    code,
                    as_of_date,
                    str(item.get("name") or item.get("code_name") or code),
                    str(item.get("industry") or ""),
                    str(item.get("list_date") or item.get("ipoDate") or ""),
                    str(item.get("delist_date") or item.get("outDate") or ""),
                    str(item.get("status") or "active"),
                    int(self._metadata_bool(item.get("is_st") or item.get("isST"))),
                    int(self._metadata_bool(item.get("is_suspended") or item.get("suspended"))),
                    str(item.get("source") or source or ""),
                    now,
                )
            )
        if not rows:
            return 0
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO stock_metadata_history
                   (ts_code, as_of_date, name, industry, list_date, delist_date,
                    status, is_st, is_suspended, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code, as_of_date) DO UPDATE SET
                     name=excluded.name,
                     industry=excluded.industry,
                     list_date=excluded.list_date,
                     delist_date=excluded.delist_date,
                     status=excluded.status,
                     is_st=excluded.is_st,
                     is_suspended=excluded.is_suspended,
                     source=excluded.source,
                     updated_at=excluded.updated_at""",
                rows,
            )
        return len(rows)

    def get_stock_metadata(self, code: str, as_of_date: str = "") -> dict | None:
        """Return metadata observable on ``as_of_date``.

        Historical callers receive no fallback to ``stock_basic`` when a
        snapshot is missing.  That fail-closed behavior is what prevents a
        current ST/delist/industry label from contaminating replay.
        """
        if not code:
            return None
        with self._get_conn() as conn:
            if as_of_date:
                row = conn.execute(
                    """SELECT ts_code, as_of_date, name, industry, list_date,
                              delist_date, status, is_st, is_suspended,
                              market_cap_yi, float_mcap_yi, turnover_pct,
                              market_cap_source, market_cap_fetched_at, source
                       FROM stock_metadata_history
                       WHERE ts_code=? AND as_of_date<=?
                       ORDER BY as_of_date DESC LIMIT 1""",
                    (code, as_of_date),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT ts_code, updated_at AS as_of_date, name, industry,
                              list_date, '' AS delist_date, 'active' AS status,
                              0 AS is_st, 0 AS is_suspended,
                              market_cap_yi, float_mcap_yi, turnover_pct,
                              metadata_source AS market_cap_source,
                              metadata_fetched_at AS market_cap_fetched_at,
                              'stock_basic' AS source
                       FROM stock_basic WHERE ts_code=?""",
                    (code,),
                ).fetchone()
        return dict(row) if row else None

    def get_stock_metadata_snapshot(self, as_of_date: str) -> dict[str, dict[str, Any]]:
        """Return the latest point-in-time metadata row per stock at a cutoff."""
        if not as_of_date:
            return {}
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT h.*
                     FROM stock_metadata_history h
                     JOIN (
                         SELECT ts_code, MAX(as_of_date) AS latest_date
                           FROM stock_metadata_history
                          WHERE as_of_date<=?
                          GROUP BY ts_code
                     ) latest
                       ON latest.ts_code=h.ts_code
                      AND latest.latest_date=h.as_of_date""",
                (as_of_date,),
            ).fetchall()
        return {str(row["ts_code"]): dict(row) for row in rows}

    def upsert_current_stock_metadata(
        self, rows: list[dict[str, Any]], as_of_date: str = ""
    ) -> dict[str, int]:
        """Persist current quote metadata and matching point-in-time fields.

        ``stock_basic`` is the latest-state cache used by live scans.  When a
        quote's own data date matches ``as_of_date``, its valuation fields are
        also copied into the historical metadata table.  A quote with another
        date can refresh the current cache but is never allowed to rewrite an
        older replay snapshot.
        """
        if not rows:
            return {"current_count": 0, "history_count": 0}

        now = datetime.now().isoformat()
        authoritative_by_code = (
            self.get_stock_metadata_snapshot(as_of_date) if as_of_date else {}
        )
        current_rows: list[tuple[Any, ...]] = []
        history_rows: list[tuple[Any, ...]] = []
        for item in rows:
            code = str(item.get("ts_code") or item.get("stock_code") or "").strip().upper()
            if not _is_a_share_stock_code(code):
                continue
            name = str(item.get("name") or item.get("stock_name") or code).strip()
            market_cap = item.get("market_cap_yi") or item.get("market_cap")
            float_mcap = item.get("float_mcap_yi") or item.get("float_market_cap_yi")
            turnover = item.get("turnover_pct") or item.get("turnover")
            try:
                market_cap = float(market_cap) if market_cap not in (None, "") else None
                if market_cap is not None and market_cap <= 0:
                    market_cap = None
            except (TypeError, ValueError):
                market_cap = None
            try:
                float_mcap = float(float_mcap) if float_mcap not in (None, "") else None
                if float_mcap is not None and float_mcap <= 0:
                    float_mcap = None
            except (TypeError, ValueError):
                float_mcap = None
            try:
                turnover = float(turnover) if turnover not in (None, "") else None
            except (TypeError, ValueError):
                turnover = None
            source = str(item.get("source") or "").strip()
            data_date = str(item.get("data_date") or item.get("metadata_as_of") or "").strip()
            fetched_at = str(item.get("fetched_at") or item.get("metadata_fetched_at") or now)
            current_rows.append(
                (
                    code, name, str(item.get("industry") or ""),
                    str(item.get("list_date") or ""), market_cap, float_mcap,
                    turnover, source, data_date, fetched_at, now,
                )
            )
            if as_of_date and data_date == as_of_date and market_cap is not None:
                authoritative = authoritative_by_code.get(code) or {}
                history_rows.append(
                    (
                        code, as_of_date, name,
                        str(authoritative.get("industry") or ""),
                        str(authoritative.get("list_date") or ""),
                        str(authoritative.get("delist_date") or ""),
                        str(authoritative.get("status") or "unknown"),
                        int(bool(authoritative.get("is_st"))),
                        int(bool(authoritative.get("is_suspended"))),
                        market_cap, float_mcap, turnover, source, fetched_at,
                        str(authoritative.get("source") or ""), now,
                    )
                )

        if not current_rows:
            return {"current_count": 0, "history_count": 0}
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO stock_basic
                   (ts_code, name, industry, list_date, market_cap_yi,
                    float_mcap_yi, turnover_pct, metadata_source,
                    metadata_as_of, metadata_fetched_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ts_code) DO UPDATE SET
                     name=CASE WHEN excluded.name <> ''
                               THEN excluded.name ELSE stock_basic.name END,
                     industry=CASE WHEN excluded.industry <> ''
                                   THEN excluded.industry ELSE stock_basic.industry END,
                     list_date=CASE WHEN excluded.list_date <> ''
                                    THEN excluded.list_date ELSE stock_basic.list_date END,
                     market_cap_yi=COALESCE(excluded.market_cap_yi,
                                            stock_basic.market_cap_yi),
                     float_mcap_yi=COALESCE(excluded.float_mcap_yi,
                                            stock_basic.float_mcap_yi),
                     turnover_pct=COALESCE(excluded.turnover_pct,
                                           stock_basic.turnover_pct),
                     metadata_source=CASE WHEN excluded.metadata_source <> ''
                                          THEN excluded.metadata_source
                                          ELSE stock_basic.metadata_source END,
                     metadata_as_of=CASE WHEN excluded.metadata_as_of <> ''
                                         THEN excluded.metadata_as_of
                                         ELSE stock_basic.metadata_as_of END,
                     metadata_fetched_at=CASE WHEN excluded.metadata_fetched_at <> ''
                                              THEN excluded.metadata_fetched_at
                                              ELSE stock_basic.metadata_fetched_at END,
                     updated_at=excluded.updated_at""",
                current_rows,
            )
            if history_rows:
                conn.executemany(
                    """INSERT INTO stock_metadata_history
                       (ts_code, as_of_date, name, industry, list_date, delist_date,
                        status, is_st, is_suspended, market_cap_yi, float_mcap_yi,
                        turnover_pct, market_cap_source, market_cap_fetched_at,
                        source, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(ts_code, as_of_date) DO UPDATE SET
                         name=CASE WHEN stock_metadata_history.name = ''
                                   THEN excluded.name
                                   ELSE stock_metadata_history.name END,
                         market_cap_yi=COALESCE(excluded.market_cap_yi,
                                                stock_metadata_history.market_cap_yi),
                         float_mcap_yi=COALESCE(excluded.float_mcap_yi,
                                                stock_metadata_history.float_mcap_yi),
                         turnover_pct=COALESCE(excluded.turnover_pct,
                                               stock_metadata_history.turnover_pct),
                         market_cap_source=excluded.market_cap_source,
                         market_cap_fetched_at=excluded.market_cap_fetched_at,
                         updated_at=excluded.updated_at""",
                    history_rows,
                )
        return {
            "current_count": len(current_rows),
            "history_count": len(history_rows),
        }

    def get_stock_metadata_coverage(self, as_of_date: str) -> dict[str, Any]:
        """Summarize snapshot coverage available to a historical cutoff."""
        if not as_of_date:
            return {"stock_count": 0, "first_snapshot": "", "last_snapshot": ""}
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT ts_code) AS stock_count,
                          MIN(as_of_date) AS first_snapshot,
                          MAX(as_of_date) AS last_snapshot
                   FROM stock_metadata_history
                   WHERE as_of_date<=?""",
                (as_of_date,),
            ).fetchone()
        return {
            "stock_count": int(row["stock_count"] or 0),
            "first_snapshot": str(row["first_snapshot"] or ""),
            "last_snapshot": str(row["last_snapshot"] or ""),
        }

    def is_stock_eligible(
        self, code: str, as_of_date: str = "", exclude_st: bool = True
    ) -> bool:
        """Check A-share tradability using only metadata known at the cutoff."""
        if not _is_a_share_stock_code(code):
            return False
        metadata = self.get_stock_metadata(code, as_of_date=as_of_date)
        if metadata is None:
            return False if as_of_date else True
        list_date = str(metadata.get("list_date") or "")
        delist_date = str(metadata.get("delist_date") or "")
        if as_of_date and list_date and list_date > as_of_date:
            return False
        if as_of_date and delist_date and delist_date <= as_of_date:
            return False
        status = str(metadata.get("status") or "").strip().lower()
        if status in {"0", "delisted", "退市", "暂停上市", "terminated"}:
            return False
        if bool(metadata.get("is_suspended")):
            return False
        if exclude_st and (
            bool(metadata.get("is_st")) or self._metadata_name_is_st(metadata.get("name"))
        ):
            return False
        return True

    def compute_and_store_indicators(self, codes: list[str] | None = None) -> int:
        """Pre-compute MACD/RSI/KDJ/MA/Volume for all stocks in local DB.

        Reads OHLCV from market_daily, computes indicators, stores in indicator_daily.
        This is the key performance optimization — signals are pre-computed,
        not calculated on every request.
        """
        from src.infrastructure.market_data.real_data_provider import real_data

        if codes is None:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT ts_code FROM market_daily"
                ).fetchall()
                codes = [r["ts_code"] for r in rows]

        total_computed = 0

        for code in codes:
            try:
                # Get all daily bars for this stock from local DB
                daily = self.get_daily_bars(code, limit=300)
                if len(daily) < 20:
                    continue

                # Get stock name
                with self._get_conn() as conn:
                    row = conn.execute(
                        "SELECT name FROM stock_basic WHERE ts_code=?",
                        (code,),
                    ).fetchone()
                    name = row["name"] if row else code

                # Compute signals
                sig = real_data.compute_signals(code, name, daily)

                # Store latest indicator
                latest_date = daily[-1]["date"]
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO indicator_daily
                           (ts_code, trade_date, macd_score, rsi_score,
                            kdj_score, ma_score, volume_score,
                            fusion_score, direction, confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            code, latest_date,
                            sig.macd_score, sig.rsi_score,
                            sig.kdj_score, sig.ma_score,
                            sig.volume_score, sig.fusion_score,
                            sig.direction, sig.confidence,
                        ),
                    )
                    total_computed += 1

            except Exception:
                continue

        return total_computed

    # ================================================================
    # Query — local, fast, no network
    # ================================================================

    def get_stock_universe(
        self,
        min_bars: int = 20,
        limit: int = 5000,
        as_of_date: str = "",
        exclude_st: bool = True,
    ) -> list[dict]:
        """Return analyzable A-share symbols, optionally replay-safe as of a date."""
        date_clause = " AND m.trade_date<=?" if as_of_date else ""
        amount_date_clause = " AND md2.trade_date<=?" if as_of_date else ""
        metadata_columns = (
            "'' AS industry, '' AS list_date, "
            "(SELECT h.market_cap_yi FROM stock_metadata_history h "
            " WHERE h.ts_code=m.ts_code AND h.as_of_date<=? "
            " ORDER BY h.as_of_date DESC LIMIT 1) AS market_cap_yi, "
            "'' AS metadata_source, '' AS metadata_as_of, "
            "'' AS metadata_fetched_at"
            if as_of_date
            else "MAX(s.industry) AS industry, MAX(s.list_date) AS list_date, "
                 "MAX(s.market_cap_yi) AS market_cap_yi, "
                 "MAX(s.metadata_source) AS metadata_source, "
                 "MAX(s.metadata_as_of) AS metadata_as_of, "
                 "MAX(s.metadata_fetched_at) AS metadata_fetched_at"
        )
        params: tuple[Any, ...] = (
            (as_of_date, as_of_date, as_of_date, min_bars, limit)
            if as_of_date
            else (min_bars, limit)
        )
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT m.ts_code, COALESCE(MAX(s.name), m.ts_code) AS name,
                          {metadata_columns},
                          (SELECT AVG(recent.amount) / 1000000.0
                             FROM (SELECT md2.amount
                                     FROM market_daily md2
                                    WHERE md2.ts_code=m.ts_code
                                      {amount_date_clause}
                                    ORDER BY md2.trade_date DESC
                                    LIMIT 20) recent) AS avg_daily_amount_million,
                          COUNT(*) AS bar_count, MAX(m.trade_date) AS latest_date
                   FROM market_daily m
                   LEFT JOIN stock_basic s ON s.ts_code = m.ts_code
                   WHERE (
                       (m.ts_code LIKE '%.SH' AND substr(m.ts_code, 1, 3) IN
                           ('600', '601', '603', '605', '688', '689'))
                       OR
                       (m.ts_code LIKE '%.SZ' AND substr(m.ts_code, 1, 3) IN
                           ('000', '001', '002', '003', '300', '301'))
                   ){date_clause}
                   GROUP BY m.ts_code
                   HAVING COUNT(*) >= ?
                   ORDER BY latest_date DESC, bar_count DESC
                   LIMIT ?""",
                params,
            ).fetchall()
        result = [
            {
                "code": row["ts_code"],
                "name": row["name"],
                "industry": row["industry"] or "",
                "list_date": row["list_date"] or "",
                "market_cap": (
                    float(row["market_cap_yi"])
                    if row["market_cap_yi"] is not None
                    else None
                ),
                "market_cap_yi": (
                    float(row["market_cap_yi"])
                    if row["market_cap_yi"] is not None
                    else None
                ),
                "metadata_source": row["metadata_source"] or "",
                "metadata_as_of": row["metadata_as_of"] or "",
                "metadata_fetched_at": row["metadata_fetched_at"] or "",
                "avg_daily_amount_million": (
                    float(row["avg_daily_amount_million"])
                    if row["avg_daily_amount_million"] is not None
                    else None
                ),
                "bar_count": row["bar_count"],
                "latest_date": row["latest_date"],
            }
            for row in rows
        ]
        if as_of_date:
            result = [
                item
                for item in result
                if self.is_stock_eligible(item["code"], as_of_date, exclude_st=exclude_st)
            ]
        return result

    def get_market_calendar(self, start_date: str = "") -> list[str]:
        """Ascending trading dates present in the local bar table.

        Serves as the session calendar the learning backfill aligns windows on.
        It used to come from the 沪深300 series it also used as the benchmark;
        the bar table is the market itself rather than one index's sessions.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT trade_date FROM market_daily
                    WHERE trade_date >= ? ORDER BY trade_date""",
                (start_date or "",),
            ).fetchall()
        return [str(row["trade_date"]) for row in rows]

    def equal_weight_benchmark(
        self, start_date: str, end_date: str
    ) -> tuple[float | None, BenchmarkBasis]:
        """Equal-weight universe return over one window, with its basis."""
        with self._get_conn() as conn:
            return equal_weight_return(conn, start_date, end_date)

    def get_daily_bars(
        self, code: str, limit: int = 250
    ) -> list[dict]:
        """Get daily OHLCV bars from local DB. No network, <2ms."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, open, high, low, close,
                          volume, amount, change_pct
                   FROM market_daily
                   WHERE ts_code=?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (code, limit),
            ).fetchall()

        # Return chronological order (oldest first)
        rows = list(reversed(rows))
        return [
            {
                "date": r["trade_date"],
                "open": r["open"], "high": r["high"],
                "low": r["low"], "close": r["close"],
                "volume": r["volume"], "amount": r["amount"],
            }
            for r in rows
        ]

    def get_two_yang_one_yin_candidates(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return research-only candidates matching the two-yang-one-yin setup.

        This deliberately lives beside the market-data queries rather than in
        the scanner.  The result is an additional observation list for the
        daily brief; it never changes scanner scores, ranking, or execution
        decisions.
        """
        safe_limit = max(1, min(int(limit), 20))
        with self._get_conn() as conn:
            date_rows = conn.execute(
                "SELECT DISTINCT trade_date FROM market_daily "
                "ORDER BY trade_date DESC LIMIT 5"
            ).fetchall()
            dates = [str(row["trade_date"] or "") for row in date_rows if row["trade_date"]]
            if len(dates) < 3:
                return []
            third_date, second_date, first_date = dates[:3]
            flow_marks = ",".join("?" for _ in dates)
            rows = conn.execute(
                f"""
                WITH flow_window AS (
                    SELECT ts_code,
                           SUM(main_net) AS five_day_main_net,
                           COUNT(*) AS flow_rows
                    FROM fund_flow_history
                    WHERE trade_date IN ({flow_marks})
                      AND data_status='available'
                    GROUP BY ts_code
                )
                SELECT
                    m1.ts_code,
                    COALESCE(s.name, m1.ts_code) AS stock_name,
                    m1.trade_date AS first_date,
                    m2.trade_date AS second_date,
                    m3.trade_date AS third_date,
                    m1.open AS first_open,
                    m1.close AS first_close,
                    m1.change_pct AS first_change_pct,
                    m2.open AS second_open,
                    m2.close AS second_close,
                    m2.change_pct AS second_change_pct,
                    m3.close AS price,
                    m3.change_pct AS third_change_pct,
                    m1.amount AS first_amount,
                    m2.amount AS second_amount,
                    m3.amount AS third_amount,
                    m3.turnover AS turnover,
                    f3.main_net AS latest_main_net,
                    flow_window.five_day_main_net,
                    flow_window.flow_rows
                FROM market_daily m1
                JOIN market_daily m2
                  ON m2.ts_code=m1.ts_code AND m2.trade_date=?
                JOIN market_daily m3
                  ON m3.ts_code=m1.ts_code AND m3.trade_date=?
                JOIN fund_flow_history f3
                  ON f3.ts_code=m1.ts_code
                 AND f3.trade_date=?
                 AND f3.data_status='available'
                JOIN flow_window ON flow_window.ts_code=m1.ts_code
                LEFT JOIN stock_basic s ON s.ts_code=m1.ts_code
                WHERE m1.trade_date=?
                  AND m1.change_pct > 0
                  AND m2.change_pct < 0
                  AND m3.change_pct > 0
                  AND m1.amount > 0
                  AND m2.amount < m1.amount
                  AND m3.amount > m2.amount * 1.2
                  AND m3.amount >= m1.amount * 0.9
                  AND f3.main_net > 0
                  AND flow_window.five_day_main_net > 0
                  AND flow_window.flow_rows >= 5
                  AND (
                      m1.ts_code LIKE '%.SH'
                      OR m1.ts_code LIKE '%.SZ'
                  )
                  AND COALESCE(s.name, '') NOT LIKE '%ST%'
                  AND COALESCE(s.name, '') NOT LIKE '%退%'
                ORDER BY (m3.amount / NULLIF(m2.amount, 0)) DESC,
                         f3.main_net DESC
                LIMIT ?
                """,
                [*dates, second_date, third_date, third_date, first_date, safe_limit],
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            first_amount = float(row["first_amount"] or 0)
            second_amount = float(row["second_amount"] or 0)
            third_amount = float(row["third_amount"] or 0)
            result.append(
                {
                    "stock_code": row["ts_code"],
                    "stock_name": row["stock_name"] or row["ts_code"],
                    "pattern": "two_yang_one_yin",
                    "pattern_label": "两阳夹一阴",
                    "pattern_state": "confirmed_watch",
                    "pattern_dates": [
                        row["first_date"], row["second_date"], row["third_date"]
                    ],
                    "price": round(float(row["price"] or 0), 3),
                    "change_pct": round(float(row["third_change_pct"] or 0), 2),
                    "turnover": round(float(row["turnover"] or 0), 4),
                    "volume_ratio_middle": round(second_amount / first_amount, 2)
                    if first_amount
                    else 0.0,
                    "volume_ratio_latest_vs_middle": round(third_amount / second_amount, 2)
                    if second_amount
                    else 0.0,
                    "latest_main_net": round(float(row["latest_main_net"] or 0), 2),
                    "five_day_main_net": round(float(row["five_day_main_net"] or 0), 2),
                    "flow_rows": int(row["flow_rows"] or 0),
                    "data_date": row["third_date"],
                    "data_source": "local market_daily + fund_flow_history",
                    "recommendation": "观察，不改变原有选股或买入规则",
                    "rationale": (
                        "阳线-阴线-阳线；中间回调缩量，第三日放量，"
                        "最新主力净流入且近5日累计为正"
                    ),
                }
            )
        return result

    def get_daily_bars_until(
        self, code: str, end_date: str, limit: int = 250
    ) -> list[dict]:
        """Return only bars observable on or before ``end_date``.

        Replay must use this query instead of ``get_daily_bars`` so later
        market data cannot leak into a historical decision.
        """
        safe_limit = max(1, min(int(limit), 1000))
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, open, high, low, close,
                          volume, amount, change_pct
                   FROM market_daily
                   WHERE ts_code=? AND trade_date<=?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (code, end_date, safe_limit),
            ).fetchall()
        return [
            {
                "date": row["trade_date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "amount": row["amount"],
            }
            for row in reversed(rows)
        ]

    def get_daily_bars_after(
        self, code: str, start_date: str, limit: int = 20
    ) -> list[dict]:
        """Return chronological bars strictly after a replay cutoff."""
        safe_limit = max(1, min(int(limit), 100))
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, open, high, low, close,
                          volume, amount, change_pct
                   FROM market_daily
                   WHERE ts_code=? AND trade_date>?
                   ORDER BY trade_date ASC
                   LIMIT ?""",
                (code, start_date, safe_limit),
            ).fetchall()
        return [
            {
                "date": row["trade_date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "amount": row["amount"],
            }
            for row in rows
        ]

    def get_latest_market_date_on_or_before(self, target_date: str) -> str:
        """Resolve a journal date to its latest observable trading date."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) AS trade_date FROM market_daily WHERE trade_date<=?",
                (target_date,),
            ).fetchone()
        return str(row["trade_date"] or "")

    def get_market_snapshot_for_date(self, trade_date: str) -> dict:
        """Build a historical A-share breadth snapshot from local bars."""
        if not trade_date:
            return {}
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN change_pct>0 THEN 1 ELSE 0 END) AS advancing,
                          SUM(CASE WHEN change_pct<0 THEN 1 ELSE 0 END) AS declining,
                          SUM(CASE WHEN change_pct=0 THEN 1 ELSE 0 END) AS unchanged,
                          SUM(CASE WHEN change_pct>=9.9 THEN 1 ELSE 0 END) AS limit_up,
                          SUM(CASE WHEN change_pct<=-9.9 THEN 1 ELSE 0 END) AS limit_down,
                          AVG(change_pct) AS average_change_pct,
                          SUM(amount) AS total_amount
                   FROM market_daily
                   WHERE trade_date=?
                     AND (
                         (ts_code LIKE '%.SH' AND substr(ts_code, 1, 3) IN
                             ('600', '601', '603', '605', '688', '689'))
                         OR
                         (ts_code LIKE '%.SZ' AND substr(ts_code, 1, 3) IN
                             ('000', '001', '002', '003', '300', '301'))
                     )""",
                (trade_date,),
            ).fetchone()
        total = int(row["total"] or 0)
        advancing = int(row["advancing"] or 0)
        return {
            "trade_date": trade_date,
            "total": total,
            "advancing": advancing,
            "declining": int(row["declining"] or 0),
            "unchanged": int(row["unchanged"] or 0),
            "limit_up": int(row["limit_up"] or 0),
            "limit_down": int(row["limit_down"] or 0),
            "average_change_pct": round(float(row["average_change_pct"] or 0), 3),
            "total_amount": float(row["total_amount"] or 0),
            "sentiment": round(advancing / total * 100, 1) if total else 0.0,
        }

    def get_replay_dates(self, limit: int = 60) -> list[dict]:
        """List journal dates that can be replayed against local market bars."""
        safe_limit = max(1, min(int(limit), 365))
        with self._get_conn() as conn:
            decision_rows = conn.execute(
                """SELECT decision_date,
                          COUNT(*) AS decisions,
                          COUNT(DISTINCT stock_code) AS stocks,
                          SUM(CASE WHEN LOWER(direction) IN ('buy', 'sell')
                              THEN 1 ELSE 0 END) AS decisive,
                          SUM(CASE WHEN outcome_known=1 THEN 1 ELSE 0 END) AS outcomes
                   FROM decision_journal
                   GROUP BY decision_date
                   ORDER BY decision_date DESC
                   LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            trading_dates = [
                str(row["trade_date"])
                for row in conn.execute(
                    "SELECT DISTINCT trade_date FROM market_daily ORDER BY trade_date"
                ).fetchall()
            ]

        result = []
        for row in decision_rows:
            decision_date = str(row["decision_date"])
            eligible = [value for value in trading_dates if value <= decision_date]
            market_date = eligible[-1] if eligible else ""
            future_sessions = sum(value > market_date for value in trading_dates) if market_date else 0
            result.append({
                "date": decision_date,
                "market_data_date": market_date,
                "decisions": int(row["decisions"] or 0),
                "stocks": int(row["stocks"] or 0),
                "decisive": int(row["decisive"] or 0),
                "recorded_outcomes": int(row["outcomes"] or 0),
                "future_sessions": future_sessions,
                "replay_ready": bool(market_date and row["stocks"]),
                "partial_evaluation_ready": future_sessions > 0,
                "evaluation_ready": future_sessions >= 5,
            })
        return result

    def save_replay_run(
        self,
        replay_date: str,
        mode: str,
        model_version: str,
        context_hash: str,
        result_hash: str,
        status: str,
        result: dict,
    ) -> int:
        """Persist one Replay/compare/simulation result across restarts."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO replay_run
                   (replay_date, mode, model_version, context_hash,
                    result_hash, status, result_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    replay_date,
                    mode,
                    model_version,
                    context_hash,
                    result_hash,
                    status,
                    json.dumps(result, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def get_replay_runs(self, limit: int = 50) -> list[dict]:
        """Return persisted Replay history, newest first."""
        safe_limit = max(1, min(int(limit), 200))
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM replay_run ORDER BY created_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json") or "{}")
            result.append(item)
        return result

    def get_latest_quote(self, code: str) -> dict | None:
        """Get latest quote from local DB."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT m.*, s.name, i.fusion_score, i.direction, i.confidence
                   FROM market_daily m
                   LEFT JOIN stock_basic s ON m.ts_code = s.ts_code
                   LEFT JOIN indicator_daily i
                     ON m.ts_code = i.ts_code AND m.trade_date = i.trade_date
                   WHERE m.ts_code=?
                   ORDER BY m.trade_date DESC
                   LIMIT 1""",
                (code,),
            ).fetchone()

            if row is None:
                return None

            return {
                "code": row["ts_code"],
                "name": row["name"] or code,
                "price": row["close"],
                "open": row["open"], "high": row["high"], "low": row["low"],
                "pre_close": row["pre_close"],
                "change_pct": row["change_pct"],
                "volume": row["volume"], "amount": row["amount"],
                "turnover": row["turnover"] or 0,
                "pe": 0, "pb": 0, "total_market_cap": 0,
                "data_date": row["trade_date"],
                "fusion_score": row["fusion_score"] or 50,
                "direction": row["direction"] or "neutral",
                "confidence": row["confidence"] or 0,
                "source": "local_db",
                "source_name": "本地数据库 (SQLite)",
            }

    def get_all_latest_quotes(
        self, codes: list[str] | None = None,
    ) -> list[dict]:
        """Get latest quotes for multiple stocks. Bulk query, very fast."""
        with self._get_conn() as conn:
            if codes:
                placeholders = ",".join("?" * len(codes))
                rows = conn.execute(
                    f"""SELECT m.ts_code, m.trade_date, m.close, m.change_pct,
                               m.volume, m.amount, s.name,
                               i.fusion_score, i.direction, i.confidence
                        FROM market_daily m
                        JOIN (
                            SELECT ts_code, MAX(trade_date) as max_date
                            FROM market_daily
                            WHERE ts_code IN ({placeholders})
                            GROUP BY ts_code
                        ) latest ON m.ts_code = latest.ts_code
                            AND m.trade_date = latest.max_date
                        LEFT JOIN stock_basic s ON m.ts_code = s.ts_code
                        LEFT JOIN indicator_daily i
                            ON m.ts_code = i.ts_code AND m.trade_date = i.trade_date""",
                    codes,
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT m.ts_code, m.trade_date, m.close, m.change_pct,
                              m.volume, m.amount, s.name,
                              i.fusion_score, i.direction, i.confidence
                       FROM market_daily m
                       JOIN (
                           SELECT ts_code, MAX(trade_date) as max_date
                           FROM market_daily GROUP BY ts_code
                       ) latest ON m.ts_code = latest.ts_code
                           AND m.trade_date = latest.max_date
                       LEFT JOIN stock_basic s ON m.ts_code = s.ts_code
                       LEFT JOIN indicator_daily i
                           ON m.ts_code = i.ts_code AND m.trade_date = i.trade_date""",
                ).fetchall()

        return [
            {
                "code": r["ts_code"],
                "name": r["name"] or r["ts_code"],
                "price": r["close"],
                "change_pct": r["change_pct"] or 0,
                "volume": r["volume"] or 0,
                "amount": r["amount"] or 0,
                "fusion_score": r["fusion_score"] or 50,
                "direction": r["direction"] or "neutral",
                "confidence": r["confidence"] or 0,
                "data_date": r["trade_date"],
            }
            for r in rows
        ]

    def get_indicator(
        self, code: str, days: int = 30
    ) -> list[dict]:
        """Get pre-computed indicator history."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT trade_date, macd_score, rsi_score, kdj_score,
                          ma_score, volume_score, fusion_score, direction
                   FROM indicator_daily
                   WHERE ts_code=?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (code, days),
            ).fetchall()

        return [dict(r) for r in reversed(rows)]

    # ================================================================
    # Decision Journal — AI decision persistence
    # ================================================================

    def save_decision(self, decision: dict) -> int:
        """Save an AI decision to the journal. Returns row id."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO decision_journal
                   (decision_date, stock_code, stock_name, ai_score,
                    direction, confidence, recommendation,
                    fusion_score, macd_score, rsi_score, kdj_score,
                    ma_score, volume_score, buy_signals, sell_signals,
                    evidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision.get("date", ""),
                    decision.get("stock_code", ""),
                    decision.get("stock_name", ""),
                    decision.get("ai_score", 50),
                    decision.get("direction", "neutral"),
                    decision.get("confidence", 0),
                    decision.get("recommendation", ""),
                    decision.get("fusion_score", 50),
                    decision.get("macd_score", 50),
                    decision.get("rsi_score", 50),
                    decision.get("kdj_score", 50),
                    decision.get("ma_score", 50),
                    decision.get("volume_score", 50),
                    decision.get("buy_signals", 0),
                    decision.get("sell_signals", 0),
                    decision.get("evidence", ""),
                    decision.get("signal_at") or datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    @staticmethod
    def _decision_journal_values(decision: dict) -> tuple[Any, ...]:
        """Build the legacy journal row without opening a database connection."""
        return (
            decision.get("date", ""),
            decision.get("stock_code", ""),
            decision.get("stock_name", ""),
            decision.get("ai_score", 50),
            decision.get("direction", "neutral"),
            decision.get("confidence", 0),
            decision.get("recommendation", ""),
            decision.get("fusion_score", 50),
            decision.get("macd_score", 50),
            decision.get("rsi_score", 50),
            decision.get("kdj_score", 50),
            decision.get("ma_score", 50),
            decision.get("volume_score", 50),
            decision.get("buy_signals", 0),
            decision.get("sell_signals", 0),
            decision.get("evidence", ""),
            decision.get("signal_at") or datetime.now().isoformat(),
        )

    @staticmethod
    def _strategy_analysis_payload(decision: dict) -> dict[str, Any]:
        """Build the model-audit payload shared by single and batch writes."""
        return {
            key: decision.get(key)
            for key in (
                "deep_analysis", "deep_thesis", "deep_trader_plan",
                "deep_analysis_available", "deep_analysis_error",
                "deep_provider", "deep_model", "deep_source", "deep_runtime",
                "deep_cached", "deep_duration_seconds", "deep_kline_evidence",
                "deep_input_fingerprint",
                "deep_evidence_consumption", "tradingagents_rating",
                "tradingagents_direction", "tradingagents_score",
                "preselection_input_sha256", "preselection_input_chars",
                "preselection_input_count", "preselection_input_fields",
                "preselection_provider", "preselection_model", "preselection_called",
                "final_review_required", "final_review_available",
                "final_review_verdict", "final_review_reason", "final_review_risk",
                "final_review_provider", "final_review_model",
                "final_review_fallback_used", "final_review_error",
                "final_review_input_sha256", "final_review_input_chars",
                "final_review_input_count", "final_review_input_fields",
                "final_buy_approved", "decision_status", "predicted_direction",
                "executable_direction", "raw_ai_score", "scanner_score",
                "preselection_base_score", "preselection_adjusted_score",
                "deep_base_score", "deep_score", "research_score", "primary_score",
                "primary_score_label", "ranking_score_label", "display_state",
                "display_state_label", "ranking_score", "action_score",
                "score_lineage", "score_guarded", "score_guard_reasons",
                "fundamental_evidence_available", "execution_evidence_complete",
                "market_evidence_complete", "market_evidence_sources",
                "market_evidence_reasons", "evidence_status", "actionability_status",
                "evidence_enrichment", "quote_enrichment_status",
                "quote_enrichment_reason", "quote_enrichment_ranking_score",
                "quote_enrichment_min_ranking_score", "publication_blocked",
                "publication_block_reasons", "recommendation_tier",
                "technical_data_through", "run_id", "strategy_name",
                "strategy_version", "config_snapshot", "config_hash", "code_hash",
                "run_created_at", "actionable", "deep_candidate_eligible",
                "deep_candidate_exclusion_reason", "pre_gate_direction",
                "final_direction", "flow_state", "flow_sources", "flow_source",
                "flow_status", "fallback_attempted", "fallback_status", "market_sources",
                "market_reasons", "market_flow", "market_price", "market_pre_close",
                "market_change_pct", "market_price_source", "market_price_date",
                "market_price_fetched_at", "market_price_exchange_at",
                "market_volume_ratio", "market_active_volume_ratio", "data_cutoff_at",
                "signal_at", "gate_reasons", "non_flow_gates_passed",
                "execution_disposition", "execution_block_reason",
                "execution_status_label", "execution_quote_verified", "evidence",
                "confidence", "fusion_score", "macd_score", "rsi_score", "kdj_score",
                "ma_score", "volume_score",
            )
            if decision.get(key) not in (None, "")
        }

    @classmethod
    def _strategy_decision_values(
        cls, decision: dict, journal_id: int | None = None
    ) -> tuple[Any, ...]:
        analysis = cls._strategy_analysis_payload(decision)
        strategy_name = (
            f"adaptive-paper:journal:{journal_id}"
            if journal_id is not None
            else f"adaptive-paper:standalone:{time.time_ns()}"
        )
        return (
            journal_id, decision.get("date", ""), decision.get("stock_code", ""),
            strategy_name, decision.get("strategy_version") or "2.1",
            decision.get("technical_score", decision.get("ai_score", 50)),
            decision.get("deep_rating", ""), decision.get("direction", "neutral"),
            json.dumps(analysis, ensure_ascii=False), datetime.now().isoformat(),
        )

    @classmethod
    def _insert_strategy_decision(
        cls, conn: sqlite3.Connection, decision: dict, journal_id: int | None = None
    ) -> int | None:
        cursor = conn.execute(
            """INSERT OR REPLACE INTO strategy_decision
               (journal_id, decision_date, stock_code, strategy_name,
                strategy_version, technical_score, deep_rating,
                effective_direction, analysis_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            cls._strategy_decision_values(decision, journal_id),
        )
        return int(cursor.lastrowid) if cursor.lastrowid is not None else None

    def save_decisions_batch(self, decisions: list[dict]) -> list[int]:
        """Persist a final decision batch in one transaction.

        The old caller opened and committed a new SQLite connection for every
        journal and strategy row.  This keeps the same row shapes and IDs while
        reducing hundreds of write transactions to one atomic transaction.

        Several scans run each day, so the same ``(decision_date, stock_code)``
        previously reached this table once per scan and multiplied every call
        4-7x.  The existing row is updated in place instead, which preserves its
        ``id``: ``strategy_decision.journal_id`` points at that id, so
        ``INSERT OR REPLACE`` would change it and orphan the child row.  A
        stable id is also what finally lets ``strategy_decision`` dedupe, since
        its ``strategy_name`` is derived from ``journal_id`` and a fresh id per
        scan defeated UNIQUE(decision_date, stock_code, strategy_name).  Outcome
        columns are deliberately untouched so a backfilled return survives a
        later scan of the same day.
        """
        if not decisions:
            return []
        journal_ids: list[int] = []
        with self._get_conn() as conn:
            for decision in decisions:
                values = self._decision_journal_values(decision)
                existing = conn.execute(
                    """SELECT id FROM decision_journal
                       WHERE decision_date=? AND stock_code=?
                       ORDER BY id DESC LIMIT 1""",
                    (values[0], values[1]),
                ).fetchone()
                if existing is None:
                    cursor = conn.execute(
                        """INSERT INTO decision_journal
                           (decision_date, stock_code, stock_name, ai_score,
                            direction, confidence, recommendation,
                            fusion_score, macd_score, rsi_score, kdj_score,
                            ma_score, volume_score, buy_signals, sell_signals,
                            evidence, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        values,
                    )
                    journal_id = int(cursor.lastrowid)
                else:
                    journal_id = int(existing["id"])
                    conn.execute(
                        """UPDATE decision_journal
                           SET stock_name=?, ai_score=?, direction=?, confidence=?,
                               recommendation=?, fusion_score=?, macd_score=?,
                               rsi_score=?, kdj_score=?, ma_score=?, volume_score=?,
                               buy_signals=?, sell_signals=?, evidence=?, created_at=?
                           WHERE id=?""",
                        (*values[2:], journal_id),
                    )
                journal_ids.append(journal_id)
                self._insert_strategy_decision(conn, decision, journal_id)
        return journal_ids

    def save_strategy_decisions_batch(self, decisions: list[dict]) -> int:
        """Persist post-execution audit fields in one transaction."""
        if not decisions:
            return 0
        stored = 0
        with self._get_conn() as conn:
            for decision in decisions:
                journal_id = decision.get("journal_id")
                if journal_id is None:
                    continue
                self._insert_strategy_decision(conn, decision, int(journal_id))
                stored += 1
        return stored

    def get_recent_decisions(self, limit: int = 50) -> list[dict]:
        """Get recent AI decisions from the journal."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT d.*, s.deep_rating, s.effective_direction,
                          s.analysis_json AS strategy_analysis_json
                   FROM decision_journal d
                   LEFT JOIN strategy_decision s ON s.journal_id=d.id
                   ORDER BY d.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            analysis = json.loads(item.pop("strategy_analysis_json") or "{}")
            item["deep_analysis"] = analysis.get("deep_analysis", "")
            item["deep_thesis"] = analysis.get("deep_thesis", "")
            item["deep_trader_plan"] = analysis.get("deep_trader_plan", "")
            item["deep_kline_evidence"] = analysis.get("deep_kline_evidence") or {}
            item["deep_analysis_available"] = bool(item.get("deep_rating"))
            for key in (
                "deep_provider", "deep_model", "deep_source", "deep_runtime",
                "tradingagents_rating", "tradingagents_direction",
                "final_review_required", "final_review_available",
                "final_review_verdict", "final_review_reason", "final_review_risk",
                "final_review_provider", "final_review_model",
                "final_review_fallback_used", "final_review_error",
                "preselection_input_sha256", "preselection_input_chars",
                "preselection_input_count", "preselection_input_fields",
                "preselection_provider", "preselection_model", "preselection_called",
                "final_review_input_sha256", "final_review_input_chars",
                "final_review_input_count", "final_review_input_fields",
                "final_buy_approved",
                "decision_status",
                "predicted_direction", "executable_direction",
                "raw_ai_score", "scanner_score", "preselection_base_score",
                "preselection_adjusted_score", "deep_base_score", "deep_score",
                "research_score", "primary_score", "primary_score_label",
                "ranking_score_label", "display_state", "display_state_label",
                "ranking_score", "action_score", "score_lineage",
                "score_guarded", "score_guard_reasons",
                "fundamental_evidence_available", "execution_evidence_complete",
                "market_evidence_complete", "market_evidence_sources",
                "market_evidence_reasons", "evidence_status", "actionability_status",
                "evidence_enrichment",
                "quote_enrichment_status", "quote_enrichment_reason",
                "quote_enrichment_ranking_score",
                "quote_enrichment_min_ranking_score",
                "publication_blocked", "publication_block_reasons",
                "recommendation_tier", "technical_data_through",
                "run_id", "strategy_name", "strategy_version",
                "config_snapshot", "config_hash", "code_hash", "run_created_at",
                "actionable", "deep_candidate_eligible",
                "deep_candidate_exclusion_reason",
                "pre_gate_direction", "final_direction", "flow_state",
                "flow_sources", "flow_source", "flow_status", "fallback_attempted",
                "fallback_status", "market_sources", "market_reasons",
                "market_flow", "market_price", "market_pre_close",
                "market_change_pct", "market_price_source", "market_price_date",
                "market_price_fetched_at", "market_price_exchange_at",
                "market_volume_ratio", "market_active_volume_ratio",
                "data_cutoff_at", "signal_at",
                "gate_reasons", "non_flow_gates_passed",
                "execution_disposition", "execution_block_reason",
                "execution_status_label", "execution_quote_verified",
            ):
                item[key] = analysis.get(key)
            result.append(item)
        return result

    def get_recent_decision_summaries(self, limit: int = 50) -> list[dict]:
        """Load the fields needed by read-only ranking/continuity views.

        The full decision reader intentionally retains the raw evidence and
        complete strategy payload for research consumers.  Scanner views only
        need a small projection of those records; keeping that projection in
        SQL prevents a large historical read from materializing thousands of
        nested evidence payloads in the API process.
        """
        safe_limit = max(1, min(int(limit), 5000))
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT d.id, d.decision_date, d.stock_code, d.stock_name,
                          d.ai_score, d.direction, d.confidence, d.recommendation,
                          d.fusion_score, d.macd_score, d.rsi_score, d.kdj_score,
                          d.ma_score, d.volume_score, d.buy_signals, d.sell_signals,
                          d.created_at, s.technical_score, s.deep_rating,
                          s.effective_direction,
                          json_extract(s.analysis_json, '$.deep_analysis') AS deep_analysis,
                          json_extract(s.analysis_json, '$.deep_thesis') AS deep_thesis,
                          json_extract(s.analysis_json, '$.deep_trader_plan') AS deep_trader_plan,
                          json_extract(s.analysis_json, '$.deep_analysis_error') AS deep_analysis_error,
                          json_extract(s.analysis_json, '$.final_review_reason') AS final_review_reason,
                          json_extract(s.analysis_json, '$.final_review_risk') AS final_review_risk,
                          json_extract(s.analysis_json, '$.execution_evidence_complete') AS execution_evidence_complete,
                          json_extract(s.analysis_json, '$.score_guard_reasons') AS score_guard_reasons,
                          json_extract(s.analysis_json, '$.publication_blocked') AS publication_blocked,
                          json_extract(s.analysis_json, '$.decision_status') AS decision_status,
                          json_extract(s.analysis_json, '$.ranking_score') AS ranking_score,
                          json_extract(s.analysis_json, '$.raw_ai_score') AS raw_ai_score,
                          json_extract(s.analysis_json, '$.action_score') AS action_score,
                          json_extract(s.analysis_json, '$.research_score') AS research_score,
                          json_extract(s.analysis_json, '$.deep_score') AS deep_score,
                          json_extract(s.analysis_json, '$.score_guarded') AS score_guarded,
                          json_extract(s.analysis_json, '$.final_buy_approved') AS final_buy_approved,
                          json_extract(s.analysis_json, '$.execution_disposition') AS execution_disposition,
                          json_extract(s.analysis_json, '$.execution_quote_verified') AS execution_quote_verified,
                          json_extract(s.analysis_json, '$.market_evidence_sources') AS market_evidence_sources,
                          json_extract(s.analysis_json, '$.market_evidence_reasons') AS market_evidence_reasons,
                          json_extract(s.analysis_json, '$.evidence_enrichment') AS evidence_enrichment,
                          json_extract(s.analysis_json, '$.quote_enrichment_status') AS quote_enrichment_status,
                          json_extract(s.analysis_json, '$.quote_enrichment_reason') AS quote_enrichment_reason,
                          json_extract(s.analysis_json, '$.evidence_status') AS evidence_status,
                          json_extract(s.analysis_json, '$.publication_block_reasons') AS publication_block_reasons,
                          json_extract(s.analysis_json, '$.discovery_score') AS discovery_score,
                          json_extract(s.analysis_json, '$.final_direction') AS final_direction,
                          json_extract(s.analysis_json, '$.recommendation_tier') AS recommendation_tier
                     FROM decision_journal d
                     LEFT JOIN strategy_decision s ON s.journal_id=d.id
                    ORDER BY d.created_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()

        def decode_fragment(value: Any, default: Any) -> Any:
            if value in (None, ""):
                return default
            if isinstance(value, (list, dict)):
                return value
            try:
                return json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return default

        list_fields = {
            "score_guard_reasons",
            "market_evidence_sources",
            "market_evidence_reasons",
            "publication_block_reasons",
        }
        dict_fields = {"evidence_enrichment"}
        result = []
        for row in rows:
            item = dict(row)
            for field in list_fields:
                item[field] = decode_fragment(item.get(field), [])
            for field in dict_fields:
                item[field] = decode_fragment(item.get(field), {})
            item["deep_analysis_available"] = bool(item.get("deep_rating"))
            result.append(item)
        return result

    def get_stock_name(self, code: str) -> str:
        """Return one stock name without loading the decision journal payload."""
        normalized = str(code or "").strip().upper()
        if not normalized:
            return ""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT stock_name FROM decision_journal
                   WHERE stock_code=? AND COALESCE(stock_name, '') <> ''
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (normalized,),
            ).fetchone()
        return str(row["stock_name"] or "") if row else ""

    def get_decisions_for_date(self, decision_date: str, limit: int = 500) -> list[dict]:
        """Return journal decisions for one exact trading date."""
        safe_limit = max(1, min(int(limit), 5000))
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT d.*, s.deep_rating, s.effective_direction,
                          s.analysis_json AS strategy_analysis_json
                   FROM decision_journal d
                   LEFT JOIN strategy_decision s ON s.journal_id=d.id
                   WHERE d.decision_date=?
                   ORDER BY d.created_at DESC, d.id DESC LIMIT ?""",
                (decision_date, safe_limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            analysis = json.loads(item.pop("strategy_analysis_json") or "{}")
            item["deep_analysis"] = analysis.get("deep_analysis", "")
            item["deep_thesis"] = analysis.get("deep_thesis", "")
            item["deep_trader_plan"] = analysis.get("deep_trader_plan", "")
            item["deep_kline_evidence"] = analysis.get("deep_kline_evidence") or {}
            item["deep_analysis_available"] = bool(item.get("deep_rating"))
            for key in (
                "deep_provider", "deep_model", "deep_source", "deep_runtime",
                "tradingagents_rating", "tradingagents_direction",
                "final_review_required", "final_review_available",
                "final_review_verdict", "final_review_reason", "final_review_risk",
                 "final_review_provider", "final_review_model",
                 "final_review_fallback_used", "final_review_error",
                 "preselection_input_sha256", "preselection_input_chars",
                 "preselection_input_count", "preselection_input_fields",
                 "preselection_provider", "preselection_model", "preselection_called",
                 "final_review_input_sha256", "final_review_input_chars",
                 "final_review_input_count", "final_review_input_fields",
                 "final_buy_approved",
                 "decision_status",
                 "predicted_direction", "executable_direction",
                 "raw_ai_score", "scanner_score", "preselection_base_score",
                 "preselection_adjusted_score", "deep_base_score", "deep_score",
                 "research_score", "primary_score", "primary_score_label",
                 "ranking_score_label", "display_state", "display_state_label",
                 "ranking_score", "action_score", "score_lineage",
                 "score_guarded", "score_guard_reasons",
                 "fundamental_evidence_available", "execution_evidence_complete",
                 "market_evidence_complete", "market_evidence_sources",
                 "market_evidence_reasons", "evidence_status", "actionability_status",
                 "evidence_enrichment",
                 "quote_enrichment_status", "quote_enrichment_reason",
                 "quote_enrichment_ranking_score",
                 "quote_enrichment_min_ranking_score",
                 "publication_blocked", "publication_block_reasons",
                 "recommendation_tier", "technical_data_through",
                 "run_id", "strategy_name", "strategy_version",
                 "config_snapshot", "config_hash", "code_hash", "run_created_at",
                 "actionable", "deep_candidate_eligible",
                 "deep_candidate_exclusion_reason",
                 "pre_gate_direction", "final_direction", "flow_state",
                 "flow_sources", "flow_source", "flow_status", "fallback_attempted",
                 "fallback_status", "market_sources", "market_reasons",
                 "market_flow", "market_price", "market_pre_close",
                 "market_change_pct", "market_price_source", "market_price_date",
                 "market_price_fetched_at", "market_price_exchange_at",
                 "market_volume_ratio", "market_active_volume_ratio",
                 "data_cutoff_at", "signal_at",
                 "gate_reasons", "non_flow_gates_passed",
                 "execution_disposition", "execution_block_reason",
                 "execution_status_label", "execution_quote_verified",
             ):
                item[key] = analysis.get(key)
            result.append(item)
        return result

    def count_decisions_for_date(self, decision_date: str) -> int:
        """Return a lightweight journal count without loading analysis JSON."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM decision_journal WHERE decision_date=?",
                (decision_date,),
            ).fetchone()
        return int(row["n"] if row else 0)

    def get_decision_history_for_codes(
        self, codes: list[str], limit_per_code: int = 2
    ) -> dict[str, list[dict[str, Any]]]:
        """Return the newest journal decisions for each requested stock.

        Portfolio consumers need the latest decision for an explicitly held
        symbol.  ``get_recent_decisions`` is intentionally bounded and is
        therefore not sufficient when the journal contains many decisions for
        other symbols.  Keep the query scoped to the requested codes and
        preserve chronological order so callers can calculate score changes.
        """
        normalized = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
        if not normalized:
            return {}
        # Portfolio callers normally request only two rows, while Timeline
        # needs enough observations to collapse multiple intraday pipeline
        # runs into a real multi-day history. Keep a defensive upper bound
        # without silently truncating Timeline to 20 observations.
        safe_limit = max(1, min(int(limit_per_code), 1000))
        placeholders = ", ".join("?" for _ in normalized)
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM decision_journal
                    WHERE UPPER(stock_code) IN ({placeholders})
                    ORDER BY created_at DESC, id DESC""",
                normalized,
            ).fetchall()

        history: dict[str, list[dict[str, Any]]] = {code: [] for code in normalized}
        for row in rows:
            item = dict(row)
            code = str(item.get("stock_code") or "").strip().upper()
            if code not in history or len(history[code]) >= safe_limit:
                continue
            history[code].append(item)
        return history

    def get_decision_stats(self) -> dict:
        """Get journal statistics without mixing abstentions into accuracy.

        ``neutral``/``hold`` rows are candidate evaluations and remain useful
        audit observations.  Only explicit BUY/SELL calls can validate stock
        selection direction, so they form the accuracy denominator.
        """
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) as n FROM decision_journal"
            ).fetchone()["n"]
            decisive_total = conn.execute(
                """SELECT COUNT(*) as n FROM decision_journal
                   WHERE LOWER(TRIM(COALESCE(direction, ''))) IN ('buy', 'sell')"""
            ).fetchone()["n"]
            verified = conn.execute(
                "SELECT COUNT(*) as n FROM decision_journal WHERE outcome_known=1"
            ).fetchone()["n"]
            correct = conn.execute(
                "SELECT COUNT(*) as n FROM decision_journal WHERE outcome_known=1 AND was_correct=1"
            ).fetchone()["n"]
            decisive_verified = conn.execute(
                """SELECT COUNT(*) as n FROM decision_journal
                   WHERE outcome_known=1
                     AND LOWER(TRIM(COALESCE(direction, ''))) IN ('buy', 'sell')"""
            ).fetchone()["n"]
            decisive_correct = conn.execute(
                """SELECT COUNT(*) as n FROM decision_journal
                   WHERE outcome_known=1 AND was_correct=1
                     AND LOWER(TRIM(COALESCE(direction, ''))) IN ('buy', 'sell')"""
            ).fetchone()["n"]
            by_direction = conn.execute(
                """SELECT LOWER(COALESCE(NULLIF(TRIM(direction), ''), 'neutral')) AS direction,
                          COUNT(*) as n,
                          SUM(CASE WHEN was_correct=1 THEN 1 ELSE 0 END) as correct
                   FROM decision_journal WHERE outcome_known=1
                   GROUP BY LOWER(COALESCE(NULLIF(TRIM(direction), ''), 'neutral'))"""
            ).fetchall()

        return {
            "total_decisions": total,
            "decisive_decisions": decisive_total,
            "neutral_decisions": max(0, total - decisive_total),
            "verified_decisions": verified,
            "correct_decisions": correct,
            "decisive_verified_decisions": decisive_verified,
            "decisive_correct_decisions": decisive_correct,
            "neutral_verified_decisions": max(0, verified - decisive_verified),
            "accuracy_available": decisive_verified > 0,
            "accuracy_status": "available" if decisive_verified > 0 else "insufficient_samples",
            "accuracy": (
                round(decisive_correct / decisive_verified, 3)
                if decisive_verified > 0 else 0
            ),
            "all_verified_outcome_match_rate": round(correct / verified, 3) if verified > 0 else 0,
            "by_direction": [
                {
                    "direction": r["direction"],
                    "count": r["n"],
                    "correct": r["correct"] or 0,
                    "match_rate": round((r["correct"] or 0) / r["n"], 3) if r["n"] else 0,
                }
                for r in by_direction
            ],
        }

    # ================================================================
    # Persistent paper portfolio and learning loop
    # ================================================================

    def ensure_paper_account(self, initial_capital: float = 100000.0) -> None:
        """Create the paper account once; never reset it on restart."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO paper_account
                   (id, initial_capital, cash, created_at, updated_at,
                    commission_rate, stamp_tax_rate, fee_policy, execution_policy)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    initial_capital, initial_capital, now, now,
                    float(COMMISSION_RATE), float(STAMP_TAX_RATE), FEE_POLICY,
                    "post_signal_fresh_exchange_quote_v1",
                ),
            )

    def get_paper_positions(self) -> list[dict[str, Any]]:
        """Return raw paper positions without applying a market-data fallback."""
        self.ensure_paper_account()
        with self._get_conn() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM paper_position WHERE shares > 0 ORDER BY stock_code"
                )
            ]

    def mark_paper_portfolio(
        self,
        snapshot_date: str,
        quotes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist one auditable end-of-day mark and calculate daily P/L.

        ``quotes`` must be real provider responses keyed by normalized stock code.
        Missing quotes fall back to the local warehouse, but are explicitly marked
        stale so the API cannot silently present an old close as today's value.
        """
        self.ensure_paper_account()
        now = datetime.now().isoformat()
        positions = self.get_paper_positions()
        local_quotes = {
            position["stock_code"]: self.get_latest_quote(position["stock_code"]) or {}
            for position in positions
        }

        with self._get_conn() as conn:
            account = dict(conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone())
            previous = conn.execute(
                """SELECT total_value FROM paper_portfolio_snapshot
                   WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1""",
                (snapshot_date,),
            ).fetchone()

            market_value = 0.0
            prior_market_value = 0.0
            market_pnl = 0.0
            fresh_count = 0
            stale_positions: list[str] = []
            sources: set[str] = set()

            for position in positions:
                code = str(position["stock_code"])
                supplied = quotes.get(code) or {}
                local = local_quotes.get(code) or {}
                supplied_price = float(supplied.get("price") or 0)
                price = supplied_price or float(local.get("price") or position["avg_cost"])
                pre_close = float(
                    supplied.get("pre_close")
                    or local.get("pre_close")
                    or price
                )
                price_date = str(
                    supplied.get("data_date")
                    or supplied.get("price_date")
                    or local.get("data_date")
                    or ""
                )
                source = str(
                    supplied.get("source")
                    or supplied.get("price_source")
                    or local.get("source")
                    or "unavailable"
                )
                fetched_at = str(supplied.get("fetched_at") or now)
                is_fresh = bool(supplied_price > 0 and price_date == snapshot_date)
                shares = int(position["shares"])
                value = shares * price
                position_daily_pl = shares * (price - pre_close)

                market_value += value
                prior_market_value += shares * pre_close
                market_pnl += position_daily_pl
                sources.add(source)
                if is_fresh:
                    fresh_count += 1
                else:
                    stale_positions.append(code)

                conn.execute(
                    """INSERT INTO paper_position_mark(
                           mark_date, stock_code, shares, price, pre_close,
                           market_value, daily_pl, price_date, price_source,
                           fetched_at, is_fresh
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(mark_date, stock_code) DO UPDATE SET
                           shares=excluded.shares,
                           price=excluded.price,
                           pre_close=excluded.pre_close,
                           market_value=excluded.market_value,
                           daily_pl=excluded.daily_pl,
                           price_date=excluded.price_date,
                           price_source=excluded.price_source,
                           fetched_at=excluded.fetched_at,
                           is_fresh=excluded.is_fresh""",
                    (
                        snapshot_date, code, shares, price, pre_close, value,
                        position_daily_pl, price_date, source, fetched_at,
                        int(is_fresh),
                    ),
                )

            cash = float(account["cash"])
            total_value = cash + market_value
            if previous is not None:
                baseline_value = float(previous["total_value"])
            else:
                baseline_value = cash + prior_market_value
            daily_pl = total_value - baseline_value
            daily_pl_pct = daily_pl / baseline_value * 100 if baseline_value else 0.0
            coverage = fresh_count / len(positions) if positions else 1.0
            financials = conn.execute(
                """SELECT COUNT(*) AS trade_count,
                          COALESCE(SUM(fee), 0) AS fees,
                          COALESCE(SUM(realized_pnl), 0) AS realized_pnl
                   FROM paper_trade WHERE trade_date=?""",
                (snapshot_date,),
            ).fetchone()
            trade_count = int(financials["trade_count"] or 0)
            fees = float(financials["fees"] or 0)
            trade_rows = conn.execute(
                """SELECT action, stock_code, shares, price
                   FROM paper_trade WHERE trade_date=?""",
                (snapshot_date,),
            ).fetchall()
            trade_pnl_bridge = 0.0
            realized_pnl = 0.0
            trade_attribution_complete = True
            for trade in trade_rows:
                code = str(trade["stock_code"] or "")
                quote = quotes.get(code) or local_quotes.get(code) or {}
                pre_close = float(quote.get("pre_close") or quote.get("prev_close") or 0)
                if pre_close <= 0:
                    trade_attribution_complete = False
                    continue
                shares = int(trade["shares"] or 0)
                price = float(trade["price"] or 0)
                if str(trade["action"] or "").upper() == "BUY":
                    bridge = shares * (pre_close - price)
                else:
                    bridge = shares * (price - pre_close)
                    realized_pnl += bridge
                trade_pnl_bridge += bridge
            expected_daily_pl = market_pnl + trade_pnl_bridge - fees
            reconciliation_delta = daily_pl - expected_daily_pl
            reconciliation_status = (
                "incomplete_marks" if stale_positions else
                "incomplete_trade_attribution"
                if trade_count and not trade_attribution_complete else
                "pass" if abs(reconciliation_delta) <= 0.01 else "mismatch"
            )

            conn.execute(
                """INSERT INTO paper_portfolio_snapshot(
                       snapshot_date, cash, market_value, total_value, daily_pl,
                       daily_pl_pct, market_pnl, realized_pnl, trade_pnl_bridge,
                       fees, equity_change,
                       reconciliation_delta, reconciliation_status, price_coverage,
                       price_sources_json, stale_positions_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(snapshot_date) DO UPDATE SET
                       cash=excluded.cash,
                       market_value=excluded.market_value,
                       total_value=excluded.total_value,
                       daily_pl=excluded.daily_pl,
                       daily_pl_pct=excluded.daily_pl_pct,
                       market_pnl=excluded.market_pnl,
                       realized_pnl=excluded.realized_pnl,
                       trade_pnl_bridge=excluded.trade_pnl_bridge,
                       fees=excluded.fees,
                       equity_change=excluded.equity_change,
                       reconciliation_delta=excluded.reconciliation_delta,
                       reconciliation_status=excluded.reconciliation_status,
                       price_coverage=excluded.price_coverage,
                       price_sources_json=excluded.price_sources_json,
                       stale_positions_json=excluded.stale_positions_json,
                       updated_at=excluded.updated_at""",
                (
                    snapshot_date, cash, market_value, total_value, daily_pl,
                    daily_pl_pct, market_pnl, realized_pnl, trade_pnl_bridge,
                    fees, daily_pl,
                    reconciliation_delta, reconciliation_status, coverage,
                    json.dumps(sorted(sources), ensure_ascii=False),
                    json.dumps(stale_positions, ensure_ascii=False), now, now,
                ),
            )

        return {
            "snapshot_date": snapshot_date,
            "position_count": len(positions),
            "fresh_position_count": fresh_count,
            "price_coverage": coverage,
            "stale_positions": stale_positions,
            "price_sources": sorted(sources),
            "total_value": total_value,
            "daily_pl": daily_pl,
            "daily_pl_pct": daily_pl_pct,
            "market_pnl": market_pnl,
            "realized_pnl": realized_pnl,
            "trade_pnl_bridge": trade_pnl_bridge,
            "fees": fees,
            "equity_change": daily_pl,
            "reconciliation_delta": reconciliation_delta,
            "reconciliation_status": reconciliation_status,
        }

    @staticmethod
    def _execution_session_status(
        trade_date: str,
        execution_timestamp: str | None,
    ) -> tuple[bool, str, str]:
        """Allow simulated fills only during a real A-share trading session."""
        raw_timestamp = execution_timestamp or datetime.now().astimezone().isoformat()
        execution_at = parse_timestamp(raw_timestamp)
        if execution_at is None:
            return False, "invalid_execution_timestamp", raw_timestamp
        execution_at = execution_at.astimezone(CHINA_TZ)
        if execution_at.date().isoformat() != trade_date:
            return False, "execution_date_mismatch", execution_at.isoformat()
        if execution_at.weekday() >= 5:
            return False, "weekend", execution_at.isoformat()
        in_session = in_a_share_session(execution_at)
        return (
            in_session,
            "verified_market_session" if in_session else "market_closed",
            execution_at.isoformat(),
        )

    @staticmethod
    def _verified_execution_quote(
        decision: dict,
        trade_date: str,
    ) -> tuple[dict | None, str]:
        """Independently enforce post-signal quote causality before a fill."""
        # Pipeline quote acquisition records the precise causal rejection on
        # the decision.  Return it before inspecting blank quote fields so the
        # audit ledger does not mislabel a provider miss as a stale date.
        recorded_rejection = str(
            decision.get("execution_quote_rejection_reason") or ""
        ).strip()
        if recorded_rejection:
            return None, recorded_rejection
        price = float(decision.get("market_price") or 0)
        price_date = str(decision.get("market_price_date") or "")
        source = str(decision.get("market_price_source") or "").strip()
        fetched_at = str(decision.get("market_price_fetched_at") or "")
        if not price_date and not source and not fetched_at:
            # No quote was ever acquired for this decision.  The pipeline only
            # fills these fields for the candidates it selected for a live
            # fetch, so a blank set means "never attempted", not "stale".  It
            # used to be reported as a stale date, which named the wrong cause
            # for roughly half of all rejections.
            return None, "quote_never_fetched"
        if price_date != trade_date:
            return None, "stale_or_future_quote_date"
        verified, reason = validate_post_signal_quote(
            decision,
            {
                "price": price,
                "data_date": price_date,
                "source": source,
                "fetched_at": fetched_at,
                "exchange_timestamp": decision.get("market_price_exchange_at"),
            },
        )
        if verified is None:
            return None, reason
        return {
            "price": price,
            "price_date": price_date,
            "price_source": source,
            "fetched_at": verified["fetched_at"],
            "exchange_at": verified["exchange_at"],
            "source_lag_seconds": verified["source_lag_seconds"],
            "causality_status": verified["causality_status"],
        }, reason

    def get_paper_ledger_state(self) -> dict:
        """Return the full active paper ledger for audit/rebuild tooling."""
        self.ensure_paper_account()
        with self._get_conn() as conn:
            account = dict(conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone())
            tables = {}
            for table in (
                "paper_position",
                "paper_trade",
                "paper_position_mark",
                "paper_portfolio_snapshot",
            ):
                tables[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        return {"account": account, **tables}

    def get_paper_trades(
        self,
        limit: int = 100,
        stock_code: str = "",
        action: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> list[dict[str, Any]]:
        """Query the auditable paper-trade timeline with explicit cash costs."""
        self.ensure_paper_account()
        self.repair_paper_trade_decision_links()
        clauses: list[str] = []
        params: list[Any] = []
        if stock_code:
            clauses.append("stock_code = ?")
            params.append(stock_code.strip().upper())
        normalized_action = action.strip().upper()
        if normalized_action:
            if normalized_action not in {"BUY", "SELL"}:
                raise ValueError("action must be BUY or SELL")
            clauses.append("action = ?")
            params.append(normalized_action)
        if date_from:
            clauses.append("trade_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("trade_date <= ?")
            params.append(date_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(int(limit), 500))
        params.append(safe_limit)
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM paper_trade {where}
                    ORDER BY created_at DESC, id DESC LIMIT ?""",
                params,
            ).fetchall()

        trades: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            value = float(row.get("value") or 0)
            total_fees = float(row.get("fee") or 0)
            direction = str(row.get("action") or "").upper()
            causality_status = str(row.get("causality_status") or "legacy_unverified")
            row.update({
                "signal_at": row.get("signal_at") or row.get("created_at") or "",
                "signal_time_type": "strategy_signal_only_not_an_order_or_fill",
                "execution_at": row.get("created_at") or "",
                "execution_time_type": (
                    "post_signal_live_snapshot_simulated_fill"
                    if causality_status == "verified_post_signal_quote"
                    else "historical_bar_replay"
                    if causality_status == "verified_historical_bar_replay"
                    else "legacy_or_unverified_simulated_fill"
                ),
                "gross_amount": value,
                "commission": float(row.get("commission") or 0),
                "stamp_tax": float(row.get("stamp_tax") or 0),
                "total_fees": total_fees,
                "net_cash_flow": (
                    -(value + total_fees)
                    if direction == "BUY"
                    else value - total_fees
                ),
            })
            trades.append(row)
        return trades

    def repair_paper_trade_decision_links(self) -> dict[str, int]:
        """Backfill only unambiguous links from fills to journal decisions.

        A paper fill is linked to the decision whose immutable signal timestamp
        exactly matches ``paper_trade.signal_at``.  We deliberately do not use
        a fuzzy stock/date match: a stock can have multiple scans on one day.
        """
        with self._get_conn() as conn:
            candidates = conn.execute(
                """SELECT t.id, d.id AS decision_id
                   FROM paper_trade t
                   JOIN decision_journal d
                     ON d.stock_code=t.stock_code
                    AND d.created_at=t.signal_at
                   WHERE t.decision_id IS NULL
                   ORDER BY t.id"""
            ).fetchall()
            linked = 0
            for row in candidates:
                updated = conn.execute(
                    """UPDATE paper_trade SET decision_id=?
                       WHERE id=? AND decision_id IS NULL""",
                    (int(row["decision_id"]), int(row["id"])),
                )
                linked += int(updated.rowcount or 0)
            remaining = int(conn.execute(
                "SELECT COUNT(*) FROM paper_trade WHERE decision_id IS NULL"
            ).fetchone()[0])
        return {"linked": linked, "remaining_unlinked": remaining}

    def get_paper_order_rejections(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent blocked fills so non-trading outcomes remain auditable."""
        safe_limit = max(1, min(int(limit), 500))
        with self._get_conn() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT * FROM paper_order_rejection
                       ORDER BY id DESC LIMIT ?""",
                    (safe_limit,),
                )
            ]

    def apply_paper_fee_policy(self) -> dict[str, Any]:
        """Archive and migrate all active paper fills to the configured fees."""
        self.ensure_paper_account()
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            account = dict(conn.execute(
                "SELECT * FROM paper_account WHERE id=1"
            ).fetchone())
            trades = [dict(row) for row in conn.execute(
                "SELECT * FROM paper_trade ORDER BY id"
            )]
            if account.get("fee_policy") == FEE_POLICY and all(
                trade.get("signal_at") for trade in trades
            ):
                return {
                    "status": "already_applied",
                    "fee_policy": FEE_POLICY,
                    "trade_count": len(trades),
                    "cash": round(float(account["cash"]), 2),
                }

            legacy_signal_times: dict[int, str] = {}
            for archive_row in conn.execute(
                "SELECT payload_json FROM paper_ledger_archive ORDER BY id"
            ):
                try:
                    payload = json.loads(archive_row["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                for legacy_trade in payload.get("paper_trade") or []:
                    legacy_id = legacy_trade.get("id")
                    if legacy_id is not None and legacy_trade.get("created_at"):
                        legacy_signal_times.setdefault(
                            int(legacy_id), str(legacy_trade["created_at"])
                        )
            decision_signal_times = {
                int(row["id"]): str(row["created_at"])
                for row in conn.execute(
                    "SELECT id, created_at FROM decision_journal"
                )
            }

            changes: list[dict[str, Any]] = []
            for trade in trades:
                costs = calculate_trade_costs(trade["value"], trade["action"])
                old_fee = float(trade.get("fee") or 0)
                new_fee = costs["total_fees"]
                legacy_id = trade.get("legacy_trade_id")
                decision_id = trade.get("decision_id")
                signal_at = (
                    trade.get("signal_at")
                    or (
                        legacy_signal_times.get(int(legacy_id), "")
                        if legacy_id is not None
                        else ""
                    )
                    or (
                        decision_signal_times.get(int(decision_id), "")
                        if decision_id is not None
                        else ""
                    )
                    or trade.get("created_at")
                    or now
                )
                changes.append({
                    "id": int(trade["id"]),
                    "trade_date": str(trade["trade_date"]),
                    "old_fee": old_fee,
                    "new_fee": new_fee,
                    "delta": new_fee - old_fee,
                    "commission": costs["commission"],
                    "stamp_tax": costs["stamp_tax"],
                    "signal_at": signal_at,
                })

            total_delta = sum(change["delta"] for change in changes)
            new_cash = float(account["cash"]) - total_delta
            if new_cash < -0.005:
                raise ValueError("fee-policy migration would make paper cash negative")

            archived = {"account": account}
            for table in (
                "paper_position",
                "paper_trade",
                "paper_position_mark",
                "paper_portfolio_snapshot",
            ):
                archived[table] = [
                    dict(row) for row in conn.execute(f"SELECT * FROM {table}")
                ]
            summary = {
                "migration": "paper_fee_policy",
                "old_fee_policy": account.get("fee_policy") or "legacy",
                "new_fee_policy": FEE_POLICY,
                "commission_rate": float(COMMISSION_RATE),
                "stamp_tax_rate": float(STAMP_TAX_RATE),
                "trade_count": len(changes),
                "cash_adjustment": -total_delta,
            }
            cursor = conn.execute(
                """INSERT INTO paper_ledger_archive(
                       archived_at, reason, payload_json, rebuilt_summary_json
                   ) VALUES (?, ?, ?, ?)""",
                (
                    now,
                    "apply commission 0.05% both sides and stamp tax 0.05% on sells",
                    json.dumps(archived, ensure_ascii=False, default=str),
                    json.dumps(summary, ensure_ascii=False, default=str),
                ),
            )
            archive_id = int(cursor.lastrowid)

            for change in changes:
                conn.execute(
                    """UPDATE paper_trade
                       SET fee=?, commission=?, stamp_tax=?, signal_at=?
                       WHERE id=?""",
                    (
                        change["new_fee"], change["commission"],
                        change["stamp_tax"], change["signal_at"], change["id"],
                    ),
                )
            for snapshot in conn.execute(
                "SELECT snapshot_date, cash, total_value FROM paper_portfolio_snapshot"
            ):
                snapshot_delta = sum(
                    change["delta"]
                    for change in changes
                    if change["trade_date"] <= snapshot["snapshot_date"]
                )
                conn.execute(
                    """UPDATE paper_portfolio_snapshot
                       SET cash=?, total_value=?, updated_at=?
                       WHERE snapshot_date=?""",
                    (
                        float(snapshot["cash"]) - snapshot_delta,
                        float(snapshot["total_value"]) - snapshot_delta,
                        now,
                        snapshot["snapshot_date"],
                    ),
                )
            conn.execute(
                """UPDATE paper_account
                   SET cash=?, updated_at=?, ledger_version=3,
                       commission_rate=?, stamp_tax_rate=?, fee_policy=?
                   WHERE id=1""",
                (
                    new_cash, now, float(COMMISSION_RATE),
                    float(STAMP_TAX_RATE), FEE_POLICY,
                ),
            )
        return {
            "status": "applied",
            "archive_id": archive_id,
            "fee_policy": FEE_POLICY,
            "trade_count": len(changes),
            "cash_adjustment": round(-total_delta, 2),
            "cash": round(new_cash, 2),
        }

    def apply_paper_causality_policy(self) -> dict[str, Any]:
        """Archive and label historical fills before enabling causal live fills."""
        self.ensure_paper_account()
        policy = "post_signal_fresh_exchange_quote_v1"
        now = datetime.now().astimezone().isoformat()
        with self._get_conn() as conn:
            account = dict(conn.execute(
                "SELECT * FROM paper_account WHERE id=1"
            ).fetchone())
            trades = [dict(row) for row in conn.execute(
                "SELECT * FROM paper_trade ORDER BY id"
            )]
            if account.get("execution_policy") == policy and all(
                trade.get("causality_status") not in (None, "", "legacy_unverified")
                for trade in trades
            ):
                return {
                    "status": "already_applied",
                    "execution_policy": policy,
                    "trade_count": len(trades),
                }

            archived = {"account": account}
            for table in (
                "paper_position",
                "paper_trade",
                "paper_position_mark",
                "paper_portfolio_snapshot",
            ):
                archived[table] = [
                    dict(row) for row in conn.execute(f"SELECT * FROM {table}")
                ]
            summary = {
                "migration": "paper_causality_policy",
                "execution_policy": policy,
                "historical_trade_count": len(trades),
                "cash_adjustment": 0,
            }
            cursor = conn.execute(
                """INSERT INTO paper_ledger_archive(
                       archived_at, reason, payload_json, rebuilt_summary_json
                   ) VALUES (?, ?, ?, ?)""",
                (
                    now,
                    "enable post-signal fresh exchange quotes; label prior bar replay",
                    json.dumps(archived, ensure_ascii=False, default=str),
                    json.dumps(summary, ensure_ascii=False, default=str),
                ),
            )
            archive_id = int(cursor.lastrowid)
            for trade in trades:
                historical_replay = bool(
                    trade.get("legacy_trade_id") is not None
                    or "replay" in str(trade.get("execution_mode") or "").lower()
                )
                status = (
                    "verified_historical_bar_replay"
                    if historical_replay
                    else "legacy_execution_time_preserved"
                )
                conn.execute(
                    """UPDATE paper_trade
                       SET data_cutoff_at=COALESCE(NULLIF(data_cutoff_at, ''), signal_at),
                           quote_exchange_at=COALESCE(
                               NULLIF(quote_exchange_at, ''), created_at
                           ),
                           causality_status=?
                       WHERE id=?""",
                    (status, trade["id"]),
                )
            conn.execute(
                """UPDATE paper_account
                   SET ledger_version=4, execution_policy=?, updated_at=?
                   WHERE id=1""",
                (policy, now),
            )
        return {
            "status": "applied",
            "archive_id": archive_id,
            "execution_policy": policy,
            "trade_count": len(trades),
        }

    def archive_and_replace_paper_ledger(
        self,
        rebuilt: dict,
        reason: str,
    ) -> dict:
        """Atomically archive the active ledger and install a verified replay."""
        cash = float(rebuilt["cash"])
        positions = list(rebuilt.get("positions") or [])
        trades = list(rebuilt.get("trades") or [])
        ledger_quality = str(
            rebuilt.get("ledger_quality") or "verified_real_prices"
        )
        price_policy = str(
            rebuilt.get("price_policy")
            or "verified_quote_same_session_or_next_open"
        )
        if cash < 0:
            raise ValueError("rebuilt paper cash cannot be negative")
        if any(int(position.get("shares") or 0) <= 0 for position in positions):
            raise ValueError("rebuilt positions must contain positive shares")
        if any(int(position["shares"]) % 100 for position in positions):
            raise ValueError("rebuilt positions must use 100-share round lots")

        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            account = dict(conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone())
            archived = {"account": account}
            for table in (
                "paper_position",
                "paper_trade",
                "paper_position_mark",
                "paper_portfolio_snapshot",
            ):
                archived[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            cursor = conn.execute(
                """INSERT INTO paper_ledger_archive(
                       archived_at, reason, payload_json, rebuilt_summary_json
                   ) VALUES (?, ?, ?, ?)""",
                (
                    now,
                    reason,
                    json.dumps(archived, ensure_ascii=False, default=str),
                    json.dumps(rebuilt.get("summary") or {}, ensure_ascii=False, default=str),
                ),
            )
            archive_id = int(cursor.lastrowid)

            for table in (
                "paper_position_mark",
                "paper_portfolio_snapshot",
                "paper_trade",
                "paper_position",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.execute(
                """UPDATE paper_account
                   SET cash=?, updated_at=?, ledger_version=4,
                       ledger_quality=?, ledger_rebuilt_at=?, price_policy=?,
                       commission_rate=?, stamp_tax_rate=?, fee_policy=?,
                       execution_policy='post_signal_fresh_exchange_quote_v1'
                   WHERE id=1""",
                (
                    cash, now, ledger_quality, now, price_policy,
                    float(COMMISSION_RATE),
                    float(STAMP_TAX_RATE), FEE_POLICY,
                ),
            )

            for position in positions:
                conn.execute(
                    """INSERT INTO paper_position(
                           stock_code, stock_name, shares, avg_cost, updated_at,
                           entry_date, eligible_sell_date, entry_price_date,
                           entry_price_source, execution_mode, execution_tier,
                           entry_flow_state, entry_fallback_status,
                           entry_gate_reasons, probe_expiry_date, promotion_status
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        position["stock_code"],
                        position.get("stock_name") or position["stock_code"],
                        int(position["shares"]),
                        float(position["avg_cost"]),
                        now,
                        position.get("entry_date", ""),
                        position.get("eligible_sell_date", position.get("entry_date", "")),
                        position.get("entry_price_date", position.get("entry_date", "")),
                        position.get("entry_price_source", ""),
                        position.get("execution_mode", "historical_replay"),
                        position.get("execution_tier", "normal"),
                        position.get("entry_flow_state", ""),
                        position.get("entry_fallback_status", ""),
                        position.get("entry_gate_reasons", "[]"),
                        position.get("probe_expiry_date", ""),
                        position.get("promotion_status", "none"),
                    ),
                )
            for trade in trades:
                conn.execute(
                    """INSERT INTO paper_trade(
                           trade_date, action, stock_code, stock_name, shares,
                           price, value, reason, created_at, decision_id, fee,
                           commission, stamp_tax, slippage, signal_date, signal_at,
                           data_cutoff_at, quote_exchange_at, source_lag_seconds,
                           causality_status, execution_tier, flow_state,
                           fallback_status, gate_reasons, promotion_status,
                           price_date, price_source,
                           execution_mode, quote_fetched_at, integrity_status,
                           legacy_trade_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade["trade_date"], trade["action"], trade["stock_code"],
                        trade.get("stock_name") or trade["stock_code"],
                        int(trade["shares"]), float(trade["price"]),
                        float(trade["value"]), trade.get("reason", ""),
                        trade.get("created_at", now), trade.get("decision_id"),
                        float(trade.get("fee") or 0),
                        float(trade.get("commission") or 0),
                        float(trade.get("stamp_tax") or 0),
                        float(trade.get("slippage") or 0),
                        trade.get("signal_date", trade["trade_date"]),
                        trade.get("signal_at", trade.get("created_at", now)),
                        trade.get("data_cutoff_at", trade.get("signal_at", "")),
                        trade.get("quote_exchange_at", trade.get("created_at", now)),
                        trade.get("source_lag_seconds"),
                        trade.get("causality_status", "verified_historical_bar_replay"),
                        trade.get("execution_tier", "normal"),
                        trade.get("flow_state", ""),
                        trade.get("fallback_status", ""),
                        trade.get("gate_reasons", "[]"),
                        trade.get("promotion_status", ""),
                        trade.get("price_date", trade["trade_date"]),
                        trade.get("price_source", ""),
                        trade.get("execution_mode", "historical_replay"),
                        trade.get("quote_fetched_at", ""),
                        "verified_real_price",
                        trade.get("legacy_trade_id"),
                    ),
                )
        return {
            "archive_id": archive_id,
            "cash": round(cash, 2),
            "position_count": len(positions),
            "trade_count": len(trades),
            "ledger_quality": ledger_quality,
            "price_policy": price_policy,
        }

    def run_paper_strategy(
        self,
        decisions: list[dict],
        trade_date: str,
        initial_capital: float = 100000.0,
        max_position_pct: float = PAPER_MAX_POSITION_PCT,
        execution_timestamp: str | None = None,
        strict_real_data: bool = True,
        trading_day_verified: bool = False,
        is_trading_day: bool = False,
        trading_calendar_source: str = "",
    ) -> dict:
        """Execute one deterministic, auditable paper-trading decision cycle.

        The strategy is intentionally conservative: no leverage, max five
        positions, a hard maximum of 20% of marked account value per position,
        and round lots of 100 shares. Full positions fail closed unless a
        successful TradingAgents result explicitly says Buy or Overweight;
        flow-incomplete candidates may enter only a bounded 2% observation slot.
        It is simulation only and never talks to a brokerage.
        """
        from config.settings import settings

        self.ensure_paper_account(initial_capital)
        flow_probe_enabled = bool(
            getattr(settings, "PAPER_EXPLORATION_ENABLED", True)
        )
        position_cap_pct = bounded_position_cap(max_position_pct)
        probe_position_pct = min(
            0.02,
            max(0.0, float(getattr(settings, "PAPER_EXPLORATION_POSITION_PCT", 0.02))),
        )
        probe_max_position_pct = min(
            0.03,
            max(
                probe_position_pct,
                float(getattr(settings, "PAPER_EXPLORATION_MAX_POSITION_PCT", 0.03)),
            ),
        )
        probe_total_pct = min(
            0.05,
            max(0.0, float(getattr(settings, "PAPER_EXPLORATION_MAX_TOTAL_PCT", 0.05))),
        )
        session_ok, execution_status, execution_at = self._execution_session_status(
            trade_date,
            execution_timestamp,
        )
        if strict_real_data and not trading_day_verified:
            session_ok = False
            execution_status = "trading_calendar_unverified"
        elif strict_real_data and not is_trading_day:
            session_ok = False
            execution_status = "market_holiday"
        if strict_real_data and not session_ok:
            portfolio = self.get_paper_portfolio(as_of_date=trade_date)
            held_codes = {
                str(position.get("stock_code") or "")
                for position in portfolio.get("positions", [])
            }
            rejections = []
            for decision in decisions:
                code = str(decision.get("stock_code") or "")
                direction = decision_direction(decision)
                if code not in held_codes and is_buy_signal(decision):
                    reason = deep_buy_rejection_reason(decision)
                    if not reason:
                        reason = execution_status
                elif (
                    code in held_codes
                    or is_momentum_probe_candidate(decision)
                    or is_conditional_probe_candidate(decision)
                    or is_flow_probe_candidate(decision)
                ):
                    reason = execution_status
                else:
                    continue
                rejections.append({
                    "signal_date": str(decision.get("date") or trade_date),
                    "stock_code": code,
                    "stock_name": str(decision.get("stock_name") or code),
                    "direction": direction,
                    "reason": reason,
                    "quote_date": str(decision.get("market_price_date") or ""),
                    "quote_source": str(decision.get("market_price_source") or ""),
                    "quote_price": float(decision.get("market_price") or 0),
                    "execution_at": execution_at,
                    "signal_at": str(decision.get("signal_at") or ""),
                    "data_cutoff_at": str(decision.get("data_cutoff_at") or ""),
                    "quote_exchange_at": str(
                        decision.get("market_price_exchange_at") or ""
                    ),
                })
            if rejections:
                with self._get_conn() as conn:
                    conn.executemany(
                        """INSERT INTO paper_order_rejection(
                               signal_date, stock_code, stock_name, direction,
                               reason, quote_date, quote_source, quote_price,
                               execution_at, signal_at, data_cutoff_at,
                               quote_exchange_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [tuple(rejection.values()) for rejection in rejections],
                    )
            return {
                "cash": round(float(portfolio["cash"]), 2),
                "position_count": len(portfolio["positions"]),
                "actions": [],
                "execution_status": execution_status,
                "execution_at": execution_at,
                "rejections": rejections,
                "trading_calendar_source": trading_calendar_source,
            }
        now = execution_at
        actions: list[dict] = []
        promotions: list[dict] = []
        rejections: list[dict] = []
        with self._get_conn() as conn:
            account = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            # Keep every fill traceable even when a caller omitted the journal
            # id.  The exact signal timestamp is the only safe fallback because
            # multiple decisions for one stock may exist on the same day.
            for decision in decisions:
                if decision.get("journal_id") is not None:
                    continue
                signal_at = str(decision.get("signal_at") or "")
                code = str(decision.get("stock_code") or "")
                if not signal_at or not code:
                    continue
                linked = conn.execute(
                    """SELECT id FROM decision_journal
                       WHERE stock_code=? AND created_at=?
                       ORDER BY id DESC LIMIT 1""",
                    (code, signal_at),
                ).fetchone()
                if linked is not None:
                    decision["journal_id"] = int(linked["id"])
            positions = {
                r["stock_code"]: dict(r)
                for r in conn.execute("SELECT * FROM paper_position WHERE shares > 0")
            }
            # Codes exited earlier in this same cycle.  The buy loop runs after
            # the exit loops and only skips `code in positions`, so a name sold
            # a moment ago could be bought straight back at the other side of
            # the spread by the same decision that just closed it.
            sold_codes: set[str] = set()
            for code, position in positions.items():
                if str(position.get("industry") or "").strip():
                    continue
                metadata = conn.execute(
                    "SELECT industry FROM stock_basic WHERE ts_code=? LIMIT 1",
                    (code,),
                ).fetchone()
                position["industry"] = str(
                    (metadata["industry"] if metadata else "") or ""
                ).strip()
            quotes = {}
            quote_meta = {}
            for d in decisions:
                code = str(d.get("stock_code") or "")
                deep_approved = is_deep_buy_approved(d)
                flow_entry = evaluate_entry_execution(
                    d,
                    allow_probe=flow_probe_enabled,
                    paper_mode=True,
                )
                flow_probe_candidate = (
                    flow_entry["tier"] == ExecutionTier.PROBE.value
                )
                legacy_probe_candidate = is_momentum_probe_candidate(d)
                conditional_probe_candidate = is_conditional_probe_candidate(d)
                probe_candidate = (
                    flow_probe_candidate
                    or legacy_probe_candidate
                    or conditional_probe_candidate
                )
                if code not in positions:
                    if is_buy_signal(d) and not deep_approved and not probe_candidate:
                        rejection = {
                            "signal_date": str(d.get("date") or trade_date),
                            "stock_code": code,
                            "stock_name": str(d.get("stock_name") or code),
                            "direction": decision_direction(d),
                            "reason": deep_buy_rejection_reason(d),
                            "quote_date": str(d.get("market_price_date") or ""),
                            "quote_source": str(d.get("market_price_source") or ""),
                            "quote_price": float(d.get("market_price") or 0),
                            "execution_at": now,
                            "signal_at": str(d.get("signal_at") or ""),
                            "data_cutoff_at": str(d.get("data_cutoff_at") or ""),
                            "quote_exchange_at": str(
                                d.get("market_price_exchange_at") or ""
                            ),
                        }
                        rejections.append(rejection)
                        conn.execute(
                            """INSERT INTO paper_order_rejection(
                                   signal_date, stock_code, stock_name, direction,
                                   reason, quote_date, quote_source, quote_price,
                                   execution_at, signal_at, data_cutoff_at,
                                   quote_exchange_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            tuple(rejection.values()),
                        )
                    if not deep_approved and not probe_candidate:
                        continue
                if strict_real_data:
                    verified_quote, rejection_reason = self._verified_execution_quote(
                        d,
                        trade_date,
                    )
                    if verified_quote is None:
                        direction = decision_direction(d)
                        if code in positions or deep_approved or probe_candidate:
                            rejection = {
                                "signal_date": str(d.get("date") or trade_date),
                                "stock_code": code,
                                "stock_name": str(d.get("stock_name") or code),
                                "direction": direction,
                                "reason": rejection_reason,
                                "quote_date": str(d.get("market_price_date") or ""),
                                "quote_source": str(d.get("market_price_source") or ""),
                                "quote_price": float(d.get("market_price") or 0),
                                "execution_at": now,
                                "signal_at": str(d.get("signal_at") or ""),
                                "data_cutoff_at": str(d.get("data_cutoff_at") or ""),
                                "quote_exchange_at": str(
                                    d.get("market_price_exchange_at") or ""
                                ),
                            }
                            rejections.append(rejection)
                            conn.execute(
                                """INSERT INTO paper_order_rejection(
                                       signal_date, stock_code, stock_name, direction,
                                       reason, quote_date, quote_source, quote_price,
                                       execution_at, signal_at, data_cutoff_at,
                                       quote_exchange_at
                                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                tuple(rejection.values()),
                            )
                        continue
                    quote_received_at = parse_timestamp(verified_quote["fetched_at"])
                    fill_processed_at = parse_timestamp(now)
                    if (
                        quote_received_at is None
                        or fill_processed_at is None
                        or fill_processed_at < quote_received_at
                        or (fill_processed_at - quote_received_at).total_seconds() > 10
                    ):
                        rejection_reason = (
                            "execution_before_quote_received"
                            if quote_received_at is not None
                            and fill_processed_at is not None
                            and fill_processed_at < quote_received_at
                            else "quote_processing_delay_exceeded"
                        )
                        rejection = {
                            "signal_date": str(d.get("date") or trade_date),
                            "stock_code": code,
                            "stock_name": str(d.get("stock_name") or code),
                            "direction": str(d.get("direction") or "neutral").lower(),
                            "reason": rejection_reason,
                            "quote_date": str(d.get("market_price_date") or ""),
                            "quote_source": str(d.get("market_price_source") or ""),
                            "quote_price": float(d.get("market_price") or 0),
                            "execution_at": now,
                            "signal_at": str(d.get("signal_at") or ""),
                            "data_cutoff_at": str(d.get("data_cutoff_at") or ""),
                            "quote_exchange_at": str(
                                d.get("market_price_exchange_at") or ""
                            ),
                        }
                        rejections.append(rejection)
                        conn.execute(
                            """INSERT INTO paper_order_rejection(
                                   signal_date, stock_code, stock_name, direction,
                                   reason, quote_date, quote_source, quote_price,
                                   execution_at, signal_at, data_cutoff_at,
                                   quote_exchange_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            tuple(rejection.values()),
                        )
                        continue
                    price = float(verified_quote["price"])
                    quote_meta[code] = verified_quote
                else:
                    q = self.get_latest_quote(code) or {}
                    price = float(
                        d.get("market_price")
                        or d.get("price")
                        or q.get("price")
                        or 0
                    )
                    quote_meta[code] = {
                        "price": price,
                        "price_date": str(d.get("market_price_date") or trade_date),
                        "price_source": str(
                            d.get("market_price_source") or "non_strict_test_or_replay"
                        ),
                        "fetched_at": str(d.get("market_price_fetched_at") or now),
                    }
                if code and price > 0:
                    quotes[code] = (d, price)

            missing_position_quotes = sorted(set(positions) - set(quotes))
            actionable_quotes = any(
                is_deep_buy_approved(decision)
                or is_flow_probe_candidate(decision)
                or is_momentum_probe_candidate(decision)
                or is_conditional_probe_candidate(decision)
                for decision in decisions
            ) or any(code in quotes for code in positions)
            if strict_real_data and missing_position_quotes and actionable_quotes:
                return {
                    "cash": round(float(account["cash"]), 2),
                    "position_count": len(positions),
                    "actions": [],
                    "execution_status": "incomplete_position_quote_coverage",
                    "execution_at": now,
                    "rejections": rejections,
                    "missing_position_quotes": missing_position_quotes,
                }

            cash = float(account["cash"])
            marked_value = cash + sum(
                p["shares"] * quotes[code][1]
                for code, p in positions.items()
                if code in quotes and quotes[code][1] > 0
            )

            # Exit bearish, stale-neutral, and profit-protected holdings first.
            for code, p in list(positions.items()):
                quote_pair = quotes.get(code)
                if quote_pair is None:
                    continue
                d, price = quote_pair
                limit_pct = price_limit_pct(code, is_st=bool(d.get("is_st")))
                quote = self.get_latest_quote(code) or {}
                change_pct = resolve_change_pct(d, quote, trade_date)
                eligible = not p.get("eligible_sell_date") or trade_date > p["eligible_sell_date"]
                holding_days = _trading_days_held(
                    conn,
                    str(p.get("entry_date") or ""),
                    trade_date,
                )
                if (
                    str(p.get("execution_tier") or "normal") == "probe"
                    and is_probe_promotion_candidate(d)
                    and is_deep_buy_approved(d)
                ):
                    p["execution_tier"] = ExecutionTier.NORMAL.value
                    p["promotion_status"] = "promoted"
                    conn.execute(
                        """UPDATE paper_position
                           SET execution_tier='normal', promotion_status='promoted',
                               updated_at=?
                           WHERE stock_code=?""",
                        (now, code),
                    )
                    promotions.append({
                        "stock_code": code,
                        "promotion_status": "promoted",
                        "execution_at": now,
                    })
                high_price = _highest_mark_price(
                    conn,
                    code,
                    str(p.get("entry_date") or ""),
                    trade_date,
                    price,
                )
                exit_reason = (
                    probe_exit_reason(
                        p,
                        d,
                        price,
                        holding_days,
                        stop_loss_pct=float(
                            getattr(settings, "PAPER_EXPLORATION_STOP_LOSS_PCT", 4.0)
                        ),
                        confirmation_days=int(
                            getattr(
                                settings,
                                "PAPER_EXPLORATION_CONFIRMATION_DAYS",
                                3,
                            )
                        ),
                        max_holding_days=int(
                            getattr(
                                settings,
                                "PAPER_EXPLORATION_MAX_HOLDING_DAYS",
                                5,
                            )
                        ),
                    )
                    if str(p.get("execution_tier") or "normal") == "probe"
                    else position_exit_reason(
                        p,
                        d,
                        price,
                        holding_days,
                        high_price,
                    )
                )
                if exit_reason and eligible and change_pct > -limit_pct + 0.2:
                    meta = quote_meta.get(code)
                    if not meta:
                        continue
                    sell_price = quantize_price(price * 0.999)
                    value = p["shares"] * sell_price
                    costs = calculate_trade_costs(value, "SELL")
                    fee = costs["total_fees"]
                    cash += value - fee
                    conn.execute("DELETE FROM paper_position WHERE stock_code=?", (code,))
                    fill_at = now
                    conn.execute(
                        """INSERT INTO paper_trade
                           (trade_date, action, stock_code, stock_name, shares,
                            price, value, reason, created_at, decision_id, fee,
                            commission, stamp_tax, slippage, signal_date, signal_at,
                            data_cutoff_at, quote_exchange_at, source_lag_seconds,
                            causality_status,
                            price_date, price_source,
                            execution_mode, quote_fetched_at, integrity_status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            trade_date, "SELL", code, p["stock_name"], p["shares"],
                            sell_price, value,
                            exit_reason, fill_at,
                            d.get("journal_id"), fee,
                            costs["commission"], costs["stamp_tax"],
                            p["shares"] * (price - sell_price),
                            d.get("date") or trade_date,
                            d.get("signal_at") or now,
                            d.get("data_cutoff_at") or d.get("signal_at") or now,
                            meta.get("exchange_at") or fill_at,
                            meta.get("source_lag_seconds"),
                            meta.get("causality_status") or "non_strict",
                            meta["price_date"],
                            meta["price_source"],
                            "intraday_verified_quote" if strict_real_data else "non_strict",
                            meta["fetched_at"],
                            "verified_real_price" if strict_real_data else "non_strict",
                        ),
                    )
                    conn.execute(
                        "UPDATE paper_trade SET realized_pnl=? WHERE id=last_insert_rowid()",
                        (p["shares"] * (sell_price - float(p["avg_cost"])),),
                    )
                    sell_flow = flow_execution_metadata(d)
                    conn.execute(
                        """UPDATE paper_trade
                           SET execution_tier=?, flow_state=?, fallback_status=?,
                               gate_reasons=?, promotion_status=?
                           WHERE id=last_insert_rowid()""",
                        (
                            str(p.get("execution_tier") or "normal"),
                            sell_flow["flow_state"],
                            sell_flow["fallback_status"],
                            json.dumps(d.get("gate_reasons") or [], ensure_ascii=False),
                            str(p.get("promotion_status") or "exited"),
                        ),
                    )
                    actions.append({
                        "action": "SELL", "stock_code": code,
                        "shares": p["shares"], "price": sell_price, "fee": fee,
                        "execution_tier": str(p.get("execution_tier") or "normal"),
                        "commission": costs["commission"],
                        "stamp_tax": costs["stamp_tax"],
                        "execution_at": fill_at,
                        "reason": exit_reason,
                        "holding_days": holding_days,
                        "high_price": high_price,
                        "causality_status": meta.get("causality_status") or "non_strict",
                        "price_date": meta["price_date"],
                        "price_source": meta["price_source"],
                    })
                    positions.pop(code, None)
                    sold_codes.add(code)

            # Bring legacy or market-appreciated holdings back under the hard
            # 20% cap as soon as A-share T+1 and limit rules permit a sale.
            for code, p in list(positions.items()):
                quote_pair = quotes.get(code)
                if quote_pair is None or not quote_meta.get(code):
                    continue
                d, price = quote_pair
                if price <= 0:
                    continue
                target_shares = int(
                    (marked_value * position_cap_pct) // price // 100
                ) * 100
                shares = int(p["shares"]) - target_shares
                if shares <= 0:
                    continue
                eligible = (
                    not p.get("eligible_sell_date")
                    or trade_date > p["eligible_sell_date"]
                )
                quote = self.get_latest_quote(code) or {}
                limit_pct = price_limit_pct(code, is_st=bool(d.get("is_st")))
                change_pct = resolve_change_pct(d, quote, trade_date)
                if not eligible or at_limit_down(change_pct, limit_pct):
                    continue
                sell_price = quantize_price(price * 0.999)
                value = shares * sell_price
                costs = calculate_trade_costs(value, "SELL")
                fee = costs["total_fees"]
                cash += value - fee
                remaining = int(p["shares"]) - shares
                if remaining <= 0:
                    conn.execute(
                        "DELETE FROM paper_position WHERE stock_code=?", (code,)
                    )
                    positions.pop(code, None)
                    sold_codes.add(code)
                else:
                    conn.execute(
                        """UPDATE paper_position SET shares=?, updated_at=?
                           WHERE stock_code=?""",
                        (remaining, now, code),
                    )
                    positions[code]["shares"] = remaining
                meta = quote_meta.get(code)
                if not meta:
                    continue
                fill_at = now
                reason = f"rebalance_max_position={position_cap_pct:.0%}"
                conn.execute(
                    """INSERT INTO paper_trade
                       (trade_date, action, stock_code, stock_name, shares, price,
                        value, reason, created_at, decision_id, fee, slippage,
                        commission, stamp_tax, signal_date, signal_at,
                        data_cutoff_at, quote_exchange_at, source_lag_seconds,
                        causality_status, price_date, price_source, execution_mode,
                        quote_fetched_at, integrity_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade_date, "SELL", code, p["stock_name"], shares,
                        sell_price, value, reason, fill_at, d.get("journal_id"),
                        fee, shares * (price - sell_price),
                        costs["commission"], costs["stamp_tax"],
                        d.get("date") or trade_date,
                        d.get("signal_at") or now,
                        d.get("data_cutoff_at") or d.get("signal_at") or now,
                        meta.get("exchange_at") or fill_at,
                        meta.get("source_lag_seconds"),
                        meta.get("causality_status") or "non_strict",
                        meta["price_date"], meta["price_source"],
                        "intraday_verified_quote" if strict_real_data else "non_strict",
                        meta["fetched_at"],
                        "verified_real_price" if strict_real_data else "non_strict",
                    ),
                )
                conn.execute(
                    "UPDATE paper_trade SET realized_pnl=? WHERE id=last_insert_rowid()",
                    (shares * (sell_price - float(p["avg_cost"])),),
                )
                sell_flow = flow_execution_metadata(d)
                conn.execute(
                    """UPDATE paper_trade
                       SET execution_tier=?, flow_state=?, fallback_status=?,
                           gate_reasons=?, promotion_status=?
                       WHERE id=last_insert_rowid()""",
                    (
                        str(p.get("execution_tier") or "normal"),
                        sell_flow["flow_state"],
                        sell_flow["fallback_status"],
                        json.dumps(d.get("gate_reasons") or [], ensure_ascii=False),
                        "exited_rebalance",
                    ),
                )
                actions.append({
                    "action": "SELL",
                    "stock_code": code,
                    "shares": shares,
                    "price": sell_price,
                    "execution_tier": str(p.get("execution_tier") or "normal"),
                    "fee": fee,
                    "commission": costs["commission"],
                    "stamp_tax": costs["stamp_tax"],
                    "execution_at": fill_at,
                    "causality_status": meta.get("causality_status") or "non_strict",
                    "reason": reason,
                    "price_date": meta["price_date"],
                    "price_source": meta["price_source"],
                })

            # Enter only the strongest names and do not churn existing holds.
            # If earlier versions or market moves pushed cash below the 10%
            # reserve, restore it first by reducing the weakest eligible hold.
            min_cash_reserve = marked_value * PAPER_MIN_CASH_RESERVE_PCT
            if cash < min_cash_reserve:
                weakest = sorted(
                    positions.items(),
                    key=lambda item: float(
                        quotes.get(item[0], ({"ai_score": 50}, 0))[0].get("ai_score") or 50
                    ),
                )
                for code, p in weakest:
                    if cash >= min_cash_reserve:
                        break
                    quote_pair = quotes.get(code)
                    if quote_pair is None or not quote_meta.get(code):
                        continue
                    d, price = quote_pair
                    eligible = not p.get("eligible_sell_date") or trade_date > p["eligible_sell_date"]
                    quote = self.get_latest_quote(code) or {}
                    limit_pct = price_limit_pct(code, is_st=bool(d.get("is_st")))
                    change_pct = resolve_change_pct(d, quote, trade_date)
                    if (
                        not eligible
                        or price <= 0
                        or at_limit_down(change_pct, limit_pct)
                    ):
                        continue
                    sell_price = quantize_price(price * 0.999)
                    shortfall = min_cash_reserve - cash
                    shares = min(
                        int(p["shares"]),
                        int(math.ceil(shortfall / sell_price / 100.0)) * 100,
                    )
                    if shares <= 0:
                        continue
                    value = shares * sell_price
                    costs = calculate_trade_costs(value, "SELL")
                    fee = costs["total_fees"]
                    cash += value - fee
                    remaining = int(p["shares"]) - shares
                    if remaining <= 0:
                        conn.execute("DELETE FROM paper_position WHERE stock_code=?", (code,))
                        positions.pop(code, None)
                        sold_codes.add(code)
                    else:
                        conn.execute(
                            """UPDATE paper_position SET shares=?, updated_at=?
                               WHERE stock_code=?""",
                            (remaining, now, code),
                        )
                        positions[code]["shares"] = remaining
                    meta = quote_meta.get(code)
                    if not meta:
                        continue
                    fill_at = now
                    conn.execute(
                        """INSERT INTO paper_trade
                           (trade_date, action, stock_code, stock_name, shares, price,
                            value, reason, created_at, decision_id, fee, slippage,
                            commission, stamp_tax, signal_date, signal_at,
                            data_cutoff_at, quote_exchange_at, source_lag_seconds,
                            causality_status,
                            price_date, price_source, execution_mode,
                            quote_fetched_at, integrity_status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            trade_date, "SELL", code, p["stock_name"], shares,
                            sell_price, value,
                            "restore_min_cash_reserve=10%", fill_at,
                            d.get("journal_id"),
                            fee, shares * (price - sell_price),
                            costs["commission"], costs["stamp_tax"],
                            d.get("date") or trade_date,
                            d.get("signal_at") or now,
                            d.get("data_cutoff_at") or d.get("signal_at") or now,
                            meta.get("exchange_at") or fill_at,
                            meta.get("source_lag_seconds"),
                            meta.get("causality_status") or "non_strict",
                            meta["price_date"],
                            meta["price_source"],
                            "intraday_verified_quote" if strict_real_data else "non_strict",
                            meta["fetched_at"],
                            "verified_real_price" if strict_real_data else "non_strict",
                        ),
                    )
                    conn.execute(
                        "UPDATE paper_trade SET realized_pnl=? WHERE id=last_insert_rowid()",
                        (shares * (sell_price - float(p["avg_cost"])),),
                    )
                    sell_flow = flow_execution_metadata(d)
                    conn.execute(
                        """UPDATE paper_trade
                           SET execution_tier=?, flow_state=?, fallback_status=?,
                               gate_reasons=?, promotion_status=?
                           WHERE id=last_insert_rowid()""",
                        (
                            str(p.get("execution_tier") or "normal"),
                            sell_flow["flow_state"],
                            sell_flow["fallback_status"],
                            json.dumps(d.get("gate_reasons") or [], ensure_ascii=False),
                            "exited_cash_reserve",
                        ),
                    )
                    actions.append({
                        "action": "SELL", "stock_code": code, "shares": shares,
                        "price": sell_price, "fee": fee,
                        "execution_tier": str(p.get("execution_tier") or "normal"),
                        "commission": costs["commission"],
                        "stamp_tax": costs["stamp_tax"],
                        "execution_at": fill_at,
                        "causality_status": meta.get("causality_status") or "non_strict",
                        "reason": "restore_min_cash_reserve=10%",
                        "price_date": meta["price_date"],
                        "price_source": meta["price_source"],
                    })

            industry_positions = [
                {
                    "industry": str(position.get("industry") or "").strip(),
                    "market_value": int(position.get("shares") or 0) * float(quotes[code][1]),
                }
                for code, position in positions.items()
                if code in quotes and quotes[code][1] > 0
            ]

            # A probe that becomes a normal, fully evidenced BUY may be topped
            # up once to the normal target.  This is deliberately separate from
            # the new-position loop so a promotion cannot reopen or duplicate a
            # position.  Never average down while promoting.
            for code, p in list(positions.items()):
                if (
                    str(p.get("execution_tier") or "normal") != "normal"
                    or str(p.get("promotion_status") or "") != "promoted"
                ):
                    continue
                quote_pair = quotes.get(code)
                if quote_pair is None:
                    continue
                d, price = quote_pair
                if not is_probe_promotion_candidate(d) or not is_deep_buy_approved(d):
                    continue
                if price <= 0 or price < float(p.get("avg_cost") or 0):
                    continue
                limit_pct = price_limit_pct(code, is_st=bool(d.get("is_st")))
                quote = self.get_latest_quote(code) or {}
                change_pct = resolve_change_pct(d, quote, trade_date)
                if at_limit_up(change_pct, limit_pct):
                    continue
                buy_price = quantize_price(price * 1.001)
                target_shares = int((marked_value * position_cap_pct) // buy_price // 100) * 100
                additional_target = target_shares - int(p.get("shares") or 0)
                if additional_target <= 0:
                    continue
                min_cash_reserve = marked_value * PAPER_MIN_CASH_RESERVE_PCT
                available_cash = max(0.0, cash - min_cash_reserve)
                budget = min(available_cash, additional_target * buy_price)
                shares = int(budget // buy_price // 100) * 100
                value = shares * buy_price
                costs = calculate_trade_costs(value, "BUY")
                fee = costs["total_fees"]
                while shares > 0 and value + fee > available_cash:
                    shares -= 100
                    value = shares * buy_price
                    costs = calculate_trade_costs(value, "BUY")
                    fee = costs["total_fees"]
                if shares <= 0:
                    continue
                exposure = projected_industry_exposure(
                    industry_positions,
                    p.get("industry") or d.get("universe_industry") or d.get("industry"),
                    value,
                    marked_value,
                )
                if not exposure["allowed"]:
                    continue
                meta = quote_meta.get(code)
                if not meta:
                    continue
                old_shares = int(p["shares"])
                old_cost = float(p["avg_cost"])
                total_shares = old_shares + shares
                new_avg_cost = (
                    old_shares * old_cost + shares * buy_price
                ) / total_shares
                cash -= value + fee
                p.update({
                    "shares": total_shares,
                    "avg_cost": new_avg_cost,
                    "eligible_sell_date": trade_date,
                })
                conn.execute(
                    """UPDATE paper_position
                       SET shares=?, avg_cost=?, eligible_sell_date=?, updated_at=?
                       WHERE stock_code=?""",
                    (total_shares, new_avg_cost, trade_date, now, code),
                )
                conn.execute(
                    """INSERT INTO paper_trade
                       (trade_date, action, stock_code, stock_name, shares, price,
                        value, reason, created_at, decision_id, fee, commission,
                        stamp_tax, slippage, signal_date, signal_at, data_cutoff_at,
                        quote_exchange_at, source_lag_seconds, causality_status,
                        price_date, price_source, execution_mode, quote_fetched_at,
                        integrity_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade_date, "BUY", code, p["stock_name"], shares,
                        buy_price, value, "probe_promoted_topup; no_average_down",
                        now, d.get("journal_id"), fee, costs["commission"],
                        costs["stamp_tax"], shares * (buy_price - price),
                        d.get("date") or trade_date, d.get("signal_at") or now,
                        d.get("data_cutoff_at") or d.get("signal_at") or now,
                        meta.get("exchange_at") or now, meta.get("source_lag_seconds"),
                        meta.get("causality_status") or "non_strict", meta["price_date"],
                        meta["price_source"],
                        "intraday_verified_quote" if strict_real_data else "non_strict",
                        meta["fetched_at"],
                        "verified_real_price" if strict_real_data else "non_strict",
                    ),
                )
                flow_meta = flow_execution_metadata(d)
                conn.execute(
                    """UPDATE paper_trade
                       SET execution_tier='normal', flow_state=?, fallback_status=?,
                           gate_reasons=?, promotion_status='promoted'
                       WHERE id=last_insert_rowid()""",
                    (
                        flow_meta["flow_state"], flow_meta["fallback_status"],
                        json.dumps(d.get("gate_reasons") or [], ensure_ascii=False),
                    ),
                )
                actions.append({
                    "action": "BUY", "stock_code": code, "shares": shares,
                    "price": buy_price, "fee": fee, "execution_tier": "normal",
                    "promotion_status": "promoted", "execution_at": now,
                    "reason": "probe_promoted_topup; no_average_down",
                    "price_date": meta["price_date"], "price_source": meta["price_source"],
                })
                for industry_position in industry_positions:
                    if industry_position["industry"] == str(p.get("industry") or "").strip():
                        industry_position["market_value"] += value
                        break

            # Enter approved deep BUYs at the normal cap. A strict production
            # run may use one small flow-incomplete probe; legacy momentum
            # probes remain available only to non-strict replay/test callers.
            probe_entries = sum(
                1
                for position in positions.values()
                if str(position.get("execution_tier") or "normal") == "probe"
                and str(position.get("entry_date") or "") == trade_date
            )
            probe_total_value = sum(
                int(position.get("shares") or 0)
                * float(quotes[code][1])
                for code, position in positions.items()
                if str(position.get("execution_tier") or "normal") == "probe"
                and code in quotes and quotes[code][1] > 0
            )
            probe_max_entries = (
                min(1, max(0, int(getattr(settings, "PAPER_EXPLORATION_MAX_ENTRIES", 1))))
                if strict_real_data else PAPER_MOMENTUM_PROBE_MAX_ENTRIES
            )
            industry_positions = [
                {
                    "industry": str(position.get("industry") or "").strip(),
                    "market_value": int(position.get("shares") or 0) * float(quotes[code][1]),
                }
                for code, position in positions.items()
                if code in quotes and quotes[code][1] > 0
            ]

            def record_buy_rejection(decision: dict, reason: str, price: float) -> None:
                rejection = {
                    "signal_date": str(decision.get("date") or trade_date),
                    "stock_code": str(decision.get("stock_code") or ""),
                    "stock_name": str(decision.get("stock_name") or decision.get("stock_code") or ""),
                    "direction": decision_direction(decision),
                    "reason": reason,
                    "quote_date": str(decision.get("market_price_date") or trade_date),
                    "quote_source": str(decision.get("market_price_source") or ""),
                    "quote_price": float(price or 0),
                    "execution_at": now,
                    "signal_at": str(decision.get("signal_at") or ""),
                    "data_cutoff_at": str(decision.get("data_cutoff_at") or ""),
                    "quote_exchange_at": str(decision.get("market_price_exchange_at") or ""),
                }
                rejections.append(rejection)
                cursor = conn.execute(
                    """INSERT INTO paper_order_rejection(
                           signal_date, stock_code, stock_name, direction,
                           reason, quote_date, quote_source, quote_price,
                           execution_at, signal_at, data_cutoff_at,
                           quote_exchange_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(rejection.values()),
                )
                flow_meta = flow_execution_metadata(decision)
                conn.execute(
                    """UPDATE paper_order_rejection
                       SET execution_tier='blocked', flow_state=?,
                           fallback_status=?, gate_reasons=?
                       WHERE id=?""",
                    (
                        flow_meta["flow_state"],
                        flow_meta["fallback_status"],
                        json.dumps(
                            decision.get("gate_reasons") or [],
                            ensure_ascii=False,
                        ),
                        cursor.lastrowid,
                    ),
                )

            for d in sorted(
                decisions,
                key=lambda item: max(
                    float(item.get("ai_score") or 0),
                    momentum_probe_rank(item),
                ),
                reverse=True,
            ):
                if len(positions) >= PAPER_MAX_POSITIONS:
                    break
                code = str(d.get("stock_code") or "")
                score = finite_or(d.get("ai_score"), 50.0)
                if code in positions or code in sold_codes:
                    continue
                deep_approved = is_deep_buy_approved(d)
                flow_entry = evaluate_entry_execution(
                    d,
                    allow_probe=flow_probe_enabled,
                    paper_mode=True,
                )
                flow_probe_candidate = (
                    flow_entry["tier"] == ExecutionTier.PROBE.value
                )
                legacy_probe_candidate = is_momentum_probe_candidate(d)
                conditional_probe_candidate = is_conditional_probe_candidate(d)
                probe_candidate = (
                    flow_probe_candidate
                    or legacy_probe_candidate
                    or conditional_probe_candidate
                )
                is_probe = False
                is_conditional_probe = False
                probe_reason = ""
                flow_metadata_supplied = any(
                    key in d
                    for key in (
                        "market_flow", "flow_status", "flow_state",
                        "flow_sources", "fallback_attempted", "fallback_status",
                    )
                )
                if strict_real_data:
                    if deep_approved and flow_entry["tier"] in {
                        ExecutionTier.NORMAL.value,
                        ExecutionTier.PROBE.value,
                    } or deep_approved and not flow_metadata_supplied:
                        is_probe = flow_probe_candidate
                    elif not deep_approved and flow_probe_candidate:
                        is_probe = True
                    elif not deep_approved and legacy_probe_candidate:
                        probe_reason = momentum_probe_rejection_reason(d)
                        if not probe_reason and probe_entries >= probe_max_entries:
                            probe_reason = "momentum_probe_entry_limit_reached"
                        if probe_reason:
                            record_buy_rejection(
                                d, probe_reason, float(d.get("market_price") or 0)
                            )
                            continue
                        is_probe = True
                    elif not deep_approved and conditional_probe_candidate:
                        probe_reason = conditional_probe_rejection_reason(d)
                        if not probe_reason and probe_entries >= probe_max_entries:
                            probe_reason = "conditional_probe_entry_limit_reached"
                        if probe_reason:
                            record_buy_rejection(
                                d, probe_reason, float(d.get("market_price") or 0)
                            )
                            continue
                        is_probe = True
                        is_conditional_probe = True
                    elif is_buy_signal(d) or (
                        str(d.get("pre_gate_direction") or "").lower() == "buy"
                        and flow_entry["tier"] == ExecutionTier.BLOCKED.value
                    ):
                        rejection_reason = deep_buy_rejection_reason(d)
                        if flow_entry["tier"] == ExecutionTier.BLOCKED.value or not rejection_reason:
                            rejection_reason = str(
                                flow_entry.get("reason") or rejection_reason
                            )
                        record_buy_rejection(
                            d,
                            rejection_reason,
                            float(d.get("market_price") or 0),
                        )
                        continue
                    else:
                        continue
                    if is_probe and probe_entries >= probe_max_entries:
                        probe_reason = (
                            "conditional_probe_entry_limit_reached"
                            if is_conditional_probe
                            else "flow_probe_entry_limit_reached"
                        )
                elif not deep_approved:
                    if not probe_candidate:
                        continue
                    probe_reason = (
                        conditional_probe_rejection_reason(d)
                        if conditional_probe_candidate and not legacy_probe_candidate
                        else momentum_probe_rejection_reason(d)
                    )
                    if not probe_reason and probe_entries >= probe_max_entries:
                        probe_reason = "momentum_probe_entry_limit_reached"
                    if probe_reason:
                        record_buy_rejection(d, probe_reason, float(d.get("market_price") or 0))
                        continue
                    is_probe = True
                    is_conditional_probe = (
                        conditional_probe_candidate and not legacy_probe_candidate
                    )
                if probe_reason:
                    record_buy_rejection(
                        d,
                        probe_reason,
                        float(d.get("market_price") or 0),
                    )
                    continue
                if strict_real_data and not legacy_probe_candidate:
                    d.update(flow_entry)
                if strict_real_data:
                    d["execution_disposition"] = (
                        "probe" if is_probe else "normal"
                    )
                price = quotes.get(code, ({}, 0))[1]
                if price <= 0:
                    continue
                quote = self.get_latest_quote(code) or {}
                limit_pct = price_limit_pct(code, is_st=bool(d.get("is_st")))
                change_pct = resolve_change_pct(d, quote, trade_date)
                if at_limit_up(change_pct, limit_pct):
                    continue
                buy_price = quantize_price(price * 1.001)
                min_cash_reserve = marked_value * PAPER_MIN_CASH_RESERVE_PCT
                available_cash = max(0.0, cash - min_cash_reserve)
                order_position_cap = (
                        min(
                            position_cap_pct,
                            probe_position_pct
                            if strict_real_data else PAPER_MOMENTUM_PROBE_POSITION_PCT,
                        probe_max_position_pct
                        if strict_real_data else PAPER_MOMENTUM_PROBE_POSITION_PCT,
                    )
                    if is_probe
                    else position_cap_pct
                )
                budget = min(available_cash, marked_value * order_position_cap)
                if is_probe and strict_real_data:
                    probe_total_cap = marked_value * probe_total_pct
                    budget = min(
                        budget,
                        max(0.0, probe_total_cap - probe_total_value),
                    )
                shares = int(budget // buy_price // 100) * 100
                value = shares * buy_price
                costs = calculate_trade_costs(value, "BUY")
                fee = costs["total_fees"]
                while shares > 0 and value + fee > available_cash:
                    shares -= 100
                    value = shares * buy_price
                    costs = calculate_trade_costs(value, "BUY")
                    fee = costs["total_fees"]
                if shares <= 0:
                    rejection = {
                        "signal_date": str(d.get("date") or trade_date),
                        "stock_code": code,
                        "stock_name": str(d.get("stock_name") or code),
                        "direction": decision_direction(d),
                        "reason": "position_cap_below_one_round_lot",
                        "quote_date": str(d.get("market_price_date") or trade_date),
                        "quote_source": str(d.get("market_price_source") or ""),
                        "quote_price": float(price),
                        "execution_at": now,
                        "signal_at": str(d.get("signal_at") or ""),
                        "data_cutoff_at": str(d.get("data_cutoff_at") or ""),
                        "quote_exchange_at": str(
                            d.get("market_price_exchange_at") or ""
                        ),
                    }
                    rejections.append(rejection)
                    conn.execute(
                        """INSERT INTO paper_order_rejection(
                               signal_date, stock_code, stock_name, direction,
                               reason, quote_date, quote_source, quote_price,
                               execution_at, signal_at, data_cutoff_at,
                               quote_exchange_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        tuple(rejection.values()),
                    )
                    continue
                exposure = projected_industry_exposure(
                    industry_positions,
                    d.get("universe_industry") or d.get("industry"),
                    value,
                    marked_value,
                )
                if not exposure["allowed"] and not (
                    not strict_real_data
                    and exposure["reason"] == "industry_metadata_missing"
                ):
                    record_buy_rejection(d, str(exposure["reason"]), price)
                    continue
                meta = quote_meta.get(code)
                if not meta:
                    record_buy_rejection(d, "quote_metadata_missing", price)
                    continue
                cash -= value + fee
                fill_at = now
                positions[code] = {
                    "stock_code": code, "stock_name": d.get("stock_name") or code,
                    "shares": shares, "avg_cost": buy_price,
                    "industry": str(
                        d.get("universe_industry") or d.get("industry") or ""
                    ).strip(),
                    "entry_date": trade_date, "eligible_sell_date": trade_date,
                    "entry_price_date": meta["price_date"],
                    "entry_price_source": meta["price_source"],
                    "execution_mode": (
                        "intraday_verified_quote" if strict_real_data else "non_strict"
                    ),
                    "entry_decision_id": d.get("journal_id"),
                    "entry_strategy_version": str(d.get("strategy_version") or ""),
                    "entry_deep_rating": str(d.get("deep_rating") or ""),
                    "entry_identity_status": (
                        "verified"
                        if d.get("journal_id") is not None
                        and str(d.get("strategy_version") or "").strip()
                        else "legacy_unverified"
                    ),
                    "execution_tier": (
                        ExecutionTier.PROBE.value if is_probe
                        else ExecutionTier.NORMAL.value
                    ),
                    "entry_flow_state": str(
                        flow_entry.get("flow_state")
                        or d.get("flow_state")
                        or d.get("flow_status")
                        or ""
                    ),
                    "entry_fallback_status": str(
                        flow_entry.get("fallback_status")
                        or d.get("fallback_status")
                        or ""
                    ),
                    "entry_gate_reasons": json.dumps(
                        d.get("gate_reasons") or [],
                        ensure_ascii=False,
                    ),
                    "probe_expiry_date": (
                        _future_trading_date(
                            conn,
                            trade_date,
                            int(
                                getattr(
                                    settings,
                                    "PAPER_EXPLORATION_MAX_HOLDING_DAYS",
                                    5,
                                )
                            ),
                        )
                        if is_probe and strict_real_data else ""
                    ),
                    "promotion_status": "open" if is_probe else "none",
                }
                conn.execute(
                    """INSERT OR REPLACE INTO paper_position
                        (stock_code, stock_name, shares, avg_cost, updated_at,
                         entry_date, eligible_sell_date, entry_price_date,
                         entry_price_source, execution_mode, entry_decision_id,
                         entry_strategy_version, entry_deep_rating,
                         entry_identity_status, industry, execution_tier,
                         entry_flow_state, entry_fallback_status,
                         entry_gate_reasons, probe_expiry_date, promotion_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        code, d.get("stock_name") or code, shares, buy_price,
                        fill_at, trade_date, trade_date, meta["price_date"],
                        meta["price_source"],
                        "intraday_verified_quote" if strict_real_data else "non_strict",
                        d.get("journal_id"), str(d.get("strategy_version") or ""),
                        str(d.get("deep_rating") or ""),
                        (
                            "verified"
                            if d.get("journal_id") is not None
                            and str(d.get("strategy_version") or "").strip()
                            else "legacy_unverified"
                        ),
                        positions[code]["industry"],
                        positions[code]["execution_tier"],
                        positions[code]["entry_flow_state"],
                        positions[code]["entry_fallback_status"],
                        positions[code]["entry_gate_reasons"],
                        positions[code]["probe_expiry_date"],
                        positions[code]["promotion_status"],
                    ),
                )
                conn.execute(
                    """INSERT INTO paper_trade
                       (trade_date, action, stock_code, stock_name, shares,
                        price, value, reason, created_at, decision_id, fee,
                        commission, stamp_tax, slippage, signal_date, signal_at,
                        data_cutoff_at, quote_exchange_at, source_lag_seconds,
                        causality_status,
                        price_date, price_source,
                        execution_mode, quote_fetched_at, integrity_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trade_date, "BUY", code, d.get("stock_name") or code, shares,
                        buy_price, value,
                        (
                            (
                                f"conditional_realtime_probe; "
                                f"flow_state={flow_entry.get('flow_state')}; "
                                f"max_position={order_position_cap:.0%}; min_cash=10%"
                            )
                            if strict_real_data and is_probe and is_conditional_probe else
                            (
                                f"flow_probe; flow_state={flow_entry.get('flow_state')}; "
                                f"max_position={order_position_cap:.0%}; min_cash=10%"
                            )
                            if strict_real_data and is_probe and not legacy_probe_candidate else
                            f"momentum_probe; raw_score={momentum_probe_rank(d):.1f}; "
                            f"max_position={order_position_cap:.0%}; min_cash=10%"
                            if is_probe else
                            f"ai_score={score:.1f}; direction=buy; "
                            f"deep_rating={d.get('deep_rating')}; "
                            f"max_position={order_position_cap:.0%}; min_cash=10%"
                        ),
                        fill_at, d.get("journal_id"), fee,
                        costs["commission"], costs["stamp_tax"],
                        shares * (buy_price - price), d.get("date") or trade_date,
                        d.get("signal_at") or now,
                        d.get("data_cutoff_at") or d.get("signal_at") or now,
                        meta.get("exchange_at") or fill_at,
                        meta.get("source_lag_seconds"),
                        meta.get("causality_status") or "non_strict",
                        meta["price_date"], meta["price_source"],
                        "intraday_verified_quote" if strict_real_data else "non_strict",
                        meta["fetched_at"],
                        "verified_real_price" if strict_real_data else "non_strict",
                    ),
                )
                conn.execute(
                    """UPDATE paper_trade
                       SET execution_tier=?, flow_state=?, fallback_status=?,
                           gate_reasons=?, promotion_status=?
                       WHERE id=last_insert_rowid()""",
                    (
                        ExecutionTier.PROBE.value if is_probe else ExecutionTier.NORMAL.value,
                        str(flow_entry.get("flow_state") or d.get("flow_state") or ""),
                        str(flow_entry.get("fallback_status") or d.get("fallback_status") or ""),
                        json.dumps(d.get("gate_reasons") or [], ensure_ascii=False),
                        "open" if is_probe else "",
                    ),
                )
                actions.append({
                    "action": "BUY", "stock_code": code, "shares": shares,
                    "price": buy_price, "fee": fee,
                    "execution_tier": (
                        ExecutionTier.PROBE.value if is_probe
                        else ExecutionTier.NORMAL.value
                    ),
                    "commission": costs["commission"],
                    "stamp_tax": costs["stamp_tax"],
                    "execution_at": fill_at,
                    "causality_status": meta.get("causality_status") or "non_strict",
                    "reason": (
                        (
                            f"conditional_realtime_probe; "
                            f"flow_state={flow_entry.get('flow_state')}; "
                            f"max_position={order_position_cap:.0%}"
                        )
                        if strict_real_data and is_probe and is_conditional_probe else
                        (
                            f"flow_probe; flow_state={flow_entry.get('flow_state')}; "
                            f"max_position={order_position_cap:.0%}"
                        )
                        if strict_real_data and is_probe and not legacy_probe_candidate else
                        f"momentum_probe; raw_score={momentum_probe_rank(d):.1f}; "
                        f"max_position={order_position_cap:.0%}"
                        if is_probe else
                        f"codex_terra={d.get('deep_rating')}; "
                        f"max_position={order_position_cap:.0%}"
                    ),
                    "price_date": meta["price_date"],
                    "price_source": meta["price_source"],
                })
                if is_probe:
                    probe_entries += 1
                    probe_total_value += value
                industry_positions.append({
                    "industry": positions[code]["industry"],
                    "market_value": value,
                })

            conn.execute(
                "UPDATE paper_account SET cash=?, updated_at=? WHERE id=1", (cash, now)
            )
        return {
            "cash": round(cash, 2),
            "position_count": len(positions),
            "actions": actions,
            "execution_status": (
                "executed" if actions else "verified_no_action"
            ),
            "execution_at": now,
            "rejections": rejections,
            "probe_opened": sum(
                1
                for action in actions
                if action.get("execution_tier") == ExecutionTier.PROBE.value
                and action.get("action") == "BUY"
            ),
            "probe_promoted": len(promotions),
            "probe_expired": sum(
                1
                for action in actions
                if action.get("execution_tier") == ExecutionTier.PROBE.value
                and action.get("action") == "SELL"
                and str(action.get("reason") or "").startswith("probe_")
            ),
            "promotions": promotions,
            "max_position_pct": position_cap_pct,
            "probe_entries": sum(
                1
                for action in actions
                if action.get("execution_tier") == ExecutionTier.PROBE.value
                and action.get("action") == "BUY"
            ),
            "probe_policy": {
                "enabled": flow_probe_enabled,
                "position_pct": float(
                    probe_position_pct
                ),
                "max_position_pct": float(
                    probe_max_position_pct
                ),
                "max_total_pct": float(
                    probe_total_pct
                ),
                "max_entries": probe_max_entries,
            },
            "new_position_policy": (
                "codex_deep_buy_up_to_20pct_or_guarded_2pct_probe"
                if strict_real_data
                else "codex_deep_buy_up_to_20pct_or_confirmed_2pct_observation"
            ),
        }

    def get_paper_portfolio(self, as_of_date: str | None = None) -> dict:
        """Return paper holdings using the latest auditable mark when available."""
        self.ensure_paper_account()
        target_date = as_of_date or dt_date.today().isoformat()
        with self._get_conn() as conn:
            account = dict(conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone())
            rows = [dict(r) for r in conn.execute("SELECT * FROM paper_position WHERE shares > 0")]
            fee_totals = dict(conn.execute(
                """SELECT COALESCE(SUM(commission), 0) AS commission,
                          COALESCE(SUM(stamp_tax), 0) AS stamp_tax,
                          COALESCE(SUM(fee), 0) AS total_fees
                   FROM paper_trade"""
            ).fetchone())
            snapshot_row = conn.execute(
                """SELECT * FROM paper_portfolio_snapshot
                   WHERE snapshot_date <= ? ORDER BY snapshot_date DESC LIMIT 1""",
                (target_date,),
            ).fetchone()
            snapshot = dict(snapshot_row) if snapshot_row is not None else None
            marks: dict[str, dict[str, Any]] = {}
            if snapshot is not None:
                current_codes = {str(row["stock_code"]) for row in rows}
                marks = {
                    row["stock_code"]: dict(row)
                    for row in conn.execute(
                        "SELECT * FROM paper_position_mark WHERE mark_date=?",
                        (snapshot["snapshot_date"],),
                    )
                    if str(row["stock_code"]) in current_codes
                }
        trades = self.get_paper_trades(limit=30)
        order_rejections = self.get_paper_order_rejections(limit=30)
        positions = []
        invested = 0.0
        for p in rows:
            mark = marks.get(p["stock_code"])
            quote = self.get_latest_quote(p["stock_code"]) or {}
            price = float(
                (mark or {}).get("price")
                or quote.get("price")
                or p["avg_cost"]
            )
            pre_close = float((mark or {}).get("pre_close") or quote.get("pre_close") or price)
            market_value = p["shares"] * price
            cost_value = p["shares"] * p["avg_cost"]
            invested += market_value
            positions.append({
                "stock_code": p["stock_code"], "stock_name": p["stock_name"],
                "shares": p["shares"], "cost_price": p["avg_cost"],
                "current_price": price, "market_value": market_value,
                "cost_value": cost_value, "profit_loss": market_value - cost_value,
                "profit_loss_pct": ((market_value / cost_value) - 1) * 100 if cost_value else 0,
                "daily_pl": p["shares"] * (price - pre_close),
                "daily_pl_pct": ((price / pre_close) - 1) * 100 if pre_close else 0,
                "price_date": (mark or {}).get("price_date") or quote.get("data_date") or "",
                "price_source": (mark or {}).get("price_source") or quote.get("source") or "",
                "price_fresh": bool((mark or {}).get("is_fresh")),
                "entry_decision_id": p.get("entry_decision_id"),
                "entry_strategy_version": p.get("entry_strategy_version") or "",
                "entry_deep_rating": p.get("entry_deep_rating") or "",
                "entry_identity_status": p.get(
                    "entry_identity_status", "legacy_unverified"
                ),
                "industry": p.get("industry") or "",
                "execution_tier": p.get("execution_tier") or "normal",
                "entry_flow_state": p.get("entry_flow_state") or "",
                "entry_fallback_status": p.get("entry_fallback_status") or "",
                "entry_gate_reasons": _json_list(p.get("entry_gate_reasons")),
                "probe_expiry_date": p.get("probe_expiry_date") or "",
                "promotion_status": p.get("promotion_status") or "none",
            })
        total = float(account["cash"]) + invested
        exact_snapshot = bool(snapshot and snapshot["snapshot_date"] == target_date)
        marks_cover_positions = set(marks) >= {
            str(position["stock_code"]) for position in rows
        }
        use_snapshot_daily = exact_snapshot and marks_cover_positions
        daily_pl = float(snapshot["daily_pl"]) if use_snapshot_daily else 0.0
        daily_pl_pct = float(snapshot["daily_pl_pct"]) if use_snapshot_daily else 0.0
        price_coverage = float(snapshot["price_coverage"]) if use_snapshot_daily else 0.0
        stale_positions = (
            json.loads(snapshot["stale_positions_json"] or "[]")
            if use_snapshot_daily else [p["stock_code"] for p in rows]
        )
        price_sources = (
            json.loads(snapshot["price_sources_json"] or "[]")
            if use_snapshot_daily else sorted({p["price_source"] for p in positions if p["price_source"]})
        )
        return {
            "date": target_date, "initial_capital": account["initial_capital"],
            "cash": account["cash"], "total_value": total,
            "total_pl": total - account["initial_capital"],
            "total_pl_pct": ((total / account["initial_capital"]) - 1) * 100,
            "daily_pl": daily_pl, "daily_pl_pct": daily_pl_pct,
            "market_pnl": float(snapshot.get("market_pnl") or 0) if use_snapshot_daily else 0.0,
            "realized_pnl": float(snapshot.get("realized_pnl") or 0) if use_snapshot_daily else 0.0,
            "fees": float(snapshot.get("fees") or 0) if use_snapshot_daily else 0.0,
            "equity_change": float(snapshot.get("equity_change") or daily_pl)
            if use_snapshot_daily else 0.0,
            "reconciliation_delta": float(snapshot.get("reconciliation_delta") or 0)
            if use_snapshot_daily else 0.0,
            "reconciliation_status": snapshot.get("reconciliation_status") or "unknown"
            if use_snapshot_daily else "unknown",
            "price_date": snapshot["snapshot_date"] if snapshot else "",
            "price_coverage": price_coverage,
            "price_sources": price_sources,
            "stale_positions": stale_positions,
            "valuation_status": (
                "fresh" if use_snapshot_daily and price_coverage == 1.0
                else "partial" if use_snapshot_daily and price_coverage > 0
                else "stale"
            ),
            "positions": positions, "trades": trades,
            "order_rejections": order_rejections,
            "portfolio_mode": "paper_trading",
            "data_source": "paper_position_mark + local SQLite paper account",
            "ledger_version": int(account.get("ledger_version") or 1),
            "ledger_quality": account.get("ledger_quality") or "legacy_unverified",
            "ledger_rebuilt_at": account.get("ledger_rebuilt_at") or "",
            "price_policy": account.get("price_policy") or "legacy",
            "commission_rate": float(account.get("commission_rate") or 0),
            "stamp_tax_rate": float(account.get("stamp_tax_rate") or 0),
            "fee_policy": account.get("fee_policy") or "legacy",
            "execution_policy": account.get("execution_policy") or "legacy",
            "total_commission": float(fee_totals["commission"] or 0),
            "total_stamp_tax": float(fee_totals["stamp_tax"] or 0),
            "total_fees": float(fee_totals["total_fees"] or 0),
        }

    def save_learning(self, learning_date: str, category: str, lesson: str,
                      evidence: dict | None = None) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO learning_log
                   (learning_date, category, lesson, evidence_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (learning_date, category, lesson, json.dumps(evidence or {}, ensure_ascii=False),
                 datetime.now().isoformat()),
            )
            return cursor.lastrowid

    def upsert_daily_learning(self, learning_date: str, category: str, lesson: str,
                              evidence: dict | None = None) -> int:
        """Keep one durable daily snapshot for a learning category."""
        payload = json.dumps(evidence or {}, ensure_ascii=False)
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM learning_log WHERE learning_date=? AND category=? ORDER BY id LIMIT 1",
                (learning_date, category),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE learning_log SET lesson=?, evidence_json=?, created_at=? WHERE id=?",
                    (lesson, payload, now, row["id"]),
                )
                return int(row["id"])
            cursor = conn.execute(
                """INSERT INTO learning_log
                   (learning_date, category, lesson, evidence_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (learning_date, category, lesson, payload, now),
            )
            return int(cursor.lastrowid)

    def save_strategy_decision(self, decision: dict, journal_id: int | None = None) -> int:
        """Persist one immutable model result linked to its exact journal row.

        The legacy key used one row per stock/day, so an afternoon technical
        scan replaced the morning TradingAgents result. A journal-scoped key
        keeps every run separate while remaining compatible with the existing
        SQLite uniqueness constraint.
        """
        analysis = {
            key: decision.get(key)
            for key in (
                "deep_analysis", "deep_thesis", "deep_trader_plan",
                "deep_analysis_available", "deep_analysis_error",
                "deep_provider", "deep_model", "deep_source", "deep_runtime",
                "deep_cached", "deep_duration_seconds", "deep_input_fingerprint",
                "deep_kline_evidence",
                "deep_evidence_consumption",
                "deep_evidence_gaps",
                "tradingagents_rating", "tradingagents_direction",
                "tradingagents_score", "final_review_required",
                "preselection_input_sha256", "preselection_input_chars",
                "preselection_input_count", "preselection_input_fields",
                "preselection_provider", "preselection_model", "preselection_called",
                "final_review_available", "final_review_verdict",
                "final_review_reason", "final_review_risk",
                 "final_review_provider", "final_review_model",
                 "final_review_fallback_used", "final_review_error",
                 "preselection_input_sha256", "preselection_input_chars",
                 "preselection_input_count", "preselection_input_fields",
                 "final_review_input_sha256", "final_review_input_chars",
                 "final_review_input_count", "final_review_input_fields",
                 "final_buy_approved",
                 "decision_status",
                 "predicted_direction", "executable_direction",
                 "raw_ai_score", "scanner_score", "preselection_base_score",
                 "preselection_adjusted_score", "deep_base_score", "deep_score",
                 "research_score", "primary_score", "primary_score_label",
                 "ranking_score_label", "display_state", "display_state_label",
                 "ranking_score", "action_score", "score_lineage",
                 "score_guarded", "score_guard_reasons",
                 "fundamental_evidence_available", "execution_evidence_complete",
                 "market_evidence_complete", "market_evidence_sources",
                 "market_evidence_reasons", "evidence_status", "actionability_status",
                 "evidence_enrichment",
                 "quote_enrichment_status", "quote_enrichment_reason",
                 "quote_enrichment_ranking_score",
                 "quote_enrichment_min_ranking_score",
                 "publication_blocked", "publication_block_reasons",
                 "recommendation_tier", "technical_data_through",
                 "run_id", "strategy_name", "strategy_version",
                 "config_snapshot", "config_hash", "code_hash", "run_created_at",
                 "actionable", "deep_candidate_eligible",
                 "deep_candidate_exclusion_reason",
                 "pre_gate_direction", "final_direction", "flow_state",
                 "flow_sources", "flow_source", "flow_status", "fallback_attempted",
                 "fallback_status", "market_sources", "market_reasons",
                 "market_flow", "market_price", "market_pre_close",
                 "market_change_pct", "market_price_source", "market_price_date",
                 "market_price_fetched_at", "market_price_exchange_at",
                 "market_volume_ratio", "market_active_volume_ratio",
                 "data_cutoff_at", "signal_at",
                 "gate_reasons", "non_flow_gates_passed",
                 "execution_disposition", "execution_block_reason",
                 "execution_status_label", "execution_quote_verified",
                 "evidence", "confidence", "fusion_score", "macd_score",
                "rsi_score", "kdj_score", "ma_score", "volume_score",
            )
            if decision.get(key) not in (None, "")
        }
        strategy_name = (
            f"adaptive-paper:journal:{journal_id}"
            if journal_id is not None
            else f"adaptive-paper:standalone:{time.time_ns()}"
        )
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT OR REPLACE INTO strategy_decision
                   (journal_id, decision_date, stock_code, strategy_name,
                    strategy_version, technical_score, deep_rating,
                    effective_direction, analysis_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    journal_id, decision.get("date", ""), decision.get("stock_code", ""),
                    strategy_name,
                    decision.get("strategy_version") or "2.1",
                    decision.get("technical_score", decision.get("ai_score", 50)),
                    decision.get("deep_rating", ""), decision.get("direction", "neutral"),
                    json.dumps(analysis, ensure_ascii=False), datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    def get_research_case_rows(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Return persisted decisive cases for rebuilding calibration memory.

        One row per ``(decision_date, stock_code)``.  Several scans run each day
        and the journal keeps a row per scan, so reading them raw inflated the
        case library ~2.4x and weighted the confidence-calibration curve by
        scan count rather than by decision.  The latest row for the day is kept,
        matching the "latest write wins" rule the execution path applies and the
        same guard ``get_pending_market_learning_decisions`` already uses -- the
        two views must agree or calibration measures a different population
        than learning does.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """WITH ranked AS (
                       SELECT d.id, d.decision_date, d.stock_code, d.stock_name,
                              d.ai_score, d.confidence, d.direction,
                              d.recommendation, d.outcome_known, d.actual_return,
                              d.was_correct, d.created_at,
                              ROW_NUMBER() OVER (
                                  PARTITION BY d.decision_date, d.stock_code
                                  ORDER BY d.id DESC
                              ) AS scan_rank
                         FROM decision_journal AS d
                        WHERE LOWER(TRIM(COALESCE(d.direction, '')))
                              IN ('buy', 'sell')
                   )
                   SELECT r.id, r.decision_date, r.stock_code, r.stock_name,
                          r.ai_score, r.confidence, r.direction, r.recommendation,
                          r.outcome_known, r.actual_return, r.was_correct,
                          r.created_at, s.analysis_json
                     FROM ranked AS r
                     LEFT JOIN strategy_decision AS s ON s.journal_id = r.id
                    WHERE r.scan_rank = 1
                    ORDER BY r.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_cached_deep_analyses(
        self,
        decision_date: str,
        stock_codes: list[str],
        provider: str = "",
        model: str = "",
        input_fingerprints: dict[str, str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Reuse deep results only when the evidence packet identity matches."""
        normalized = list(dict.fromkeys(
            str(code or "").strip().upper() for code in stock_codes if str(code or "").strip()
        ))
        if not decision_date or not normalized:
            return {}
        placeholders = ",".join("?" for _ in normalized)
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT stock_code, deep_rating, effective_direction, analysis_json
                    FROM strategy_decision
                    WHERE decision_date=?
                      AND UPPER(stock_code) IN ({placeholders})
                      AND COALESCE(deep_rating, '')<>''
                    ORDER BY id DESC""",
                (decision_date, *normalized),
            ).fetchall()
        scores = {
            "buy": 85.0,
            "overweight": 72.0,
            "hold": 50.0,
            "underweight": 35.0,
            "sell": 20.0,
        }
        cached: dict[str, dict[str, Any]] = {}
        for row in rows:
            code = str(row["stock_code"] or "").upper()
            if code in cached:
                continue
            try:
                analysis = json.loads(row["analysis_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                analysis = {}
            cached_provider = str(analysis.get("deep_provider") or "codex_cli")
            cached_model = str(analysis.get("deep_model") or "gpt-5.6-terra")
            if provider and cached_provider != provider:
                continue
            if model and cached_model != model:
                continue
            if input_fingerprints is not None:
                expected = str(input_fingerprints.get(code) or "")
                actual = str(analysis.get("deep_input_fingerprint") or "")
                # Legacy same-day rows have no packet identity.  They remain
                # readable for audit, but cannot be reused after a new scan.
                if not expected or not actual or actual != expected:
                    continue
            rating = str(row["deep_rating"] or "Hold")
            cached[code] = {
                "available": True,
                "stock_code": code,
                "rating": rating,
                "direction": str(row["effective_direction"] or "neutral"),
                "score": scores.get(rating.lower(), 50.0),
                "decision": str(analysis.get("deep_analysis") or ""),
                "thesis": str(analysis.get("deep_thesis") or ""),
                "trader_plan": str(analysis.get("deep_trader_plan") or ""),
                "kline_evidence": analysis.get("deep_kline_evidence") or {},
                "deep_evidence_consumption": analysis.get(
                    "deep_evidence_consumption"
                ) or {},
                "evidence_gaps": analysis.get("deep_evidence_gaps") or [],
                "provider": cached_provider,
                "model": cached_model,
                "runtime": str(analysis.get("deep_runtime") or "persisted_same_day"),
                "duration_seconds": float(analysis.get("deep_duration_seconds") or 0),
                "deep_input_fingerprint": str(
                    analysis.get("deep_input_fingerprint") or ""
                ),
                "cached": True,
                "source": str(
                    analysis.get("deep_source")
                    or ("Codex-Terra Multi-Agent" if cached_provider == "codex_cli"
                        else "TradingAgents-Astock")
                ),
            }
        return cached

    def count_cached_deep_analyses(
        self, decision_date: str, provider: str = "", model: str = ""
    ) -> int:
        """Count unique successful deep analyses for an optional runtime."""
        if not decision_date:
            return 0
        conditions = ["decision_date=?", "COALESCE(deep_rating, '')<>''"]
        params: list[Any] = [decision_date]
        if provider:
            conditions.append("json_extract(analysis_json, '$.deep_provider')=?")
            params.append(provider)
        if model:
            conditions.append("json_extract(analysis_json, '$.deep_model')=?")
            params.append(model)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT stock_code) AS n FROM strategy_decision WHERE "
                + " AND ".join(conditions),
                tuple(params),
            ).fetchone()
        return int(row["n"] or 0)

    def count_daily_deep_attempts(
        self, decision_date: str, provider: str = "", model: str = ""
    ) -> int:
        """Count unique same-day deep calls, including failed attempts."""
        if not decision_date:
            return 0
        conditions = [
            "decision_date=?",
            "(COALESCE(deep_rating, '')<>'' OR "
            "COALESCE(json_extract(analysis_json, '$.deep_analysis_error'), '')<>'')",
        ]
        params: list[Any] = [decision_date]
        if provider:
            conditions.append("json_extract(analysis_json, '$.deep_provider')=?")
            params.append(provider)
        if model:
            conditions.append("json_extract(analysis_json, '$.deep_model')=?")
            params.append(model)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT stock_code) AS n FROM strategy_decision WHERE "
                + " AND ".join(conditions),
                tuple(params),
            ).fetchone()
        return int(row["n"] or 0)

    def reserve_deep_analysis_slots(
        self,
        budget_date: str,
        research_window: str,
        candidates: list[dict[str, Any]],
        input_fingerprints: dict[str, str],
        *,
        window_limit: int,
        daily_limit: int,
        override_daily_limit: bool = False,
        override_window_usage: bool = False,
    ) -> dict[str, Any]:
        """Atomically reserve bounded deep calls across overlapping workers."""
        if not budget_date or not research_window or not candidates:
            return {"selected": [], "skipped": len(candidates), "used_before": 0}
        now = datetime.now().isoformat()
        selected: list[dict[str, Any]] = []
        skipped = 0
        with self._get_conn() as conn:
            legacy_used = self.count_daily_deep_attempts(budget_date)
            persisted_row = conn.execute(
                """SELECT COUNT(*) AS n FROM deep_analysis_attempt
                   WHERE budget_date=? AND status IN ('reserved','success','failed','timeout')""",
                (budget_date,),
            ).fetchone()
            persisted_used = int(persisted_row["n"] or 0)
            daily_used = max(legacy_used, persisted_used)
            window_row = conn.execute(
                """SELECT COUNT(*) AS n FROM deep_analysis_attempt
                   WHERE budget_date=? AND research_window=?
                     AND status IN ('reserved','success','failed','timeout')""",
                (budget_date, research_window),
            ).fetchone()
            window_used = int(window_row["n"] or 0)
            used_before = daily_used
            for candidate in candidates:
                code = str(candidate.get("stock_code") or "").strip().upper()
                fingerprint = str(input_fingerprints.get(code) or "")
                if not code or not fingerprint:
                    skipped += 1
                    continue
                effective_window_used = (
                    len(selected) if override_window_usage else window_used
                )
                if effective_window_used >= max(0, int(window_limit)) or (
                    not override_daily_limit
                    and daily_used >= max(0, int(daily_limit))
                ):
                    skipped += 1
                    continue
                existing = conn.execute(
                    """SELECT id FROM deep_analysis_attempt
                       WHERE budget_date=? AND research_window=?
                         AND stock_code=? AND input_fingerprint=?""",
                    (budget_date, research_window, code, fingerprint),
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                index_row = conn.execute(
                    """SELECT COALESCE(MAX(attempt_index), 0) AS n
                       FROM deep_analysis_attempt
                       WHERE budget_date=? AND stock_code=?""",
                    (budget_date, code),
                ).fetchone()
                conn.execute(
                    """INSERT INTO deep_analysis_attempt(
                           budget_date, research_window, stock_code,
                           input_fingerprint, attempt_index, status,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?)""",
                    (
                        budget_date, research_window, code, fingerprint,
                        int(index_row["n"] or 0) + 1, now, now,
                    ),
                )
                selected.append(candidate)
                window_used += 1
                daily_used += 1
        return {
            "selected": selected,
            "skipped": skipped,
            "used_before": used_before,
            "used_after": daily_used,
            "window_used_after": window_used,
        }

    def finalize_deep_analysis_slots(
        self,
        budget_date: str,
        research_window: str,
        results: list[dict[str, Any]],
        input_fingerprints: dict[str, str],
    ) -> int:
        """Record the result of each previously reserved deep call."""
        if not budget_date or not research_window or not results:
            return 0
        now = datetime.now().isoformat()
        updated = 0
        with self._get_conn() as conn:
            for result in results:
                code = str(result.get("stock_code") or "").strip().upper()
                fingerprint = str(input_fingerprints.get(code) or "")
                if not code or not fingerprint:
                    continue
                available = bool(result.get("available"))
                status = "success" if available else (
                    "timeout" if str(result.get("error_type") or "") in {
                        "TimeoutError", "ResearchDeadlineExceeded"
                    } else "failed"
                )
                cursor = conn.execute(
                    """UPDATE deep_analysis_attempt
                       SET status=?, error_type=?, error_detail=?,
                           duration_seconds=?, updated_at=?
                       WHERE budget_date=? AND research_window=?
                         AND stock_code=? AND input_fingerprint=?
                         AND status='reserved'""",
                    (
                        status, str(result.get("error_type") or ""),
                        str(result.get("error") or "")[:240],
                        float(result.get("duration_seconds") or 0), now,
                        budget_date, research_window, code, fingerprint,
                    ),
                )
                updated += int(cursor.rowcount or 0)
        return updated

    def get_strategy_context(self, stock_code: str = "", limit: int = 12) -> list[dict]:
        with self._get_conn() as conn:
            if stock_code:
                rows = conn.execute(
                    """SELECT * FROM strategy_decision WHERE stock_code=?
                       ORDER BY decision_date DESC, id DESC LIMIT ?""",
                    (stock_code, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM strategy_decision ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["analysis"] = json.loads(item.pop("analysis_json") or "{}")
            result.append(item)
        return result

    def get_strategy_performance(self) -> dict:
        """Return BUY/SELL performance split by deep-decision rating."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT COALESCE(NULLIF(deep_rating, ''), 'technical_only') AS bucket,
                          COUNT(*) AS total,
                          SUM(CASE WHEN outcome_status='correct' THEN 1 ELSE 0 END) AS correct,
                          AVG(actual_return) AS avg_return
                   FROM strategy_decision
                   WHERE outcome_status IN ('correct', 'wrong')
                     AND LOWER(TRIM(COALESCE(effective_direction, ''))) IN ('buy', 'sell')
                   GROUP BY bucket"""
            ).fetchall()
        buckets = []
        for row in rows:
            total = int(row["total"] or 0)
            buckets.append({
                "strategy": row["bucket"], "total": total,
                "correct": int(row["correct"] or 0),
                "accuracy": round((row["correct"] or 0) / total, 3) if total else 0,
                "avg_return": round(float(row["avg_return"] or 0), 4),
            })
        return {"buckets": buckets, "data_source": "strategy_decision"}

    def get_learning_log(self, limit: int = 30) -> list[dict]:
        # Order by business date, not insertion id.  Outcome rows are written in
        # bulk by the backfiller and take high ids while carrying old
        # learning_dates, so `ORDER BY id DESC` let them fill 12 of the 30 slots
        # with entries days or weeks stale.  Ties keep newest-first.
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM learning_log
                   ORDER BY learning_date DESC, id DESC LIMIT ?""", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            result.append(item)
        return result

    def get_pending_market_learning_decisions(
        self, horizon_days: int = 1, limit: int = 1000
    ) -> list[dict]:
        """Return prior BUY/SELL calls that still need a market observation.

        Scans can contain hundreds of neutral candidates.  They are retained in
        the journal, but cannot teach the directional stock-selection model and
        must not crowd real recommendations out of this bounded queue.

        One row per ``(decision_date, stock_code)``: several scans run each day
        and the journal keeps a row per scan, so the same call would otherwise
        be observed -- and learned from -- once per scan.  That inflated
        ``observations`` and let a single day's event clear the minimum-sample
        threshold in ``market_learning``.  The latest row for the day is the one
        used, matching the "latest write wins" rule the execution path applies.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """WITH ranked AS (
                       SELECT d.*,
                              ROW_NUMBER() OVER (
                                  PARTITION BY d.decision_date, d.stock_code
                                  ORDER BY d.id DESC
                              ) AS scan_rank
                         FROM decision_journal d
                        WHERE d.decision_date < date('now')
                          AND LOWER(TRIM(COALESCE(d.direction, '')))
                              IN ('buy', 'sell')
                   )
                   SELECT r.*
                     FROM ranked r
                     LEFT JOIN market_learning_observation o
                       ON o.decision_id=r.id AND o.horizon_days=?
                    WHERE r.scan_rank = 1
                      AND o.id IS NULL
                    ORDER BY r.decision_date, r.id
                    LIMIT ?""",
                (horizon_days, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_market_learning_observation(
        self,
        decision: dict,
        observation_date: str,
        horizon_days: int,
        stock_return: float,
        benchmark_return: float,
        excess_return: float,
        was_correct: bool,
        benchmark_basis: str = "",
    ) -> bool:
        """Persist one idempotent next-session/future-session learning sample."""
        evidence = decision.get("evidence") or ""
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except json.JSONDecodeError:
                evidence = {}
        if not isinstance(evidence, dict):
            evidence = {}
        discovery = evidence.get("market_discovery") or {}
        sources = discovery.get("sources") or []
        if not isinstance(sources, list):
            sources = []
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO market_learning_observation
                   (decision_id, observation_date, horizon_days, stock_code,
                    direction, was_correct, stock_return, benchmark_return,
                    excess_return, sources_json, feature_json, benchmark_basis,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision["id"], observation_date, horizon_days,
                    decision.get("stock_code", ""), decision.get("direction", "neutral"),
                    1 if was_correct else 0, round(float(stock_return), 6),
                    round(float(benchmark_return), 6), round(float(excess_return), 6),
                    json.dumps(sources, ensure_ascii=False),
                    json.dumps(discovery, ensure_ascii=False),
                    benchmark_basis, datetime.now().isoformat(),
                ),
            )
            return cursor.rowcount > 0

    def get_market_learning_profile(
        self,
        horizon_days: int = 1,
        as_of_date: str | None = None,
        decay_half_life_days: float | None = None,
    ) -> dict:
        """Aggregate only decisive BUY/SELL observations for scoring feedback.

        Neutral/HOLD records are retained for audit but deliberately excluded
        from adaptive weights.  Otherwise a quiet market can create a misleading
        high "accuracy" without teaching the system which candidates outperform.
        """
        cutoff_date = as_of_date or dt_date.today().isoformat()
        cutoff = dt_date.fromisoformat(cutoff_date)
        half_life = (
            float(decay_half_life_days)
            if decay_half_life_days is not None and float(decay_half_life_days) > 0
            else None
        )
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT stock_code, direction, was_correct, sources_json,
                          stock_return, benchmark_return, excess_return,
                          observation_date
                   FROM market_learning_observation
                   WHERE horizon_days=? AND observation_date < ?
                   ORDER BY id""",
                (horizon_days, cutoff_date),
            ).fetchall()

        by_symbol: dict[str, dict] = {}
        by_source: dict[str, dict] = {}
        decisive = 0
        decisive_correct = 0
        for row in rows:
            direction = str(row["direction"] or "neutral").lower()
            if direction not in {"buy", "sell"}:
                continue
            decisive += 1
            correct = bool(row["was_correct"])
            decisive_correct += int(correct)
            symbol = str(row["stock_code"] or "")
            weight = 1.0
            if half_life is not None:
                try:
                    observation_date = dt_date.fromisoformat(
                        str(row["observation_date"] or "")[:10]
                    )
                    age_days = max(0, (cutoff - observation_date).days)
                    weight = math.pow(0.5, age_days / half_life)
                except (TypeError, ValueError):
                    weight = 0.0
            if weight <= 0:
                continue
            try:
                sources = json.loads(row["sources_json"] or "[]")
            except json.JSONDecodeError:
                sources = []
            for bucket, keys in ((by_symbol, [symbol]), (by_source, sources)):
                for key in keys:
                    if not key:
                        continue
                    stats = bucket.setdefault(
                        str(key),
                        {"observations": 0, "correct": 0, "incorrect": 0,
                         "excess_return_sum": 0.0},
                    )
                    stats["observations"] += weight
                    stats["correct" if correct else "incorrect"] += weight
                    stats["excess_return_sum"] += float(row["excess_return"] or 0) * weight

        for bucket in (by_symbol, by_source):
            for stats in bucket.values():
                observations = stats["observations"]
                stats["win_rate"] = round(stats["correct"] / observations, 4)
                stats["avg_excess_return"] = round(
                    stats.pop("excess_return_sum") / observations, 6
                )
        return {
            "horizon_days": horizon_days,
            "as_of_date_exclusive": cutoff_date,
            "total_observations": len(rows),
            "decisive_observations": decisive,
            "neutral_observations": max(0, len(rows) - decisive),
            "accuracy_available": decisive > 0,
            "decisive_accuracy": round(decisive_correct / decisive, 4) if decisive else 0,
            "decay_half_life_days": half_life,
            "by_symbol": by_symbol,
            "by_source": by_source,
        }

    def get_pending_outcome_decisions(self, min_calendar_days: int = 9) -> list[dict]:
        """查到期但未验证结果的 BUY/SELL 决策。

        中性候选保留在日志中，但不再占用正式方向验证队列。已有中性结果
        仍保留作审计，不会被删除或改写。
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM decision_journal
                   WHERE outcome_known=0
                     AND decision_date <= date('now', ?)
                     AND LOWER(TRIM(COALESCE(direction, ''))) IN ('buy', 'sell')
                   ORDER BY decision_date""",
                (f'-{min_calendar_days} days',),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_decision_outcome(
        self, decision_id: int,
        was_correct: bool, actual_return: float,
    ) -> bool:
        """回填一条决策的真实结果。幂等(WHERE outcome_known=0 守卫,重跑安全)。"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """UPDATE decision_journal
                   SET outcome_known=1, was_correct=?, actual_return=?,
                       outcome_checked_at=?
                   WHERE id=? AND outcome_known=0""",
                (
                    1 if was_correct else 0,
                    round(float(actual_return), 4),
                    datetime.now().isoformat(),
                    decision_id,
                ),
            )
            if cursor.rowcount:
                decision = conn.execute(
                    """SELECT decision_date, stock_code, ai_score, direction, evidence
                       FROM decision_journal WHERE id=?""",
                    (decision_id,),
                ).fetchone()
                direction = str(
                    decision["direction"] if decision is not None else "neutral"
                ).strip().lower()
                is_decisive = direction in {"buy", "sell"}
                outcome_status = (
                    "correct" if was_correct else "wrong"
                ) if is_decisive else "observed"
                conn.execute(
                    """UPDATE strategy_decision
                       SET outcome_status=?, actual_return=?
                       WHERE journal_id=?""",
                    (outcome_status, round(float(actual_return), 4), decision_id),
                )
                if decision:
                    source_evidence = {}
                    try:
                        payload = json.loads(decision["evidence"] or "{}")
                        source_evidence = payload.get("market_discovery") or {}
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    outcome_label = (
                        "正确" if was_correct else "错误"
                    ) if is_decisive else (
                        "中性区间匹配" if was_correct else "中性区间偏离"
                    )
                    conn.execute(
                        """INSERT INTO learning_log
                           (learning_date, category, lesson, evidence_json, created_at)
                           VALUES (?, 'outcome', ?, ?, ?)""",
                        (
                            decision["decision_date"],
                            f"{decision['stock_code']} 的 {decision['direction']} 决策已验证："
                            f"{outcome_label}，实际收益 {float(actual_return):.2%}。",
                            json.dumps({
                                "decision_id": decision_id,
                                "ai_score": decision["ai_score"],
                                "metric_scope": "directional_accuracy" if is_decisive else "neutral_calibration",
                                "market_discovery": source_evidence,
                            }, ensure_ascii=False),
                            datetime.now().isoformat(),
                        ),
                    )
            return cursor.rowcount > 0

    def get_stats(self) -> dict:
        """Database statistics for monitoring."""
        with self._get_conn() as conn:
            stocks = conn.execute(
                "SELECT COUNT(*) as n FROM stock_basic"
            ).fetchone()["n"]
            daily = conn.execute(
                "SELECT COUNT(*) as n FROM market_daily"
            ).fetchone()["n"]
            indicators = conn.execute(
                "SELECT COUNT(*) as n FROM indicator_daily"
            ).fetchone()["n"]
            latest_date = conn.execute(
                "SELECT MAX(trade_date) as d FROM market_daily"
            ).fetchone()["d"]
            last_sync = conn.execute(
                "SELECT completed_at FROM sync_log WHERE status='completed' ORDER BY id DESC LIMIT 1"
            ).fetchone()

        completed_breadth = self.get_latest_market_breadth()
        completed_date = str(completed_breadth.get("data_date") or latest_date or "")
        return {
            "stocks": stocks,
            "daily_bars": daily,
            "indicators": indicators,
            "latest_data_date": completed_date,
            "latest_any_data_date": latest_date,
            "latest_data_coverage": completed_breadth.get("coverage_ratio", 0.0),
            "last_sync": last_sync["completed_at"] if last_sync else None,
            "db_path": str(self.db_path),
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1)
                if self.db_path.exists() else 0,
        }

    def get_latest_market_breadth(self) -> dict[str, Any]:
        """Aggregate the latest completed local trading day without network I/O."""
        with self._get_conn() as conn:
            row = conn.execute(
                """WITH recent_dates AS (
                       SELECT trade_date
                       FROM market_daily
                       GROUP BY trade_date
                       ORDER BY trade_date DESC
                       LIMIT 10
                   ), recent_counts AS (
                       SELECT d.trade_date, COUNT(*) AS row_count
                       FROM market_daily AS d
                       INNER JOIN recent_dates AS r ON r.trade_date = d.trade_date
                       GROUP BY d.trade_date
                   ), completed_day AS (
                       SELECT MAX(trade_date) AS trade_date
                       FROM recent_counts
                       WHERE row_count >= (SELECT MAX(row_count) * 0.8 FROM recent_counts)
                   )
                   SELECT d.trade_date,
                          COUNT(*) AS covered_stocks,
                          (SELECT MAX(row_count) FROM recent_counts) AS expected_stocks,
                          SUM(CASE WHEN d.change_pct > 0 THEN 1 ELSE 0 END) AS up,
                          SUM(CASE WHEN d.change_pct < 0 THEN 1 ELSE 0 END) AS down,
                          SUM(CASE WHEN d.change_pct = 0 THEN 1 ELSE 0 END) AS flat,
                          SUM(CASE WHEN d.change_pct >= 9.9 THEN 1 ELSE 0 END) AS limit_up,
                          SUM(CASE WHEN d.change_pct <= -9.9 THEN 1 ELSE 0 END) AS limit_down,
                          SUM(d.amount) AS total_amount
                   FROM market_daily AS d
                   WHERE d.trade_date = (SELECT trade_date FROM completed_day)
                   GROUP BY d.trade_date"""
            ).fetchone()
        if row is None:
            return {}
        return {
            "data_date": str(row["trade_date"] or ""),
            "covered_stocks": int(row["covered_stocks"] or 0),
            "expected_stocks": int(row["expected_stocks"] or 0),
            "coverage_ratio": round(
                float(row["covered_stocks"] or 0)
                / max(1, int(row["expected_stocks"] or 0)),
                3,
            ),
            "up": int(row["up"] or 0),
            "down": int(row["down"] or 0),
            "flat": int(row["flat"] or 0),
            "limit_up": int(row["limit_up"] or 0),
            "limit_down": int(row["limit_down"] or 0),
            "total_volume": round(float(row["total_amount"] or 0) / 1e12, 2),
        }

    def get_runtime_contract(self) -> dict[str, Any] | None:
        """Return the last explicitly accepted runtime identity."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM runtime_contract WHERE id=1"
            ).fetchone()
        return dict(row) if row is not None else None

    def validate_runtime_contract(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Fail closed when the process and persisted runtime contract differ."""
        expected = {
            "algorithm_version": str(identity.get("algorithm_version") or ""),
            "code_hash": str(identity.get("code_hash") or ""),
            "build_id": str(identity.get("build_id") or ""),
            "schema_version": DB_SCHEMA_VERSION,
        }
        with self._get_conn() as conn:
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if schema_version != DB_SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema mismatch: db={schema_version}, "
                    f"process={DB_SCHEMA_VERSION}"
                )
            row = conn.execute(
                "SELECT * FROM runtime_contract WHERE id=1"
            ).fetchone()
            if row is None:
                has_history = any(
                    int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    > 0
                    for table in (
                        "decision_journal",
                        "strategy_decision",
                        "paper_position",
                        "paper_trade",
                    )
                )
                status = "legacy_unverified" if has_history else "active"
                conn.execute(
                    """INSERT INTO runtime_contract(
                           id, algorithm_version, code_hash, build_id,
                           schema_version, status, validated_at
                       ) VALUES (1, ?, ?, ?, ?, ?, ?)""",
                    (
                        expected["algorithm_version"], expected["code_hash"],
                        expected["build_id"], expected["schema_version"],
                        status, datetime.now().astimezone().isoformat(),
                    ),
                )
                if status != "active":
                    raise RuntimeError(
                        "runtime contract missing for existing data; explicit adoption required"
                    )
                return {**expected, "status": status}

            actual = dict(row)
            mismatches = {
                key: (actual.get(key), value)
                for key, value in expected.items()
                if str(actual.get(key)) != str(value)
            }
            if actual.get("status") != "active" or mismatches:
                raise RuntimeError(
                    "runtime contract mismatch: "
                    f"status={actual.get('status')}, mismatches={mismatches}"
                )
            conn.execute(
                "UPDATE runtime_contract SET validated_at=? WHERE id=1",
                (datetime.now().astimezone().isoformat(),),
            )
        return {**expected, "status": "active"}

    def adopt_runtime_contract(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Explicitly accept a runtime identity during an off-hours deployment."""
        payload = {
            "algorithm_version": str(identity.get("algorithm_version") or ""),
            "code_hash": str(identity.get("code_hash") or ""),
            "build_id": str(identity.get("build_id") or ""),
            "schema_version": DB_SCHEMA_VERSION,
        }
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO runtime_contract(
                       id, algorithm_version, code_hash, build_id,
                       schema_version, status, validated_at
                   ) VALUES (1, ?, ?, ?, ?, 'active', ?)
                   ON CONFLICT(id) DO UPDATE SET
                       algorithm_version=excluded.algorithm_version,
                       code_hash=excluded.code_hash,
                       build_id=excluded.build_id,
                       schema_version=excluded.schema_version,
                       status='active',
                       validated_at=excluded.validated_at""",
                (
                    payload["algorithm_version"], payload["code_hash"],
                    payload["build_id"], payload["schema_version"],
                    datetime.now().astimezone().isoformat(),
                ),
            )
        return {**payload, "status": "active"}

    def get_task_failure_incident(self, task_name: str) -> dict[str, Any] | None:
        """Return the current failure incident for one task."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM task_failure_incident
                   WHERE task_name=? ORDER BY updated_at DESC, rowid DESC LIMIT 1""",
                (task_name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_task_failure_incidents(self) -> list[dict[str, Any]]:
        """Return the latest persisted incident for each task."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT incident.* FROM task_failure_incident AS incident
                    WHERE NOT EXISTS (
                        SELECT 1 FROM task_failure_incident AS newer
                         WHERE newer.task_name=incident.task_name
                           AND (newer.updated_at > incident.updated_at
                                OR (newer.updated_at = incident.updated_at
                                    AND newer.rowid > incident.rowid))
                    )"""
            ).fetchall()
        return [dict(row) for row in rows]

    def save_task_failure_incident(self, incident: dict[str, Any]) -> None:
        """Persist failure state so restarts cannot reset circuit protection."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO task_failure_incident(
                       incident_key, task_name, phase, fingerprint, severity,
                       state, consecutive_failures, first_failed_at,
                       last_failed_at, last_alert_state, next_probe_at,
                       recovered_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(incident_key) DO UPDATE SET
                       task_name=excluded.task_name,
                       phase=excluded.phase,
                       fingerprint=excluded.fingerprint,
                       severity=excluded.severity,
                       state=excluded.state,
                       consecutive_failures=excluded.consecutive_failures,
                       first_failed_at=excluded.first_failed_at,
                       last_failed_at=excluded.last_failed_at,
                       last_alert_state=excluded.last_alert_state,
                       next_probe_at=excluded.next_probe_at,
                       recovered_at=excluded.recovered_at,
                       updated_at=excluded.updated_at
                     WHERE excluded.updated_at >= task_failure_incident.updated_at""",
                (
                    incident.get("incident_key", ""), incident.get("task_name", ""),
                    incident.get("phase", ""), incident.get("fingerprint", ""),
                    incident.get("severity", "P1"), incident.get("state", "failed"),
                    int(incident.get("consecutive_failures", 0) or 0),
                    incident.get("first_failed_at", ""), incident.get("last_failed_at", ""),
                    incident.get("last_alert_state", ""), incident.get("next_probe_at", ""),
                    incident.get("recovered_at", ""), incident.get("updated_at", ""),
                ),
            )

    def save_task_execution(self, execution: dict[str, Any]) -> None:
        """Persist one task execution and retain a bounded audit history."""
        output = execution.get("output", {})
        execution_key = str(
            execution.get("execution_key")
            or (output.get("execution_key") if isinstance(output, dict) else "")
            or ""
        )
        with self._get_conn() as conn:
            # A successful stage is terminal for its date/version key. Do not
            # create a second persisted success when cron and recovery overlap.
            if execution_key:
                existing = conn.execute(
                    """SELECT 1 FROM task_execution
                       WHERE execution_key=? AND status IN ('success', 'succeeded')
                       LIMIT 1""",
                    (execution_key,),
                ).fetchone()
                if existing:
                    return
            conn.execute(
                """INSERT INTO task_execution(
                       task_name, phase, status, trigger_source, started_at,
                       completed_at, duration_seconds, error, output_json,
                       execution_key
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    execution.get("task_name", ""),
                    execution.get("phase", ""),
                    execution.get("status", ""),
                    execution.get("trigger_source", "internal"),
                    execution.get("started_at", ""),
                    execution.get("completed_at", ""),
                    float(execution.get("duration_seconds", 0) or 0),
                    execution.get("error", ""),
                    json.dumps(output, ensure_ascii=False, default=str),
                    execution_key,
                ),
            )
            conn.execute(
                """DELETE FROM task_execution
                   WHERE id NOT IN (
                       SELECT id FROM task_execution ORDER BY id DESC LIMIT 500
                   )"""
            )

    def get_task_executions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Load recent task executions in chronological order."""
        safe_limit = max(1, min(int(limit), 500))
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_execution ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["output"] = json.loads(item.pop("output_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["output"] = {}
                item.pop("output_json", None)
            item.pop("id", None)
            result.append(item)
        return result


# Singleton
market_db = MarketDatabase()
