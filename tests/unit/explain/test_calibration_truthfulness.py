from types import SimpleNamespace

from src.explain.calibration import CalibrationEngine


def test_annual_report_does_not_invent_model_or_blind_test_metrics():
    case = SimpleNamespace(
        created_at="2026-08-01T01:00:00+08:00",
        outcome_known=True,
        was_correct=True,
        stock_code="000001.SZ",
        stock_name="测试公司",
        evidence_grade="EvidenceGrade.C",
        confidence=0.8,
    )

    report = CalibrationEngine().generate_annual_report([case], year=2026)

    assert report.model_versions == []
    assert report.replay_stability == 0.0
    assert report.replayable_cases == 0
    assert report.blind_test_cases == 0
    assert report.blind_test_accuracy == 0.0
    assert report.replay_stability_available is False
    assert report.blind_test_available is False


def test_empty_calibration_is_explicitly_unavailable():
    report = CalibrationEngine().compute_calibration([])

    assert report.available is False
    assert report.to_dict()["available"] is False


def test_verified_calibration_is_available():
    case = SimpleNamespace(
        outcome_known=True,
        was_correct=True,
        confidence=0.8,
    )

    report = CalibrationEngine().compute_calibration([case])

    assert report.available is True
    assert report.total_verified_cases == 1
