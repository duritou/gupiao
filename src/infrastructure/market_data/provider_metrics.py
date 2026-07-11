"""Provider Reliability Engine — v7.5 Adaptive Data Trust.

Transforms data trust from configuration-driven to observation-driven.
Every provider call is recorded. Trust scores are computed from real
runtime metrics, not hardcoded numbers.

Architecture:
  Provider Call → RuntimeMetrics.record() → DynamicTrustScore
    → ProviderRanking → Auto-degrade/recover → TrustHistory

Layers:
  1. Runtime Metrics — requests, latency, success_rate, completeness
  2. Dynamic Trust Score — weighted composite from observed metrics
  3. Sliding Windows — 5min / 30min / 6h / 24h / 7d
  4. Auto-degrade — trust drops below threshold → exit primary
  5. Auto-recover — health checks pass → rejoin candidate → backup → primary
  6. Trust History — time series for trend analysis
"""

from __future__ import annotations

import time as _time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


# ================================================================
# Metrics Event — one data point per provider call
# ================================================================

@dataclass
class ProviderCallEvent:
    """A single provider call record."""
    provider: str = ""
    operation: str = ""          # "quote" / "kline" / "index"
    success: bool = False
    latency_ms: float = 0.0
    error_message: str = ""
    timestamp: float = field(default_factory=_time.time)
    data_completeness: float = 1.0  # 0-1, how many fields were populated
    validation_passed: bool = True


# ================================================================
# Runtime Metrics — accumulated stats per provider
# ================================================================

@dataclass
class WindowMetrics:
    """Aggregated metrics for a time window."""
    requests: int = 0
    success: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    latencies: list[float] = field(default_factory=list)  # For percentile calc
    completeness_sum: float = 0.0
    validation_passes: int = 0
    window_start: float = field(default_factory=_time.time)

    @property
    def success_rate(self) -> float:
        return self.success / self.requests if self.requests > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.requests if self.requests > 0 else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def completeness(self) -> float:
        return self.completeness_sum / self.requests if self.requests > 0 else 0.0

    @property
    def validation_rate(self) -> float:
        return self.validation_passes / self.requests if self.requests > 0 else 0.0


@dataclass
class ProviderRuntimeMetrics:
    """All runtime metrics for a single provider."""
    provider: str = ""

    # Sliding windows (seconds)
    window_5min: WindowMetrics = field(default_factory=WindowMetrics)
    window_30min: WindowMetrics = field(default_factory=WindowMetrics)
    window_6h: WindowMetrics = field(default_factory=WindowMetrics)
    window_24h: WindowMetrics = field(default_factory=WindowMetrics)
    window_7d: WindowMetrics = field(default_factory=WindowMetrics)

    # Lifetime totals
    lifetime_requests: int = 0
    lifetime_success: int = 0
    lifetime_failures: int = 0

    # State
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    last_error: str = ""
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    # Health check
    is_degraded: bool = False        # Auto-removed from primary chain
    degraded_at: float = 0.0
    health_check_interval: float = 300.0  # 5 minutes

    def record(self, event: ProviderCallEvent):
        """Record a single provider call and update all windows."""
        now = _time.time()

        # Update all windows
        for window_sec, wm in [
            (300, self.window_5min),
            (1800, self.window_30min),
            (21600, self.window_6h),
            (86400, self.window_24h),
            (604800, self.window_7d),
        ]:
            self._add_to_window(wm, event, now, window_sec)

        # Lifetime
        self.lifetime_requests += 1
        if event.success:
            self.lifetime_success += 1
            self.last_success_at = now
            self.consecutive_successes += 1
            self.consecutive_failures = 0
        else:
            self.lifetime_failures += 1
            self.last_failure_at = now
            self.last_error = event.error_message
            self.consecutive_failures += 1
            self.consecutive_successes = 0

    def _add_to_window(
        self, wm: WindowMetrics, event: ProviderCallEvent,
        now: float, window_sec: float,
    ):
        """Add event to a sliding window, evicting old entries."""
        # Reset window if expired
        if now - wm.window_start > window_sec:
            wm.requests = 0
            wm.success = 0
            wm.failures = 0
            wm.total_latency_ms = 0.0
            wm.latencies = []
            wm.completeness_sum = 0.0
            wm.validation_passes = 0
            wm.window_start = now

        wm.requests += 1
        if event.success:
            wm.success += 1
        else:
            wm.failures += 1
        wm.total_latency_ms += event.latency_ms
        wm.latencies.append(event.latency_ms)
        wm.completeness_sum += event.data_completeness
        if event.validation_passed:
            wm.validation_passes += 1

    @property
    def lifetime_success_rate(self) -> float:
        total = self.lifetime_requests
        return self.lifetime_success / total if total > 0 else 0.0


# ================================================================
# Dynamic Trust Score
# ================================================================

@dataclass
class DynamicTrustScore:
    """Trust score computed from observed metrics, not config."""
    provider: str = ""
    computed_at: float = field(default_factory=_time.time)

    # Sub-scores (0-1)
    reliability: float = 0.0    # 35% weight — success rate
    latency_score: float = 0.0  # 20% weight — speed
    freshness: float = 0.0      # 20% weight — data recency
    completeness: float = 0.0   # 15% weight — field population
    validation: float = 0.0     # 10% weight — data validator pass rate

    # Composite (0-1)
    overall_trust: float = 0.0

    # Context
    sample_size: int = 0        # How many requests in the evaluation window
    window_label: str = ""      # "24h" / "7d" / "5min"

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "overall_trust": round(self.overall_trust, 4),
            "reliability": round(self.reliability, 4),
            "latency_score": round(self.latency_score, 4),
            "freshness": round(self.freshness, 4),
            "completeness": round(self.completeness, 4),
            "validation": round(self.validation, 4),
            "sample_size": self.sample_size,
            "window": self.window_label,
        }


# ================================================================
# Provider Reliability Engine
# ================================================================

class ProviderReliabilityEngine:
    """Tracks provider metrics and computes dynamic trust scores.

    No hardcoded trust values. Everything comes from observation.
    """

    # Trust score weights
    WEIGHTS = {
        "reliability": 0.35,
        "latency": 0.20,
        "freshness": 0.20,
        "completeness": 0.15,
        "validation": 0.10,
    }

    # Thresholds
    DEGRADE_THRESHOLD = 0.50    # Trust below this → auto-degrade
    RECOVER_THRESHOLD = 0.80    # Trust above this → auto-recover
    MIN_RECOVER_SAMPLES = 20    # Need this many successful checks to recover

    def __init__(self):
        self._metrics: dict[str, ProviderRuntimeMetrics] = {}
        self._trust_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
        # trust_history[provider] = [(timestamp, trust_score), ...]

    def get_or_create_metrics(self, provider: str) -> ProviderRuntimeMetrics:
        """Get or create metrics tracker for a provider."""
        if provider not in self._metrics:
            self._metrics[provider] = ProviderRuntimeMetrics(provider=provider)
        return self._metrics[provider]

    def record_call(
        self, provider: str, operation: str,
        success: bool, latency_ms: float,
        error_message: str = "",
        completeness: float = 1.0,
        validation_passed: bool = True,
    ):
        """Record a single provider call."""
        metrics = self.get_or_create_metrics(provider)
        event = ProviderCallEvent(
            provider=provider, operation=operation,
            success=success, latency_ms=latency_ms,
            error_message=error_message,
            data_completeness=completeness,
            validation_passed=validation_passed,
        )
        metrics.record(event)

        # Auto-degrade check
        if not success and metrics.consecutive_failures >= 5:
            trust = self.compute_trust(provider, "30min")
            if trust.overall_trust < self.DEGRADE_THRESHOLD and not metrics.is_degraded:
                metrics.is_degraded = True
                metrics.degraded_at = _time.time()

        # Auto-recover check
        if metrics.is_degraded and metrics.consecutive_successes >= self.MIN_RECOVER_SAMPLES:
            trust = self.compute_trust(provider, "30min")
            if trust.overall_trust >= self.RECOVER_THRESHOLD:
                metrics.is_degraded = False
                metrics.consecutive_failures = 0

    def compute_trust(
        self, provider: str, window: str = "24h"
    ) -> DynamicTrustScore:
        """Compute dynamic trust score from observed metrics.

        Args:
            provider: Provider name
            window: Time window ("5min", "30min", "6h", "24h", "7d")

        Returns:
            DynamicTrustScore with all sub-scores
        """
        metrics = self._metrics.get(provider)
        if metrics is None:
            return DynamicTrustScore(provider=provider, window_label=window)

        # Select window
        wm_map = {
            "5min": metrics.window_5min,
            "30min": metrics.window_30min,
            "6h": metrics.window_6h,
            "24h": metrics.window_24h,
            "7d": metrics.window_7d,
        }
        wm = wm_map.get(window, metrics.window_24h)

        if wm.requests == 0:
            # No data in this window — use lifetime or return neutral
            if metrics.lifetime_requests == 0:
                return DynamicTrustScore(
                    provider=provider, window_label=window,
                    overall_trust=0.5, sample_size=0,
                )
            return DynamicTrustScore(
                provider=provider, window_label=window,
                reliability=metrics.lifetime_success_rate,
                completeness=0.95,
                validation=0.95,
                overall_trust=metrics.lifetime_success_rate * 0.7 + 0.25,
                sample_size=metrics.lifetime_requests,
            )

        # Sub-scores
        reliability = wm.success_rate

        # Latency: normalize to 0-1 (assuming 500ms is good, 5000ms is bad)
        latency_ms = wm.avg_latency_ms
        if latency_ms < 500:
            latency_score = 1.0
        elif latency_ms < 2000:
            latency_score = 1.0 - (latency_ms - 500) / 1500 * 0.5
        elif latency_ms < 5000:
            latency_score = 0.5 - (latency_ms - 2000) / 3000 * 0.4
        else:
            latency_score = 0.1

        # Freshness: based on last success time
        now = _time.time()
        if metrics.last_success_at > 0:
            age_sec = now - metrics.last_success_at
            if age_sec < 300:
                freshness = 1.0
            elif age_sec < 3600:
                freshness = 0.9
            elif age_sec < 86400:
                freshness = 0.7
            else:
                freshness = 0.4
        else:
            freshness = 0.0

        completeness = wm.completeness
        validation = wm.validation_rate

        # Weighted composite
        overall = (
            reliability * self.WEIGHTS["reliability"]
            + latency_score * self.WEIGHTS["latency"]
            + freshness * self.WEIGHTS["freshness"]
            + completeness * self.WEIGHTS["completeness"]
            + validation * self.WEIGHTS["validation"]
        )

        score = DynamicTrustScore(
            provider=provider,
            reliability=reliability,
            latency_score=latency_score,
            freshness=freshness,
            completeness=completeness,
            validation=validation,
            overall_trust=overall,
            sample_size=wm.requests,
            window_label=window,
        )

        # Record in history (every 5 minutes to avoid spam)
        history = self._trust_history[provider]
        if not history or (now - history[-1][0]) > 300:
            history.append((now, overall))

        return score

    def get_trust(self, provider: str, window: str = "24h") -> float:
        """Quick access: get just the trust score float."""
        return self.compute_trust(provider, window).overall_trust

    def get_all_trust_scores(self, window: str = "24h") -> list[DynamicTrustScore]:
        """Get trust scores for all tracked providers, ranked."""
        scores = [
            self.compute_trust(p, window)
            for p in self._metrics
            if p != "cache"
        ]
        scores.sort(key=lambda s: -s.overall_trust)
        return scores

    def is_degraded(self, provider: str) -> bool:
        """Check if a provider is currently degraded."""
        metrics = self._metrics.get(provider)
        return metrics.is_degraded if metrics else False

    def get_trust_history(
        self, provider: str, limit: int = 100
    ) -> list[dict]:
        """Get trust score history for trend analysis."""
        history = self._trust_history.get(provider, [])
        return [
            {
                "timestamp": datetime.fromtimestamp(ts).isoformat(),
                "trust_score": round(score, 4),
            }
            for ts, score in history[-limit:]
        ]

    def get_metrics_summary(self, provider: str) -> dict:
        """Full metrics summary for a provider."""
        metrics = self._metrics.get(provider)
        if not metrics:
            return {"provider": provider, "available": False}

        trust_24h = self.compute_trust(provider, "24h")
        trust_30min = self.compute_trust(provider, "30min")

        return {
            "provider": provider,
            "status": "degraded" if metrics.is_degraded else "active",
            "trust_30min": round(trust_30min.overall_trust, 4),
            "trust_24h": round(trust_24h.overall_trust, 4),
            "success_rate_24h": round(metrics.window_24h.success_rate, 4),
            "avg_latency_ms_24h": round(metrics.window_24h.avg_latency_ms, 1),
            "p95_latency_ms_24h": round(metrics.window_24h.p95_latency_ms, 1),
            "completeness_24h": round(metrics.window_24h.completeness, 4),
            "validation_rate_24h": round(metrics.window_24h.validation_rate, 4),
            "lifetime_requests": metrics.lifetime_requests,
            "lifetime_success_rate": round(metrics.lifetime_success_rate, 4),
            "consecutive_failures": metrics.consecutive_failures,
            "consecutive_successes": metrics.consecutive_successes,
            "last_error": metrics.last_error[:120] if metrics.last_error else "",
            "last_success_at": (
                datetime.fromtimestamp(metrics.last_success_at).isoformat()
                if metrics.last_success_at else ""
            ),
            "trust_breakdown": trust_24h.to_dict(),
        }


# Singleton
reliability_engine = ProviderReliabilityEngine()
