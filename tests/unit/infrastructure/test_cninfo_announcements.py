from __future__ import annotations

import pytest

from src.infrastructure.market_data import cninfo_announcements


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_cninfo_announcements_normalizes_dates_and_links():
    rows = cninfo_announcements.parse_cninfo_announcements({
        "announcements": [{
            "announcementId": "abc123",
            "announcementTitle": "annual report",
            "announcementTypeName": "periodic report",
            "announcementTime": "2026-08-30 10:00:00",
            "adjunctUrl": "/2026/annual.pdf",
        }]
    })

    assert rows == [{
        "title": "annual report",
        "type": "periodic report",
        "date": "2026-08-30",
        "url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId=abc123",
        "pdf": "https://static.cninfo.com.cn/2026/annual.pdf",
        "source": "cninfo",
    }]


@pytest.mark.asyncio
async def test_fetch_cninfo_announcements_uses_dynamic_org_id(monkeypatch):
    cninfo_announcements._ORGID_CACHE.clear()
    calls: list[dict] = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            assert url == cninfo_announcements.CNINFO_STOCK_MAP_URL
            return _Response({"stockList": [{"code": "600519", "orgId": "gssh000519"}]})

        async def post(self, url, data):
            assert url == cninfo_announcements.CNINFO_ANNOUNCEMENT_URL
            calls.append(data)
            return _Response({
                "announcements": [{
                    "announcementId": "abc123",
                    "announcementTitle": "annual report",
                    "announcementTime": "2026-08-30",
                }]
            })

    monkeypatch.setattr(cninfo_announcements.httpx, "AsyncClient", lambda **kwargs: Client())

    result = await cninfo_announcements.fetch_cninfo_announcements("600519.SH", limit=5)

    assert result["count"] == 1
    assert result["_meta"]["source_layer"] == "adaptive_native"
    assert result["_meta"]["historical"] is True
    assert calls[0]["stock"] == "600519,gssh000519"
