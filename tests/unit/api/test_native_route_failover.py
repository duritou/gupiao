from __future__ import annotations

import pytest

from src.api.routes import (
    announcements_routes,
    dragon_tiger_routes,
    financials_routes,
    reports_routes,
)


class _FallbackProvider:
    async def get_financials(self, code):
        return {
            "data": {"code": code, "source": "vibe"},
            "_meta": {"provider": "vibe"},
        }

    async def get_announcements(self, code):
        return {"announcements": [{"title": code}], "_meta": {"provider": "vibe"}}

    async def get_dragon_tiger(self, code):
        return {"data": {"code": code}, "_meta": {"provider": "vibe"}}

    async def get_reports(self, code):
        return {"reports": [{"id": code}], "_meta": {"provider": "vibe"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_module", "fetch_name", "handler", "payload_key"),
    [
        (financials_routes, "fetch_sina_financials", financials_routes.get_financials, "data"),
        (
            announcements_routes,
            "fetch_cninfo_announcements",
            announcements_routes.get_announcements,
            "announcements",
        ),
        (
            dragon_tiger_routes,
            "fetch_eastmoney_dragon_tiger",
            dragon_tiger_routes.get_dragon_tiger,
            "data",
        ),
        (reports_routes, "fetch_eastmoney_reports", reports_routes.get_reports, "reports"),
    ],
)
async def test_native_adapter_exception_uses_compatibility_fallback(
    monkeypatch, route_module, fetch_name, handler, payload_key
):
    async def broken_native(*args, **kwargs):
        raise ValueError("malformed provider payload")

    monkeypatch.setattr(route_module, fetch_name, broken_native)
    monkeypatch.setattr(route_module, "get_vibe_provider", lambda: _FallbackProvider())
    if route_module is financials_routes:
        async def unavailable_statements(code):
            del code
            return {}, object()

        async def unavailable_history(code, periods=8):
            del code, periods
            return {}, object()

        monkeypatch.setattr(
            route_module.source_manager,
            "get_financial_statements",
            unavailable_statements,
        )
        monkeypatch.setattr(
            route_module.source_manager,
            "get_financial_history",
            unavailable_history,
        )
    if route_module is dragon_tiger_routes:
        async def unavailable_board(code):
            del code
            return {}, object()

        monkeypatch.setattr(
            route_module.source_manager,
            "get_dragon_tiger",
            unavailable_board,
        )

    result = await handler("600519.SH")

    assert result[payload_key]
    assert result["_meta"]["provider"] == "vibe"
