from src.ai_os.paper_execution_service import PaperExecutionService
from src.ai_os.shadow_runner import build_shadow_report
from src.infrastructure.storage.market_database import MarketDatabase


def _decision(code, direction, score, *, actionable=True, evidence=False):
    return {
        "stock_code": code,
        "direction": direction,
        "action_score": score,
        "actionable": actionable,
        "market_evidence_complete": evidence,
        "market_evidence_sources": ["sina"] if evidence else [],
    }


def test_shadow_report_records_changes_without_execution():
    report = build_shadow_report(
        "2026-08-24",
        [_decision("A", "buy", 70, evidence=True), _decision("B", "sell", 35)],
        [_decision("A", "sell", 55, evidence=True), _decision("C", "buy", 72)],
        baseline_version="2.1",
        candidate_version="2.2",
        run_id="run-1",
    )

    assert report["status"] == "shadow_only"
    assert report["paper_execution_enabled"] is False
    assert report["counts"]["direction_changed"] == 1
    assert report["counts"]["added"] == 1
    assert report["counts"]["removed"] == 1
    assert {item["stock_code"] for item in report["differences"]} == {"A", "B", "C"}


def test_shadow_report_does_not_treat_blocked_direction_as_executable():
    report = build_shadow_report(
        "2026-08-24",
        [_decision("A", "buy", 70, actionable=False)],
        [_decision("A", "buy", 70, actionable=True)],
    )

    assert report["counts"]["direction_changed"] == 1
    assert report["differences"][0]["baseline_direction"] == ""
    assert report["differences"][0]["candidate_direction"] == "buy"


def test_shadow_report_is_deterministic_and_ignores_empty_codes():
    report = build_shadow_report(
        "2026-08-24",
        [{"direction": "buy"}, _decision("B", "neutral", 50)],
        [_decision("B", "neutral", 50)],
    )

    assert report["baseline_count"] == 1
    assert report["candidate_count"] == 1
    assert report["changed_count"] == 0
    assert report["differences"] == []


def test_paper_execution_service_rejects_shadow_decisions(tmp_path):
    database = MarketDatabase(tmp_path / "shadow-execution.db")
    service = PaperExecutionService(database)

    result = service.execute(
        [{
            "stock_code": "000001.SZ",
            "stock_name": "shadow",
            "paper_execution_enabled": False,
        }],
        "2026-09-01",
        execution_timestamp="2026-09-01T09:35:00+08:00",
    )

    assert result["actions"] == []
    assert result["execution_status"] == "shadow_only_not_executable"
    assert result["rejections"][0]["reason"] == (
        "shadow_only_decision_not_executable"
    )
