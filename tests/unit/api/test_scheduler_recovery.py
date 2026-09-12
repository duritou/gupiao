from datetime import datetime

from src.ai_os.scheduler import SchedulePhase, get_current_phase, get_recoverable_phases


def test_current_phase_does_not_enter_open_execution_before_0935():
    assert get_current_phase(datetime(2026, 8, 17, 9, 5)) == SchedulePhase.PRE_MARKET
    assert get_current_phase(datetime(2026, 8, 17, 9, 35)) == SchedulePhase.MARKET_OPEN


def test_recovery_catches_a_late_pre_market_start():
    assert get_recoverable_phases(datetime(2026, 8, 17, 1, 5)) == [
        SchedulePhase.PRE_MARKET,
    ]
    assert get_recoverable_phases(datetime(2026, 8, 17, 8, 38)) == [
        SchedulePhase.PRE_MARKET,
    ]


def test_recovery_catches_missed_open_without_replaying_pre_market():
    assert get_recoverable_phases(datetime(2026, 8, 17, 10, 0)) == [
        SchedulePhase.MARKET_OPEN,
    ]


def test_afternoon_deep_scan_and_light_review_have_separate_windows():
    assert get_current_phase(datetime(2026, 8, 17, 13, 30)) == SchedulePhase.AFTERNOON
    assert get_recoverable_phases(datetime(2026, 8, 17, 13, 40)) == [
        SchedulePhase.AFTERNOON,
    ]
    assert get_current_phase(datetime(2026, 8, 17, 14, 30)) == (
        SchedulePhase.LATE_AFTERNOON
    )
    assert get_recoverable_phases(datetime(2026, 8, 17, 14, 40)) == [
        SchedulePhase.LATE_AFTERNOON,
    ]


def test_recovery_runs_close_before_evening_after_late_restart():
    assert get_recoverable_phases(datetime(2026, 8, 17, 21, 18)) == [
        SchedulePhase.MARKET_CLOSE,
        SchedulePhase.EVENING,
    ]


def test_recovery_does_not_run_outside_safe_windows_or_on_weekends():
    assert get_recoverable_phases(datetime(2026, 8, 17, 9, 25)) == []
    assert get_recoverable_phases(datetime(2026, 8, 17, 15, 0)) == [
        SchedulePhase.MARKET_CLOSE,
    ]
    assert get_recoverable_phases(datetime(2026, 8, 22, 8, 38)) == []
