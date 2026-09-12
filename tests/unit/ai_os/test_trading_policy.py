from src.ai_os.execution_policy import probe_exit_reason
from src.ai_os.trading_policy import position_exit_reason


def test_normal_deep_buy_exit_rules_remain_unchanged():
    assert position_exit_reason(
        {"avg_cost": 10.0, "entry_date": "2026-08-01"},
        {"ai_score": 75, "direction": "buy", "deep_rating": "Buy"},
        current_price=20.0,
        holding_days=19,
        high_price=25.0,
    ) == ""


def test_probe_has_hard_stop_and_flow_negative_exit():
    position = {"execution_tier": "probe", "avg_cost": 10.0}
    assert probe_exit_reason(
        position,
        {"flow_status": "missing", "market_flow": {}},
        9.5,
        1,
    ).startswith("probe_stop_loss")
    assert probe_exit_reason(
        position,
        {"flow_status": "negative", "market_flow": {"main_net": -1}},
        10.0,
        1,
    ) == "probe_flow_negative"


def test_probe_expires_at_confirmation_and_absolute_limits():
    position = {"execution_tier": "probe", "avg_cost": 10.0}
    missing = {"flow_status": "missing", "market_flow": {}}
    assert probe_exit_reason(position, missing, 10.2, 3) == "probe_unconfirmed_after=3d"
    assert probe_exit_reason(position, missing, 10.2, 5) == "probe_max_holding_days=5"

