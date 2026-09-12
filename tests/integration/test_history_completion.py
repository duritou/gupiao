from __future__ import annotations

from src.infrastructure.storage.market_database import MarketDatabase


def test_new_listing_is_not_filled_before_its_first_observed_bar(tmp_path):
    database = MarketDatabase(tmp_path / "market.db")
    database.upsert_tushare_daily_history([
        {"ts_code": "301999.SZ", "trade_date": "2026-08-22", "close": 20}
    ])
    detail = database.get_bar_coverage(["301999.SZ"], 250)["details"][0]
    assert detail["status"] == "insufficient"
    assert detail["first_date"] == "2026-08-22"
