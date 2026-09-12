from src.ai_os.evidence_policy import assess_evidence


def test_evidence_policy_accepts_sourced_quote_and_excludes_internal_labels():
    assessment = assess_evidence({
        "sources": ["portfolio_review", "Tencent"],
        "quote": {"price": 12.3},
    })

    assert assessment.market_complete is True
    assert assessment.market_sources == ("tencent",)
    assert assessment.reasons == ()


def test_evidence_policy_reports_each_market_gap():
    assessment = assess_evidence({"sources": []})

    assert assessment.market_complete is False
    assert assessment.deep_eligible is False
    assert assessment.reasons == (
        "market_sources_missing",
        "market_quote_missing",
    )


def test_deep_result_can_supply_fundamental_state_but_not_market_quote():
    assessment = assess_evidence(
        {"sources": [], "quote": {}},
        deep_result={"available": True, "evidence_gaps": []},
    )

    assert assessment.fundamental_available is True
    assert assessment.market_complete is False
