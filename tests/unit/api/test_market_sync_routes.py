from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.routes import market_routes


@pytest.mark.asyncio
async def test_market_overview_exposes_auditable_regime(monkeypatch):
    class _Provenance:
        is_live = True

        def to_dict(self):
            return {"provider": "test", "is_live": True}

    async def _indices():
        return ([{"name": "涓婅瘉鎸囨暟", "value": 3200, "change_pct": 0.8}], _Provenance())

    async def _breadth():
        return (
            {
                "data_date": "2026-02-03",
                "up": 700,
                "down": 200,
                "flat": 100,
                "limit_up": 80,
                "limit_down": 10,
                "average_change_pct": 0.8,
            },
            _Provenance(),
        )

    monkeypatch.setattr(market_routes.source_manager, "get_index_quotes", _indices)
    monkeypatch.setattr(market_routes.source_manager, "get_market_breadth", _breadth)

    response = await market_routes._build_market_overview()

    assert response["market_regime"]["state"] in {"strong", "lean_strong"}
    assert response["market_regime"]["as_of_date"] == "2026-02-03"
    assert response["market_regime"]["lookahead_safe"] is True
    assert response["_data"]["available"] is True


@pytest.mark.asyncio
async def test_run_sync_can_store_metadata_snapshot_before_daily_bars(monkeypatch):
    calls = []

    class _Database:
        def sync_stock_metadata_snapshot(self, metadata_date, codes=None):
            calls.append(("metadata", metadata_date, codes))
            return {"status": "ok", "stored_count": 2}

        def sync_daily_bars(self, **kwargs):
            calls.append(("daily", kwargs))
            return SimpleNamespace(
                new_daily=3,
                stocks_updated=1,
                errors=[],
                duration_seconds=0.1,
            )

    monkeypatch.setattr(
        "src.infrastructure.storage.market_database.market_db", _Database()
    )
    market_routes._sync_state.update(
        {
            "running": True,
            "result": None,
            "error": None,
            "finished_at": None,
        }
    )

    await market_routes._run_sync(
        ["000001.SZ"], 30, False, metadata_date="2026-01-02"
    )

    assert calls[0] == ("metadata", "2026-01-02", ["000001.SZ"])
    assert calls[1][0] == "daily"
    assert market_routes._sync_state["result"]["metadata_snapshot"]["stored_count"] == 2
    assert market_routes._sync_state["running"] is False


@pytest.mark.asyncio
async def test_ingest_metadata_snapshot_normalizes_date_and_returns_coverage(monkeypatch):
    calls = []

    class _Database:
        def upsert_stock_metadata_snapshot(self, snapshots, as_of_date, source):
            calls.append((snapshots, as_of_date, source))
            return 1

        def get_stock_metadata_coverage(self, as_of_date):
            return {
                "stock_count": 1,
                "first_snapshot": as_of_date,
                "last_snapshot": as_of_date,
            }

    monkeypatch.setattr(
        "src.infrastructure.storage.market_database.market_db", _Database()
    )

    response = await market_routes.ingest_metadata_snapshot(
        market_routes.MetadataSnapshotRequest(
            as_of_date="2026-01-02",
            source="dated-industry",
            snapshots=[{"ts_code": "000001.SZ", "industry": "银行"}],
        )
    )

    assert calls == [
        ([{"ts_code": "000001.SZ", "industry": "银行"}], "2026-01-02", "dated-industry")
    ]
    assert response["status"] == "ok"
    assert response["coverage"]["stock_count"] == 1


@pytest.mark.asyncio
async def test_ingest_metadata_snapshot_rejects_invalid_date_or_missing_code():
    with pytest.raises(HTTPException) as invalid_date:
        await market_routes.ingest_metadata_snapshot(
            market_routes.MetadataSnapshotRequest(
                as_of_date="2026/01/02",
                snapshots=[{"ts_code": "000001.SZ"}],
            )
        )
    assert getattr(invalid_date.value, "status_code", None) == 422

    with pytest.raises(HTTPException) as missing_code:
        await market_routes.ingest_metadata_snapshot(
            market_routes.MetadataSnapshotRequest(
                as_of_date="2026-01-02",
                snapshots=[{"industry": "银行"}],
            )
        )
    assert getattr(missing_code.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_sync_market_data_rejects_invalid_metadata_date_before_start():
    with pytest.raises(HTTPException) as invalid_date:
        await market_routes.sync_market_data(
            codes=None,
            days_back=30,
            with_indicators=False,
            metadata_date="2026/01/02",
        )

    assert invalid_date.value.status_code == 422
    assert market_routes._sync_state["running"] is False


@pytest.mark.asyncio
async def test_metadata_status_returns_date_cutoff_coverage(monkeypatch):
    class _Database:
        def get_stock_metadata_coverage(self, as_of_date):
            return {
                "stock_count": 3,
                "first_snapshot": "2025-01-01",
                "last_snapshot": as_of_date,
            }

    monkeypatch.setattr(
        "src.infrastructure.storage.market_database.market_db", _Database()
    )

    response = await market_routes.metadata_status("2026-02-03")

    assert response["as_of_date"] == "2026-02-03"
    assert response["coverage"]["stock_count"] == 3
