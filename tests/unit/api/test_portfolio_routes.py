"""Regression tests for the paper portfolio AI overlay."""

import asyncio

from src.api.routes.portfolio_routes import portfolio_overview


class _FakeMarketDatabase:
    def get_paper_portfolio(self):
        return {
            "date": "2026-08-13",
            "initial_capital": 100000.0,
            "cash": 90000.0,
            "total_value": 100000.0,
            "total_pl": 0.0,
            "total_pl_pct": 0.0,
            "daily_pl": 0.0,
            "daily_pl_pct": 0.0,
            "positions": [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "测试股票",
                    "shares": 125,
                    "cost_price": 80.0,
                    "current_price": 80.0,
                    "market_value": 10000.0,
                    "cost_value": 10000.0,
                    "profit_loss": 0.0,
                    "profit_loss_pct": 0.0,
                    "daily_pl": 0.0,
                    "daily_pl_pct": 0.0,
                    "price_date": "2026-08-13",
                    "price_source": "test",
                    "price_fresh": True,
                },
            ],
            "trades": [],
            "stale_positions": [],
        }

    def get_decision_history_for_codes(self, codes, limit_per_code=2):
        assert codes == ["000001.SZ"]
        assert limit_per_code == 2
        return {
            "000001.SZ": [
                {
                    "stock_code": "000001.SZ",
                    "ai_score": 78.0,
                    "direction": "buy",
                    "confidence": 0.82,
                    "created_at": "2026-08-13T08:30:00",
                    "macd_score": 75.0,
                    "rsi_score": 76.0,
                    "kdj_score": 74.0,
                    "ma_score": 77.0,
                    "volume_score": 76.0,
                },
                {
                    "stock_code": "000001.SZ",
                    "ai_score": 64.0,
                    "direction": "neutral",
                    "confidence": 0.60,
                    "created_at": "2026-08-12T08:30:00",
                },
            ]
        }


def test_portfolio_overview_uses_latest_decision(monkeypatch):
    from src.infrastructure.storage import market_database

    monkeypatch.setattr(market_database, "market_db", _FakeMarketDatabase())

    result = asyncio.run(portfolio_overview())
    position = result["positions"][0]

    assert result["ai_score_source"] == "decision_journal"
    assert result["ai_score_coverage"] == 1.0
    assert result["avg_ai_score"] == 78.0
    assert position["ai_score"] == 78.0
    assert position["ai_direction"] == "buy"
    assert position["last_score_change"] == 14.0
    assert position["risk_level"] == "低"
    assert result["portfolio_risk_level"] == "低"
    assert "78.0" in result["ai_summary"]
    assert "组合风险等级：低" in result["risk_summary"]
