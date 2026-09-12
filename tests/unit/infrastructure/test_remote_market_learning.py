import json
import subprocess

import httpx
import pytest

from src.ai_os.market_learning import learning_adjustment
from src.infrastructure.market_data import provider_resilience
from src.infrastructure.market_data import remote_market_discovery as discovery_module
from src.infrastructure.market_data.provider_resilience import (
    reserve_provider_request,
    reset_provider_resilience_state,
)
from src.infrastructure.market_data.remote_market_discovery import (
    EastmoneyCircuitOpenError,
    RemoteMarketDiscovery,
    normalize_a_share_code,
)
from src.infrastructure.storage.market_database import MarketDatabase


@pytest.fixture(autouse=True)
def _reset_provider_state():
    reset_provider_resilience_state()
    yield
    reset_provider_resilience_state()


@pytest.mark.asyncio
async def test_generic_retry_honours_retry_after_with_jitter(monkeypatch):
    calls = 0
    sleeps = []

    async def temporary_failure(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                request=request,
                headers={"Retry-After": "2"},
            )
        return httpx.Response(200, request=request, content=b"{}")

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(discovery_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(provider_resilience.random, "uniform", lambda low, high: high)
    discovery = RemoteMarketDiscovery(timeout_seconds=1)
    discovery.retry_backoff_seconds = 0.5
    discovery.retry_jitter_seconds = 0.25
    discovery.public_min_interval_seconds = 0
    discovery.public_jitter_seconds = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(temporary_failure)) as client:
        response = await discovery._request_with_retry(client, "GET", "https://example.com")

    assert response.status_code == 200
    assert calls == 2
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_generic_retry_does_not_replay_rate_control_response():
    calls = 0

    async def rate_limited(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request, headers={"Retry-After": "30"})

    discovery = RemoteMarketDiscovery(timeout_seconds=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_limited)) as client:
        response = await discovery._request_with_retry(client, "GET", "https://example.com")

    assert response.status_code == 429
    assert calls == 1


@pytest.mark.asyncio
async def test_transport_failure_does_not_block_alternate_transport():
    async def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("local socket blocked", request=request)

    discovery = RemoteMarketDiscovery(timeout_seconds=1)
    discovery.public_min_interval_seconds = 0
    discovery.public_jitter_seconds = 0
    discovery.retry_backoff_seconds = 0
    discovery.retry_jitter_seconds = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnected)) as client:
        with pytest.raises(httpx.ConnectError):
            await discovery._request_with_retry(
                client,
                "GET",
                "https://qt.gtimg.cn/q=sh600519",
            )

    # The next transport may still reserve the same host; only an explicit
    # provider response or a complete multi-transport failure should trip it.
    reserve_provider_request(
        "qt.gtimg.cn",
        min_interval_seconds=0,
        jitter_seconds=0,
    )


@pytest.mark.asyncio
async def test_fund_flow_uses_curl_after_python_disconnect(monkeypatch):
    async def disconnect(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("server disconnected", request=request)

    payload = json.dumps({
        "data": {"klines": ["09:31,100000,0,0,0,0,0"]}
    }).encode()
    monkeypatch.setattr(
        discovery_module,
        "_curl_get_bytes",
        lambda url, headers, timeout: payload,
    )
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)
    discovery.eastmoney_min_interval_seconds = 0
    discovery.eastmoney_jitter_seconds = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnect)) as client:
        result = await discovery._eastmoney_fund_flow(client, "600667.SH")

    assert result["status"] == "ok"
    assert result["source"] == "eastmoney_intraday_fund_flow"
    assert result["transport"] == "curl"
    assert result["main_net"] == 100000


def test_curl_accepts_valid_json_despite_schannel_close_warning(monkeypatch):
    completed = subprocess.CompletedProcess(
        args=[], returncode=56, stdout=b'{"data":{}}',
        stderr=b"schannel: server closed abruptly",
    )
    monkeypatch.setattr(discovery_module.shutil, "which", lambda name: "curl.exe")
    monkeypatch.setattr(discovery_module.subprocess, "run", lambda *a, **k: completed)

    raw = discovery_module._curl_get_bytes(
        "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
        {},
        10,
    )

    assert raw == b'{"data":{}}'


def test_curl_refuses_non_eastmoney_host():
    with pytest.raises(RuntimeError, match="untrusted host"):
        discovery_module._curl_get_bytes("https://example.com/", {}, 10)


@pytest.mark.asyncio
async def test_eastmoney_rate_control_opens_circuit_without_curl(monkeypatch):
    calls = 0

    async def rate_limited(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request, content=b"rate limited")

    monkeypatch.setattr(
        discovery_module,
        "_curl_get_bytes",
        lambda *args, **kwargs: pytest.fail("curl must not retry HTTP 429"),
    )
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)
    discovery.eastmoney_min_interval_seconds = 0
    discovery.eastmoney_jitter_seconds = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_limited)) as client:
        with pytest.raises(EastmoneyCircuitOpenError, match="rate control"):
            await discovery._eastmoney_get(
                client,
                "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                params={"secid": "1.600667"},
                headers={},
            )
        second_discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)
        second_discovery.eastmoney_min_interval_seconds = 0
        second_discovery.eastmoney_jitter_seconds = 0
        with pytest.raises(EastmoneyCircuitOpenError, match="cooldown active"):
            await second_discovery._eastmoney_get(
                client,
                "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                params={"secid": "1.600667"},
                headers={},
            )

    assert calls == 1


@pytest.mark.asyncio
async def test_fund_flow_disconnect_does_not_double_hit_daily_endpoint(monkeypatch):
    requested_hosts = []

    async def disconnect(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        raise httpx.RemoteProtocolError("server disconnected", request=request)

    def curl_disconnect(*args, **kwargs):
        raise RuntimeError("disconnected")

    monkeypatch.setattr(discovery_module, "_curl_get_bytes", curl_disconnect)
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)
    discovery.eastmoney_min_interval_seconds = 0
    discovery.eastmoney_jitter_seconds = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnect)) as client:
        with pytest.raises(EastmoneyCircuitOpenError, match="transports failed"):
            await discovery._eastmoney_fund_flow(client, "600667.SH")

    assert requested_hosts == ["push2.eastmoney.com"]


@pytest.mark.asyncio
async def test_discovery_skips_eastmoney_hot_rank_when_ths_heat_is_available(
    monkeypatch,
):
    discovery = RemoteMarketDiscovery(timeout_seconds=1, flow_limit=1)

    async def hot_reason(client, day):
        return [{"rank": 1, "code": "600667", "name": "样本", "reason": "topic"}]

    async def hot_list(client):
        return [{"rank": 1, "code": "600667", "name": "样本", "concepts": []}]

    async def eastmoney_hot_rank(client, top):
        pytest.fail("Eastmoney hot rank should be fallback-only")

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

    monkeypatch.setattr(discovery, "_ths_hot_reason", hot_reason)
    monkeypatch.setattr(discovery, "_ths_hot_list", hot_list)
    monkeypatch.setattr(discovery, "_eastmoney_hot_rank", eastmoney_hot_rank)
    monkeypatch.setattr(discovery, "_tencent_quotes", quotes)
    monkeypatch.setattr(discovery, "_eastmoney_fund_flow", flow)

    snapshot = await discovery.discover("2026-08-22", limit=1)

    assert snapshot.remote_available is True
    assert snapshot.source_counts["eastmoney_hot_rank"] == 0


def test_normalize_a_share_code_and_score_remote_candidate():
    assert normalize_a_share_code("SZ000001") == "000001.SZ"
    assert normalize_a_share_code("600519.SH") == "600519.SH"
    assert normalize_a_share_code("sh.000300") == ""

    candidate = RemoteMarketDiscovery._score_candidate(
        {
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
            "sources": ["ths_hot_reason", "ths_hot_list"],
            "source_ranks": {"ths_hot_reason": 2, "ths_hot_list": 5},
            "reasons": ["银行"],
            "concepts": ["金融"],
        },
        {
            "name": "平安银行",
            "price": 12.0,
            "change_pct": 3.0,
            "amount_wan": 100_000,
            "source": "tencent_live_quote",
        },
        {
            "status": "ok",
            "main_net": 100_000_000,
            "source": "eastmoney_intraday_fund_flow",
        },
    )

    assert candidate["discovery_score"] > 70
    assert candidate["fund_flow"]["main_net_ratio"] == 0.1
    assert "tencent_live_quote" in candidate["data_sources"]


def _decision(day: str, code: str, sources: list[str]) -> dict:
    return {
        "date": day,
        "stock_code": code,
        "stock_name": code,
        "ai_score": 70,
        "direction": "buy",
        "confidence": 0.7,
        "recommendation": "买入",
        "evidence": json.dumps({
            "market_discovery": {
                "sources": sources,
                "discovery_score": 80,
            }
        }),
    }


def test_real_observations_drive_bounded_symbol_and_source_learning(tmp_path):
    database = MarketDatabase(tmp_path / "learning.db")
    source = "ths_hot_reason"

    first = _decision("2026-08-01", "000001.SZ", [source])
    first["id"] = database.save_decision(first)
    second = _decision("2026-08-02", "000001.SZ", [source])
    second["id"] = database.save_decision(second)
    third = _decision("2026-08-03", "000002.SZ", [source])
    third["id"] = database.save_decision(third)

    assert database.save_market_learning_observation(
        first, "2026-08-04", 1, 0.03, 0.01, 0.02, True
    )
    assert not database.save_market_learning_observation(
        first, "2026-08-04", 1, 0.03, 0.01, 0.02, True
    )
    assert database.save_market_learning_observation(
        second, "2026-08-05", 1, 0.02, 0.01, 0.01, True
    )
    assert database.save_market_learning_observation(
        third, "2026-08-06", 1, -0.02, 0.0, -0.02, False
    )

    profile = database.get_market_learning_profile(horizon_days=1)
    learned = learning_adjustment(profile, "000001.SZ", [source])

    assert profile["total_observations"] == 3
    assert profile["decisive_observations"] == 3
    assert profile["by_symbol"]["000001.SZ"]["win_rate"] == 1.0
    assert profile["by_source"][source]["observations"] == 3
    assert learned["symbol_adjustment"] == 2.0
    assert learned["source_adjustment"] == 3.0
    assert learned["score_adjustment"] == 5.0


def test_neutral_observations_are_audited_but_not_learned(tmp_path):
    database = MarketDatabase(tmp_path / "neutral.db")
    decision = _decision("2026-08-01", "000001.SZ", ["ths_hot_list"])
    decision["direction"] = "neutral"
    decision["id"] = database.save_decision(decision)
    database.save_market_learning_observation(
        decision, "2026-08-04", 1, 0.0, 0.0, 0.0, True
    )

    profile = database.get_market_learning_profile(horizon_days=1)
    assert profile["total_observations"] == 1
    assert profile["decisive_observations"] == 0
    assert profile["by_symbol"] == {}


def test_neutral_outcomes_do_not_become_directional_accuracy(tmp_path):
    database = MarketDatabase(tmp_path / "accuracy.db")
    neutral = _decision("2026-08-01", "000001.SZ", [])
    neutral["direction"] = "neutral"
    neutral_id = database.save_decision(neutral)
    database.save_strategy_decision(neutral, neutral_id)

    assert database.update_decision_outcome(neutral_id, False, 0.02)
    stats = database.get_decision_stats()
    performance = database.get_strategy_performance()

    assert stats["verified_decisions"] == 1
    assert stats["neutral_verified_decisions"] == 1
    assert stats["decisive_verified_decisions"] == 0
    assert stats["accuracy_available"] is False
    assert stats["accuracy_status"] == "insufficient_samples"
    assert performance["buckets"] == []


def test_learning_queues_only_directional_recommendations(tmp_path):
    database = MarketDatabase(tmp_path / "queues.db")
    neutral = _decision("2026-08-01", "000001.SZ", [])
    neutral["direction"] = "neutral"
    database.save_decision(neutral)
    buy = _decision("2026-08-01", "000002.SZ", [])
    buy_id = database.save_decision(buy)

    daily = database.get_pending_market_learning_decisions()
    formal = database.get_pending_outcome_decisions(min_calendar_days=0)

    assert [item["id"] for item in daily] == [buy_id]
    assert [item["id"] for item in formal] == [buy_id]


def test_paper_strategy_buys_only_buy_direction_and_keeps_cash_reserve(
    tmp_path, monkeypatch
):
    database = MarketDatabase(tmp_path / "paper.db")
    quotes = {
        "000001.SZ": {"price": 10.0, "change_pct": 1.0},
        "000002.SZ": {"price": 10.0, "change_pct": 1.0},
        "000003.SZ": {"price": 10.0, "change_pct": 1.0},
        "000004.SZ": {"price": 10.0, "change_pct": 1.0},
        "000005.SZ": {"price": 10.0, "change_pct": 1.0},
        "000006.SZ": {"price": 10.0, "change_pct": 1.0},
    }
    monkeypatch.setattr(database, "get_latest_quote", lambda code: quotes.get(code))
    decisions = [
        {
            "stock_code": "000001.SZ", "stock_name": "neutral",
            "ai_score": 90, "direction": "neutral",
        },
        *[
            {
                "stock_code": f"00000{index}.SZ", "stock_name": f"buy-{index}",
                "ai_score": 80 - index, "direction": "buy",
                "deep_analysis_available": True, "deep_rating": "Overweight",
            }
            for index in range(2, 7)
        ],
    ]

    result = database.run_paper_strategy(
        decisions, "2026-08-11", 100_000, strict_real_data=False
    )

    assert all(action["stock_code"] != "000001.SZ" for action in result["actions"])
    assert result["cash"] >= 75_000
    assert all(action["shares"] == 400 for action in result["actions"])


def test_paper_strategy_restores_cash_reserve_from_eligible_holding(
    tmp_path, monkeypatch
):
    database = MarketDatabase(tmp_path / "reserve.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute("UPDATE paper_account SET cash=5000 WHERE id=1")
        connection.execute(
            """INSERT INTO paper_position
               (stock_code, stock_name, shares, avg_cost, updated_at,
                entry_date, eligible_sell_date)
               VALUES ('000001.SZ', 'reserve', 10000, 10, '', '2026-08-01', '2026-08-01')"""
        )
    monkeypatch.setattr(
        database,
        "get_latest_quote",
        lambda code: {"price": 10.0, "change_pct": 0.0},
    )

    result = database.run_paper_strategy(
        [{
            "stock_code": "000001.SZ", "stock_name": "reserve",
            "ai_score": 50, "direction": "neutral",
        }],
        "2026-08-11",
        100_000,
        strict_real_data=False,
    )

    portfolio = database.get_paper_portfolio()
    assert result["cash"] >= 83_000
    assert result["actions"][0]["reason"] == "rebalance_max_position=20%"
    assert portfolio["positions"][0]["shares"] == 2100
