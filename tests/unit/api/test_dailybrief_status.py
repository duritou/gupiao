import asyncio
from time import monotonic

import pytest

from src.api.routes.brief_utils import _bounded, _brief_data_state


def test_brief_data_state_distinguishes_collecting_empty_and_degraded():
    assert _brief_data_state({"market": False}, {"process_status": "running"}) == "collecting"
    assert _brief_data_state({"market": False}, {}) == "empty"
    assert _brief_data_state({"market": True, "vibe": False}, {}) == "degraded"
    assert _brief_data_state({"market": True, "vibe": True}, {}) == "ready"


@pytest.mark.asyncio
async def test_bounded_optional_source_returns_within_budget():
    async def slow_source():
        await asyncio.sleep(0.2)
        return {"unexpected": True}

    started = monotonic()
    result = await _bounded(slow_source(), {}, 0.01)
    elapsed = monotonic() - started

    assert result == {}
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_bounded_sync_read_returns_within_budget():
    def slow_database_read():
        import time

        time.sleep(0.2)
        return {"unexpected": True}

    started = monotonic()
    result = await _bounded(asyncio.to_thread(slow_database_read), {}, 0.01)
    elapsed = monotonic() - started

    assert result == {}
    assert elapsed < 0.1
