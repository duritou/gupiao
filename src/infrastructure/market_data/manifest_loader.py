"""Provider Manifest Loader — YAML-driven provider registration + certification.

Startup: scans providers/*.yaml → ProviderManifest objects
Runtime: feeds Metrics Center with real-time per-provider stats
Certification: gates AI data access — only certified capabilities feed AI
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CertifiedCapability:
    """A single certified capability within a provider."""
    capability: str = ""           # "realtime_quote", "daily_kline"
    verified: bool = False         # Has this been tested and confirmed?
    samples: int = 0               # How many test calls verified
    accuracy: float = 0.0          # Field-level accuracy
    consistency: float = 0.0       # Cross-provider agreement
    last_verified: str = ""        # ISO date of last verification

    def to_dict(self) -> dict:
        return {
            "capability": self.capability,
            "verified": self.verified,
            "samples": self.samples,
            "accuracy": round(self.accuracy, 4) if self.accuracy else 0,
            "consistency": round(self.consistency, 4) if self.consistency else 0,
            "last_verified": self.last_verified,
        }

    @property
    def is_certified(self) -> bool:
        return self.verified and self.samples >= 10 and self.accuracy >= 0.95


@dataclass
class KnownLimits:
    """Known limitations of a provider capability."""
    realtime_delay_sec: float = 0      # 0 = realtime, >0 = delayed
    history_years: int = 5
    minute_history_days: int = 60
    supports_adjust: list[str] = field(default_factory=list)  # ["qfq","hfq"]
    supports_tick: bool = False
    supports_orderbook: bool = False
    max_batch_size: int = 100

    def to_dict(self) -> dict:
        return {
            "realtime_delay_sec": self.realtime_delay_sec,
            "history_years": self.history_years,
            "minute_history_days": self.minute_history_days,
            "supports_adjust": self.supports_adjust,
            "supports_tick": self.supports_tick,
            "supports_orderbook": self.supports_orderbook,
            "max_batch_size": self.max_batch_size,
        }


@dataclass
class DataQualityMetrics:
    """Multi-dimensional data quality (not just trust_score).

    Trust = 0.4*Freshness + 0.3*Agreement + 0.2*Availability + 0.1*Completeness
    All computed from runtime observation, not configuration.
    """
    provider: str = ""
    freshness: float = 0.0      # How recent is the data? (0-1)
    completeness: float = 0.0   # Field population rate (0-1)
    agreement: float = 0.0      # Cross-provider consistency (0-1)
    availability: float = 0.0   # Uptime / success rate (0-1)
    overall_quality: float = 0.0  # Weighted composite

    QUALITY_WEIGHTS = {
        "freshness": 0.40,
        "agreement": 0.30,
        "availability": 0.20,
        "completeness": 0.10,
    }

    def compute(self):
        """Compute overall quality from sub-scores."""
        self.overall_quality = (
            self.freshness * self.QUALITY_WEIGHTS["freshness"]
            + self.agreement * self.QUALITY_WEIGHTS["agreement"]
            + self.availability * self.QUALITY_WEIGHTS["availability"]
            + self.completeness * self.QUALITY_WEIGHTS["completeness"]
        )

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "freshness": round(self.freshness, 4),
            "completeness": round(self.completeness, 4),
            "agreement": round(self.agreement, 4),
            "availability": round(self.availability, 4),
            "overall_quality": round(self.overall_quality, 4),
            "grade": self.quality_grade,
        }

    @property
    def quality_grade(self) -> str:
        if self.overall_quality >= 0.95:
            return "A+"
        if self.overall_quality >= 0.90:
            return "A"
        if self.overall_quality >= 0.80:
            return "B+"
        if self.overall_quality >= 0.70:
            return "B"
        if self.overall_quality >= 0.50:
            return "C"
        return "D"


@dataclass
class ProviderManifest:
    """Loaded from YAML. Describes what a provider CAN do."""
    provider: str = ""
    version: str = ""
    description: str = ""
    capabilities: dict[str, dict] = field(default_factory=dict)
    certification: dict[str, dict] = field(default_factory=dict)
    known_limits: dict[str, Any] = field(default_factory=dict)
    known_bugs: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    code_format: str = ""

    def get_capability_ids(self) -> list[str]:
        return list(self.capabilities.keys())

    def get_certified_capabilities(self) -> list[CertifiedCapability]:
        """Return list of CertifiedCapability objects from YAML."""
        result = []
        for cap_id, cert_data in self.certification.items():
            cc = CertifiedCapability(
                capability=cap_id,
                verified=cert_data.get("verified", False),
                samples=cert_data.get("samples", 0),
                accuracy=cert_data.get("accuracy", 0),
                consistency=cert_data.get("consistency", 0),
                last_verified=cert_data.get("last_verified", ""),
            )
            result.append(cc)
        return result

    def is_capability_certified(self, capability: str) -> bool:
        """Gate: only certified capabilities feed AI."""
        cert = self.certification.get(capability, {})
        cc = CertifiedCapability(
            capability=capability,
            verified=cert.get("verified", False),
            samples=cert.get("samples", 0),
            accuracy=cert.get("accuracy", 0),
        )
        return cc.is_certified

    def get_known_limits(self) -> KnownLimits:
        """Parse known_limits from YAML into typed object."""
        kl = self.known_limits
        return KnownLimits(
            realtime_delay_sec=kl.get("realtime_delay_sec", 0),
            history_years=kl.get("history_years", 5),
            minute_history_days=kl.get("minute_history_days", 60),
            supports_adjust=kl.get("supports_adjust", []),
            supports_tick=kl.get("supports_tick", False),
            supports_orderbook=kl.get("supports_orderbook", False),
            max_batch_size=kl.get("max_batch_size", 100),
        )


@dataclass
class ProviderMetricsSummary:
    """Live metrics for one provider — feeds dashboard."""
    provider: str = ""
    status: str = "unknown"       # active / degraded / down
    trust_24h: float = 0.0
    trust_30min: float = 0.0
    success_rate_24h: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    requests_24h: int = 0
    consecutive_failures: int = 0
    last_error: str = ""
    capabilities: list[str] = field(default_factory=list)
    certified: list[dict] = field(default_factory=list)
    known_limits: dict = field(default_factory=dict)
    known_bugs: list[str] = field(default_factory=list)
    data_quality: DataQualityMetrics = field(default_factory=DataQualityMetrics)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "status": self.status,
            "trust_24h": round(self.trust_24h, 4),
            "trust_30min": round(self.trust_30min, 4),
            "success_rate_24h": round(self.success_rate_24h, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "requests_24h": self.requests_24h,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error[:120] if self.last_error else "",
            "capabilities": self.capabilities,
            "certified": self.certified,
            "known_limits": self.known_limits,
            "known_bugs": self.known_bugs,
            "data_quality": self.data_quality.to_dict(),
        }


class ManifestLoader:
    """Loads provider YAML manifests and merges with live metrics."""

    def __init__(self, providers_dir: str = None):
        if providers_dir is None:
            # Find providers/ relative to project root
            root = Path(__file__).parent.parent.parent.parent
            providers_dir = root / "providers"
        self._dir = Path(providers_dir)
        self._manifests: dict[str, ProviderManifest] = {}
        self._load_all()

    def _load_all(self):
        """Load all .yaml files from providers/ directory."""
        import yaml

        if not self._dir.exists():
            return

        for yaml_file in self._dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and "provider" in data:
                    manifest = ProviderManifest(
                        provider=data.get("provider", ""),
                        version=str(data.get("version", "")),
                        description=data.get("description", ""),
                        capabilities=data.get("capabilities", {}),
                        certification=data.get("certification", {}),
                        known_limits=data.get("known_limits", {}),
                        known_bugs=data.get("known_bugs", []),
                        limitations=data.get("limitations", []),
                        code_format=data.get("code_format", ""),
                    )
                    self._manifests[manifest.provider] = manifest
            except Exception:
                pass

    def get(self, provider: str) -> ProviderManifest | None:
        return self._manifests.get(provider)

    def list_all(self) -> list[ProviderManifest]:
        return list(self._manifests.values())

    def get_summary(self, provider: str) -> ProviderMetricsSummary:
        """Merge YAML manifest with live runtime metrics + data quality."""
        from src.infrastructure.market_data.provider_metrics import (
            reliability_engine,
        )

        manifest = self._manifests.get(provider)
        metrics = reliability_engine.get_metrics_summary(provider)

        # Compute data quality from runtime metrics
        dq = DataQualityMetrics(provider=provider)
        dq.availability = metrics.get("success_rate_24h", 0)
        dq.freshness = 1.0  # Default — updated when freshness tracking is added
        dq.completeness = metrics.get("completeness_24h", 0.95)
        dq.compute()

        return ProviderMetricsSummary(
            provider=provider,
            status=metrics.get("status", "unknown"),
            trust_24h=metrics.get("trust_24h", 0),
            trust_30min=metrics.get("trust_30min", 0),
            success_rate_24h=metrics.get("success_rate_24h", 0),
            avg_latency_ms=metrics.get("avg_latency_ms_24h", 0),
            p95_latency_ms=metrics.get("p95_latency_ms_24h", 0),
            requests_24h=metrics.get("lifetime_requests", 0),
            consecutive_failures=metrics.get("consecutive_failures", 0),
            last_error=metrics.get("last_error", ""),
            capabilities=manifest.get_capability_ids() if manifest else [],
            certified=[
                c.to_dict() for c in manifest.get_certified_capabilities()
            ] if manifest else [],
            known_limits=manifest.get_known_limits().to_dict() if manifest else {},
            known_bugs=manifest.known_bugs if manifest else [],
            data_quality=dq,
        )

    def get_all_summaries(self) -> list[ProviderMetricsSummary]:
        """Get live metrics for all registered providers."""
        return [self.get_summary(p) for p in self._manifests]


# Singleton
manifest_loader = ManifestLoader()
