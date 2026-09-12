"""Read-only baseline audit for the Tushare data-completion project.

The database is opened read-only. The optional Tushare probe uses one stock
and one recent trading day, so this audit measures permission availability
without downloading or changing market data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _is_a_share(code: str) -> bool:
    code = str(code or "").upper()
    return (
        (code.endswith(".SH") and code[:3] in {"600", "601", "603", "605", "688", "689"})
        or (code.endswith(".SZ") and code[:3] in {"000", "001", "002", "003", "300", "301"})
    )


def _safe_json(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def audit_database(
    db_path: Path, required_bars: int = 250,
    financial_periods: int = 8, flow_days: int = 20,
    run_id: str = "",
) -> dict[str, Any]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        latest_date = str(
            conn.execute("SELECT MAX(trade_date) AS d FROM market_daily").fetchone()["d"] or ""
        )
        daily_rows = conn.execute(
            "SELECT ts_code, COUNT(*) AS n FROM market_daily GROUP BY ts_code"
        ).fetchall()
        daily_codes = {str(row["ts_code"]) for row in daily_rows if _is_a_share(row["ts_code"])}
        bar_counts = {str(row["ts_code"]): int(row["n"] or 0) for row in daily_rows}
        categories = Counter(
            "sufficient" if count >= required_bars else
            "core_only" if count >= 20 else
            "insufficient" if count > 0 else "missing"
            for code, count in bar_counts.items() if _is_a_share(code)
        )
        latest_codes = {
            str(row["ts_code"])
            for row in conn.execute(
                "SELECT DISTINCT ts_code FROM market_daily WHERE trade_date=?", (latest_date,)
            ).fetchall()
            if _is_a_share(row["ts_code"])
        }

        basic_codes: set[str] = set()
        basic_missing = {"market_cap_yi": 0, "turnover_pct": 0}
        if _table_exists(conn, "stock_basic"):
            basic_rows = conn.execute(
                "SELECT ts_code, market_cap_yi, turnover_pct FROM stock_basic"
            ).fetchall()
            basic_codes = {str(row["ts_code"]) for row in basic_rows if _is_a_share(row["ts_code"])}
            basic_missing = {
                "market_cap_yi": sum(
                    row["market_cap_yi"] is None for row in basic_rows if _is_a_share(row["ts_code"])
                ),
                "turnover_pct": sum(
                    row["turnover_pct"] is None for row in basic_rows if _is_a_share(row["ts_code"])
                ),
            }
        latest_basic_missing = {"market_cap_yi": 0, "turnover_pct": 0}
        if latest_codes and _table_exists(conn, "stock_basic"):
            placeholders = ",".join("?" for _ in latest_codes)
            rows = conn.execute(
                f"SELECT market_cap_yi, turnover_pct FROM stock_basic WHERE ts_code IN ({placeholders})",
                tuple(sorted(latest_codes)),
            ).fetchall()
            latest_basic_missing = {
                "market_cap_yi": sum(row["market_cap_yi"] is None for row in rows),
                "turnover_pct": sum(row["turnover_pct"] is None for row in rows),
            }

        requested_run_id = str(run_id or "").strip()
        candidate_codes: set[str] = set()
        flow_counts: Counter[str] = Counter()
        decision_analysis: dict[str, dict[str, Any]] = {}
        decision_count = 0
        latest_decision_date = ""
        matched_run_ids: set[str] = set()
        if _table_exists(conn, "strategy_decision"):
            all_decisions = conn.execute(
                "SELECT stock_code, decision_date, analysis_json FROM strategy_decision"
            ).fetchall()
            decoded_decisions = []
            for row in all_decisions:
                analysis = _safe_json(row["analysis_json"])
                observed_run_id = str(analysis.get("run_id") or "").strip()
                if observed_run_id:
                    matched_run_ids.add(observed_run_id)
                decoded_decisions.append((row, analysis))
            if requested_run_id:
                decisions = [
                    (row, analysis)
                    for row, analysis in decoded_decisions
                    if str(analysis.get("run_id") or "").strip()
                    == requested_run_id
                ]
                latest_decision_date = max(
                    (str(row["decision_date"] or "") for row, _ in decisions),
                    default="",
                )
            else:
                latest_decision_date = str(
                    conn.execute(
                        "SELECT MAX(decision_date) FROM strategy_decision"
                    ).fetchone()[0] or ""
                )
                decisions = [
                    (row, analysis)
                    for row, analysis in decoded_decisions
                    if str(row["decision_date"] or "") == latest_decision_date
                ]
            decision_count = len(decisions)
            for row, analysis in decisions:
                code = str(row["stock_code"] or "").upper()
                candidate_codes.add(code)
                decision_analysis[code] = analysis
                flow_counts[str(analysis.get("flow_state") or "missing")] += 1

        run_task_context: dict[str, Any] = {}
        if requested_run_id and _table_exists(conn, "task_execution"):
            task_rows = conn.execute(
                """SELECT task_name, status, started_at, completed_at,
                          duration_seconds, output_json
                     FROM task_execution ORDER BY id ASC"""
            ).fetchall()
            for row in task_rows:
                output = _safe_json(row["output_json"])
                quality = output.get("market_data_quality")
                if not isinstance(quality, dict):
                    quality = {}
                observed = {
                    "run_id": output.get("run_id") or quality.get("run_id"),
                    "research_backfill_task": quality.get("research_backfill_task"),
                }
                backfill = observed["research_backfill_task"]
                if isinstance(backfill, dict) and not observed["run_id"]:
                    observed["run_id"] = backfill.get("run_id")
                if str(observed.get("run_id") or "").strip() != requested_run_id:
                    continue
                run_task_context = {
                    "task_name": row["task_name"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "duration_seconds": row["duration_seconds"],
                    "research_backfill_task": backfill or {},
                }

        financial_history = {
            "table_present": _table_exists(conn, "financial_statement_history"),
            "row_count": 0,
            "stock_count": 0,
        }
        if financial_history["table_present"]:
            row = conn.execute(
                "SELECT COUNT(*) AS n, COUNT(DISTINCT ts_code) AS stocks FROM financial_statement_history"
            ).fetchone()
            financial_history.update(
                row_count=int(row["n"] or 0), stock_count=int(row["stocks"] or 0)
            )

        flow_history = {"table_present": _table_exists(conn, "fund_flow_history"), "row_count": 0}
        if flow_history["table_present"]:
            flow_history["row_count"] = int(
                conn.execute("SELECT COUNT(*) FROM fund_flow_history").fetchone()[0] or 0
            )

        candidate_coverage: dict[str, Any] = {
            "requested": len(candidate_codes),
            "required_bars": required_bars,
            "required_financial_periods": financial_periods,
            "required_flow_days": flow_days,
            "daily_sufficient": 0, "adjustment_factor_sufficient": 0,
            "financial_complete": 0, "flow_sufficient": 0,
            "details": [],
        }
        for code in sorted(candidate_codes):
            analysis = decision_analysis.get(code) or {}
            daily = conn.execute(
                "SELECT COUNT(*) AS n FROM market_daily WHERE ts_code=?", (code,)
            ).fetchone()["n"]
            factor = 0
            if _table_exists(conn, "market_adjustment_factor"):
                factor = conn.execute(
                    "SELECT COUNT(*) AS n FROM market_adjustment_factor WHERE ts_code=?",
                    (code,),
                ).fetchone()["n"]
            statement_counts: dict[str, int] = {}
            if _table_exists(conn, "financial_statement_history"):
                statement_counts = {
                    str(row["statement_type"]): int(row["n"] or 0)
                    for row in conn.execute(
                        """SELECT statement_type, COUNT(DISTINCT report_date) AS n
                             FROM financial_statement_history
                            WHERE ts_code=? AND data_status='available'
                            GROUP BY statement_type""",
                        (code,),
                    ).fetchall()
                }
            flow = 0
            flow_latest_date = ""
            if _table_exists(conn, "fund_flow_history"):
                flow = conn.execute(
                    "SELECT COUNT(*) AS n FROM fund_flow_history WHERE ts_code=? AND data_status='available'",
                    (code,),
                ).fetchone()["n"]
                flow_latest_date = str(
                    conn.execute(
                        """SELECT MAX(trade_date) FROM fund_flow_history
                           WHERE ts_code=? AND data_status='available'""",
                        (code,),
                    ).fetchone()[0] or ""
                )
            daily_ok = int(daily or 0) >= required_bars
            factor_ok = int(factor or 0) >= required_bars
            financial_ok = all(
                statement_counts.get(name, 0) >= financial_periods
                for name in ("income", "balancesheet", "cashflow", "fina_indicator")
            )
            flow_ok = int(flow or 0) >= flow_days and (
                not latest_date or flow_latest_date >= latest_date
            )
            enrichment = analysis.get("evidence_enrichment") or {}
            attempted = bool(enrichment.get("attempted"))
            quote_available = bool(enrichment.get("quote_available"))
            ranking_score = analysis.get("ranking_score")
            missing_reasons: list[str] = []
            if not flow_ok:
                missing_reasons.append(
                    "local_flow_stale"
                    if int(flow or 0) >= flow_days and flow_latest_date < latest_date
                    else "local_flow_insufficient"
                )
            elif str(analysis.get("flow_state") or "missing") in {"missing", "invalid"}:
                missing_reasons.append("local_flow_not_attached")
            if str(analysis.get("flow_state") or "missing") in {"missing", "invalid"}:
                if attempted:
                    missing_reasons.append(
                        "quote_enrichment_failed" if not quote_available
                        else "flow_not_returned_by_evidence_path"
                    )
                else:
                    missing_reasons.append("not_scheduled_for_network_enrichment")
            if ranking_score is not None and float(ranking_score or 0) < 65:
                missing_reasons.append("below_immediate_enrichment_threshold")
            preselection_member = analysis.get("preselection_base_score") is not None
            deep_member = bool(
                analysis.get("deep_candidate_eligible") is True
                and not str(analysis.get("deep_candidate_exclusion_reason") or "").strip()
            )
            deep_completed = analysis.get("deep_analysis_available") is True
            final_member = deep_completed or analysis.get("final_review_available") is not None
            final_completed = analysis.get("final_review_available") is True
            stage_membership = ["technical_shortlist"]
            if preselection_member:
                stage_membership.append("preselection")
            if deep_member:
                stage_membership.append("deep_research")
            if final_member:
                stage_membership.append("final_review")
            stage_membership.append("execution_evaluation")
            enrichment_status = (
                "scheduled_completed" if attempted and quote_available else
                "attempted_failed" if attempted else
                "not_scheduled"
            )
            deep_consumption = analysis.get("deep_evidence_consumption") or {}
            deep_financial = deep_consumption.get("financials") or {}
            deep_flow = deep_consumption.get("fund_flow") or {}
            deep_kline = analysis.get("deep_kline_evidence") or {}
            deep_kline_date = str(deep_kline.get("visible_last_date") or "")
            deep_kline_status = (
                "stale"
                if deep_kline.get("available")
                and latest_date
                and deep_kline_date
                and deep_kline_date < latest_date
                else "available" if deep_kline.get("available") else "missing"
            )
            deep_flow_dates = [
                str(row.get("data_date") or row.get("trade_date") or "")
                for row in (deep_flow.get("rows") or [])
                if isinstance(row, dict)
            ]
            deep_flow_date = max(deep_flow_dates, default="")
            deep_flow_status = (
                "stale"
                if deep_flow.get("status") == "available"
                and latest_date
                and deep_flow_date
                and deep_flow_date < latest_date
                else "available"
                if deep_flow.get("status") == "available"
                else "missing"
            )
            component_status = {
                "daily": {
                    "required_for_stage": True,
                    "data_status": "available" if daily_ok else "missing",
                    "freshness_status": "known" if daily else "unknown",
                    "actual_data_date": str(analysis.get("technical_data_through") or ""),
                },
                "financial_summary": {
                    "required_for_stage": preselection_member,
                    "data_status": "available" if analysis.get("fundamental_evidence_available") is True else "missing",
                    "freshness_status": "unknown",
                    "period_counts": statement_counts,
                },
                "fund_flow": {
                    "required_for_stage": deep_member,
                    "data_status": (
                        "available" if flow_ok and str(analysis.get("flow_state") or "missing")
                        not in {"missing", "invalid"} else
                        "stale" if int(flow or 0) >= flow_days and flow_latest_date < latest_date else
                        "missing"
                    ),
                    "freshness_status": "fresh" if flow_ok else "stale_or_unknown",
                    "actual_data_date": flow_latest_date,
                    "source": analysis.get("flow_source") or "",
                },
                "deep_kline": {
                    "required_for_stage": deep_member,
                    "data_status": deep_kline_status,
                    "freshness_status": (
                        "stale" if deep_kline_status == "stale"
                        else "known" if deep_kline else "unknown"
                    ),
                    "actual_data_date": deep_kline.get("visible_last_date") or "",
                },
                "deep_financial_history": {
                    "required_for_stage": deep_member,
                    "data_status": "available" if deep_financial.get("status") == "available" else "missing",
                    "freshness_status": "known" if deep_financial else "unknown",
                    "period_counts": deep_financial.get("period_counts") or {},
                },
                "deep_fund_flow": {
                    "required_for_stage": deep_member,
                    "data_status": deep_flow_status,
                    "freshness_status": (
                        "stale" if deep_flow_status == "stale"
                        else "known" if deep_flow else "unknown"
                    ),
                    "actual_data_date": deep_flow_date,
                },
                "preselection_input": {
                    "required_for_stage": preselection_member,
                    "data_status": "available" if analysis.get("preselection_input_sha256") else "unknown",
                    "freshness_status": "known" if analysis.get("preselection_input_sha256") else "unknown",
                },
                "deep_input": {
                    "required_for_stage": deep_member,
                    "data_status": "available" if deep_consumption.get("analysis_input_sha256") else "unknown",
                    "freshness_status": "known" if deep_consumption.get("analysis_input_sha256") else "unknown",
                },
                "final_review_input": {
                    "required_for_stage": final_member,
                    "data_status": "available" if analysis.get("final_review_input_sha256") else "unknown",
                    "freshness_status": "known" if analysis.get("final_review_input_sha256") else "unknown",
                },
            }
            stage_reasons = list(missing_reasons)
            if deep_member:
                if deep_kline_status != "available":
                    stage_reasons.append(f"deep_kline_{deep_kline_status}")
                if deep_financial.get("status") != "available":
                    stage_reasons.append("deep_financial_history_missing")
                if deep_flow_status != "available":
                    stage_reasons.append(f"deep_fund_flow_{deep_flow_status}")
                if not deep_consumption.get("analysis_input_sha256"):
                    stage_reasons.append("deep_input_evidence_unknown")
            if final_member and not analysis.get("final_review_input_sha256"):
                stage_reasons.append("final_review_input_evidence_unknown")
            required_states = [
                str(item.get("data_status") or "unknown")
                for item in component_status.values()
                if item.get("required_for_stage")
            ]
            required_bad = {
                "missing", "invalid", "stale", "unknown", "partial"
            }
            required_data_status = (
                "partial" if any(state in required_bad for state in required_states)
                else "available"
            )
            candidate_coverage["daily_sufficient"] += int(daily_ok)
            candidate_coverage["adjustment_factor_sufficient"] += int(factor_ok)
            candidate_coverage["financial_complete"] += int(financial_ok)
            candidate_coverage["flow_sufficient"] += int(flow_ok)
            candidate_coverage["details"].append({
                "ts_code": code, "daily_bars": int(daily or 0),
                "adjustment_factor_rows": int(factor or 0),
                "financial_period_counts": statement_counts,
                "flow_rows": int(flow or 0), "daily_ok": daily_ok,
                "adjustment_factor_ok": factor_ok,
                "financial_ok": financial_ok, "flow_ok": flow_ok,
                "flow_latest_date": flow_latest_date,
                "flow_state": str(analysis.get("flow_state") or "missing"),
                "ranking_score": ranking_score,
                "evidence_attempted": attempted,
                "quote_available": quote_available,
                "missing_reasons": sorted(set(stage_reasons)),
                "stage_membership": stage_membership,
                "stage": (
                    "final_review" if final_member else
                    "deep_research" if deep_member else
                    "preselection" if preselection_member else
                    "technical_shortlist"
                ),
                "preselection_member": preselection_member,
                "deep_member": deep_member,
                "deep_completed": deep_completed,
                "final_review_member": final_member,
                "final_review_completed": final_completed,
                "scheduling_status": enrichment_status,
                "data_status": required_data_status,
                "freshness_status": (
                    "fresh" if flow_ok and (daily_ok or deep_completed) else "stale_or_unknown"
                ),
                "target_trade_date": latest_date,
                "as_of": str(analysis.get("data_cutoff_at") or analysis.get("run_created_at") or ""),
                "actual_data_date": str(
                    analysis.get("market_price_date") or analysis.get("technical_data_through") or ""
                ),
                "source": analysis.get("market_price_source") or analysis.get("flow_source") or "",
                "evidence_ref": {
                    "run_id": str(analysis.get("run_id") or ""),
                    "input_sha256": str(
                        analysis.get("final_review_input_sha256")
                        or analysis.get("deep_input_fingerprint")
                        or analysis.get("preselection_input_sha256")
                        or ""
                    ),
                },
                "input_evidence": {
                    "preselection": {
                        "status": (
                            "available"
                            if analysis.get("preselection_input_sha256")
                            else "unknown"
                        ),
                        "sha256": str(
                            analysis.get("preselection_input_sha256") or ""
                        ),
                        "chars": int(analysis.get("preselection_input_chars") or 0),
                        "count": int(analysis.get("preselection_input_count") or 0),
                        "fields": analysis.get("preselection_input_fields") or [],
                        "provider": str(analysis.get("preselection_provider") or ""),
                        "model": str(analysis.get("preselection_model") or ""),
                        "called": bool(analysis.get("preselection_called")),
                    },
                    "deep": {
                        "status": (
                            "available"
                            if deep_consumption.get("analysis_input_sha256")
                            and analysis.get("deep_input_fingerprint")
                            else "unknown"
                        ),
                        "fingerprint": str(
                            analysis.get("deep_input_fingerprint") or ""
                        ),
                        "sha256": str(
                            deep_consumption.get("analysis_input_sha256") or ""
                        ),
                        "chars": int(
                            deep_consumption.get("analysis_input_chars") or 0
                        ),
                        "submitted_fields": deep_consumption.get(
                            "submitted_fields"
                        ) or [],
                        "provider": str(analysis.get("deep_provider") or ""),
                        "model": str(analysis.get("deep_model") or ""),
                        "called": bool(analysis.get("deep_analysis_available")),
                        "components": {
                            str(name): {
                                key: value
                                for key, value in component.items()
                                if key in {
                                    "status", "available", "submitted", "stale",
                                    "source_layer", "provider", "fetched_at",
                                    "error", "record_count",
                                }
                            }
                            for name, component in (
                                deep_consumption.get("components") or {}
                            ).items()
                            if isinstance(component, dict)
                        },
                    },
                    "final_review": {
                        "status": (
                            "available"
                            if analysis.get("final_review_input_sha256")
                            else "unknown"
                        ),
                        "sha256": str(
                            analysis.get("final_review_input_sha256") or ""
                        ),
                        "chars": int(analysis.get("final_review_input_chars") or 0),
                        "count": int(analysis.get("final_review_input_count") or 0),
                        "fields": analysis.get("final_review_input_fields") or [],
                        "provider": str(analysis.get("final_review_provider") or ""),
                        "model": str(analysis.get("final_review_model") or ""),
                        "called": bool(analysis.get("final_review_available")),
                    },
                },
                "ai_execution": {
                    "deep": {
                        "available": bool(analysis.get("deep_analysis_available")),
                        "cached": bool(analysis.get("deep_cached")),
                        "duration_seconds": float(
                            analysis.get("deep_duration_seconds") or 0
                        ),
                        "provider": str(analysis.get("deep_provider") or ""),
                        "model": str(analysis.get("deep_model") or ""),
                        "error": str(analysis.get("deep_analysis_error") or ""),
                    },
                    "final_review": {
                        "available": bool(analysis.get("final_review_available")),
                        "provider": str(analysis.get("final_review_provider") or ""),
                        "model": str(analysis.get("final_review_model") or ""),
                        "error": str(analysis.get("final_review_error") or ""),
                    },
                },
                "required_for_stage": {
                    name: bool(item.get("required_for_stage"))
                    for name, item in component_status.items()
                },
                "component_status": component_status,
                "background_task_id": (
                    (run_task_context.get("research_backfill_task") or {}).get("partition_key") or ""
                ),
                "background_task_status": (
                    (run_task_context.get("research_backfill_task") or {}).get("status")
                    or "unknown"
                ),
            })

        stage_details = candidate_coverage["details"]
        stage_counts: dict[str, dict[str, int]] = {}

        def _stage_bucket(stage: str) -> dict[str, int]:
            return stage_counts.setdefault(
                stage,
                {
                    "target_count": 0,
                    "attempted_count": 0,
                    "completed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "unverified_count": 0,
                },
            )

        def _count_stage(
            stage: str,
            *,
            attempted: bool,
            completed: bool,
            failed: bool = False,
            unverified: bool = False,
        ) -> None:
            bucket = _stage_bucket(stage)
            bucket["target_count"] += 1
            bucket["attempted_count"] += int(attempted)
            bucket["completed_count"] += int(completed)
            bucket["failed_count"] += int(failed)
            bucket["unverified_count"] += int(unverified)

        # Each stage is classified from its own required components.  Using
        # detail["data_status"] here would let a Deep/final evidence gap make
        # an otherwise complete technical row appear technically unverified.
        for detail in stage_details:
            membership = set(detail.get("stage_membership") or [])
            components = detail.get("component_status") or {}
            if "technical_shortlist" in membership:
                daily = components.get("daily") or {}
                daily_status = str(daily.get("data_status") or "unknown")
                _count_stage(
                    "technical_shortlist",
                    attempted=True,
                    completed=daily_status == "available",
                    failed=daily_status in {"missing", "invalid", "stale"},
                    unverified=daily_status == "unknown",
                )
            if "preselection" in membership:
                input_status = str(
                    (components.get("preselection_input") or {}).get(
                        "data_status"
                    )
                    or "unknown"
                )
                _count_stage(
                    "preselection",
                    attempted=True,
                    completed=True,
                    failed=input_status in {"missing", "invalid", "stale"},
                    unverified=input_status == "unknown",
                )
            if "deep_research" in membership:
                required_components = (
                    "deep_kline",
                    "deep_financial_history",
                    "deep_fund_flow",
                    "deep_input",
                )
                states = [
                    str((components.get(name) or {}).get("data_status") or "unknown")
                    for name in required_components
                ]
                completed = bool(detail.get("deep_completed"))
                _count_stage(
                    "deep_research",
                    attempted=True,
                    completed=completed,
                    failed=not completed,
                    unverified=any(state == "unknown" for state in states)
                    or any(
                        state in {"missing", "invalid", "stale"} for state in states
                    ),
                )
            if "final_review" in membership:
                input_status = str(
                    (components.get("final_review_input") or {}).get(
                        "data_status"
                    )
                    or "unknown"
                )
                completed = detail.get("final_review_completed") is True
                _count_stage(
                    "final_review",
                    attempted=True,
                    completed=completed,
                    failed=not completed,
                    unverified=input_status != "available",
                )
            if "execution_evaluation" in membership:
                _count_stage(
                    "execution_evaluation",
                    attempted=True,
                    completed=True,
                )
        candidate_coverage["stage_counts"] = stage_counts

        learning_counts: dict[str, int] = {}
        if _table_exists(conn, "market_learning_observation"):
            learning_counts = {
                str(row["horizon_days"]): int(row["n"] or 0)
                for row in conn.execute(
                    "SELECT horizon_days, COUNT(*) AS n FROM market_learning_observation GROUP BY horizon_days"
                ).fetchall()
            }

        return {
            "audited_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "database": str(db_path.resolve()),
            "read_only": True,
            "latest_market_date": latest_date,
            "market_daily": {
                "a_share_code_count": len(daily_codes),
                "latest_date_code_count": len(latest_codes),
                "bar_row_count": sum(bar_counts.get(code, 0) for code in daily_codes),
                "required_bars": required_bars,
                "coverage_categories": dict(categories),
            },
            "stock_basic": {
                "a_share_code_count": len(basic_codes),
                "daily_code_not_in_basic_count": len(daily_codes - basic_codes),
                "basic_code_without_daily_count": len(basic_codes - daily_codes),
                "daily_not_in_basic_sample": sorted(daily_codes - basic_codes)[:50],
                "basic_not_in_daily_sample": sorted(basic_codes - daily_codes)[:50],
                "all_a_share_missing_fields": basic_missing,
                "latest_date_missing_fields": latest_basic_missing,
            },
            "latest_decisions": {
                "decision_date": latest_decision_date,
                "count": decision_count,
                "run_id": requested_run_id,
                "candidate_count_with_bars": len(candidate_codes & daily_codes),
                "candidate_missing_bars_count": len(candidate_codes - daily_codes),
                "flow_state_counts": dict(flow_counts),
            },
            "financial_history": financial_history,
            "fund_flow_history": flow_history,
            "candidate_coverage": candidate_coverage,
            "learning_observations": learning_counts,
            "run_selection": {
                "requested_run_id": requested_run_id,
                "matched_decision_count": decision_count,
                "run_ids_seen": len(matched_run_ids),
                "exact_match": bool(requested_run_id and decision_count),
                "task_context": run_task_context,
            },
            "date_note": "当前日期仅用于审计时间；历史行情和财报按各自有效日期读取。",
        }


async def _probe_tushare(code: str) -> dict[str, Any]:
    try:
        from scripts.probe_tushare import run_probe
        return await run_probe(code, "", extended=True)
    except Exception as exc:
        return {"status": "probe_failed", "error": f"{type(exc).__name__}: {str(exc)[:180]}"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit data completion without changing the market DB.")
    parser.add_argument("--db", default="src/infrastructure/storage/market_data.db")
    parser.add_argument("--output", default="test-reports/data-completion-20260905/baseline.json")
    parser.add_argument("--required-bars", type=int, default=250)
    parser.add_argument("--financial-periods", type=int, default=8)
    parser.add_argument("--flow-days", type=int, default=20)
    parser.add_argument("--run-id", default="", help="Audit one exact persisted strategy run.")
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument("--probe-code", default="600519.SH")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit_database(
        Path(args.db), max(20, int(args.required_bars)),
        max(1, int(args.financial_periods)), max(1, int(args.flow_days)),
        str(args.run_id or "").strip(),
    )
    result["tushare_capability_probe"] = (
        {"status": "skipped"}
        if args.skip_probe else asyncio.run(_probe_tushare(args.probe_code))
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
