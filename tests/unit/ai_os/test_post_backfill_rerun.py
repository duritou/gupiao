from __future__ import annotations

from src.ai_os.post_backfill_rerun import (
    build_data_revision,
    evaluate_post_backfill_gate,
    make_rerun_execution_key,
    parse_backfill_partition,
    verify_rerun_result,
)


def _summary(coverage: float = 0.95, *, status: str = "partial") -> dict:
    return {
        "target_date": "2026-09-08",
        "source_run_id": "run-old",
        "candidate_count": 300,
        "worker_status": status,
        "checkpoint_updated_at": "2026-09-08T20:42:36",
        "data_revision": "revision-a",
        "component_coverage": {
            name: {"coverage": coverage}
            for name in (
                "daily", "adjustment_factor", "financial_history",
                "fund_flow_history",
            )
        },
        "missing_reason_by_symbol": {},
    }


def test_partition_parser_preserves_existing_checkpoint_contract():
    parsed = parse_backfill_partition(
        "20260906-v3:candidate:run-old:300:2026-09-08:250:8:20"
    )

    assert parsed == {
        "scope": "candidate",
        "source_run_id": "run-old",
        "limit": 300,
        "target_date": "2026-09-08",
        "required_bars": 250,
        "periods": 8,
        "flow_days": 20,
    }


def test_partial_batch_at_threshold_is_eligible_without_rule_change():
    result = evaluate_post_backfill_gate(_summary(), previous_ai_run_created_at="2026-09-08T13:33:49")

    assert result["eligible"] is True
    assert result["reason_codes"] == []


def test_below_threshold_is_not_eligible_and_exposes_component_reason():
    summary = _summary(0.9499)

    result = evaluate_post_backfill_gate(summary)

    assert result["eligible"] is False
    assert set(result["reason_codes"]) == {
        "daily_coverage_below_threshold",
        "adjustment_factor_coverage_below_threshold",
        "financial_history_coverage_below_threshold",
        "fund_flow_history_coverage_below_threshold",
    }


def test_systemic_failure_blocks_rerun_even_when_coverage_is_high():
    summary = _summary()
    summary["missing_reason_by_symbol"] = {
        "300792.SZ": {
            "persisted": {"fund_flow_history": {"status": "permission_denied"}}
        }
    }

    result = evaluate_post_backfill_gate(summary)

    assert result["eligible"] is False
    assert result["reason_codes"] == ["systemic_data_source_failure"]


def test_data_revision_is_stable_for_same_persisted_facts():
    summary = _summary()
    coverage = {"expected_flow_dates": ["2026-09-08"], "details": {"A": {"daily": 1}}}

    first = build_data_revision(summary, coverage)
    second = build_data_revision(dict(summary), dict(coverage))

    assert first == second
    assert make_rerun_execution_key({**summary, "data_revision": first}).endswith(first)


def test_verification_rejects_paper_trades_and_accepts_research_only_run():
    payload = {
        "status": "success",
        "execute_paper_trades": False,
        "result": {"run_id": "run-new", "paper_trades": []},
    }
    persisted = {
        "run_id": "run-new",
        "decision_count": 300,
        "run_created_at": "2026-09-08T21:00:00",
    }

    result = verify_rerun_result(
        payload,
        persisted,
        source_run_id="run-old",
        checkpoint_updated_at="2026-09-08T20:42:36",
    )

    assert result["verified"] is True

    payload["result"]["paper_trades"] = [{"action": "BUY"}]
    result = verify_rerun_result(
        payload,
        persisted,
        source_run_id="run-old",
        checkpoint_updated_at="2026-09-08T20:42:36",
    )
    assert result["verified"] is False
    assert "paper_trades_created" in result["reason_codes"]
