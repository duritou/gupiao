"""MetricsCollector 单元测试"""

import pytest

from src.infrastructure.metrics.collector import MetricsCollector


class TestMetricsCollector:
    """MetricsCollector 单元测试"""

    @pytest.fixture
    def mc(self):
        return MetricsCollector()

    def test_increment_counter(self, mc):
        mc.increment("test_counter")
        assert mc.counters["test_counter"] == 1

        mc.increment("test_counter", 5)
        assert mc.counters["test_counter"] == 6

    def test_observe_histogram(self, mc):
        mc.observe("test_latency", 100.0)
        mc.observe("test_latency", 200.0)
        mc.observe("test_latency", 300.0)

        assert len(mc.histograms["test_latency"]) == 3
        snapshot = mc.get_snapshot()
        stats = snapshot["histograms"]["test_latency"]
        assert stats["count"] == 3
        assert stats["avg"] == 200.0
        assert stats["min"] == 100.0
        assert stats["max"] == 300.0

    def test_set_gauge(self, mc):
        mc.set_gauge("cpu_usage", 75.5)
        assert mc.gauges["cpu_usage"] == 75.5

        mc.set_gauge("cpu_usage", 80.0)
        assert mc.gauges["cpu_usage"] == 80.0

    def test_record_llm_call(self, mc):
        mc.record_llm_call("deepseek-v3", tokens=500, latency_ms=1200.0, cost=0.005)

        assert mc.counters["ai_requests_total"] == 1
        assert mc.counters["ai_tokens_total"] == 500
        assert len(mc.histograms["ai_latency_ms"]) == 1
        assert mc.gauges["ai_cost_deepseek-v3"] == 0.005

    def test_record_cache_hit_miss(self, mc):
        mc.record_cache_hit("memory")
        mc.record_cache_hit("memory")
        mc.record_cache_miss("memory")

        assert mc.counters["cache_hit_memory"] == 2
        assert mc.counters["cache_miss_memory"] == 1

    def test_record_event_metrics(self, mc):
        mc.record_event_published("scanner.completed")
        mc.record_event_published("scanner.completed")
        mc.record_event_handled("scanner.completed", 50.0)

        assert mc.counters["events_published_total"] == 2
        assert mc.counters["events_scanner.completed"] == 2
        assert mc.counters["events_handled_total"] == 1

    def test_get_snapshot_empty_histogram(self, mc):
        snapshot = mc.get_snapshot()
        assert snapshot["counters"] == {}
        assert snapshot["histograms"] == {}
        assert snapshot["gauges"] == {}

    def test_reset(self, mc):
        mc.increment("test", 10)
        mc.set_gauge("test_gauge", 100)
        mc.reset()

        assert mc.counters == {}
        assert mc.gauges == {}

    def test_p50_p99(self, mc):
        """验证分位数计算"""
        for i in range(1, 101):
            mc.observe("latency", float(i))

        snapshot = mc.get_snapshot()
        stats = snapshot["histograms"]["latency"]
        assert stats["p50"] == 50.5
        assert stats["p99"] == 99.01
