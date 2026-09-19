"""Auditable strategy identity for every pipeline run."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Bump by hand.  This is not derived from anything, and two literals must be
# changed with it or the audit chain silently disagrees with itself:
# runtime_identity.create_manifest (:108) and the startup_identity fallback
# (:200) each hardcode their own copy rather than importing this constant.
ALGORITHM_VERSION = "2.3.0-evidence-integrity"
_RUNTIME_SOURCE_FILES = (
    "src/infrastructure/market_data/research_flow.py",
    "src/infrastructure/market_data/source_manager.py",
    "src/infrastructure/market_data/vibe_embedded.py",
    "src/infrastructure/market_data/tushare_provider.py",
    "src/infrastructure/market_data/index_sync.py",
    "src/infrastructure/market_data/flow_batch_backfill.py",
    "src/infrastructure/market_data/remote_market_discovery.py",
    "src/agents/codex_stock_analyzer.py",
    "src/ai_os/pipeline_runner.py",
    "src/ai_os/execution_policy.py",
    "src/ai_os/pipeline_observability.py",
    "src/ai_os/market_learning.py",
    "src/ai_os/numeric_policy.py",
    "src/ai_os/price_limit_policy.py",
    "src/ai_os/deep_research_identity.py",
    "src/ai_os/trading_costs.py",
    "src/ai_os/trading_policy.py",
    "src/ai_os/universe_policy.py",
    "src/ai_os/score_guard.py",
    "src/ai_os/paper_ledger_rebuild.py",
    "src/backtest/engine.py",
    "src/explain/benchmark.py",
    "src/explain/strategy_evaluation.py",
    "src/explain/calibration.py",
    "src/explain/evidence_quality.py",
    "src/ai_os/task_executor.py",
    "src/ai_os/scheduler.py",
    "src/api/app.py",
    "src/infrastructure/storage/market_database.py",
)
_CONFIG_KEYS = (
    "SCANNER_MIN_MARKET_CAP",
    "SCANNER_MIN_DAILY_VOLUME",
    "SCANNER_EXCLUDE_ST",
    "SCANNER_EXCLUDE_NEW_IPO_DAYS",
    "SCANNER_TECHNICAL_SHORTLIST_COUNT",
    "SCANNER_AI_PRESELECT_COUNT",
    "SCANNER_AI_DEEP_ANALYSIS_N",
    "SCANNER_AI_DEEP_ANALYSIS_MORNING_MAX",
    "SCANNER_AI_DEEP_ANALYSIS_MIDDAY_MAX",
    "SCANNER_AI_DEEP_ANALYSIS_DAILY_MAX",
    "SCANNER_AI_DEEP_ANALYSIS_DEADLINE_SECONDS",
    "SCANNER_EVIDENCE_ENRICHMENT_COUNT",
    "SCANNER_EVIDENCE_ENRICHMENT_CONCURRENCY",
    "SCANNER_EVIDENCE_ENRICHMENT_TIMEOUT_SECONDS",
    "DATA_COMPLETION_FLOW_BATCH_ENABLED",
    "DATA_COMPLETION_FLOW_BATCH_CODE_CHUNK",
    "DATA_COMPLETION_FLOW_BATCH_MAX_REQUESTS",
    "DATA_COMPLETION_FLOW_BATCH_DEADLINE_SECONDS",
    "CROSS_SECTIONAL_RANK_WEIGHT",
    "SELECTION_TECHNICAL_WEIGHT",
    "SELECTION_DISCOVERY_WEIGHT",
    "SELECTION_LEARNING_WEIGHT",
    "MAX_POSITION_PCT",
    "MAX_INDUSTRY_PCT",
    "PAPER_EXPLORATION_ENABLED",
    "PAPER_CONDITIONAL_BUY_ENABLED",
    "LIVE_EXPLORATION_ENABLED",
    "PAPER_EXPLORATION_POSITION_PCT",
    "PAPER_EXPLORATION_MAX_POSITION_PCT",
    "PAPER_EXPLORATION_MAX_TOTAL_PCT",
    "PAPER_EXPLORATION_MAX_ENTRIES",
    "PAPER_EXPLORATION_CONFIRMATION_DAYS",
    "PAPER_EXPLORATION_MAX_HOLDING_DAYS",
    "PAPER_EXPLORATION_STOP_LOSS_PCT",
    "PAPER_LIVENESS_ALERT_DAYS",
    "PAPER_LIVENESS_MIN_CASH_PCT",
)
_SOURCE_FILES = (
    "src/ai_os/candidate_allocator.py",
    "src/ai_os/execution_policy.py",
    "src/ai_os/cross_sectional_scoring.py",
    "src/ai_os/trading_costs.py",
    "src/ai_os/market_learning.py",
    "src/ai_os/numeric_policy.py",
    "src/ai_os/price_limit_policy.py",
    "src/ai_os/deep_research_identity.py",
    "src/ai_os/pipeline_observability.py",
    "src/ai_os/evidence_policy.py",
    "src/ai_os/pipeline_runner.py",
    "src/ai_os/paper_execution_service.py",
    "src/ai_os/recommendation_quality.py",
    "src/ai_os/score_guard.py",
    "src/ai_os/shadow_runner.py",
    "src/ai_os/trading_policy.py",
    "src/ai_os/universe_policy.py",
    "src/agents/codex_stock_analyzer.py",
    "src/explain/benchmark.py",
    "src/explain/strategy_evaluation.py",
    "src/domain/models/selection_decision.py",
    "src/infrastructure/market_data/current_metadata_sync.py",
    "src/infrastructure/market_data/index_sync.py",
    "src/infrastructure/market_data/flow_batch_backfill.py",
    "src/infrastructure/market_data/remote_market_discovery.py",
    "src/infrastructure/market_data/vibe_embedded.py",
    "src/replay/algorithm_comparator.py",
    "src/replay/historical_gate.py",
    "src/replay/shadow_gate.py",
)


def _config_snapshot(settings: Any) -> dict[str, Any]:
    return {key: getattr(settings, key, None) for key in _CONFIG_KEYS}


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_hash() -> str:
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for relative_path in _SOURCE_FILES:
        path = root / relative_path
        digest.update(relative_path.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def runtime_code_hash() -> str:
    """Hash the code that controls startup, scheduling, and paper execution."""
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for relative_path in _RUNTIME_SOURCE_FILES:
        path = root / relative_path
        digest.update(relative_path.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def create_runtime_identity() -> dict[str, str]:
    """Return the immutable process identity used by startup compatibility checks."""
    code_hash = runtime_code_hash()
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "code_hash": code_hash,
        "build_id": os.environ.get("ADAPTIVE_BUILD_ID") or f"code-{code_hash[:16]}",
    }


def create_strategy_run_metadata(settings: Any) -> dict[str, Any]:
    """Create one immutable identity shared by all decisions in a run."""
    config = _config_snapshot(settings)
    return {
        "run_id": uuid.uuid4().hex,
        "strategy_name": "adaptive-paper",
        "strategy_version": ALGORITHM_VERSION,
        "config_snapshot": config,
        "config_hash": _hash_payload(config),
        "code_hash": _source_hash(),
        "run_created_at": datetime.now().astimezone().isoformat(),
    }
