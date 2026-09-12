import sys
from types import SimpleNamespace

import pytest

from src.infrastructure.market_data import current_metadata_sync
from src.infrastructure.storage.market_database import MarketDatabase


def _seed_bars(database, code, dates):
    with database._get_conn() as conn:
        conn.executemany(
            """INSERT INTO market_daily
               (ts_code, trade_date, open, high, low, close, volume, amount, change_pct)
               VALUES (?, ?, 1, 1, 1, 1, 100, 100, 0)""",
            [(code, date) for date in dates],
        )


def test_historical_metadata_is_as_of_and_missing_snapshots_fail_closed(tmp_path):
    database = MarketDatabase(tmp_path / "metadata.db")
    database.upsert_stock_metadata_snapshot(
        [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "industry": "银行",
                "list_date": "2010-01-01",
                "status": "active",
            },
            {
                "ts_code": "000002.SZ",
                "name": "*ST示例",
                "list_date": "2010-01-01",
                "is_st": True,
                "status": "active",
            },
        ],
        "2026-01-01",
        source="fixture",
    )

    assert database.get_stock_metadata("000001.SZ", "2026-02-01")["industry"] == "银行"
    assert database.is_stock_eligible("000001.SZ", "2026-02-01") is True
    assert database.is_stock_eligible("000002.SZ", "2026-02-01") is False
    assert database.is_stock_eligible("000001.SZ", "2025-12-31") is False


def test_historical_universe_filters_bars_by_cutoff_and_metadata(tmp_path):
    database = MarketDatabase(tmp_path / "universe.db")
    _seed_bars(database, "000001.SZ", ["2026-01-01", "2026-01-02", "2026-01-03"])
    _seed_bars(database, "000002.SZ", ["2026-01-01", "2026-01-02", "2026-01-03"])
    database.upsert_stock_metadata_snapshot(
        [
            {"ts_code": "000001.SZ", "name": "A", "list_date": "2020-01-01"},
            {"ts_code": "000002.SZ", "name": "B", "list_date": "2026-01-03"},
        ],
        "2026-01-02",
    )

    result = database.get_stock_universe(min_bars=2, as_of_date="2026-01-02")

    assert [item["code"] for item in result] == ["000001.SZ"]
    assert result[0]["latest_date"] == "2026-01-02"


def test_metadata_snapshot_sync_uses_date_aware_exchange_universe(tmp_path, monkeypatch):
    class _Result:
        error_code = "0"
        error_msg = ""
        fields = ["code", "code_name", "tradeStatus"]

        def __init__(self):
            self._rows = [["sz.000001", "平安银行", "1"], ["sz.000002", "示例", "0"]]
            self._index = -1

        def next(self):
            self._index += 1
            return self._index < len(self._rows)

        def get_row_data(self):
            return self._rows[self._index]

    fake_baostock = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        query_all_stock=lambda day: _Result(),
        logout=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_baostock)
    database = MarketDatabase(tmp_path / "metadata-sync.db")

    result = database.sync_stock_metadata_snapshot("2026-01-02")

    assert result["status"] == "ok"
    assert result["stored_count"] == 2
    assert database.get_stock_metadata("000002.SZ", "2026-01-02")["is_suspended"] == 1


def test_metadata_snapshot_sync_falls_back_without_carrying_suspension(
    tmp_path, monkeypatch
):
    class _Result:
        error_code = "0"
        error_msg = ""
        fields = ["code", "code_name", "tradeStatus", "isST"]

        def __init__(self, rows):
            self._rows = rows
            self._index = -1

        def next(self):
            self._index += 1
            return self._index < len(self._rows)

        def get_row_data(self):
            return self._rows[self._index]

    queried = []

    def query_all_stock(day):
        queried.append(day)
        if day == "2026-01-05":
            return _Result([])
        return _Result([
            ["sz.000001", "平安银行", "1", "0"],
            ["sz.000002", "示例", "0", "0"],
        ])

    fake_baostock = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        query_all_stock=query_all_stock,
        logout=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_baostock)
    database = MarketDatabase(tmp_path / "metadata-fallback.db")

    result = database.sync_stock_metadata_snapshot(
        "2026-01-05", codes=["000001.SZ", "000002.SZ"]
    )

    assert queried[:2] == ["2026-01-05", "2026-01-04"]
    assert result["status"] == "fallback"
    assert result["source_date"] == "2026-01-04"
    assert result["suspension_status"] == "unknown_pending_live_quote"
    assert result["stored_count"] == 2
    assert "same_day_status_unavailable" in result["warnings"]
    metadata = database.get_stock_metadata_snapshot("2026-01-05")
    assert metadata["000001.SZ"]["is_suspended"] == 0
    assert metadata["000002.SZ"]["is_suspended"] == 0
    assert metadata["000002.SZ"]["status"] == "status_unknown"
    assert metadata["000002.SZ"]["source"] == "baostock_previous_day_baseline"


def test_metadata_snapshot_sync_reports_unavailable_after_empty_lookback(
    tmp_path, monkeypatch
):
    class _EmptyResult:
        error_code = "0"
        error_msg = ""
        fields = ["code", "code_name", "tradeStatus"]

        def next(self):
            return False

    fake_baostock = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        query_all_stock=lambda day: _EmptyResult(),
        logout=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_baostock)
    database = MarketDatabase(tmp_path / "metadata-unavailable.db")

    result = database.sync_stock_metadata_snapshot("2026-01-05")

    assert result["status"] == "unavailable"
    assert result["stored_count"] == 0
    assert result["suspension_status"] == "unknown"
    assert "status_source_unpublished_or_empty" in result["warnings"]


def test_live_universe_exposes_liquidity_but_historical_query_does_not_use_current_metadata(
    tmp_path,
):
    database = MarketDatabase(tmp_path / "live-universe.db")
    _seed_bars(database, "000001.SZ", ["2026-01-01", "2026-01-02", "2026-01-03"])
    with database._get_conn() as conn:
        conn.execute(
            """INSERT INTO stock_basic(ts_code, name, industry, list_date, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("000001.SZ", "平安银行", "银行", "2010-01-01", "2026-01-03"),
        )
    database.upsert_stock_metadata_snapshot(
        [{"ts_code": "000001.SZ", "name": "平安银行", "list_date": "2010-01-01"}],
        "2026-01-03",
    )

    live = database.get_stock_universe(min_bars=2, limit=10)
    historical = database.get_stock_universe(
        min_bars=2, limit=10, as_of_date="2026-01-03"
    )

    assert live[0]["industry"] == "银行"
    assert live[0]["list_date"] == "2010-01-01"
    assert live[0]["avg_daily_amount_million"] == 0.0001
    assert historical[0]["industry"] == ""
    assert historical[0]["list_date"] == ""


def test_current_quote_metadata_is_available_live_but_history_is_date_matched(tmp_path):
    database = MarketDatabase(tmp_path / "quote-metadata.db")
    _seed_bars(database, "000001.SZ", ["2026-01-01", "2026-01-02", "2026-01-03"])
    database.upsert_stock_metadata_snapshot(
        [{"ts_code": "000001.SZ", "name": "平安银行", "list_date": "2010-01-01"}],
        "2026-01-03",
    )

    stored = database.upsert_current_stock_metadata(
        [{
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "market_cap_yi": 1200,
            "float_mcap_yi": 1100,
            "turnover_pct": 1.2,
            "data_date": "2026-01-03",
            "fetched_at": "2026-01-03T08:00:00+00:00",
            "source": "fixture_quote",
        }],
        "2026-01-03",
    )

    assert stored == {"current_count": 1, "history_count": 1}
    assert database.get_stock_universe(min_bars=2)[0]["market_cap"] == 1200
    assert database.get_stock_universe(
        min_bars=2, as_of_date="2026-01-03"
    )[0]["market_cap"] == 1200

    database.upsert_current_stock_metadata(
        [{
            "ts_code": "000001.SZ",
            "market_cap_yi": 1300,
            "data_date": "2026-01-04",
            "source": "fixture_quote",
        }],
        "2026-01-03",
    )
    assert database.get_stock_universe(min_bars=2)[0]["market_cap"] == 1300
    assert database.get_stock_universe(
        min_bars=2, as_of_date="2026-01-03"
    )[0]["market_cap"] == 1200


@pytest.mark.asyncio
async def test_current_metadata_sync_reports_partial_quote_and_cap_coverage(
    tmp_path, monkeypatch
):
    database = MarketDatabase(tmp_path / "current-sync.db")
    monkeypatch.setattr(
        "src.infrastructure.storage.market_database.market_db", database
    )
    database.upsert_stock_metadata_snapshot(
        [{
            "ts_code": "000002.SZ",
            "name": "万科A",
            "status": "suspended",
            "is_suspended": True,
        }],
        "2026-01-03",
        source="fixture_status",
    )

    monkeypatch.setattr(
        database,
        "sync_stock_metadata_snapshot",
        lambda as_of_date, codes=None: {
            "status": "ok",
            "as_of_date": as_of_date,
            "stored_count": len(codes or []),
            "errors": [],
        },
    )

    async def no_tushare_metadata(codes, target_date):
        return None

    monkeypatch.setattr(
        current_metadata_sync,
        "_try_tushare_metadata",
        no_tushare_metadata,
    )

    async def fake_quotes(self, codes):
        return {
            "000001.SZ": {
                "name": "平安银行",
                "market_cap_yi": 1200,
                "data_date": "2026-01-03",
                "fetched_at": "2026-01-03T08:00:00+00:00",
                "source": "fixture_quote",
            },
            "000002.SZ": {
                "name": "万科A",
                "market_cap_yi": None,
                "data_date": "2026-01-03",
                "fetched_at": "2026-01-03T08:00:00+00:00",
                "source": "fixture_quote",
            },
        }

    monkeypatch.setattr(
        current_metadata_sync.RemoteMarketDiscovery,
        "fetch_live_quotes",
        fake_quotes,
    )
    result = await current_metadata_sync.sync_current_stock_metadata(
        ["000001.SZ", "000002.SZ", "600000.SH"],
        as_of_date="2026-01-03",
    )

    assert result["status"] == "partial"
    assert result["requested_count"] == 3
    assert result["quote_count"] == 2
    assert result["market_cap_count"] == 1
    assert result["history_count"] == 1
    assert "quote_missing:1" in result["errors"]
    assert "market_cap_missing:1" in result["errors"]
    assert result["trading_status_snapshot"]["status"] == "ok"
    suspended = database.get_stock_metadata("000002.SZ", "2026-01-03")
    assert suspended["is_suspended"] == 1
    assert suspended["status"] == "suspended"


def test_metadata_snapshot_map_returns_latest_status_at_cutoff(tmp_path):
    database = MarketDatabase(tmp_path / "metadata-map.db")
    database.upsert_stock_metadata_snapshot(
        [{"ts_code": "002998.SZ", "status": "active"}],
        "2026-09-03",
    )
    database.upsert_stock_metadata_snapshot(
        [{
            "ts_code": "002998.SZ",
            "status": "suspended",
            "is_suspended": True,
        }],
        "2026-09-09",
    )

    old = database.get_stock_metadata_snapshot("2026-09-03")
    current = database.get_stock_metadata_snapshot("2026-09-09")

    assert old["002998.SZ"]["is_suspended"] == 0
    assert current["002998.SZ"]["is_suspended"] == 1


def test_quote_valuation_carries_forward_authoritative_suspension(tmp_path):
    database = MarketDatabase(tmp_path / "metadata-carry-forward.db")
    database.upsert_stock_metadata_snapshot(
        [{
            "ts_code": "002998.SZ",
            "name": "优彩资源",
            "status": "suspended",
            "is_suspended": True,
            "source": "baostock_query_all_stock",
        }],
        "2026-09-09",
    )

    database.upsert_current_stock_metadata([{
        "ts_code": "002998.SZ",
        "name": "优彩资源",
        "market_cap_yi": 40,
        "data_date": "2026-09-10",
        "source": "tencent_live_quote",
    }], "2026-09-10")

    current = database.get_stock_metadata("002998.SZ", "2026-09-10")
    assert current["status"] == "suspended"
    assert current["is_suspended"] == 1
    assert current["market_cap_yi"] == 40
    assert current["source"] == "baostock_query_all_stock"
    assert current["market_cap_source"] == "tencent_live_quote"
