from src.ai_os.trading_calendar import (
    TradingDayStatus,
    paper_execution_calendar_verified,
)


def test_official_trading_calendar_allows_paper_execution():
    status = TradingDayStatus(
        is_trading_day=True,
        source="baostock_trade_calendar",
    )

    assert paper_execution_calendar_verified(status) is True


def test_weekday_fallback_never_verifies_paper_execution():
    status = TradingDayStatus(
        is_trading_day=True,
        source="weekday_fallback",
        degraded=True,
        error="calendar unavailable",
    )

    assert paper_execution_calendar_verified(status) is False


def test_official_holiday_never_verifies_paper_execution():
    status = TradingDayStatus(
        is_trading_day=False,
        source="baostock_trade_calendar",
    )

    assert paper_execution_calendar_verified(status) is False
