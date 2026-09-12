from src.ai_os.market_learning import multi_horizon_learning_adjustment


def _profile(horizon, observations, correct=None, incorrect=None):
    correct = observations if correct is None else correct
    incorrect = 0 if incorrect is None else incorrect
    return {
        "horizon_days": horizon,
        "decisive_observations": observations,
        "by_symbol": {
            "000001.SZ": {
                "observations": observations,
                "correct": correct,
                "incorrect": incorrect,
            }
        },
        "by_source": {},
    }


def test_sparse_long_horizons_are_visible_but_do_not_steer_score():
    result = multi_horizon_learning_adjustment(
        {
            1: _profile(1, 2),
            5: _profile(5, 2),
            20: _profile(20, 2),
        },
        "000001.SZ",
        [],
    )

    assert result["active_horizons"] == [1]
    assert result["horizon_contributions"]["5"]["available"] is False
    assert result["horizon_contributions"]["20"]["available"] is False


def test_mature_five_day_horizon_can_drive_the_weighted_learning_score():
    result = multi_horizon_learning_adjustment(
        {
            1: _profile(1, 1),
            5: _profile(5, 20),
            20: _profile(20, 1),
        },
        "000001.SZ",
        [],
    )

    assert result["active_horizons"] == [5]
    assert result["horizon_contributions"]["5"]["available"] is True
    assert result["score_adjustment"] == 8.0

