import asyncio
import time

import pytest

from src.infrastructure.storage.market_database import MarketDatabase


def _decision(code: str) -> dict:
    return {
        "date": "2026-09-07",
        "stock_code": code,
        "stock_name": code,
        "ai_score": 70,
        "direction": "neutral",
        "recommendation": "Hold",
        "technical_score": 70,
        "signal_at": "2026-09-07T01:00:00+08:00",
        "run_id": "test-run",
        "evidence": "{}",
    }


def test_decision_batch_persists_journal_and_strategy_atomically(tmp_path, monkeypatch):
    database = MarketDatabase(tmp_path / "batch.db")
    calls = 0
    original_get_conn = database._get_conn

    def counted_connection():
        nonlocal calls
        calls += 1
        return original_get_conn()

    monkeypatch.setattr(database, "_get_conn", counted_connection)
    decisions = [_decision("000001.SZ"), _decision("600000.SH")]

    journal_ids = database.save_decisions_batch(decisions)

    assert len(journal_ids) == 2
    assert journal_ids[0] < journal_ids[1]
    assert calls == 1
    assert database.count_decisions_for_date("2026-09-07") == 2
    assert calls == 2

    for decision, journal_id in zip(decisions, journal_ids, strict=True):
        decision["journal_id"] = journal_id
        decision["execution_disposition"] = "blocked"
        decision["execution_block_reason"] = "test"
    assert database.save_strategy_decisions_batch(decisions) == 2
    assert calls == 3

    restored = database.get_decisions_for_date("2026-09-07")
    by_code = {item["stock_code"]: item for item in restored}
    assert by_code["000001.SZ"]["execution_disposition"] == "blocked"
    assert by_code["600000.SH"]["execution_block_reason"] == "test"


@pytest.mark.asyncio
async def test_batch_persistence_does_not_block_event_loop(tmp_path):
    database = MarketDatabase(tmp_path / "responsive.db")
    decisions = [_decision(f"60{index:04d}.SH") for index in range(100)]
    ticks = 0
    running = True

    async def heartbeat():
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.001)

    heartbeat_task = asyncio.create_task(heartbeat())
    started = time.perf_counter()
    try:
        journal_ids = await asyncio.to_thread(database.save_decisions_batch, decisions)
    finally:
        running = False
        await heartbeat_task

    assert len(journal_ids) == len(decisions)
    assert ticks >= 1
    assert time.perf_counter() - started < 5
