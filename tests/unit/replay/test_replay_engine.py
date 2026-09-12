from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from src.infrastructure.market_data.real_data_provider import real_data
from src.infrastructure.storage.market_database import MarketDatabase
from src.replay.engine import ReplayEngine


@pytest.fixture
def replay_database(tmp_path, monkeypatch):
    database = MarketDatabase(tmp_path / "replay.db")
    target = date(2026, 1, 30)
    start = target - timedelta(days=35)
    rows = []
    previous = 10.0
    for index in range(42):
        trade_date = start + timedelta(days=index)
        close = 10.0 + index * 0.1
        rows.append((
            "600001.SH", trade_date.isoformat(), previous, close + 0.1,
            close - 0.1, close, previous, (close / previous - 1) * 100,
            1_000_000 + index * 10_000, 10_000_000, 1.0,
        ))
        previous = close

    with database._get_conn() as conn:
        conn.execute(
            "INSERT INTO stock_basic (ts_code, name) VALUES (?, ?)",
            ("600001.SH", "Replay Test"),
        )
        conn.executemany(
            """INSERT INTO market_daily
               (ts_code, trade_date, open, high, low, close, pre_close,
                change_pct, volume, amount, turnover)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.execute(
            """INSERT INTO decision_journal
               (decision_date, stock_code, stock_name, ai_score, direction,
                confidence, recommendation, fusion_score, macd_score,
                rsi_score, kdj_score, ma_score, volume_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                target.isoformat(), "600001.SH", "Replay Test", 72.0, "buy",
                0.8, "buy", 72.0, 75.0, 55.0, 60.0, 80.0, 65.0,
                f"{target.isoformat()}T15:10:00+08:00",
            ),
        )

    import src.infrastructure.storage.market_database as storage_module

    monkeypatch.setattr(storage_module, "market_db", database)
    return database, target


def test_freeze_requires_an_exact_journal_date(replay_database):
    _, target = replay_database
    engine = ReplayEngine()

    context = engine.freeze_world((target - timedelta(days=1)).isoformat())

    assert context.status == "no_journal_data"
    assert context.stock_pool == []
    assert "不会回退" in context.message


def test_rerun_excludes_future_bars_and_persists_determinism(replay_database):
    database, target = replay_database
    engine = ReplayEngine()
    context = engine.freeze_world(target.isoformat(), model_version="balanced-v2")

    first = asyncio.run(engine.rerun(context, horizon_days=3))
    second = asyncio.run(engine.rerun(context, horizon_days=3))
    historical = database.get_daily_bars_until("600001.SH", target.isoformat(), limit=250)
    expected = real_data.compute_signals("600001.SH", "Replay Test", historical)

    assert first.status == "ok"
    assert first.total_scanned == 1
    assert first.candidates[0]["entry_date"] == target.isoformat()
    assert first.candidates[0]["data_days"] == len(historical)
    assert first.candidates[0]["scores"]["macd"] == expected.macd_score
    assert first.candidates[0]["outcome_available"] is True
    assert second.is_deterministic is True
    assert second.current_hash == first.current_hash
    assert len(database.get_replay_runs()) == 2


def test_freeze_applies_point_in_time_metadata_when_snapshot_exists(replay_database):
    database, target = replay_database
    database.upsert_stock_metadata_snapshot(
        [{"ts_code": "600001.SH", "name": "Replay Test", "list_date": "2020-01-01"}],
        target.isoformat(),
        source="fixture",
    )

    context = ReplayEngine().freeze_world(target.isoformat())

    assert context.status == "ok"
    assert context.stock_pool[0]["code"] == "600001.SH"
    assert context.scanner_config["metadata_applied"] is True
    assert context.scanner_config["metadata_missing_count"] == 0
    assert context.lookahead_safe is True
    assert context.market_regime["state"] in {
        "strong", "lean_strong", "range", "lean_weak", "weak", "unknown"
    }


def test_strict_metadata_policy_stops_replay_without_snapshot(replay_database):
    _, target = replay_database

    context = ReplayEngine().freeze_world(target.isoformat(), metadata_policy="strict")

    assert context.status == "metadata_unavailable"
    assert "元数据" in context.message


def test_compare_and_simulation_use_observed_future_paths(replay_database):
    database, target = replay_database
    engine = ReplayEngine()

    comparison = asyncio.run(engine.compare_models(target.isoformat(), horizon_days=3))
    simulation = asyncio.run(engine.simulate(
        target.isoformat(),
        scenarios=[{
            "name": "test_path",
            "description": "real three-day path",
            "buy_threshold": 50,
            "top_n": 1,
            "holding_days": 3,
            "cost_pct": 0.2,
        }],
    ))

    assert comparison.status in {"ok", "outcomes_pending"}
    assert set(comparison.metrics) == {
        "technical-v1", "balanced-v2", "defensive-v2"
    }
    assert simulation.status == "ok"
    assert simulation.results["test_path"]["total_trades"] == 1
    assert simulation.results["test_path"]["evaluation_coverage"] == 1.0
    assert {run["mode"] for run in database.get_replay_runs()} == {"compare", "simulate"}
