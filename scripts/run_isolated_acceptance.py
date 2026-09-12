"""Run the current research chain against a SQLite copy, never production."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _try_sha256(path: Path) -> tuple[str, str]:
    try:
        return _sha256(path), ""
    except OSError as exc:
        return "", f"{type(exc).__name__}: {str(exc)[:180]}"


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with (
        sqlite3.connect(source) as source_connection,
        sqlite3.connect(target) as target_connection,
    ):
        source_connection.backup(target_connection)


def _reset_isolated_deep_budget(database_path: Path, budget_date: str) -> dict[str, int]:
    """Remove only copied same-day Deep reservations before a fresh replay.

    The production copy contains earlier same-day reservations and legacy
    strategy rows.  Leaving them in place would make a ``force_reanalysis``
    acceptance run skip every real model call at the unchanged daily limit.
    This mutation is strictly inside the SQLite copy; the source database is
    never opened for writing.
    """
    with sqlite3.connect(str(database_path)) as connection:
        attempt_cursor = connection.execute(
            "DELETE FROM deep_analysis_attempt WHERE budget_date=?",
            (budget_date,),
        )
        decision_cursor = connection.execute(
            "DELETE FROM strategy_decision WHERE decision_date=?",
            (budget_date,),
        )
    return {
        "deep_analysis_attempt_rows_removed": int(attempt_cursor.rowcount or 0),
        "same_day_strategy_rows_removed": int(decision_cursor.rowcount or 0),
    }


def _ledger_summary(database: Any) -> dict[str, Any]:
    state = database.get_paper_ledger_state()
    account = state.get("account") or {}
    return {
        "cash": float(account.get("cash") or 0),
        "position_count": len(state.get("paper_position") or []),
        "trade_count": len(state.get("paper_trade") or []),
        "mark_count": len(state.get("paper_position_mark") or []),
        "snapshot_count": len(state.get("paper_portfolio_snapshot") or []),
    }


def _protected_table_summary(database: Any) -> dict[str, Any]:
    """Fingerprint state that an acceptance run must not mutate."""
    summary: dict[str, Any] = {}
    for table in (
        "paper_account",
        "paper_position",
        "paper_trade",
        "paper_position_mark",
        "paper_portfolio_snapshot",
        "learning_log",
    ):
        with sqlite3.connect(str(database.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                ).fetchall()
            ]
        payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
        summary[table] = {
            "row_count": len(rows),
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }
    return summary


def _run_rows(database: Any, run_id: str, trade_date: str) -> list[dict[str, Any]]:
    rows = database.get_decisions_for_date(trade_date, limit=5000)
    return [row for row in rows if str(row.get("run_id") or "") == run_id]


def _consistency_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from src.ai_os.execution_policy import classify_execution_flow

    flow_counts = Counter(str(row.get("flow_state") or "missing") for row in rows)
    source_counts = Counter()
    mismatches = []
    nested_flow_count = 0
    for row in rows:
        sources = row.get("flow_sources") or []
        source_counts.update(str(source) for source in sources)
        try:
            evidence = json.loads(str(row.get("evidence") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence = {}
        nested = (evidence.get("market_discovery") or {}).get("fund_flow") or {}
        if nested:
            nested_flow_count += 1
        nested_status = str(nested.get("status") or "")
        normalized_nested = classify_execution_flow({
            "market_flow": nested,
            "flow_status": nested_status,
            "flow_source": nested.get("source"),
        }).value if nested_status else ""
        if normalized_nested and normalized_nested != str(row.get("flow_state") or ""):
            mismatches.append({
                "stock_code": row.get("stock_code"),
                "top_level": row.get("flow_state"),
                "nested": nested_status,
                "normalized_nested": normalized_nested,
            })
    return {
        "row_count": len(rows),
        "flow_state_counts": dict(flow_counts),
        "flow_source_counts": dict(source_counts),
        "nested_flow_count": nested_flow_count,
        "nested_top_level_mismatch_count": len(mismatches),
        "mismatch_examples": mismatches[:10],
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    source_db = Path(args.source_db).resolve()
    output_dir = Path(args.output_dir).resolve()
    isolated_db = output_dir / "market_data-isolated.db"
    if source_db == isolated_db:
        raise ValueError("source and isolated database must differ")
    source_hash_before = _sha256(source_db)
    _backup_database(source_db, isolated_db)
    isolated_budget_reset = _reset_isolated_deep_budget(
        isolated_db, date.today().isoformat()
    )
    # Set the singleton destination before importing any consumer.
    os.environ["ADAPTIVE_MARKET_DB_PATH"] = str(isolated_db)
    import src.infrastructure.storage.market_database as database_module
    from config.settings import settings
    from src.ai_os.execution_policy import evaluate_entry_execution
    from src.ai_os.pipeline_runner import pipeline_runner
    from src.infrastructure.market_data.source_manager import source_manager
    from src.infrastructure.market_data.tushare_provider import tushare_provider

    isolated_database = database_module.MarketDatabase(isolated_db)
    production_database = database_module.market_db
    database_module.market_db = isolated_database
    settings.NOTIFICATION_ENABLED = False
    cache_env_before = os.environ.get("EVIDENCE_DOSSIER_CACHE_PATH")
    os.environ["EVIDENCE_DOSSIER_CACHE_PATH"] = str(
        output_dir / "evidence_last_good-isolated.json"
    )
    before_ledger = _ledger_summary(isolated_database)
    before_protected = _protected_table_summary(isolated_database)
    tushare_before = tushare_provider.runtime_stats()
    blocked_learning_writes: list[dict[str, Any]] = []
    blocked_portfolio_marks: list[dict[str, Any]] = []
    original_learning_methods: dict[str, Any] = {}
    from src.ai_os import portfolio_marking

    original_portfolio_mark = portfolio_marking.refresh_paper_portfolio_quotes

    async def _block_portfolio_mark(*method_args: Any, **method_kwargs: Any) -> dict[str, Any]:
        blocked_portfolio_marks.append({
            "args_count": len(method_args),
            "keyword_names": sorted(method_kwargs),
        })
        return {
            "status": "skipped_isolated_acceptance",
            "reason": "portfolio_mark_write_blocked",
        }

    portfolio_marking.refresh_paper_portfolio_quotes = _block_portfolio_mark
    for method_name in (
        "save_learning",
        "upsert_daily_learning",
        "save_market_learning_observation",
    ):
        original = getattr(isolated_database, method_name, None)
        if original is None:
            continue
        original_learning_methods[method_name] = original

        def _block_learning_write(
            *method_args: Any,
            _method_name: str = method_name,
            **method_kwargs: Any,
        ) -> int:
            blocked_learning_writes.append({
                "method": _method_name,
                "args_count": len(method_args),
                "keyword_names": sorted(method_kwargs),
            })
            return 0

        setattr(isolated_database, method_name, _block_learning_write)

    try:
        result = await pipeline_runner.run_daily_pipeline(
            force_reanalysis=bool(args.force_reanalysis),
            execute_paper_trades=False,
        )
        serialized = result.to_dict()
        run_id = str(serialized.get("run_id") or result.run_id)
        trade_date = str(serialized.get("run_date") or date.today().isoformat())
        rows = _run_rows(isolated_database, run_id, trade_date)
        consistency = _consistency_report(rows)
        execution_tiers = Counter(
            str(evaluate_entry_execution(row, allow_probe=True).get("tier") or "blocked")
            for row in rows
        )

        # Exercise the real route consumer against the isolated database.
        from src.api.routes.decision_routes import daily_decisions

        api_result = await daily_decisions()
        after_ledger = _ledger_summary(isolated_database)
        after_protected = _protected_table_summary(isolated_database)
        production_hash_after, production_hash_error = _try_sha256(source_db)
        production_database_unchanged = bool(
            production_hash_after and production_hash_after == source_hash_before
        )
        reopened_database = database_module.MarketDatabase(isolated_db)
        saved_audit = isolated_database.get_pipeline_run_audit(run_id)
        reopened_audit = reopened_database.get_pipeline_run_audit(run_id)
        stage_acceptance = (
            serialized.get("market_data_quality", {}).get("stage_acceptance") or {}
        )
        return {
            "status": (
                "pass"
                if not consistency["nested_top_level_mismatch_count"]
                and stage_acceptance.get("run_id") == run_id
                and reopened_audit.get("run_id") == run_id
                and before_protected == after_protected
                and production_database_unchanged
                else "fail"
            ),
            "source_database": str(source_db),
            "isolated_database": str(isolated_db),
            "isolation_preparation": {
                "same_day_deep_budget_reset": isolated_budget_reset,
                "source_database_not_mutated": True,
            },
            "run_id": run_id,
            "trade_date": trade_date,
            "pipeline": serialized,
            "stage_acceptance": stage_acceptance,
            "audit_persistence": {
                "saved_readback_verified": saved_audit.get("run_id") == run_id,
                "reopened_readback_verified": reopened_audit.get("run_id") == run_id,
                "saved_schema_version": saved_audit.get("schema_version") or "",
                "reopened_schema_version": reopened_audit.get("schema_version") or "",
            },
            "flow_consistency": consistency,
            "execution_tier_counts": dict(execution_tiers),
            "api_consumer": {
                "status": api_result.get("recommendation_available"),
                "count": len(api_result.get("decisions") or []),
                "blocked_count": api_result.get("blocked_count"),
            },
            "tushare_runtime": {
                "before": tushare_before,
                "after": tushare_provider.runtime_stats(),
            },
            "source_manager": {
                "status": source_manager.get_all_sources_status(),
            },
            "isolated_ledger_before": before_ledger,
            "isolated_ledger_after": after_ledger,
            "protected_state_before": before_protected,
            "protected_state_after": after_protected,
            "blocked_learning_writes": blocked_learning_writes,
            "blocked_portfolio_marks": blocked_portfolio_marks,
            "side_effect_guard": {
                "execute_paper_trades": False,
                "scheduler_started": False,
                "notifications_enabled": False,
                "learning_writes_blocked": True,
                "portfolio_mark_writes_blocked": True,
                "protected_state_unchanged": before_protected == after_protected,
                "production_sha256_before": source_hash_before,
                "production_sha256_after": production_hash_after,
                "production_sha256_after_error": production_hash_error,
                "production_database_unchanged": production_database_unchanged,
                "isolated_trade_count_delta": (
                    after_ledger["trade_count"] - before_ledger["trade_count"]
                ),
            },
        }
    finally:
        if cache_env_before is None:
            os.environ.pop("EVIDENCE_DOSSIER_CACHE_PATH", None)
        else:
            os.environ["EVIDENCE_DOSSIER_CACHE_PATH"] = cache_env_before
        for method_name, original in original_learning_methods.items():
            setattr(isolated_database, method_name, original)
        portfolio_marking.refresh_paper_portfolio_quotes = original_portfolio_mark
        database_module.market_db = production_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated Adaptive Investment acceptance scan."
    )
    parser.add_argument(
        "--source-db",
        default=str(PROJECT_ROOT / "src" / "infrastructure" / "storage" / "market_data.db"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "test-reports" / "isolated-acceptance-20260905"),
    )
    parser.add_argument("--force-reanalysis", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(_run(args))
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "acceptance.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "run_id": report["run_id"],
        "trade_date": report["trade_date"],
        "report": str(report_path),
        "flow_consistency": report["flow_consistency"],
        "execution_tier_counts": report["execution_tier_counts"],
        "side_effect_guard": report["side_effect_guard"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
