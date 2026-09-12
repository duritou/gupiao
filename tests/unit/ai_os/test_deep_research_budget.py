from src.ai_os.deep_research_identity import deep_input_fingerprint
from src.ai_os.pipeline_runner import _deep_analysis_plan, _serialize_recommendation


def _candidate(code: str, price: float = 10.0) -> dict:
    return {
        "stock_code": code,
        "technical_score": 72,
        "discovery_score": 70,
        "market_sources": ["tushare"],
        "market_flow": {"status": "positive", "main_net": 10},
        "market_price": price,
        "market_price_date": "2026-09-07",
    }


def test_session_continuation_uses_remaining_daily_budget():
    candidates = [_candidate(f"00000{index}.SZ") for index in range(1, 11)]
    reusable, missing, skipped = _deep_analysis_plan(
        candidates,
        {},
        deep_target=10,
        daily_deep_successes=5,
        daily_deep_attempts=5,
        force_reanalysis=False,
        max_new_candidates=10,
        daily_call_limit=15,
    )

    assert reusable == {}
    assert len(missing) == 10
    assert skipped == 0

    _, afternoon_missing, afternoon_skipped = _deep_analysis_plan(
        candidates,
        {},
        deep_target=5,
        daily_deep_successes=10,
        daily_deep_attempts=10,
        force_reanalysis=False,
        max_new_candidates=5,
        daily_call_limit=15,
    )
    assert len(afternoon_missing) == 5
    assert afternoon_skipped == 5


def test_daily_budget_blocks_after_fifteen_attempts():
    candidates = [_candidate(f"00000{index}.SZ") for index in range(1, 6)]
    _, missing, skipped = _deep_analysis_plan(
        candidates,
        {},
        deep_target=5,
        daily_deep_successes=10,
        daily_deep_attempts=15,
        force_reanalysis=False,
        max_new_candidates=5,
        daily_call_limit=15,
    )
    assert missing == []
    assert skipped == 5


def test_deep_input_fingerprint_is_stable_but_changes_with_evidence():
    candidate = _candidate("000001.SZ")
    first = deep_input_fingerprint(
        {**candidate, "fetched_at": "2026-09-07T01:00:00"},
        "2026-09-07",
        strategy_version="2.2.0-evidence-routing",
        model="gpt-5.6-terra",
    )
    same_evidence = deep_input_fingerprint(
        {**candidate, "fetched_at": "2026-09-07T13:00:00"},
        "2026-09-07",
        strategy_version="2.2.0-evidence-routing",
        model="gpt-5.6-terra",
    )
    changed_quote = deep_input_fingerprint(
        {**candidate, "market_price": 10.2},
        "2026-09-07",
        strategy_version="2.2.0-evidence-routing",
        model="gpt-5.6-terra",
    )
    assert first == same_evidence
    assert first != changed_quote


def test_serialized_recommendation_exposes_deep_audit_fields():
    serialized = _serialize_recommendation({
        **_candidate("000001.SZ"),
        "stock_name": "fixture",
        "direction": "neutral",
        "recommendation": "Hold",
        "deep_provider": "codex_cli",
        "deep_source": "Codex-Terra Multi-Agent",
        "deep_input_fingerprint": "fp-1",
        "deep_evidence_consumption": {"quote": {"data_date": "2026-09-07"}},
    })
    assert serialized["deep_provider"] == "codex_cli"
    assert serialized["deep_source"] == "Codex-Terra Multi-Agent"
    assert serialized["deep_input_fingerprint"] == "fp-1"
    assert serialized["deep_evidence_consumption"]["quote"]["data_date"] == "2026-09-07"
