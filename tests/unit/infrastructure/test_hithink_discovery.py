from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.infrastructure.market_data import remote_market_discovery as discovery_module
from src.infrastructure.market_data.hithink_discovery import (
    HiThinkDiscoveryResult,
    fetch_hithink_special,
)
from src.infrastructure.market_data.remote_market_discovery import RemoteMarketDiscovery


@dataclass
class _Payload:
    data: dict
    data_date: str = "2026-09-11"
    request_id: str = "req-test"


class _FakeHiThink:
    configured = True

    async def fetch_limit_pool(self, kind, trade_date, size):
        if kind == "up":
            return _Payload(
                {
                    "item": [
                        {
                            "thscode": "600519.SH",
                            "name": "贵州茅台",
                            "limit_up_reason": "白酒涨停",
                            "concept_list": ["白酒"],
                        },
                        {"thscode": "bad-code", "name": "忽略"},
                    ]
                },
                request_id="req-up",
            )
        return _Payload({"item": []}, request_id="req-break")

    async def fetch_dragon_tiger(self, trade_date):
        return _Payload(
            {
                "stock_items": [
                    {
                        "thscode": "000001.SZ",
                        "name": "平安银行",
                        "hot_rank": 2,
                    }
                ]
            },
            request_id="req-dragon",
        )


@pytest.mark.asyncio
async def test_hithink_special_projection_is_redacted_and_normalized():
    result = await fetch_hithink_special(
        "2026-09-11",
        10,
        provider=_FakeHiThink(),
    )

    assert result.sources["hithink_limit_up"][0]["code"] == "600519.SH"
    assert result.sources["hithink_limit_up"][0]["concepts"] == ["白酒"]
    assert result.sources["hithink_dragon_tiger"][0]["reason"] == "龙虎榜"
    assert result.observation["status"] == "ok"
    assert result.observation["row_count"] == 2
    assert result.observation["successes"][0]["request_id"] == "req-up"
    assert "api-key" not in str(result.observation).lower()


@pytest.mark.asyncio
async def test_shadow_observation_does_not_change_candidates_or_scores(monkeypatch):
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)

    async def hot_reason(client, day):
        return [{"rank": 1, "code": "600667", "name": "样本", "reason": "topic"}]

    async def hot_list(client):
        return [{"rank": 1, "code": "600667", "name": "样本", "concepts": []}]

    async def eastmoney_hot_rank(client, top):
        return []

    async def quotes(client, codes):
        return {
            "600667.SH": {
                "name": "样本",
                "price": 10,
                "change_pct": 1,
                "amount_wan": 1000,
                "active_volume_ratio": 0.1,
                "source": "tencent_live_quote",
            }
        }

    async def flow(client, code):
        return {"status": "missing", "main_net": None}

    async def research_flow(code, days=5):
        return {"status": "missing", "main_net": None}

    async def shadow(day, limit):
        return HiThinkDiscoveryResult(
            sources={
                "hithink_limit_up": [
                    {"code": "000001.SZ", "name": "额外样本", "rank": 1}
                ]
            },
            observation={"status": "ok", "row_count": 1},
        )

    for name, function in {
        "_ths_hot_reason": hot_reason,
        "_ths_hot_list": hot_list,
        "_eastmoney_hot_rank": eastmoney_hot_rank,
        "_tencent_quotes": quotes,
        "_eastmoney_fund_flow": flow,
    }.items():
        monkeypatch.setattr(discovery, name, function)
    monkeypatch.setattr(
        "src.infrastructure.market_data.research_flow.get_research_flow",
        research_flow,
    )
    monkeypatch.setattr(discovery_module.settings, "HITHINK_SPECIAL_MODE", "disabled")
    baseline = await discovery.discover("2026-09-11", limit=1)
    monkeypatch.setattr(discovery_module.settings, "HITHINK_SPECIAL_MODE", "shadow")
    monkeypatch.setattr(discovery_module, "fetch_hithink_special", shadow)
    shadow_snapshot = await discovery.discover("2026-09-11", limit=1)

    assert shadow_snapshot.candidates == baseline.candidates
    assert shadow_snapshot.provider_observations["hithink_special"]["used"] is False
    assert shadow_snapshot.degraded == baseline.degraded


@pytest.mark.asyncio
async def test_primary_special_rows_use_existing_scoring_pipeline(monkeypatch):
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)

    async def empty_source(*args, **kwargs):
        return []

    async def quotes(client, codes):
        assert codes == ["000001.SZ"]
        return {
            "000001.SZ": {
                "name": "平安银行",
                "price": 10,
                "change_pct": 2,
                "amount_wan": 1000,
                "active_volume_ratio": 0.1,
                "source": "tencent_live_quote",
            }
        }

    async def flow(client, code):
        return {"status": "missing", "main_net": None}

    async def primary(day, limit):
        return HiThinkDiscoveryResult(
            sources={
                "hithink_limit_up": [
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "rank": 1,
                        "reason": "涨停池",
                    }
                ]
            },
            observation={"status": "ok", "row_count": 1},
        )

    monkeypatch.setattr(discovery, "_ths_hot_reason", empty_source)
    monkeypatch.setattr(discovery, "_ths_hot_list", empty_source)
    monkeypatch.setattr(discovery, "_eastmoney_hot_rank", empty_source)
    monkeypatch.setattr(discovery, "_tencent_quotes", quotes)
    monkeypatch.setattr(discovery, "_eastmoney_fund_flow", flow)
    monkeypatch.setattr(discovery_module.settings, "HITHINK_SPECIAL_MODE", "primary")
    monkeypatch.setattr(discovery_module, "fetch_hithink_special", primary)

    snapshot = await discovery.discover("2026-09-11", limit=1)

    assert snapshot.candidates[0]["stock_code"] == "000001.SZ"
    assert "hithink_limit_up" in snapshot.candidates[0]["data_sources"]
    assert snapshot.provider_observations["hithink_special"]["used"] is True


@pytest.mark.asyncio
async def test_shadow_failure_is_audit_only(monkeypatch):
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)

    async def empty_source(*args, **kwargs):
        return []

    async def failed(day, limit):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(discovery, "_ths_hot_reason", empty_source)
    monkeypatch.setattr(discovery, "_ths_hot_list", empty_source)
    monkeypatch.setattr(discovery, "_eastmoney_hot_rank", empty_source)
    monkeypatch.setattr(discovery_module.settings, "HITHINK_SPECIAL_MODE", "shadow")
    monkeypatch.setattr(discovery_module, "fetch_hithink_special", failed)

    snapshot = await discovery.discover("2026-09-11", limit=1)

    assert snapshot.provider_observations["hithink_special"] == {
        "status": "failed",
        "mode": "shadow",
        "used": False,
        "error_type": "RuntimeError",
    }
    assert not any("provider unavailable" in error for error in snapshot.errors)
