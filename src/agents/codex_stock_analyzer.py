"""Codex-only, evidence-first deep analysis for scheduled A-share research."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable

from config.settings import settings
from src.ai_os.deep_research_identity import deep_input_fingerprint
from src.agents.evidence_dossier import EvidenceDossierCache, collect_evidence_dossier
from src.ai_os.evidence_policy import assess_evidence
from src.ai_os.numeric_policy import clamp_finite
from src.infrastructure.ai import ai_router
from src.infrastructure.ai.codex_cli import codex_cli_status

_RATING_SIGNAL = {
    "Buy": ("buy", 85.0),
    "Overweight": ("buy", 72.0),
    "Hold": ("neutral", 50.0),
    "Underweight": ("sell", 35.0),
    "Sell": ("sell", 20.0),
}


def availability_status() -> dict[str, Any]:
    """Return non-secret readiness for the saved-login Codex runtime."""
    cli = codex_cli_status(settings.CODEX_CLI_PATH)
    installed_and_logged_in = bool(
        cli["executable_found"] and cli["auth_file_present"]
    )
    available = bool(installed_and_logged_in and cli.get("runtime_writable"))
    if available:
        reasons = []
    elif installed_and_logged_in:
        reasons = ["codex_runtime_not_writable"]
    else:
        reasons = ["codex_cli_or_login_missing"]
    return {
        "available": available,
        "runtime": "codex_cli" if available else "unavailable",
        "provider": "codex_cli",
        "model": settings.CODEX_MODEL,
        "max_concurrency": settings.CODEX_ANALYSIS_MAX_CONCURRENCY,
        "codex_cli": cli,
        "reasons": reasons,
    }


def _compact(value: Any, *, depth: int = 0) -> Any:
    """Bound provider payloads before placing them in a model prompt."""
    if depth >= 4:
        return (
            str(value)[:300]
            if isinstance(value, dict | list | tuple)
            else value
        )
    if isinstance(value, dict):
        return {
            str(key)[:80]: (
                [_compact(bar, depth=depth + 2) for bar in item[-60:]]
                if key == "kline" and isinstance(item, list)
                else item
                if key == "ai_consumption_summary"
                else _compact(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, list | tuple):
        return [_compact(item, depth=depth + 1) for item in list(value)[:20]]
    if isinstance(value, str):
        return value[:1200]
    return value


def _evidence_consumption_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep a compact, auditable view of the multi-period inputs sent to AI."""
    dossier = evidence.get("fact_dossier") or {}
    items = dossier.get("items") or {}
    financial = ((items.get("financials") or {}).get("payload") or {})
    financial_data = financial.get("data") if isinstance(financial, dict) else {}
    statements = financial_data.get("statements") if isinstance(financial_data, dict) else {}
    statement_summary: dict[str, Any] = {}
    if isinstance(statements, dict):
        for name, rows in statements.items():
            if not isinstance(rows, list):
                continue
            samples = []
            for row in rows[:8]:
                if not isinstance(row, dict):
                    continue
                samples.append({
                    key: row.get(key)
                    for key in (
                        "end_date", "ann_date", "f_ann_date", "total_revenue",
                        "revenue", "n_income", "n_income_attr_p", "eps", "roe",
                        "net_profit", "tr_yoy", "netprofit_yoy",
                        "total_assets", "total_liab", "total_hldr_eqy_exc_min_int",
                        "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act",
                        "c_cash_equ_end_period", "report_type", "update_flag",
                    )
                    if row.get(key) not in (None, "")
                })
            statement_summary[name] = {
                "actual_period_count": len(rows),
                "report_dates": [
                    str(row.get("end_date") or row.get("report_date") or "")
                    for row in rows[:8] if isinstance(row, dict)
                ],
                "period_samples": samples,
            }
    flow = ((items.get("fundflow") or {}).get("payload") or {})
    flow_data = flow.get("data") if isinstance(flow, dict) else {}
    flow_rows = flow_data.get("rows") if isinstance(flow_data, dict) else []
    summary = {
        "financials": {
            "status": (items.get("financials") or {}).get("status"),
            "source_layer": ((items.get("financials") or {}).get("payload") or {})
            .get("_meta", {}).get("source_layer"),
            "requested_periods": financial_data.get("requested_periods")
            if isinstance(financial_data, dict) else None,
            "period_counts": financial_data.get("period_counts") or {}
            if isinstance(financial_data, dict) else {},
            "history_complete": bool(financial_data.get("history_complete"))
            if isinstance(financial_data, dict) else False,
            "statements": statement_summary,
        },
        "fund_flow": {
            "status": (items.get("fundflow") or {}).get("status"),
            "source_layer": ((items.get("fundflow") or {}).get("payload") or {})
            .get("_meta", {}).get("source_layer"),
            "requested_days": flow_data.get("requested_days")
            if isinstance(flow_data, dict) else None,
            "row_count": len(flow_rows) if isinstance(flow_rows, list) else 0,
            "rows": flow_rows[:20] if isinstance(flow_rows, list) else [],
        },
    }
    component_summary: dict[str, Any] = {}
    for label, item in items.items():
        if not isinstance(item, dict):
            component_summary[str(label)] = {
                "status": "unknown",
                "available": False,
                "submitted": True,
            }
            continue
        payload = item.get("payload")
        metadata = payload.get("_meta") if isinstance(payload, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        record_count = None
        if isinstance(payload, dict):
            for key in ("rows", "records", "announcements", "reports"):
                value = payload.get(key)
                if isinstance(value, list):
                    record_count = len(value)
                    break
            if record_count is None and isinstance(payload.get("data"), dict):
                data = payload["data"]
                for key in ("rows", "records", "announcements", "reports"):
                    value = data.get(key)
                    if isinstance(value, list):
                        record_count = len(value)
                        break
        component_summary[str(label)] = {
            "status": str(item.get("status") or "unknown"),
            "available": bool(item.get("available")),
            "submitted": True,
            "stale": bool(item.get("stale")),
            "source_layer": str(metadata.get("source_layer") or ""),
            "provider": str(metadata.get("provider") or ""),
            "fetched_at": str(item.get("fetched_at") or metadata.get("fetched_at") or ""),
            "error": str(item.get("error") or metadata.get("error") or "")[:240],
            "record_count": record_count,
        }
    summary["components"] = component_summary
    summary["submitted_fields"] = [
        "candidate", "kline", "kline_summary", "kline_provenance",
        "fact_dossier", "ai_consumption_summary", "research_calendar",
    ]
    summary["input_sha256"] = hashlib.sha256(
        json.dumps(
            summary, ensure_ascii=False, sort_keys=True, default=str
        ).encode("utf-8")
    ).hexdigest()
    return summary


async def _safe(awaitable: Awaitable[Any], timeout: float = 15.0) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except Exception as exc:  # Data gaps are evidence, not a pipeline crash.
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


async def _collect_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    """Collect bounded non-LLM evidence using the existing local data layer."""
    from src.infrastructure.market_data.cninfo_announcements import (
        fetch_cninfo_announcements,
    )
    from src.infrastructure.market_data.native_quote_views import (
        get_native_fundflow,
        get_native_valuation,
        quote_valuation_snapshot,
    )
    from src.infrastructure.market_data.sina_financials import fetch_sina_financials
    from src.infrastructure.market_data.source_manager import source_manager
    from src.infrastructure.market_data.vibe_provider import get_vibe_provider

    code = str(candidate.get("stock_code") or candidate.get("code") or "")
    plain_code = "".join(char for char in code if char.isdigit())[-6:]
    evidence: dict[str, Any] = {
        "candidate": {
            key: candidate.get(key)
            for key in (
                "stock_code", "stock_name", "technical_score", "discovery_score",
                "fusion_score", "macd_score", "rsi_score", "kdj_score", "ma_score",
                "volume_score", "market_price", "market_pre_close",
                "market_change_pct", "market_price_date", "market_sources",
                "market_reasons", "market_flow", "stock_skill_evidence",
            )
        }
    }

    kline_result = await _safe(source_manager.get_kline(code, count=80), timeout=20.0)
    if isinstance(kline_result, tuple):
        bars, provenance = kline_result
        ordered = sorted(bars or [], key=lambda bar: str(bar.get("date") or ""))
        evidence["kline"] = ordered[-60:]
        evidence["kline_summary"] = {
            "received_count": len(ordered),
            "visible_count": len(evidence["kline"]),
            "first_date": ordered[0].get("date", "") if ordered else "",
            "last_date": ordered[-1].get("date", "") if ordered else "",
            "visible_first_date": evidence["kline"][0].get("date", "") if ordered else "",
            "visible_last_date": ordered[-1].get("date", "") if ordered else "",
            "available": bool(ordered),
        }
        evidence["kline_provenance"] = (
            provenance.to_dict() if hasattr(provenance, "to_dict") else str(provenance)
        )
    else:
        evidence["kline"] = kline_result
        evidence["kline_summary"] = {"available": False, "error": kline_result}

    provider = get_vibe_provider()

    async def financials_with_native_fallback() -> dict[str, Any]:
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
            native = await fetch_sina_financials(plain_code)
        except Exception as exc:  # Native transport failure must not block the dossier.
            native = {
                "data": {},
                "_meta": {"available": False, "error": str(exc)[:160]},
            }
        if isinstance(native, dict) and native.get("data"):
            return native
        return await provider.get_financials(plain_code)

    async def valuation_with_native_fallback() -> dict[str, Any]:
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
        native = await get_native_valuation(plain_code)
        if native is not None and native.get("data"):
            return native
        return await provider.get_valuation(plain_code)

    async def fundflow_with_native_fallback() -> dict[str, Any]:
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
                        "is_realtime": False,
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
        native = await get_native_fundflow(plain_code)
        if native is not None and native.get("data"):
            return native
        return await provider.get_fundflow(plain_code)

    async def announcements_with_native_fallback() -> dict[str, Any]:
        try:
            native = await fetch_cninfo_announcements(plain_code)
        except Exception as exc:  # Native transport failure must not block the dossier.
            native = {
                "announcements": [],
                "_meta": {"available": False, "error": str(exc)[:160]},
            }
        if isinstance(native, dict) and native.get("announcements"):
            return native
        return await provider.get_announcements(plain_code)

    async def dragon_tiger_with_native_fallback() -> dict[str, Any]:
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
            from src.infrastructure.market_data.eastmoney_billboard import (
                fetch_eastmoney_dragon_tiger,
            )

            native = await fetch_eastmoney_dragon_tiger(plain_code)
        except Exception as exc:  # Native transport failure must not block the dossier.
            native = {"data": {}, "_meta": {"available": False, "error": str(exc)[:160]}}
        if isinstance(native, dict) and native.get("data"):
            return native
        return await provider.get_dragon_tiger(plain_code)

    async def reports_with_native_fallback() -> dict[str, Any]:
        try:
            from src.infrastructure.market_data.eastmoney_reports import fetch_eastmoney_reports

            native = await fetch_eastmoney_reports(plain_code, max_pages=2)
        except Exception as exc:  # Native transport failure must not block the dossier.
            native = {"reports": [], "count": 0, "_meta": {"available": False, "error": str(exc)[:160]}}
        if isinstance(native, dict) and native.get("reports"):
            return native
        return await provider.get_reports(plain_code)

    cache_path = os.getenv("EVIDENCE_DOSSIER_CACHE_PATH", "")
    cache = EvidenceDossierCache(
        Path(cache_path)
        if cache_path
        else Path(__file__).resolve().parents[2] / "data" / "evidence_last_good.json"
    )
    evidence["fact_dossier"] = await collect_evidence_dossier(
        code,
        [
            ("financials", financials_with_native_fallback),
            ("valuation", valuation_with_native_fallback),
            ("announcements", announcements_with_native_fallback),
            ("fundflow", fundflow_with_native_fallback),
            ("dragon_tiger", dragon_tiger_with_native_fallback),
            ("research_reports", reports_with_native_fallback),
        ],
        cache,
    )
    evidence["ai_consumption_summary"] = _evidence_consumption_summary(evidence)
    return _compact(evidence)


def _extract_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    candidates = [raw]
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _analysis_prompt(
    candidate: dict[str, Any], evidence: dict[str, Any], trade_date: str, past_context: str
) -> str:
    payload = {
        "trade_date": trade_date,
        "stock": {
            "code": candidate.get("stock_code") or candidate.get("code"),
            "name": candidate.get("stock_name") or candidate.get("name"),
        },
        "evidence": evidence,
        "recent_learning": str(past_context or "")[-5000:],
    }
    return (
        "请以技术分析师、新闻/公告分析师、基本面分析师、多头、空头和风险经理"
        "六个角色完成一次A股深度研究，然后由组合经理给出唯一结论。只能使用输入证据，"
        "不得联网、读取文件或编造缺失数据。日线研究按research_calendar中的最近已完成交易日"
        "判断新鲜度，周末/节假日的上一交易日日线不因自然日变化而滞后；日历未验证则明确未知。"
        "日线不是盘中可成交报价，开仓必须另取执行时有效报价。日线早于已验证截止日、证据矛盾、涨停追高、"
        "财务/公告证据不足时不得给Buy或Overweight。单票正常仓位上限20%，T+1风险必须纳入。"
        "只返回一个JSON对象，不要Markdown："
        '{"rating":"Buy|Overweight|Hold|Underweight|Sell","score":0,'
        '"thesis":"支持与反对证据摘要","decision":"最终决策及风险",'
        '"trader_plan":"买卖条件、仓位、止损/退出条件","evidence_gaps":["缺失项"]}\n\n'
        "JSON还必须包含falsification_conditions数组、weakest_assumption、"
        "monitoring_signals数组和review_by；数据源失败与确实无记录不得混为一谈。\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


async def _analyze_one(
    candidate: dict[str, Any], trade_date: str, past_context: str
) -> dict[str, Any]:
    code = str(candidate.get("stock_code") or candidate.get("code") or "")
    started = time.perf_counter()
    evidence = await _collect_evidence(candidate)
    from src.infrastructure.market_data.research_flow import completed_research_day

    calendar = await completed_research_day()
    evidence["research_calendar"] = {
        "analysis_date": trade_date,
        "latest_completed_trading_day": calendar.day.isoformat() if calendar.day else None,
        "source": calendar.source,
        "verified": bool(calendar.day and not calendar.degraded),
        "scope": "daily_research_not_execution_quote",
    }
    system_prompt = (
        "你是只读的A股多角色投资研究协调器。严格依据输入证据，输出可解析JSON；"
        "不保证收益，不执行交易，不得把数据缺失解释为利好。"
    )
    prompt = _analysis_prompt(candidate, evidence, trade_date, past_context)
    request_payload = json.dumps(
        {"system_prompt": system_prompt, "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    analysis_input_sha256 = hashlib.sha256(
        request_payload.encode("utf-8")
    ).hexdigest()
    response = await ai_router.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        primary_provider=settings.AI_PRIMARY_PROVIDER,
        allow_fallback=False,
    )
    parsed = _extract_object(response.text)
    rating = str(parsed.get("rating") or "Hold").strip().title()
    if rating not in _RATING_SIGNAL:
        raise RuntimeError("Codex returned an invalid rating")
    direction, default_score = _RATING_SIGNAL[rating]
    try:
        # A NaN here would clamp to 100, i.e. garbage input becomes a top
        # score; non-finite values fall back to the rating's own default.
        score = clamp_finite(
            parsed.get("score", default_score), 0.0, 100.0, default_score
        )
    except (TypeError, ValueError):
        score = default_score
    if direction == "buy":
        score = max(default_score, score)
    decision = str(parsed.get("decision") or "").strip()
    thesis = str(parsed.get("thesis") or "").strip()
    trader_plan = str(parsed.get("trader_plan") or "").strip()
    if not decision or not thesis:
        raise RuntimeError("Codex returned an incomplete deep analysis")
    return {
        "available": True,
        "stock_code": code,
        "rating": rating,
        "direction": direction,
        "score": round(score, 1),
        "decision": decision,
        "thesis": thesis,
        "trader_plan": trader_plan,
        "evidence_gaps": parsed.get("evidence_gaps") or [],
        "kline_evidence": {
            **evidence.get("kline_summary", {}),
            "provenance": evidence.get("kline_provenance", {}),
        },
        "deep_evidence_consumption": {
            **(evidence.get("ai_consumption_summary", {}) or {}),
            "analysis_input_sha256": analysis_input_sha256,
            "analysis_input_hash_scope": "system_prompt_plus_user_prompt",
            "analysis_input_chars": len(request_payload),
        },
        "deep_input_fingerprint": deep_input_fingerprint(
            candidate,
            trade_date,
            strategy_version=str(candidate.get("strategy_version") or ""),
            model=settings.CODEX_MODEL,
        ),
        "falsification_conditions": parsed.get("falsification_conditions") or [],
        "weakest_assumption": str(parsed.get("weakest_assumption") or ""),
        "monitoring_signals": parsed.get("monitoring_signals") or [],
        "review_by": str(parsed.get("review_by") or ""),
        "source": "Codex-Terra Multi-Agent",
        "provider": response.provider,
        "model": response.model,
        "runtime": "codex_cli",
        "duration_seconds": round(time.perf_counter() - started, 2),
    }


async def analyze_candidates(
    candidates: list[dict[str, Any]],
    trade_date: str,
    past_context: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Analyze a bounded candidate set with one Codex-Terra call per stock."""
    selected = candidates[: max(0, int(limit))]
    status = availability_status()
    if not status["available"]:
        reason = ", ".join(status["reasons"])
        return [
            {
                "available": False,
                "stock_code": str(item.get("stock_code") or item.get("code") or ""),
                "error": f"Codex unavailable: {reason}",
                "error_type": "RuntimeUnavailable",
                "runtime": "unavailable",
                "source": "Codex-Terra Multi-Agent",
                "provider": "codex_cli",
                "model": settings.CODEX_MODEL,
            }
            for item in selected
        ]

    blocked = []
    eligible = []
    for item in selected:
        assessment = assess_evidence(item)
        if assessment.deep_eligible:
            eligible.append(item)
            continue
        blocked.append({
            "available": False,
            "stock_code": str(item.get("stock_code") or item.get("code") or ""),
            "error": "Deep analysis skipped: market evidence is incomplete",
            "error_type": "MarketEvidenceUnavailable",
            "evidence_status": "incomplete",
            "market_evidence_complete": False,
            "market_evidence_sources": list(assessment.market_sources),
            "market_evidence_reasons": list(assessment.reasons),
            "runtime": "codex_cli",
            "source": "Codex-Terra Multi-Agent",
            "provider": "codex_cli",
            "model": settings.CODEX_MODEL,
        })
    semaphore = asyncio.Semaphore(max(1, settings.CODEX_ANALYSIS_MAX_CONCURRENCY))

    async def guarded(candidate: dict[str, Any]) -> dict[str, Any]:
        code = str(candidate.get("stock_code") or candidate.get("code") or "")
        async with semaphore:
            try:
                return await _analyze_one(candidate, trade_date, past_context)
            except Exception as exc:
                return {
                    "available": False,
                    "stock_code": code,
                    "error": str(exc)[:240],
                    "error_type": type(exc).__name__,
                    "runtime": "codex_cli",
                    "source": "Codex-Terra Multi-Agent",
                    "provider": "codex_cli",
                    "model": settings.CODEX_MODEL,
                }

    analyzed = list(await asyncio.gather(*(guarded(item) for item in eligible)))
    by_code = {
        str(item.get("stock_code") or "").upper(): item
        for item in [*blocked, *analyzed]
    }
    return [
        by_code.get(str(item.get("stock_code") or item.get("code") or "").upper())
        for item in selected
    ]
