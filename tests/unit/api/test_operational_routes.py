from __future__ import annotations

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest

from src.ai_os.scheduler import SchedulePhase, get_schedule_for_phase
from src.ai_os.task_executor import TaskExecutor
from src.api.routes import (
    alerts_routes,
    brief_utils,
    decision_routes,
    market_routes,
    trust_routes,
)
from src.infrastructure.market_data.real_data_provider import RealDataProvider
from src.infrastructure.market_data.source_manager import DataProvenance
from src.infrastructure.market_data.news_freshness import apply_news_freshness
from src.infrastructure.market_data.vibe_provider import VibeResearchProvider
from src.user_model import journal_loader
from src.user_model.engine import UserModelEngine


class FakeOperationalDB:
    def __init__(self):
        today = date.today().isoformat()
        self.requested_date = ""
        self.decisions = [
            {
                "id": 1,
                "decision_date": today,
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "ai_score": 72.0,
                "direction": "buy",
                "confidence": 0.8,
                "recommendation": "buy",
                "fusion_score": 72.0,
                "macd_score": 75.0,
                "rsi_score": 55.0,
                "kdj_score": 60.0,
                "ma_score": 70.0,
                "volume_score": 65.0,
                "buy_signals": 4,
                "sell_signals": 0,
                "evidence": "real test evidence",
                "created_at": f"{today}T09:35:00+08:00",
                "outcome_known": 1,
                "was_correct": 1,
                "actual_return": 0.05,
                "deep_rating": "",
                "deep_analysis_available": True,
                "execution_evidence_complete": True,
                "score_guard_reasons": [],
                "publication_blocked": False,
                "decision_status": "buy_candidate",
            },
            {
                "id": 2,
                "decision_date": today,
                "stock_code": "000002.SZ",
                "stock_name": "万科A",
                "ai_score": 45.0,
                "direction": "sell",
                "confidence": 0.7,
                "recommendation": "avoid",
                "fusion_score": 45.0,
                "macd_score": 40.0,
                "rsi_score": 50.0,
                "kdj_score": 45.0,
                "ma_score": 35.0,
                "volume_score": 50.0,
                "buy_signals": 0,
                "sell_signals": 3,
                "evidence": "real test evidence",
                "created_at": f"{today}T09:36:00+08:00",
                "outcome_known": 1,
                "was_correct": 0,
                "actual_return": -0.02,
                "deep_rating": "",
                "deep_analysis_available": True,
                "execution_evidence_complete": True,
                "score_guard_reasons": [],
                "publication_blocked": False,
                "decision_status": "sell_candidate",
            },
        ]

    def get_decisions_for_date(self, requested_date, limit=500):
        self.requested_date = requested_date
        return list(self.decisions)[:limit]

    def get_recent_decisions(self, limit=50):
        return list(self.decisions)[:limit]

    def get_decision_stats(self):
        return {
            "total_decisions": 2,
            "decisive_decisions": 2,
            "neutral_decisions": 0,
            "verified_decisions": 2,
            "correct_decisions": 1,
            "decisive_verified_decisions": 2,
            "decisive_correct_decisions": 1,
            "neutral_verified_decisions": 0,
            "accuracy_available": True,
            "accuracy_status": "available",
            "accuracy": 0.5,
            "all_verified_outcome_match_rate": 0.5,
            "by_direction": [],
        }

    def get_strategy_performance(self):
        return {"buckets": []}

    def get_market_learning_profile(self, horizon_days=1):
        return {"total_observations": 2, "decisive_observations": 2}

    def get_paper_portfolio(self):
        return {"total_pl_pct": 3.2}

    def get_strategy_context(self, limit=5000):
        return [
            {"strategy_version": "2.0", "outcome_status": "correct", "effective_direction": "buy"},
            {"strategy_version": "2.0", "outcome_status": "wrong", "effective_direction": "sell"},
        ]

    def get_paper_trades(self, limit=500):
        return [{
            "decision_id": 1,
            "action": "BUY",
            "price": 12.5,
            "created_at": f"{date.today().isoformat()}T09:37:00+08:00",
        }]


def test_scheduler_phase_mapping_uses_declared_phases():
    assert [task.name for task in get_schedule_for_phase(SchedulePhase.MIDDAY)] == [
        "midday_review"
    ]
    assert [task.name for task in get_schedule_for_phase(SchedulePhase.AFTERNOON)] == [
        "afternoon_scan"
    ]
    assert [
        task.name for task in get_schedule_for_phase(SchedulePhase.LATE_AFTERNOON)
    ] == ["late_afternoon_review"]


@pytest.mark.asyncio
async def test_today_routes_only_query_today(monkeypatch):
    fake = FakeOperationalDB()
    import src.infrastructure.storage.market_database as storage_module

    monkeypatch.setattr(storage_module, "market_db", fake)
    decisions = await decision_routes.daily_decisions()
    alerts = await alerts_routes.get_today_alerts()

    assert fake.requested_date == date.today().isoformat()
    assert decisions["date"] == date.today().isoformat()
    assert decisions["total_items"] == 2
    assert alerts["date"] == date.today().isoformat()
    assert all(item["status"] == "new" for item in alerts["alerts"])


def test_alert_focus_is_ranked_and_bounded(monkeypatch):
    fake = FakeOperationalDB()
    fake.decisions = [
        {
            **fake.decisions[0],
            "id": index,
            "stock_code": f"{index:06d}.SZ",
            "ai_score": 65.0 + index,
        }
        for index in range(1, 12)
    ]
    import src.infrastructure.storage.market_database as storage_module

    monkeypatch.setattr(storage_module, "market_db", fake)
    alerts = alerts_routes._build_alerts_from_journal(date.today().isoformat())
    focus = alerts_routes._build_today_focus(alerts)

    assert alerts[0]["score"] == 76.0
    assert len(focus["important"]) == 8


def test_boll_signal_is_computed_from_real_closes():
    provider = RealDataProvider()

    assert provider._compute_boll_signal([float(i) for i in range(1, 21)]) <= 40
    assert provider._compute_boll_signal([float(i) for i in range(20, 0, -1)]) >= 60


@pytest.mark.asyncio
async def test_trust_endpoints_compute_live_metrics(monkeypatch):
    fake = FakeOperationalDB()
    monkeypatch.setattr(trust_routes, "market_db", fake)

    strategies = await trust_routes.strategies()
    ranges = await trust_routes.score_ranges()
    resume = await trust_routes.resume()
    versions = await trust_routes.model_evolution()

    assert strategies["status"] == "live"
    assert sum(item["total"] for item in strategies["strategies"]) == 2
    assert ranges["status"] == "live"
    assert sum(item["total"] for item in ranges["ranges"]) == 2
    assert ranges["verified_decisions"] == 2
    assert resume["overall_accuracy"] == 0.5
    assert resume["correct_count"] == 1
    assert versions["versions"][0]["accuracy"] == 0.5


@pytest.mark.asyncio
async def test_trust_pages_report_waiting_instead_of_zero_accuracy(monkeypatch):
    fake = FakeOperationalDB()
    for decision in fake.decisions:
        decision["outcome_known"] = 0
        decision["was_correct"] = None
    fake.get_strategy_context = lambda limit=5000: [{
        "strategy_version": "2.0",
        "outcome_status": "pending",
        "effective_direction": "buy",
    }]
    monkeypatch.setattr(trust_routes, "market_db", fake)

    track = await trust_routes.track_record(30)
    ranges = await trust_routes.score_ranges()
    versions = await trust_routes.model_evolution()
    monthly = await trust_routes.monthly()

    assert track["status"] == "collecting_samples"
    assert track["accuracy_available"] is False
    assert track["avg_return_pct"] == 0
    assert ranges["ranges"] == []
    assert versions["status"] == "collecting_samples"
    assert versions["versions"][0]["accuracy_available"] is False
    assert monthly["status"] == "collecting_samples"
    assert monthly["monthly"][0]["accuracy_available"] is False


def test_user_model_loads_persisted_paper_actions(monkeypatch):
    fake = FakeOperationalDB()
    engine = UserModelEngine()
    monkeypatch.setattr(journal_loader, "market_db", fake)
    monkeypatch.setattr(journal_loader, "get_user_model_engine", lambda: engine)

    loaded, metadata = journal_loader.load_user_model_from_journal()
    profile = loaded.generate_profile().to_dict()

    assert metadata["decision_count"] == 2
    assert metadata["paper_action_count"] == 1
    assert profile["total_decisions_analyzed"] == 2
    assert profile["ai_alignment"]["overall_follow_rate"] == 0.5


def test_user_model_accepts_mixed_legacy_timestamp_formats(monkeypatch):
    fake = FakeOperationalDB()
    fake.decisions[0]["created_at"] = f"{date.today().isoformat()}T09:35:00"
    engine = UserModelEngine()
    monkeypatch.setattr(journal_loader, "market_db", fake)
    monkeypatch.setattr(journal_loader, "get_user_model_engine", lambda: engine)

    loaded, _ = journal_loader.load_user_model_from_journal()

    assert loaded.generate_profile().data_period_days >= 0


def test_neutral_observation_is_not_a_verified_user_model_call(monkeypatch):
    fake = FakeOperationalDB()
    fake.decisions.append({
        **fake.decisions[0],
        "id": 3,
        "stock_code": "000003.SZ",
        "direction": "neutral",
        "outcome_known": 1,
        "was_correct": 0,
    })
    engine = UserModelEngine()
    monkeypatch.setattr(journal_loader, "market_db", fake)
    monkeypatch.setattr(journal_loader, "get_user_model_engine", lambda: engine)

    loaded, metadata = journal_loader.load_user_model_from_journal()

    assert metadata["observed_count"] == 3
    assert metadata["verified_count"] == 2
    assert metadata["neutral_observed_count"] == 1
    assert loaded._snapshots[-1].final_verdict == "pending"


def test_stale_news_is_not_reported_available():
    data = apply_news_freshness({
        "news": [{"title": "old"}],
        "updated_at": "2020-01-01 00:00",
        "_meta": {"available": True},
    })
    assert data["_meta"]["available"] is False
    assert data["_meta"]["stale"] is True


def test_empty_news_is_not_reported_available_even_with_fresh_timestamp():
    data = apply_news_freshness({
        "news": [],
        "updated_at": datetime.now().isoformat(timespec="minutes"),
        "_meta": {"available": True},
    })
    assert data["_meta"]["available"] is False
    assert "没有返回有效内容" in data["_meta"]["error"]


def test_news_radar_prioritizes_a_share_relevance_before_generic_ai():
    result = VibeResearchProvider._radar_result({
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "industries": [
            {
                "key": "ai",
                "name": "AI",
                "items": [{"title": "Generic model update", "ts": 200}],
            },
            {
                "key": "semi",
                "name": "半导体",
                "items": [{"title": "A股芯片制造扩产", "ts": 100}],
            },
        ],
    }, {"available": True})

    assert result["news"][0]["title"] == "A股芯片制造扩产"
    assert result["_meta"]["ranking"] == "a_share_relevance_then_recency"


@pytest.mark.asyncio
async def test_market_overview_collapses_concurrent_requests(monkeypatch):
    calls = {"indices": 0, "breadth": 0}

    async def indices():
        calls["indices"] += 1
        await asyncio.sleep(0)
        return [], DataProvenance(provider="test", is_live=True)

    async def breadth():
        calls["breadth"] += 1
        await asyncio.sleep(0)
        return {"up": 1, "down": 1}, DataProvenance(
            provider="test", is_live=True
        )

    monkeypatch.setattr(market_routes, "_overview_cache", None)
    monkeypatch.setattr(market_routes.source_manager, "get_index_quotes", indices)
    monkeypatch.setattr(market_routes.source_manager, "get_market_breadth", breadth)

    first, second = await asyncio.gather(
        market_routes.market_overview(), market_routes.market_overview()
    )

    assert first == second
    assert calls == {"indices": 1, "breadth": 1}


@pytest.mark.asyncio
async def test_brief_reuses_inflight_build(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def build(force_refresh=False):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"date": "2026-08-21", "cached": False}

    monkeypatch.setattr(brief_utils, "_brief_cache", None)
    monkeypatch.setattr(brief_utils, "_brief_refresh_task", None)
    monkeypatch.setattr(brief_utils, "_build_real_brief_uncached", build)

    first = asyncio.create_task(brief_utils.build_real_brief())
    await started.wait()
    second = asyncio.create_task(brief_utils.build_real_brief())
    await asyncio.sleep(0)
    release.set()

    assert await first == await second
    assert calls == 1


@pytest.mark.asyncio
async def test_brief_carries_market_regime_from_overview(monkeypatch):
    from src.infrastructure.market_data import eastmoney_emotion
    from src.infrastructure.storage import market_database

    regime = {
        "state": "lean_strong",
        "score": 68,
        "confidence": 0.84,
        "as_of_date": "2026-08-30",
        "components": {"profit": 70},
        "reasons": ["breadth supports trend"],
        "source": "local_market_snapshot",
        "lookahead_safe": True,
    }

    async def overview():
        return {
            "market_breadth": {"up": 3, "down": 1, "flat": 0},
            "total_volume": 100,
            "market_regime": regime,
            "_data": {"available": True},
        }

    class FakeVibe:
        async def get_sentiment_lite(self):
            return {}

        async def get_top_volume_stocks(self, limit=20):
            return []

    monkeypatch.setattr(brief_utils, "_brief_cache", None)
    monkeypatch.setattr(brief_utils, "_brief_refresh_task", None)
    monkeypatch.setattr(market_database.market_db, "get_latest_pipeline_run_audit", lambda: {})
    monkeypatch.setattr(
        market_database.market_db,
        "get_decisions_for_date",
        lambda decision_date, limit=5000: [],
    )
    monkeypatch.setattr(brief_utils, "get_vibe_provider", lambda: FakeVibe())
    monkeypatch.setattr(
        eastmoney_emotion,
        "fetch_limit_up_sentiment",
        AsyncMock(return_value={"data": {}, "_meta": {"available": False}}),
    )
    monkeypatch.setattr(market_routes, "market_overview", overview)

    result = await brief_utils.build_real_brief(force_refresh=True)

    assert result["market_regime"] == regime
    assert result["market"]["market_regime"] == regime
    assert result["data_status"]["components"]["market_regime"] is True


@pytest.mark.asyncio
async def test_morning_brief_notification_includes_market_regime(monkeypatch):
    from src.api.routes import brief_utils
    from src.infrastructure.storage import market_database

    async def fake_brief(force_refresh=False):
        return {
            "date": "2026-08-30",
            "generated_at": "2026-08-30T09:00:00",
            "market_summary": "3 up / 1 down",
            "market_regime": {
                "state": "lean_strong",
                "score": 68,
                "as_of_date": "2026-08-30",
            },
            "top_opportunities": [],
            "considered_stocks": [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "recommendation": "HOLD",
                    "ranking_score": 71.5,
                    "reference_price": 12.34,
                    "reference_price_date": "2026-08-29",
                    "analysis": "资金流改善，但仍需观察开盘量价确认。",
                }
            ],
            "data_status": {"degraded": False},
        }

    monkeypatch.setattr(brief_utils, "build_real_brief", fake_brief)
    monkeypatch.setattr(
        market_database.market_db,
        "get_paper_portfolio",
        lambda: {
            "total_value": 100000.0,
            "cash": 100000.0,
            "total_pl": 0.0,
            "trades": [],
        },
    )
    notify = AsyncMock(return_value=True)
    executor = TaskExecutor(persist=False)
    monkeypatch.setattr(executor, "_notify_wechat", notify)

    result = await executor._generate_morning_brief(None)

    assert result["status"] == "generated"
    assert result["considered_count"] == 1
    content = notify.await_args.args[1]
    assert "market_regime: lean_strong (68/100) @ 2026-08-30" in content
    assert "平安银行（000001.SZ）｜HOLD｜排名分 71.5" in content
    assert "参考价：12.34元（2026-08-29）" in content
    assert "资金流改善，但仍需观察开盘量价确认。" in content
    assert "不是限价委托或买入指令" in content
    assert "不下真实订单" in content


@pytest.mark.asyncio
async def test_real_brief_exposes_considered_stock_analysis_and_reference_price(monkeypatch):
    from src.infrastructure.market_data import eastmoney_emotion
    from src.infrastructure.storage import market_database

    async def overview():
        return {"market_breadth": {"up": 1, "down": 1}, "_data": {"available": True}}

    class FakeVibe:
        async def get_sentiment_lite(self):
            return {}

        async def get_top_volume_stocks(self, limit=20):
            return []

    decision = {
        "stock_code": "000001.SZ",
        "stock_name": "平安银行",
        "decision_date": date.today().isoformat(),
        "ai_score": 58,
        "ranking_score": 73.2,
        "direction": "neutral",
        "decision_status": "hold",
        "recommendation": "HOLD",
        "deep_analysis": "估值尚可，等待量价确认。",
        "deep_rating": "Hold",
        "deep_analysis_available": True,
        "execution_evidence_complete": True,
        "score_guard_reasons": [],
        "publication_blocked": False,
        "run_id": "test-run",
        "recommendation_tier": "research_complete",
        "market_price": 12.345,
        "market_price_date": "2026-08-29",
        "market_price_source": "tencent",
    }
    monkeypatch.setattr(brief_utils, "_brief_cache", None)
    monkeypatch.setattr(brief_utils, "_brief_refresh_task", None)
    monkeypatch.setattr(brief_utils, "get_vibe_provider", lambda: FakeVibe())
    monkeypatch.setattr(market_routes, "market_overview", overview)
    monkeypatch.setattr(
        eastmoney_emotion,
        "fetch_limit_up_sentiment",
        AsyncMock(return_value={"data": {}, "_meta": {"available": False}}),
    )
    monkeypatch.setattr(
        market_database.market_db,
        "get_latest_pipeline_run_audit",
        lambda: {"decision_date": date.today().isoformat(), "run_id": "test-run"},
    )
    monkeypatch.setattr(
        market_database.market_db,
        "get_decisions_for_date",
        lambda decision_date, limit=5000: [decision],
    )

    result = await brief_utils.build_real_brief(force_refresh=True)

    item = result["considered_stocks"][0]
    assert item["recommendation"] == "HOLD"
    assert item["analysis"] == "估值尚可，等待量价确认。"
    assert item["reference_price"] == 12.345
    assert item["reference_price_date"] == "2026-08-29"
    assert item["reference_price_source"] == "tencent"
    assert item["ranking_score"] == 73.2


@pytest.mark.asyncio
async def test_market_checkpoint_returns_market_regime(monkeypatch):
    today = date.today().isoformat()
    regime = {"state": "range", "score": 50, "as_of_date": today}

    async def overview(*, require_intraday=False):
        assert require_intraday is True
        return {
            "market_breadth": {"up": 2, "down": 2, "data_date": today},
            "market_regime": regime,
            "_data": {
                "available": True,
                "intraday_available": True,
                "breadth": {
                    "provider": "akshare",
                    "source_name": "test",
                    "is_live": True,
                    "data_date": today,
                },
            },
        }

    async def alerts():
        return {"urgent_count": 1}

    monkeypatch.setattr(market_routes, "market_overview", overview)
    monkeypatch.setattr(alerts_routes, "get_today_alerts", alerts)

    result = await TaskExecutor(persist=False)._market_checkpoint(None)

    assert result["market_regime"] == regime
    assert result["market_regime_state"] == "range"
    assert result["market_regime_score"] == 50
    assert result["market_data_freshness"] == "today_live"
    assert result["market_regime_usable_for_intraday"] is True


@pytest.mark.asyncio
async def test_market_checkpoint_does_not_use_dated_close_as_intraday_regime(monkeypatch):
    async def overview(*, require_intraday=False):
        assert require_intraday is True
        return {
            "market_breadth": {"up": 2, "down": 2, "data_date": "2026-09-08"},
            "market_regime": {"state": "range", "score": 50, "as_of_date": "2026-09-08"},
            "_data": {
                "available": True,
                "intraday_available": False,
                "breadth": {
                    "provider": "local",
                    "is_live": False,
                    "data_date": "2026-09-08",
                },
            },
        }

    async def alerts():
        return {"urgent_count": 0}

    monkeypatch.setattr(market_routes, "market_overview", overview)
    monkeypatch.setattr(alerts_routes, "get_today_alerts", alerts)

    result = await TaskExecutor(persist=False)._market_checkpoint(None)

    assert result["market_data_freshness"] == "previous_close_only"
    assert result["market_regime_usable_for_intraday"] is False
    assert result["market_regime_state"] == "unknown"
    assert result["market_regime_score"] is None
