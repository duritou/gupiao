from src.ai_os.market_regime import classify_market_regime


def test_market_regime_combines_breadth_trend_and_limit_participation():
    result = classify_market_regime(
        {
            "total": 1000,
            "advancing": 800,
            "declining": 150,
            "average_change_pct": 0.9,
            "limit_up": 80,
            "limit_down": 2,
            "trade_date": "2026-01-02",
        },
        signal_date="2026-01-02",
    )

    assert result.state == "strong"
    assert result.score >= 70
    assert result.lookahead_safe is True
    assert result.components["speculation"] > 50


def test_market_regime_marks_future_snapshot_unsafe_and_handles_missing_data():
    future = classify_market_regime(
        {"total": 100, "advancing": 60, "declining": 30, "trade_date": "2026-01-03"},
        signal_date="2026-01-02",
    )
    missing = classify_market_regime({}, signal_date="2026-01-02")

    assert future.lookahead_safe is False
    assert "snapshot date is after signal date" in future.reasons
    assert missing.state == "unknown"
    assert missing.confidence == 0.0
