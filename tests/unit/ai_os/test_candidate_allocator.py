from src.ai_os.candidate_allocator import (
    allocate_deep_candidates,
    has_market_evidence,
)


def _decision(code: str, score: float, *, evidence: bool) -> dict:
    return {
        "stock_code": code,
        "ranking_score": score,
        "technical_score": score - 2,
        "discovery_score": score - 4,
        "market_sources": ["tencent"] if evidence else [],
        "market_price": 10.0 if evidence else 0.0,
    }


def test_market_evidence_requires_source_and_positive_quote():
    assert has_market_evidence(_decision("000001.SZ", 80, evidence=True)) is True
    assert has_market_evidence(_decision("000002.SZ", 90, evidence=False)) is False
    assert has_market_evidence({
        **_decision("000003.SZ", 90, evidence=True),
        "market_sources": ["portfolio_review"],
    }) is False


def test_deep_slots_prioritize_evidence_eligible_candidates():
    no_evidence = _decision("000001.SZ", 99, evidence=False)
    evidence_a = _decision("000002.SZ", 80, evidence=True)
    evidence_b = _decision("000003.SZ", 70, evidence=True)

    selected, stats = allocate_deep_candidates(
        [no_evidence, evidence_a, evidence_b], target=2
    )

    assert [item["stock_code"] for item in selected] == [
        "000002.SZ", "000003.SZ"
    ]
    assert stats == {"eligible_count": 2, "ineligible_count": 1, "selected_count": 2}
    assert no_evidence["deep_candidate_exclusion_reason"] == (
        "market_sources_missing;market_quote_missing"
    )


def test_deep_allocator_allows_fewer_slots_when_evidence_is_insufficient():
    candidate = _decision("000001.SZ", 90, evidence=False)

    selected, stats = allocate_deep_candidates([candidate], target=5)

    assert selected == []
    assert stats["selected_count"] == 0
    assert stats["ineligible_count"] == 1


def test_deep_allocator_does_not_spend_ai_slots_on_unknown_universe_metadata():
    candidate = {
        **_decision("000001.SZ", 90, evidence=True),
        "universe_metadata_complete": False,
    }

    selected, stats = allocate_deep_candidates([candidate], target=5)

    assert selected == []
    assert stats == {"eligible_count": 0, "ineligible_count": 1, "selected_count": 0}
    assert candidate["deep_candidate_exclusion_reason"] == (
        "universe_metadata_incomplete"
    )
