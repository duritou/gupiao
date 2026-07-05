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


class TestSignalsRoutes:
    def test_list_signals(self):
        r = client.get("/api/v1/signals/list")
        assert r.status_code == 200
        assert len(r.json()["signals"]) == 6

    def test_compute_signals(self):
        r = client.get("/api/v1/signals/compute/000001.SZ?trend=up")
        assert r.status_code == 200
        data = r.json()
        assert data["stock_code"] == "000001.SZ"
        assert "fusion_score" in data
        assert "direction" in data
        assert "scores" in data


class TestScannerRoutes:
    def test_run_scanner(self):
        r = client.post("/api/v1/scanner/run?pool_size=10&top_n=3")
        assert r.status_code == 200
        data = r.json()
        assert data["total_scanned"] == 10
        assert len(data["candidates"]) <= 3


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
    def test_run_research_pipeline(self):
        r = client.post("/api/v1/research/run?pool_size=10&top_n=3&mode=pipeline")
        assert r.status_code == 200
        data = r.json()
        assert "report_id" in data
        assert "candidates" in data

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
