from types import SimpleNamespace

from src.ai_os.strategy_version import (
    ALGORITHM_VERSION,
    create_strategy_run_metadata,
)


def _settings(**overrides):
    values = {
        "SCANNER_TECHNICAL_SHORTLIST_COUNT": 300,
        "SCANNER_AI_PRESELECT_COUNT": 20,
        "SCANNER_AI_DEEP_ANALYSIS_N": 5,
        "CROSS_SECTIONAL_RANK_WEIGHT": 0.7,
        "SELECTION_TECHNICAL_WEIGHT": 0.7,
        "SELECTION_DISCOVERY_WEIGHT": 0.2,
        "SELECTION_LEARNING_WEIGHT": 0.1,
        "MAX_POSITION_PCT": 0.2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_strategy_metadata_is_unique_and_auditable():
    first = create_strategy_run_metadata(_settings())
    second = create_strategy_run_metadata(_settings())

    assert first["run_id"] != second["run_id"]
    assert first["strategy_version"] == ALGORITHM_VERSION
    assert len(first["config_hash"]) == 64
    assert len(first["code_hash"]) == 64
    assert first["config_hash"] == second["config_hash"]
    assert first["code_hash"] == second["code_hash"]


def test_strategy_metadata_distinguishes_configuration_changes():
    baseline = create_strategy_run_metadata(_settings())
    changed = create_strategy_run_metadata(
        _settings(SCANNER_AI_DEEP_ANALYSIS_N=7)
    )

    assert baseline["config_hash"] != changed["config_hash"]
    assert baseline["strategy_version"] == changed["strategy_version"]
