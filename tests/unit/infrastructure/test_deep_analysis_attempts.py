from src.infrastructure.storage.market_database import MarketDatabase


def _candidate(code: str) -> dict:
    return {"stock_code": code}


def test_deep_budget_reservation_is_persistent_and_bounded(tmp_path):
    path = tmp_path / "budget.db"
    database = MarketDatabase(path)
    candidates = [_candidate(f"00000{index}.SZ") for index in range(1, 6)]
    fingerprints = {
        item["stock_code"]: f"fp-{item['stock_code']}" for item in candidates
    }

    first = database.reserve_deep_analysis_slots(
        "2026-09-07", "morning", candidates, fingerprints,
        window_limit=3, daily_limit=4,
    )
    assert len(first["selected"]) == 3
    assert first["skipped"] == 2

    database.finalize_deep_analysis_slots(
        "2026-09-07", "morning",
        [
            {"stock_code": item["stock_code"], "available": True, "duration_seconds": 1.2}
            for item in first["selected"]
        ],
        fingerprints,
    )
    reopened = MarketDatabase(path)
    second = reopened.reserve_deep_analysis_slots(
        "2026-09-07", "midday", candidates, fingerprints,
        window_limit=5, daily_limit=4,
    )
    assert len(second["selected"]) == 1
    assert second["used_before"] == 3
    assert second["used_after"] == 4


def test_deep_budget_same_input_is_idempotent(tmp_path):
    database = MarketDatabase(tmp_path / "idempotent.db")
    candidate = _candidate("000001.SZ")
    fingerprints = {"000001.SZ": "same-fingerprint"}

    first = database.reserve_deep_analysis_slots(
        "2026-09-07", "morning", [candidate], fingerprints,
        window_limit=5, daily_limit=5,
    )
    second = database.reserve_deep_analysis_slots(
        "2026-09-07", "morning", [candidate], fingerprints,
        window_limit=5, daily_limit=5,
    )
    assert len(first["selected"]) == 1
    assert second["selected"] == []
    assert second["skipped"] == 1


def test_deep_failure_detail_survives_reopen(tmp_path):
    path = tmp_path / "failure.db"
    database = MarketDatabase(path)
    candidate = _candidate("000002.SZ")
    fingerprints = {"000002.SZ": "failed-input"}
    reserved = database.reserve_deep_analysis_slots(
        "2026-09-07", "morning", [candidate], fingerprints,
        window_limit=5, daily_limit=5,
    )
    assert len(reserved["selected"]) == 1

    updated = database.finalize_deep_analysis_slots(
        "2026-09-07", "morning",
        [{
            "stock_code": "000002.SZ",
            "available": False,
            "error_type": "ResearchDeadlineExceeded",
            "error": "bounded research deadline exceeded",
            "duration_seconds": 8.0,
        }],
        fingerprints,
    )
    assert updated == 1

    reopened = MarketDatabase(path)
    with reopened._get_conn() as conn:
        row = conn.execute(
            """SELECT status, error_type, error_detail, duration_seconds
               FROM deep_analysis_attempt
               WHERE budget_date=? AND research_window=? AND stock_code=?""",
            ("2026-09-07", "morning", "000002.SZ"),
        ).fetchone()
    assert dict(row) == {
        "status": "timeout",
        "error_type": "ResearchDeadlineExceeded",
        "error_detail": "bounded research deadline exceeded",
        "duration_seconds": 8.0,
    }
