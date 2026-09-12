"""Bounded HiThink canary runner for the existing application scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from scripts.probe_hithink import run_probe
from src.infrastructure.market_data.hithink_provider import hithink_provider

HITHINK_CANARY_CAPABILITIES = (
    "snapshot",
    "valuation",
    "daily_kline",
    "financial_indicators",
)


class HiThinkCanaryRunner:
    """Serialize safe read-only probes and expose only aggregate outcomes."""

    def __init__(self, provider: Any = hithink_provider) -> None:
        self.provider = provider
        self._lock = asyncio.Lock()

    async def run(self, checkpoint: str, code: str = "600519.SH") -> dict[str, Any]:
        checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if not bool(getattr(self.provider, "configured", False)):
            return {
                "status": "not_configured",
                "checkpoint": checkpoint,
                "code": code,
                "checked_at": checked_at,
            }
        if self._lock.locked():
            return {
                "status": "skipped",
                "reason": "probe_in_progress",
                "checkpoint": checkpoint,
                "code": code,
                "checked_at": checked_at,
            }
        async with self._lock:
            try:
                result = await run_probe(
                    code,
                    HITHINK_CANARY_CAPABILITIES,
                    provider=self.provider,
                )
            except Exception as exc:
                return {
                    "status": "failed",
                    "error_type": str(getattr(exc, "category", type(exc).__name__)).lower()[:80],
                    "checkpoint": checkpoint,
                    "code": code,
                    "checked_at": checked_at,
                }
        return {
            "status": result.get("status", "failed"),
            "checkpoint": checkpoint,
            "code": code,
            "checked_at": result.get("checked_at", checked_at),
            "capability_count": result.get("capability_count", 0),
            "supported_count": result.get("supported_count", 0),
            "failed_count": sum(
                item.get("status") == "failed" for item in result.get("results", [])
            ),
        }


hithink_canary_runner = HiThinkCanaryRunner()


async def run_hithink_canary(checkpoint: str, code: str = "600519.SH") -> dict[str, Any]:
    """Run one scheduler checkpoint through the process-wide serialized runner."""
    return await hithink_canary_runner.run(checkpoint, code)
