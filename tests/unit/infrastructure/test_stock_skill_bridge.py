import json
from urllib.error import HTTPError

import pytest

from src.infrastructure.market_data import stock_skill_bridge
from src.infrastructure.market_data.provider_resilience import (
    reset_provider_resilience_state,
)
from src.infrastructure.market_data.stock_skill_bridge import (
    StockSkillFetchError,
    normalize_stock_code,
    parse_tencent_quotes,
    parse_ths_hot_reason,
)


@pytest.fixture(autouse=True)
def _reset_provider_state():
    reset_provider_resilience_state()
    yield
    reset_provider_resilience_state()


def test_stock_skill_rate_control_does_not_amplify_with_curl(monkeypatch):
    def rate_limited(*args, **kwargs):
        raise HTTPError(
            "https://qt.gtimg.cn/q=sh600487",
            429,
            "rate limited",
            {"Retry-After": "60"},
            None,
        )

    monkeypatch.setattr(stock_skill_bridge, "urlopen", rate_limited)
    monkeypatch.setattr(
        stock_skill_bridge,
        "_curl_get",
        lambda *args, **kwargs: pytest.fail("curl must not replay HTTP 429"),
    )

    with pytest.raises(StockSkillFetchError, match="rate control"):
        stock_skill_bridge._fetch_tencent_quotes_sync(["600487.SH"], 1)


@pytest.mark.asyncio
async def test_remote_execution_uses_stock_skill_quote_fallback(monkeypatch):
    from src.infrastructure.market_data.remote_market_discovery import (
        RemoteMarketDiscovery,
    )

    discovery = RemoteMarketDiscovery(stock_skill_enabled=True)

    async def primary_failure(client, codes):
        raise RuntimeError("simulated Tencent HTTPX failure")

    async def fallback_quotes(codes, *, timeout_seconds):
        return {"600487.SH": {
            "price": 65.06,
            "source": "stock_skill_tencent_live_quote",
        }}

    monkeypatch.setattr(discovery, "_tencent_quotes", primary_failure)
    monkeypatch.setattr(stock_skill_bridge, "fetch_tencent_quotes", fallback_quotes)

    quotes = await discovery.fetch_live_quotes(["600487.SH"])

    assert quotes["600487.SH"]["source"] == "stock_skill_tencent_live_quote"


@pytest.mark.asyncio
async def test_large_quote_fallback_stays_batched(monkeypatch):
    from src.infrastructure.market_data.remote_market_discovery import (
        RemoteMarketDiscovery,
    )

    discovery = RemoteMarketDiscovery(stock_skill_enabled=True)
    fallback_batch_sizes = []

    async def primary_empty(client, codes):
        return {}

    async def fallback_quotes(codes, *, timeout_seconds):
        fallback_batch_sizes.append(len(codes))
        return {
            code: {"price": 1.0, "source": "stock_skill_tencent_live_quote"}
            for code in codes
        }

    monkeypatch.setattr(discovery, "_tencent_quotes", primary_empty)
    monkeypatch.setattr(stock_skill_bridge, "fetch_tencent_quotes", fallback_quotes)

    codes = [f"000{index:03d}.SZ" for index in range(1, 62)]
    quotes = await discovery.fetch_live_quotes(codes)

    assert fallback_batch_sizes == [60, 1]
    assert len(quotes) == 61


def test_stock_skill_tencent_parser_keeps_short_term_fields():
    values = [""] * 53
    values[1] = "亨通光电"
    values[2] = "600487"
    values[3] = "65.06"
    values[4] = "64.00"
    values[5] = "64.20"
    values[7] = "1200"
    values[8] = "800"
    values[30] = "20260817103520"
    values[31] = "1.06"
    values[32] = "1.66"
    values[33] = "65.50"
    values[34] = "63.20"
    values[37] = "1000000"
    values[38] = "8.10"
    values[39] = "25.4"
    values[43] = "3.59"
    values[44] = "1500"
    values[45] = "1000"
    values[46] = "2.1"
    values[47] = "70.40"
    values[48] = "57.60"
    values[49] = "1.8"
    values[52] = "26.0"

    quotes = parse_tencent_quotes(
        f'v_sh600487="{"~".join(values)}";',
        fetched_at="2026-08-17T02:35:20+00:00",
    )
    quote = quotes["600487.SH"]

    assert quote["name"] == "亨通光电"
    assert quote["price"] == 65.06
    assert quote["amplitude_pct"] == 3.59
    assert quote["limit_up"] == 70.40
    assert quote["float_mcap_yi"] == 1000
    assert quote["source"] == "stock_skill_tencent_live_quote"
    assert quote["data_date"] == "2026-08-17"
    assert quote["active_volume_ratio"] == 0.2


def test_stock_skill_ths_parser_keeps_recommendation_evidence():
    payload = {
        "errocode": 0,
        "data": [{
            "code": "300017",
            "name": "网宿科技",
            "reason": "算力租赁",
            "zhangfu": "5.2",
            "close": "17.57",
            "huanshou": "12.3",
            "chengjiaoe": "900000",
            "ddejingliang": "12000000",
        }],
    }

    rows = parse_ths_hot_reason(json.dumps(payload, ensure_ascii=False))

    assert rows == [{
        "rank": 1,
        "code": "300017.SZ",
        "name": "网宿科技",
        "reason": "算力租赁",
        "change_pct": 5.2,
        "price": 17.57,
        "turnover_pct": 12.3,
        "amount": 900000.0,
        "main_net": 12000000.0,
    }]


def test_normalize_stock_code_rejects_non_a_share_code():
    assert normalize_stock_code("600487.SH") == "600487.SH"
    assert normalize_stock_code("SZ300017") == "300017.SZ"
    assert normalize_stock_code("AAPL") == ""


@pytest.mark.parametrize("bad_payload", ["", "not-json"])
def test_stock_skill_parser_rejects_invalid_payload(bad_payload):
    with pytest.raises(StockSkillFetchError):
        parse_ths_hot_reason(bad_payload)
