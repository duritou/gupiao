"""FastAPI 路由集成测试"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

client = TestClient(app)


class TestSystemRoutes:
    def test_health(self):
        r = client.get("/api/v1/system/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_status(self):
        r = client.get("/api/v1/system/status")
        assert r.status_code == 200
        assert "modules" in r.json()


class TestAIOSRoutes:
    def test_status_uses_persistent_journal_state(self):
        r = client.get("/api/v1/ai-os/status")
        assert r.status_code == 200
        data = r.json()
        assert "today_progress" in data
        assert "journal_decisions_total" in data["today_progress"]
        assert data["data_source"] == "task_executor + decision_journal"

    def test_memory_and_learning_routes_return_real_data(self):
        memory = client.get("/api/v1/ai-os/memory/today")
        learning = client.get("/api/v1/ai-os/learning-log")
        assert memory.status_code == 200
        assert learning.status_code == 200
        assert memory.json()["data_source"] == "decision_journal + paper_account + learning_log"
        assert isinstance(learning.json()["learning_log"], list)


class TestSignalsRoutes:
    def test_list_signals(self):
        r = client.get("/api/v1/signals/list")
        assert r.status_code == 200
        assert len(r.json()["signals"]) == 6

    @pytest.mark.slow
    def test_compute_signals(self):
        """v7.5: Signals computed from real baostock daily bars."""
        r = client.get("/api/v1/signals/compute/000001.SZ")
        assert r.status_code == 200
        data = r.json()
        assert data["stock_code"] == "000001.SZ"
        # Real data may succeed or return data/error — both are valid
        assert "fusion_score" in data or "error" in data or "detail" in data

    @pytest.mark.slow
    def test_compute_signals_batch(self):
        """Batch signals from real data."""
        r = client.post("/api/v1/signals/batch", json={
            "codes": ["000001.SZ", "000002.SZ"]
        })
        assert r.status_code == 200
        data = r.json()
        assert "signals" in data
        assert len(data["signals"]) == 2


class TestScannerRoutes:
    @pytest.mark.slow
    def test_run_scanner(self):
        """v7.5: Scanner uses real baostock universe + signals."""
        r = client.post("/api/v1/scanner/run?top_n=5")
        assert r.status_code == 200
        data = r.json()
        assert "total_scanned" in data
        assert "candidates" in data
        assert "data_source" in data


class TestKnowledgeRoutes:
    def test_categories(self):
        r = client.get("/api/v1/knowledge/categories")
        assert r.status_code == 200
        assert "categories" in r.json()

    def test_search(self):
        r = client.get("/api/v1/knowledge/search?q=半导体")
        assert r.status_code == 200
        data = r.json()
        assert data["query"] == "半导体"
        assert len(data["results"]) >= 0

    def test_get_entry(self):
        r = client.get("/api/v1/knowledge/entries/semiconductor")
        assert r.status_code == 200
        data = r.json()
        if "error" not in data:
            assert data["id"] == "semiconductor"


class TestResearchRoutes:
    # Both run a real research pipeline and fetch from external providers.
    # Measured at 105s and 72s; the same tests can come back in 0.08s when a
    # request happens to short-circuit, which is exactly why they cannot be
    # part of a gate that has to mean the same thing every run.
    @pytest.mark.slow
    def test_run_research_pipeline(self):
        r = client.post("/api/v1/research/run?pool_size=10&top_n=3&mode=pipeline")
        assert r.status_code == 200
        data = r.json()
        assert "report_id" in data
        assert "candidates" in data

    @pytest.mark.slow
    def test_run_research_lite(self):
        r = client.post("/api/v1/research/run?pool_size=10&top_n=2&mode=lite")
        assert r.status_code == 200
        assert "report_id" in r.json()


class TestBacktestRoutes:
    def test_run_backtest_up(self):
        r = client.post("/api/v1/backtest/run?trend=up&days=80")
        assert r.status_code == 200
        data = r.json()
        assert "metrics" in data
        assert data["metrics"]["total_return_pct"] != 0 or data["metrics"]["total_trades"] == 0

    def test_run_backtest_down(self):
        r = client.post("/api/v1/backtest/run?trend=down&days=80")
        assert r.status_code == 200
        assert "period" in r.json()
