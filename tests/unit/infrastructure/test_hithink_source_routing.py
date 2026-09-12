from __future__ import annotations

from dataclasses import dataclass

import pytest

from config.settings import settings
from src.infrastructure.market_data import source_manager as source_manager_module
from src.infrastructure.market_data.source_manager import source_manager


@dataclass
class _Payload:
    data: list[dict]
    data_date: str = "2026-09-11"
    endpoint: str = "/api/a-share/prices/historical"
    fetched_at: str = "2026-09-12T01:00:00+00:00"


class _FakeHiThink:
    configured = True

    async def fetch_daily_history(self, code, start, end, adjust):
        assert code == "600519.SH"
        assert start < end
        assert adjust == "none"
        return _Payload(
            [
                {
                    "date": "2026-09-10",
                    "open": 1200,
                    "high": 1210,
                    "low": 1190,
                    "close": 1205,
                    "volume": 100,
                    "amount": 120500,
                },
                {
                    "date": "2026-09-11",
                    "open": 1205,
                    "high": 1220,
                    "low": 1200,
                    "close": 1215,
                    "volume": 110,
                    "amount": 133650,
                },
            ]
        )


@pytest.mark.asyncio
async def test_hithink_kline_dispatch_returns_dated_non_live_bars(monkeypatch):
    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeHiThink())
    monkeypatch.setattr(settings, "HITHINK_DAILY_MODE", "validator")

    bars, provenance = await source_manager._dispatch_kline(
        "hithink", "600519.SH", 2
    )

    assert bars is not None
    assert [bar["date"] for bar in bars] == ["2026-09-10", "2026-09-11"]
    assert provenance.provider == "hithink"
    assert provenance.is_live is False
    assert provenance.data_date == "2026-09-11"
    assert provenance.coverage_ratio == 1.0


def test_hithink_is_not_ranked_when_daily_mode_is_shadow_or_disabled(monkeypatch):
    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeHiThink())
    for mode in ("shadow", "disabled"):
        monkeypatch.setattr(settings, "HITHINK_DAILY_MODE", mode)
        assert "hithink" not in source_manager._get_ranked_providers(
            "600519.SH", "daily_kline"
        )
