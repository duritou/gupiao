from __future__ import annotations

from src.infrastructure.market_data.hithink_financial import (
    missing_financial_rows,
    normalize_financial_statements,
)


def test_normalize_financial_statements_preserves_period_and_nulls():
    result = normalize_financial_statements(
        {
            "statements": {
                "income": [
                    {
                        "thscode": "600519.SH",
                        "period_end_ms": 1767139200000,
                        "report_date_ms": 1774915200000,
                        "net_profit": None,
                    }
                ],
                "balance": [
                    {"period_end_ms": 1767139200000, "assets_total": 100}
                ],
            }
        },
        "600519.SH",
    )

    income = result["income"][0]
    assert income["end_date"] == "2025-12-31"
    assert income["ann_date"] == "2026-03-31"
    assert income["net_profit"] is None
    assert result["balancesheet"][0]["ts_code"] == "600519.SH"


def test_missing_financial_rows_never_overwrites_existing_period():
    existing = {
        "income": [{"end_date": "2025-12-31", "net_profit": 10}],
    }
    incoming = {
        "income": [
            {"end_date": "2025-12-31", "net_profit": 99},
            {"end_date": "2024-12-31", "net_profit": 8},
        ]
    }

    additions = missing_financial_rows(existing, incoming, 2)

    assert additions == {"income": [{"end_date": "2024-12-31", "net_profit": 8}]}
