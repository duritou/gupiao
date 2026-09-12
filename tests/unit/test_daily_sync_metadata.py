from types import SimpleNamespace

from scripts import daily_sync


def test_daily_sync_metadata_uses_latest_local_market_date(monkeypatch):
    calls = []

    class FakeDatabase:
        def get_latest_market_date_on_or_before(self, target_date):
            calls.append(("latest", target_date))
            return "2026-08-31"

        def sync_stock_metadata_snapshot(self, market_date):
            calls.append(("sync", market_date))
            return {"status": "ok", "as_of_date": market_date, "stored_count": 2}

    monkeypatch.setattr(daily_sync, "market_db", FakeDatabase())

    result = daily_sync.sync_latest_metadata_snapshot()

    assert result["status"] == "ok"
    assert calls[0][0] == "latest"
    assert calls[1] == ("sync", "2026-08-31")


def test_daily_sync_metadata_fails_closed_without_market_date(monkeypatch):
    class EmptyDatabase:
        def get_latest_market_date_on_or_before(self, target_date):
            return ""

    monkeypatch.setattr(daily_sync, "market_db", EmptyDatabase())

    result = daily_sync.sync_latest_metadata_snapshot()

    assert result == {
        "status": "no_market_date",
        "as_of_date": "",
        "stock_count": 0,
        "stored_count": 0,
    }


def test_daily_sync_returns_warning_code_when_quote_metadata_is_partial(monkeypatch):
    class FakeDatabase:
        def get_latest_market_date_on_or_before(self, target_date):
            return "2026-08-31"

        def sync_stock_metadata_snapshot(self, market_date):
            return {
                "status": "ok",
                "as_of_date": market_date,
                "stock_count": 2,
                "stored_count": 2,
                "errors": [],
            }

        def sync_daily_bars(self, **kwargs):
            return SimpleNamespace(
                new_daily=2, stocks_updated=1, errors=[], duration_seconds=0
            )

    async def trading_day():
        return SimpleNamespace(is_trading_day=True, source="fixture")

    async def partial_metadata(**kwargs):
        return {
            "status": "partial",
            "requested_count": 2,
            "quote_count": 1,
            "market_cap_count": 1,
            "history_count": 1,
            "errors": ["quote_missing:1"],
        }

    monkeypatch.setattr(daily_sync, "market_db", FakeDatabase())
    monkeypatch.setattr(daily_sync, "get_trading_day_status", trading_day)
    monkeypatch.setattr(
        daily_sync, "sync_current_stock_metadata", partial_metadata
    )
    monkeypatch.setattr(
        daily_sync, "parse_args", lambda: SimpleNamespace(dry_run=False)
    )

    assert daily_sync.main() == 2
