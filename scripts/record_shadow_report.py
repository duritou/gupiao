"""Persist a same-day baseline/candidate shadow report locally."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ai_os.shadow_runner import (  # noqa: E402
    build_shadow_report,
    persist_shadow_report,
)


def _load_decisions(path: Path, trade_date: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared_date = ""
    if isinstance(payload, dict):
        declared_date = str(
            payload.get("trade_date") or payload.get("date") or ""
        ).strip()
        payload = payload.get("decisions") or payload.get("rows") or []
    if declared_date and declared_date != trade_date:
        raise ValueError(
            f"{path} declares trade_date={declared_date}, expected {trade_date}"
        )
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON list or decisions field")
    return [item for item in payload if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persist a same-day shadow comparison without executing trades."
    )
    parser.add_argument("trade_date")
    parser.add_argument("baseline_file", type=Path)
    parser.add_argument("candidate_file", type=Path)
    parser.add_argument("--baseline-version", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    baseline = _load_decisions(args.baseline_file, args.trade_date)
    candidate = _load_decisions(args.candidate_file, args.trade_date)
    report = build_shadow_report(
        args.trade_date,
        baseline,
        candidate,
        baseline_version=args.baseline_version,
        candidate_version=args.candidate_version,
        run_id=args.run_id,
    )
    replay_run_id = persist_shadow_report(report)
    print(json.dumps({
        "status": report["status"],
        "trade_date": report["trade_date"],
        "replay_run_id": replay_run_id,
        "changed_count": report["changed_count"],
        "paper_execution_enabled": report["paper_execution_enabled"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
