from src.infrastructure.storage.market_database import DB_SCHEMA_VERSION, MarketDatabase


def test_pipeline_run_audit_survives_sqlite_reopen_and_missing_is_unverified(tmp_path):
    path = tmp_path / "pipeline-audit.db"
    database = MarketDatabase(path)
    database.save_pipeline_run_audit({
        "run_id": "run-1",
        "decision_date": "2026-09-09",
        "target_trade_date": "2026-09-08",
        "requirement_version": "2026-09-09.v1",
        "strategy_version": "test",
        "code_hash": "code",
        "config_hash": "config",
        "acceptance_status": "partial",
        "evidence_status": "partial",
        "stages": {"deep_research": {"target_count": 10, "failed_count": 2}},
    })

    reopened = MarketDatabase(path)
    stored = reopened.get_pipeline_run_audit("run-1")
    assert stored["run_id"] == "run-1"
    assert stored["stages"]["deep_research"]["failed_count"] == 2
    assert stored["requirement_version"] == "2026-09-09.v1"
    assert reopened.get_pipeline_run_audit("legacy-run")["acceptance_status"] == "unverified"
    with reopened._get_conn() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == DB_SCHEMA_VERSION


def test_incident_persistence_rejects_stale_event_and_accepts_later_recovery(tmp_path):
    database = MarketDatabase(tmp_path / "incident-order.db")
    base = {
        "incident_key": "incident-1",
        "task_name": "ai_reflection",
        "phase": "evening",
        "fingerprint": "fp",
        "severity": "P1",
        "consecutive_failures": 3,
        "first_failed_at": "2026-09-08T22:00:00",
        "last_failed_at": "2026-09-08T22:10:00",
        "last_alert_state": "circuit_open",
        "next_probe_at": "",
        "recovered_at": "",
    }
    database.save_task_failure_incident({
        **base, "state": "circuit_open", "updated_at": "2026-09-08T22:10:00"
    })
    database.save_task_failure_incident({
        **base, "state": "healthy", "consecutive_failures": 0,
        "last_alert_state": "recovered", "recovered_at": "2026-09-08T22:05:00",
        "updated_at": "2026-09-08T22:05:00",
    })
    assert database.get_task_failure_incident("ai_reflection")["state"] == "circuit_open"

    database.save_task_failure_incident({
        **base, "state": "healthy", "consecutive_failures": 0,
        "last_alert_state": "recovered", "recovered_at": "2026-09-08T22:15:00",
        "updated_at": "2026-09-08T22:15:00",
    })
    assert database.get_task_failure_incidents()[0]["state"] == "healthy"
