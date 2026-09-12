"""Build point-in-time replay snapshots from the local journal and bars.

This command is deliberately offline.  It reads the existing decision journal
and local market_daily table, reruns two deterministic scoring policies, and
writes the contract consumed by ``run_historical_gate.py``.  It does not call
remote providers and does not write to the market database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.storage.market_database import market_db  # noqa: E402
from src.replay.engine import ReplayEngine  # noqa: E402


def _model_choices(engine: ReplayEngine) -> tuple[str, ...]:
    return tuple(str(item["id"]) for item in engine.available_models())


def _decision_row(candidate: dict[str, Any]) -> dict[str, Any]:
    direction = str(candidate.get("direction") or "").strip().lower()
    actionable = direction in {"buy", "sell"}
    return {
        "stock_code": str(candidate.get("stock_code") or ""),
        "direction": direction,
        "executable_direction": direction if actionable else "",
        "actionable": actionable,
        "ranking_score": candidate.get("fusion_score"),
        "action_score": candidate.get("fusion_score") if actionable else None,
        "forward_return_pct": candidate.get("forward_return_pct"),
        "outcome_available": bool(candidate.get("outcome_available")),
    }


def _outcomes(rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        if not row.get("outcome_available"):
            continue
        code = str(row.get("stock_code") or "").strip().upper()
        value = row.get("forward_return_pct")
        if not code or value is None:
            continue
        result[code] = float(value)
    return result


async def build_snapshots(
    *,
    baseline_model: str,
    candidate_model: str,
    horizon_days: int,
    pool_size: int,
    metadata_policy: str,
    limit: int,
) -> dict[str, Any]:
    engine = ReplayEngine()
    dates = market_db.get_replay_dates(limit=365)
    eligible_dates = sorted(
        str(item["date"])
        for item in dates
        if item.get("evaluation_ready") and item.get("date")
    )
    if limit > 0:
        eligible_dates = eligible_dates[-limit:]

    snapshots: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for trade_date in eligible_dates:
        context = engine.freeze_world(
            trade_date,
            pool_size=pool_size,
            model_version=baseline_model,
            metadata_policy=metadata_policy,
        )
        if context.status != "ok":
            skipped.append({"trade_date": trade_date, "reason": context.status})
            continue

        baseline_result = await engine.rerun(
            context, horizon_days=horizon_days, record_run=False
        )
        candidate_context = engine.freeze_world(
            trade_date,
            pool_size=pool_size,
            model_version=candidate_model,
            metadata_policy=metadata_policy,
        )
        candidate_result = await engine.rerun(
            candidate_context, horizon_days=horizon_days, record_run=False
        )
        if baseline_result.status != "ok" or candidate_result.status != "ok":
            skipped.append({
                "trade_date": trade_date,
                "reason": "replay_result_incomplete",
            })
            continue

        baseline_rows = [_decision_row(row) for row in baseline_result.candidates]
        candidate_rows = [_decision_row(row) for row in candidate_result.candidates]
        all_rows = baseline_rows + candidate_rows
        if any(
            row["actionable"] and not row["outcome_available"] for row in all_rows
        ):
            skipped.append({
                "trade_date": trade_date,
                "reason": "incomplete_forward_labels",
            })
            continue

        snapshots.append({
            "trade_date": trade_date,
            "baseline": baseline_rows,
            "candidate": candidate_rows,
            "outcomes": {
                **_outcomes(baseline_rows),
                **_outcomes(candidate_rows),
            },
            "lookahead_safe": bool(
                context.lookahead_safe and candidate_context.lookahead_safe
            ),
        })

    return {
        "metadata": {
            "snapshot_type": "local_point_in_time_replay",
            "source": "decision_journal + market_daily",
            "baseline_model": baseline_model,
            "candidate_model": candidate_model,
            "horizon_days": horizon_days,
            "pool_size": pool_size,
            "metadata_policy": metadata_policy,
            "eligible_dates_before_label_filter": len(eligible_dates),
            "included_dates": len(snapshots),
            "skipped_dates": len(skipped),
            "skipped": skipped,
            "promotion_status": "pending_historical_gate",
            "network_used": False,
        },
        "snapshots": snapshots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build offline replay snapshots from local point-in-time data."
    )
    parser.add_argument("output_file", type=Path)
    parser.add_argument("--baseline-model", default="technical-v1")
    parser.add_argument("--candidate-model", default="balanced-v2")
    parser.add_argument("--horizon-days", type=int, default=5)
    parser.add_argument("--pool-size", type=int, default=200)
    parser.add_argument("--metadata-policy", choices=("auto", "ignore", "strict"), default="auto")
    parser.add_argument("--limit", type=int, default=0, help="Keep only the newest N eligible dates.")
    args = parser.parse_args()

    engine = ReplayEngine()
    choices = _model_choices(engine)
    invalid = [
        value for value in (args.baseline_model, args.candidate_model)
        if value not in choices
    ]
    if invalid:
        parser.error(f"unsupported model(s): {', '.join(invalid)}; choose from {', '.join(choices)}")

    payload = asyncio.run(build_snapshots(
        baseline_model=args.baseline_model,
        candidate_model=args.candidate_model,
        horizon_days=max(1, min(args.horizon_days, 20)),
        pool_size=max(1, min(args.pool_size, 500)),
        metadata_policy=args.metadata_policy,
        limit=max(0, args.limit),
    ))
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["metadata"], ensure_ascii=False, indent=2))
    return 0 if payload["metadata"]["included_dates"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
