from src.ai_os.pipeline_observability import build_stage_acceptance
from src.infrastructure.storage.market_database import MarketDatabase


def test_kline_evidence_survives_restart_and_same_day_cache(tmp_path):
    path = tmp_path / "kline-evidence.db"
    database = MarketDatabase(path)
    evidence = {
        "received_count": 80,
        "visible_count": 60,
        "last_date": "2026-09-03",
        "visible_last_date": "2026-09-03",
        "provenance": {"provider": "tickflow"},
    }
    decision = {
        "date": "2026-09-04", "stock_code": "600506.SH",
        "stock_name": "test", "deep_rating": "Hold",
        "deep_kline_evidence": evidence,
    }
    journal_id = database.save_decision(decision)
    database.save_strategy_decision(decision, journal_id)
    reopened = MarketDatabase(path)
    assert reopened.get_recent_decisions()[0]["deep_kline_evidence"] == evidence
    assert reopened.get_decisions_for_date("2026-09-04")[0]["deep_kline_evidence"] == evidence
    cached = reopened.get_cached_deep_analyses("2026-09-04", ["600506.SH"])
    assert cached["600506.SH"]["kline_evidence"] == evidence


def test_complete_deep_evidence_survives_same_day_cache(tmp_path):
    path = tmp_path / "complete-deep-evidence.db"
    database = MarketDatabase(path)
    consumption = {
        "financials": {"status": "available", "history_complete": True},
        "fund_flow": {
            "status": "available",
            "requested_days": 1,
            "row_count": 1,
            "rows": [{"data_date": "2026-09-10"}],
        },
        "components": {"announcements": {"status": "empty"}},
        "analysis_input_sha256": "input-sha256",
    }
    decision = {
        "date": "2026-09-11",
        "stock_code": "000978.SZ",
        "deep_rating": "Hold",
        "deep_input_fingerprint": "fingerprint",
        "deep_kline_evidence": {
            "available": True,
            "visible_last_date": "2026-09-10",
        },
        "deep_evidence_consumption": consumption,
        "deep_evidence_gaps": [],
    }
    journal_id = database.save_decision(decision)
    database.save_strategy_decision(decision, journal_id)

    cached = MarketDatabase(path).get_cached_deep_analyses(
        "2026-09-11",
        ["000978.SZ"],
        input_fingerprints={"000978.SZ": "fingerprint"},
    )

    assert cached["000978.SZ"]["deep_evidence_consumption"] == consumption
    assert cached["000978.SZ"]["evidence_gaps"] == []

    reused = cached["000978.SZ"]
    audit = build_stage_acceptance(
        [{
            "stock_code": "000978.SZ",
            "deep_candidate_eligible": True,
            "deep_analysis_available": True,
            "deep_input_fingerprint": reused["deep_input_fingerprint"],
            "deep_kline_evidence": reused["kline_evidence"],
            "deep_evidence_consumption": reused["deep_evidence_consumption"],
        }],
        {
            "target_trade_date": "2026-09-10",
            "technical_universe_size": 1,
            "signals_computed": 1,
            "deep_analysis_target": 1,
            "deep_analysis_cached_count": 1,
            "deep_analysis_count": 1,
        },
    )
    details = audit["stages"]["deep_research"]["stock_details"][0]
    assert details["evidence_gaps"] == []
