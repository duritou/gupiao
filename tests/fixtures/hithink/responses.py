"""Small synthetic HiThink envelopes used by offline contract tests."""

SNAPSHOT = {
    "code": 0,
    "request_id": "req-snapshot-001",
    "data": {
        "timestamp": None,
        "total": 1,
        "item": [{
            "thscode": "600519.SH", "ticker": "600519", "last_price": 1234.5,
            "price_change": -2.5, "price_change_ratio_pct": -0.2,
            "open_price": 1236.0, "high_price": 1240.0, "low_price": 1230.0,
            "prev_price": 1237.0, "volume": 100, "turnover": None,
        }],
    },
}

SYMBOL_SEARCH = {
    "code": 0,
    "request_id": "req-symbol-001",
    "data": {
        "timestamp": 1789171200000,
        "item": [{
            "thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台",
            "exchange": "SH", "asset_type": "a-share", "list_date": "2001-08-27",
            "end_date": None, "last_trade_date": None, "currency": "CNY",
        }],
    },
}

VALUATION = {
    "code": 0,
    "request_id": "req-valuation-001",
    "data": {
        "timestamp": 1789171200000,
        "total": 1,
        "item": [{
            "thscode": "300750.SZ", "ticker": "300750", "name": "宁德时代",
            "pe_ttm": -1.2, "pe_mrq": None, "pb_mrq": 4.1,
            "ps_ttm": 7.2, "pcf_ttm": None,
        }],
    },
}

EMPTY_LIMIT_POOL = {
    "code": 0,
    "request_id": "req-limit-001",
    "data": {"timestamp": 1789171200000, "pagination": {"total": 0, "pages": 0, "size": 50, "page": 1}, "item": []},
}

DAILY_HISTORY = {
    "code": 0,
    "request_id": "req-history-001",
    "data": {
        "timestamp": 1789171200000,
        "item": [{
            "date_ms": 1789084800000, "open_price": 10.0, "high_price": 11.0,
            "low_price": 9.5, "close_price": 10.5, "volume": 1200, "turnover": 12600,
        }],
    },
}

FINANCIAL = {
    "code": 0,
    "request_id": "req-financial-001",
    "data": {
        "timestamp": 1789171200000,
        "item": [{
            "thscode": "600519.SH", "ticker": "600519", "period": "annual",
            "period_end_ms": 1767139200000,
            "report_date_ms": 1774915200000, "fiscal_year": 2025, "fiscal_period": "FY",
            "currency": "CNY", "net_profit": None, "assets_total": 100.0,
        }],
    },
}

INDICATORS = {
    "code": 0,
    "request_id": "req-indicators-001",
    "data": {
        "thscode": "600519.SH", "report": "2025-4",
        "abilities": [{"ability": "growth", "indicators": [{"index_id": "revenue_yoy", "value": None}]}],
    },
}

DRAGON_TIGER = {
    "code": 0,
    "request_id": "req-dragon-001",
    "data": {
        "timestamp": 1789171200000, "board_type": "all", "trade_date": "2026-09-11",
        "count": 1, "stock_count": 1,
        "stock_items": [{"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台", "net_value": None}],
        "hot_money_items": [],
    },
}
