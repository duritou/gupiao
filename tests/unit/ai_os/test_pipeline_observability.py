from src.ai_os.pipeline_observability import classify_run_outcome


def _decision(*, sources=None, flow_status="positive"):
    return {
        "market_sources": sources or ["tencent_live_quote"],
        "flow_status": flow_status,
    }


def test_run_classification_distinguishes_data_failure_from_no_opportunity():
    insufficient = classify_run_outcome(
        [_decision(sources=[], flow_status="missing")],
        {"degraded": False, "errors": []},
        actionable_count=0,
        execution_deferred=False,
    )
    no_opportunity = classify_run_outcome(
        [_decision(flow_status="positive")],
        {"degraded": False, "errors": []},
        actionable_count=0,
        execution_deferred=False,
    )

    assert insufficient["status"] == "data_insufficient_abstention"
    assert insufficient["flow_coverage"] == 0.0
    assert no_opportunity["status"] == "no_actionable_market_opportunity"
    assert no_opportunity["flow_coverage"] == 1.0


def test_deferred_execution_is_not_reported_as_no_opportunity():
    result = classify_run_outcome(
        [_decision()],
        {},
        actionable_count=1,
        execution_deferred=True,
    )

    assert result["status"] == "discovery_only"
    assert result["execution_deferred"] is True
