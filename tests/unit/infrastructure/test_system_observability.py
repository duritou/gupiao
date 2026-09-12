import json
import urllib.request
from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.ai_os.task_executor import TaskExecution, TaskStatus
from src.infrastructure.market_data.source_manager import (
    DataProvenance,
    SourceManager,
)
from src.infrastructure.storage.market_database import MarketDatabase


def test_task_trigger_source_round_trips_through_database(tmp_path):
    database = MarketDatabase(tmp_path / "observability.db")
    execution = TaskExecution(
        task_name="run_scanner",
        phase="pre_market",
        status=TaskStatus.SUCCESS,
        trigger_source="manual_api",
        started_at="2026-08-16T10:00:00",
        completed_at="2026-08-16T10:00:01",
        duration_seconds=1,
        output={"status": "ok"},
    )

    database.save_task_execution(execution.to_dict())
    restored = database.get_task_executions(limit=1)[0]

    assert restored["trigger_source"] == "manual_api"
    assert restored["output"]["status"] == "ok"


def test_successful_task_execution_key_is_idempotent(tmp_path):
    database = MarketDatabase(tmp_path / "task-idempotency.db")
    first = TaskExecution(
        task_name="run_scanner",
        phase="pre_market",
        status=TaskStatus.SUCCESS,
        output={"execution_key": "2026-09-01:run_scanner:test-version"},
    )
    second = TaskExecution(
        task_name="run_scanner",
        phase="pre_market",
        status=TaskStatus.SUCCESS,
        output={"execution_key": "2026-09-01:run_scanner:test-version"},
    )

    database.save_task_execution(first.to_dict())
    database.save_task_execution(second.to_dict())

    rows = database.get_task_executions(limit=10)
    assert len(rows) == 1
    assert rows[0]["execution_key"] == "2026-09-01:run_scanner:test-version"


def test_same_day_tradingagents_result_can_be_reused(tmp_path):
    database = MarketDatabase(tmp_path / "deep-cache.db")
    database.save_strategy_decision({
        "date": "2026-08-16",
        "stock_code": "600667.SH",
        "technical_score": 70,
        "deep_rating": "Underweight",
        "direction": "sell",
        "deep_analysis": "risk exceeds reward",
        "deep_analysis_available": True,
        "deep_provider": "deepseek",
        "deep_model": "deepseek-v4-flash",
        "deep_runtime": "isolated_tradingagents_venv",
    })

    cached = database.get_cached_deep_analyses(
        "2026-08-16", ["600667.SH"]
    )

    assert database.count_cached_deep_analyses("2026-08-16") == 1
    assert database.count_daily_deep_attempts("2026-08-16") == 1
    assert cached["600667.SH"]["cached"] is True
    assert cached["600667.SH"]["score"] == 35.0


def test_latest_market_breadth_uses_only_latest_trading_day(tmp_path):
    database = MarketDatabase(tmp_path / "breadth.db")
    with database._get_conn() as conn:
        conn.executemany(
            """INSERT INTO stock_basic(ts_code, name) VALUES (?, ?)""",
            [("000001.SZ", "A"), ("000002.SZ", "B"), ("000003.SZ", "C")],
        )
        conn.executemany(
            """INSERT INTO market_daily(
                   ts_code, trade_date, change_pct, amount
               ) VALUES (?, ?, ?, ?)""",
            [
                ("000001.SZ", "2026-08-20", -1.0, 100),
                ("000001.SZ", "2026-08-21", 10.0, 1_000_000_000_000),
                ("000002.SZ", "2026-08-21", -10.0, 500_000_000_000),
                ("000003.SZ", "2026-08-21", 0.0, 0),
                ("000001.SZ", "2026-08-22", 2.0, 1),
            ],
        )

    result = database.get_latest_market_breadth()

    assert result == {
        "data_date": "2026-08-21",
        "covered_stocks": 3,
        "expected_stocks": 3,
        "coverage_ratio": 1.0,
        "up": 1,
        "down": 1,
        "flat": 1,
        "limit_up": 1,
        "limit_down": 1,
        "total_volume": 1.5,
    }

    stats = database.get_stats()
    assert stats["latest_data_date"] == "2026-08-21"
    assert stats["latest_any_data_date"] == "2026-08-22"


def test_interrupted_market_sync_resumes_only_missing_codes(tmp_path):
    database = MarketDatabase(tmp_path / "resume-sync.db")
    with database._get_conn() as conn:
        conn.execute(
            """INSERT INTO market_daily(ts_code, trade_date, change_pct)
               VALUES ('000001.SZ', '2026-08-21', 1.0)"""
        )

    missing = database.get_codes_missing_market_date(
        ["000001.SZ", "000002.SZ", "000003.SZ"], "2026-08-21"
    )

    assert missing == ["000002.SZ", "000003.SZ"]


@pytest.mark.asyncio
async def test_startup_probe_updates_health_and_cache(monkeypatch):
    monkeypatch.setattr(
        "src.infrastructure.market_data.tickflow_provider.is_configured",
        lambda: False,
    )
    manager = SourceManager()
    quote = {
        "stock_code": "600000.SH",
        "price": 10.0,
        "data_date": "2026-08-14",
    }
    provenance = DataProvenance(
        provider="tencent",
        source_name="腾讯财经",
        fetched_at="2026-08-16T10:00:00",
        is_live=True,
        trust_score=0.9,
    )
    manager._sources["tencent"].is_available = True
    manager._sources["tencent"].total_calls = 1
    monkeypatch.setattr(
        manager,
        "_try_tencent_quote",
        AsyncMock(return_value=(quote, provenance)),
    )
    monkeypatch.setattr(
        manager,
        "_try_tushare_quote",
        AsyncMock(return_value=(None, DataProvenance(
            provider="tushare", error_message="test unavailable",
        ))),
    )
    monkeypatch.setattr(
        manager,
        "_try_sina_quote",
        AsyncMock(return_value=(None, DataProvenance(
            provider="sina", error_message="test standby unavailable",
        ))),
    )

    result = await manager.probe_live_sources()
    health = manager.check_health()

    assert result["available"] is True
    assert result["provider"] == "tencent"
    assert len(result["providers"]) == 3
    assert health["live_data_available"] is True
    assert health["last_probe"]["data_date"] == "2026-08-14"


@pytest.mark.asyncio
async def test_startup_probe_falls_back_to_sina(monkeypatch):
    manager = SourceManager()
    # The production environment may have TickFlow configured. Force that
    # primary to fail so this test remains a deterministic Tencent -> Sina
    # fallback check instead of making a live network request.
    monkeypatch.setattr(
        manager,
        "_try_tickflow_quote",
        AsyncMock(return_value=(None, DataProvenance(
            provider="tickflow", error_message="forced test failure",
        ))),
    )
    tencent_failure = DataProvenance(
        provider="tencent", error_message="connection closed",
    )
    sina_quote = {
        "stock_code": "600000.SH",
        "price": 10.1,
        "data_date": "2026-08-21",
    }
    sina_provenance = DataProvenance(
        provider="sina", is_live=True, trust_score=0.85,
    )
    monkeypatch.setattr(
        manager,
        "_try_tencent_quote",
        AsyncMock(return_value=(None, tencent_failure)),
    )
    monkeypatch.setattr(
        manager,
        "_try_tushare_quote",
        AsyncMock(return_value=(None, DataProvenance(
            provider="tushare", error_message="test unavailable",
        ))),
    )
    sina = AsyncMock(return_value=(sina_quote, sina_provenance))
    monkeypatch.setattr(manager, "_try_sina_quote", sina)

    result = await manager.probe_live_sources()

    assert result["available"] is True
    assert result["provider"] == "sina"
    sina.assert_awaited_once_with("600000.SH")


@pytest.mark.asyncio
async def test_sina_quote_adapter_normalizes_real_payload(monkeypatch):
    manager = SourceManager()
    fields = [
        "贵州茅台", "1291.500", "1291.500", "1272.830", "1291.500",
        "1272.010", "1272.830", "1272.900", "3347231", "4278311022.000",
        *(["0"] * 20),
        "2026-08-21", "15:34:58", "00",
    ]
    payload = f'var hq_str_sh600519="{",".join(fields)}";'.encode("gb18030")

    class Response:
        def read(self):
            return payload

    def urlopen(request, *_args):
        assert request.get_header("Referer") == "https://finance.sina.com.cn/"
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    quote, provenance = await manager._try_sina_quote("600519.SH")

    assert provenance.provider == "sina"
    assert quote["stock_name"] == "贵州茅台"
    assert quote["price"] == 1272.83
    assert quote["volume"] == 33472.31
    assert quote["amount"] == 4278311022.0
    assert quote["data_date"] == "2026-08-21"
    assert quote["exchange_timestamp"] == "20260821153458"


@pytest.mark.asyncio
async def test_sina_kline_adapter_labels_unadjusted_data(monkeypatch):
    manager = SourceManager()
    payload = json.dumps([
        {
            "day": "2026-08-20", "open": "1299.800", "high": "1306.880",
            "low": "1291.000", "close": "1291.500", "volume": "2533166",
        },
        {
            "day": "2026-08-21", "open": "1291.500", "high": "1291.500",
            "low": "1272.010", "close": "1272.830", "volume": "3347231",
        },
    ]).encode("utf-8")

    class Response:
        def read(self):
            return payload

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args: Response())

    bars, provenance = await manager._try_sina_kline("600519.SH", 2)

    assert provenance.provider == "sina"
    assert provenance.source_name == "新浪财经 (未复权日K)"
    assert [bar["date"] for bar in bars] == ["2026-08-20", "2026-08-21"]
    assert bars[-1]["volume"] == 33472.31
    assert bars[-1]["change_pct"] == pytest.approx(-1.4456)


@pytest.mark.asyncio
async def test_public_quote_route_uses_sina_before_eastmoney(monkeypatch):
    manager = SourceManager()
    tencent = AsyncMock(return_value=(None, DataProvenance(
        provider="tencent", error_message="connection closed",
    )))
    sina_quote = {"stock_code": "600519.SH", "price": 1272.83}
    sina = AsyncMock(return_value=(sina_quote, DataProvenance(
        provider="sina", is_live=True,
    )))
    eastmoney = AsyncMock()
    monkeypatch.setattr(
        manager,
        "_get_ranked_providers",
        lambda _code, capability: (
            ["tencent", "sina", "akshare"]
            if capability == "realtime_quote"
            else []
        ),
    )
    monkeypatch.setattr(manager, "_try_tencent_quote", tencent)
    monkeypatch.setattr(manager, "_try_sina_quote", sina)
    monkeypatch.setattr(manager, "_try_akshare_quote", eastmoney)

    quote, provenance = await manager.get_realtime_quote("600519.SH")

    assert quote == sina_quote
    assert provenance.provider == "sina"
    tencent.assert_awaited_once()
    sina.assert_awaited_once()
    eastmoney.assert_not_awaited()


@pytest.mark.asyncio
async def test_major_indices_prefer_tencent(monkeypatch):
    manager = SourceManager()
    monkeypatch.setattr(
        manager,
        "_try_tushare_indices",
        AsyncMock(return_value=(None, DataProvenance(
            provider="tushare", error_message="test unavailable",
        ))),
    )
    tencent = AsyncMock(return_value=([{"name": "上证指数"}], DataProvenance(
        provider="tencent", is_live=True,
    )))
    akshare = AsyncMock()
    monkeypatch.setattr(manager, "_try_tencent_indices", tencent)
    monkeypatch.setattr(manager, "_try_akshare_indices", akshare)

    result, provenance = await manager.get_index_quotes()

    assert result == [{"name": "上证指数"}]
    assert provenance.provider == "tencent"
    tencent.assert_awaited_once()
    akshare.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_breadth_prefers_local_completed_close(monkeypatch):
    manager = SourceManager()
    monkeypatch.setattr(
        manager,
        "_try_tushare_breadth",
        AsyncMock(return_value=(None, DataProvenance(
            provider="tushare", error_message="test unavailable",
        ))),
    )
    local = AsyncMock(return_value=({"up": 2, "down": 1}, DataProvenance(
        provider="local_market_db", is_cached=True,
    )))
    akshare = AsyncMock()
    monkeypatch.setattr(manager, "_try_local_market_breadth", local)
    monkeypatch.setattr(manager, "_try_akshare_breadth", akshare)

    result, provenance = await manager.get_market_breadth()

    assert result == {"up": 2, "down": 1}
    assert provenance.provider == "local_market_db"
    local.assert_awaited_once()
    akshare.assert_not_awaited()

    cached, cached_provenance = await manager.get_market_breadth()
    assert cached == result
    assert cached_provenance.is_cached is True
    assert cached_provenance.is_live is False
    assert cached_provenance.data_date == ""


@pytest.mark.asyncio
async def test_intraday_breadth_never_falls_back_to_dated_sources(monkeypatch):
    manager = SourceManager()
    today = date.today().isoformat()
    akshare = AsyncMock(return_value=(
        {"up": 2, "down": 1, "data_date": "2026-09-08"},
        DataProvenance(
            provider="akshare", is_live=True, data_date="2026-09-08",
        ),
    ))
    local = AsyncMock()
    tushare = AsyncMock()
    monkeypatch.setattr(manager, "_try_akshare_breadth", akshare)
    monkeypatch.setattr(manager, "_try_local_market_breadth", local)
    monkeypatch.setattr(manager, "_try_tushare_breadth", tushare)

    result, provenance = await manager.get_intraday_market_breadth()

    assert result is None
    assert provenance.provider == "none"
    assert today not in provenance.error_message
    akshare.assert_awaited_once()
    local.assert_not_awaited()
    tushare.assert_not_awaited()


@pytest.mark.asyncio
async def test_intraday_breadth_accepts_only_live_current_date(monkeypatch):
    manager = SourceManager()
    today = date.today().isoformat()
    akshare = AsyncMock(return_value=(
        {"up": 2, "down": 1, "data_date": today},
        DataProvenance(
            provider="akshare", is_live=True, data_date=today,
        ),
    ))
    monkeypatch.setattr(manager, "_try_akshare_breadth", akshare)

    result, provenance = await manager.get_intraday_market_breadth()

    assert result["data_date"] == today
    assert provenance.provider == "akshare"
    assert provenance.is_live is True


@pytest.mark.asyncio
async def test_intraday_indices_use_live_provider_only(monkeypatch):
    manager = SourceManager()
    tencent = AsyncMock(return_value=(
        [{"name": "上证指数", "value": 3000}],
        DataProvenance(provider="tencent", is_live=True),
    ))
    akshare = AsyncMock()
    monkeypatch.setattr(manager, "_try_tencent_indices", tencent)
    monkeypatch.setattr(manager, "_try_akshare_indices", akshare)

    result, provenance = await manager.get_intraday_index_quotes()

    assert result == [{"name": "上证指数", "value": 3000}]
    assert provenance.provider == "tencent"
    tencent.assert_awaited_once()
    akshare.assert_not_awaited()
