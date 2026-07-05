"""指标采集器 — Phase 0 内存版

Phase 6+ 切换到 Prometheus (prometheus_client)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


def _percentile(values: list[float], p: float) -> float:
    """计算百分位数（线性插值）"""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    k = (p / 100.0) * (n - 1)
    f = int(k)
    c = k - f
    if f + 1 < n:
        return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
    return sorted_vals[f]


@dataclass
class MetricsCollector:
    """统一指标采集器 — 内存版"""

    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    histograms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    gauges: dict[str, float] = field(default_factory=dict)

    # ===== Counter 操作 =====

    def increment(self, name: str, value: int = 1) -> None:
        """计数器 +1"""
        self.counters[name] += value

    # ===== Histogram 操作 =====

    def observe(self, name: str, value: float) -> None:
        """记录一次观测值"""
        self.histograms[name].append(value)

    # ===== Gauge 操作 =====

    def set_gauge(self, name: str, value: float) -> None:
        """设置仪表值"""
        self.gauges[name] = value

    # ===== LLM 指标 =====

    def record_llm_call(self, model: str, tokens: int, latency_ms: float, cost: float) -> None:
        """记录 LLM 调用"""
        self.increment("ai_requests_total")
        self.increment("ai_tokens_total", tokens)
        self.observe("ai_latency_ms", latency_ms)
        self.gauges[f"ai_cost_{model}"] = self.gauges.get(f"ai_cost_{model}", 0) + cost

    def record_llm_error(self, model: str, error: str) -> None:
        """记录 LLM 错误"""
        self.increment("ai_errors_total")
        self.increment(f"ai_errors_{model}")

    # ===== Cache 指标 =====

    def record_cache_hit(self, cache_level: str) -> None:
        self.increment(f"cache_hit_{cache_level}")

    def record_cache_miss(self, cache_level: str) -> None:
        self.increment(f"cache_miss_{cache_level}")

    # ===== Scanner 指标 =====

    def record_scanner_stage(self, stage: str, count: int, duration_ms: float) -> None:
        self.increment(f"scanner_{stage}_count", count)
        self.observe(f"scanner_{stage}_duration_ms", duration_ms)

    # ===== Event 指标 =====

    def record_event_published(self, event_type: str) -> None:
        self.increment("events_published_total")
        self.increment(f"events_{event_type}")

    def record_event_handled(self, event_type: str, duration_ms: float) -> None:
        self.increment("events_handled_total")
        self.observe(f"events_{event_type}_duration_ms", duration_ms)

    # ===== 快照 =====

    def get_snapshot(self) -> dict:
        """获取当前指标快照"""
        hist_stats = {}
        for name, values in self.histograms.items():
            if values:
                hist_stats[name] = {
                    "count": len(values),
                    "avg": sum(values) / len(values),
                    "max": max(values),
                    "min": min(values),
                    "p50": _percentile(values, 50) if values else 0,
                    "p99": _percentile(values, 99) if values else 0,
                }

        return {
            "counters": dict(self.counters),
            "histograms": hist_stats,
            "gauges": dict(self.gauges),
        }

    def reset(self) -> None:
        """重置所有指标（测试用）"""
        self.counters.clear()
        self.histograms.clear()
        self.gauges.clear()


# 全局单例
metrics = MetricsCollector()


def track_duration(metric_name: str):
    """装饰器：自动记录函数耗时（异步函数）"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                metrics.observe(metric_name, duration_ms)
        return wrapper
    return decorator
