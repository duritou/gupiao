"""Bounded HiThink canary runner for the existing application scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from scripts.probe_hithink import run_probe
from src.infrastructure.market_data.hithink_contracts import normalize_thscode
from src.infrastructure.market_data.hithink_provider import hithink_provider

HITHINK_CANARY_CAPABILITIES = (
    "snapshot",
    "valuation",
    "daily_kline",
    "financial_indicators",
)
HITHINK_CANARY_DEFAULT_CODES = (
    "600519.SH",
    "000001.SZ",
    "300750.SZ",
    "688981.SH",
    "002594.SZ",
    "601318.SH",
    "600000.SH",
    "300015.SZ",
)
HITHINK_CANARY_MAX_CODES = 20


def configured_canary_codes(raw: str | None = None) -> tuple[str, ...]:
    """Return a bounded, normalized shadow matrix without exposing credentials."""
    if raw is None:
        try:
            from config.settings import settings

            raw = str(getattr(settings, "HITHINK_CANARY_CODES", "") or "")
        except Exception:
            raw = ""
    normalized: list[str] = []
    for item in str(raw).split(","):
        try:
            code = normalize_thscode(item)
        except ValueError:
            continue
        if code not in normalized:
            normalized.append(code)
        if len(normalized) >= HITHINK_CANARY_MAX_CODES:
            break
    return tuple(normalized) or HITHINK_CANARY_DEFAULT_CODES


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

    async def run_matrix(
        self,
        checkpoint: str,
        codes: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a bounded multi-market shadow matrix sequentially.

        The matrix is intentionally isolated from ``run`` so existing callers
        can continue probing one symbol while the scheduler collects enough
        SH/SZ/BJ observations for the promotion gate.
        """
        checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
        selected = tuple(codes) if codes is not None else configured_canary_codes()
        selected = configured_canary_codes(",".join(selected))
        if not bool(getattr(self.provider, "configured", False)):
            return {
                "status": "not_configured",
                "checkpoint": checkpoint,
                "code_count": len(selected),
                "checked_at": checked_at,
            }
        if self._lock.locked():
            return {
                "status": "skipped",
                "reason": "probe_in_progress",
                "checkpoint": checkpoint,
                "code_count": len(selected),
                "checked_at": checked_at,
            }
        code_results: list[dict[str, Any]] = []
        async with self._lock:
            for code in selected:
                try:
                    result = await run_probe(
                        code,
                        HITHINK_CANARY_CAPABILITIES,
                        provider=self.provider,
                    )
                    code_results.append(
                        {
                            "code": code,
                            "status": result.get("status", "failed"),
                            "capability_count": result.get("capability_count", 0),
                            "supported_count": result.get("supported_count", 0),
                            "failed_count": sum(
                                item.get("status") == "failed"
                                for item in result.get("results", [])
                            ),
                        }
                    )
                except Exception as exc:
                    code_results.append(
                        {
                            "code": code,
                            "status": "failed",
                            "error_type": str(
                                getattr(exc, "category", type(exc).__name__)
                            ).lower()[:80],
                        }
                    )
        supported_count = sum(int(item.get("supported_count", 0) or 0) for item in code_results)
        capability_count = sum(int(item.get("capability_count", 0) or 0) for item in code_results)
        failed_count = sum(int(item.get("failed_count", 0) or 0) for item in code_results)
        return {
            "status": "completed" if supported_count else "failed",
            "checkpoint": checkpoint,
            "checked_at": checked_at,
            "code_count": len(code_results),
            "capability_count": capability_count,
            "supported_count": supported_count,
            "failed_count": failed_count,
            "codes": code_results,
        }


hithink_canary_runner = HiThinkCanaryRunner()


async def run_hithink_canary(
    checkpoint: str,
    code: str | None = None,
    *,
    codes: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Run one scheduler checkpoint through the process-wide serialized runner."""
    if code is not None:
        return await hithink_canary_runner.run(checkpoint, code)
    return await hithink_canary_runner.run_matrix(checkpoint, codes)
