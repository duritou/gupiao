import json
from pathlib import Path

from src.ai_os.scheduler import (
    EOD_PROCESSING,
    MARKET_HOURS_MONITOR,
    MORNING_ROUTINE,
    SchedulePhase,
    get_schedule_for_phase,
)
from src.replay.trading_cycle_replay import replay_trading_cycle


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "trading_days"
    / "2026-09-01"
    / "manifest.json"
)


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_frozen_fixture_runs_the_complete_closed_loop():
    result = replay_trading_cycle(_load_fixture())

    assert result.status == "passed"
    assert result.stage_names == (
        "pre_market",
        "market_open",
        "midday",
        "afternoon",
        "market_close",
        "outcome_backfill",
        "evening",
    )
    assert result.metrics == {
        "candidate_count": 2,
        "raw_score_qualified_count": 2,
        "evidence_attempt_count": 2,
        "evidence_success_count": 1,
        "action_score_qualified_count": 1,
        "deep_analysis_count": 1,
        "final_review_approved_count": 1,
        "buy_count": 1,
        "sell_count": 1,
        "learning_update_count": 2,
        "rejection_counts": {"fundamental_evidence_missing": 2},
    }
    assert result.metadata_verified is True


def test_scheduler_dependencies_cover_scan_to_execution_to_learning():
    morning_names = [task.name for task in MORNING_ROUTINE]
    assert morning_names.index("sync_market_data") < morning_names.index("run_scanner")
    assert morning_names.index("run_scanner") < morning_names.index("generate_morning_brief")

    market_names = [task.name for task in MARKET_HOURS_MONITOR]
    assert market_names.index("market_open_check") < market_names.index("execute_open_strategy")
    assert get_schedule_for_phase(SchedulePhase.MARKET_OPEN)[1].depends_on == [
        "market_open_check"
    ]

    eod_names = [task.name for task in EOD_PROCESSING]
    assert eod_names.index("close_positions_check") < eod_names.index("update_outcomes")
    assert eod_names.index("update_outcomes") < eod_names.index("generate_daily_journal")


def test_degraded_market_data_blocks_new_buy_but_allows_existing_position_sell():
    payload = _load_fixture()
    for stage in payload["stages"]:
        if stage["name"] == "market_open":
            stage["market_data_status"] = "degraded"

    result = replay_trading_cycle(payload)

    assert result.status == "blocked"
    assert "degraded_data_buy_blocked" in result.reasons
    assert result.metrics["sell_count"] == 1
    assert result.metrics["buy_count"] == 0


def test_replay_rejects_future_data_and_formal_ledger_writes():
    payload = _load_fixture()
    payload["metadata"]["writes_formal_ledger"] = True
    payload["stages"][0]["candidates"][0]["data_time"] = "2026-09-01T01:04:01+08:00"

    result = replay_trading_cycle(payload)

    assert result.status == "blocked"
    assert "formal_ledger_write_forbidden" in result.reasons
    assert "future_data_detected" in result.reasons
