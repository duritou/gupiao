from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.api.routes import brief_utils
from src.infrastructure.market_data import eastmoney_emotion


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_limit_pool_normalizes_board_fields():
    rows = eastmoney_emotion.parse_limit_pool({
        "data": {"pool": [{
            "c": "000001",
            "n": "测试股份",
            "p": 12345,
            "zdp": 10.01,
            "hs": 4.2,
            "lbc": 3,
            "fbt": 93000,
            "zttj": {"days": 3, "ct": 3},
        }]}
    }, "limit_up")

    assert rows[0]["code"] == "000001"
    assert rows[0]["price"] == 12.345
    assert rows[0]["limit_days"] == 3
    assert rows[0]["board_stat"] == "3天3板"
    assert rows[0]["first_seal"] == "09:30:00"


@pytest.mark.asyncio
async def test_fetch_limit_up_sentiment_calculates_core_metrics(monkeypatch):
    monkeypatch.setattr(eastmoney_emotion, "pace", AsyncMock())

    pools = {
        "getTopicZTPool": [{"c": "000001", "n": "涨停股", "p": 1000, "zdp": 10, "lbc": 2}],
        "getTopicZBPool": [{"c": "000002", "n": "炸板股", "p": 1000, "zdp": 6, "lbc": 1}],
        "getTopicDTPool": [{"c": "000003", "n": "跌停股", "p": 1000, "zdp": -10}],
        "getYesterdayZTPool": [{"c": "000004", "n": "晋级股", "p": 1000, "zdp": 10, "ylbc": 1}],
    }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            endpoint = url.rsplit("/", 1)[-1]
            return _Response({"data": {"pool": pools[endpoint]}})

    monkeypatch.setattr(eastmoney_emotion.httpx, "AsyncClient", lambda **kwargs: Client())

    result = await eastmoney_emotion.fetch_limit_up_sentiment("2026-08-31")

    data = result["data"]
    assert result["_meta"]["provider"] == "eastmoney"
    assert data["zt_count"] == 1
    assert data["zb_count"] == 1
    assert data["dt_count"] == 1
    assert data["break_rate"] == 50.0
    assert data["max_height"] == 2
    assert data["promotion_rate"] == 100.0


@pytest.mark.asyncio
async def test_brief_sentiment_prefers_native_pools(monkeypatch):
    native = {
        "data": {"zt_count": 12, "break_rate": 18.0},
        "_meta": {"provider": "eastmoney"},
    }
    monkeypatch.setattr(
        eastmoney_emotion,
        "fetch_limit_up_sentiment",
        AsyncMock(return_value=native),
    )

    class Provider:
        async def get_sentiment_lite(self):
            raise AssertionError("Vibe should not be used when native sentiment is available")

    result, metadata = await brief_utils._get_short_term_sentiment(Provider())

    assert result["zt_count"] == 12
    assert metadata["provider"] == "eastmoney"
