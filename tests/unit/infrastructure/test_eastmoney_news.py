from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.market_data import eastmoney_common, eastmoney_news


class _Response:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_stock_and_global_news_strips_html():
    stock = eastmoney_news.parse_stock_news({
        "result": {"cmsArticleWebOld": [{
            "title": "<b>风华高科</b>公告",
            "content": "<p>公司发布公告</p>",
            "date": "2026-08-31 09:00:00",
            "mediaName": "测试媒体",
            "url": "https://example.test/a",
        }]}
    })
    global_news = eastmoney_news.parse_global_news({
        "data": {"fastNewsList": [{
            "title": "<b>A股午盘</b>",
            "summary": "<p>市场震荡</p>",
            "showTime": "2026-08-31 11:30:00",
            "mediaName": "东方财富",
        }]}
    })

    assert stock[0]["title"] == "风华高科公告"
    assert stock[0]["content"] == "公司发布公告"
    assert global_news[0]["title"] == "A股午盘"
    assert global_news[0]["summary"] == "市场震荡"


@pytest.mark.asyncio
async def test_fetch_global_news_returns_radar_contract(monkeypatch):
    eastmoney_common._CACHE.clear()
    monkeypatch.setattr(eastmoney_news, "pace", AsyncMock())

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            assert url == eastmoney_news.GLOBAL_NEWS_URL
            assert params["biz"] == "web_724"
            return _Response({
                "data": {"fastNewsList": [{
                    "title": "市场快讯",
                    "brief": "指数走强",
                    "showTime": "2026-08-31 10:00:00",
                    "source": "东方财富",
                }]}
            })

    monkeypatch.setattr(eastmoney_news.httpx, "AsyncClient", lambda **kwargs: Client())

    result = await eastmoney_news.fetch_eastmoney_global_news(page_size=10)

    assert result["total_count"] == 1
    assert result["news"][0]["title"] == "市场快讯"
    assert result["_meta"]["provider"] == "eastmoney"
    assert result["_meta"]["available"] is True


@pytest.mark.asyncio
async def test_fetch_global_news_reuses_fresh_cache(monkeypatch):
    eastmoney_common._CACHE.clear()
    monkeypatch.setattr(eastmoney_news, "pace", AsyncMock())
    calls = 0

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            nonlocal calls
            calls += 1
            return _Response({"data": {"fastNewsList": [{"title": "缓存测试"}]}})

    monkeypatch.setattr(eastmoney_news.httpx, "AsyncClient", lambda **kwargs: Client())

    first = await eastmoney_news.fetch_eastmoney_global_news(page_size=11)
    second = await eastmoney_news.fetch_eastmoney_global_news(page_size=11)

    assert calls == 1
    assert second["_meta"]["cached"] is True
    assert second["news"] == first["news"]
