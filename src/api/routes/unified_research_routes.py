"""Single-process research orchestration for the three stock plugins."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

_SHARED_PYTHON = Path(__file__).resolve().parents[4] / "shared" / "python"
if str(_SHARED_PYTHON) not in sys.path:
    sys.path.insert(0, str(_SHARED_PYTHON))

from investment_common import JsonRecordStore, load_runtime_env, plain_code, runtime_value

router = APIRouter(prefix="/unified-research", tags=["unified-research"])
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 100
_LOGGER = logging.getLogger(__name__)
_ADAPTIVE_ROOT = Path(__file__).resolve().parents[3]
load_runtime_env(_ADAPTIVE_ROOT)
_DATA_ROOT = Path(runtime_value("INVESTMENT_DATA_ROOT", str(_ADAPTIVE_ROOT / "data"))).resolve()
_JOB_STORE = JsonRecordStore(_DATA_ROOT / "unified_research")


class UnifiedResearchRequest(BaseModel):
    code: str = Field(..., description="六位 A 股代码")
    trade_date: str | None = Field(default=None, description="YYYY-MM-DD")
    include_vibe: bool = True
    include_tradingagents: bool = True
    past_context: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _persist(job: dict[str, Any]) -> None:
    try:
        _JOB_STORE.save(job["job_id"], job)
    except (OSError, TypeError, ValueError) as exc:
        # Persistence is a recovery aid; it must not make a live research job
        # fail when a read-only or full data directory is configured.
        _LOGGER.warning("Could not persist unified research job %s: %s", job.get("job_id"), exc)


def _load_jobs() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for record in _JOB_STORE.list(limit=_MAX_JOBS):
        job_id = record.get("job_id")
        if not isinstance(job_id, str):
            continue
        if record.get("status") in {"queued", "running"}:
            record.update({
                "status": "failed",
                "stage": "failed",
                "error": "Adaptive 服务重启，任务未完成",
                "updated_at": _now(),
            })
            _persist(record)
        loaded[job_id] = record
    return loaded


_JOBS.update(_load_jobs())


def _validate_code(value: str) -> str:
    code = plain_code(value)
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="code 必须是六位 A 股代码")
    return code


def _validate_trade_date(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="trade_date 必须是 YYYY-MM-DD") from exc


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    # The in-memory task record contains no credentials, but returning an
    # explicit copy prevents callers from mutating the server-side state.
    return {**job, "result": job.get("result")}


async def _safe(awaitable, semaphore: asyncio.Semaphore | None = None):
    try:
        if semaphore is not None:
            async with semaphore:
                return await awaitable
        return await awaitable
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


async def _financials_with_native_fallback(code: str, provider) -> dict[str, Any]:
    """Use Adaptive's dated native statements before the Vibe fallback."""
    from config.settings import settings
    from src.infrastructure.market_data.source_manager import source_manager
    from src.infrastructure.market_data.sina_financials import fetch_sina_financials

    try:
        history, history_provenance = await source_manager.get_financial_history(
            code, periods=settings.DATA_COMPLETION_FINANCIAL_PERIODS
        )
        if history.get("available") and history.get("statements"):
            return {
                "data": history,
                "_meta": {
                    **history_provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare_history",
                    "available": True,
                    "is_realtime": False,
                    "requested_periods": history.get("requested_periods"),
                    "period_counts": history.get("period_counts") or {},
                    "history_complete": bool(history.get("history_complete")),
                },
            }
    except Exception:
        pass
    try:
        statements, provenance = await source_manager.get_financial_statements(code)
        if statements.get("available"):
            return {
                "data": statements,
                "_meta": {
                    **provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare",
                    "available": True,
                    "is_realtime": False,
                },
            }
    except Exception:
        pass
    try:
        native = await fetch_sina_financials(code)
    except Exception as exc:  # Native transport failure must not fail the job.
        native = {"data": {}, "_meta": {"available": False, "error": str(exc)[:160]}}
    if isinstance(native, dict) and native.get("data"):
        return native
    return await provider.get_financials(code)


async def _announcements_with_native_fallback(code: str, provider) -> dict[str, Any]:
    """Use CNINFO dated disclosures before the Vibe fallback."""
    from src.infrastructure.market_data.cninfo_announcements import (
        fetch_cninfo_announcements,
    )

    try:
        native = await fetch_cninfo_announcements(code)
    except Exception as exc:  # Native transport failure must not fail the job.
        native = {"announcements": [], "_meta": {"available": False, "error": str(exc)[:160]}}
    if isinstance(native, dict) and native.get("announcements"):
        return native
    return await provider.get_announcements(code)


async def _valuation_with_native_fallback(code: str, provider) -> dict[str, Any]:
    """Use the Adaptive quote valuation snapshot before the Vibe fallback."""
    from src.infrastructure.market_data.native_quote_views import (
        get_native_valuation,
        quote_valuation_snapshot,
    )
    from src.infrastructure.market_data.source_manager import source_manager

    try:
        quote, provenance = await source_manager.get_eod_quote(code)
        native = quote_valuation_snapshot(quote, provenance)
        if native is not None:
            native["_meta"].update({
                "provider": "tushare" if provenance.provider == "tushare" else provenance.provider,
                "source_layer": (
                    "adaptive_tushare"
                    if provenance.provider == "tushare"
                    else "adaptive_source_manager_quote"
                ),
                "is_proxy": provenance.provider != "tushare",
            })
            return native
    except Exception:
        pass
    native = await get_native_valuation(code)
    if native is not None and native.get("data"):
        return native
    return await provider.get_valuation(code)


async def _fundflow_with_native_fallback(code: str, provider) -> dict[str, Any]:
    """Use the labelled Adaptive flow proxy before the Vibe fallback."""
    from config.settings import settings
    from src.infrastructure.market_data.native_quote_views import get_native_fundflow
    from src.infrastructure.market_data.source_manager import source_manager

    try:
        history, history_provenance = await source_manager.get_fund_flow_history(
            code, days=settings.DATA_COMPLETION_FLOW_DAYS
        )
        if history.get("available") and history.get("rows"):
            return {
                "data": history,
                "_meta": {
                    **history_provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare_flow_history",
                    "available": True,
                    "requested_days": history.get("requested_days"),
                    "row_count": history.get("row_count"),
                },
            }
    except Exception:
        pass
    try:
        evidence_packet = await source_manager.get_stock_evidence(code)
        flow = evidence_packet.get("fund_flow") or {}
        if flow:
            return {
                "data": flow,
                "_meta": {
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare",
                    "available": True,
                    "data_date": flow.get("data_date") or "",
                    "endpoint": flow.get("endpoint") or "moneyflow",
                    "is_realtime": False,
                    "is_proxy": False,
                },
            }
    except Exception:
        pass
    native = await get_native_fundflow(code)
    if native is not None and native.get("data"):
        return native
    return await provider.get_fundflow(code)


async def _dragon_tiger_with_native_fallback(code: str, provider) -> dict[str, Any]:
    """Use Eastmoney's dated billboard data before the Vibe fallback."""
    from src.infrastructure.market_data.source_manager import source_manager
    from src.infrastructure.market_data.eastmoney_billboard import (
        fetch_eastmoney_dragon_tiger,
    )

    try:
        data, provenance = await source_manager.get_dragon_tiger(code)
        if data.get("records"):
            return {
                "data": data,
                "_meta": {
                    **provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare",
                    "available": True,
                    "seat_detail_available": False,
                },
            }
    except Exception:
        pass
    try:
        native = await fetch_eastmoney_dragon_tiger(code)
    except Exception as exc:  # Native transport failure must not fail the job.
        native = {"data": {}, "_meta": {"available": False, "error": str(exc)[:160]}}
    if isinstance(native, dict) and native.get("data"):
        return native
    return await provider.get_dragon_tiger(code)


async def _reports_with_native_fallback(code: str, provider) -> dict[str, Any]:
    """Use Eastmoney's stock research reports before the Vibe fallback."""
    from src.infrastructure.market_data.eastmoney_reports import fetch_eastmoney_reports

    try:
        native = await fetch_eastmoney_reports(code, max_pages=2)
    except Exception as exc:  # Native transport failure must not fail the job.
        native = {"reports": [], "count": 0, "_meta": {"available": False, "error": str(exc)[:160]}}
    if isinstance(native, dict) and native.get("reports"):
        return native
    return await provider.get_reports(code)


async def _candidate_with_market_evidence(code: str) -> dict[str, Any]:
    """Prepare the evidence gate input for the unified deep-research route."""
    from config.settings import settings
    from src.infrastructure.market_data.source_manager import source_manager

    candidate: dict[str, Any] = {
        "stock_code": code,
        "market_sources": [],
        "sources": [],
        "market_reasons": [],
        "evidence_enrichment": {"attempted": True},
    }
    timeout_seconds = max(
        1.0,
        float(getattr(settings, "SCANNER_EVIDENCE_ENRICHMENT_TIMEOUT_SECONDS", 30.0)),
    )
    try:
        packet = await asyncio.wait_for(
            source_manager.get_stock_evidence(code), timeout=timeout_seconds
        )
    except Exception as exc:  # Evidence failure must remain fail-closed.
        candidate["market_reasons"] = [
            f"market_evidence_fetch_failed:{type(exc).__name__}"
        ]
        candidate["evidence_enrichment"]["error"] = str(exc)[:240]
        return candidate

    packet = packet if isinstance(packet, dict) else {}
    quote = packet.get("quote")
    quote = quote if isinstance(quote, dict) else {}
    provenance = packet.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    quote_provenance = provenance.get("quote")
    quote_provenance = quote_provenance if isinstance(quote_provenance, dict) else {}
    sources = [
        str(source).strip()
        for source in packet.get("sources") or []
        if str(source).strip()
    ]

    candidate["market_sources"] = sources
    candidate["sources"] = sources
    candidate["market_flow"] = packet.get("fund_flow") or {}
    candidate["fundamental_evidence_available"] = bool(packet.get("fundamental"))
    candidate["evidence_enrichment"].update({
        "sources": sources,
        "provenance": provenance,
    })
    if quote:
        candidate.update({
            "quote": quote,
            "stock_skill_evidence": {"quote": quote},
            "market_price": quote.get("price"),
            "market_pre_close": quote.get("pre_close") or quote.get("prev_close"),
            "market_change_pct": quote.get("change_pct"),
            "market_price_source": (
                quote.get("source")
                or quote_provenance.get("provider")
                or ""
            ),
            "market_price_date": (
                quote.get("data_date")
                or quote_provenance.get("data_date")
                or ""
            ),
            "market_price_fetched_at": (
                quote.get("fetched_at")
                or quote_provenance.get("fetched_at")
                or ""
            ),
        })
    else:
        candidate["market_reasons"].append("market_quote_missing")
    if not sources:
        candidate["market_reasons"].append("market_sources_missing")
    return candidate


def _trim_jobs() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    removable = sorted(
        (job for job in _JOBS.values() if job["status"] in {"completed", "failed"}),
        key=lambda job: job.get("updated_at", ""),
    )
    for job in removable[: max(0, len(_JOBS) - _MAX_JOBS)]:
        _JOBS.pop(job["job_id"], None)
        _JOB_STORE.delete(job["job_id"])


async def _run_job(job_id: str, request: UnifiedResearchRequest, code: str, trade_date: str) -> None:
    job = _JOBS[job_id]
    job.update({"status": "running", "stage": "initializing", "updated_at": _now()})
    _persist(job)
    try:
        result: dict[str, Any] = {
            "code": code,
            "trade_date": trade_date,
            "sources": {},
        }

        if request.include_vibe:
            job.update({"stage": "vibe_research", "progress": 25, "updated_at": _now()})
            _persist(job)
            from src.infrastructure.market_data.vibe_provider import get_vibe_provider

            provider = get_vibe_provider()
            labels = (
                "market_emotion",
                "top_volume",
                "announcements",
                "financials",
                "valuation",
                "fundflow",
                "dragon_tiger",
                "reports",
            )
            calls = (
                provider.get_sentiment_lite(),
                provider.get_top_volume_stocks(limit=10),
                _announcements_with_native_fallback(code, provider),
                _financials_with_native_fallback(code, provider),
                _valuation_with_native_fallback(code, provider),
                _fundflow_with_native_fallback(code, provider),
                _dragon_tiger_with_native_fallback(code, provider),
                _reports_with_native_fallback(code, provider),
            )
            semaphore = asyncio.Semaphore(3)
            values = await asyncio.gather(*(_safe(call, semaphore) for call in calls))
            result["sources"]["vibe_research"] = dict(zip(labels, values, strict=True))
        else:
            result["sources"]["vibe_research"] = {"available": False, "skipped": True}

        if request.include_tradingagents:
            job.update({"stage": "codex_terra", "progress": 60, "updated_at": _now()})
            _persist(job)
            from src.agents import codex_stock_analyzer

            # Always use the adapter's selected runtime.  The Adaptive venv
            # intentionally does not contain langgraph; when the isolated
            # TradingAgents venv is available, calling _run_one directly in
            # this process would fail even though the runtime check passed.
            deep_candidate = await _candidate_with_market_evidence(code)
            deep_results = await codex_stock_analyzer.analyze_candidates(
                [deep_candidate],
                trade_date,
                request.past_context,
                limit=1,
            )
            deep_result = deep_results[0] if deep_results else {
                "available": False,
                "error": "Codex-Terra 未返回分析结果",
                "source": "Codex-Terra Multi-Agent",
            }
            result["sources"]["tradingagents"] = deep_result
        else:
            result["sources"]["tradingagents"] = {"available": False, "skipped": True}

        deep = result["sources"]["tradingagents"]
        result["summary"] = {
            "direction": deep.get("direction", "neutral"),
            "rating": deep.get("rating", "Hold"),
            "score": deep.get("score", 50.0),
            "deep_analysis_available": bool(deep.get("available")),
            "data_sources": list(result["sources"]),
        }
        job.update({
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "result": result,
            "updated_at": _now(),
        })
        _persist(job)
    except Exception as exc:  # noqa: BLE001
        job.update({
            "status": "failed",
            "stage": "failed",
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "updated_at": _now(),
        })
        _persist(job)


@router.post("", status_code=202)
async def create_unified_research(request: UnifiedResearchRequest):
    code = _validate_code(request.code)
    trade_date = _validate_trade_date(request.trade_date)
    job_id = f"research-{uuid.uuid4().hex[:12]}"
    job = {
        "job_id": job_id,
        "code": code,
        "trade_date": trade_date,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "result": None,
    }
    _JOBS[job_id] = job
    _persist(job)
    _trim_jobs()
    asyncio.create_task(_run_job(job_id, request, code, trade_date))
    return _public_job(job)


@router.get("")
async def list_unified_research(code: str | None = None, limit: int = 20):
    safe_limit = max(1, min(limit, 100))
    normalized = _validate_code(code) if code else None
    jobs = list(_JOBS.values())
    if normalized:
        jobs = [job for job in jobs if job.get("code") == normalized]
    jobs.sort(key=lambda item: item.get("updated_at", item.get("created_at", "")), reverse=True)
    return {"jobs": [_public_job(job) for job in jobs[:safe_limit]], "count": min(len(jobs), safe_limit)}


@router.get("/{job_id}")
async def get_unified_research(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        job = _JOB_STORE.get(job_id)
        if job is not None:
            _JOBS[job_id] = job
    if job is None:
        raise HTTPException(status_code=404, detail="研究任务不存在或已过期")
    return _public_job(job)
