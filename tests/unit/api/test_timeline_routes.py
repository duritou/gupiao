"""Regression tests for real decision-journal Timeline history."""

import asyncio

from src.api.routes.timeline_routes import get_timeline


class _FakeMarketDatabase:
    def get_decision_history_for_codes(self, codes, limit_per_code=2):
        assert codes == ["000001.SZ"]
        assert limit_per_code == 300
        # Database history is newest-first. Two runs on 08-22 verify that the
        # route retains the newest observation for each trading date.
        return {
            "000001.SZ": [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "decision_date": "2026-08-22",
                    "created_at": "2026-08-22T14:30:00+08:00",
                    "ai_score": 72,
                    "recommendation": "buy",
                },
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "decision_date": "2026-08-22",
                    "created_at": "2026-08-22T09:35:00+08:00",
                    "ai_score": 68,
                    "recommendation": "watch",
                },
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "decision_date": "2026-08-21",
                    "created_at": "2026-08-21T14:30:00+08:00",
                    "ai_score": 65,
                    "recommendation": "watch",
                },
            ]
        }


def test_timeline_returns_real_daily_history_in_chronological_order(monkeypatch):
    from src.infrastructure.storage import market_database

    monkeypatch.setattr(market_database, "market_db", _FakeMarketDatabase())

    result = asyncio.run(get_timeline("000001.sz", 30))

    assert result["stock_code"] == "000001.SZ"
    assert result["stock_name"] == "平安银行"
    assert result["current_score"] == 72.0
    assert result["total_change"] == 7.0
    assert [entry["date"] for entry in result["entries"]] == [
        "2026-08-21",
        "2026-08-22",
    ]
    assert [entry["score"] for entry in result["entries"]] == [65.0, 72.0]
    assert result["entries"][1]["change"] == 7.0
    assert result["entries"][1]["observed_at"] == "2026-08-22T14:30:00+08:00"


def test_timeline_handles_missing_history(monkeypatch):
    from src.infrastructure.storage import market_database

    class _EmptyMarketDatabase:
        def get_decision_history_for_codes(self, codes, limit_per_code=2):
            return {"000001.SZ": []}

    monkeypatch.setattr(market_database, "market_db", _EmptyMarketDatabase())

    result = asyncio.run(get_timeline("000001.SZ", 30))

    assert result["entries"] == []
    assert result["current_score"] is None
    assert result["total_change"] == 0
