"""Stable identity for the evidence packet submitted to deep research."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_VOLATILE_KEYS = frozenset({
    "created_at",
    "fetched_at",
    "quote_fetched_at",
    "signal_at",
    "data_cutoff_at",
    "run_id",
    "config_hash",
    "code_hash",
    "duration_seconds",
    "source_lag_seconds",
})


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def deep_input_fingerprint(
    candidate: dict[str, Any],
    trade_date: str,
    *,
    strategy_version: str = "",
    model: str = "",
    prompt_version: str = "deep-research-v2",
) -> str:
    """Hash stable decision evidence while excluding fetch/run timestamps.

    The hash is deliberately based on the candidate packet available before
    the analyzer performs its final local evidence read.  The analyzer also
    stores its full request hash; this smaller identity is used to decide
    whether a same-day result is safe to reuse after a new scan.
    """
    fields = {
        "trade_date": trade_date,
        "strategy_version": strategy_version,
        "model": model,
        "prompt_version": prompt_version,
        "candidate": {
            key: candidate.get(key)
            for key in (
                "stock_code", "stock_name", "technical_score", "discovery_score",
                "raw_ai_score", "ranking_score", "ai_score", "market_sources",
                "market_reasons", "market_flow", "flow_status", "flow_sources",
                "fundamentals", "stock_skill_evidence", "evidence_enrichment",
                "market_price", "market_pre_close", "market_change_pct",
                "market_price_source", "market_price_date", "technical_data_through",
                "deep_kline_evidence", "universe_industry",
            )
        },
    }
    payload = json.dumps(
        _stable_value(fields),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
