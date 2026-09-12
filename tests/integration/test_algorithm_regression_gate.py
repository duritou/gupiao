"""Offline system invariants for the candidate-to-promotion path."""

import json
from pathlib import Path

from src.ai_os.candidate_allocator import allocate_deep_candidates
from src.ai_os.score_guard import apply_score_guard
from src.ai_os.shadow_runner import build_shadow_report
from src.replay.historical_gate import evaluate_historical_gate

FIXTURE = Path(__file__).parents[1] / "fixtures" / "algorithm_replay" / "contract_samples.json"


def _market_evidence(code: str, score: float) -> dict:
    return {
        "stock_code": code,
        "ranking_score": score,
        "technical_score": score - 2,
        "discovery_score": score - 4,
        "market_sources": ["tencent", "sina"],
        "market_price": 10.0,
        "fundamentals": {"net_profit": 1.0},
        "direction": "buy",
    }


def test_candidate_evidence_and_shadow_gates_are_fail_closed():
    missing = {
        "stock_code": "000001.SZ",
        "ranking_score": 99,
        "technical_score": 97,
        "discovery_score": 95,
        "direction": "buy",
        "market_sources": [],
        "market_price": 0,
    }
    eligible = _market_evidence("000002.SZ", 80)

    selected, stats = allocate_deep_candidates([missing, eligible], target=5)

    assert [item["stock_code"] for item in selected] == ["000002.SZ"]
    assert stats == {"eligible_count": 1, "ineligible_count": 1, "selected_count": 1}
    apply_score_guard(missing, {})
    assert missing["decision_status"] == "data_blocked"
    assert missing["action_score"] == 60.0

    shadow = build_shadow_report(
        "2026-09-01",
        baseline_decisions=[_market_evidence("000002.SZ", 80)],
        candidate_decisions=selected,
        baseline_version="2.1",
        candidate_version="2.2.0-evidence-routing",
    )

    assert shadow["status"] == "shadow_only"
    assert shadow["paper_execution_enabled"] is False


def test_frozen_contract_fixture_cannot_clear_twenty_day_gate():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["metadata"]["performance_evidence"] is False

    result = evaluate_historical_gate(payload["snapshots"])

    assert result.status == "insufficient_history"
    assert result.available_days == 5
    assert result.required_days == 20
    assert result.eligible_for_promotion is False
