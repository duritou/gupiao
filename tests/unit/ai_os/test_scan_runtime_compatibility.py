from datetime import datetime

from src.ai_os.pipeline_runner import _selection_weights
from src.ai_os.scheduler import SchedulePhase, get_recoverable_phases


def test_pre_market_recovery_leaves_exact_scheduled_checkpoint_to_cron():
    assert get_recoverable_phases(datetime(2026, 8, 17, 1, 0)) == []
    assert get_recoverable_phases(datetime(2026, 8, 17, 1, 1)) == [
        SchedulePhase.PRE_MARKET,
    ]


def test_cross_sectional_weights_are_compatible_with_legacy_settings():
    class LegacySettings:
        pass

    settings = LegacySettings()
    assert _selection_weights(settings) == {
        "technical": 0.70,
        "discovery": 0.20,
        "learning": 0.10,
        "rank": 0.70,
    }
