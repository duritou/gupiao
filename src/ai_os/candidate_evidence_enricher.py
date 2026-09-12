"""Bounded live-market evidence enrichment for technical candidates.

The broad scanner is intentionally local and deterministic.  This module is
the narrow bridge between that scan and expensive research: it asks the
configured source manager for fresh quotes only for the strongest candidates,
then records exactly what was attempted and what was returned.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from src.ai_os.execution_policy import flow_execution_metadata
from src.ai_os.score_guard import decision_ranking_score

QuoteFetcher = Callable[[list[str]], Awaitable[dict[str, Any]]]


def _code(value: Any) -> str:
    return str(value or "").strip().upper()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip().lower()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _source_key(quote: dict[str, Any], provenance: Any) -> str:
    source = str(quote.get("source") or "").strip().lower()
    if source and source not in {"unknown", "unavailable"}:
        return source
    provider = str(getattr(provenance, "provider", "") or "").strip().lower()
    return provider or ""


def _usable_quote(quote: Any) -> bool:
    return isinstance(quote, dict) and _number(quote.get("price")) > 0


def _update_evidence_json(decision: dict[str, Any], item: dict[str, Any]) -> None:
    try:
        payload = json.loads(str(decision.get("evidence") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    payload["market_discovery"] = {
        **(payload.get("market_discovery") or {}),
        "sources": list(item.get("sources") or []),
        "quote": item.get("quote") or {},
        "fundamental": item.get("fundamental") or {},
        "fund_flow": item.get("fund_flow") or {},
        "flow_fallback_observation": item.get("flow_fallback_observation") or {},
        "component_evidence_cache": item.get("component_evidence_cache") or {},
        "evidence_enrichment": item.get("evidence_enrichment") or {},
    }
    payload["stock_skill"] = {
        **(payload.get("stock_skill") or {}),
        "quote": item.get("quote") or {},
    }
    decision["evidence"] = json.dumps(payload, ensure_ascii=False)


def _apply_component_evidence(
    decision: dict[str, Any],
    item: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> None:
    """Attach non-quote evidence without requiring a usable quote."""
    packet = evidence or {}
    fundamental = packet.get("fundamental")
    if isinstance(fundamental, dict) and fundamental.get("available"):
        existing = item.get("fundamental")
        merged_fundamental = _merge_fundamental_evidence(existing, fundamental)
        item["fundamental"] = merged_fundamental
        decision["fundamentals"] = dict(merged_fundamental)
        decision["fundamental_evidence_available"] = True

    flow = packet.get("fund_flow") or item.get("fund_flow")
    if isinstance(flow, dict) and flow:
        item["fund_flow"] = dict(flow)
        decision["market_flow"] = dict(flow)
        decision["flow_status"] = str(flow.get("status") or "")
        flow_source = str(flow.get("source") or "tushare.moneyflow")
        decision["flow_source"] = flow_source
        item["sources"] = _unique([*(item.get("sources") or []), flow_source])
        item["market_sources"] = list(item["sources"])

    _record_flow_provenance_observation(decision, item, packet)
    decision["market_sources"] = list(item.get("sources") or [])
    decision.update(flow_execution_metadata(decision))
    decision["flow_status"] = decision["flow_state"]
    _update_evidence_json(decision, item)


def _record_flow_provenance_observation(
    decision: dict[str, Any],
    item: dict[str, Any],
    packet: dict[str, Any],
) -> None:
    """Separate an attempted provider failure from a candidate never queued.

    The execution policy remains fail-closed: ``provider_error`` is not one of
    the statuses that can qualify a probe.  This metadata only corrects the
    audit trail so a provider failure is not reported as a strategy veto.
    """
    flow = packet.get("fund_flow") or item.get("fund_flow") or {}
    if isinstance(flow, dict) and flow:
        flow_state = str(flow.get("status") or "").strip().lower()
        has_flow_value = any(
            flow.get(field) not in (None, "", "-")
            for field in ("main_net", "flow_signal")
        )
        if flow_state not in {"missing", "invalid"} and has_flow_value:
            return

    provenance = packet.get("provenance") or {}
    flow_provenance = provenance.get("fund_flow")
    if not isinstance(flow_provenance, dict):
        return
    provider = str(flow_provenance.get("provider") or "").strip().lower()
    error = str(
        flow_provenance.get("error")
        or flow_provenance.get("error_message")
        or ""
    ).strip()
    attempted = bool(
        error
        or flow_provenance.get("endpoint")
        or provider not in {"", "none", "unknown"}
    )
    if not attempted:
        return

    # Do not overwrite an explicit discovery-level fallback result.  A failed
    # quote enrichment with no such result is an actual attempted failure.
    existing_attempted = bool(
        decision.get("fallback_attempted")
        or decision.get("flow_fallback_attempted")
    )
    existing_status = str(
        decision.get("fallback_status")
        or decision.get("flow_fallback_status")
        or ""
    ).strip().lower()
    if existing_attempted or existing_status in {"exhausted", "proxy_only", "incomplete"}:
        return

    status = "provider_error" if error else "incomplete"
    observation = {
        "attempted": True,
        "status": status,
        "provider": provider or "unknown",
        "available": bool(flow_provenance.get("available")),
        "error": error[:240],
    }
    item["flow_fallback_observation"] = observation
    decision["flow_fallback_observation"] = dict(observation)
    decision["flow_fallback_attempted"] = True
    decision["flow_fallback_status"] = status
    decision["fallback_status"] = status


def _merge_fundamental_evidence(
    existing: Any, incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge a summary without discarding a complete multi-period cache."""
    previous = dict(existing) if isinstance(existing, dict) else {}
    merged = {**previous, **incoming}
    previous_statements = previous.get("statements")
    incoming_statements = incoming.get("statements")
    if isinstance(previous_statements, dict) and previous_statements:
        # A quote/enrichment request commonly returns only the latest
        # fina_indicator and income fields.  Preserve every cached statement
        # unless the incoming packet contains a statement history for it.
        statements = dict(previous_statements)
        if isinstance(incoming_statements, dict):
            for name, rows in incoming_statements.items():
                if rows:
                    statements[name] = rows
        merged["statements"] = statements
        previous_counts = previous.get("period_counts") or {}
        incoming_counts = incoming.get("period_counts") or {}
        merged["period_counts"] = {
            name: max(
                int(previous_counts.get(name, 0) or 0),
                int(incoming_counts.get(name, 0) or 0),
            )
            for name in set(previous_counts) | set(incoming_counts) | set(statements)
        }
        merged["requested_periods"] = max(
            int(previous.get("requested_periods", 0) or 0),
            int(incoming.get("requested_periods", 0) or 0),
        ) or previous.get("requested_periods") or incoming.get("requested_periods")
        merged["history_complete"] = all(
            int(merged["period_counts"].get(name, 0) or 0) >= int(
                merged.get("requested_periods") or 0
            )
            for name in ("income", "balancesheet", "cashflow", "fina_indicator")
        )
        merged["history_source_layer"] = previous.get("source_layer") or "adaptive_local_cache"
    return merged


def _apply_quote(
    decision: dict[str, Any],
    item: dict[str, Any],
    quote: dict[str, Any],
    provenance: Any = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    source = _source_key(quote, provenance)
    item["quote"] = dict(quote)
    item["sources"] = _unique([*(item.get("sources") or []), source])
    item["market_sources"] = list(item["sources"])
    item["data_sources"] = _unique([
        *(item.get("data_sources") or []),
        str(quote.get("source") or source),
    ])
    enrichment = dict(item.get("evidence_enrichment") or {})
    enrichment.update({
        "attempted": True,
        "quote_available": True,
        "quote_source": source,
        "quote_fetched_at": str(
            quote.get("fetched_at")
            or getattr(provenance, "fetched_at", "")
            or datetime.now(timezone.utc).isoformat()
        ),
        "quote_data_date": str(quote.get("data_date") or ""),
    })
    if provenance is not None and hasattr(provenance, "to_dict"):
        enrichment["provenance"] = provenance.to_dict()
    elif isinstance(provenance, dict):
        enrichment["provenance"] = dict(provenance)
    item["evidence_enrichment"] = enrichment
    decision["evidence_enrichment"] = dict(enrichment)

    _apply_component_evidence(decision, item, evidence)
    # Evidence enrichment happens after the broad selector's first pass.  The
    # flow packet is therefore newer than the initial derived fields; refresh
    # only the canonical execution metadata here.  This never recomputes a
    # score or turns positive flow into BUY by itself.
    decision.update(flow_execution_metadata(decision))
    decision["flow_status"] = decision["flow_state"]
    decision["market_price"] = _number(quote.get("price"))
    decision["market_pre_close"] = _number(
        quote.get("prev_close") or quote.get("pre_close")
    )
    decision["market_change_pct"] = _number(quote.get("change_pct"))
    decision["market_price_source"] = str(quote.get("source") or source)
    decision["market_price_date"] = str(quote.get("data_date") or "")
    decision["market_price_fetched_at"] = str(
        quote.get("fetched_at") or enrichment["quote_fetched_at"]
    )
    decision["market_price_exchange_at"] = str(
        quote.get("exchange_timestamp") or quote.get("exchange_at") or ""
    )
    decision["market_volume_ratio"] = _number(
        quote.get("volume_ratio") or quote.get("vol_ratio")
    )
    active_ratio = quote.get("active_volume_ratio")
    decision["market_active_volume_ratio"] = (
        _number(active_ratio) if active_ratio is not None else None
    )
    decision["stock_skill_evidence"] = {
        **(decision.get("stock_skill_evidence") or {}),
        "quote": dict(quote),
    }
    _update_evidence_json(decision, item)


async def _default_quote_fetcher(
    codes: list[str], *, concurrency: int, timeout_seconds: float
) -> dict[str, Any]:
    """Fetch quotes through SourceManager, which owns provider failover."""
    from src.infrastructure.market_data.source_manager import source_manager

    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def fetch_one(code: str) -> tuple[str, Any]:
        async with semaphore:
            try:
                evidence = await asyncio.wait_for(
                    source_manager.get_stock_evidence(code),
                    timeout=max(1.0, float(timeout_seconds)),
                )
                quote = evidence.get("quote") or {}
                if not _usable_quote(quote):
                    return code, {
                        "error": "quote_missing",
                        "evidence": evidence,
                        "provenance": evidence.get("provenance") or {},
                    }
                return code, {
                    "quote": quote,
                    "evidence": evidence,
                    "provenance": evidence.get("provenance") or {},
                }
            except Exception as exc:
                return code, {
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}"
                }

    pairs = await asyncio.gather(*(fetch_one(code) for code in codes))
    return dict(pairs)


async def _hydrate_cached_components(
    decisions: list[dict[str, Any]],
    discovery_by_code: dict[str, dict[str, Any]],
    *,
    flow_days: int = 20,
    financial_periods: int = 8,
    target_trade_date: str = "",
) -> dict[str, int]:
    """Attach complete local research packets before spending network budget."""
    from src.infrastructure.market_data.research_flow import aggregate_flow
    from src.infrastructure.storage.market_database import market_db

    if not target_trade_date:
        target_trade_date = await asyncio.to_thread(
            market_db.get_latest_market_date_on_or_before,
            datetime.now().date().isoformat(),
        )

    stats = {
        "cache_checked_count": 0,
        "cached_flow_count": 0,
        "cached_financial_count": 0,
        "cached_component_count": 0,
        "cached_stale_flow_count": 0,
    }
    semaphore = asyncio.Semaphore(8)

    async def hydrate(decision: dict[str, Any]) -> None:
        code = _code(decision.get("stock_code"))
        if not code:
            return
        async with semaphore:
            flow_rows, financials = await asyncio.gather(
                asyncio.to_thread(
                    market_db.get_fund_flow_history, code, flow_days
                ),
                asyncio.to_thread(
                    market_db.get_financial_history, code, financial_periods
                ),
            )
        stats["cache_checked_count"] += 1
        item = discovery_by_code.setdefault(code, {
            "stock_code": code,
            "stock_name": decision.get("stock_name") or code,
            "sources": [],
            "reasons": [],
            "concepts": [],
            "stock_skill": {},
        })
        packet: dict[str, Any] = {}

        expected = str(target_trade_date or "")[:10]
        if len(flow_rows) >= flow_days and flow_rows:
            latest = str(flow_rows[0].get("trade_date") or "")[:10]
            if expected and latest < expected:
                stats["cached_stale_flow_count"] += 1
            else:
                try:
                    packet["fund_flow"] = aggregate_flow(
                        flow_rows, flow_days, latest
                    )
                    packet["fund_flow"]["freshness_target_date"] = expected
                    packet["fund_flow"]["freshness_status"] = "available"
                    stats["cached_flow_count"] += 1
                except (KeyError, TypeError, ValueError):
                    stats["cached_stale_flow_count"] += 1

        statement_names = ("income", "balancesheet", "cashflow", "fina_indicator")
        period_counts = {
            name: len(financials.get(name) or []) for name in statement_names
        }
        if all(count >= financial_periods for count in period_counts.values()):
            packet["fundamental"] = {
                "available": True,
                "statements": financials,
                "period_counts": period_counts,
                "requested_periods": financial_periods,
                "source_layer": "adaptive_local_cache",
                "is_cached": True,
            }
            stats["cached_financial_count"] += 1

        if not packet:
            return
        _apply_component_evidence(decision, item, packet)
        components = sorted(packet)
        cache_metadata = {
            "attempted": False,
            "source_layer": "adaptive_local_cache",
            "components": components,
        }
        # Component hydration is local evidence preparation, not a quote
        # enrichment attempt.  Keep it separate so a candidate that is
        # skipped by the bounded quote queue remains correctly marked
        # ``not_scheduled`` without losing the cached research audit trail.
        item["component_evidence_cache"] = cache_metadata
        decision["component_evidence_cache"] = dict(cache_metadata)
        stats["cached_component_count"] += len(components)
        _update_evidence_json(decision, item)

    await asyncio.gather(*(hydrate(decision) for decision in decisions))
    return stats


async def enrich_candidate_evidence(
    decisions: list[dict[str, Any]],
    discovery_by_code: dict[str, dict[str, Any]],
    *,
    quote_fetcher: QuoteFetcher | None = None,
    max_candidates: int = 80,
    min_ranking_score: float = 65.0,
    concurrency: int = 4,
    timeout_seconds: float = 10.0,
    target_trade_date: str = "",
) -> dict[str, Any]:
    """Fill missing quote/source evidence for a bounded high-score queue.

    The function mutates the supplied decisions and discovery map so the
    existing score guard and deep allocator see the same evidence packet.  It
    never manufactures a quote and leaves an explicit failure reason when a
    provider cannot answer.
    """
    ordered = sorted(
        (item for item in decisions if _code(item.get("stock_code"))),
        key=lambda item: (
            -decision_ranking_score(item),
            -_number(item.get("technical_score")),
            -_number(item.get("discovery_score")),
            _code(item.get("stock_code")),
        ),
    )
    flow_batch_stats: dict[str, Any] = {"status": "disabled"}
    try:
        from config.settings import settings
        from src.infrastructure.storage import market_database as database_module
        from src.infrastructure.market_data.flow_batch_backfill import (
            backfill_fund_flow_history,
        )

        if bool(getattr(settings, "DATA_COMPLETION_FLOW_BATCH_ENABLED", True)):
            flow_batch_stats = await backfill_fund_flow_history(
                database_module.market_db,
                [_code(item.get("stock_code")) for item in ordered],
                target_date=target_trade_date,
                flow_days=int(getattr(settings, "DATA_COMPLETION_FLOW_DAYS", 20)),
                code_chunk_size=int(
                    getattr(settings, "DATA_COMPLETION_FLOW_BATCH_CODE_CHUNK", 100)
                ),
                max_requests=int(
                    getattr(settings, "DATA_COMPLETION_FLOW_BATCH_MAX_REQUESTS", 80)
                ),
                deadline_seconds=float(
                    getattr(
                        settings,
                        "DATA_COMPLETION_FLOW_BATCH_DEADLINE_SECONDS",
                        180.0,
                    )
                ),
            )
    except Exception as exc:
        flow_batch_stats = {
            "status": "failed",
            "error": f"{type(exc).__name__}:{str(exc)[:180]}",
        }
    cache_stats = await _hydrate_cached_components(
        ordered,
        discovery_by_code,
        target_trade_date=target_trade_date,
    )
    targets: list[dict[str, Any]] = []
    eligible_count = sum(
        decision_ranking_score(item) >= float(min_ranking_score)
        for item in ordered
    )
    quote_ready_count = 0
    not_scheduled: dict[str, int] = {}

    def mark_not_scheduled(
        decision: dict[str, Any], reason: str, *, score: float
    ) -> None:
        """Record a bounded-queue skip without calling it a provider failure."""
        normalized = str(reason or "not_scheduled")
        not_scheduled[normalized] = not_scheduled.get(normalized, 0) + 1
        decision["quote_enrichment_status"] = "not_scheduled"
        decision["quote_enrichment_reason"] = normalized
        decision["quote_enrichment_ranking_score"] = round(float(score), 1)
        decision["quote_enrichment_min_ranking_score"] = round(
            float(min_ranking_score), 1
        )
        flow = decision.get("market_flow") or {}
        flow_state = str(
            decision.get("flow_state")
            or decision.get("flow_status")
            or flow.get("status")
            or ""
        ).strip().lower()
        has_flow_value = any(
            flow.get(field) not in (None, "", "-")
            for field in ("main_net", "flow_signal")
        ) if isinstance(flow, dict) else False
        if flow_state not in {"positive", "negative"} and not has_flow_value:
            decision.setdefault("flow_fallback_observation", {
                "attempted": False,
                "status": "not_scheduled",
                "reason": normalized,
            })

    for decision in ordered:
        ranking_score = decision_ranking_score(decision)
        if ranking_score < float(min_ranking_score):
            mark_not_scheduled(
                decision, "below_min_ranking_score", score=ranking_score
            )
            continue
        code = _code(decision.get("stock_code"))
        item = discovery_by_code.setdefault(code, {
            "stock_code": code,
            "stock_name": decision.get("stock_name") or code,
            "sources": [],
            "reasons": [],
            "concepts": [],
            "stock_skill": {},
        })
        current_quote = item.get("quote") or {}
        current_sources = item.get("sources") or item.get("market_sources") or []
        has_fundamental = bool(
            isinstance(item.get("fundamental"), dict)
            and item.get("fundamental", {}).get("available")
        )
        has_flow = bool(isinstance(item.get("fund_flow"), dict) and item.get("fund_flow"))
        if _usable_quote(current_quote) and current_sources and has_fundamental and has_flow:
            # Copy the already-fetched quote onto the decision as well as the
            # discovery map; the deep analyzer receives the decision object.
            _apply_quote(decision, item, current_quote)
            decision["evidence_enrichment"].update({
                "attempted": False,
                "reason": "existing_remote_quote",
            })
            item["evidence_enrichment"].update({
                "attempted": False,
                "reason": "existing_remote_quote",
            })
            decision["quote_enrichment_status"] = "available"
            decision["quote_enrichment_reason"] = "existing_remote_quote"
            decision["quote_enrichment_ranking_score"] = round(ranking_score, 1)
            continue
        quote_ready_count += 1
        targets.append(decision)
        if len(targets) >= max(1, int(max_candidates)):
            break

    # Candidates above the ranking threshold that did not fit in the bounded
    # network queue are intentionally deferred, not failed.
    queued_codes = {
        _code(item.get("stock_code")) for item in targets
    }
    for decision in ordered:
        ranking_score = decision_ranking_score(decision)
        code = _code(decision.get("stock_code"))
        if decision.get("quote_enrichment_status") in {
            "available", "not_scheduled"
        }:
            continue
        if ranking_score < float(min_ranking_score):
            mark_not_scheduled(
                decision, "below_min_ranking_score", score=ranking_score
            )
            continue
        if (
            code not in queued_codes
            and not _usable_quote(
                (discovery_by_code.get(code) or {}).get("quote") or {}
            )
        ):
            mark_not_scheduled(
                decision, "enrichment_queue_budget_exhausted", score=ranking_score
            )

    stats: dict[str, Any] = {
        "flow_batch_backfill": flow_batch_stats,
        "eligible_count": eligible_count,
        "quote_ready_count": quote_ready_count,
        "attempted_count": len(targets),
        "quote_success_count": 0,
        "quote_failure_count": 0,
        "not_scheduled_count": sum(not_scheduled.values()),
        "not_scheduled_reason_counts": dict(not_scheduled),
        "source_counts": {},
        "errors": [],
        **cache_stats,
    }
    if not targets:
        return stats

    fetcher = quote_fetcher
    if fetcher is None:
        async def fetcher(codes: list[str]) -> dict[str, Any]:
            return await _default_quote_fetcher(
                codes,
                concurrency=concurrency,
                timeout_seconds=timeout_seconds,
            )

    codes = [_code(item.get("stock_code")) for item in targets]
    try:
        fetched = await fetcher(codes)
    except Exception as exc:
        fetched = {}
        stats["errors"].append(f"batch:{type(exc).__name__}:{str(exc)[:160]}")

    for decision in targets:
        code = _code(decision.get("stock_code"))
        item = discovery_by_code[code]
        response = (fetched or {}).get(code) or (fetched or {}).get(code.lower())
        quote: dict[str, Any] = {}
        provenance = None
        evidence: dict[str, Any] = {}
        error = "quote_missing"
        if isinstance(response, dict) and isinstance(response.get("quote"), dict):
            quote = response["quote"]
            provenance = response.get("provenance")
            evidence = response.get("evidence") or {}
        elif isinstance(response, dict):
            quote = response
        if _usable_quote(quote):
            _apply_quote(decision, item, quote, provenance, evidence)
            decision["quote_enrichment_status"] = "available"
            decision["quote_enrichment_reason"] = "fetched"
            decision["quote_enrichment_ranking_score"] = round(
                decision_ranking_score(decision), 1
            )
            stats["quote_success_count"] += 1
            source = _source_key(quote, provenance) or "unknown"
            stats["source_counts"][source] = stats["source_counts"].get(source, 0) + 1
            continue
        if isinstance(response, dict):
            error = str(response.get("error") or error)[:200]
            response_evidence = response.get("evidence")
            if isinstance(response_evidence, dict):
                _apply_component_evidence(decision, item, response_evidence)
        existing_quote = item.get("quote") or {}
        if _usable_quote(existing_quote):
            # A failed enrichment must not erase a previously verified quote;
            # preserve it while exposing the missing Tushare evidence.
            _apply_quote(decision, item, existing_quote)
        item["evidence_enrichment"] = {
            "attempted": True,
            "quote_available": False,
            "reason": "evidence_enrichment_quote_failed",
            "error": error,
            "provenance": (
                response.get("provenance") or {} if isinstance(response, dict) else {}
            ),
        }
        decision["evidence_enrichment"] = dict(item["evidence_enrichment"])
        decision["quote_enrichment_status"] = "failed"
        decision["quote_enrichment_reason"] = "evidence_enrichment_quote_failed"
        decision["quote_enrichment_ranking_score"] = round(
            decision_ranking_score(decision), 1
        )
        decision.setdefault("market_evidence_reasons", []).append(
            "evidence_enrichment_quote_failed"
        )
        stats["quote_failure_count"] += 1
        if len(stats["errors"]) < 20:
            stats["errors"].append(f"{code}:{error}")
        _update_evidence_json(decision, item)
    return stats
