"""Backfill research data with a resumable, isolated-first workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text or len(text) != 6 or not text.isdigit():
        return text
    if text.startswith(("6", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "2", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8")):
        return f"{text}.BJ"
    return text


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _args_from_checkpoint(
    source_db: str, output_dir: str, partition_key: str,
    *, write_production: bool, confirm_production: bool,
    batch_deadline_seconds: float = 60.0,
) -> argparse.Namespace | None:
    """Decode the v3 partition without inventing a second task format."""
    parts = str(partition_key or "").split(":")
    if len(parts) != 8 or parts[0] != "20260906-v3":
        return None
    try:
        _version, scope, run_id, limit, _target, required_bars, periods, flow_days = parts
        return SimpleNamespace(
            source_db=source_db, output_dir=output_dir, scope=scope,
            limit=int(limit), run_id=run_id, required_bars=int(required_bars),
            periods=int(periods), flow_days=int(flow_days),
            write_production=write_production,
            confirm_production=confirm_production, retry_completed=False,
            batch_deadline_seconds=batch_deadline_seconds,
            lease_seconds=max(300.0, batch_deadline_seconds + 60.0),
        )
    except (TypeError, ValueError):
        return None


async def recover_pending_research_data(
    source_db: str, output_dir: str, *,
    write_production: bool = False, confirm_production: bool = False,
    batch_deadline_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """Resume partial/running partitions through the same _run service."""
    from src.infrastructure.storage.market_database import MarketDatabase

    database = await asyncio.to_thread(MarketDatabase, source_db)
    checkpoints = await asyncio.to_thread(
        database.list_completion_checkpoints, "research_data_backfill", "candidate"
    )
    results: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        if checkpoint.get("status") not in {"pending", "running", "partial"}:
            continue
        args = _args_from_checkpoint(
            source_db, output_dir, checkpoint.get("partition_key", ""),
            write_production=write_production,
            confirm_production=confirm_production,
            batch_deadline_seconds=batch_deadline_seconds,
        )
        if args is None:
            results.append({
                "status": "unsupported_checkpoint",
                "partition_key": checkpoint.get("partition_key", ""),
            })
            continue
        results.append(await _run(args))
    return results


def _run_id_from_analysis(value: Any) -> str:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    return str(payload.get("run_id") or "").strip()


def _codes_from_source(
    source: Path, scope: str, limit: int, run_id: str = ""
) -> tuple[list[str], dict[str, Any]]:
    with sqlite3.connect(source) as conn:
        conn.row_factory = sqlite3.Row
        candidate_rows = conn.execute(
            "SELECT id, decision_date, stock_code, analysis_json "
            "FROM strategy_decision ORDER BY decision_date DESC, id DESC"
        ).fetchall()
        run_rows: dict[str, list[sqlite3.Row]] = {}
        for row in candidate_rows:
            candidate_run_id = _run_id_from_analysis(row["analysis_json"])
            if candidate_run_id:
                run_rows.setdefault(candidate_run_id, []).append(row)
        for rows in run_rows.values():
            rows.sort(key=lambda row: int(row["id"] or 0))
        run_counts = Counter({run: len(rows) for run, rows in run_rows.items()})
        selected_run_id = str(run_id or "").strip()
        if not selected_run_id and run_counts:
            selected_run_id = max(
                run_rows,
                key=lambda run: (
                    max(
                        (
                            str(row["decision_date"] or ""),
                            int(row["id"] or 0),
                        )
                        for row in run_rows[run]
                    ),
                ),
            )
        source_rows = (
            run_rows.get(selected_run_id, [])
            if selected_run_id
            else candidate_rows
        )
        candidates = [_normalize_code(row["stock_code"]) for row in source_rows]
        positions = [
            _normalize_code(row[0])
            for row in conn.execute(
                "SELECT stock_code FROM paper_position WHERE shares > 0"
            ).fetchall()
        ] if _table_exists(conn, "paper_position") else []
        technical = [
            _normalize_code(row[0])
            for row in conn.execute(
                "SELECT ts_code FROM market_daily GROUP BY ts_code HAVING COUNT(*) >= 20"
            ).fetchall()
        ]
        basic = [
            _normalize_code(row[0])
            for row in conn.execute("SELECT ts_code FROM stock_basic").fetchall()
        ] if _table_exists(conn, "stock_basic") else []
    if scope == "candidate":
        # The limit belongs to the requested candidate batch.  Held positions
        # are appended for risk coverage and must not evict a candidate.
        candidate_batch = candidates[:limit] if limit > 0 else candidates
        selected = [*candidate_batch, *positions]
    elif scope == "technical":
        technical_batch = technical[:limit] if limit > 0 else technical
        selected = [*technical_batch, *positions]
    else:
        selected = [*positions, *candidates, *technical, *basic]
    seen: set[str] = set()
    ordered: list[str] = []
    for code in selected:
        if code and code not in seen:
            ordered.append(code)
            seen.add(code)
    if limit > 0 and scope == "all":
        ordered = ordered[:limit]
    selected_run_known = bool(selected_run_id and selected_run_id in run_rows)
    return ordered, {
        "scope": scope,
        "decision_date": str(
            max(
                str(row["decision_date"] or "")
                for row in run_rows.get(selected_run_id, [])
            )
            if run_rows.get(selected_run_id) else ""
        ),
        "run_id": selected_run_id, "run_id_counts": dict(run_counts),
        "candidate_count": len(set(candidates)), "position_count": len(set(positions)),
        "technical_count": len(set(technical)), "basic_count": len(set(basic)),
        "selected_count": len(ordered),
        "candidate_selection_exact": selected_run_known or not run_counts,
        "selected_run_known": selected_run_known,
        "selection_error": (
            "requested_run_id_not_found" if run_id and not selected_run_known else ""
        ),
    }


async def _sync_metadata(database: Any, target_date: str, codes: set[str]) -> dict[str, Any]:
    from src.infrastructure.market_data.data_completion_service import error_status
    from src.infrastructure.market_data.tushare_provider import tushare_provider

    result: dict[str, Any] = {"status": "not_attempted", "requested": len(codes)}
    try:
        metadata = await tushare_provider.fetch_stock_metadata()
        by_code = {str(row.get("ts_code") or "").upper(): row for row in metadata.data}
        rows = [
            {
                "ts_code": code, "name": by_code.get(code, {}).get("name") or code,
                "industry": by_code.get(code, {}).get("industry") or "",
                "list_date": by_code.get(code, {}).get("list_date") or "",
                "source": "tushare", "data_date": target_date,
            }
            for code in sorted(codes) if code in by_code
        ]
        stored = await asyncio.to_thread(database.upsert_current_stock_metadata, rows, "")
        result.update({
            "status": "available" if len(rows) == len(codes) else "partial",
            "provider_count": len(metadata.data), "matched": len(rows), "stored": stored,
            "missing_count": len(codes) - len(rows),
        })
        if target_date:
            snapshot = await tushare_provider.fetch_daily_snapshot(target_date)
            if snapshot.coverage_ratio is not None and snapshot.coverage_ratio >= 0.80:
                snapshot_by_code = {
                    str(row.get("ts_code") or "").upper(): row
                    for row in snapshot.data
                }
                quote_rows = []
                for code in sorted(codes):
                    quote = snapshot_by_code.get(code)
                    base = by_code.get(code, {})
                    if not quote:
                        continue
                    quote_rows.append({
                        "ts_code": code, "name": base.get("name") or code,
                        "industry": base.get("industry") or "",
                        "list_date": base.get("list_date") or "",
                        "market_cap_yi": quote.get("market_cap_yi"),
                        "float_mcap_yi": quote.get("float_mcap_yi"),
                        "turnover_pct": quote.get("turnover"),
                        "data_date": target_date, "source": "tushare",
                    })
                snapshot_stored = await asyncio.to_thread(
                    database.upsert_current_stock_metadata, quote_rows, target_date
                )
                result["daily_basic_snapshot"] = {
                    "status": "available" if len(quote_rows) == len(codes) else "partial",
                    "coverage_ratio": snapshot.coverage_ratio,
                    "matched": len(quote_rows), "stored": snapshot_stored,
                }
            else:
                result["daily_basic_snapshot"] = {
                    "status": "partial", "coverage_ratio": snapshot.coverage_ratio,
                    "matched": 0, "error": "tushare_snapshot_below_80_percent",
                }
    except Exception as exc:
        result.update({
            "status": error_status(exc),
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
        })
    return result


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    from src.ai_os.post_backfill_rerun import build_backfill_summary
    from src.infrastructure.market_data.data_completion_service import sync_code
    from src.infrastructure.market_data.tushare_provider import tushare_provider
    from src.infrastructure.storage.market_database import MarketDatabase

    started = time.perf_counter()
    batch_deadline_seconds = max(
        1.0, float(getattr(args, "batch_deadline_seconds", 1800.0))
    )
    lease_seconds = max(
        1.0, float(getattr(args, "lease_seconds", batch_deadline_seconds + 60.0))
    )
    lease_owner = f"backfill:{uuid.uuid4().hex}"
    source = Path(args.source_db).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.write_production and not args.confirm_production:
        raise SystemExit("生产写入必须同时指定 --write-production --confirm-production")
    target = source if args.write_production else output / "market_data-backfill-isolated.db"
    await asyncio.to_thread(_backup_database, source, target)
    database = await asyncio.to_thread(MarketDatabase, target)
    codes, selection = await asyncio.to_thread(
        _codes_from_source, source, args.scope, args.limit, args.run_id
    )
    if selection.get("selection_error"):
        return {
            "status": "failed",
            "source_db": str(source), "target_db": str(target),
            "isolated": not args.write_production,
            "selection": selection, "codes": {}, "code_count": 0,
            "completed_count": 0, "retryable_count": 0,
            "error": selection["selection_error"],
            "started_at": datetime.now().astimezone().isoformat(),
            "finished_at": datetime.now().astimezone().isoformat(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    target_date = await asyncio.to_thread(
        database.get_latest_market_date_on_or_before, date.today().isoformat()
    ) or ""
    report: dict[str, Any] = {
        "status": "running", "started_at": datetime.now().astimezone().isoformat(),
        "source_db": str(source), "target_db": str(target),
        "isolated": not args.write_production, "selection": selection,
        "config": {
            "required_bars": args.required_bars, "financial_periods": args.periods,
            "flow_days": args.flow_days,
        },
        "metadata": {}, "codes": {},
        "request_stats_before": tushare_provider.runtime_stats(),
    }
    checkpoint_partition = ":".join((
        "20260906-v3",
        args.scope,
        str(selection.get("run_id") or "no-run-id"),
        str(args.limit),
        target_date,
        str(args.required_bars),
        str(args.periods),
        str(args.flow_days),
    ))
    checkpoint_key = ("research_data_backfill", args.scope, checkpoint_partition)
    previous = await asyncio.to_thread(
        database.get_completion_checkpoint, *checkpoint_key
    ) or {}
    progress = previous.get("progress") or {}
    if not previous:
        await asyncio.to_thread(
            database.save_completion_checkpoint,
            *checkpoint_key,
            {
                "codes": codes, "completed": [], "target_date": target_date,
                "results": {},
            },
            "pending",
        )
    claim = await asyncio.to_thread(
        database.try_claim_completion_checkpoint,
        *checkpoint_key, lease_owner, lease_seconds
    )
    if not claim.get("claimed"):
        return {
            "status": "deferred", "source_db": str(source),
            "target_db": str(target), "isolated": not args.write_production,
            "selection": selection, "codes": {}, "code_count": len(codes),
            "completed_count": 0, "retryable_count": len(codes),
            "error": "checkpoint_lease_active",
            "lease": {
                "owner": claim.get("lease_owner"),
                "expires_at": claim.get("lease_expires_at"),
            },
            "started_at": datetime.now().astimezone().isoformat(),
            "finished_at": datetime.now().astimezone().isoformat(),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    progress = claim.get("progress") or progress
    completed = set(progress.get("completed") or [])
    checkpoint_results = dict(progress.get("results") or {})
    report["codes"].update(checkpoint_results)
    report["config"]["batch_deadline_seconds"] = batch_deadline_seconds
    report["config"]["lease_seconds"] = lease_seconds
    report["metadata"] = await _sync_metadata(database, target_date, set(codes))
    deferred = time.perf_counter() - started >= batch_deadline_seconds
    for index, code in enumerate(codes, start=1):
        if code in completed and not args.retry_completed:
            continue
        if time.perf_counter() - started >= batch_deadline_seconds:
            deferred = True
            break
        item = await sync_code(
            database, code, args.required_bars, args.periods, args.flow_days,
            target_date=target_date,
        )
        report["codes"][code] = item
        checkpoint_results[code] = item
        if item.get("complete"):
            completed.add(code)
        await asyncio.to_thread(
            database.save_completion_checkpoint,
            *checkpoint_key,
            {
                "codes": codes, "completed": sorted(completed), "last_code": code,
                "index": index, "target_date": target_date,
                "results": checkpoint_results,
                "lease_owner": lease_owner,
                "lease_heartbeat_at": datetime.now().astimezone().isoformat(),
                "lease_expires_at": datetime.fromtimestamp(
                    datetime.now().timestamp() + lease_seconds,
                    tz=datetime.now().astimezone().tzinfo,
                ).isoformat(),
            },
            "running",
        )
        if index % 10 == 0 or index == len(codes):
            print(f"[{index}/{len(codes)}] {code} completed={len(completed)}", flush=True)
    final_status = "completed" if len(completed) == len(codes) else "partial"
    coverage = await asyncio.to_thread(
        database.get_research_component_coverage,
        codes,
        target_date,
        args.required_bars,
        args.periods,
        args.flow_days,
    )
    checkpoint_snapshot = {
        "progress": {
            "codes": codes,
            "results": checkpoint_results,
        },
        "status": final_status,
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    summary = build_backfill_summary(
        checkpoint=checkpoint_snapshot,
        coverage=coverage,
        source_run_id=str(selection.get("run_id") or ""),
        target_date=target_date,
    )
    await asyncio.to_thread(
        database.save_completion_checkpoint,
        *checkpoint_key,
        {
            "codes": codes, "completed": sorted(completed),
            "target_date": target_date, "results": checkpoint_results,
            "deferred": deferred,
            "lease_owner": "", "lease_heartbeat_at": "", "lease_expires_at": "",
            "backfill_summary": summary,
        },
        final_status,
    )
    status_counts = Counter(
        component.get("status", "unknown")
        for item in report["codes"].values()
        for component in item.get("components", {}).values()
    )
    failure_details = {
        code: {
            name: {
                key: component.get(key)
                for key in (
                    "status", "error_type", "error_message", "error",
                    "attempted", "attempt_count", "elapsed_seconds",
                    "request_attempts",
                )
                if component.get(key)
            }
            for name, component in item.get("components", {}).items()
            if component.get("status") != "available"
        }
        for code, item in report["codes"].items()
    }
    report.update({
        "status": final_status,
        "completed_count": len(completed), "code_count": len(codes),
        "retryable_count": len(codes) - len(completed),
        "deferred": deferred,
        "lease": {"owner": "", "expires_at": ""},
        "checkpoint_partition": checkpoint_partition,
        "component_status_counts": dict(status_counts),
        "failure_details": failure_details,
        "backfill_summary": summary,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "request_stats_after": tushare_provider.runtime_stats(),
        "finished_at": datetime.now().astimezone().isoformat(),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="补采研究所需的Tushare历史数据")
    parser.add_argument("--source-db", default="src/infrastructure/storage/market_data.db")
    parser.add_argument("--output-dir", default="test-reports/data-completion-20260905/backfill")
    parser.add_argument("--scope", choices=("candidate", "technical", "all"), default="candidate")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument(
        "--run-id", default="",
        help="精确限定 strategy_decision.analysis_json 中的 run_id",
    )
    parser.add_argument(
        "--recover-pending", action="store_true",
        help="只恢复已有的 pending/running/partial 分区，不创建新批次",
    )
    parser.add_argument("--required-bars", type=int, default=250)
    parser.add_argument("--periods", type=int, default=8)
    parser.add_argument("--flow-days", type=int, default=20)
    parser.add_argument("--write-production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--retry-completed", action="store_true")
    parser.add_argument(
        "--batch-deadline-seconds", type=float, default=1800.0,
        help="单批补采的总时间预算；超时保存partial并由下一次恢复",
    )
    parser.add_argument(
        "--lease-seconds", type=float, default=1860.0,
        help="跨进程补采租约时长；过期后才允许恢复接管",
    )
    args = parser.parse_args()
    if args.recover_pending:
        started = time.perf_counter()
        results = asyncio.run(
            recover_pending_research_data(
                args.source_db,
                args.output_dir,
                write_production=args.write_production,
                confirm_production=args.confirm_production,
                batch_deadline_seconds=args.batch_deadline_seconds,
            )
        )
        report = {
            "status": (
                "completed"
                if all(item.get("status") == "completed" for item in results)
                else "partial"
            ),
            "mode": "recover_pending",
            "source_db": str(Path(args.source_db).resolve()),
            "output_dir": str(Path(args.output_dir).resolve()),
            "isolated": not args.write_production,
            "results": results,
            "partition_count": len(results),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "finished_at": datetime.now().astimezone().isoformat(),
        }
        output = Path(args.output_dir).resolve() / "backfill-recovery.json"
    else:
        report = asyncio.run(_run(args))
        output = Path(args.output_dir).resolve() / "backfill.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "status": report.get("status", "failed"),
        "target_db": report.get("target_db", ""),
        "code_count": report.get("code_count", 0),
        "completed_count": report.get("completed_count", 0),
        "component_status_counts": report.get("component_status_counts", {}),
        "report": str(output),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
