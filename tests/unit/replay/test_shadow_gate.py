from src.ai_os.shadow_runner import load_persisted_shadow_reports, persist_shadow_report
from src.infrastructure.storage.market_database import MarketDatabase
from src.replay.shadow_gate import evaluate_shadow_gate


def _report(day: int, *, changed: int = 0) -> dict:
    return {
        "status": "shadow_only",
        "trade_date": f"2026-08-{day:02d}",
        "baseline_version": "2.1",
        "candidate_version": "2.2",
        "changed_count": changed,
        "counts": {"direction_changed": 0, "evidence_changed": 0},
        "paper_execution_enabled": False,
        "data_source": "same_scan_decision_sets_only",
    }


def test_shadow_gate_requires_five_distinct_days():
    result = evaluate_shadow_gate([_report(day) for day in range(18, 22)])

    assert result.status == "insufficient_shadow_history"
    assert result.available_days == 4
    assert result.shadow_gate_passed is False


def test_shadow_gate_passes_clean_non_executable_reports():
    result = evaluate_shadow_gate([_report(day) for day in range(18, 23)])

    assert result.status == "passed"
    assert result.available_days == 5
    assert result.shadow_gate_passed is True
    assert result.eligible_for_promotion is False


def test_shadow_gate_blocks_unreviewed_differences_or_execution():
    changed = _report(18, changed=1)
    unsafe = _report(19)
    unsafe["paper_execution_enabled"] = True
    result = evaluate_shadow_gate([changed, unsafe])

    assert result.status == "blocked"
    assert "unreviewed_shadow_differences" in result.reasons
    assert "shadow_execution_not_disabled" in result.reasons


def test_shadow_gate_blocks_missing_trade_date_even_with_five_valid_days():
    reports = [_report(day) for day in range(18, 23)]
    reports.append(_report(23))
    reports[-1]["trade_date"] = ""

    result = evaluate_shadow_gate(reports)

    assert result.shadow_gate_passed is False
    assert "shadow_trade_date_missing" in result.reasons


def test_shadow_report_persistence_uses_replay_history_without_mixing_modes(tmp_path):
    database = MarketDatabase(tmp_path / "shadow.db")
    report = _report(18)

    run_id = persist_shadow_report(report, database)
    loaded = load_persisted_shadow_reports(database)

    assert run_id > 0
    assert len(loaded) == 1
    assert loaded[0]["trade_date"] == "2026-08-18"
    assert loaded[0]["replay_run_id"] == run_id
