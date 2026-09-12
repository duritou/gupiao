from src.infrastructure.storage.market_database import MarketDatabase


def test_learning_profile_can_apply_time_decay_without_changing_cutoff_semantics(tmp_path):
    database = MarketDatabase(tmp_path / "decay.db")
    with database._get_conn() as connection:
        connection.executemany(
            """INSERT INTO market_learning_observation(
                   decision_id, observation_date, horizon_days, stock_code,
                   direction, was_correct, stock_return, benchmark_return,
                   excess_return, sources_json, feature_json, created_at
               ) VALUES (?, ?, 1, '000001.SZ', 'buy', ?, 0.1, 0, 0.1,
                         '[]', '{}', '')""",
            [(1, "2026-08-31", 1), (2, "2026-06-01", 1)],
        )

    profile = database.get_market_learning_profile(
        horizon_days=1,
        as_of_date="2026-09-01",
        decay_half_life_days=30,
    )

    stats = profile["by_symbol"]["000001.SZ"]
    assert profile["decay_half_life_days"] == 30
    assert stats["observations"] < 2
    assert stats["correct"] == stats["observations"]
