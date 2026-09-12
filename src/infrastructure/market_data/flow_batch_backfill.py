"""Bounded, dated Tushare money-flow backfill for the research warehouse."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from uuid import uuid4


def _codes(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        code = str(value or "").strip().upper()
        if code and code not in result:
            result.append(code)
    return result


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}:{str(exc)[:180]}"


async def backfill_fund_flow_history(
    database: Any,
    codes: list[str],
    *,
    target_date: str,
    flow_days: int = 20,
    code_chunk_size: int = 100,
    max_requests: int = 80,
    deadline_seconds: float = 180.0,
) -> dict[str, Any]:
    """Fill missing code/date cells with sequential bounded batch requests.

    Existing rows are never overwritten with fabricated values.  Requests are
    grouped by trade date and code chunk so 300 candidates do not become 300
    independent per-stock history calls.  A resumable checkpoint prevents two
    processes from backfilling the same date window concurrently.
    """
    normalized_codes = _codes(codes)
    requested_days = max(1, min(int(flow_days), 20))
    target = str(target_date or "")[:10]
    if not normalized_codes or not target:
        return {
            "status": "not_started",
            "reason": "codes_or_target_date_missing",
            "code_count": len(normalized_codes),
            "requested_days": requested_days,
        }

    from src.infrastructure.market_data.tushare_provider import tushare_provider

    local_dates = await asyncio.to_thread(
        database.get_recent_market_dates, target, requested_days
    )
    dates = sorted({str(day)[:10] for day in local_dates if day}, reverse=True)
    calendar_error = ""
    if len(dates) < requested_days or target not in dates:
        try:
            dates = sorted({
                *dates,
                *await tushare_provider.recent_trade_dates(requested_days, target),
            }, reverse=True)
        except Exception as exc:
            calendar_error = _error(exc)
    dates = dates[:requested_days]
    if len(dates) < requested_days:
        return {
            "status": "incomplete",
            "reason": "trade_dates_insufficient",
            "code_count": len(normalized_codes),
            "requested_days": requested_days,
            "trade_dates": dates,
            "error": calendar_error,
        }

    coverage = await asyncio.to_thread(
        database.get_fund_flow_coverage, normalized_codes, dates
    )
    expected_absences = await asyncio.to_thread(
        database.get_expected_market_absences, normalized_codes, dates
    )
    excluded_cells = [
        {"code": code, "trade_date": day, "reason": reason}
        for code, cells in expected_absences.items()
        for day, reason in cells.items()
        if day not in coverage.get(code, set())
    ]
    missing_by_date = {
        day: [code for code in normalized_codes
              if day not in coverage.get(code, set())
              and day not in expected_absences.get(code, {})]
        for day in dates
    }
    missing_count_before = sum(len(items) for items in missing_by_date.values())
    if not missing_count_before:
        return {
            "status": "complete",
            "reason": "expected_nontrading_accounted" if excluded_cells else "local_cache_complete",
            "code_count": len(normalized_codes),
            "requested_days": requested_days,
            "trade_dates": dates,
            "missing_cells_before": 0,
            "missing_cells_after": 0,
            "requests_attempted": 0,
            "expected_absent_cells": excluded_cells,
            "expected_absent_count": len(excluded_cells),
        }

    job_name = "fund_flow_batch_backfill"
    target_name = "candidate_universe"
    partition_key = f"{target}:{requested_days}"
    lease_owner = f"flow-batch-{uuid4().hex}"
    claim = {"claimed": True}
    claimer = getattr(database, "try_claim_completion_checkpoint", None)
    if callable(claimer):
        claim = await asyncio.to_thread(
            claimer,
            job_name,
            target_name,
            partition_key,
            lease_owner,
            max(300.0, float(deadline_seconds) + 60.0),
        )
    if not claim.get("claimed"):
        return {
            "status": "already_running",
            "reason": "active_backfill_lease",
            "code_count": len(normalized_codes),
            "requested_days": requested_days,
            "trade_dates": dates,
            "missing_cells_before": missing_count_before,
            "lease_owner": claim.get("lease_owner", ""),
        }

    chunks: list[tuple[str, list[str]]] = []
    chunk_size = max(1, int(code_chunk_size))
    for day in dates:
        missing = missing_by_date[day]
        chunks.extend(
            (day, missing[index:index + chunk_size])
            for index in range(0, len(missing), chunk_size)
        )

    started = time.perf_counter()
    attempted = 0
    successful_requests = 0
    stored_rows = 0
    deferred_cells = 0
    errors: list[dict[str, Any]] = []
    empty_responses: list[dict[str, Any]] = []
    max_request_count = max(1, int(max_requests))
    deadline = max(1.0, float(deadline_seconds))
    for index, (trade_date, chunk) in enumerate(chunks):
        elapsed = time.perf_counter() - started
        if attempted >= max_request_count or elapsed >= deadline:
            deferred_cells += len(chunk)
            deferred_cells += sum(len(items) for _, items in chunks[index + 1:])
            break
        remaining = max(1.0, deadline - elapsed)
        attempted += 1
        try:
            payload = await asyncio.wait_for(
                tushare_provider.fetch_moneyflow_batch(chunk, trade_date),
                timeout=min(45.0, remaining),
            )
            rows = [
                dict(row) for row in (payload.data or [])
                if str(row.get("ts_code") or "").strip().upper() in set(chunk)
                and str(row.get("trade_date") or "")[:10] == trade_date
            ]
            stored = await asyncio.to_thread(
                database.upsert_fund_flow_history, rows
            )
            stored_rows += int(stored or 0)
            successful_requests += 1
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "tushare_empty:moneyflow":
                empty_responses.append({
                    "trade_date": trade_date, "codes": list(chunk),
                    "reason": "empty_unclassified",
                })
                continue
            errors.append({
                "trade_date": trade_date,
                "codes": list(chunk),
                "error": _error(exc),
            })
            if isinstance(exc, asyncio.TimeoutError):
                deferred_cells += sum(len(items) for _, items in chunks[index + 1:])
                break

    after = await asyncio.to_thread(
        database.get_fund_flow_coverage, normalized_codes, dates
    )
    missing_count_after = sum(
        1
        for day in dates
        for code in normalized_codes
        if day not in after.get(code, set())
        and day not in expected_absences.get(code, {})
    )
    status = "complete" if missing_count_after == 0 else (
        "failed" if errors and successful_requests == 0 else "partial"
    )
    progress = {
        "target_date": target,
        "requested_days": requested_days,
        "trade_dates": dates,
        "code_count": len(normalized_codes),
        "missing_cells_before": missing_count_before,
        "missing_cells_after": missing_count_after,
        "requests_planned": len(chunks),
        "requests_attempted": attempted,
        "successful_requests": successful_requests,
        "stored_rows": stored_rows,
        "deferred_cells": deferred_cells,
        "errors": errors[:20],
        "empty_responses": empty_responses[:20],
        "expected_absent_cells": excluded_cells,
        "expected_absent_count": len(excluded_cells),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "lease_owner": lease_owner,
        "updated_at": datetime.now().isoformat(),
    }
    saver = getattr(database, "save_completion_checkpoint", None)
    if callable(saver):
        await asyncio.to_thread(
            saver, job_name, target_name, partition_key, progress, status
        )
    return {"status": status, **progress}
